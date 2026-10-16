import base64
import datetime as dt
import json
from decimal import Decimal as D
from unittest import mock

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from connections.coinbase import CoinbaseClient, build_jwt
from connections.exchange_data import CashMove, ExchangeError, Reward, Snapshot, Trade
from connections.exchange_sync import sync_exchange
from connections.kraken import KrakenClient, kraken_symbol, sign
from connections.models import ExchangeConnection
from portfolio.models import Account, AccountType, PriceHistory, Transaction
from portfolio.services.positions import compute_positions

pytestmark = pytest.mark.django_db


# -- Kraken ----------------------------------------------------------------------------------------


def test_kraken_signature_matches_the_documented_example():
    secret = "kQH5HW/8p1uGOVjbgWA7FunAmGO8lsSUXNsu3eow76sz84Q18fWxnyRzBHCd3pd5nE9qa99HAZtuZuj6F1huXg=="
    data = "nonce=1616492376594&ordertype=limit&pair=XBTUSD&price=37500&type=buy&volume=1.25"
    expected = "4/dpxb3iT4tp/ZCVEwSnEsLxx0bqyhLpdfOpc6fn7OR8+UClSV5n9E6aSS8MPtnRfp32bAb0nmbRn6H8ndwLUQ=="
    assert sign("/0/private/AddOrder", "1616492376594", data, secret) == expected


@pytest.mark.parametrize(
    "code, symbol",
    [
        ("XXBT", "BTC"), ("SOL.S", "SOL"), ("ZUSD", "USD"), ("XETH.F", "ETH"), ("USDC", "USDC"), ("SOL03.S", "SOL"),
        ("SOL03", "SOL"), ("DOT28.S", "DOT"), ("FLOW14.S", "FLOW"), ("ETH2.S", "ETH"), ("C98", "C98"), ("API3", "API3"),
    ],
)
def test_kraken_asset_codes(code, symbol):
    assert kraken_symbol(code) == symbol


JAN1 = 1735689600  # 2025-01-01 UTC

KRAKEN_PRIVATE = {
    "Balance": {"XXBT": "0.5", "SOL.S": "10", "SOL": "2", "ZUSD": "100", "USDC": "50", "ETH": "0"},
    "TradesHistory": {
        "count": 2,
        "trades": {
            "T1": {"pair": "XXBTZUSD", "time": JAN1, "type": "buy", "price": "90000", "vol": "0.5", "fee": "10"},
            "T2": {"pair": "SOLETH", "time": JAN1, "type": "buy", "price": "0.05", "vol": "1", "fee": "0"},
        },
    },
    "Ledgers": {
        "count": 5,
        "ledger": {
            "L1": {"type": "deposit", "subtype": "", "asset": "ZUSD", "amount": "1000", "fee": "0", "time": JAN1},
            "L2": {"type": "staking", "subtype": "", "asset": "SOL.S", "amount": "0.1", "fee": "0", "time": JAN1},
            "L3": {"type": "earn", "subtype": "reward", "asset": "SOL", "amount": "0.05", "fee": "0", "time": JAN1},
            "L4": {"type": "withdrawal", "subtype": "", "asset": "XXBT", "amount": "-0.1", "fee": "0", "time": JAN1},
            "L5": {"type": "trade", "subtype": "", "asset": "XXBT", "amount": "0.5", "fee": "0", "time": JAN1},
        },
    },
}
KRAKEN_PAIRS = {
    "XXBTZUSD": {"altname": "XBTUSD", "base": "XXBT", "quote": "ZUSD"},
    "SOLUSD": {"altname": "SOLUSD", "base": "SOL", "quote": "ZUSD"},
    "SOLETH": {"altname": "SOLETH", "base": "SOL", "quote": "XETH"},
}


