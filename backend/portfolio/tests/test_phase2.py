import datetime as dt
from decimal import Decimal as D
from unittest import mock

import pytest

from portfolio.models import (
    Account,
    AccountType,
    Asset,
    AssetClass,
    EquityGrant,
    PriceHistory,
    Transaction,
    UserSettings,
)
from portfolio.services.allocation import compute_allocation
from portfolio.services.equity import compute_equity
from portfolio.services.positions import compute_positions, compute_summary
from portfolio.services.risk import parse_custom, portfolio_metrics, stress_test
from portfolio.services.taxes import compute_tax_lots

pytestmark = pytest.mark.django_db


def tx(account, asset, kind, date, **fields):
    values = {k: D(str(v)) if isinstance(v, (int, float, str)) else v for k, v in fields.items()}
    return Transaction.objects.create(account=account, asset=asset, kind=kind, date=date, **values)


def on(date):
    return mock.patch("django.utils.timezone.localdate", return_value=date)


def position(user, account, symbol):
    return next(p for p in compute_positions(user) if p.account == account and p.symbol == symbol)


# -- tax lots --------------------------------------------------------------------------------------


def test_sell_consumes_oldest_lots_first(user, broker, voo):
    tx(broker, voo, "buy", dt.date(2025, 1, 1), quantity=10, price=100)
    tx(broker, voo, "buy", dt.date(2025, 6, 1), quantity=10, price=120)
    tx(broker, voo, "sell", dt.date(2025, 7, 1), quantity=15, price=130)
    [lot] = position(user, broker, "VOO").lots
    assert (lot.date, lot.quantity, lot.unit_cost) == (dt.date(2025, 6, 1), 5, 120)


def test_split_and_transfer_keep_lot_dates(user, broker, ira, voo):
    tx(broker, voo, "buy", dt.date(2025, 1, 1), quantity=10, price=100)
    tx(broker, voo, "split", dt.date(2025, 2, 1), quantity=2)
    tx(broker, voo, "transfer", dt.date(2025, 3, 1), quantity=5, to_account=ira)
    [moved] = position(user, ira, "VOO").lots
    assert (moved.date, moved.quantity, moved.unit_cost) == (dt.date(2025, 1, 1), 5, 50)
    assert position(user, broker, "VOO").lots[0].quantity == 15


def test_short_long_terms_harvest_and_wash_sale(user, broker, voo):
    tx(broker, voo, "buy", dt.date(2025, 1, 1), quantity=10, price=100)  # long-term, +100 at 110
    tx(broker, voo, "buy", dt.date(2025, 12, 1), quantity=10, price=120)  # short-term, −100
    tx(broker, voo, "buy", dt.date(2026, 2, 20), quantity=1, price=110)  # recent buy → wash-sale risk
    with on(dt.date(2026, 3, 1)):
        t = compute_tax_lots(user)
        summary = compute_summary(user)
    assert t["long_gain"] == 100
    assert t["short_gain"] == -100
    [h] = t["harvest"]
    assert h["term"] == "short"
    assert h["tax_saving"] == D(24)  # 100 × 24% ordinary rate
    assert h["wash_sale_risk"] is True
    # Per-position netting: the short-term loss doesn't create a refund; the long-term gain pays 15%.
    assert summary["estimated_taxes"] == D(15)


def test_lots_about_to_turn_long_term(user, broker, voo):
    tx(broker, voo, "buy", dt.date(2025, 3, 20), quantity=10, price=100)
    with on(dt.date(2026, 3, 1)):
        [soon] = compute_tax_lots(user)["soon_long_term"]
    assert soon["days_to_long_term"] == 20
    assert soon["saving_if_wait"] == D(9)  # gain 100 × (24% − 15%)


def test_crypto_losses_are_not_subject_to_wash_sale(user, broker):
    sol = Asset.objects.create(owner=user, symbol="SOL", asset_class=AssetClass.CRYPTO, last_price=D(50))
    tx(broker, sol, "buy", dt.date(2026, 2, 25), quantity=1, price=100)
    with on(dt.date(2026, 3, 1)):
        [h] = compute_tax_lots(user)["harvest"]
    assert h["wash_sale_rule"] is False
    assert h["wash_sale_risk"] is False


# -- private equity --------------------------------------------------------------------------------


@pytest.fixture
def grant(user):
    acc = Account.objects.create(owner=user, name="Eq", account_type=AccountType.PRIVATE_EQUITY, is_liquid=False)
    return EquityGrant.objects.create(
        account=acc, company="Co", quantity=4800, strike=2, fmv=10, vesting_start=dt.date(2024, 1, 15),
        vesting_months=48, cliff_months=12, liquidity_discount_pct=20, expiration_date=dt.date(2025, 3, 1),
    )


def test_cliff_then_monthly_vesting(grant):
    assert grant.vested_quantity(dt.date(2025, 1, 14)) == 0
    assert grant.vested_quantity(dt.date(2025, 1, 15)) == 1200
    assert grant.vested_quantity(dt.date(2026, 7, 20)) == 3000
    assert grant.vested_quantity(dt.date(2028, 2, 1)) == 4800
    assert grant.next_vest_date(dt.date(2025, 1, 15)) == dt.date(2025, 2, 15)


