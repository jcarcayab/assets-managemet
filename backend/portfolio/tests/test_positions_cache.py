from decimal import Decimal as D
from unittest import mock

import pytest
from django.db import transaction

from portfolio.models import Account, AccountType, Asset, AssetClass, PriceSource, Transaction
from portfolio.services import positions as pos
from portfolio.services.positions import clear_replay_cache, compute_positions
from portfolio.tests.conftest import buy

# Outside a test transaction, like a real request (the cache is skipped inside atomic blocks).
pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def fresh_cache():
    clear_replay_cache()
    yield
    clear_replay_cache()


@pytest.fixture
def setup(user):
    broker = Account.objects.create(owner=user, name="Broker", account_type=AccountType.BROKERAGE)
    voo = Asset.objects.create(owner=user, symbol="VOO", asset_class=AssetClass.STOCK,
                               price_source=PriceSource.MANUAL, manual_price=D(110))
    buy(broker, voo, 10, 100)
    return broker, voo


def replays():
    return mock.patch.object(pos, "_replay", wraps=pos._replay)


def value(user):
    [p] = compute_positions(user)
    return p.quantity, p.market_value, p.cost_basis


def test_second_call_reuses_the_replay_but_reads_fresh_prices(user, setup):
    broker, voo = setup
    with replays() as replay:
        assert value(user) == (10, 1100, 1000)
        voo.manual_price = D(120)
        voo.sector = "Index"
        voo.save()
        assert value(user) == (10, 1200, 1000)  # new price, same cached quantities
        assert compute_positions(user)[0].sector == "Index"
    assert replay.call_count == 1


def test_results_are_independent_copies(user, setup):
    first = compute_positions(user)
    first[0].quantity = 999
    first[0].lots.clear()
    again = compute_positions(user)
    assert again[0].quantity == 10 and len(again[0].lots) == 1


def test_changes_to_transactions_or_accounts_invalidate(user, setup):
    broker, voo = setup
    with replays() as replay:
        value(user)
        buy(broker, voo, 5, 100, day=2)  # new row
        assert value(user)[0] == 15
        tx = Transaction.objects.get(account=broker, date__day=2)
        tx.quantity = 1  # edited in place: same count and last id, the signal bumps the version
        tx.save()
        assert value(user)[0] == 11
        broker.archived = True
        broker.save()
        assert compute_positions(user) == []
    assert replay.call_count == 4


def test_inside_a_transaction_it_always_replays(user, setup):
    compute_positions(user)  # warm the cache
    with replays() as replay, transaction.atomic():
        compute_positions(user)
        compute_positions(user)
    assert replay.call_count == 2