def test_kraken_snapshot_normalizes_everything():
    client = KrakenClient("key", base64.b64encode(b"secret").decode())
    with (
        mock.patch.object(client, "private", side_effect=lambda method, data=None: KRAKEN_PRIVATE[method]),
        mock.patch.object(client, "public", return_value=KRAKEN_PAIRS),
    ):
        snap = client.snapshot()
    assert snap.balances == {"BTC": D("0.5"), "SOL": D(12), "USD": D(150)}
    [trade] = snap.trades
    assert (trade.symbol, trade.side, trade.quantity, trade.price, trade.fee) == ("BTC", "buy", D("0.5"), D(90000), D(10))
    assert trade.date == dt.date(2025, 1, 1)
    assert sorted(r.quantity for r in snap.rewards) == [D("0.05"), D("0.1")]
    assert [(c.amount, c.kind) for c in snap.cash_moves] == [(D(1000), "deposit")]
    # The BTC withdrawal to another wallet becomes a transfer, valued later at that day's close.
    assert [(t.symbol, t.side, t.quantity) for t in snap.transfers] == [("BTC", "sell", D("0.1"))]
    assert snap.skipped == 1  # the SOL/ETH trade


def test_kraken_errors_raise():
    client = KrakenClient("key", base64.b64encode(b"secret").decode())
    resp = mock.Mock(status_code=200)
    resp.json.return_value = {"error": ["EAPI:Invalid key"]}
    with (
        mock.patch("connections.kraken.requests.post", return_value=resp),
        pytest.raises(ExchangeError, match="Invalid key"),
    ):
        client.private("Balance")


def _kraken_resp(body):
    resp = mock.Mock(status_code=200)
    resp.json.return_value = body
    return resp


def test_kraken_waits_and_retries_when_rate_limited():
    client = KrakenClient("key", base64.b64encode(b"secret").decode())
    responses = [_kraken_resp({"error": ["EAPI:Rate limit exceeded"]}), _kraken_resp({"error": [], "result": {"ok": 1}})]
    with (
        mock.patch("connections.kraken.requests.post", side_effect=responses),
        mock.patch("connections.kraken.time.sleep") as sleep,
    ):
        assert client.private("Ledgers") == {"ok": 1}
    assert mock.call(10) in sleep.call_args_list  # backed off before retrying


def test_kraken_gives_up_after_repeated_rate_limits():
    client = KrakenClient("key", base64.b64encode(b"secret").decode())
    limited = _kraken_resp({"error": ["EAPI:Rate limit exceeded"]})
    with (
        mock.patch("connections.kraken.requests.post", return_value=limited),
        mock.patch("connections.kraken.time.sleep"),
        pytest.raises(ExchangeError, match="Rate limit"),
    ):
        client.private("Ledgers")


def test_kraken_paces_history_queries():
    client = KrakenClient("key", base64.b64encode(b"secret").decode())
    ok = _kraken_resp({"error": [], "result": {}})
    with (
        mock.patch("connections.kraken.requests.post", return_value=ok),
        mock.patch("connections.kraken.time.monotonic", return_value=client._counter_at),  # no time passes
        mock.patch("connections.kraken.time.sleep") as sleep,
    ):
        for _ in range(7):
            client.private("Ledgers")  # 7 x 2 = 14 fits under 15
        sleep.assert_not_called()
        client.private("Ledgers")  # 16 would not: wait for one point to decay
    [(wait,)] = [c.args for c in sleep.call_args_list]
    assert wait == pytest.approx(1 / 0.33)


# -- Coinbase --------------------------------------------------------------------------------------


def _b64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _claims(token):
    header, payload, _ = token.split(".")
    return json.loads(_b64(header)), json.loads(_b64(payload))


def test_coinbase_jwt_es256_verifies():
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()
    ).decode()
    name = "organizations/org/apiKeys/key"
    token = build_jwt(name, pem.replace("\n", "\\n"), "GET", "/v2/accounts")  # pasted keys often have literal \n
    header, claims = _claims(token)
    assert (header["alg"], header["kid"]) == ("ES256", name)
    assert (claims["sub"], claims["iss"], claims["uri"]) == (name, "cdp", "GET api.coinbase.com/v2/accounts")
    signing_input, sig = token.rsplit(".", 1)
    raw = _b64(sig)
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    key.public_key().verify(der, signing_input.encode(), ec.ECDSA(hashes.SHA256()))


def test_coinbase_jwt_ed25519_verifies():
    key = ed25519.Ed25519PrivateKey.generate()
    raw = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    token = build_jwt("key-id", base64.b64encode(raw + pub).decode(), "GET", "/v2/accounts")
    header, _ = _claims(token)
    assert header["alg"] == "EdDSA"
    signing_input, sig = token.rsplit(".", 1)
    key.public_key().verify(_b64(sig), signing_input.encode())


