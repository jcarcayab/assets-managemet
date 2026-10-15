from decimal import Decimal as D
from unittest import mock

import pytest
from rest_framework.test import APIClient

from portfolio.models import Account, Asset, Snapshot
from portfolio.tests.conftest import buy

pytestmark = pytest.mark.django_db


def test_endpoints_require_login():
    client = APIClient()
    for url in ["/api/summary/", "/api/positions/", "/api/accounts/", "/api/transactions/"]:
        assert client.get(url).status_code == 403


def test_login_flow(user):
    client = APIClient(enforce_csrf_checks=True)
    client.get("/api/auth/session/")
    token = client.cookies["csrftoken"].value
    bad = client.post("/api/auth/login/", {"username": "alice", "password": "nope"}, HTTP_X_CSRFTOKEN=token)
    assert bad.status_code == 400
    ok = client.post(
        "/api/auth/login/", {"username": "alice", "password": "a-long-test-password"}, HTTP_X_CSRFTOKEN=token
    )
    assert ok.status_code == 200
    assert client.get("/api/auth/session/").json()["user"]["username"] == "alice"


def test_create_transaction_and_read_summary(api, broker, voo):
    resp = api.post(
        "/api/transactions/",
        {"account": broker.id, "asset": voo.id, "kind": "buy", "date": "2025-02-01", "quantity": "2", "price": "100"},
        format="json",
    )
    assert resp.status_code == 201, resp.json()
    summary = api.get("/api/summary/").json()
    assert summary["net_worth"] == 220
    positions = api.get("/api/positions/").json()
    assert positions[0]["symbol"] == "VOO"


def test_cannot_use_another_users_account(api, other_user, voo):
    foreign = Account.objects.create(owner=other_user, name="Theirs")
    resp = api.post(
        "/api/transactions/",
        {"account": foreign.id, "asset": voo.id, "kind": "buy", "date": "2025-02-01", "quantity": "1", "price": "1"},
        format="json",
    )
    assert resp.status_code == 400
    assert api.get(f"/api/accounts/{foreign.id}/").status_code == 404


def test_asset_with_transactions_cannot_be_deleted(api, broker, voo):
    buy(broker, voo, 1, 100)
    assert api.delete(f"/api/assets/{voo.id}/").status_code == 409


def test_take_snapshot(api, user, broker, voo):
    buy(broker, voo, 1, 100)
    resp = api.post("/api/snapshots/", {"notes": "test"}, format="json")
    assert resp.status_code == 201
    assert Snapshot.objects.get(owner=user).net_worth == D(110)


def test_refresh_prices_updates_live_assets_only(api, user):
    Asset.objects.create(owner=user, symbol="VOO", price_source="yahoo")
    Asset.objects.create(owner=user, symbol="SOL", price_source="coingecko", source_id="solana")
    Asset.objects.create(owner=user, symbol="FUND", price_source="manual", manual_price=10)
    fetchers = {"yahoo": lambda ids: {"VOO": D(500)}, "coingecko": lambda ids: {}}
    with mock.patch.dict("portfolio.services.prices.FETCHERS", fetchers):
        result = api.post("/api/prices/refresh/").json()
    assert result == {"updated": ["VOO"], "failed": ["SOL"]}
    assert Asset.objects.get(symbol="VOO").last_price == 500


def test_settings_roundtrip(api):
    assert api.get("/api/settings/").json()["take_profit_1_pct"] == 10
    resp = api.patch("/api/settings/", {"retirement_age": 60}, format="json")
    assert resp.json()["retirement_age"] == 60
