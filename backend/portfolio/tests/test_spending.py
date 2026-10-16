import datetime as dt
from decimal import Decimal as D

import pytest

from connections.models import BankTransaction, PlaidAccount, PlaidItem
from connections.sync import store_bank_transactions
from portfolio.models import BudgetItem
from portfolio.services.spending import compute_spending

pytestmark = pytest.mark.django_db


@pytest.fixture
def card(user):
    item = PlaidItem.objects.create(owner=user, item_id="i1", access_token_encrypted="x", institution_name="Robinhood",
                                    bank_transactions=True)
    return PlaidAccount.objects.create(item=item, plaid_account_id="c1", name="Card", type="credit", subtype="credit card")


def tx(id_, day, amount, primary, detailed="", **extra):
    return {"transaction_id": id_, "account_id": "c1", "date": day, "amount": amount, "name": id_,
            "merchant_name": extra.pop("merchant", ""), "personal_finance_category": {"primary": primary, "detailed": detailed},
            **extra}


def test_store_keeps_posted_movements_and_follows_removals(user, card):
    changes = {"added": [
        tx("a", "2026-09-03", 40, "FOOD_AND_DRINK", merchant="Publix", authorized_date="2026-08-31"),
        tx("p", "2026-09-04", 9, "FOOD_AND_DRINK", pending=True),
        {**tx("x", "2026-09-04", 9, "FOOD_AND_DRINK"), "account_id": "other"},
    ], "modified": [], "removed": []}
    assert store_bank_transactions(card.item, changes) == 1
    saved = BankTransaction.objects.get(transaction_id="a")
    assert (saved.date, saved.merchant, saved.amount) == (dt.date(2026, 8, 31), "Publix", 40)  # the purchase day
    store_bank_transactions(card.item, {"added": [], "modified": [], "removed": [{"transaction_id": "a"}]})
    assert not BankTransaction.objects.exists()


def test_spending_vs_budget(user, card):
    BudgetItem.objects.create(owner=user, name="Groceries", kind="expense", amount=500, spending_category="FOOD_AND_DRINK")
    BudgetItem.objects.create(owner=user, name="Gym", kind="expense", amount=40)  # not mapped
    rows = [
        ("t1", "2026-10-02", 120, "FOOD_AND_DRINK", "", "Publix"),
        ("t2", "2026-10-05", -20, "FOOD_AND_DRINK", "", "Publix"),  # refund
        ("t3", "2026-10-06", 60, "TRANSPORTATION", "", "Shell"),
        ("t4", "2026-10-07", 900, "LOAN_PAYMENTS", "LOAN_PAYMENTS_CREDIT_CARD_PAYMENT", ""),  # paying the card
        ("t5", "2026-10-08", 300, "TRANSFER_OUT", "", ""),
        ("t6", "2026-09-10", 90, "FOOD_AND_DRINK", "", "Publix"),
        ("t7", "2026-10-09", 15, "SOMETHING_NEW", "", "Shop"),
    ]
    for id_, day, amount, cat, det, merchant in rows:
        BankTransaction.objects.create(owner=user, plaid_account=card, transaction_id=id_, date=dt.date.fromisoformat(day),
                                       amount=amount, category=cat, detailed_category=det, merchant=merchant)
    bank = PlaidAccount.objects.create(item=card.item, plaid_account_id="b1", name="Checking", type="depository")
    BankTransaction.objects.create(owner=user, plaid_account=card, transaction_id="t8", date=dt.date(2026, 10, 10),
                                   amount=-1500, category="LOAN_DISBURSEMENTS")  # how Chase labels a card payment
    BankTransaction.objects.create(owner=user, plaid_account=bank, transaction_id="t9", date=dt.date(2026, 10, 11),
                                   amount=-140, category="OTHER")  # money received in the bank: not a refund
    BankTransaction.objects.create(owner=user, plaid_account=bank, transaction_id="t10", date=dt.date(2026, 10, 12),
                                   amount=30, category="FOOD_AND_DRINK", merchant="Publix")  # debit card purchase
    data = compute_spending(user, dt.date(2026, 10, 1))
    assert data["spent"] == 205  # 120 − 20 + 60 + 15 + 30: no card payment, transfer, disbursement or inflow
    assert (data["budget"], data["unmapped_budget"]) == (500, 40)
    food = next(r for r in data["categories"] if r["category"] == "FOOD_AND_DRINK")
    assert (food["spent"], food["budget"], food["remaining"], food["avg_3m"]) == (130, 500, 370, 30)
    assert next(r for r in data["categories"] if r["category"] == "OTHER")["spent"] == 15
    assert data["top_merchants"][0] == {"name": "Publix", "spent": D(130)}
    assert [h["spent"] for h in data["history"]][-2:] == [90, 205]
    assert {"account": "Robinhood · Card", "importing": True} in data["sources"]


def test_spending_endpoint(api):
    assert api.get("/api/spending/").status_code == 200
    assert api.get("/api/spending/?month=2026-13").status_code == 400
