import datetime as dt
from decimal import Decimal as D

import pytest
from rest_framework.test import APIClient

from portfolio.models import Account, AccountType, Asset, AssetClass, PriceSource, Transaction


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user("alice", password="a-long-test-password")


@pytest.fixture
def other_user(django_user_model):
    return django_user_model.objects.create_user("bob", password="a-long-test-password")


@pytest.fixture
def api(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def broker(user):
    return Account.objects.create(owner=user, name="Broker", account_type=AccountType.BROKERAGE, is_liquid=True)


@pytest.fixture
def ira(user):
    return Account.objects.create(owner=user, name="IRA", account_type=AccountType.ROTH_IRA, is_liquid=False)


@pytest.fixture
def voo(user):
    return Asset.objects.create(
        owner=user, symbol="VOO", asset_class=AssetClass.STOCK, price_source=PriceSource.YAHOO, last_price=D(110)
    )


def buy(account, asset, qty, price, day=1, fees=0, kind="buy"):
    return Transaction.objects.create(
        account=account, asset=asset, kind=kind, date=dt.date(2025, 1, day),
        quantity=D(str(qty)), price=D(str(price)), fees=D(str(fees)),
    )