def test_only_vested_discounted_value_counts(user, grant):
    with on(dt.date(2025, 1, 15)):
        s = compute_summary(user)
        eq = compute_equity(user)
    assert s["net_worth"] == D(7200)  # 1200 vested × (10 × 0.8 − 2)
    [g] = eq["grants"]
    assert g["unvested_value"] == D(3600 * 6)
    assert g["exercise_cost"] == D(2400)
    assert g["exercise_tax"] == D(9600) * D("0.24")  # NSO spread at the undiscounted FMV
    assert eq["alerts"][0]["level"] == "critical"


def test_iso_has_no_regular_tax_at_exercise_but_amt_preference(user, grant):
    grant.grant_type = "iso"
    grant.save()
    with on(dt.date(2025, 1, 15)):
        [g] = compute_equity(user)["grants"]
    assert g["exercise_tax"] == 0
    assert g["amt_preference"] == D(9600)


# -- household allocation --------------------------------------------------------------------------


def test_rebalance_trims_tax_advantaged_account_first(user, broker, voo):
    k401 = Account.objects.create(owner=user, name="401k", account_type=AccountType.K401, is_liquid=False)
    sol = Asset.objects.create(owner=user, symbol="SOL", asset_class=AssetClass.CRYPTO, last_price=D(100))
    tx(broker, voo, "buy", dt.date(2024, 1, 1), quantity=10, price=100)  # 1100, taxable gain
    tx(k401, voo, "buy", dt.date(2024, 1, 1), quantity=10, price=100)  # 1100, tax-deferred
    tx(broker, sol, "buy", dt.date(2024, 1, 1), quantity=10, price=100)  # 1000
    s = UserSettings.for_user(user)
    s.target_allocation = {"us_equity": 50, "crypto": 50}
    s.save()

    a = compute_allocation(user)
    rows = {r["key"]: r for r in a["rows"]}
    assert rows["us_equity"]["action"] == "sell"
    assert rows["crypto"]["action"] == "buy"
    [plan] = a["sells"]
    assert plan["amount"] == 600
    first = plan["items"][0]
    assert (first["account"], first["sell"], first["estimated_tax"]) == ("401k", 600, 0)


def test_private_equity_over_target_is_locked_not_sold(user):
    eq = Account.objects.create(owner=user, name="Eq", account_type=AccountType.PRIVATE_EQUITY, is_liquid=False)
    EquityGrant.objects.create(account=eq, company="Co", quantity=10, strike=0, fmv=100)
    s = UserSettings.for_user(user)
    s.target_allocation = {"us_equity": 100}
    s.save()
    a = compute_allocation(user)
    assert {r["key"]: r["action"] for r in a["rows"]}["private_equity"] == "locked"
    assert a["sells"] == []


def test_target_allocation_and_benchmark_validation(api):
    assert api.patch("/api/settings/", {"target_allocation": {"us_equity": 60}}, format="json").status_code == 400
    ok = api.patch("/api/settings/", {"target_allocation": {"us_equity": 60, "bonds": 40}}, format="json")
    assert ok.status_code == 200
    assert api.patch("/api/settings/", {"benchmark": "NOPE"}, format="json").status_code == 400


# -- risk ------------------------------------------------------------------------------------------


def test_stress_uses_the_more_severe_of_category_and_sector_shock(user, broker):
    sol = Asset.objects.create(
        owner=user, symbol="SOL", asset_class=AssetClass.CRYPTO, sector="Crypto", last_price=D(100)
    )
    tx(broker, sol, "buy", dt.date(2024, 1, 1), quantity=10, price=100)
    eq = Account.objects.create(owner=user, name="Eq", account_type=AccountType.PRIVATE_EQUITY, is_liquid=False)
    EquityGrant.objects.create(account=eq, company="Co", quantity=10, strike=0, fmv=100, sector="Crypto")

    result = stress_test(compute_positions(user), {"categories": {"crypto": -65}, "sectors": {"Crypto": -50}})
    assert result["change"] == D(-1150)  # SOL −65%, the crypto company −50%
    assert result["liquid_change"] == D(-650)


def test_parse_custom_scenario():
    sc = parse_custom("crypto:-50, us_equity:-20,sector.Crypto:-60,bad")
    assert sc["categories"] == {"crypto": -50.0, "us_equity": -20.0}
    assert sc["sectors"] == {"Crypto": -60.0}


def test_portfolio_drawdown(user, broker, voo):
    start = dt.date(2025, 1, 1)
    for i, close in enumerate([100, 110, 99, 105]):
        PriceHistory.objects.create(symbol="VOO", date=start + dt.timedelta(days=i), close=D(close))
    voo.last_price = D(105)
    voo.save()
    tx(broker, voo, "buy", start, quantity=1, price=100)
    with mock.patch("portfolio.services.performance.timezone.localdate", return_value=start + dt.timedelta(days=3)):
        m = portfolio_metrics(user)
    assert m["max_drawdown"] == pytest.approx(10.0)
    assert m["current_drawdown"] == pytest.approx((1 - 105 / 110) * 100)


def test_phase2_endpoints(api, broker, voo):
    tx(broker, voo, "buy", dt.date(2025, 1, 1), quantity=1, price=100)
    for url in ["/api/tax-lots/", "/api/allocation/", "/api/risk/", "/api/risk/?custom=crypto:-50", "/api/equity/"]:
        assert api.get(url).status_code == 200, url
    assert "grant_types" in api.get("/api/choices/").json()
