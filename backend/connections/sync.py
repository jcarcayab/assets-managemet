"""Turn Plaid data into the portfolio ledger.

Plaid's investment transactions become ledger entries (idempotent by Plaid's transaction id). Plaid only
returns ~24 months of history, so after applying them each account is reconciled against the holdings the
institution reports:

1. an *opening* adjustment, dated just before the account's first known transaction, supplies the units the
   history doesn't explain (at the broker's average cost), so history and performance stay meaningful;
2. a *fix* adjustment dated today absorbs anything still off (cash, splits, transfers Plaid doesn't detail).

Both adjustments are recomputed from scratch on every sync, so they never pile up.
"""

import datetime as dt
from decimal import Decimal

from django.db import transaction as db_tx
from django.utils import timezone

from connections.models import PlaidAccount, PlaidItem
from connections.plaid import PlaidClient, PlaidError, get_client
from connections.reconcile import Target, reconcile_account
from portfolio.models import (
    Account,
    AccountType,
    Asset,
    AssetClass,
    CashFlow,
    CashFlowKind,
    PriceSource,
    TaxTreatment,
    Transaction,
    TransactionKind,
)
from portfolio.services.excel_import import COINGECKO_IDS
from portfolio.services.positions import cash_asset

HISTORY_DAYS = 730  # Plaid's investment history limit (24 months)
OVERLAP_DAYS = 30  # re-read recent days on each sync to catch late-posted transactions
TX_PREFIX = "plaid:"
ADJ_PREFIX = "plaid-adj:"

# Plaid account subtype -> (our account type, tax treatment override)
SUBTYPES = {
    "401k": (AccountType.K401, None),
    "401a": (AccountType.K401, None),
    "403b": (AccountType.K401, None),
    "457b": (AccountType.K401, None),
    "roth 401k": (AccountType.K401, TaxTreatment.TAX_FREE),
    "roth": (AccountType.ROTH_IRA, None),
    "ira": (AccountType.TRADITIONAL_IRA, None),
    "sep ira": (AccountType.TRADITIONAL_IRA, None),
    "simple ira": (AccountType.TRADITIONAL_IRA, None),
    "hsa": (AccountType.HSA, None),
    "brokerage": (AccountType.BROKERAGE, None),
    "crypto exchange": (AccountType.CRYPTO, None),
}
RETIREMENT = {AccountType.K401, AccountType.ROTH_IRA, AccountType.TRADITIONAL_IRA, AccountType.HSA}

DIVIDEND_SUBTYPES = {
    "dividend", "qualified dividend", "non-qualified dividend", "long-term capital gain", "short-term capital gain",
}
INTEREST_SUBTYPES = {"interest"}
DEPOSIT_SUBTYPES = {"deposit", "contribution"}
WITHDRAWAL_SUBTYPES = {"withdrawal", "distribution"}
FEE_SUBTYPES = {
    "account fee", "management fee", "fund fee", "miscellaneous fee", "legal fee", "transfer fee", "margin expense",
}


def _d(value) -> Decimal:
    return Decimal(str(value)) if value is not None else Decimal(0)


def account_kind(plaid_type: str, subtype: str) -> tuple[str, str | None]:
    if subtype in SUBTYPES:
        return SUBTYPES[subtype]
    if plaid_type == "depository":
        return AccountType.BANK, None
    if plaid_type == "investment":
        return AccountType.BROKERAGE, None
    return AccountType.OTHER, None


# -- items and accounts ----------------------------------------------------------------------------


def refresh_accounts(item: PlaidItem, accounts: list[dict]) -> None:
    for a in accounts:
        PlaidAccount.objects.update_or_create(
            plaid_account_id=a["account_id"],
            defaults={
                "item": item,
                "name": a.get("name") or a["account_id"],
                "official_name": a.get("official_name") or "",
                "mask": a.get("mask") or "",
                "type": a.get("type") or "",
                "subtype": a.get("subtype") or "",
                "current_balance": a.get("balances", {}).get("current"),
            },
        )


def link_item(user, public_token: str, client: PlaidClient | None = None) -> PlaidItem:
    client = client or get_client()
    access_token, item_id = client.exchange_public_token(public_token)
    institution_id = client.get_item(access_token).get("institution_id") or ""
    try:
        institution = client.institution_name(institution_id)
    except PlaidError:
        institution = ""
    item = PlaidItem(owner=user, item_id=item_id, institution_id=institution_id, institution_name=institution)
    item.access_token = access_token
    item.save()
    refresh_accounts(item, client.get_accounts(access_token))
    return item


