import datetime as dt
from decimal import Decimal as D
from unittest import mock

import pytest

from connections.models import PlaidItem
from connections.plaid import PlaidClient, PlaidError
from connections.sync import link_item, sync_item
from portfolio.models import Account, AccountType, Asset, CashFlow, Liability, TaxTreatment, Transaction
from portfolio.services.positions import compute_positions

pytestmark = pytest.mark.django_db

SECURITIES = [
    {"security_id": "sec-voo", "ticker_symbol": "VOO", "type": "etf", "name": "Vanguard S&P 500 ETF", "close_price": 500},
    {"security_id": "sec-cit-abcdef", "ticker_symbol": None, "type": "mutual fund", "name": "Target 2055 Trust",
     "close_price": 29},
    {"security_id": "sec-cash", "ticker_symbol": "CUR:USD", "type": "cash", "is_cash_equivalent": True, "name": "Cash"},
]
ACCOUNTS = [
    {"account_id": "inv1", "name": "Brokerage", "mask": "1234", "type": "investment", "subtype": "brokerage",
     "balances": {"current": 7700}},
    {"account_id": "inv2", "name": "401k Plan", "mask": "5678", "type": "investment", "subtype": "401k",
     "balances": {"current": 3000}},
    {"account_id": "dep1", "name": "Checking", "mask": "9999", "type": "depository", "subtype": "checking",
     "balances": {"current": 2500}},
    {"account_id": "cc1", "name": "Card", "mask": "4444", "type": "credit", "subtype": "credit card",
     "balances": {"current": 800}},
]
TRANSACTIONS = [
    {"investment_transaction_id": "t-dep", "account_id": "inv1", "security_id": None, "date": "2025-02-15",
     "type": "cash", "subtype": "deposit", "quantity": 0, "amount": -5000, "price": 0, "name": "ACH deposit"},
    {"investment_transaction_id": "t-buy", "account_id": "inv1", "security_id": "sec-voo", "date": "2025-03-01",
     "type": "buy", "subtype": "buy", "quantity": 10, "amount": 4000, "price": 400, "fees": 0, "name": "Buy VOO"},
    {"investment_transaction_id": "t-sell", "account_id": "inv1", "security_id": "sec-voo", "date": "2025-06-01",
     "type": "sell", "subtype": "sell", "quantity": -5, "amount": -2250, "price": 450, "fees": 0, "name": "Sell VOO"},
    {"investment_transaction_id": "t-div", "account_id": "inv1", "security_id": "sec-voo", "date": "2025-07-01",
     "type": "cash", "subtype": "dividend", "quantity": 0, "amount": -30, "price": 0, "name": "VOO dividend"},
    {"investment_transaction_id": "t-fee", "account_id": "inv1", "security_id": None, "date": "2025-08-01",
     "type": "fee", "subtype": "account fee", "quantity": 0, "amount": 5, "price": 0, "name": "Fee"},
    {"investment_transaction_id": "t-xfer", "account_id": "inv1", "security_id": "sec-voo", "date": "2025-08-02",
     "type": "transfer", "subtype": "transfer", "quantity": 1, "amount": 0, "price": 0, "name": "ACATS"},
]


def holdings(voo_qty=15):
    return {
        "accounts": ACCOUNTS,
        "securities": SECURITIES,
        "holdings": [
            {"account_id": "inv1", "security_id": "sec-voo", "quantity": voo_qty, "cost_basis": 400 * voo_qty,
             "institution_price": 500},
            {"account_id": "inv1", "security_id": "sec-cash", "quantity": 200, "institution_price": 1},
            {"account_id": "inv2", "security_id": "sec-cit-abcdef", "quantity": 100, "cost_basis": 2500,
             "institution_price": 30},
        ],
    }


