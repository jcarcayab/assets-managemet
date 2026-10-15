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
    TaxTreatment,
    Transaction,
)
from portfolio.services.exposure import compute_exposure
from portfolio.services.history import update_history
from portfolio.services.performance import compute_performance, daily_series, xirr
from portfolio.services.positions import compute_positions, compute_summary

pytestmark = pytest.mark.django_db

JAN = dt.date(2025, 1, 1)


def tx(account, asset, kind, day=1, **fields):
    values = {k: D(str(v)) if isinstance(v, (int, float, str)) else v for k, v in fields.items()}
    return Transaction.objects.create(
        account=account, asset=asset, kind=kind, date=JAN + dt.timedelta(days=day - 1), **values
    )


def by_symbol(user):
    return {(p.account.name, p.symbol): p for p in compute_positions(user)}


# -- ledger kinds ----------------------------------------------------------------------------------


def test_dividend_credits_cash_and_fee_debits_it(user, broker, voo):
    tx(broker, voo, "buy", quantity=10, price=100)
    tx(broker, voo, "dividend", day=2, amount=15)
    tx(broker, voo, "fee", day=3, amount=5)

    pos = by_symbol(user)
    assert pos[("Broker", "VOO")].income == 15
    assert pos[("Broker", "VOO")].fees_paid == 5
    assert pos[("Broker", "USD")].market_value == 10


def test_split_multiplies_quantity_keeps_cost(user, broker, voo):
    tx(broker, voo, "buy", quantity=10, price=100)
    tx(broker, voo, "split", day=2, quantity=2)
    p = by_symbol(user)[("Broker", "VOO")]
    assert p.quantity == 20
    assert p.cost_basis == 1000
    assert p.avg_cost == 50


def test_transfer_moves_units_with_cost_basis(user, broker, ira, voo):
    tx(broker, voo, "buy", quantity=10, price=100)
    tx(broker, voo, "transfer", day=2, quantity=4, price=105, to_account=ira)
    pos = by_symbol(user)
    assert pos[("Broker", "VOO")].quantity == 6
    assert pos[("IRA", "VOO")].quantity == 4
    assert pos[("IRA", "VOO")].cost_basis == 400
    assert pos[("Broker", "VOO")].realized == 0


def test_staking_adds_units_at_fair_value_and_counts_as_income(user):
    acc = Account.objects.create(owner=user, name="Crypto", account_type=AccountType.CRYPTO)
    sol = Asset.objects.create(owner=user, symbol="SOL", asset_class=AssetClass.CRYPTO, last_price=D(200))
    tx(acc, sol, "buy", quantity=10, price=100)
    tx(acc, sol, "staking", day=2, quantity=1, price=150)
    p = by_symbol(user)[("Crypto", "SOL")]
    assert p.quantity == 11
    assert p.cost_basis == 1150
    assert p.income == 150


@pytest.mark.parametrize(
    "payload, field",
    [
        ({"kind": "dividend", "amount": "0"}, "amount"),
        ({"kind": "transfer", "quantity": "1"}, "to_account"),
        ({"kind": "buy", "quantity": "0", "price": "1"}, "quantity"),
    ],
)
def test_transaction_kind_validation(api, broker, voo, payload, field):
    body = {"account": broker.id, "asset": voo.id, "date": "2025-01-01", **payload}
    resp = api.post("/api/transactions/", body, format="json")
    assert resp.status_code == 400
    assert field in resp.json()


def test_transfer_to_same_account_rejected(api, broker, voo):
    body = {
        "account": broker.id, "asset": voo.id, "date": "2025-01-01", "kind": "transfer", "quantity": "1",
        "to_account": broker.id,
    }
    assert api.post("/api/transactions/", body, format="json").status_code == 400


def test_withdrawal_sign_follows_kind(api, broker):
    body = {"account": broker.id, "kind": "withdrawal", "date": "2025-01-01", "amount": "300"}
    assert api.post("/api/cash-flows/", body, format="json").json()["amount"] == -300


# -- taxes -----------------------------------------------------------------------------------------