def ensure_account(pa: PlaidAccount) -> Account | None:
    """The portfolio account mirroring this Plaid account, created on first sync unless one was chosen."""
    if not pa.enabled or pa.type not in ("investment", "depository"):
        return None
    if pa.account_id:
        return pa.account
    owner = pa.item.owner
    kind, tax = account_kind(pa.type, pa.subtype)
    base = f"{pa.item.institution_name or 'Plaid'} {pa.name}" + (f" ····{pa.mask}" if pa.mask else "")
    name, n = base[:95], 2
    while Account.objects.filter(owner=owner, name=name).exists():
        name, n = f"{base[:90]} ({n})", n + 1
    pa.account = Account.objects.create(
        owner=owner,
        name=name,
        institution=pa.item.institution_name,
        account_type=kind,
        is_liquid=kind not in RETIREMENT,
        tax_treatment=tax or "",
        notes="Sincronizada con Plaid.",
    )
    pa.save(update_fields=["account"])
    return pa.account


# -- securities ------------------------------------------------------------------------------------


def asset_for_security(owner, sec: dict | None) -> Asset:
    if sec is None or sec.get("is_cash_equivalent") or sec.get("type") == "cash":
        return cash_asset(owner)
    kind = sec.get("type") or ""
    ticker = (sec.get("ticker_symbol") or "").upper().removeprefix("CUR:")
    name = sec.get("name") or ticker
    if kind == "cryptocurrency":
        symbol = ticker or name.upper()
        defaults = {
            "name": name, "asset_class": AssetClass.CRYPTO, "price_source": PriceSource.COINGECKO,
            "source_id": COINGECKO_IDS.get(symbol, symbol.lower()), "sector": "Crypto",
        }
    elif kind == "derivative":
        # Options and the like: no usable live quote, so the institution's price is the source.
        symbol = (ticker or f"PLAID-{sec['security_id'][:8]}").upper()[:30]
        defaults = {
            "name": name, "asset_class": AssetClass.OTHER, "price_source": PriceSource.MANUAL,
            "manual_price": _d(sec.get("close_price")) or None,
        }
    elif ticker:
        symbol = ticker
        asset_class = AssetClass.BOND if kind == "fixed income" else AssetClass.STOCK
        defaults = {"name": name, "asset_class": asset_class, "price_source": PriceSource.YAHOO}
    else:
        # No public ticker (e.g. collective trusts in a 401k): price comes from the institution on each sync.
        symbol = f"PLAID-{sec['security_id'][:8].upper()}"
        asset_class = AssetClass.BOND if kind == "fixed income" else AssetClass.STOCK
        defaults = {
            "name": name, "asset_class": asset_class, "price_source": PriceSource.MANUAL,
            "manual_price": _d(sec.get("close_price")) or None,
        }
    asset, _ = Asset.objects.get_or_create(owner=owner, symbol=symbol, defaults=defaults)
    return asset


# -- transactions ----------------------------------------------------------------------------------


def apply_transaction(t: dict, account: Account, securities: dict) -> str | None:
    """Record one Plaid investment transaction. Returns 'tx', 'flow', 'dup' (already imported) or None (unsupported)."""
    ext = f"{TX_PREFIX}{t['investment_transaction_id']}"
    if (
        Transaction.objects.filter(account=account, external_id=ext).exists()
        or CashFlow.objects.filter(account=account, external_id=ext).exists()
    ):
        return "dup"

    owner = account.owner
    kind, subtype = t.get("type") or "", (t.get("subtype") or "").lower()
    sec = securities.get(t.get("security_id"))
    date = dt.date.fromisoformat(t["date"])
    qty, amount, fees = abs(_d(t.get("quantity"))), abs(_d(t.get("amount"))), abs(_d(t.get("fees")))
    price = abs(_d(t.get("price"))) or (amount / qty if qty else Decimal(0))
    notes = (t.get("name") or "")[:200]

    def ledger(tx_kind, asset, **fields):
        Transaction.objects.create(
            account=account, kind=tx_kind, asset=asset, date=date, external_id=ext, notes=notes, **fields
        )
        return "tx"

    if kind == "buy" and qty:
        return ledger(TransactionKind.BUY, asset_for_security(owner, sec), quantity=qty, price=price, fees=fees)
    if kind == "sell" and qty:
        return ledger(TransactionKind.SELL, asset_for_security(owner, sec), quantity=qty, price=price, fees=fees)
    if (kind == "fee" or subtype in FEE_SUBTYPES) and amount:
        return ledger(TransactionKind.FEE, asset_for_security(owner, sec), amount=amount)
    if kind == "cash" and amount:
        if subtype in DIVIDEND_SUBTYPES:
            return ledger(TransactionKind.DIVIDEND, asset_for_security(owner, sec), amount=amount)
        if subtype in INTEREST_SUBTYPES:
            return ledger(TransactionKind.INTEREST, asset_for_security(owner, sec), amount=amount)
        if subtype in DEPOSIT_SUBTYPES | WITHDRAWAL_SUBTYPES:
            flow = CashFlowKind.WITHDRAWAL if subtype in WITHDRAWAL_SUBTYPES else CashFlowKind.DEPOSIT
            CashFlow.objects.create(account=account, kind=flow, date=date, amount=amount, external_id=ext, notes=notes)
            return "flow"
    return None  # transfers, cancellations, options… are covered by reconciliation


