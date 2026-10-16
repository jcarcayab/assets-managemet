"""Make an account's ledger agree with the balances an institution reports.

Shared by every connection (Plaid, crypto exchanges). Providers only return part of the history, so:

1. an *opening* adjustment, dated just before the account's first known transaction, supplies the units the
   history doesn't explain (at the provider's average cost when known, else the current price);
2. a *fix* adjustment dated today absorbs anything still off (cash, splits, transfers without detail).

Both are recomputed from scratch on every sync, so they never pile up.
"""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from django.utils import timezone

from portfolio.models import Account, Asset, AssetClass, Transaction, TransactionKind
from portfolio.services.positions import cash_asset, compute_positions

EPS = Decimal("0.000001")


@dataclass
class Target:
    asset: Asset
    quantity: Decimal = Decimal(0)
    cost: Decimal | None = None  # total cost basis reported by the provider, if any
    price: Decimal = Decimal(0)  # current unit price per the provider (fallback for adjustments)


def ledger_positions(account: Account) -> dict:
    return {
        p.asset.id: p
        for p in compute_positions(account.owner, include_closed=True)
        if p.account.id == account.id and p.asset is not None
    }


def net_units(account: Account, asset: Asset, prefix: str) -> Decimal:
    """Units the recorded history adds to this account (ignoring splits): buys − sells ± transfers."""
    net = Decimal(0)
    history = Transaction.objects.filter(account=account, asset=asset).exclude(external_id__startswith=prefix)
    for kind, qty in history.values_list("kind", "quantity"):
        if kind in (TransactionKind.BUY, TransactionKind.STAKING):
            net += qty
        elif kind in (TransactionKind.SELL, TransactionKind.TRANSFER):
            net -= qty
    transfers_in = Transaction.objects.filter(to_account=account, asset=asset, kind=TransactionKind.TRANSFER)
    return net + sum(transfers_in.values_list("quantity", flat=True), Decimal(0))


def reconcile_account(
    account: Account, targets: dict[int, Target], *, prefix: str, source: str, cash_balance: Decimal | None = None
) -> int:
    """Adjust `account` so every asset's quantity equals its target. Returns the number of adjustments."""
    Transaction.objects.filter(account=account, external_id__startswith=prefix).delete()
    targets = dict(targets)
    if cash_balance is not None:
        cash = cash_asset(account.owner)
        targets.setdefault(cash.id, Target(cash, price=Decimal(1))).quantity += cash_balance
    for asset_id, p in ledger_positions(account).items():
        targets.setdefault(asset_id, Target(p.asset, price=p.price))  # held here before, gone now

    today = timezone.localdate()
    first_date = (
        Transaction.objects.filter(account=account)
        .exclude(external_id__startswith=prefix)
        .order_by("date")
        .values_list("date", flat=True)
        .first()
    )
    created = 0

    # 1) Opening balance for the units the available history doesn't explain.
    for t in targets.values():
        if t.asset.asset_class == AssetClass.CASH:
            continue
        opening = t.quantity - net_units(account, t.asset, prefix)
        if opening > EPS:
            unit = t.cost / t.quantity if t.cost is not None and t.quantity else t.price
            Transaction.objects.create(
                account=account, asset=t.asset, kind=TransactionKind.BUY,
                date=(first_date - dt.timedelta(days=1)) if first_date else today,
                quantity=opening, price=max(unit, Decimal(0)), external_id=f"{prefix}open:{t.asset.id}",
                notes=f"Saldo anterior al historial disponible en {source}"
                + (" (costo promedio reportado)." if t.cost is not None else " (valorado al precio actual)."),
            )
            created += 1

    # 2) Whatever still differs is fixed as of today.
    current = ledger_positions(account)
    for t in targets.values():
        have = current[t.asset.id].quantity if t.asset.id in current else Decimal(0)
        diff = t.quantity - have
        if abs(diff) <= EPS:
            continue
        fallback = current[t.asset.id].avg_cost if t.asset.id in current else Decimal(0)
        Transaction.objects.create(
            account=account, asset=t.asset, kind=TransactionKind.BUY if diff > 0 else TransactionKind.SELL,
            date=today, quantity=abs(diff), price=t.price or fallback, external_id=f"{prefix}fix:{t.asset.id}",
            notes=f"Ajuste de conciliación con {source} (cuadra con el saldo reportado).",
        )
        created += 1
    return created
