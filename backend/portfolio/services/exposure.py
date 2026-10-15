"""Look-through exposure: what the portfolio is really invested in, and where it is concentrated."""

from decimal import Decimal

from portfolio.models import AssetClass, ExposureCategory, UserSettings
from portfolio.services.positions import compute_positions, pct

ZERO = Decimal(0)
HUNDRED = Decimal(100)


def _rows(groups: dict[str, dict], total: Decimal) -> list[dict]:
    for g in groups.values():
        g["weight"] = pct(g["value"], total)
    return sorted(groups.values(), key=lambda r: -r["value"])


def compute_exposure(user) -> dict:
    limit = UserSettings.for_user(user).concentration_limit_pct
    # Weights are of gross assets (debt excluded) so a loan doesn't inflate every percentage.
    positions = [p for p in compute_positions(user) if p.asset_class != AssetClass.DEBT and p.market_value > 0]
    total = sum((p.market_value for p in positions), ZERO)

    labels = dict(ExposureCategory.choices)
    by_category: dict[str, dict] = {}
    by_holding: dict[str, dict] = {}
    by_sector: dict[str, dict] = {}
    for p in positions:
        for category, weight in (p.exposures or {"other": HUNDRED}).items():
            g = by_category.setdefault(category, {"key": category, "label": labels.get(category, category), "value": ZERO})
            g["value"] += p.market_value * weight / HUNDRED

        if p.asset_class != AssetClass.CASH:  # cash is not a concentration risk
            key = p.underlying or p.symbol
            h = by_holding.setdefault(key, {"key": key, "label": key, "value": ZERO, "via": []})
            h["value"] += p.market_value
            via = f"{p.symbol} ({p.account.name})"
            if via not in h["via"]:
                h["via"].append(via)

        if p.sector:
            sec = by_sector.setdefault(p.sector, {"key": p.sector, "label": p.sector, "value": ZERO, "via": []})
            sec["value"] += p.market_value
            if p.symbol not in sec["via"]:
                sec["via"].append(p.symbol)

    holdings = _rows(by_holding, total)
    sectors = _rows(by_sector, total)
    alerts = [
        {"kind": kind, "label": r["label"], "weight": r["weight"], "value": r["value"], "via": r["via"]}
        for kind, rows in (("holding", holdings), ("sector", sectors))
        for r in rows
        if r["weight"] is not None and r["weight"] > limit
    ]

    return {
        "gross_assets": total,
        "limit": limit,
        "by_category": _rows(by_category, total),
        "by_holding": holdings,
        "by_sector": sectors,
        "alerts": sorted(alerts, key=lambda a: -a["weight"]),
    }
