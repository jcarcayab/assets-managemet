"""Tax lots in taxable accounts: short/long-term gains, tax-loss harvesting and lots about to turn long-term.

Rough flat-rate estimates for planning, not tax advice.
"""

import datetime as dt
from decimal import Decimal

from django.utils import timezone

from portfolio.models import AssetClass, TaxTreatment, Transaction, TransactionKind, UserSettings
from portfolio.services.positions import LONG_TERM_DAYS, compute_positions

ZERO = Decimal(0)
HUNDRED = Decimal(100)
WASH_SALE_DAYS = 30
SOON_LONG_TERM_DAYS = 60


def wash_sale_applies(asset) -> bool:
    """US wash-sale rules cover securities; physical metals (priced off futures) and crypto are treated as exempt."""
    if asset.asset_class in (AssetClass.STOCK, AssetClass.BOND):
        return True
    return asset.asset_class == AssetClass.METAL and not asset.lookup_id.endswith("=F")


def compute_tax_lots(user) -> dict:
    s = UserSettings.for_user(user)
    today = timezone.localdate()
    st_rate, lt_rate = s.ordinary_income_tax_pct / HUNDRED, s.capital_gains_tax_pct / HUNDRED

    recent_buys = set(
        Transaction.objects.filter(
            account__owner=user, kind=TransactionKind.BUY, date__gte=today - dt.timedelta(days=WASH_SALE_DAYS)
        ).values_list("asset_id", flat=True)
    )

    positions = [
        p for p in compute_positions(user)
        if p.asset is not None
        and p.account.tax_treatment == TaxTreatment.TAXABLE
        and p.asset_class not in (AssetClass.CASH, AssetClass.DEBT)
        and p.lots
    ]

    rows, harvest, soon_long = [], [], []
    totals = {"short_gain": ZERO, "long_gain": ZERO}
    for p in positions:
        lots = []
        for lot in p.lots:
            cost = lot.quantity * lot.unit_cost
            value = lot.quantity * p.price
            gain = value - cost
            held = (today - lot.date).days
            long_term = held > LONG_TERM_DAYS
            to_long = None if long_term else LONG_TERM_DAYS + 1 - held
            totals["long_gain" if long_term else "short_gain"] += gain
            lots.append(
                {
                    "date": lot.date,
                    "quantity": lot.quantity,
                    "unit_cost": lot.unit_cost,
                    "cost": cost,
                    "value": value,
                    "gain": gain,
                    "term": "long" if long_term else "short",
                    "days_to_long_term": to_long,
                }
            )
            if gain < 0:
                wash = wash_sale_applies(p.asset)
                harvest.append(
                    {
                        "symbol": p.symbol,
                        "account": p.account.name,
                        "date": lot.date,
                        "loss": gain,
                        "term": "long" if long_term else "short",
                        "tax_saving": -gain * (lt_rate if long_term else st_rate),
                        "wash_sale_rule": wash,
                        "wash_sale_risk": wash and p.asset.id in recent_buys,
                    }
                )
            elif gain > 0 and to_long is not None and to_long <= SOON_LONG_TERM_DAYS:
                soon_long.append(
                    {
                        "symbol": p.symbol,
                        "account": p.account.name,
                        "date": lot.date,
                        "gain": gain,
                        "days_to_long_term": to_long,
                        "saving_if_wait": gain * (st_rate - lt_rate),
                    }
                )
        rows.append(
            {
                "symbol": p.symbol,
                "name": p.name,
                "account": p.account.name,
                "asset_class": p.asset_class,
                "price": p.price,
                "lots": lots,
                "gain": sum((lot["gain"] for lot in lots), ZERO),
            }
        )

    est_tax = max(totals["short_gain"], ZERO) * st_rate + max(totals["long_gain"], ZERO) * lt_rate
    return {
        "rates": {"short": s.ordinary_income_tax_pct, "long": s.capital_gains_tax_pct},
        "short_gain": totals["short_gain"],
        "long_gain": totals["long_gain"],
        "estimated_tax": est_tax,
        "positions": sorted(rows, key=lambda r: r["gain"]),
        "harvest": sorted(harvest, key=lambda h: h["loss"]),
        "harvest_total_loss": sum((h["loss"] for h in harvest), ZERO),
        "harvest_total_saving": sum((h["tax_saving"] for h in harvest), ZERO),
        "soon_long_term": sorted(soon_long, key=lambda r: r["days_to_long_term"]),
    }
