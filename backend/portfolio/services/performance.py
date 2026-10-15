"""Investment performance: time-weighted return (TWR), money-weighted return (XIRR) and benchmark comparison.

Holdings are re-valued every day from the ledger and PriceHistory. Because cash is not a full ledger
(buys don't debit a cash balance), external flows are measured at the security level: a buy is money
put in, a sale is money taken out, while dividends, interest, staking and fees stay inside as return.
Private equity and debt are excluded (no daily prices / not investments).
"""

import bisect
import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from django.utils import timezone

from portfolio.models import AssetClass, Transaction, TransactionKind, UserSettings
from portfolio.services.history import BENCHMARKS, load_history
from portfolio.services.positions import Ledger, ledger_transactions

ZERO = Decimal(0)
MAX_POINTS = 400
PRICED_KINDS = (TransactionKind.BUY, TransactionKind.SELL, TransactionKind.STAKING, TransactionKind.TRANSFER)


class PriceBook:
    """Forward-filled daily price per asset: daily history, else trade prices, and the current price today."""

    def __init__(self, assets, txs, history, today):
        self.points: dict[int, tuple[list[dt.date], list[Decimal]]] = {}
        trade_prices: dict[int, dict[dt.date, Decimal]] = defaultdict(dict)
        for tx in txs:
            if tx.price and tx.kind in PRICED_KINDS:
                trade_prices[tx.asset_id][tx.date] = tx.price
        for asset in assets:
            by_date = dict(trade_prices[asset.id])
            for date, close in history.get(asset.history_symbol or "", []):
                by_date[date] = close
            if asset.price:
                by_date[today] = asset.price
            dates = sorted(by_date)
            self.points[asset.id] = (dates, [by_date[d] for d in dates])

    def price(self, asset_id: int, date: dt.date) -> Decimal | None:
        if asset_id not in self.points:
            return None
        dates, prices = self.points[asset_id]
        i = bisect.bisect_right(dates, date) - 1
        if i >= 0:
            return prices[i]
        return prices[0] if prices else ZERO  # before the first known price: use the earliest one


@dataclass
class Day:
    date: dt.date
    value: Decimal
    flow: Decimal  # money put in (+) or taken out (-) that day


def _flow(tx: Transaction, account_id: int | None, ledger: Ledger) -> Decimal:
    """External flow for the scope (whole portfolio when account_id is None)."""
    in_scope = account_id in (None, tx.account_id)
    if tx.kind == TransactionKind.BUY:
        return tx.quantity * tx.price + tx.fees if in_scope else ZERO
    if tx.kind == TransactionKind.SELL:
        return -(tx.quantity * tx.price - tx.fees) if in_scope else ZERO
    if tx.kind == TransactionKind.TRANSFER and account_id is not None:
        value = tx.quantity * (tx.price or ledger.position(tx.account, tx.asset).avg_cost)
        if tx.account_id == account_id:
            return -value
        if tx.to_account_id == account_id:
            return value
    return ZERO


def daily_series(user, account_id: int | None = None) -> list[Day]:
    """One Day per calendar day from the scope's first transaction until today."""
    txs = [
        tx for tx in ledger_transactions(user)
        if tx.asset.asset_class not in (AssetClass.DEBT, AssetClass.PRIVATE_EQUITY)
    ]
    scope_dates = [tx.date for tx in txs if account_id is None or account_id in (tx.account_id, tx.to_account_id)]
    if not scope_dates:
        return []
    today = timezone.localdate()
    assets = {tx.asset_id: tx.asset for tx in txs}
    history = load_history({a.history_symbol for a in assets.values() if a.history_symbol})
    book = PriceBook(assets.values(), txs, history, today)

    # The whole ledger is replayed (a transfer into the account needs the source's holdings),
    # but only the scope's value and flows are recorded.
    by_day: dict[dt.date, list[Transaction]] = defaultdict(list)
    for tx in txs:
        by_day[tx.date].append(tx)
    ledger = Ledger(user)
    days: list[Day] = []
    date, record_from = txs[0].date, min(scope_dates)
    while date <= today:
        flow = ZERO
        for tx in by_day.get(date, ()):
            flow += _flow(tx, account_id, ledger)  # before apply: transfers use the pre-move average cost
            ledger.apply(tx)
        if date >= record_from:
            value = ZERO
            for (acc_id, asset_id), pos in ledger.positions.items():
                if pos.quantity and (account_id is None or acc_id == account_id):
                    price = book.price(asset_id, date)
                    value += pos.quantity * (pos.price if price is None else price)
            days.append(Day(date, value, flow))
        date += dt.timedelta(days=1)
    return days


def twr_index(days: list[Day]) -> list[float]:
    """Cumulative growth of $1 (flows assumed at the start of each day). index[i] is after day i."""
    out, level, prev = [], 1.0, ZERO
    for d in days:
        base = prev + d.flow
        if base > 0:
            level *= float(d.value / base)
        out.append(level)
        prev = d.value
    return out


