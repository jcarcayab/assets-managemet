"""Private equity details: vesting progress, exercise cost and taxes, deadlines and exit scenarios."""

from decimal import Decimal

from django.utils import timezone

from portfolio.models import EquityGrant, GrantType, UserSettings

ZERO = Decimal(0)
HUNDRED = Decimal(100)
EXPIRY_WARNING_DAYS = 365
EXPIRY_CRITICAL_DAYS = 90
# Exit prices as multiples of today's FMV (409A). 0 = the company fails.
SCENARIO_MULTIPLES = [Decimal(m) for m in ("0", "0.5", "1", "2", "3", "5")]


def exit_value(g: EquityGrant, price: Decimal, s: UserSettings, everything: bool = False) -> tuple[Decimal, Decimal]:
    """(gross, tax) if the company were sold at `price` per share today.

    A sale is a liquidity event, so no liquidity discount. Options are assumed exercised and sold at once:
    the spread pays ordinary income (NSO) or capital gains (ISO, assuming a qualifying disposition); shares
    pay capital gains over their basis. `everything` also counts what hasn't vested yet.
    """
    cg, ordinary = s.capital_gains_tax_pct / HUNDRED, s.ordinary_income_tax_pct / HUNDRED
    if not g.is_option:
        shares = g.quantity if everything else g.vested_quantity()
        gross = shares * price
        return gross, max(gross - shares * g.strike, ZERO) * cg
    shares = g.exercised_quantity()
    gross = shares * price
    tax = max(gross - g.shares_cost_basis, ZERO) * cg
    if not g.options_lost():
        options = g.quantity - shares if everything else g.open_options()
        spread = options * max(price - g.strike, ZERO)
        gross += spread
        tax += spread * (ordinary if g.grant_type == GrantType.NSO else cg)
    return gross, tax


def scenarios(grants: list[EquityGrant], s: UserSettings) -> list[dict]:
    by_company: dict[str, list[EquityGrant]] = {}
    for g in grants:
        by_company.setdefault(g.company, []).append(g)
    out = []
    for company, gs in by_company.items():
        rows = []
        for m in SCENARIO_MULTIPLES:
            vested = [exit_value(g, g.fmv * m, s) for g in gs]
            full = [exit_value(g, g.fmv * m, s, everything=True) for g in gs]
            gross, tax = sum((v[0] for v in vested), ZERO), sum((v[1] for v in vested), ZERO)
            full_gross, full_tax = sum((v[0] for v in full), ZERO), sum((v[1] for v in full), ZERO)
            rows.append(
                {
                    "multiple": m, "price": gs[0].fmv * m, "gross": gross, "net": gross - tax,
                    "full_gross": full_gross, "full_net": full_gross - full_tax,
                }
            )
        out.append({"company": company, "fmv": gs[0].fmv, "rows": rows})
    return out


def deadline_alert(g: EquityGrant, open_options: Decimal, cash_needed: Decimal, today) -> dict | None:
    deadline = g.exercise_deadline
    if deadline is None:
        return None
    days = (deadline - today).days
    if g.termination_date:
        if days < 0:
            lost = max(g.vested_quantity() - g.exercised_quantity(), ZERO)
            if not lost:
                return None
            return {
                "level": "warning", "company": g.company,
                "message": f"El plazo para ejercer venció el {deadline}: {lost.normalize():,} opciones adquiridas sin "
                           f"ejercer se perdieron.",
            }
        if not open_options:
            return None
        return {
            "level": "critical", "company": g.company,
            "message": f"Dejaste la empresa el {g.termination_date}: tienes hasta el {deadline} ({days} días) para "
                       f"ejercer {open_options.normalize():,} opciones. Necesitas unos ${cash_needed:,.0f} "
                       f"(strike + impuesto estimado).",
        }
    if open_options and days <= EXPIRY_WARNING_DAYS:
        return {
            "level": "critical" if days <= EXPIRY_CRITICAL_DAYS else "warning", "company": g.company,
            "message": f"Las opciones vencen en {days} días ({deadline}).",
        }
    return None


def compute_equity(user) -> dict:
    s = UserSettings.for_user(user)
    today = timezone.localdate()
    grants, alerts = [], []
    grants_qs = EquityGrant.objects.filter(account__owner=user, account__archived=False)
    rows = list(grants_qs.select_related("account").prefetch_related("exercises"))
    for g in rows:
        vested = g.vested_quantity(today)
        unvested = g.quantity - vested
        open_options = g.open_options(today)
        shares = g.shares_held(today)
        spread = open_options * max(g.fmv - g.strike, ZERO)
        # NSO: the spread is ordinary income at exercise. ISO: no regular tax then, but it counts toward AMT.
        nso = g.is_option and g.grant_type == GrantType.NSO
        exercise_tax = spread * s.ordinary_income_tax_pct / HUNDRED if nso else ZERO
        days_to_expiry = (g.expiration_date - today).days if g.expiration_date else None
        cash_to_exercise = g.exercise_cost + exercise_tax

        alert = deadline_alert(g, open_options, cash_to_exercise, today)
        if alert:
            alerts.append(alert)

        grants.append(
            {
                "id": g.id,
                "company": g.company,
                "account": g.account.name,
                "grant_type": g.grant_type,
                "grant_type_label": g.get_grant_type_display(),
                "is_option": g.is_option,
                "quantity": g.quantity,
                "vested": vested,
                "unvested": unvested,
                "vested_pct": vested / g.quantity * HUNDRED if g.quantity else None,
                "next_vest_date": g.next_vest_date(today),
                "fully_vested_date": g.fully_vested_date,
                "strike": g.strike,
                "fmv": g.fmv,
                "liquidity_discount_pct": g.liquidity_discount_pct,
                "value": g.market_value,
                "unvested_value": unvested * g.per_share_value,
                "value_without_discount": shares * g.fmv + spread,
                "exercised": g.exercised_quantity(),
                "open_options": open_options,
                "shares": shares,
                "shares_value": shares * g.share_value,
                "shares_cost_basis": g.shares_cost_basis,
                "exercises": [
                    {
                        "id": e.id, "date": e.date, "quantity": e.quantity, "fmv": e.fmv, "cost": e.cost,
                        "spread": e.spread,
                        # What the exercise meant for taxes that year (NSO wages; ISO AMT preference).
                        "income_tax": e.spread * s.ordinary_income_tax_pct / HUNDRED if nso else ZERO,
                        "amt_preference": e.spread if g.grant_type == GrantType.ISO else ZERO,
                        "notes": e.notes,
                    }
                    for e in g.exercises.all()
                ],
                "exercise_cost": g.exercise_cost,
                "spread": spread,
                "exercise_tax": exercise_tax,
                "amt_preference": spread if g.grant_type == GrantType.ISO else ZERO,
                "cash_to_exercise": cash_to_exercise,
                "expiration_date": g.expiration_date,
                "days_to_expiration": days_to_expiry,
                "post_termination_days": g.post_termination_days,
                "termination_date": g.termination_date,
                "exercise_deadline": g.exercise_deadline,
                "options_lost": g.is_option and g.options_lost(today),
            }
        )

    def total(key):
        return sum((g[key] for g in grants), ZERO)

    return {
        "grants": grants,
        "alerts": alerts,
        "scenarios": scenarios(rows, s),
        "totals": {
            "value": total("value"),
            "unvested_value": total("unvested_value"),
            "exercise_cost": total("exercise_cost"),
            "exercise_tax": total("exercise_tax"),
            "cash_to_exercise": total("cash_to_exercise"),
        },
    }
