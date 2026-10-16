"""Planning: household budget and emergency fund, debts, and a Monte Carlo retirement projection."""

import datetime as dt
import math
import random
from decimal import Decimal

from django.utils import timezone

from portfolio.models import (
    AccountType,
    AssetClass,
    BudgetItem,
    BudgetKind,
    CashFlow,
    CashFlowKind,
    Liability,
    TaxTreatment,
    UserSettings,
    add_months,
)
from portfolio.services.positions import compute_positions, compute_summary, pct

ZERO = Decimal(0)
HUNDRED = Decimal(100)


# -- budget ----------------------------------------------------------------------------------------


def compute_budget(user) -> dict:
    s = UserSettings.for_user(user)
    items = list(BudgetItem.objects.filter(owner=user))
    income = sum((i.monthly for i in items if i.kind == BudgetKind.INCOME), ZERO)
    expenses = sum((i.monthly for i in items if i.kind == BudgetKind.EXPENSE), ZERO)
    essential = sum((i.monthly for i in items if i.kind == BudgetKind.EXPENSE and i.essential), ZERO)

    by_category: dict[str, Decimal] = {}
    for i in items:
        if i.kind == BudgetKind.EXPENSE:
            key = i.category or "Sin categoría"
            by_category[key] = by_category.get(key, ZERO) + i.monthly

    # Emergency fund = cash in accessible accounts (not investments that can fall exactly when you need them).
    cash = sum(
        (p.market_value for p in compute_positions(user) if p.asset_class == AssetClass.CASH and p.account.is_liquid),
        ZERO,
    )
    target = essential * s.emergency_fund_months
    return {
        "monthly_income": income,
        "monthly_expenses": expenses,
        "monthly_essential": essential,
        "monthly_savings": income - expenses,
        "savings_rate": pct(income - expenses, income),
        "annual_expenses": expenses * 12,
        "emergency_cash": cash,
        "emergency_months": cash / essential if essential else None,
        "emergency_target_months": s.emergency_fund_months,
        "emergency_target": target,
        "emergency_gap": max(target - cash, ZERO),
        "by_category": [
            {"label": k, "monthly": v, "share": pct(v, expenses)}
            for k, v in sorted(by_category.items(), key=lambda kv: -kv[1])
        ],
    }


# -- debts -----------------------------------------------------------------------------------------


MAX_MONTHS = 600


def payoff_schedule(
    balance: Decimal, payment: Decimal, regular_rate_pct: Decimal, *, promo_rate_pct: Decimal | None = None,
    promo_months: int = 0, deferred_interest: bool = False, max_months: int = MAX_MONTHS,
) -> tuple[int | None, float]:
    """Simulate fixed monthly payments. The first `promo_months` months accrue at the promo rate; with deferred
    interest, if a balance is left when the promo ends, the interest the regular rate would have charged during
    the promo is added at once. Returns (months to pay off, or None if not within `max_months`; interest paid)."""
    b, p = float(balance), float(payment)
    if b <= 0:
        return 0, 0.0
    if p <= 0:
        return None, 0.0
    regular = float(regular_rate_pct) / 100 / 12
    promo = float(promo_rate_pct or 0) / 100 / 12
    interest = deferred = 0.0
    for month in range(1, max_months + 1):
        if month <= promo_months:
            charged = b * promo
            deferred += b * regular - charged
        else:
            if month == promo_months + 1 and deferred_interest and deferred:
                b += deferred  # the promo was missed: the retroactive interest lands now
                interest += deferred
            charged = b * regular
        interest += charged
        b += charged - min(p, b + charged)
        if b <= 1e-9:
            return month, interest
    return None, interest


def months_to_payoff(balance: Decimal, annual_rate_pct: Decimal, payment: Decimal) -> int | None:
    """Months to repay with a fixed monthly payment; None if the payment doesn't cover the interest."""
    return payoff_schedule(balance, payment, annual_rate_pct)[0]


def promo_months_left(promo_end: dt.date, today: dt.date) -> int:
    """Monthly payments still due inside the promo (payment m falls on today + m months)."""
    months = 0
    while add_months(today, months + 1) <= promo_end:
        months += 1
    return months