# -- reconciliation --------------------------------------------------------------------------------


def reconcile(account: Account, holdings: list[dict], securities: dict, cash_balance: Decimal | None = None) -> int:
    """Make the ledger's quantities in `account` equal to the holdings Plaid reports."""
    owner = account.owner
    targets: dict[int, Target] = {}
    for h in holdings:
        asset = asset_for_security(owner, securities.get(h.get("security_id")))
        is_cash = asset.asset_class == AssetClass.CASH
        price = _d(h.get("institution_price")) or (Decimal(1) if is_cash else Decimal(0))
        target = targets.setdefault(asset.id, Target(asset, price=price))
        target.quantity += _d(h.get("quantity"))
        if h.get("cost_basis") is not None:
            target.cost = (target.cost or Decimal(0)) + _d(h["cost_basis"])
        if asset.price_source == PriceSource.MANUAL and not is_cash and price:
            asset.manual_price = price
            asset.save(update_fields=["manual_price"])
        elif not is_cash and price and asset.manual_price is None and asset.last_price is None:
            # Live-priced asset not quoted yet (or unknown to Yahoo): use the institution's price until it is.
            asset.last_price = price
            asset.save(update_fields=["last_price"])
    return reconcile_account(account, targets, prefix=ADJ_PREFIX, source="Plaid", cash_balance=cash_balance)


# -- sync ------------------------------------------------------------------------------------------

NO_INVESTMENTS = {"PRODUCTS_NOT_SUPPORTED", "NO_INVESTMENT_ACCOUNTS", "PRODUCT_NOT_READY"}
REAUTH = {"ITEM_LOGIN_REQUIRED", "PENDING_EXPIRATION", "ACCESS_NOT_GRANTED"}


def sync_item(item: PlaidItem, client: PlaidClient | None = None) -> dict:
    client = client or get_client()
    report = {"accounts": 0, "transactions": 0, "cash_flows": 0, "adjustments": 0, "skipped": 0, "error": None}
    token = item.access_token
    today = timezone.localdate()
    try:
        accounts = client.get_accounts(token)
        refresh_accounts(item, accounts)
        balances = {a["account_id"]: a.get("balances", {}) for a in accounts}

        try:
            holdings = client.get_holdings(token)
        except PlaidError as exc:
            if exc.code not in NO_INVESTMENTS:
                raise
            holdings = None
        txs = {"investment_transactions": [], "securities": []}
        if holdings is not None:
            start = (
                item.last_synced_at.date() - dt.timedelta(days=OVERLAP_DAYS)
                if item.last_synced_at
                else today - dt.timedelta(days=HISTORY_DAYS)
            )
            txs = client.get_investment_transactions(token, start, today)
        securities = {s["security_id"]: s for s in (holdings or {}).get("securities", []) + txs["securities"]}

        with db_tx.atomic():
            mapped: dict[str, tuple[PlaidAccount, Account]] = {}
            for pa in item.accounts.select_related("item", "account"):
                account = ensure_account(pa)
                if account is not None:
                    mapped[pa.plaid_account_id] = (pa, account)
            report["accounts"] = len(mapped)

            for t in sorted(txs["investment_transactions"], key=lambda t: t["date"]):
                target = mapped.get(t["account_id"])
                if target is None:
                    continue
                result = apply_transaction(t, target[1], securities)
                if result in ("tx", "flow"):
                    report["transactions" if result == "tx" else "cash_flows"] += 1
                elif result is None:
                    report["skipped"] += 1

            for plaid_id, (pa, account) in mapped.items():
                if pa.type == "investment" and holdings is not None:
                    rows = [h for h in holdings["holdings"] if h["account_id"] == plaid_id]
                    report["adjustments"] += reconcile(account, rows, securities)
                elif pa.type == "depository":
                    current = balances.get(plaid_id, {}).get("current")
                    if current is not None:
                        report["adjustments"] += reconcile(account, [], securities, cash_balance=_d(current))

            item.last_synced_at = timezone.now()
            item.last_error = ""
            item.needs_reauth = False
            item.save(update_fields=["last_synced_at", "last_error", "needs_reauth"])
    except PlaidError as exc:
        item.last_error = f"{exc.code}: {exc.message}"[:300]
        item.needs_reauth = exc.code in REAUTH
        item.save(update_fields=["last_error", "needs_reauth"])
        report["error"] = {"code": exc.code, "message": exc.message, "needs_reauth": item.needs_reauth}
    return report
