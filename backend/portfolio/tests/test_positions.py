from decimal import Decimal as D

import pytest

from portfolio.models import (
    Account,
    AccountType,
    AllocationTarget,
    Asset,
    AssetClass,
    CashFlow,
    EquityGrant,
    PriceSource,
)
from portfolio.services.positions import compute_positions, compute_summary
from portfolio.tests.conftest import buy

pytestmark = pytest.mark.django_db


def test_average_cost_and_unrealized(user, broker, voo):
    buy(broker, voo, 10, 100)
    buy(broker, voo, 10, 80, day=2, fees=2)

    [p] = compute_positions(user)
    assert p.quantity == 20
    assert p.cost_basis == D(1802)
    assert p.avg_cost == D("90.1")
    assert p.market_value == D(2200)
    assert p.unrealized == D(398)


def test_sell_books_realized_and_keeps_average(user, broker, voo):
    buy(broker, voo, 10, 100)
    buy(broker, voo, 4, 150, day=2, kind="sell")

    [p] = compute_positions(user)
    assert p.quantity == 6
    assert p.avg_cost == 100
    assert p.realized == D(200)


def test_fully_sold_position_is_hidden_unless_requested(user, broker, voo):
    buy(broker, voo, 5, 100)
    buy(broker, voo, 5, 120, day=2, kind="sell")

    assert compute_positions(user) == []
    [closed] = compute_positions(user, include_closed=True)
    assert closed.realized == D(100)


def test_manual_price_overrides_live(user, broker, voo):
    voo.manual_price = D(200)
    voo.save()
    buy(broker, voo, 1, 100)
    assert compute_positions(user)[0].market_value == 200


def test_debt_subtracts_from_net_worth(user, broker, voo):
    loan_acc = Account.objects.create(owner=user, name="Loan", account_type=AccountType.LOAN)
    loan = Asset.objects.create(
        owner=user, symbol="LOAN", asset_class=AssetClass.DEBT, price_source=PriceSource.MANUAL, manual_price=1
    )
    buy(broker, voo, 10, 100)  # 1100 market value
    buy(loan_acc, loan, 300, 1)

    s = compute_summary(user)
    assert s["net_worth"] == D(800)
    assert s["unrealized"] == D(100)


def test_unexercised_options_valued_at_intrinsic(user):
    acc = Account.objects.create(owner=user, name="Co Equity", account_type=AccountType.PRIVATE_EQUITY, is_liquid=False)
    EquityGrant.objects.create(account=acc, company="Co", quantity=100, strike=D("8.5"), fmv=D(60))

    s = compute_summary(user)
    assert s["net_worth"] == D(5150)
    assert s["net_worth_ex_private"] == 0
    assert s["liquid"] == 0
    assert s["cost"] == 0


def test_summary_liquidity_and_rebalance(user, broker, ira, voo):
    bnd = Asset.objects.create(owner=user, symbol="BND", asset_class=AssetClass.BOND, last_price=D(50))
    buy(broker, voo, 10, 100)  # 1100 liquid
    buy(ira, voo, 1, 100)  # 110 illiquid
    buy(ira, bnd, 2, 50)  # 100 illiquid
    AllocationTarget.objects.create(account=ira, asset=bnd, target_pct=50)

    s = compute_summary(user)
    assert s["liquid"] == D(1100)
    assert s["illiquid"] == D(210)
    bnd_pos = next(p for p in compute_positions(user) if p.symbol == "BND")
    assert bnd_pos.target_value == D(105)
    assert bnd_pos.rebalance == D(5)


def test_crypto_return_vs_deposits_and_levels(user):
    acc = Account.objects.create(owner=user, name="Crypto", account_type=AccountType.CRYPTO)
    sol = Asset.objects.create(
        owner=user, symbol="SOL", asset_class=AssetClass.CRYPTO, price_source=PriceSource.COINGECKO,
        source_id="solana", last_price=D(150),
    )
    buy(acc, sol, 10, 100)
    CashFlow.objects.create(account=acc, date="2025-01-01", amount=D(1200))

    s = compute_summary(user)
    assert s["crypto"]["value"] == D(1500)
    assert s["crypto"]["gain"] == D(300)


def test_users_do_not_see_each_others_data(user, other_user, broker, voo):
    buy(broker, voo, 1, 100)
    assert compute_positions(other_user) == []
    assert compute_summary(other_user)["net_worth"] == 0
