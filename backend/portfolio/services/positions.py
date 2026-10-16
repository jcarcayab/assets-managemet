"""Derive current holdings from the transaction ledger (average-cost method) and aggregate them."""

import datetime as dt
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field, replace
from decimal import Decimal

from django.db import connection
from django.db.models import Count, F, Max
from django.utils import timezone

from portfolio.models import (
    Account,
    AllocationTarget,
    Asset,
    AssetClass,
    CacheVersion,
    CashFlow,
    EquityGrant,
    GrantType,
    Liability,
    PriceSource,
    TaxTreatment,
    Transaction,
    TransactionKind,
    UserSettings,
)

ZERO = Decimal(0)
HUNDRED = Decimal(100)
DUST = Decimal("1e-8")


def pct(part: Decimal, whole: Decimal) -> Decimal | None:
    return (part / whole * HUNDRED) if whole else None


LONG_TERM_DAYS = 365


@dataclass
class Lot:
    """A tax lot: units acquired on one date at one unit cost (FIFO, the US broker default)."""

    date: dt.date
    quantity: Decimal
    unit_cost: Decimal

    def is_long_term(self, on: dt.date) -> bool:
        return (on - self.date).days > LONG_TERM_DAYS


def take_fifo(lots: list[Lot], quantity: Decimal) -> list[Lot]:
    """Remove `quantity` units from the oldest lots; return the removed pieces."""
    taken, remaining = [], quantity
    while remaining > 0 and lots:
        lot = lots[0]
        used = min(lot.quantity, remaining)
        taken.append(Lot(lot.date, used, lot.unit_cost))
        lot.quantity -= used
        remaining -= used
        if lot.quantity <= DUST:
            lots.pop(0)
    return taken


@dataclass
class Position:
    account: Account
    asset: Asset | None
    symbol: str
    name: str
    asset_class: str
    quantity: Decimal = ZERO
    cost_basis: Decimal = ZERO
    realized: Decimal = ZERO
    income: Decimal = ZERO
    fees_paid: Decimal = ZERO
    price: Decimal = ZERO
    target_pct: Decimal | None = None
    underlying: str = ""
    sector: str = ""
    exposures: dict = field(default_factory=dict)
    lots: list[Lot] = field(default_factory=list)
    # filled by finalize()/_apply_account_context()
    market_value: Decimal = ZERO
    unrealized: Decimal = ZERO
    weight_in_account: Decimal | None = None
    target_value: Decimal | None = None
    rebalance: Decimal | None = None
    extra: dict = field(default_factory=dict)

    @property
    def avg_cost(self) -> Decimal:
        return abs(self.cost_basis) / self.quantity if self.quantity else ZERO

    @property
    def unrealized_pct(self) -> Decimal | None:
        return pct(self.unrealized, abs(self.cost_basis))

    def finalize(self):
        sign = self.asset.sign if self.asset else 1
        self.market_value = sign * self.quantity * self.price
        self.cost_basis = sign * self.cost_basis
        self.unrealized = self.market_value - self.cost_basis


def cash_asset(user) -> Asset:
    asset, _ = Asset.objects.get_or_create(
        owner=user,
        symbol="USD",
        defaults={
            "name": "Dólar",
            "asset_class": AssetClass.CASH,
            "price_source": PriceSource.MANUAL,
            "manual_price": Decimal(1),
        },
    )
    return asset