class FakePlaid:
    def __init__(self, voo_qty=15, fail=None, no_investments=False):
        self.voo_qty, self.fail, self.no_investments = voo_qty, fail, no_investments
        self.removed = []

    def create_link_token(self, user_id, access_token=None, kind="investments"):
        return f"link-sandbox-{user_id}-{kind}-{'update' if access_token else 'new'}"

    def exchange_public_token(self, public_token):
        return "access-sandbox-secret", "item-1"

    def get_item(self, access_token):
        return {"institution_id": "ins_1"}

    def institution_name(self, institution_id):
        return "Fidelity"

    def get_accounts(self, access_token):
        if self.fail:
            raise PlaidError(self.fail, "the login details of this item have changed")
        return ACCOUNTS

    def get_holdings(self, access_token):
        if self.no_investments:
            raise PlaidError("PRODUCTS_NOT_SUPPORTED", "no investments")
        return holdings(self.voo_qty)

    def get_investment_transactions(self, access_token, start, end):
        return {"investment_transactions": TRANSACTIONS, "securities": SECURITIES}

    liabilities = None  # None = the item has no Liabilities product

    def get_liabilities(self, access_token):
        if self.liabilities is None:
            raise PlaidError("PRODUCTS_NOT_SUPPORTED", "no liabilities")
        return self.liabilities

    def remove_item(self, access_token):
        self.removed.append(access_token)


@pytest.fixture
def item(user):
    return link_item(user, "public-sandbox-x", FakePlaid())


def holding(user, account_suffix, symbol):
    return next(
        p for p in compute_positions(user) if p.account.name.endswith(account_suffix) and p.symbol == symbol
    )


def test_link_stores_encrypted_token_and_accounts(item):
    assert item.institution_name == "Fidelity"
    assert "access-sandbox-secret" not in item.access_token_encrypted
    assert item.access_token == "access-sandbox-secret"
    assert item.accounts.count() == 4


def test_sync_maps_transactions_and_reconciles(user, item):
    report = sync_item(item, FakePlaid())
    assert report["error"] is None
    assert report["accounts"] == 3  # the credit card is neither an investment nor a bank account
    assert (report["transactions"], report["cash_flows"], report["skipped"]) == (4, 1, 1)
    assert report["adjustments"] == 4

    broker = Account.objects.get(owner=user, name="Fidelity Brokerage ····1234")
    assert broker.account_type == AccountType.BROKERAGE and broker.is_liquid
    k401 = Account.objects.get(owner=user, name="Fidelity 401k Plan ····5678")
    assert k401.tax_treatment == TaxTreatment.TAX_DEFERRED and not k401.is_liquid

    voo = holding(user, "····1234", "VOO")
    assert voo.quantity == 15
    assert voo.price == 500  # institution's price until Yahoo quotes it
    opening = Transaction.objects.get(account=broker, external_id__startswith="plaid-adj:open")
    assert opening.date == dt.date(2025, 2, 28)  # just before the first known trade
    assert (opening.quantity, opening.price) == (10, 400)  # at the broker's average cost
    assert holding(user, "····1234", "USD").quantity == 200  # 30 dividend − 5 fee + 175 reconciled
    assert CashFlow.objects.get(account=broker).amount == 5000

    cit = holding(user, "····5678", "PLAID-SEC-CIT-")
    assert (cit.quantity, cit.price) == (100, 30)
    assert holding(user, "····9999", "USD").market_value == 2500


def test_sync_is_idempotent_and_follows_the_broker(user, item):
    sync_item(item, FakePlaid())
    before = Transaction.objects.count()
    second = sync_item(item, FakePlaid())
    assert (second["transactions"], second["cash_flows"]) == (0, 0)
    assert Transaction.objects.count() == before
    assert holding(user, "····1234", "VOO").quantity == 15

    sync_item(item, FakePlaid(voo_qty=12))  # 3 sold somewhere Plaid didn't detail
    assert holding(user, "····1234", "VOO").quantity == 12


