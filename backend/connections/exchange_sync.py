"""Mirror a crypto exchange into one portfolio account: trades, staking rewards and USD deposits become
ledger entries (idempotent by the exchange's ids); then the account is reconciled with the reported balances.

Crypto moved between your own wallets/exchanges arrives without its original cost; those units are covered
by reconciliation at the current price.
"""

import logging
from decimal import Decimal

from django.db import transaction as db_tx
from django.utils import timezone

from connections.coinbase import CoinbaseClient
from connections.exchange_data import CASH_SYMBOLS, ExchangeError, Snapshot
from connections.kraken import KrakenClient
from connections.models import ExchangeConnection, ExchangeProvider
from connections.reconcile import Target, reconcile_account
from portfolio.models import (
    Account,
    AccountType,
    Asset,
    AssetClass,
    CashFlow,
    CashFlowKind,
    PriceHistory,
    PriceSource,
    Transaction,
    TransactionKind,
)
from portfolio.services.excel_import import COINGECKO_IDS
from portfolio.services.history import update_history
from portfolio.services.positions import cash_asset
from portfolio.services.prices import refresh_prices

log = logging.getLogger(__name__)
ADJ_PREFIX = "exchange-adj:"


def client_for(conn: ExchangeConnection):
    if conn.provider == ExchangeProvider.KRAKEN:
        return KrakenClient(conn.api_key, conn.api_secret)
    return CoinbaseClient(conn.api_key, conn.api_secret)


def ensure_account(conn: ExchangeConnection) -> Account:
    if conn.account_id:
        return conn.account
    base = conn.label or conn.get_provider_display()
    name, n = base, 2
    while Account.objects.filter(owner=conn.owner, name=name).exists():
        name, n = f"{base} ({n})", n + 1
    conn.account = Account.objects.create(
        owner=conn.owner, name=name, institution=conn.get_provider_display(), account_type=AccountType.CRYPTO,
        is_liquid=True, notes=f"Sincronizada con {conn.get_provider_display()} (API de solo lectura).",
    )
    conn.save(update_fields=["account"])
    return conn.account


def crypto_asset(owner, symbol: str) -> Asset:
    if symbol in CASH_SYMBOLS:
        return cash_asset(owner)
    if symbol in COINGECKO_IDS:
        defaults = {"price_source": PriceSource.COINGECKO, "source_id": COINGECKO_IDS[symbol]}
    else:
        defaults = {"price_source": PriceSource.YAHOO, "source_id": f"{symbol}-USD"}
    asset, _ = Asset.objects.get_or_create(
        owner=owner, symbol=symbol,
        defaults={"name": symbol, "asset_class": AssetClass.CRYPTO, "sector": "Crypto", **defaults},
    )
    return asset


def price_on(asset: Asset, date) -> Decimal | None:
    """Daily close on (or before) `date`, from the stored price history."""
    if not asset.history_symbol:
        return None
    row = PriceHistory.objects.filter(symbol=asset.history_symbol, date__lte=date).order_by("-date").first()
    return row.close if row else None


def _exists(account, ext_id) -> bool:
    return (
        Transaction.objects.filter(account=account, external_id=ext_id).exists()
        or CashFlow.objects.filter(account=account, external_id=ext_id).exists()
    )


def apply_snapshot(conn: ExchangeConnection, snap: Snapshot) -> dict:
    report = {"trades": 0, "rewards": 0, "cash_flows": 0, "adjustments": 0, "skipped": snap.skipped}
    owner = conn.owner
    account = ensure_account(conn)
    symbols = set(snap.balances) | {t.symbol for t in snap.trades} | {r.symbol for r in snap.rewards}
    assets = {s: crypto_asset(owner, s) for s in symbols}

    # New coins need a live price (for reconciliation) and history (to value rewards) before we use them.
    live = [a for a in assets.values() if a.asset_class != AssetClass.CASH]
    try:
        refresh_prices([a for a in live if a.last_price is None])
        if snap.rewards:
            update_history(owner)
    except Exception as exc:  # pricing is best-effort; balances still reconcile
        log.warning("Price refresh during exchange sync failed: %s", exc)
    for a in live:
        a.refresh_from_db()

    with db_tx.atomic():
        for t in sorted(snap.trades, key=lambda t: t.date):
            if _exists(account, t.ext_id):
                continue
            Transaction.objects.create(
                account=account, asset=assets[t.symbol], date=t.date, external_id=t.ext_id,
                kind=TransactionKind.BUY if t.side == "buy" else TransactionKind.SELL,
                quantity=t.quantity, price=t.price, fees=t.fee,
            )
            report["trades"] += 1

        for r in snap.rewards:
            if _exists(account, r.ext_id):
                continue
            asset = assets[r.symbol]
            price = r.value / r.quantity if r.value is not None and r.quantity else price_on(asset, r.date)
            Transaction.objects.create(
                account=account, asset=asset, date=r.date, external_id=r.ext_id, kind=TransactionKind.STAKING,
                quantity=r.quantity, price=price or Decimal(0),
                notes="" if price else "Precio del día desconocido: recompensa registrada a costo 0.",
            )
            report["rewards"] += 1

        for c in snap.cash_moves:
            if _exists(account, c.ext_id):
                continue
            kind = CashFlowKind.WITHDRAWAL if c.kind == "withdrawal" else CashFlowKind.DEPOSIT
            CashFlow.objects.create(account=account, date=c.date, amount=c.amount, kind=kind, external_id=c.ext_id)
            report["cash_flows"] += 1

        targets = {
            assets[s].id: Target(assets[s], quantity=qty, price=assets[s].price)
            for s, qty in snap.balances.items()
            if s != "USD"
        }
        report["adjustments"] = reconcile_account(
            account, targets, prefix=ADJ_PREFIX, source=conn.get_provider_display(),
            cash_balance=snap.balances.get("USD", Decimal(0)),
        )
    return report


def sync_exchange(conn: ExchangeConnection, client=None) -> dict:
    client = client or client_for(conn)
    try:
        report = apply_snapshot(conn, client.snapshot())
        conn.last_synced_at, conn.last_error = timezone.now(), ""
        report["error"] = None
    except ExchangeError as exc:
        conn.last_error = str(exc)[:300]
        report = {"trades": 0, "rewards": 0, "cash_flows": 0, "adjustments": 0, "skipped": 0, "error": str(exc)}
    conn.save(update_fields=["last_synced_at", "last_error"])
    return report
