import datetime as dt
from decimal import Decimal as D
from unittest import mock

import pytest

from portfolio.models import Liability
from portfolio.services.planning import compute_debts, payoff_schedule, promo_months_left

pytestmark = pytest.mark.django_db


def test_promo_paid_off_inside_the_promo_costs_nothing():
    months, interest = payoff_schedule(D(1200), D(100), D(24), promo_rate_pct=D(0), promo_months=12)
    assert (months, interest) == (12, 0)


def test_balance_left_after_promo_accrues_the_regular_rate():
    months, interest = payoff_schedule(D(1200), D(50), D(24), promo_rate_pct=D(0), promo_months=12)
    assert months == 26  # 12 promo months leave 600, which takes 14 more at 2%/month
    assert interest > 0


def test_deferred_interest_is_charged_retroactively_when_the_promo_is_missed():
    _, plain = payoff_schedule(D(1200), D(50), D(24), promo_rate_pct=D(0), promo_months=12)
    _, deferred = payoff_schedule(D(1200), D(50), D(24), promo_rate_pct=D(0), promo_months=12, deferred_interest=True)
    # 2% of the balances during the promo: 1200, 1150, … 650 → 11,100 × 0.02 = 222 charged at month 13,
    # which then itself accrues interest.
    assert deferred - plain > 222


def test_promo_months_left_counts_payments_due_before_the_end():
    assert promo_months_left(dt.date(2026, 12, 31), dt.date(2026, 1, 15)) == 11
    assert promo_months_left(dt.date(2026, 1, 20), dt.date(2026, 1, 15)) == 0


def debts_on(user, date):
    with mock.patch("portfolio.services.planning.timezone.localdate", return_value=date):
        return compute_debts(user)


def test_debts_during_promo(user):
    Liability.objects.create(
        owner=user, name="Store card", kind="credit_card", balance=1100, interest_rate_pct=24, minimum_payment=50,
        promo_rate_pct=0, promo_end_date=dt.date(2026, 12, 31), deferred_interest=True,
    )
    Liability.objects.create(owner=user, name="Car", kind="auto", balance=5000, interest_rate_pct=5, minimum_payment=200)

    d = debts_on(user, dt.date(2026, 1, 15))
    car, card = d["rows"]  # avalanche on today's rate: 5% before the 0% promo
    assert (car["name"], card["name"]) == ("Car", "Store card")
    assert (card["verdict"], card["current_rate_pct"], card["promo_months_left"]) == ("promo", 0, 11)
    assert card["payment_to_clear_promo"] == D("100.00")
    assert card["clears_in_promo"] is False
    [alert] = d["alerts"]
    assert alert["level"] == "critical"
    assert "diferido" in alert["message"]


def test_debts_after_promo_use_the_regular_rate(user):
    Liability.objects.create(
        owner=user, name="Card", kind="credit_card", balance=1000, interest_rate_pct=24, minimum_payment=100,
        promo_rate_pct=0, promo_end_date=dt.date(2026, 12, 31),
    )
    [row] = debts_on(user, dt.date(2027, 2, 1))["rows"]
    assert (row["in_promo"], row["current_rate_pct"], row["verdict"]) == (False, 24, "pay_first")


def test_promo_rate_and_end_date_go_together(api):
    body = {"name": "Card", "kind": "credit_card", "balance": "100", "promo_rate_pct": "0"}
    assert api.post("/api/liabilities/", body, format="json").status_code == 400
    body["promo_end_date"] = "2026-12-31"
    assert api.post("/api/liabilities/", body, format="json").status_code == 201


def test_alert_when_the_payment_doesnt_cover_interest(user):
    Liability.objects.create(owner=user, name="Card", kind="credit_card", balance=1943, interest_rate_pct=D("28.24"),
                             minimum_payment=25)
    Liability.objects.create(owner=user, name="Fine", kind="credit_card", balance=1000, interest_rate_pct=24,
                             minimum_payment=100)
    [alert] = compute_debts(user)["alerts"]
    assert alert["name"] == "Card" and alert["level"] == "critical"
    assert "no cubre los intereses (~$45.73/mes" in alert["message"] and "~$187" in alert["message"]


def test_paid_off_debts_have_no_place_in_the_order(user):
    Liability.objects.create(owner=user, name="Paid card", kind="credit_card", balance=0, interest_rate_pct=30)
    Liability.objects.create(owner=user, name="Card", kind="credit_card", balance=500, interest_rate_pct=20,
                             minimum_payment=50)
    rows = compute_debts(user)["rows"]
    assert [(r["name"], r["order"]) for r in rows] == [("Card", 1), ("Paid card", None)]


def test_savings_plan_parks_the_balance_and_pays_the_minimum(user):
    from portfolio.models import UserSettings, add_months
    from portfolio.services.planning import savings_plan

    s = UserSettings.for_user(user)
    s.ordinary_income_tax_pct = D(24)
    s.save()
    today = dt.date.today()
    Liability.objects.create(owner=user, name="Phone", kind="other", balance=1200, interest_rate_pct=0, minimum_payment=100)
    Liability.objects.create(owner=user, name="Store", kind="credit_card", balance=1200, interest_rate_pct=25,
                             minimum_payment=50, promo_rate_pct=0, promo_end_date=add_months(today, 6) - dt.timedelta(days=1),
                             deferred_interest=True)
    Liability.objects.create(owner=user, name="Card", kind="credit_card", balance=500, interest_rate_pct=28,
                             minimum_payment=50)
    Liability.objects.create(owner=user, name="Paid", kind="credit_card", balance=0, interest_rate_pct=0)

    plan = savings_plan(user, D("3.1"))
    rows = {r["name"]: r for r in plan["rows"]}
    assert set(rows) == {"Phone", "Store"}  # by default the debts at 0% today, with a balance

    phone = rows["Phone"]
    assert phone["months"] == 12 and phone["debt_interest"] == 0
    # Starts at $1,200 and drops $100 a month (sum of month-start balances ≈ $7,800) at ~0.2545%/month ≈ $20
    assert 19 < phone["interest_earned"] < 21
    assert phone["net_after_tax"] == pytest.approx(phone["interest_earned"] * 0.76, abs=0.01)

    store = rows["Store"]  # the promo ends first: the rest is paid from the account, no deferred interest
    assert store["months"] == 5 and store["lump_sum"] == 950 and store["debt_interest"] == 0
    assert "pagas el resto ($950.00)" in store["note"]

    card = savings_plan(user, D("3.1"), ids=[Liability.objects.get(name="Card").id])["rows"][0]
    assert card["net_after_tax"] < 0  # 28% debt vs 3.1% savings: keeping the cash loses money


def test_savings_plan_endpoint(api):
    assert api.get("/api/debts/savings-plan/?apy=3.1").status_code == 200
    assert api.get("/api/debts/savings-plan/?apy=abc").status_code == 400
    assert api.get("/api/debts/savings-plan/?apy=40").status_code == 400