class Ledger:
    """Replays transactions in date order, keeping a Position per (account, asset)."""

    def __init__(self, user, targets: dict | None = None):
        self.user = user
        self.targets = targets or {}
        self.positions: dict[tuple[int, int], Position] = {}
        self._cash: Asset | None = None

    def position(self, account: Account, asset: Asset) -> Position:
        key = (account.id, asset.id)
        pos = self.positions.get(key)
        if pos is None:
            pos = self.positions[key] = Position(
                account=account,
                asset=asset,
                symbol=asset.symbol,
                name=asset.name,
                asset_class=asset.asset_class,
                price=asset.price,
                target_pct=self.targets.get(key),
                underlying=asset.underlying,
                sector=asset.sector,
                exposures=asset.exposure_breakdown(),
            )
        return pos

    def cash(self, account: Account) -> Position:
        if self._cash is None:
            self._cash = cash_asset(self.user)
        return self.position(account, self._cash)

    def apply(self, tx: Transaction) -> None:
        pos = self.position(tx.account, tx.asset)
        kind = tx.kind
        if kind == TransactionKind.BUY:
            # Bought with the employer's match: free to you, so its whole value shows as gain.
            cost = ZERO if tx.employer_paid else tx.quantity * tx.price + tx.fees
            pos.quantity += tx.quantity
            pos.cost_basis += cost
            if tx.quantity:
                pos.lots.append(Lot(tx.date, tx.quantity, cost / tx.quantity))
        elif kind == TransactionKind.SELL:
            # Position cost uses the running average; tax lots are consumed FIFO.
            sold = min(tx.quantity, pos.quantity)
            avg = pos.avg_cost
            pos.cost_basis -= avg * sold
            pos.quantity -= sold
            pos.realized += sold * tx.price - tx.fees - avg * sold
            take_fifo(pos.lots, sold)
        elif kind == TransactionKind.STAKING:
            value = tx.quantity * tx.price
            pos.quantity += tx.quantity
            pos.cost_basis += value  # US tax basis = fair value at receipt
            pos.income += value
            pos.lots.append(Lot(tx.date, tx.quantity, tx.price))
        elif kind in (TransactionKind.DIVIDEND, TransactionKind.INTEREST):
            pos.income += tx.amount
            cash = self.cash(tx.account)
            cash.quantity += tx.amount
            cash.cost_basis += tx.amount
        elif kind == TransactionKind.FEE:
            pos.fees_paid += tx.amount
            cash = self.cash(tx.account)
            cash.quantity -= tx.amount
            cash.cost_basis -= tx.amount
        elif kind == TransactionKind.SPLIT:
            if tx.quantity:
                pos.quantity *= tx.quantity
                for lot in pos.lots:
                    lot.quantity *= tx.quantity
                    lot.unit_cost /= tx.quantity
        elif kind == TransactionKind.TRANSFER and tx.to_account_id:
            moved = min(tx.quantity, pos.quantity)
            moved_cost = pos.avg_cost * moved
            pos.quantity -= moved
            pos.cost_basis -= moved_cost
            dest = self.position(tx.to_account, tx.asset)
            dest.quantity += moved
            dest.cost_basis += moved_cost
            # Lots keep their original purchase dates (holding period carries over).
            dest.lots.extend(take_fifo(pos.lots, moved))
            dest.lots.sort(key=lambda lot: lot.date)
        if 0 <= pos.quantity < DUST and pos.asset_class != AssetClass.CASH:
            pos.quantity = ZERO
            pos.cost_basis = ZERO
            pos.lots.clear()


def ledger_transactions(user):
    return (
        Transaction.objects.filter(account__owner=user, account__archived=False)
        .select_related("account", "asset", "to_account")
        .order_by("date", "id")
    )


# -- cached ledger replay --------------------------------------------------------------------------
# Replaying every transaction is the slow part of computing positions (seconds with tens of thousands of
# synced trades), and it only changes when transactions or accounts do. The replayed quantities, costs and
# lots are cached per user; prices, asset and account details and targets are always read fresh.

LEDGER_VERSION = "ledger"
CACHE_TTL_SECONDS = 3600  # safety net for changes that bypass signals (e.g. QuerySet.update in a shell)
_replay_cache: dict[int, tuple[tuple, float, list["Position"]]] = {}
_replay_lock = threading.Lock()


def bump_ledger_version(**_) -> None:
    if not CacheVersion.objects.filter(name=LEDGER_VERSION).update(value=F("value") + 1):
        CacheVersion.objects.get_or_create(name=LEDGER_VERSION, defaults={"value": 1})


