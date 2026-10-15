"""Private equity details: vesting progress, exercise cost and taxes, expiration alerts."""

from decimal import Decimal

from django.utils import timezone

from portfolio.models import EquityGrant, GrantType, UserSettings

ZERO = Decimal(0)
HUNDRED = Decimal(100)
EXPIRY_WARNING_DAYS = 365
EXPIRY_CRITICAL_DAYS = 90


def compute_equity(user) -> dict:
    s = UserSettings.for_user(user)
    today = timezone.localdate()
    grants, alerts = [], []
    for g in EquityGrant.objects.filter(account__owner=user, account__archived=False).select_related("account"):
        vested = g.vested_quantity(today)
        unvested = g.quantity - vested
        spread = vested * max(g.fmv - g.strike, ZERO) if g.is_option else ZERO
        # NSO: the spread is ordinary income at exercise. ISO: no regular tax then, but it counts toward AMT.
        nso = g.is_option and g.grant_type == GrantType.NSO
        exercise_tax = spread * s.ordinary_income_tax_pct / HUNDRED if nso else ZERO
        days_to_expiry = (g.expiration_date - today).days if g.expiration_date else None

        if g.is_option and days_to_expiry is not None and days_to_expiry <= EXPIRY_WARNING_DAYS:
            alerts.append(
                {
                    "level": "critical" if days_to_expiry <= EXPIRY_CRITICAL_DAYS else "warning",
                    "company": g.company,
                    "message": f"Las opciones vencen en {days_to_expiry} días ({g.expiration_date}).",
                }
            )

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
                "value_without_discount": vested * (max(g.fmv - g.strike, ZERO) if g.is_option else g.fmv),
                "exercise_cost": g.exercise_cost,
                "spread": spread,
                "exercise_tax": exercise_tax,
                "amt_preference": spread if g.is_option and g.grant_type == GrantType.ISO else ZERO,
                "cash_to_exercise": g.exercise_cost + exercise_tax,
                "expiration_date": g.expiration_date,
                "days_to_expiration": days_to_expiry,
                "post_termination_days": g.post_termination_days,
            }
        )

    def total(key):
        return sum((g[key] for g in grants), ZERO)

    return {
        "grants": grants,
        "alerts": alerts,
        "totals": {
            "value": total("value"),
            "unvested_value": total("unvested_value"),
            "exercise_cost": total("exercise_cost"),
            "exercise_tax": total("exercise_tax"),
            "cash_to_exercise": total("cash_to_exercise"),
        },
    }