def compute_debts(user) -> dict:
    expected = UserSettings.for_user(user).annual_return_pct
    today = timezone.localdate()
    rows, alerts = [], []
    for lb in Liability.objects.filter(owner=user):
        in_promo = lb.in_promo(today)
        promo_months = promo_months_left(lb.promo_end_date, today) if in_promo else 0
        schedule = {
            "promo_rate_pct": lb.promo_rate_pct if in_promo else None,
            "promo_months": promo_months,
            "deferred_interest": lb.deferred_interest and in_promo,
        }
        months, interest = payoff_schedule(lb.balance, lb.minimum_payment, lb.interest_rate_pct, **schedule)
        _, interest_12m = payoff_schedule(lb.balance, lb.minimum_payment, lb.interest_rate_pct, max_months=12, **schedule)

        rate = lb.current_rate_pct(today)
        payment_to_clear = clears_in_promo = None
        if in_promo:
            # A 0% balance shouldn't be prepaid, but it has to be gone before the rate jumps.
            verdict = "promo"
            payment_to_clear = (lb.balance / promo_months).quantize(Decimal("0.01")) if promo_months else lb.balance
            clears_in_promo = lb.minimum_payment * promo_months >= lb.balance
            if not clears_in_promo:
                risk = (
                    "te cobrarán todo el interés diferido" if lb.deferred_interest
                    else f"el saldo pasará a {lb.interest_rate_pct}%"
                )
                alerts.append(
                    {
                        "name": lb.name,
                        "level": "critical" if lb.deferred_interest else "warning",
                        "message": f"Con el pago mínimo no la liquidas antes del {lb.promo_end_date} y {risk}. "
                        f"Paga al menos ${payment_to_clear} al mes.",
                    }
                )
        elif rate > expected:
            verdict = "pay_first"  # guaranteed return above what investing is expected to earn
        elif rate < expected - 2:
            verdict = "invest"
        else:
            verdict = "either"
        rows.append(
            {
                "id": lb.id,
                "name": lb.name,
                "kind": lb.kind,
                "kind_label": lb.get_kind_display(),
                "balance": lb.balance,
                "interest_rate_pct": lb.interest_rate_pct,
                "current_rate_pct": rate,
                "in_promo": in_promo,
                "promo_rate_pct": lb.promo_rate_pct,
                "promo_end_date": lb.promo_end_date,
                "promo_months_left": promo_months if in_promo else None,
                "deferred_interest": lb.deferred_interest,
                "payment_to_clear_promo": payment_to_clear,
                "clears_in_promo": clears_in_promo,
                "minimum_payment": lb.minimum_payment,
                "annual_interest": Decimal(str(round(interest_12m, 2))),  # next 12 months at the minimum payment
                "months_to_payoff": months,
                "total_interest": Decimal(str(round(interest, 2))) if months is not None else None,
                "verdict": verdict,
            }
        )
    # Avalanche order on today's rate: highest first minimizes interest; 0% promos go last (watch the alerts).
    rows.sort(key=lambda r: (-r["current_rate_pct"], -r["balance"]))
    for i, r in enumerate(rows, start=1):
        r["order"] = i
    total = sum((r["balance"] for r in rows), ZERO)
    return {
        "expected_return_pct": expected,
        "total": total,
        "weighted_rate_pct": sum((r["balance"] * r["current_rate_pct"] for r in rows), ZERO) / total if total else None,
        "minimum_payments": sum((r["minimum_payment"] for r in rows), ZERO),
        "annual_interest": sum((r["annual_interest"] for r in rows), ZERO),
        "alerts": alerts,
        "rows": rows,
    }


# -- Monte Carlo retirement ------------------------------------------------------------------------

BASES = ("net_worth", "net_worth_ex_private", "liquid")


def _percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