def ledger_version(user) -> tuple:
    """Changes whenever the replay could: the bump counter, plus row count and last id as a backstop."""
    counter = CacheVersion.objects.filter(name=LEDGER_VERSION).values_list("value", flat=True).first() or 0
    rows = Transaction.objects.filter(account__owner=user).aggregate(n=Count("id"), last=Max("id"))
    return counter, rows["n"], rows["last"]


def clear_replay_cache() -> None:
    with _replay_lock:
        _replay_cache.clear()


def _clone(p: "Position") -> "Position":
    return replace(
        p, lots=[Lot(lot.date, lot.quantity, lot.unit_cost) for lot in p.lots], exposures=dict(p.exposures),
        extra=dict(p.extra),
    )


def _replay(user) -> list["Position"]:
    ledger = Ledger(user)
    for tx in ledger_transactions(user):
        if tx.to_account_id and tx.to_account.archived:
            continue
        ledger.apply(tx)
    return list(ledger.positions.values())


def _refresh(user, positions: list["Position"]) -> list["Position"] | None:
    """Point cached positions at today's assets, accounts and targets. None if something they need is gone."""
    assets = {a.id: a for a in Asset.objects.filter(owner=user)}
    accounts = {a.id: a for a in Account.objects.filter(owner=user)}
    targets = {(t.account_id, t.asset_id): t.target_pct for t in AllocationTarget.objects.filter(account__owner=user)}
    for p in positions:
        asset, account = assets.get(p.asset.id), accounts.get(p.account.id)
        if asset is None or account is None:
            return None
        p.asset, p.account = asset, account
        p.symbol, p.name, p.asset_class, p.price = asset.symbol, asset.name, asset.asset_class, asset.price
        p.underlying, p.sector, p.exposures = asset.underlying, asset.sector, asset.exposure_breakdown()
        p.target_pct = targets.get((account.id, asset.id))
    return positions


def replayed_positions(user) -> list["Position"]:
    """Every (account, asset) position from the ledger, closed ones included; cached between requests.

    Inside a database transaction (syncs, reconciliation) the cache is skipped: rows written in that
    transaction aren't visible to the version check from other processes, and must always be counted."""
    if connection.in_atomic_block:
        return _refresh(user, _replay(user))
    key = ledger_version(user)
    with _replay_lock:
        hit = _replay_cache.get(user.pk)
    if hit and hit[0] == key and time.monotonic() - hit[1] < CACHE_TTL_SECONDS:
        refreshed = _refresh(user, [_clone(p) for p in hit[2]])
        if refreshed is not None:
            return refreshed
    positions = _replay(user)
    with _replay_lock:
        _replay_cache[user.pk] = (key, time.monotonic(), [_clone(p) for p in positions])
    return _refresh(user, positions)


def compute_positions(user, include_closed: bool = False) -> list[Position]:
    positions = [p for p in replayed_positions(user) if include_closed or p.quantity != 0]

    grants = EquityGrant.objects.filter(account__owner=user, account__archived=False)
    for grant in grants.select_related("account").prefetch_related("exercises"):
        vested = grant.vested_quantity()

        def grant_position(name, quantity, cost, price, is_option):
            return Position(
                account=grant.account,
                asset=None,
                symbol=grant.company,
                name=name,
                asset_class=AssetClass.PRIVATE_EQUITY,
                quantity=quantity,
                cost_basis=cost,
                price=price,
                underlying=grant.company,
                sector=grant.sector,
                exposures={"private_equity": HUNDRED},
                extra={
                    "equity_grant_id": grant.id,
                    "grant_type": grant.grant_type,
                    "is_option": is_option,
                    "strike": grant.strike,
                    "fmv": grant.fmv,
                    "unvested": grant.quantity - vested,
                },
            )

        if not grant.is_option:
            positions.append(
                grant_position(grant.get_grant_type_display(), vested, grant.cost_basis, grant.share_value, False)
            )
            continue
        # Options split in two: those still open (intrinsic value) and the shares already exercised (FMV).
        kind = grant.grant_type.upper()
        exercised = grant.exercised_quantity()
        if grant.open_options() or not exercised:
            positions.append(
                grant_position(f"Opciones {kind} sin ejercer", grant.open_options(), ZERO, grant.per_share_value, True)
            )
        if exercised:
            positions.append(
                grant_position(f"Acciones (opciones {kind} ejercidas)", exercised, grant.shares_cost_basis,
                               grant.share_value, False)
            )

    for p in positions:
        p.finalize()
    _apply_account_context(positions)
    positions.sort(key=lambda p: (p.account.name, -p.market_value))
    return positions


