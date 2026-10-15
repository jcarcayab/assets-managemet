"""Household-level target allocation: drift by exposure category and where to rebalance with least tax."""

from decimal import Decimal

from portfolio.models import AssetClass, ExposureCategory, TaxTreatment, UserSettings
from portfolio.services.exposure import compute_exposure
from portfolio.services.positions import compute_positions, estimated_tax

ZERO = Decimal(0)
HUNDRED = Decimal(100)
NOT_TRADEABLE = {"private_equity"}


def compute_allocation(user) -> dict:
    s = UserSettings.for_user(user)
    target = {k: Decimal(str(v)) for k, v in (s.target_allocation or {}).items()}
    exposure = compute_exposure(user)
    total = exposure["gross_assets"]
    current = {r["key"]: r["value"] for r in exposure["by_category"]}
    labels = dict(ExposureCategory.choices)
    threshold = s.rebalance_threshold_pct

    rows = []
    for key in sorted(set(current) | set(target), key=lambda k: -current.get(k, ZERO)):
        value = current.get(key, ZERO)
        weight = value / total * HUNDRED if total else ZERO
        row = {
            "key": key,
            "label": labels.get(key, key),
            "value": value,
            "weight": weight,
            "target_pct": None,
            "target_value": None,
            "diff": None,
            "drift": None,
            "action": None,
            "tradeable": key not in NOT_TRADEABLE,
        }
        if target:
            tgt = target.get(key, ZERO)
            row.update(target_pct=tgt, target_value=total * tgt / HUNDRED)
            row["diff"] = row["target_value"] - value
            row["drift"] = weight - tgt
            if abs(row["drift"]) > threshold:
                # Illiquid categories can't be traded down; the rest of the portfolio has to adjust around them.
                row["action"] = "locked" if not row["tradeable"] else ("sell" if row["drift"] > 0 else "buy")
        rows.append(row)

    return {
        "total": total,
        "threshold": threshold,
        "has_target": bool(target),
        "rows": rows,
        "sells": _sell_plan(user, s, rows),
        "cash_available": _cash(user),
    }


def _sell_plan(user, s, rows) -> list[dict]:
    """For each overweight category, which holdings to trim first: tax-advantaged accounts (selling inside them
    is not a taxable event), then taxable holdings with the lowest embedded tax per dollar."""
    over = [r for r in rows if r["action"] == "sell" and r["tradeable"]]
    if not over:
        return []
    positions = [
        p for p in compute_positions(user)
        if p.asset is not None and p.asset_class not in (AssetClass.CASH, AssetClass.DEBT) and p.market_value > 0
    ]
    plans = []
    for row in over:
        candidates = []
        for p in positions:
            weight = p.exposures.get(row["key"], ZERO) / HUNDRED
            if not weight:
                continue
            taxable = p.account.tax_treatment == TaxTreatment.TAXABLE
            tax_rate = estimated_tax(p, s) / p.market_value if taxable else ZERO
            candidates.append((tax_rate, -p.market_value * weight, p, weight))
        candidates.sort(key=lambda c: (c[0], c[1]))

        needed = -row["diff"]
        items, remaining = [], needed
        for tax_rate, _, p, weight in candidates:
            if remaining <= 0:
                break
            # Selling $1 of a multi-asset fund only removes `weight` dollars from this category.
            sell = min(p.market_value, remaining / weight)
            items.append(
                {
                    "symbol": p.symbol,
                    "account": p.account.name,
                    "tax_treatment": p.account.tax_treatment,
                    "sell": sell,
                    "estimated_tax": sell * tax_rate,
                }
            )
            remaining -= sell * weight
        plans.append({"category": row["key"], "label": row["label"], "amount": needed, "items": items})
    return plans


def _cash(user) -> list[dict]:
    return [
        {"account": p.account.name, "value": p.market_value, "tax_treatment": p.account.tax_treatment}
        for p in compute_positions(user)
        if p.asset_class == AssetClass.CASH and p.market_value > 0
    ]