def test_cash_transfers_become_deposits_and_withdrawals(user, item):
    from connections.sync import apply_transaction

    sync_item(item, FakePlaid())
    broker = Account.objects.get(owner=user, name="Fidelity Brokerage ····1234")
    base = {"account_id": "inv1", "security_id": None, "type": "transfer", "subtype": "transfer", "quantity": 0, "price": 0}
    deposit = {**base, "investment_transaction_id": "x-in", "date": "2025-09-01", "amount": -20}
    withdrawal = {**base, "investment_transaction_id": "x-out", "date": "2025-09-02", "amount": 15}
    assert apply_transaction(deposit, broker, {}) == "flow"
    assert apply_transaction(withdrawal, broker, {}) == "flow"
    flows = {f.external_id: (f.kind, f.amount) for f in CashFlow.objects.filter(account=broker)}
    assert flows["plaid:x-in"] == ("deposit", 20)
    assert flows["plaid:x-out"] == ("withdrawal", -15)


def test_sold_position_bought_before_history_uses_first_known_price(user, item):
    # VOO bought before the available history and sold entirely within it: no holding, no reported cost.
    class SoldOut(FakePlaid):
        def get_holdings(self, access_token):
            data = holdings()
            data["holdings"] = [h for h in data["holdings"] if h["security_id"] != "sec-voo"]
            return data

        def get_investment_transactions(self, access_token, start, end):
            sell_all = {**TRANSACTIONS[2], "investment_transaction_id": "t-sell-all", "quantity": -20, "price": 450}
            return {"investment_transactions": [TRANSACTIONS[1], sell_all], "securities": SECURITIES}

    sync_item(item, SoldOut())
    broker = Account.objects.get(owner=user, name="Fidelity Brokerage ····1234")
    opening = Transaction.objects.get(account=broker, external_id__startswith="plaid-adj:open")
    assert (opening.quantity, opening.price) == (10, 400)  # the first buy's price, not $0
    assert not any(p.symbol == "VOO" for p in compute_positions(user) if p.account == broker)


@pytest.mark.parametrize(
    "institution, name, mask, expected",
    [
        ("Robinhood", "Robinhood Credit Card **2114", "2114", "Robinhood Credit Card ····2114"),
        ("Robinhood", "Robinhood individual", "", "Robinhood individual"),
        ("Fidelity", "Brokerage", "1234", "Fidelity Brokerage ····1234"),
        ("Chase", "Freedom Card ...4444", "4444", "Chase Freedom Card ····4444"),
        ("Amex", "Gold xx1001", "1001", "Amex Gold ····1001"),
    ],
)
def test_display_names_dont_repeat_bank_or_digits(institution, name, mask, expected):
    from types import SimpleNamespace

    from connections.sync import display_name

    pa = SimpleNamespace(name=name, mask=mask, item=SimpleNamespace(institution_name=institution))
    assert display_name(pa) == expected


def test_credit_cards_become_debts_and_follow_the_balance(user, item):
    report = sync_item(item, FakePlaid())
    assert report["liabilities"] == 1
    card = Liability.objects.get(owner=user)
    assert (card.name, card.kind, card.balance) == ("Fidelity Card ····4444", "credit_card", 800)
    assert card.interest_rate_pct == 0  # no Liabilities product: the rate is left for the user

    card.interest_rate_pct, card.promo_rate_pct, card.promo_end_date = D(24), D(0), dt.date(2027, 6, 30)
    card.save()
    ACCOUNTS_PAID = [{**a, "balances": {"current": 350}} if a["account_id"] == "cc1" else a for a in ACCOUNTS]
    with mock.patch.object(FakePlaid, "get_accounts", return_value=ACCOUNTS_PAID):
        sync_item(item, FakePlaid())
    card.refresh_from_db()
    assert card.balance == 350
    assert (card.interest_rate_pct, card.promo_rate_pct) == (24, 0)  # user's terms untouched
    assert Liability.objects.filter(owner=user).count() == 1


