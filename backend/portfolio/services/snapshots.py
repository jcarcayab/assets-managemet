from decimal import Decimal

from django.utils import timezone

from portfolio.models import Snapshot
from portfolio.services.positions import compute_summary

CENT = Decimal("0.01")


def _money(v) -> Decimal:
    return Decimal(v).quantize(CENT)


def take_snapshot(user, date=None, notes: str = "") -> Snapshot:
    """Store today's (or `date`'s) totals. Re-running on the same day overwrites that day's snapshot."""
    s = compute_summary(user)
    snap, _ = Snapshot.objects.update_or_create(
        owner=user,
        date=date or timezone.localdate(),
        defaults={
            "net_worth": _money(s["net_worth"]),
            "net_worth_ex_private": _money(s["net_worth_ex_private"]),
            "liquid": _money(s["liquid"]),
            "cost": _money(s["cost"]),
            "unrealized": _money(s["unrealized"]),
            "breakdown": {
                "by_account": {r["label"]: float(r["value"]) for r in s["by_account"]},
                "by_class": {r["label"]: float(r["value"]) for r in s["by_class"]},
            },
            "notes": notes,
        },
    )
    return snap