# Long-run capital market assumptions, nominal %/year: (expected return, volatility). Editable per user in
# Settings → return_assumptions. Rough consensus ranges; crypto and private equity are deliberately wide.
DEFAULT_ASSUMPTIONS = {
    AssetClass.STOCK: (7.0, 16.0),
    AssetClass.BOND: (4.5, 6.0),
    AssetClass.CRYPTO: (12.0, 65.0),
    AssetClass.METAL: (4.0, 15.0),
    AssetClass.CASH: (3.5, 1.0),
    AssetClass.REAL_ESTATE: (6.0, 15.0),
    AssetClass.PRIVATE_EQUITY: (9.0, 35.0),
    AssetClass.OTHER: (5.0, 15.0),
}
# Correlations between classes (symmetric; anything unlisted is 0). CoinRoutes-style private equity moves
# with crypto, so the two are tied together.
CORRELATIONS = {
    frozenset({AssetClass.STOCK, AssetClass.BOND}): 0.1,
    frozenset({AssetClass.STOCK, AssetClass.CRYPTO}): 0.4,
    frozenset({AssetClass.STOCK, AssetClass.METAL}): 0.1,
    frozenset({AssetClass.STOCK, AssetClass.REAL_ESTATE}): 0.6,
    frozenset({AssetClass.STOCK, AssetClass.PRIVATE_EQUITY}): 0.6,
    frozenset({AssetClass.STOCK, AssetClass.OTHER}): 0.5,
    frozenset({AssetClass.BOND, AssetClass.METAL}): 0.2,
    frozenset({AssetClass.BOND, AssetClass.REAL_ESTATE}): 0.2,
    frozenset({AssetClass.CRYPTO, AssetClass.METAL}): 0.1,
    frozenset({AssetClass.CRYPTO, AssetClass.PRIVATE_EQUITY}): 0.6,
}

# IRS Uniform Lifetime Table (2022+): age -> distribution period.
UNIFORM_LIFETIME = {
    72: 27.4, 73: 26.5, 74: 25.5, 75: 24.6, 76: 23.7, 77: 22.9, 78: 22.0, 79: 21.1, 80: 20.2, 81: 19.4,
    82: 18.5, 83: 17.7, 84: 16.8, 85: 16.0, 86: 15.2, 87: 14.4, 88: 13.7, 89: 12.9, 90: 12.2, 91: 11.5,
    92: 10.8, 93: 10.1, 94: 9.5, 95: 8.9, 96: 8.4, 97: 7.8, 98: 7.3, 99: 6.8, 100: 6.4, 101: 6.0, 102: 5.6,
    103: 5.2, 104: 4.9, 105: 4.6, 106: 4.3, 107: 4.1, 108: 3.9, 109: 3.7, 110: 3.5, 111: 3.4, 112: 3.3,
    113: 3.1, 114: 3.0, 115: 2.9, 116: 2.8, 117: 2.7, 118: 2.5, 119: 2.3, 120: 2.0,
}


def rmd_start_age(birth_year: int) -> int:
    """SECURE 2.0: 73 for those born 1951–1959, 75 from 1960 on."""
    return 75 if birth_year >= 1960 else 73


def class_assumptions(s: UserSettings) -> dict[str, tuple[float, float]]:
    out = {str(k): v for k, v in DEFAULT_ASSUMPTIONS.items()}
    for cls, numbers in (s.return_assumptions or {}).items():
        if cls in out:
            out[cls] = (float(numbers["return"]), float(numbers["volatility"]))
    return out


def portfolio_assumptions(user, base: str, s: UserSettings) -> dict:
    """Expected return and volatility of what `base` holds today, from per-class assumptions and correlations."""
    weights: dict[str, float] = {}
    deferred = total = 0.0
    for p in compute_positions(user):
        value = float(p.market_value)
        if value <= 0 or p.asset_class == AssetClass.DEBT:
            continue
        if base != "net_worth" and p.asset_class == AssetClass.PRIVATE_EQUITY:
            continue
        if base == "liquid" and not p.account.is_liquid:
            continue
        cls = p.asset_class if p.asset_class in DEFAULT_ASSUMPTIONS else AssetClass.OTHER
        weights[cls] = weights.get(cls, 0.0) + value
        total += value
        if p.account.tax_treatment == TaxTreatment.TAX_DEFERRED:
            deferred += value
    table = class_assumptions(s)
    if not total:
        return {"return_pct": float(s.annual_return_pct), "volatility_pct": float(s.expected_volatility_pct),
                "deferred_share": 0.0, "by_class": []}
    w = {cls: v / total for cls, v in weights.items()}
    mu = sum(w[c] * table[c][0] for c in w)
    variance = 0.0
    for a in w:
        for b in w:
            rho = 1.0 if a == b else CORRELATIONS.get(frozenset({a, b}), 0.0)
            variance += w[a] * w[b] * rho * table[a][1] * table[b][1]
    by_class = [
        {"asset_class": c, "label": AssetClass(c).label, "weight_pct": w.get(c, 0.0) * 100,
         "return_pct": table[c][0], "volatility_pct": table[c][1],
         "default_return_pct": DEFAULT_ASSUMPTIONS[c][0], "default_volatility_pct": DEFAULT_ASSUMPTIONS[c][1],
         "custom": c in (s.return_assumptions or {})}
        for c in table
    ]
    by_class.sort(key=lambda r: -r["weight_pct"])
    return {"return_pct": mu, "volatility_pct": math.sqrt(variance), "deferred_share": deferred / total,
            "by_class": by_class}


