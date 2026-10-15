"""Fetch live prices from free sources: Yahoo Finance (stocks, ETFs, funds, metal futures) and CoinGecko (crypto)."""

import logging
import math
from decimal import Decimal

import requests
from django.utils import timezone

from portfolio.models import Asset, PriceSource

log = logging.getLogger(__name__)

COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"


def fetch_yahoo(ids: list[str]) -> dict[str, Decimal]:
    if not ids:
        return {}
    import yfinance as yf  # heavy import; only load when needed

    data = yf.download(ids, period="5d", interval="1d", progress=False, auto_adjust=False, threads=True)
    if data is None or data.empty:
        return {}
    closes = data["Close"]
    out: dict[str, Decimal] = {}
    for ticker in ids:
        series = closes[ticker] if ticker in getattr(closes, "columns", []) else closes
        series = series.dropna()
        if len(series):
            value = float(series.iloc[-1])
            if math.isfinite(value):
                out[ticker] = Decimal(str(round(value, 6)))
    return out


def fetch_coingecko(ids: list[str]) -> dict[str, Decimal]:
    if not ids:
        return {}
    resp = requests.get(COINGECKO_URL, params={"ids": ",".join(ids), "vs_currencies": "usd"}, timeout=15)
    resp.raise_for_status()
    return {k: Decimal(str(v["usd"])) for k, v in resp.json().items() if "usd" in v}


FETCHERS = {
    PriceSource.YAHOO: fetch_yahoo,
    PriceSource.COINGECKO: fetch_coingecko,
}


def refresh_prices(assets) -> dict:
    """Update last_price for the given assets. Returns {'updated': [...], 'failed': [...]}."""
    by_source: dict[str, list[Asset]] = {}
    for a in assets:
        if a.price_source in FETCHERS:
            by_source.setdefault(a.price_source, []).append(a)

    updated, failed = [], []
    now = timezone.now()
    for source, group in by_source.items():
        ids = sorted({a.lookup_id for a in group})
        try:
            prices = FETCHERS[source](ids)
        except Exception as exc:  # one source failing shouldn't block the other
            log.warning("Price fetch from %s failed: %s", source, exc)
            prices = {}
        for a in group:
            price = prices.get(a.lookup_id)
            if price is None:
                failed.append(a.symbol)
                continue
            a.last_price, a.last_price_at = price, now
            a.save(update_fields=["last_price", "last_price_at"])
            updated.append(a.symbol)
    return {"updated": sorted(updated), "failed": sorted(failed)}