def test_liabilities_product_fills_rate_and_minimum(user, item):
    fake = FakePlaid()
    fake.liabilities = {"credit": [{
        "account_id": "cc1", "minimum_payment_amount": 35,
        "aprs": [{"apr_type": "cash_apr", "apr_percentage": 29.99}, {"apr_type": "purchase_apr", "apr_percentage": 22.49}],
    }]}
    sync_item(item, fake)
    card = Liability.objects.get(owner=user)
    assert (card.interest_rate_pct, card.minimum_payment) == (D("22.49"), 35)


def test_card_can_feed_an_existing_debt_or_be_skipped(api, user, item):
    mine = Liability.objects.create(owner=user, name="Mi tarjeta", kind="credit_card", balance=0, interest_rate_pct=20)
    cc1 = item.accounts.get(plaid_account_id="cc1")
    assert api.patch(f"/api/plaid/accounts/{cc1.id}/", {"liability": mine.id}, format="json").status_code == 200
    sync_item(item, FakePlaid())
    mine.refresh_from_db()
    assert mine.balance == 800
    assert Liability.objects.filter(owner=user).count() == 1

    assert api.patch(f"/api/plaid/accounts/{cc1.id}/", {"enabled": False}, format="json").status_code == 200
    assert sync_item(item, FakePlaid())["liabilities"] == 0


def test_existing_ticker_asset_is_reused(user, item, voo):
    sync_item(item, FakePlaid())
    assert Asset.objects.filter(owner=user, symbol="VOO").count() == 1
    voo.refresh_from_db()
    assert voo.last_price == 110  # an existing live price is not overwritten


def test_derivatives_are_priced_by_the_institution(user):
    from connections.sync import asset_for_security

    option = {"security_id": "sec-opt", "ticker_symbol": "NFLX180201C00355", "type": "derivative", "name": "NFLX call",
              "close_price": 1.5}
    asset = asset_for_security(user, option)
    assert (asset.price_source, asset.asset_class, asset.price) == ("manual", "other", 1.5)


def test_deleting_the_user_removes_synced_data(user, item):
    sync_item(item, FakePlaid())
    user.delete()  # transactions reference assets; both go with the user
    assert not Transaction.objects.exists()
    assert not PlaidItem.objects.exists()


def test_can_feed_an_existing_account_or_skip_one(api, user, item, broker, other_user):
    inv1 = item.accounts.get(plaid_account_id="inv1")
    dep1 = item.accounts.get(plaid_account_id="dep1")
    assert api.patch(f"/api/plaid/accounts/{inv1.id}/", {"account": broker.id}, format="json").status_code == 200
    assert api.patch(f"/api/plaid/accounts/{dep1.id}/", {"enabled": False}, format="json").status_code == 200
    foreign = Account.objects.create(owner=other_user, name="Theirs")
    assert api.patch(f"/api/plaid/accounts/{inv1.id}/", {"account": foreign.id}, format="json").status_code == 400

    report = sync_item(item, FakePlaid())
    assert report["accounts"] == 2
    assert holding(user, "Broker", "VOO").quantity == 15
    assert not Account.objects.filter(owner=user, name__contains="Checking").exists()


def test_login_required_marks_item_for_reauth(item):
    report = sync_item(item, FakePlaid(fail="ITEM_LOGIN_REQUIRED"))
    item.refresh_from_db()
    assert report["error"]["needs_reauth"] is True
    assert item.needs_reauth is True
    assert item.last_error.startswith("ITEM_LOGIN_REQUIRED")


def test_bank_only_item_still_syncs_balances(user, item):
    report = sync_item(item, FakePlaid(no_investments=True))
    assert report["error"] is None
    assert holding(user, "····9999", "USD").market_value == 2500


@pytest.fixture
def plaid_on(settings):
    settings.PLAID_CLIENT_ID, settings.PLAID_SECRET = "id", "secret"
    fake = FakePlaid()
    with mock.patch("connections.views.get_client", return_value=fake):
        yield fake


