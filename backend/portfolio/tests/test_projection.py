import datetime as dt
from decimal import Decimal as D

import pytest

from portfolio.models import Account, AccountType, Asset, AssetClass, CashFlow, PriceSource, TaxTreatment, UserSettings
from portfolio.services.planning import contribution_limits, monte_carlo, portfolio_assumptions, rmd_start_age
from portfolio.tests.conftest import buy

pytestmark = pytest.mark.django_db


def asset(user, symbol, cls, price):
    return Asset.objects.create(
        owner=user, symbol=symbol, asset_class=cls, price_source=PriceSource.MANUAL, manual_price=price
    )


def test_assumptions_come_from_the_allocation(user, broker):
    buy(broker, asset(user, "VTI", AssetClass.STOCK, 100), 50, 100)
    buy(broker, asset(user, "BND", AssetClass.BOND, 100), 50, 100)
    s = UserSettings.for_user(user)
    mix = portfolio_assumptions(user, "net_worth", s)
    assert mix["return_pct"] == pytest.approx(5.75)  # 50% × 7 + 50% × 4.5
    # √(.5²·16² + .5²·6² + 2·.5·.5·0.1·16·6)
    assert mix["volatility_pct"] == pytest.approx((0.25 * 256 + 0.25 * 36 + 0.5 * 0.1 * 96) ** 0.5)

    s.return_assumptions = {"stock": {"return": 9, "volatility": 16}}
    s.save()
    assert portfolio_assumptions(user, "net_worth", s)["return_pct"] == pytest.approx(6.75)
    assert monte_carlo(user, paths=20)["assumptions"]["return_pct"] == pytest.approx(6.75)


def test_rmd_start_age():
    assert (rmd_start_age(1955), rmd_start_age(1960), rmd_start_age(1990)) == (73, 75, 75)


def test_rmds_force_taxed_withdrawals_from_deferred_accounts(user):
    k401 = Account.objects.create(
        owner=user, name="401k", account_type=AccountType.K401, tax_treatment=TaxTreatment.TAX_DEFERRED
    )
    buy(k401, asset(user, "USD", AssetClass.CASH, 1), 1_000_000, 1)
    s = UserSettings.for_user(user)
    s.projection_by_asset_class = False
    s.annual_return_pct = s.expected_volatility_pct = s.inflation_pct = s.withdrawal_rate_pct = D(0)
    s.current_age, s.retirement_age, s.life_expectancy = 74, 74, 76  # born ~1952 → RMDs from 73
    s.retirement_tax_pct = D(20)
    s.save()
    mc = monte_carlo(user, base="net_worth", paths=10)
    assert mc["rmd"]["start_age"] == 73 and mc["rmd"]["deferred_share_pct"] == pytest.approx(100)
    assert mc["rmd"]["first_p50"] == pytest.approx(1_000_000 / 24.6)  # age 75 divisor
    assert mc["rmd"]["forced_tax_p50"] > 0
    assert mc["bands"][-1]["p50"] < 1_000_000  # nothing was spent, but the forced distributions paid tax


def test_contribution_limits_split_401k_sources(user, ira):
    k401 = Account.objects.create(owner=user, name="401k", account_type=AccountType.K401)
    day = dt.date(2026, 3, 1)
    for kind, amount, notes in [
        ("deposit", 10_000, "FXAIX - BEFORETAX CONTRIBUTION"),
        ("deposit", 5_000, "FXAIX - AFTERTAX CONTRIBUTION"),
        ("employer", 8_000, "FXAIX - MATCH CONTRIBUTION"),
    ]:
        CashFlow.objects.create(account=k401, kind=kind, date=day, amount=amount, notes=notes)
    CashFlow.objects.create(account=ira, kind="deposit", date=day, amount=3_000)
    CashFlow.objects.create(account=ira, kind="deposit", date=dt.date(2025, 3, 1), amount=7_000)  # other year

    data = contribution_limits(user, year=2026)  # default age 35: no catch-up
    k = data["k401"]
    assert (k["elective"], k["after_tax"], k["employer"]) == (10_000, 5_000, 8_000)
    assert (k["elective_limit"], k["elective_room"]) == (24_500, 14_500)
    assert (k["total"], k["total_room"]) == (23_000, 49_000)
    assert data["ira"] == {"contributed": 3_000, "limit": 7_500, "room": 4_500}

    s = UserSettings.for_user(user)
    s.current_age = 61
    s.save()
    assert contribution_limits(user, year=2026)["k401"]["elective_limit"] == 24_500 + 11_250


def test_projection_endpoints(api):
    assert api.get("/api/contribution-limits/").status_code == 200
    bad = api.patch("/api/settings/", {"return_assumptions": {"stock": {"return": 500, "volatility": 10}}}, format="json")
    assert bad.status_code == 400
    ok = api.patch("/api/settings/", {"return_assumptions": {"crypto": {"return": "10", "volatility": "60"}}}, format="json")
    assert ok.status_code == 200 and ok.json()["return_assumptions"] == {"crypto": {"return": 10.0, "volatility": 60.0}}
