"""Exchange-agnostic data: every exchange client turns its API into this shape for exchange_sync."""

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

# Balances in these count as the account's cash (stablecoins are treated as dollars).
CASH_SYMBOLS = {"USD", "USDC", "USDT"}


class ExchangeError(Exception):
    """The exchange refused the request (bad key, missing permission, rate limit…)."""


@dataclass
class Trade:
    ext_id: str
    date: dt.date
    symbol: str
    side: str  # "buy" | "sell"
    quantity: Decimal
    price: Decimal  # USD per unit
    fee: Decimal = Decimal(0)  # USD


@dataclass
class Reward:
    """Staking / earn income received in kind."""

    ext_id: str
    date: dt.date
    symbol: str
    quantity: Decimal
    value: Decimal | None = None  # USD at receipt, when the exchange reports it


@dataclass
class Transfer:
    """Crypto moved in or out of the exchange without a USD value: priced at that day's close when applied."""

    ext_id: str
    date: dt.date
    symbol: str
    side: str  # "buy" (received) | "sell" (sent)
    quantity: Decimal  # units that entered / left the balance
    fee: Decimal = Decimal(0)  # in units of the coin


@dataclass
class Fee:
    """Trading commissions paid on one day for one coin (USD). Re-sent on later syncs as the day fills up."""

    ext_id: str
    date: dt.date
    symbol: str
    amount: Decimal


@dataclass
class CashMove:
    ext_id: str
    date: dt.date
    amount: Decimal  # USD, positive
    kind: str  # "deposit" | "withdrawal"


@dataclass
class Snapshot:
    balances: dict[str, Decimal] = field(default_factory=dict)  # symbol -> quantity (cash under "USD")
    trades: list[Trade] = field(default_factory=list)
    rewards: list[Reward] = field(default_factory=list)
    cash_moves: list[CashMove] = field(default_factory=list)
    transfers: list[Transfer] = field(default_factory=list)
    fees: list[Fee] = field(default_factory=list)
    skipped: int = 0  # events with no ledger equivalent (crypto transfers, non-USD pairs…)

    def add_balance(self, symbol: str, quantity: Decimal) -> None:
        key = "USD" if symbol in CASH_SYMBOLS else symbol
        self.balances[key] = self.balances.get(key, Decimal(0)) + quantity
