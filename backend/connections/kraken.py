"""Kraken REST API, read-only (https://docs.kraken.com/api/).

Needs an API key with only: Query Funds, Query Closed Orders & Trades, Query Ledger Entries.
"""

import base64
import datetime as dt
import hashlib
import hmac
import re
import time
import urllib.parse
from decimal import Decimal

import requests

from connections.exchange_data import CASH_SYMBOLS, CashMove, ExchangeError, Reward, Snapshot, Trade

API = "https://api.kraken.com"

# Private calls share a counter (https://docs.kraken.com/api/docs/guides/spot-rest-ratelimits): history queries
# add 2, the rest 1, and it decays 0.33/s up to a max of 15 on the Starter tier. Higher tiers allow more, so
# pacing for Starter is safe for everyone; a long first history just takes a few minutes.
RATE_MAX, RATE_DECAY = 15, 0.33
HEAVY_METHODS = {"TradesHistory", "Ledgers", "QueryLedgers", "ClosedOrders", "QueryTrades"}
RATE_RETRIES = 5

# Kraken's legacy asset codes. Suffixes like ".S" (staked) or ".F" (earn) are stripped first.
ALIASES = {
    "XBT": "BTC", "XXBT": "BTC", "XDG": "DOGE", "XXDG": "DOGE", "XETH": "ETH", "XXRP": "XRP", "XLTC": "LTC",
    "XXLM": "XLM", "XZEC": "ZEC", "XXMR": "XMR", "XETC": "ETC", "XMLN": "MLN", "XREP": "REP",
    "ZUSD": "USD", "ZEUR": "EUR", "ZGBP": "GBP", "ZCAD": "CAD", "ZJPY": "JPY", "ZAUD": "AUD",
    "ETH2": "ETH",  # staked ETH
}
# Staking with a lock period adds it in days to the code: SOL03, DOT28, KSM07, FLOW14…
LOCKED_STAKING = re.compile(r"^([A-Z]{2,})\d{2}$")


def kraken_symbol(code: str) -> str:
    base = code.split(".")[0].upper()
    if base in ALIASES:
        return ALIASES[base]
    if locked := LOCKED_STAKING.match(base):
        base = locked.group(1)
    return ALIASES.get(base, base)


def sign(path: str, nonce: str, postdata: str, secret: str) -> str:
    """API-Sign = base64(HMAC-SHA512(base64decode(secret), path + SHA256(nonce + postdata)))."""
    digest = hashlib.sha256((nonce + postdata).encode()).digest()
    mac = hmac.new(base64.b64decode(secret), path.encode() + digest, hashlib.sha512)
    return base64.b64encode(mac.digest()).decode()


def _date(ts) -> dt.date:
    return dt.datetime.fromtimestamp(float(ts), tz=dt.UTC).date()