def xirr(flows: list[tuple[dt.date, float]]) -> float | None:
    """Annualized money-weighted return. Flows from the investor's view: money in < 0, money out > 0."""
    if len(flows) < 2 or not any(a > 0 for _, a in flows) or not any(a < 0 for _, a in flows):
        return None
    t0 = flows[0][0]

    def npv(rate: float) -> float:
        return sum(a / (1 + rate) ** ((d - t0).days / 365.0) for d, a in flows)

    lo, hi = -0.9999, 10.0
    f_lo = npv(lo)
    if f_lo * npv(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-7:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def _bench_prices(symbol: str, days: list[Day]) -> list[float | None]:
    points = load_history([symbol]).get(symbol, [])
    dates = [d for d, _ in points]
    out = []
    for day in days:
        i = bisect.bisect_right(dates, day.date) - 1
        out.append(float(points[i][1]) if i >= 0 else None)
    return out


def _period_start(key: str, today: dt.date, first: dt.date) -> dt.date:
    starts = {
        "1M": today - dt.timedelta(days=30),
        "3M": today - dt.timedelta(days=91),
        "YTD": dt.date(today.year, 1, 1) - dt.timedelta(days=1),
        "1A": today - dt.timedelta(days=365),
    }
    return max(starts.get(key, first), first)


def _period(key: str, days: list[Day], index: list[float], bench: list[float | None]) -> dict:
    first, today = days[0].date, days[-1].date
    start = _period_start(key, today, first)
    whole = start == first  # the period covers the full history: base is "before the first day"
    i = 0 if whole else (start - first).days
    span = max((today - start).days, 1)

    twr = index[-1] / (1.0 if whole else index[i]) - 1
    b0 = next((b for b in bench[i:] if b), None)
    bench_ret = bench[-1] / b0 - 1 if b0 and bench[-1] else None

    # XIRR: the starting value counts as money put in, then the period's flows, then the ending value out.
    cash: list[tuple[dt.date, float]] = []
    if not whole and days[i].value:
        cash.append((days[i].date, -float(days[i].value)))
    for d in days[(0 if whole else i + 1):]:
        if d.flow:
            cash.append((d.date, -float(d.flow)))
    cash.append((today, float(days[-1].value)))
    money_weighted = xirr(cash) if span >= 30 else None
    # Periods under a year are reported as the cumulative money-weighted return over the period, not annualized
    # (annualizing one month turns −3% into −30%+ and misleads).
    if money_weighted is not None and span < 365:
        money_weighted = (1 + money_weighted) ** (span / 365) - 1

    return {
        "key": key,
        "start": start,
        "days": span,
        "twr": twr * 100,
        "twr_annualized": ((1 + twr) ** (365 / span) - 1) * 100 if span > 365 else None,
        "benchmark": bench_ret * 100 if bench_ret is not None else None,
        "xirr": money_weighted * 100 if money_weighted is not None else None,
        "xirr_annualized": span >= 365,
    }


def compute_performance(user, account_id: int | None = None, benchmark: str | None = None) -> dict:
    benchmark = benchmark or UserSettings.for_user(user).benchmark
    meta = {"benchmark": benchmark, "benchmark_label": BENCHMARKS.get(benchmark, benchmark)}
    days = daily_series(user, account_id)
    if not days:
        return {**meta, "empty": True}

    index = twr_index(days)
    bench = _bench_prices(benchmark, days)

    # The same flows invested in the benchmark instead ("public market equivalent").
    units, invested = 0.0, 0.0
    for d, b in zip(days, bench):
        if d.flow and b:
            units += float(d.flow) / b
        invested += float(d.flow)

    step = max(1, len(days) // MAX_POINTS)
    b_first = next((b for b in bench if b), None)
    series, cum_flow = [], 0.0
    for i, (d, b) in enumerate(zip(days, bench)):
        cum_flow += float(d.flow)
        if i % step == 0 or i == len(days) - 1:
            series.append(
                {
                    "date": d.date,
                    "value": float(d.value),
                    "invested": cum_flow,
                    "twr": (index[i] - 1) * 100,
                    "benchmark": (b / b_first - 1) * 100 if b and b_first else None,
                }
            )

    # Opening balances entered with today's date make history look like it all started this week.
    recent = sum(float(d.flow) for d in days[-7:] if d.flow > 0)
    recent_share = recent / float(days[-1].value) if days[-1].value else 0.0

    return {
        **meta,
        "empty": False,
        "recent_contribution_share": recent_share * 100,
        "start": days[0].date,
        "value": float(days[-1].value),
        "net_invested": invested,
        "gain": float(days[-1].value) - invested,
        "benchmark_equivalent": units * bench[-1] if bench[-1] else None,
        "missing_benchmark": not any(bench),
        "periods": [_period(key, days, index, bench) for key in ("1M", "3M", "YTD", "1A", "Total")],
        "series": series,
    }


def compute_income(user) -> dict:
    """Dividends, interest, staking rewards and fees by year, plus income by asset over the last 12 months."""
    kinds = [TransactionKind.DIVIDEND, TransactionKind.INTEREST, TransactionKind.STAKING, TransactionKind.FEE]
    txs = Transaction.objects.filter(account__owner=user, account__archived=False, kind__in=kinds).select_related("asset")
    since = timezone.localdate() - dt.timedelta(days=365)
    by_year: dict[int, dict] = {}
    by_asset: dict[str, Decimal] = defaultdict(Decimal)
    for tx in txs:
        value = tx.quantity * tx.price if tx.kind == TransactionKind.STAKING else tx.amount
        key = "fees" if tx.kind == TransactionKind.FEE else str(tx.kind)
        row = by_year.setdefault(
            tx.date.year, {"year": tx.date.year, "dividend": ZERO, "interest": ZERO, "staking": ZERO, "fees": ZERO}
        )
        row[key] += value
        if tx.date >= since and tx.kind != TransactionKind.FEE:
            by_asset[tx.asset.symbol] += value
    for row in by_year.values():
        row["total"] = row["dividend"] + row["interest"] + row["staking"] - row["fees"]
    return {
        "by_year": sorted(by_year.values(), key=lambda r: r["year"]),
        "by_asset_12m": [{"symbol": k, "value": v} for k, v in sorted(by_asset.items(), key=lambda kv: -kv[1])],
    }
