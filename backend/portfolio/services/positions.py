"""Derive current holdings from the transaction ledger (average-cost method) and aggregate them."""

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from portfolio.models import (
    Account,
    AllocationTarget,
    Asset,
    AssetClass,
    CashFlow,
    EquityGrant,
    Transaction,
    TransactionKind,
    UserSettings,
)

ZERO = Decimal(0)
HUNDRED = Decimal(100)
DUST = Decimal("1e-8")


def pct(part: Decimal, whole: Decimal) -> Decimal | None:
    return (part / whole * HUNDRED) if whole else None


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
    price: Decimal = ZERO
    target_pct: Decimal | None = None
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


def apply_trade(pos: Position, tx: Transaction) -> None:
    if tx.kind == TransactionKind.BUY:
        pos.quantity += tx.quantity
        pos.cost_basis += tx.quantity * tx.price + tx.fees
        return
    # SELL: remove cost at the running average, book the difference as realized P/L.
    sold = min(tx.quantity, pos.quantity)
    avg = pos.avg_cost
    pos.cost_basis -= avg * sold
    pos.quantity -= sold
    pos.realized += sold * tx.price - tx.fees - avg * sold
    if pos.quantity < DUST:
        pos.quantity = ZERO
        pos.cost_basis = ZERO


def compute_positions(user, include_closed: bool = False) -> list[Position]:
    txs = (
        Transaction.objects.filter(account__owner=user, account__archived=False)
        .select_related("account", "asset")
        .order_by("date", "id")
    )
    targets = {
        (t.account_id, t.asset_id): t.target_pct
        for t in AllocationTarget.objects.filter(account__owner=user)
    }

    by_key: dict[tuple[int, int], Position] = {}
    for tx in txs:
        key = (tx.account_id, tx.asset_id)
        pos = by_key.get(key)
        if pos is None:
            pos = by_key[key] = Position(
                account=tx.account,
                asset=tx.asset,
                symbol=tx.asset.symbol,
                name=tx.asset.name,
                asset_class=tx.asset.asset_class,
                price=tx.asset.price,
                target_pct=targets.get(key),
            )
        apply_trade(pos, tx)

    positions = [p for p in by_key.values() if include_closed or p.quantity > 0]

    for grant in EquityGrant.objects.filter(account__owner=user, account__archived=False).select_related("account"):
        positions.append(
            Position(
                account=grant.account,
                asset=None,
                symbol=grant.company,
                name=f"Opciones {grant.company}" + ("" if grant.exercised else " (sin ejercer)"),
                asset_class=AssetClass.PRIVATE_EQUITY,
                quantity=grant.quantity,
                cost_basis=grant.cost_basis,
                price=grant.market_value / grant.quantity if grant.quantity else ZERO,
                extra={"equity_grant_id": grant.id, "strike": grant.strike, "fmv": grant.fmv},
            )
        )

    for p in positions:
        p.finalize()
    _apply_account_context(positions)
    _apply_trade_levels(user, positions)
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


def _apply_trade_levels(user, positions: list[Position]) -> None:
    """Take-profit / stop-loss price levels for crypto, from the user's percentages."""
    s = UserSettings.for_user(user)
    for p in positions:
        if p.asset_class != AssetClass.CRYPTO or not p.quantity:
            continue
        avg = p.avg_cost
        p.extra["tp1_price"] = avg * (1 + s.take_profit_1_pct / HUNDRED)
        p.extra["tp2_price"] = avg * (1 + s.take_profit_2_pct / HUNDRED)
        p.extra["sl_price"] = avg * (1 + s.stop_loss_pct / HUNDRED)


def _group(positions, key_fn, label_fn):
    groups: dict = {}
    for p in positions:
        k = key_fn(p)
        g = groups.setdefault(k, {"key": k, "label": label_fn(p), "cost": ZERO, "value": ZERO})
        g["cost"] += p.cost_basis
        g["value"] += p.market_value
    return groups


def compute_summary(user) -> dict:
    positions = compute_positions(user)
    net_worth = sum((p.market_value for p in positions), ZERO)
    cost = sum((p.cost_basis for p in positions), ZERO)
    private = sum((p.market_value for p in positions if p.asset_class == AssetClass.PRIVATE_EQUITY), ZERO)
    liquid = sum((p.market_value for p in positions if p.account.is_liquid), ZERO)

    def finish(groups: dict) -> list[dict]:
        rows = []
        for g in groups.values():
            g["gain"] = g["value"] - g["cost"]
            g["gain_pct"] = pct(g["gain"], abs(g["cost"]))
            g["weight"] = pct(g["value"], net_worth)
            rows.append(g)
        return sorted(rows, key=lambda r: -r["value"])

    accounts = {a.id: a for a in Account.objects.filter(owner=user, archived=False)}
    by_account = _group(positions, lambda p: p.account.id, lambda p: p.account.name)
    # Accounts with no holdings still show up (e.g. an empty Roth IRA).
    for acc in accounts.values():
        g = by_account.setdefault(acc.id, {"key": acc.id, "label": acc.name, "cost": ZERO, "value": ZERO})
        g.update(institution=acc.institution, account_type=acc.account_type, is_liquid=acc.is_liquid)

    labels = dict(AssetClass.choices)
    by_class = _group(positions, lambda p: p.asset_class, lambda p: labels.get(p.asset_class, p.asset_class))

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
        "liquid": liquid,
        "illiquid": net_worth - liquid,
        "cost": cost,
        "unrealized": net_worth - cost,
        "unrealized_pct": pct(net_worth - cost, abs(cost)),
        "prices_as_of": min(live_prices_at) if live_prices_at else None,
        "by_account": finish(by_account),
        "by_class": finish(by_class),
        "crypto": {
            "deposits": crypto_deposits,
            "value": crypto_value,
            "gain": crypto_value - crypto_deposits,
            "gain_pct": pct(crypto_value - crypto_deposits, crypto_deposits),
        },
    }