class KrakenClient:
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key.strip()
        self.api_secret = api_secret.strip()
        self._last_nonce = 0
        self._counter, self._counter_at = 0.0, time.monotonic()

    def _nonce(self) -> str:
        self._last_nonce = max(int(time.time() * 1000), self._last_nonce + 1)  # must strictly increase
        return str(self._last_nonce)

    @staticmethod
    def _result(resp) -> dict:
        try:
            data = resp.json()
        except ValueError:
            raise ExchangeError(f"Kraken HTTP {resp.status_code}") from None
        if data.get("error"):
            raise ExchangeError("Kraken: " + ", ".join(data["error"]))
        return data["result"]

    def _throttle(self, method: str) -> None:
        """Wait until this call fits in Kraken's counter (as we track it), then count it."""
        cost = 2 if method in HEAVY_METHODS else 1
        now = time.monotonic()
        self._counter = max(0.0, self._counter - (now - self._counter_at) * RATE_DECAY)
        wait = (self._counter + cost - RATE_MAX) / RATE_DECAY
        if wait > 0:
            time.sleep(wait)
            self._counter = RATE_MAX - cost
        self._counter += cost
        self._counter_at = time.monotonic()

    def private(self, method: str, data: dict | None = None) -> dict:
        for attempt in range(RATE_RETRIES + 1):
            self._throttle(method)
            try:
                return self._private(method, data)
            except ExchangeError as exc:
                if "Rate limit" not in str(exc) or attempt == RATE_RETRIES:
                    raise
                # Kraken's counter is higher than ours (an earlier sync, another app on the key): let it drain.
                self._counter, self._counter_at = RATE_MAX, time.monotonic()
                time.sleep(10 * (attempt + 1))
        raise AssertionError("unreachable")

    def _private(self, method: str, data: dict | None = None) -> dict:
        path = f"/0/private/{method}"
        body = {"nonce": self._nonce(), **(data or {})}
        postdata = urllib.parse.urlencode(body)
        headers = {
            "API-Key": self.api_key,
            "API-Sign": sign(path, body["nonce"], postdata, self.api_secret),
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
        }
        return self._result(requests.post(API + path, data=postdata, headers=headers, timeout=30))

    def public(self, method: str) -> dict:
        return self._result(requests.get(f"{API}/0/public/{method}", timeout=30))

    def _paged(self, method: str, key: str, since: dt.date | None = None) -> dict:
        rows, offset = {}, 0
        start = {"start": int(dt.datetime.combine(since, dt.time(), tzinfo=dt.UTC).timestamp())} if since else {}
        while True:
            result = self.private(method, {"ofs": offset, **start})
            page = result.get(key, {})
            rows.update(page)
            offset += len(page)
            if not page or offset >= int(result.get("count", 0)):
                return rows

    def check(self) -> None:
        """Fails unless the key can read balances, trades and ledger entries."""
        self.private("Balance")
        self.private("TradesHistory", {"ofs": 0})
        self.private("Ledgers", {"ofs": 0})

    def snapshot(self, since: dt.date | None = None) -> Snapshot:
        """Balances, plus trades and ledger entries (all of them, or only those from `since` on)."""
        snap = Snapshot()
        for code, amount in self.private("Balance").items():
            if Decimal(amount):
                snap.add_balance(kraken_symbol(code), Decimal(amount))

        pairs = {}
        for name, info in self.public("AssetPairs").items():
            pair = (kraken_symbol(info["base"]), kraken_symbol(info["quote"]))
            pairs[name] = pairs[info.get("altname", name)] = pair

        for txid, t in self._paged("TradesHistory", "trades", since).items():
            base, quote = pairs.get(t["pair"], (None, None))
            if base is None or quote not in CASH_SYMBOLS:
                snap.skipped += 1  # crypto/crypto or non-USD pair: reconciliation covers the balances
                continue
            snap.trades.append(
                Trade(
                    ext_id=f"kraken:{txid}", date=_date(t["time"]), symbol=base, side=t["type"],
                    quantity=Decimal(t["vol"]), price=Decimal(t["price"]), fee=Decimal(t.get("fee", "0")),
                )
            )

        for lid, entry in self._paged("Ledgers", "ledger", since).items():
            symbol, amount = kraken_symbol(entry["asset"]), Decimal(entry["amount"])
            kind, subtype = entry.get("type", ""), entry.get("subtype", "")
            if kind in ("deposit", "withdrawal") and symbol in CASH_SYMBOLS:
                snap.cash_moves.append(CashMove(f"kraken:{lid}", _date(entry["time"]), abs(amount), kind))
            elif amount > 0 and (kind == "staking" or (kind == "earn" and subtype == "reward")):
                received = amount - Decimal(entry.get("fee", "0"))
                snap.rewards.append(Reward(f"kraken:{lid}", _date(entry["time"]), symbol, received))
            elif kind not in ("trade", "transfer", "earn", "spend", "receive"):
                snap.skipped += 1  # crypto deposits/withdrawals etc.: covered by reconciliation
        return snap