def test_tax_treatment_defaults_from_account_type(user):
    def make(name, kind):
        return Account.objects.create(owner=user, name=name, account_type=kind).tax_treatment

    assert make("R", AccountType.ROTH_IRA) == TaxTreatment.TAX_FREE
    assert make("K", AccountType.K401) == TaxTreatment.TAX_DEFERRED
    assert make("B", AccountType.BROKERAGE) == TaxTreatment.TAXABLE


def test_after_tax_net_worth(user, broker, voo):
    k401 = Account.objects.create(owner=user, name="401k", account_type=AccountType.K401, is_liquid=False)
    roth = Account.objects.create(owner=user, name="Roth", account_type=AccountType.ROTH_IRA, is_liquid=False)
    eq = Account.objects.create(owner=user, name="Eq", account_type=AccountType.PRIVATE_EQUITY, is_liquid=False)
    tx(broker, voo, "buy", quantity=10, price=100)  # value 1100, gain 100 × 15% = 15
    tx(k401, voo, "buy", quantity=10, price=100)  # whole 1100 × 22% = 242
    tx(roth, voo, "buy", quantity=10, price=100)  # 0
    EquityGrant.objects.create(account=eq, company="Co", quantity=100, strike=10, fmv=20)  # spread 1000 × 24% = 240

    s = compute_summary(user)
    assert s["estimated_taxes"] == D(497)
    assert s["after_tax_net_worth"] == s["net_worth"] - 497


# -- exposure --------------------------------------------------------------------------------------


def test_exposure_groups_same_index_and_flags_concentration(user, broker, ira, voo):
    voo.underlying = "S&P 500"
    voo.save()
    fxaix = Asset.objects.create(owner=user, symbol="FXAIX", underlying="S&P 500", last_price=D(100))
    tdf = Asset.objects.create(
        owner=user, symbol="TDF", last_price=D(100), exposures={"us_equity": 60, "intl_equity": 30, "bonds": 10}
    )
    sol = Asset.objects.create(owner=user, symbol="SOL", asset_class=AssetClass.CRYPTO, sector="Crypto", last_price=D(100))
    eq = Account.objects.create(owner=user, name="Eq", account_type=AccountType.PRIVATE_EQUITY, is_liquid=False)
    EquityGrant.objects.create(account=eq, company="Co", quantity=10, strike=0, fmv=100, sector="Crypto")
    tx(broker, voo, "buy", quantity=10, price=110)  # 1100
    tx(ira, fxaix, "buy", quantity=9, price=100)  # 900
    tx(ira, tdf, "buy", quantity=10, price=100)  # 1000
    tx(broker, sol, "buy", quantity=10, price=100)  # 1000, + grant 1000 → 2000 in the Crypto sector

    e = compute_exposure(user)
    assert e["gross_assets"] == 5000
    assert next(h for h in e["by_holding"] if h["key"] == "S&P 500")["value"] == 2000
    cat = {c["key"]: c["value"] for c in e["by_category"]}
    assert cat["us_equity"] == 2600
    assert cat["intl_equity"] == 300
    assert {(a["kind"], a["label"]) for a in e["alerts"]} >= {("holding", "S&P 500"), ("sector", "Crypto")}


def test_exposures_must_sum_to_100(api, voo):
    assert api.patch(f"/api/assets/{voo.id}/", {"exposures": {"us_equity": 50, "bonds": 10}}, format="json").status_code == 400
    assert api.patch(f"/api/assets/{voo.id}/", {"exposures": {"us_equity": 90, "bonds": 10}}, format="json").status_code == 200


# -- performance -----------------------------------------------------------------------------------


@pytest.fixture
def today():
    day = JAN + dt.timedelta(days=3)
    with mock.patch("portfolio.services.performance.timezone.localdate", return_value=day):
        yield day


def _history(symbol, closes):
    for i, c in enumerate(closes):
        PriceHistory.objects.create(symbol=symbol, date=JAN + dt.timedelta(days=i), close=D(c))


def _total(perf):
    return next(p for p in perf["periods"] if p["key"] == "Total")


def test_twr_ignores_timing_of_contributions(user, broker, voo, today):
    _history("VOO", [100, 110, 110])
    voo.last_price = D(121)
    voo.save()
    tx(broker, voo, "buy", quantity=10, price=100)
    tx(broker, voo, "buy", day=3, quantity=10, price=110)

    assert [d.value for d in daily_series(user)] == [1000, 1100, 2200, 2420]
    perf = compute_performance(user, benchmark="SPY")
    assert _total(perf)["twr"] == pytest.approx(21.0)
    assert perf["net_invested"] == pytest.approx(2100)