def _apply_account_context(positions: list[Position]) -> None:
    totals: dict[int, Decimal] = defaultdict(Decimal)
    for p in positions:
        totals[p.account.id] += p.market_value
    for p in positions:
        total = totals[p.account.id]
        p.weight_in_account = pct(p.market_value, total)
        if p.target_pct is not None:
            p.target_value = total * p.target_pct / HUNDRED
            p.rebalance = p.target_value - p.market_value


def lot_gains(p: Position, on: dt.date) -> tuple[Decimal, Decimal]:
    """(short-term, long-term) unrealized gain of a position's tax lots at its current price."""
    short = long = ZERO
    for lot in p.lots:
        gain = lot.quantity * (p.price - lot.unit_cost)
        if lot.is_long_term(on):
            long += gain
        else:
            short += gain
    return short, long


def estimated_tax(p: Position, s: UserSettings, on: dt.date | None = None) -> Decimal:
    """Tax owed if this position were turned into spendable cash today (rough, flat-rate estimate).

    Taxable accounts: FIFO lots held over a year pay the capital-gains rate, newer lots the ordinary rate.
    Tax-deferred accounts: the whole balance is taxed on withdrawal. Private options: NSO spread as ordinary
    income, ISO spread at capital-gains rates (assuming a qualifying disposition).
    """
    if p.asset_class == AssetClass.DEBT:
        return ZERO
    if p.asset is None:
        rate = s.ordinary_income_tax_pct if p.extra.get("grant_type") == GrantType.NSO and p.extra.get("is_option") else s.capital_gains_tax_pct
        return max(p.unrealized, ZERO) * rate / HUNDRED
    treatment = p.account.tax_treatment
    if treatment == TaxTreatment.TAX_DEFERRED:
        return max(p.market_value, ZERO) * s.retirement_tax_pct / HUNDRED
    if treatment == TaxTreatment.TAXABLE and p.asset_class != AssetClass.CASH:
        short, long = lot_gains(p, on or timezone.localdate())
        return (max(short, ZERO) * s.ordinary_income_tax_pct + max(long, ZERO) * s.capital_gains_tax_pct) / HUNDRED
    return ZERO


def income_since(user, since: dt.date) -> dict:
    out = {"dividend": ZERO, "interest": ZERO, "staking": ZERO, "fees": ZERO}
    txs = Transaction.objects.filter(account__owner=user, account__archived=False, date__gte=since).filter(
        kind__in=[TransactionKind.DIVIDEND, TransactionKind.INTEREST, TransactionKind.STAKING, TransactionKind.FEE]
    )
    for tx in txs:
        if tx.kind == TransactionKind.STAKING:
            out["staking"] += tx.quantity * tx.price
        elif tx.kind == TransactionKind.FEE:
            out["fees"] += tx.amount
        else:
            out[tx.kind] += tx.amount
    out["total"] = out["dividend"] + out["interest"] + out["staking"]
    return out


def _group(positions, key_fn, label_fn):
    groups: dict = {}
    for p in positions:
        k = key_fn(p)
        g = groups.setdefault(k, {"key": k, "label": label_fn(p), "cost": ZERO, "value": ZERO, "interest": ZERO})
        g["cost"] += p.cost_basis
        g["value"] += p.market_value
        if p.asset_class == AssetClass.CASH:
            # Interest paid in cash is already part of the cash's cost, so value - cost would hide it.
            g["interest"] += p.income
    return groups