def _cb_tx(id_, type_, amount, usd=None, status="completed", currency="SOL"):
    t = {
        "id": id_, "type": type_, "status": status, "amount": {"amount": str(amount), "currency": currency},
        "created_at": "2025-01-05T12:00:00Z",
    }
    if usd is not None:
        t["native_amount"] = {"amount": str(usd), "currency": "USD"}
    return t


COINBASE = {
    "/v2/accounts": {"data": [
        {"id": "a-sol", "currency": {"code": "SOL"}, "balance": {"amount": "12", "currency": "SOL"}},
        {"id": "a-usd", "currency": "USD", "balance": {"amount": "25", "currency": "USD"}},
    ]},
    "/v2/accounts/a-sol/transactions": {"data": [
        _cb_tx("t1", "buy", 10, 1000),
        _cb_tx("t2", "advanced_trade_fill", -2, -300),
        _cb_tx("t3", "staking_reward", "0.5", 60),
        _cb_tx("t4", "send", -1, -150),
        _cb_tx("t5", "buy", 1, 100, status="pending"),
        _cb_tx("t6", "send", 4, 560),
        _cb_tx("t7", "staking_transfer", -3, -420),
    ]},
    "/v2/accounts/a-usd/transactions": {"data": [
        _cb_tx("u1", "fiat_deposit", 500, 500, currency="USD"),
        _cb_tx("u2", "buy", -1000, -1000, currency="USD"),
    ]},
}


def test_coinbase_snapshot_maps_transactions():
    client = CoinbaseClient("key", "secret")
    with mock.patch.object(client, "get", side_effect=lambda path, params=None: COINBASE[path]):
        snap = client.snapshot()
    assert snap.balances == {"SOL": D(12), "USD": D(25)}
    # Sends in and out of Coinbase move the units at that day's market value; internal wallet moves are skipped.
    assert [(t.side, t.quantity, t.price) for t in snap.trades] == [
        ("buy", D(10), D(100)), ("sell", D(2), D(150)), ("sell", D(1), D(150)), ("buy", D(4), D(140)),
    ]
    assert snap.skipped == 1
    [reward] = snap.rewards
    assert (reward.quantity, reward.value) == (D("0.5"), D(60))
    assert [(c.amount, c.kind) for c in snap.cash_moves] == [(D(500), "deposit")]
    assert snap.skipped == 1  # the send


def test_coinbase_refuses_keys_that_can_trade():
    client = CoinbaseClient("key", "secret")
    trading = {"/api/v3/brokerage/key_permissions": {"can_view": True, "can_trade": True, "can_transfer": False}}
    with (
        mock.patch.object(client, "get", side_effect=lambda path, params=None: trading.get(path, {"data": []})),
        pytest.raises(ExchangeError, match="solo lectura"),
    ):
        client.check()
    view_only = {"/api/v3/brokerage/key_permissions": {"can_view": True, "can_trade": False, "can_transfer": False}}
    with mock.patch.object(client, "get", side_effect=lambda path, params=None: view_only.get(path, {"data": []})):
        client.check()


# -- sync ------------------------------------------------------------------------------------------


class FakeExchange:
    def __init__(self, snap=None, error=None):
        self.snap, self.error = snap, error

    def check(self):
        if self.error:
            raise ExchangeError(self.error)

    def snapshot(self, since=None):
        self.since = since
        if self.error:
            raise ExchangeError(self.error)
        return self.snap


def snapshot(reward_value=D(60)):
    return Snapshot(
        balances={"SOL": D(12), "USD": D(25)},
        trades=[
            Trade("x:t1", dt.date(2025, 1, 5), "SOL", "buy", D(10), D(100)),
            Trade("x:t2", dt.date(2025, 2, 1), "SOL", "sell", D(2), D(150)),
        ],
        rewards=[Reward("x:r1", dt.date(2025, 3, 1), "SOL", D("0.5"), reward_value)],
        cash_moves=[CashMove("x:c1", dt.date(2025, 1, 4), D(500), "deposit")],
    )