def test_endpoints_require_configuration(api, settings):
    settings.PLAID_CLIENT_ID = ""
    assert api.get("/api/plaid/status/").json()["configured"] is False
    assert api.post("/api/plaid/link-token/").status_code == 503


def test_link_exchange_sync_and_disconnect(api, user, plaid_on, other_user):
    assert api.post("/api/plaid/link-token/").json()["link_token"].endswith("investments-new")
    assert api.post("/api/plaid/link-token/", {"kind": "credit"}, format="json").json()["link_token"].endswith("credit-new")
    assert api.post("/api/plaid/link-token/", {"kind": "crypto"}, format="json").status_code == 400
    created = api.post("/api/plaid/exchange/", {"public_token": "public-sandbox-x"}, format="json")
    assert created.status_code == 201
    body = created.json()
    assert "access" not in str(body)  # the token never leaves the server
    item_id = body["id"]
    update = api.post("/api/plaid/link-token/", {"item": item_id}, format="json")
    assert update.json()["link_token"].endswith("update")
    assert api.post(f"/api/plaid/items/{item_id}/sync/").status_code == 200
    assert len(api.get("/api/plaid/items/").json()) == 1

    other_item = PlaidItem.objects.create(owner=other_user, item_id="item-x", access_token_encrypted="x")
    assert api.post(f"/api/plaid/items/{other_item.id}/sync/").status_code == 404

    assert api.delete(f"/api/plaid/items/{item_id}/").status_code == 204
    assert plaid_on.removed == ["access-sandbox-secret"]
    assert Account.objects.filter(owner=user, name__contains="Brokerage").exists()  # history stays


def _response(status, payload):
    resp = mock.Mock(status_code=status)
    resp.json.return_value = payload
    return resp


def test_client_raises_plaid_errors_and_paginates(settings):
    settings.PLAID_CLIENT_ID, settings.PLAID_SECRET, settings.PLAID_ENV = "id", "secret", "sandbox"
    client = PlaidClient()

    error = _response(400, {"error_code": "INVALID_FIELD", "error_message": "bad"})
    with mock.patch("connections.plaid.requests.post", return_value=error) as post, pytest.raises(PlaidError) as err:
        client.get_accounts("tok")
    assert err.value.code == "INVALID_FIELD"
    assert post.call_args.kwargs["json"]["secret"] == "secret"

    pages = [
        _response(200, {"investment_transactions": [{"id": 1}, {"id": 2}], "total_investment_transactions": 3}),
        _response(200, {"investment_transactions": [{"id": 3}], "total_investment_transactions": 3}),
    ]
    with mock.patch("connections.plaid.requests.post", side_effect=pages) as post:
        data = client.get_investment_transactions("tok", dt.date(2025, 1, 1), dt.date(2025, 2, 1))
    assert [t["id"] for t in data["investment_transactions"]] == [1, 2, 3]
    assert post.call_args.kwargs["json"]["options"]["offset"] == 2


@pytest.mark.parametrize("name, flow", [("FXAIX - MATCH CONTRIBUTION", "employer"), ("FXAIX - BEFORETAX CONTRIBUTION", "deposit")])
def test_401k_contributions_record_the_money_coming_in(user, name, flow):
    from connections.sync import apply_transaction
    from portfolio.models import CashFlow

    account = Account.objects.create(owner=user, name="401k", account_type="401k")
    sec = {"security_id": "s1", "ticker_symbol": "FXAIX", "name": "Fidelity 500 Index", "type": "mutual fund"}
    t = {
        "investment_transaction_id": "c1", "type": "buy", "subtype": "contribution", "name": name, "date": "2025-01-02",
        "quantity": 2, "price": 200, "amount": 400, "fees": 0, "security_id": "s1",
    }
    assert apply_transaction(t, account, {"s1": sec}) == "tx"
    assert Transaction.objects.get(account=account).quantity == 2
    cash = CashFlow.objects.get(account=account)
    assert (cash.kind, cash.amount) == (flow, 400)
    assert apply_transaction(t, account, {"s1": sec}) == "dup"