def monte_carlo(user, base: str = "net_worth_ex_private", paths: int = 2000, seed: int = 7) -> dict:
    """Yearly lognormal returns; contributions until retirement; then spending (budget expenses, or the
    withdrawal rate if there is no budget) minus Social Security, all inflation-adjusted. Results in today's $.

    Tax-deferred money (401k / traditional IRA) is tracked apart: spending comes from the rest first, and from
    the RMD age on, at least the required minimum distribution leaves the deferred bucket each year; what isn't
    spent pays retirement tax and is reinvested."""
    s = UserSettings.for_user(user)
    base = base if base in BASES else "net_worth_ex_private"
    start = float(compute_summary(user)[base])
    budget = compute_budget(user)
    mix = portfolio_assumptions(user, base, s)

    if s.projection_by_asset_class and mix["by_class"]:
        mu, sigma = mix["return_pct"] / 100, mix["volatility_pct"] / 100
    else:
        mu, sigma = float(s.annual_return_pct) / 100, float(s.expected_volatility_pct) / 100
    inflation = float(s.inflation_pct) / 100
    drift = math.log(1 + mu) - sigma**2 / 2  # so the mean yearly return is `mu`
    contribution = float(s.annual_contribution + s.employer_match_annual)
    social_security = float(s.social_security_annual)
    spending_real = float(budget["annual_expenses"]) or None  # today's dollars
    years = max(s.life_expectancy - s.current_age, 1)
    retire_at = min(max(s.retirement_age - s.current_age, 0), years)
    deferred_share = mix["deferred_share"]
    rmd_age = rmd_start_age(timezone.localdate().year - s.current_age)
    rmd_tax = float(s.retirement_tax_pct) / 100

    rng = random.Random(seed)  # fixed seed: the same inputs always give the same answer
    real_paths = [[0.0] * (years + 1) for _ in range(paths)]
    first_rmds, rmd_taxes = [], []
    survived = 0
    for path in real_paths:
        deferred, other = start * deferred_share, start * (1 - deferred_share)
        fixed_withdrawal, failed, first_rmd, taxed = None, False, None, 0.0
        path[0] = start
        for y in range(1, years + 1):
            prices = (1 + inflation) ** y
            age = s.current_age + y
            need = from_other = 0.0
            required = deferred / UNIFORM_LIFETIME.get(age, 2.0) if age >= rmd_age and deferred > 0 else 0.0
            growth = math.exp(rng.gauss(drift, sigma))
            deferred, other = deferred * growth, other * growth
            if y <= retire_at:
                deferred += contribution * deferred_share
                other += contribution * (1 - deferred_share)
            else:
                if spending_real is not None:
                    need = spending_real * prices
                else:
                    if fixed_withdrawal is None:  # 4%-style rule: % of the balance at retirement, then indexed
                        fixed_withdrawal = path[retire_at] * float(s.withdrawal_rate_pct) / 100
                    need = fixed_withdrawal * prices
                if age >= s.social_security_age:
                    need -= social_security * prices
                need = max(need, 0.0)
                from_other = min(need, max(other, 0.0))
                other -= from_other
                deferred -= need - from_other
            if required:
                # Spending already taken from the deferred bucket counts toward the RMD.
                extra = min(max(required - (need - from_other), 0.0), max(deferred, 0.0))
                deferred -= extra
                other += extra * (1 - rmd_tax)
                taxed += extra * rmd_tax / prices
                if first_rmd is None:
                    first_rmd = required / prices
            balance = deferred + other
            if balance <= 0:
                deferred, other, balance, failed = 0.0, 0.0, 0.0, True
            path[y] = balance / prices
        survived += not failed
        if first_rmd is not None:
            first_rmds.append(first_rmd)
        rmd_taxes.append(taxed)

    bands = []
    for y in range(years + 1):
        column = sorted(p[y] for p in real_paths)
        bands.append(
            {
                "age": s.current_age + y,
                "p10": _percentile(column, 0.1),
                "p50": _percentile(column, 0.5),
                "p90": _percentile(column, 0.9),
            }
        )

    fi_number = fi_age = None
    if spending_real and s.withdrawal_rate_pct:
        fi_number = max(spending_real - social_security, 0.0) / (float(s.withdrawal_rate_pct) / 100)
        fi_age = next((b["age"] for b in bands if b["p50"] >= fi_number), None)

    return {
        "base": base,
        "start": start,
        "paths": paths,
        "success_probability": survived / paths * 100,
        "uses_budget": spending_real is not None,
        "annual_spending": spending_real,
        "fi_number": fi_number,
        "fi_age": fi_age,
        "at_retirement": bands[retire_at],
        "bands": bands,
        "assumptions": {
            "by_asset_class": bool(s.projection_by_asset_class and mix["by_class"]),
            "return_pct": mu * 100,
            "volatility_pct": sigma * 100,
            "allocation_return_pct": mix["return_pct"],
            "allocation_volatility_pct": mix["volatility_pct"],
            "by_class": mix["by_class"],
        },
        "rmd": {
            "start_age": rmd_age,
            "deferred_share_pct": deferred_share * 100,
            "first_p50": _percentile(sorted(first_rmds), 0.5) if first_rmds else None,
            "forced_tax_p50": _percentile(sorted(rmd_taxes), 0.5),
        },
    }


