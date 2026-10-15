"""Daily price history (Yahoo Finance) for owned assets and benchmarks, stored in PriceHistory."""

import datetime as dt
import logging
import math
from decimal import Decimal

from django.db.models import Max, Min
from django.utils import timezone

from portfolio.models import Asset, PriceHistory, Transaction

log = logging.getLogger(__name__)

BENCHMARKS = {
    "SPY": "S&P 500 (SPY)",
    "VT": "Acciones globales (VT)",
    "QQQ": "Nasdaq 100 (QQQ)",
    "AGG": "Bonos EE.UU. (AGG)",
    "BTC-USD": "Bitcoin",
}

DEFAULT_LOOKBACK = dt.timedelta(days=365)


def fetch_yahoo_history(tickers: list[str], start: dt.date) -> dict[str, list[tuple[dt.date, Decimal]]]:
    import yfinance as yf  # heavy import; only load when needed

    data = yf.download(tickers, start=start.isoformat(), interval="1d", progress=False, auto_adjust=False, threads=True)
    if data is None or data.empty:
        return {}
    closes = data["Close"]
    out: dict[str, list[tuple[dt.date, Decimal]]] = {}
    for ticker in tickers:
        series = closes[ticker] if ticker in getattr(closes, "columns", []) else closes
        rows = []
        for ts, value in series.dropna().items():
            value = float(value)
            if math.isfinite(value):
                rows.append((ts.date(), Decimal(str(round(value, 6)))))
        if rows:
            out[ticker] = rows
    return out


def history_tickers(user) -> set[str]:
    tickers = {a.history_symbol for a in Asset.objects.filter(owner=user) if a.history_symbol}
    return tickers | set(BENCHMARKS)


def update_history(user, fetcher=None) -> dict:
    """Fetch missing daily closes since the user's first transaction (or one year back)."""
    fetcher = fetcher or fetch_yahoo_history
    today = timezone.localdate()
    first_tx = Transaction.objects.filter(account__owner=user).aggregate(d=Min("date"))["d"]
    start = (first_tx or today - DEFAULT_LOOKBACK) - dt.timedelta(days=7)

    tickers = sorted(history_tickers(user))
    stored = PriceHistory.objects.filter(symbol__in=tickers).values("symbol").annotate(first=Min("date"), last=Max("date"))
    first = {r["symbol"]: r["first"] for r in stored}
    last = {r["symbol"]: r["last"] for r in stored}

    # Tickers without data back to `start` are fetched from `start`; the rest only from their last stored day.
    full = [t for t in tickers if t not in first or first[t] > start + dt.timedelta(days=7)]
    incremental = [t for t in tickers if t not in full and last[t] < today]
    batches = [(full, start)]
    if incremental:
        batches.append((incremental, min(last[t] for t in incremental)))

    saved, failed = 0, []
    for batch, since in batches:
        if not batch:
            continue
        try:
            data = fetcher(batch, since)
        except Exception as exc:  # network/API errors: keep what we have
            log.warning("History fetch failed for %s: %s", batch, exc)
            data = {}
        rows = [PriceHistory(symbol=t, date=d, close=c) for t, points in data.items() for d, c in points]
        if rows:
            PriceHistory.objects.bulk_create(
                rows, update_conflicts=True, unique_fields=["symbol", "date"], update_fields=["close"]
            )
        saved += len(rows)
        failed += [t for t in batch if t not in data]
    return {"saved": saved, "failed": sorted(failed)}


def load_history(symbols) -> dict[str, list[tuple[dt.date, Decimal]]]:
    out: dict[str, list[tuple[dt.date, Decimal]]] = {}
    rows = PriceHistory.objects.filter(symbol__in=list(symbols)).values_list("symbol", "date", "close")
    for symbol, date, close in rows:
        out.setdefault(symbol, []).append((date, close))
    return out