@pytest.fixture
def no_network():
    def fake_refresh(assets):
        for a in assets:
            a.last_price = D(150)
            a.save()

    with (
        mock.patch("connections.exchange_sync.refresh_prices", side_effect=fake_refresh),
        mock.patch("connections.exchange_sync.update_history"),
    ):
        yield


@pytest.fixture
def conn(user):
    c = ExchangeConnection(owner=user, provider="kraken")
    c.set_credentials("api-key-123456", "secret")
    c.save()
    return c


def position(user, account, symbol="SOL"):
    return next(p for p in compute_positions(user) if p.account == account and p.symbol == symbol)


def test_sync_records_history_and_reconciles(user, conn, no_network):
    report = sync_exchange(conn, FakeExchange(snapshot()))
    assert report["error"] is None
    assert (report["trades"], report["rewards"], report["cash_flows"]) == (2, 1, 1)
    assert report["adjustments"] == 2  # opening SOL + cash

    conn.refresh_from_db()
    account = conn.account
    assert (account.name, account.account_type) == ("Kraken", AccountType.CRYPTO)
    sol = position(user, account)
    assert sol.quantity == 12
    assert sol.asset.sector == "Crypto"
    opening = Transaction.objects.get(account=account, external_id=f"exchange-adj:open:{sol.asset.id}")
    # No reported cost: estimated with the earliest known price (the first buy at 100), not today's 150.
    assert (opening.date, opening.quantity, opening.price) == (dt.date(2025, 1, 4), D("3.5"), D(100))
    reward = Transaction.objects.get(external_id="x:r1")
    assert (reward.kind, reward.price) == ("staking", D(120))  # $60 for 0.5 SOL
    assert position(user, account, "USD").quantity == 25


def test_sync_is_idempotent(user, conn, no_network):
    sync_exchange(conn, FakeExchange(snapshot()))
    count = Transaction.objects.count()
    second = sync_exchange(conn, FakeExchange(snapshot()))
    assert (second["trades"], second["rewards"], second["cash_flows"]) == (0, 0, 0)
    assert Transaction.objects.count() == count
    conn.refresh_from_db()
    assert position(user, conn.account).quantity == 12


def test_later_syncs_only_read_recent_history(user, conn, no_network):
    first = FakeExchange(snapshot())
    sync_exchange(conn, first)
    assert first.since is None  # first sync: everything
    second = FakeExchange(snapshot())
    sync_exchange(conn, second)
    conn.refresh_from_db()
    assert second.since == conn.last_synced_at.date() - dt.timedelta(days=7)
    full = FakeExchange(snapshot())
    sync_exchange(conn, full, full=True)
    assert full.since is None


def test_coinbase_stops_paging_at_older_transactions():
    client = CoinbaseClient("key", "secret")
    tx = lambda id_, day: {**_cb_tx(id_, "buy", 1, 100), "created_at": f"2025-{day}T00:00:00Z"}  # noqa: E731
    pages = {
        "/v2/accounts": {"data": [{"id": "a", "currency": "SOL", "balance": {"amount": "5", "currency": "SOL"}}]},
        "/v2/accounts/a/transactions": {"data": [tx("n1", "03-10"), tx("n2", "03-05")], "pagination": {"next_uri": "/p2"}},
        "/p2": {"data": [tx("n3", "03-02"), tx("old", "01-01")], "pagination": {"next_uri": "/p3"}},
    }
    calls = []

    def get(path, params=None):
        calls.append(path)
        return pages[path]

    with mock.patch.object(client, "get", side_effect=get):
        snap = client.snapshot(since=dt.date(2025, 3, 1))
    assert "/p3" not in calls
    assert [t.ext_id for t in snap.trades] == ["coinbase:n1", "coinbase:n2", "coinbase:n3"]


def test_kraken_sends_start_when_incremental():
    client = KrakenClient("key", base64.b64encode(b"secret").decode())
    seen = []

    def private(method, data=None):
        seen.append((method, (data or {}).get("start")))
        return {"Balance": {}, "TradesHistory": {"count": 0, "trades": {}}, "Ledgers": {"count": 0, "ledger": {}}}[method]

    with mock.patch.object(client, "private", side_effect=private), mock.patch.object(client, "public", return_value={}):
        client.snapshot(since=dt.date(2025, 1, 1))
    assert ("TradesHistory", JAN1) in seen and ("Ledgers", JAN1) in seen


