"""Planning: household budget and emergency fund, debts, and a Monte Carlo retirement projection."""

import datetime as dt
import math
import random
from decimal import Decimal

from django.utils import timezone

from portfolio.models import AssetClass, BudgetItem, BudgetKind, Liability, UserSettings, add_months
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


def monte_carlo(user, base: str = "net_worth_ex_private", paths: int = 2000, seed: int = 7) -> dict:
    """Yearly lognormal returns; contributions until retirement; then spending (budget expenses, or the
    withdrawal rate if there is no budget) minus Social Security, all inflation-adjusted. Results in today's $."""
    s = UserSettings.for_user(user)
    base = base if base in BASES else "net_worth_ex_private"
    start = float(compute_summary(user)[base])
    budget = compute_budget(user)

    mu, sigma = float(s.annual_return_pct) / 100, float(s.expected_volatility_pct) / 100
    inflation = float(s.inflation_pct) / 100
    drift = math.log(1 + mu) - sigma**2 / 2  # so the mean yearly return is `mu`
    contribution = float(s.annual_contribution + s.employer_match_annual)
    social_security = float(s.social_security_annual)
    spending_real = float(budget["annual_expenses"]) or None  # today's dollars
    years = max(s.life_expectancy - s.current_age, 1)
    retire_at = min(max(s.retirement_age - s.current_age, 0), years)

    rng = random.Random(seed)  # fixed seed: the same inputs always give the same answer
    real_paths = [[0.0] * (years + 1) for _ in range(paths)]
    survived = 0
    for path in real_paths:
        balance, fixed_withdrawal, failed = start, None, False
        path[0] = balance
        for y in range(1, years + 1):
            prices = (1 + inflation) ** y
            balance *= math.exp(rng.gauss(drift, sigma))
            if y <= retire_at:
                balance += contribution
            else:
                if spending_real is not None:
                    need = spending_real * prices
                else:
                    if fixed_withdrawal is None:  # 4%-style rule: % of the balance at retirement, then indexed
                        fixed_withdrawal = path[retire_at] * float(s.withdrawal_rate_pct) / 100
                    need = fixed_withdrawal * prices
                if s.current_age + y >= s.social_security_age:
                    need -= social_security * prices
                balance -= max(need, 0.0)
            if balance <= 0:
                balance, failed = 0.0, True
            path[y] = balance / prices
        survived += not failed

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
    }