def test_benchmark_and_public_market_equivalent(user, broker, voo, today):
    _history("VOO", [100, 100, 100])
    _history("SPY", [100, 100, 100, 110])
    voo.last_price = D(100)
    voo.save()
    tx(broker, voo, "buy", quantity=10, price=100)
    tx(broker, voo, "buy", day=3, quantity=11, price=100)

    perf = compute_performance(user, benchmark="SPY")
    assert _total(perf)["benchmark"] == pytest.approx(10.0)
    assert perf["benchmark_equivalent"] == pytest.approx(2310)  # 21 SPY units at 110


def test_account_performance_counts_transfers_as_flows(user, broker, ira, voo, today):
    _history("VOO", [100, 100, 100, 100])
    tx(broker, voo, "buy", quantity=10, price=100)
    tx(broker, voo, "transfer", day=2, quantity=5, price=100, to_account=ira)

    ira_days = daily_series(user, ira.id)
    assert ira_days[0].date == JAN + dt.timedelta(days=1)
    assert (ira_days[0].flow, ira_days[0].value) == (500, 500)
    assert daily_series(user, broker.id)[1].flow == -500


def test_dividends_count_as_return_not_contribution(user, broker, voo, today):
    _history("VOO", [100, 100, 100, 100])
    voo.last_price = D(100)
    voo.save()
    tx(broker, voo, "buy", quantity=10, price=100)
    tx(broker, voo, "dividend", day=2, amount=50)
    assert _total(compute_performance(user, benchmark="SPY"))["twr"] == pytest.approx(5.0)


def test_short_period_money_weighted_return_is_not_annualized(user, broker, voo):
    start = dt.date(2025, 1, 1)
    _history("VOO", [100] * 60 + [110])
    voo.last_price = D(110)
    voo.save()
    tx(broker, voo, "buy", quantity=10, price=100)
    with mock.patch("portfolio.services.performance.timezone.localdate", return_value=start + dt.timedelta(days=60)):
        perf = compute_performance(user, benchmark="SPY")
    total = _total(perf)
    assert total["xirr_annualized"] is False
    assert total["xirr"] == pytest.approx(10.0, abs=0.01)  # +10% over 60 days, not ~78% annualized
    assert perf["recent_contribution_share"] == 0


def test_xirr_simple_year():
    assert xirr([(JAN, -1000.0), (JAN + dt.timedelta(days=365), 1100.0)]) == pytest.approx(0.10, abs=1e-6)
    assert xirr([(JAN, -1000.0)]) is None


def test_update_history_is_incremental(user, broker, voo):
    tx(broker, voo, "buy", quantity=1, price=100)
    calls = []

    def fake(tickers, start):
        calls.append((sorted(tickers), start))
        return {t: [(start, D(1)), (start + dt.timedelta(days=1), D(2))] for t in tickers}

    with mock.patch("portfolio.services.history.timezone.localdate", return_value=dt.date(2025, 3, 1)):
        first = update_history(user, fetcher=fake)
        update_history(user, fetcher=fake)
    assert first["saved"] > 0
    assert calls[0][1] == JAN - dt.timedelta(days=7)
    assert {"VOO", "SPY"} <= set(calls[0][0])
    assert calls[1][1] == JAN - dt.timedelta(days=6)  # resumes from the last stored day


def test_phase1_endpoints(api, broker, voo, other_user):
    tx(broker, voo, "buy", quantity=1, price=100)
    assert api.get("/api/performance/").status_code == 200
    assert api.get("/api/income/").status_code == 200
    assert api.get("/api/exposure/").status_code == 200
    assert api.get("/api/performance/?benchmark=NOPE").status_code == 400
    foreign = Account.objects.create(owner=other_user, name="Theirs")
    assert api.get(f"/api/performance/?account={foreign.id}").status_code == 404
    choices = api.get("/api/choices/").json()
    assert {"tax_treatments", "exposure_categories", "benchmarks", "cash_flow_kinds"} <= choices.keys()
