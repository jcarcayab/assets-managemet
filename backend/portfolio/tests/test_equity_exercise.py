import datetime as dt
from decimal import Decimal as D

import pytest

from portfolio.models import Account, AccountType, EquityExercise, EquityGrant, UserSettings
from portfolio.services.equity import compute_equity
from portfolio.services.positions import compute_positions, compute_summary

pytestmark = pytest.mark.django_db


@pytest.fixture
def grant(user):
    acc = Account.objects.create(owner=user, name="Co Equity", account_type=AccountType.PRIVATE_EQUITY, is_liquid=False)
    return EquityGrant.objects.create(account=acc, company="Co", grant_type="nso", quantity=100, strike=10, fmv=20)


def test_partial_exercise_splits_options_and_shares(user, grant):
    EquityExercise.objects.create(grant=grant, date=dt.date(2026, 3, 1), quantity=30, fmv=15)

    rows = {p.name: p for p in compute_positions(user) if p.asset is None}
    options, shares = rows["Opciones NSO sin ejercer"], rows["Acciones (opciones NSO ejercidas)"]
    assert (options.quantity, options.market_value, options.cost_basis) == (70, 700, 0)
    # NSO shares: tax basis is the FMV on exercise day (the spread was taxed as wages then).
    assert (shares.quantity, shares.market_value, shares.cost_basis) == (30, 600, 450)
    assert compute_summary(user)["net_worth"] == 1300

    rate = UserSettings.for_user(user).ordinary_income_tax_pct
    [g] = compute_equity(user)["grants"]
    assert (g["open_options"], g["shares"], g["exercise_cost"]) == (70, 30, 700)
    [ex] = g["exercises"]
    assert (ex["cost"], ex["spread"], ex["income_tax"]) == (300, 150, 150 * rate / 100)


def test_fully_exercised_grant_has_only_shares(user, grant):
    EquityExercise.objects.create(grant=grant, date=dt.date(2026, 3, 1), quantity=100, fmv=20)
    names = [p.name for p in compute_positions(user) if p.asset is None]
    assert names == ["Acciones (opciones NSO ejercidas)"]


def test_exercise_api_checks_remaining_options_and_ownership(api, grant, other_user):
    ok = api.post("/api/equity-exercises/", {"grant": grant.id, "date": "2026-10-01", "quantity": "1", "fmv": "11.6"})
    assert ok.status_code == 201, ok.json()
    too_many = api.post("/api/equity-exercises/", {"grant": grant.id, "date": "2026-10-02", "quantity": "100", "fmv": "11.6"})
    assert too_many.status_code == 400 and "99" in str(too_many.json())

    theirs_acc = Account.objects.create(owner=other_user, name="X", account_type=AccountType.PRIVATE_EQUITY)
    theirs = EquityGrant.objects.create(account=theirs_acc, company="X", quantity=10, strike=1, fmv=2)
    assert api.post("/api/equity-exercises/", {"grant": theirs.id, "date": "2026-10-01", "quantity": "1", "fmv": "2"}).status_code == 400
    assert api.get("/api/equity-grants/").json()[0]["exercised_quantity"] == D(1)


def test_exit_scenarios_after_tax(user, grant):
    from portfolio.models import UserSettings

    s = UserSettings.for_user(user)
    s.ordinary_income_tax_pct, s.capital_gains_tax_pct = D(30), D(15)
    s.save()
    EquityExercise.objects.create(grant=grant, date=dt.date(2026, 3, 1), quantity=20, fmv=15)
    [company] = compute_equity(user)["scenarios"]
    rows = {r["multiple"]: r for r in company["rows"]}
    assert rows[0]["gross"] == 0 and rows[0]["net"] == 0
    # 2× FMV = $40: 20 shares → 800 (gain over the $15 basis 500 × 15% = 75); 80 options → 80 × 30 = 2400 (NSO 30%).
    assert rows[2]["gross"] == 3200
    assert rows[2]["net"] == 3200 - 75 - 720


def test_leaving_stops_vesting_and_starts_the_exercise_window(user, grant):
    from django.utils import timezone

    today = timezone.localdate()
    grant.vesting_start, grant.vesting_months, grant.cliff_months = today - dt.timedelta(days=730), 48, 12
    grant.termination_date = today - dt.timedelta(days=30)
    grant.save()
    [g] = compute_equity(user)["grants"]
    assert g["vested"] < 50 and g["next_vest_date"] is None  # stopped about a month short of 2 years
    assert g["exercise_deadline"] == grant.termination_date + dt.timedelta(days=90)
    [alert] = compute_equity(user)["alerts"]
    assert alert["level"] == "critical" and "60 días" in alert["message"]

    grant.termination_date = today - dt.timedelta(days=120)
    grant.save()
    data = compute_equity(user)
    assert data["grants"][0]["options_lost"] and data["grants"][0]["value"] == 0
    assert "se perdieron" in data["alerts"][0]["message"]