def test_reward_without_value_uses_daily_close(user, conn, no_network):
    PriceHistory.objects.create(symbol="SOL-USD", date=dt.date(2025, 2, 28), close=D(140))
    sync_exchange(conn, FakeExchange(snapshot(reward_value=None)))
    assert Transaction.objects.get(external_id="x:r1").price == 140


def test_sync_error_is_recorded(conn):
    report = sync_exchange(conn, FakeExchange(error="Kraken: EAPI:Invalid key"))
    conn.refresh_from_db()
    assert report["error"] == "Kraken: EAPI:Invalid key"
    assert conn.last_error == "Kraken: EAPI:Invalid key"


def test_feed_an_existing_account(user, conn, no_network):
    existing = Account.objects.create(owner=user, name="Crypto", account_type=AccountType.CRYPTO)
    conn.account = existing
    conn.save()
    sync_exchange(conn, FakeExchange(snapshot()))
    assert position(user, existing).quantity == 12


# -- API -------------------------------------------------------------------------------------------


def test_create_validates_and_never_returns_keys(api, user):
    body = {"provider": "coinbase", "api_key": "organizations/o/apiKeys/abcdef", "api_secret": "super-secret"}
    with mock.patch("connections.views.exchange_client_for", return_value=FakeExchange()):
        resp = api.post("/api/exchanges/", body, format="json")
    assert resp.status_code == 201
    text = json.dumps(resp.json())
    assert "super-secret" not in text and "organizations" not in text
    assert resp.json()["key_hint"] == "abcdef"
    stored = ExchangeConnection.objects.get(owner=user)
    assert "super-secret" not in stored.api_secret_encrypted
    assert stored.api_secret == "super-secret"


def test_create_rejects_bad_keys(api):
    bad = FakeExchange(error="Kraken: EAPI:Invalid key")
    with mock.patch("connections.views.exchange_client_for", return_value=bad):
        resp = api.post("/api/exchanges/", {"provider": "kraken", "api_key": "k", "api_secret": "s"}, format="json")
    assert resp.status_code == 400
    assert not ExchangeConnection.objects.exists()
    other = {"provider": "binance", "api_key": "k", "api_secret": "s"}
    assert api.post("/api/exchanges/", other, format="json").status_code == 400


def test_sync_endpoint_and_ownership(api, user, other_user, conn, no_network):
    with mock.patch("connections.exchange_sync.client_for", return_value=FakeExchange(snapshot())):
        assert api.post(f"/api/exchanges/{conn.id}/sync/").status_code == 200
    assert len(api.get("/api/exchanges/").json()) == 1
    theirs = ExchangeConnection(owner=other_user, provider="kraken")
    theirs.set_credentials("k", "s")
    theirs.save()
    assert api.post(f"/api/exchanges/{theirs.id}/sync/").status_code == 404
    assert api.delete(f"/api/exchanges/{theirs.id}/").status_code == 404
    assert api.delete(f"/api/exchanges/{conn.id}/").status_code == 204
    assert Account.objects.filter(owner=user, name="Kraken").exists()  # history stays


def test_crypto_transfers_use_that_days_close(user, conn, no_network):
    from connections.exchange_data import Transfer
    from portfolio.models import PriceHistory

    PriceHistory.objects.create(symbol="SOL-USD", date=dt.date(2025, 1, 3), close=D(90))
    snap = snapshot()
    snap.balances["SOL"] = D(15)
    snap.transfers = [
        Transfer("x:d1", dt.date(2025, 1, 4), "SOL", "buy", D(4)),  # close of the 3rd carries forward
        Transfer("x:w1", dt.date(2025, 1, 2), "SOL", "sell", D(1), fee=D("0.01")),  # before any close: skipped
    ]
    report = sync_exchange(conn, FakeExchange(snap))
    assert report["transfers"] == 1 and report["skipped"] == 1
    received = Transaction.objects.get(external_id="x:d1")
    assert (received.kind, received.quantity, received.price) == ("buy", D(4), D(90))
    conn.refresh_from_db()
    assert position(user, conn.account).quantity == 15