# -- IRS contribution limits -----------------------------------------------------------------------

# Published IRS limits (USD). 401k "elective" = pre-tax + Roth 401k deferrals; "total" = 415(c), all sources
# except catch-up. Ages 60–63 get the larger SECURE 2.0 catch-up instead of the 50+ one.
IRS_LIMITS = {
    2025: {"elective": 23500, "catch_up_50": 7500, "catch_up_60_63": 11250, "total": 70000, "ira": 7000,
           "ira_catch_up": 1000},
    2026: {"elective": 24500, "catch_up_50": 8000, "catch_up_60_63": 11250, "total": 72000, "ira": 7500,
           "ira_catch_up": 1100},
}


def contribution_limits(user, year: int | None = None) -> dict:
    """This year's 401k and IRA contributions (from recorded deposits) against the IRS limits."""
    s = UserSettings.for_user(user)
    year = year or timezone.localdate().year
    known = year in IRS_LIMITS
    limits = IRS_LIMITS[year if known else max(IRS_LIMITS)]
    age = s.current_age  # age reached this year, as entered in Settings
    catch_up = limits["catch_up_60_63"] if 60 <= age <= 63 else limits["catch_up_50"] if age >= 50 else 0
    elective_limit = limits["elective"] + catch_up
    ira_limit = limits["ira"] + (limits["ira_catch_up"] if age >= 50 else 0)

    flows = CashFlow.objects.filter(account__owner=user, account__archived=False, date__year=year)
    k401 = {"elective": ZERO, "after_tax": ZERO, "employer": ZERO}
    for f in flows.filter(account__account_type=AccountType.K401):
        if f.kind == CashFlowKind.EMPLOYER:
            k401["employer"] += f.amount
        elif f.kind == CashFlowKind.DEPOSIT:
            k401["after_tax" if "AFTERTAX" in f.notes.upper().replace("-", "").replace(" ", "") else "elective"] += f.amount
    ira = sum(
        (f.amount for f in flows.filter(
            account__account_type__in=[AccountType.ROTH_IRA, AccountType.TRADITIONAL_IRA], kind=CashFlowKind.DEPOSIT)),
        ZERO,
    )
    total_401k = k401["elective"] + k401["after_tax"] + k401["employer"]
    total_limit = Decimal(limits["total"]) + catch_up
    return {
        "year": year,
        "limits_year": year if known else max(IRS_LIMITS),
        "age": age,
        "k401": {
            **k401,
            "elective_limit": Decimal(elective_limit),
            "elective_room": max(Decimal(elective_limit) - k401["elective"], ZERO),
            "total": total_401k,
            "total_limit": total_limit,
            "total_room": max(total_limit - total_401k, ZERO),
        },
        "ira": {"contributed": ira, "limit": Decimal(ira_limit), "room": max(Decimal(ira_limit) - ira, ZERO)},
    }
