"""Real spending (card and bank movements from Plaid Transactions) against the budget, month by month.

Counts purchases minus card refunds. Money moving between your own accounts, income, credit-card payments and
loan disbursements are left out (a card payment would count the same purchases twice; some banks, like Chase,
label card payments as disbursements). On bank accounts only money going out counts: money coming in there is
income or a transfer, not a refund.
"""

import calendar
import datetime as dt
from collections import defaultdict
from decimal import Decimal

from django.utils import timezone

from portfolio.models import BudgetItem, BudgetKind, SpendingCategory

ZERO = Decimal(0)
NOT_SPENDING = {"TRANSFER_IN", "TRANSFER_OUT", "INCOME", "LOAN_DISBURSEMENTS"}
CARD_PAYMENT = "LOAN_PAYMENTS_CREDIT_CARD_PAYMENT"
TRACKED_MONTHS = 6
TOP_MERCHANTS = 10


def _month_start(d: dt.date, back: int = 0) -> dt.date:
    month = d.month - 1 - back
    return dt.date(d.year + month // 12, month % 12 + 1, 1)


def _category(code: str) -> str:
    return code if code in SpendingCategory.values else SpendingCategory.OTHER


def compute_spending(user, month: dt.date | None = None) -> dict:
    from connections.models import BankTransaction, PlaidAccount

    today = timezone.localdate()
    target = _month_start(month or today)
    first = _month_start(target, TRACKED_MONTHS - 1)
    end = _month_start(target, -1)
    txs = (
        BankTransaction.objects.filter(owner=user, date__gte=first, date__lt=end)
        .exclude(category__in=NOT_SPENDING)
        .exclude(detailed_category=CARD_PAYMENT)
        .exclude(plaid_account__type="depository", amount__lt=0)
        .select_related("plaid_account")
    )

    by_month: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    merchants: dict[str, Decimal] = defaultdict(Decimal)
    for t in txs:
        key = t.date.strftime("%Y-%m")
        by_month[key][_category(t.category)] += t.amount
        if t.date >= target:
            merchants[t.merchant or t.name] += t.amount

    budget: dict[str, Decimal] = defaultdict(Decimal)
    unmapped = ZERO
    for item in BudgetItem.objects.filter(owner=user, kind=BudgetKind.EXPENSE):
        if item.spending_category:
            budget[item.spending_category] += item.monthly
        else:
            unmapped += item.monthly

    months = [_month_start(target, back).strftime("%Y-%m") for back in range(TRACKED_MONTHS - 1, -1, -1)]
    current = by_month.get(target.strftime("%Y-%m"), {})
    previous = months[-4:-1]  # the three months before the target, for a normal level
    rows = []
    for code, label in SpendingCategory.choices:
        spent = current.get(code, ZERO)
        avg = sum((by_month.get(m, {}).get(code, ZERO) for m in previous), ZERO) / len(previous)
        if spent or budget.get(code) or avg:
            rows.append({
                "category": code, "label": label, "budget": budget.get(code, ZERO), "spent": spent,
                "remaining": budget.get(code, ZERO) - spent, "avg_3m": avg,
            })
    rows.sort(key=lambda r: -max(r["spent"], r["budget"]))

    days_in_month = calendar.monthrange(target.year, target.month)[1]
    is_current = target == _month_start(today)
    sources = PlaidAccount.objects.filter(
        item__owner=user, enabled=True, type__in=["depository", "credit"]
    ).select_related("item")
    return {
        "month": target.strftime("%Y-%m"),
        "is_current_month": is_current,
        "month_progress": (today.day / days_in_month) if is_current else 1.0,
        "spent": sum(current.values(), ZERO),
        "budget": sum(budget.values(), ZERO),
        "unmapped_budget": unmapped,
        "categories": rows,
        "history": [{"month": m, "spent": sum(by_month.get(m, {}).values(), ZERO)} for m in months],
        "top_merchants": [
            {"name": name or "—", "spent": amount}
            for name, amount in sorted(merchants.items(), key=lambda kv: -kv[1])[:TOP_MERCHANTS] if amount > 0
        ],
        "sources": [
            {"account": f"{pa.item.institution_name} · {pa.name}" + (f" ····{pa.mask}" if pa.mask else ""),
             "importing": pa.item.bank_transactions and not pa.item.transactions_error}
            for pa in sources
        ],
    }