def compute_summary(user, positions: list[Position] | None = None) -> dict:
    """`positions` lets callers that already computed them skip the (slow) ledger replay."""
    s = UserSettings.for_user(user)
    positions = compute_positions(user) if positions is None else positions
    assets_value = sum((p.market_value for p in positions), ZERO)
    liabilities = sum((lb.balance for lb in Liability.objects.filter(owner=user)), ZERO)
    net_worth = assets_value - liabilities
    cost = sum((p.cost_basis for p in positions), ZERO)
    private = sum((p.market_value for p in positions if p.asset_class == AssetClass.PRIVATE_EQUITY), ZERO)
    liquid = sum((p.market_value for p in positions if p.account.is_liquid), ZERO)

    def finish(groups: dict) -> list[dict]:
        rows = []
        for g in groups.values():
            g["gain"] = g["value"] - g["cost"] + g.get("interest", ZERO)
            g["gain_pct"] = pct(g["gain"], abs(g["cost"]))
            g["weight"] = pct(g["value"], assets_value)
            rows.append(g)
        return sorted(rows, key=lambda r: -r["value"])

    accounts = {a.id: a for a in Account.objects.filter(owner=user, archived=False)}
    by_account = _group(positions, lambda p: p.account.id, lambda p: p.account.name)
    # Accounts with no holdings still show up (e.g. an empty Roth IRA).
    for acc in accounts.values():
        g = by_account.setdefault(acc.id, {"key": acc.id, "label": acc.name, "cost": ZERO, "value": ZERO, "interest": ZERO})
        g.update(
            institution=acc.institution, account_type=acc.account_type, is_liquid=acc.is_liquid,
            tax_treatment=acc.tax_treatment,
        )

    labels = dict(AssetClass.choices)
    by_class = _group(positions, lambda p: p.asset_class, lambda p: labels.get(p.asset_class, p.asset_class))

    tax_labels = dict(TaxTreatment.choices)
    by_tax: dict[str, dict] = {}
    for p in positions:
        key = "private_equity" if p.asset is None else p.account.tax_treatment
        g = by_tax.setdefault(
            key, {"key": key, "label": tax_labels.get(key, "Equity privada"), "value": ZERO, "tax": ZERO}
        )
        g["value"] += p.market_value
        g["tax"] += estimated_tax(p, s)
    taxes = sum((g["tax"] for g in by_tax.values()), ZERO)
    for g in by_tax.values():
        g["after_tax"] = g["value"] - g["tax"]

    crypto_accounts = {a.id for a in accounts.values() if a.account_type == "crypto"}
    crypto_deposits = sum(
        (cf.amount for cf in CashFlow.objects.filter(account_id__in=crypto_accounts)), ZERO
    )
    crypto_value = sum((p.market_value for p in positions if p.account.id in crypto_accounts), ZERO)

    live_prices_at = [
        p.asset.last_price_at
        for p in positions
        if p.asset and p.asset.manual_price is None and p.asset.last_price_at
    ]

    return {
        "net_worth": net_worth,
        "net_worth_ex_private": net_worth - private,
        "after_tax_net_worth": net_worth - taxes,
        "estimated_taxes": taxes,
        "assets": assets_value,
        "liabilities": liabilities,
        "liquid": liquid,
        "illiquid": assets_value - liquid,
        "cost": cost,
        "unrealized": assets_value - cost,
        "unrealized_pct": pct(assets_value - cost, abs(cost)),
        "prices_as_of": min(live_prices_at) if live_prices_at else None,
        "income_12m": income_since(user, timezone.localdate() - dt.timedelta(days=365)),
        "by_account": finish(by_account),
        "by_class": finish(by_class),
        "by_tax_treatment": sorted(by_tax.values(), key=lambda r: -r["value"]),
        "crypto": {
            "deposits": crypto_deposits,
            "value": crypto_value,
            "gain": crypto_value - crypto_deposits,
            "gain_pct": pct(crypto_value - crypto_deposits, crypto_deposits),
        },
    }
