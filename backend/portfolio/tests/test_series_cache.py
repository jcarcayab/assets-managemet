from decimal import Decimal as D
from unittest import mock

import pytest

from portfolio.models import Account, AccountType, Asset, AssetClass, PriceSource
from portfolio.services import performance as perf
from portfolio.services.performance import clear_series_cache, daily_series
from portfolio.services.positions import clear_replay_cache
from portfolio.tests.conftest import buy

pytestmark = pytest.mark.django_db(transaction=True)  # like a real request: the cache is skipped in atomic blocks


@pytest.fixture(autouse=True)
def fresh():
    clear_series_cache()
    clear_replay_cache()
    yield
    clear_series_cache()


def test_series_is_cached_until_prices_or_trades_change(user):
    broker = Account.objects.create(owner=user, name="Broker", account_type=AccountType.BROKERAGE)
    voo = Asset.objects.create(owner=user, symbol="VOO", asset_class=AssetClass.STOCK,
                               price_source=PriceSource.MANUAL, manual_price=D(110))
    buy(broker, voo, 10, 100)
    with mock.patch.object(perf, "_daily_series", wraps=perf._daily_series) as build:
        first = daily_series(user)
        assert daily_series(user) == first and build.call_count == 1
        voo.manual_price = D(120)  # today's value changes
        voo.save()
        assert daily_series(user)[-1].value == 1200 and build.call_count == 2
        buy(broker, voo, 1, 100, day=2)
        assert daily_series(user)[-1].value == 1320 and build.call_count == 3
        daily_series(user, account_id=broker.id)  # each scope has its own entry
        assert build.call_count == 4
