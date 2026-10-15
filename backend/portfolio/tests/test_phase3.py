import datetime as dt
from decimal import Decimal as D

import pytest

from portfolio.models import Asset, AssetClass, BudgetItem, Liability, PriceSource, Transaction, UserSettings
from portfolio.services.planning import compute_budget, compute_debts, monte_carlo, months_to_payoff
from portfolio.services.positions import compute_summary

pytestmark = pytest.mark.django_db


@pytest.fixture
def usd(user):
    return Asset.objects.create(
        owner=user, symbol="USD", asset_class=AssetClass.CASH, price_source=PriceSource.MANUAL, manual_price=1
    )


def deposit_cash(account, usd, amount):
    Transaction.objects.create(
        account=account, asset=usd, kind="buy", date=dt.date(2025, 1, 1), quantity=amount, price=1
    )


def test_liabilities_reduce_net_worth_not_asset_weights(user, broker, usd):
    deposit_cash(broker, usd, 10_000)
    Liability.objects.create(owner=user, name="Card", kind="credit_card", balance=2_000, interest_rate_pct=24)
    s = compute_summary(user)
    assert (s["assets"], s["liabilities"], s["net_worth"]) == (10_000, 2_000, 8_000)
    assert s["after_tax_net_worth"] == 8_000
    assert s["by_account"][0]["weight"] == 100


def test_budget_savings_rate_and_emergency_fund(user, broker, usd):
    deposit_cash(broker, usd, 8_000)
    BudgetItem.objects.create(owner=user, name="Salary", kind="income", amount=8000)
    BudgetItem.objects.create(owner=user, name="Rent", kind="expense", category="Vivienda", amount=2500)
    BudgetItem.objects.create(owner=user, name="Fun", kind="expense", category="Ocio", amount=500, essential=False)
    BudgetItem.objects.create(owner=user, name="Insurance", kind="expense", amount=1200, frequency="annual")

    b = compute_budget(user)
    assert b["monthly_expenses"] == 3100
    assert b["monthly_essential"] == 2600
    assert b["savings_rate"] == pytest.approx(D("61.25"))
    assert float(b["emergency_months"]) == pytest.approx(8000 / 2600)
    assert (b["emergency_target"], b["emergency_gap"]) == (15_600, 7_600)
    assert b["by_category"][0]["label"] == "Vivienda"


def test_months_to_payoff():
    assert months_to_payoff(D(1000), D(12), D(100)) == 11
    assert months_to_payoff(D(1000), D(0), D(100)) == 10
    assert months_to_payoff(D(1000), D(24), D(20)) is None  # the payment doesn't cover the interest


def test_debts_avalanche_order_and_verdicts(user):
    Liability.objects.create(owner=user, name="Mortgage", kind="mortgage", balance=200_000, interest_rate_pct=3)
    Liability.objects.create(owner=user, name="Card", kind="credit_card", balance=3_000, interest_rate_pct=24)
    Liability.objects.create(owner=user, name="Student", kind="student", balance=10_000, interest_rate_pct=1)
    d = compute_debts(user)  # expected return defaults to 3.8%
    assert [(r["name"], r["verdict"]) for r in d["rows"]] == [
        ("Card", "pay_first"), ("Mortgage", "either"), ("Student", "invest"),
    ]
    assert d["total"] == 213_000


def _retiree(user, broker, usd, spending):
    deposit_cash(broker, usd, 1_000_000)
    s = UserSettings.for_user(user)
    s.annual_return_pct = s.expected_volatility_pct = s.inflation_pct = D(0)
    s.current_age = s.retirement_age = 60
    s.life_expectancy = 70
    s.save()
    BudgetItem.objects.create(owner=user, name="Life", kind="expense", amount=spending, frequency="annual")


def test_monte_carlo_deterministic_without_volatility(user, broker, usd):
    _retiree(user, broker, usd, 50_000)
    mc = monte_carlo(user, paths=50)
    assert mc["success_probability"] == 100
    assert mc["bands"][-1]["p50"] == pytest.approx(500_000)
    assert mc["fi_number"] == pytest.approx(1_250_000)  # 50k / 4%
    assert mc["fi_age"] is None


def test_monte_carlo_runs_out_of_money(user, broker, usd):
    _retiree(user, broker, usd, 150_000)
    mc = monte_carlo(user, paths=50)
    assert mc["success_probability"] == 0
    assert mc["bands"][-1]["p90"] == 0


def test_phase3_endpoints(api):
    budget = {"name": "Rent", "kind": "expense", "amount": "100"}
    assert api.post("/api/budget-items/", budget, format="json").status_code == 201
    debt = {"name": "Card", "kind": "credit_card", "balance": "50"}
    assert api.post("/api/liabilities/", debt, format="json").status_code == 201
    for url in ["/api/budget/", "/api/debts/", "/api/monte-carlo/", "/api/monte-carlo/?base=liquid"]:
        assert api.get(url).status_code == 200, url
    choices = api.get("/api/choices/").json()
    assert {"budget_kinds", "frequencies", "liability_kinds"} <= choices.keys()
