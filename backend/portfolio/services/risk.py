"""Risk metrics: volatility, drawdown, correlations between holdings and stress-test scenarios."""

import datetime as dt
import math
from decimal import Decimal

from django.utils import timezone

from portfolio.models import AssetClass
from portfolio.services.history import load_history
from portfolio.services.performance import daily_series, twr_index
from portfolio.services.positions import compute_positions

ZERO = Decimal(0)
WINDOW_DAYS = 365
MAX_CORRELATED = 8

# Hypothetical shocks in % by exposure category. `sectors` add a shock for positions tagged with that sector
# (e.g. a crypto company's equity falls with crypto); the more severe of the two applies.
# Rough historical analogues, not forecasts.
SCENARIOS = [
    {
        "key": "crypto_winter",
        "label": "Invierno crypto",
        "description": "Crypto −65% (como 2022); empresas del sector −50%.",
        "categories": {"crypto": -65},
        "sectors": {"Crypto": -50},
    },
    {
        "key": "recession",
        "label": "Recesión",
        "description": "Acciones −30%, crypto −50%, equity privada −40%; bonos y oro suben un poco.",
        "categories": {
            "us_equity": -30, "intl_equity": -30, "crypto": -50, "private_equity": -40, "bonds": 5,
            "commodities": 10, "real_estate": -20,
        },
        "sectors": {"Crypto": -55},
    },
    {
        "key": "gfc",
        "label": "Crisis tipo 2008",
        "description": "Acciones −50%, internacional −55%, inmobiliario −35%, crypto −75%.",
        "categories": {
            "us_equity": -50, "intl_equity": -55, "crypto": -75, "private_equity": -60, "bonds": 5,
            "commodities": 5, "real_estate": -35,
        },
        "sectors": {"Crypto": -70},
    },
    {
        "key": "rates",
        "label": "Inflación y tasas altas",
        "description": "Bonos −15%, acciones −20%, crypto −40%, metales +20% (como 2022).",
        "categories": {
            "us_equity": -20, "intl_equity": -20, "bonds": -15, "crypto": -40, "private_equity": -25,
            "commodities": 20, "real_estate": -15,
        },
        "sectors": {"Crypto": -45},
    },
]


def _stdev(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    mean = sum(xs) / len(xs)
    return math.sqrt(sum((x - mean) ** 2 for x in xs) / (len(xs) - 1))


def _correlation(a: list[float], b: list[float]) -> float | None:
    sa, sb = _stdev(a), _stdev(b)
    if len(a) < 10 or not sa or not sb:
        return None
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (len(a) - 1)
    return cov / (sa * sb)


def portfolio_metrics(user) -> dict:
    days = daily_series(user)
    if len(days) < 3:
        return {"volatility": None, "max_drawdown": None, "current_drawdown": None, "window_days": 0}
    index = twr_index(days)
    window = index[max(0, len(index) - WINDOW_DAYS - 1):]
    # Calendar-day returns (weekends are flat for stocks), annualized with 365 to match.
    returns = [window[i] / window[i - 1] - 1 for i in range(1, len(window)) if window[i - 1]]
    peak, max_dd = window[0], 0.0
    for level in window:
        peak = max(peak, level)
        if peak:
            max_dd = max(max_dd, 1 - level / peak)
    top = max(window)
    recent = sum(float(d.flow) for d in days[-7:] if d.flow > 0)
    return {
        # Same signal as performance: most value contributed this week means history is mostly missing.
        "recent_contribution_share": recent / float(days[-1].value) * 100 if days[-1].value else 0.0,
        "window_days": len(window) - 1,
        "volatility": _stdev(returns) * math.sqrt(365) * 100,
        "max_drawdown": max_dd * 100,
        "current_drawdown": (1 - window[-1] / top) * 100 if top else None,
    }


def holding_risk(positions) -> dict:
    """Volatility of the largest holdings and pairwise correlations of their daily returns over the last year."""
    by_symbol: dict[str, dict] = {}
    for p in positions:
        if p.asset is None or not p.asset.history_symbol or p.market_value <= 0:
            continue
        row = by_symbol.setdefault(p.asset.history_symbol, {"symbol": p.symbol, "history": p.asset.history_symbol, "value": ZERO})
        row["value"] += p.market_value
    top = sorted(by_symbol.values(), key=lambda r: -r["value"])[:MAX_CORRELATED]
    since = timezone.localdate() - dt.timedelta(days=WINDOW_DAYS)
    history = load_history([r["history"] for r in top])

    returns: dict[str, dict[dt.date, float]] = {}
    for r in top:
        points = [(d, float(c)) for d, c in history.get(r["history"], []) if d >= since]
        rets = {points[i][0]: points[i][1] / points[i - 1][1] - 1 for i in range(1, len(points)) if points[i - 1][1]}
        returns[r["symbol"]] = rets
        per_year = len(rets) * 365 / WINDOW_DAYS  # ~252 for stocks, ~365 for crypto
        r["volatility"] = _stdev(list(rets.values())) * math.sqrt(per_year) * 100 if len(rets) > 10 else None

    symbols = [r["symbol"] for r in top]
    matrix = []
    for a in symbols:
        row = []
        for b in symbols:
            if a == b:
                row.append(1.0)
                continue
            common = sorted(set(returns[a]) & set(returns[b]))
            row.append(_correlation([returns[a][d] for d in common], [returns[b][d] for d in common]))
        matrix.append(row)
    assets = [{"symbol": r["symbol"], "value": r["value"], "volatility": r["volatility"]} for r in top]
    return {"assets": assets, "symbols": symbols, "matrix": matrix}


def stress_test(positions, scenario: dict) -> dict:
    categories = {k: Decimal(str(v)) for k, v in scenario.get("categories", {}).items()}
    sectors = {k: Decimal(str(v)) for k, v in scenario.get("sectors", {}).items()}
    net_worth = sum((p.market_value for p in positions), ZERO)
    change, liquid_change, impacts = ZERO, ZERO, {}
    for p in positions:
        if p.asset_class == AssetClass.DEBT or p.market_value <= 0:
            continue
        shock = sum((w * categories.get(cat, ZERO) / 100 for cat, w in p.exposures.items()), ZERO)
        if p.sector in sectors:
            shock = min(shock, sectors[p.sector])
        delta = p.market_value * shock / 100
        change += delta
        if p.account.is_liquid:
            liquid_change += delta
        key = p.underlying or p.symbol
        impacts[key] = impacts.get(key, ZERO) + delta
    worst = sorted(((k, v) for k, v in impacts.items() if v < 0), key=lambda kv: kv[1])[:3]
    return {
        "key": scenario.get("key", "custom"),
        "label": scenario.get("label", "Personalizado"),
        "description": scenario.get("description", ""),
        "change": change,
        "change_pct": change / net_worth * 100 if net_worth else None,
        "net_worth_after": net_worth + change,
        "liquid_change": liquid_change,
        "worst": [{"label": k, "change": v} for k, v in worst],
    }


def parse_custom(raw: str | None) -> dict | None:
    """'crypto:-50,us_equity:-20,sector.Crypto:-60' → scenario dict."""
    if not raw:
        return None
    categories, sectors = {}, {}
    for part in raw.split(","):
        key, _, value = part.partition(":")
        try:
            pct = max(-100.0, min(float(value), 1000.0))
        except ValueError:
            continue
        key = key.strip()
        if key.startswith("sector."):
            sectors[key[len("sector."):]] = pct
        elif key:
            categories[key] = pct
    return {"key": "custom", "label": "Personalizado", "categories": categories, "sectors": sectors}


def compute_risk(user, custom: str | None = None) -> dict:
    positions = compute_positions(user)
    scenarios = list(SCENARIOS)
    extra = parse_custom(custom)
    if extra:
        scenarios.append(extra)
    return {
        "portfolio": portfolio_metrics(user),
        "holdings": holding_risk(positions),
        "scenarios": [stress_test(positions, sc) for sc in scenarios],
    }
