"""Coinbase App API (v2), read-only, authenticated with a CDP API key (JWT).

Uses v2 rather than Advanced Trade fills because simple buys made in the Coinbase app only show up there,
and every v2 transaction carries its USD value (`native_amount`), which gives exact cost basis.
Keys with trade or transfer permission are refused: create the key with "View" only.
"""

import base64
import datetime as dt
import json
import secrets
import time
from decimal import Decimal

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from connections.exchange_data import CASH_SYMBOLS, CashMove, ExchangeError, Reward, Snapshot, Trade

HOST = "api.coinbase.com"
TRADE_TYPES = {"buy", "sell", "advanced_trade_fill", "trade"}
REWARD_TYPES = {"staking_reward", "inflation_reward", "interest", "earn_payout", "reward"}


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def load_key(secret: str):
    """CDP keys are either an EC private key (PEM, ES256) or a base64 Ed25519 key (EdDSA)."""
    secret = secret.strip().replace("\\n", "\n")
    if "BEGIN" in secret:
        key = serialization.load_pem_private_key(secret.encode(), password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey):
            raise ExchangeError("La llave privada PEM no es ECDSA.")
        return key, "ES256"
    try:
        raw = base64.b64decode(secret, validate=True)
        return ed25519.Ed25519PrivateKey.from_private_bytes(raw[:32]), "EdDSA"
    except ValueError as exc:
        raise ExchangeError("No reconozco el formato de la llave privada de Coinbase.") from exc


def build_jwt(key_name: str, secret: str, method: str, path: str) -> str:
    key, alg = load_key(secret)
    now = int(time.time())
    header = {"alg": alg, "kid": key_name, "nonce": secrets.token_hex(16), "typ": "JWT"}
    claims = {"sub": key_name, "iss": "cdp", "nbf": now, "exp": now + 120, "uri": f"{method} {HOST}{path}"}
    signing_input = f"{_b64url(json.dumps(header).encode())}.{_b64url(json.dumps(claims).encode())}".encode()
    if alg == "ES256":
        r, s = decode_dss_signature(key.sign(signing_input, ec.ECDSA(hashes.SHA256())))
        signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")  # JWS wants raw r||s, not DER
    else:
        signature = key.sign(signing_input)
    return f"{signing_input.decode()}.{_b64url(signature)}"


def _code(currency) -> str:
    return (currency.get("code") if isinstance(currency, dict) else currency or "").upper()


def _date(iso: str) -> dt.date:
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).date()


class CoinbaseClient:
    def __init__(self, key_name: str, private_key: str):
        self.key_name = key_name.strip()
        self.private_key = private_key

    def get(self, path: str, params: dict | None = None) -> dict:
        token = build_jwt(self.key_name, self.private_key, "GET", path.split("?")[0])
        resp = requests.get(
            f"https://{HOST}{path}", params=params, headers={"Authorization": f"Bearer {token}"}, timeout=30
        )
        if resp.status_code == 401:
            raise ExchangeError("Coinbase rechazó la llave: revisa el nombre (organizations/…/apiKeys/…) y la llave privada.")
        try:
            data = resp.json()
        except ValueError:
            raise ExchangeError(f"Coinbase HTTP {resp.status_code}") from None
        if resp.status_code >= 400:
            errors = data.get("errors") or [{"message": data.get("message") or data.get("error") or resp.status_code}]
            raise ExchangeError(f"Coinbase: {errors[0].get('message')}")
        return data

    def paginate(self, path: str) -> list[dict]:
        rows, next_path, params = [], path, {"limit": 100}
        while next_path:
            data = self.get(next_path, params)
            rows += data.get("data", [])
            next_path = (data.get("pagination") or {}).get("next_uri")
            params = None  # next_uri already carries the cursor
        return rows

    def check(self) -> None:
        """Fails for an unusable key, and for any key that could trade or move money."""
        try:
            perms = self.get("/api/v3/brokerage/key_permissions")
        except ExchangeError:
            perms = {}
        if perms.get("can_trade") or perms.get("can_transfer"):
            raise ExchangeError(
                "Esta llave puede operar o transferir. Crea una con permiso de solo lectura (View) y úsala en su lugar."
            )
        self.get("/v2/accounts", {"limit": 1})

    def snapshot(self) -> Snapshot:
        snap = Snapshot()
        for account in self.paginate("/v2/accounts"):
            symbol = _code(account.get("currency") or account.get("balance", {}).get("currency"))
            balance = Decimal(account.get("balance", {}).get("amount", "0"))
            if balance:
                snap.add_balance(symbol, balance)
            for t in self.paginate(f"/v2/accounts/{account['id']}/transactions"):
                self._event(snap, symbol, t)
        return snap

    @staticmethod
    def _event(snap: Snapshot, symbol: str, t: dict) -> None:
        if t.get("status", "completed") != "completed":
            return
        kind = t.get("type", "")
        amount = Decimal(t.get("amount", {}).get("amount", "0"))
        native = t.get("native_amount") or {}
        usd = abs(Decimal(native["amount"])) if _code(native.get("currency")) == "USD" else None
        ext, date = f"coinbase:{t['id']}", _date(t["created_at"])

        if symbol in CASH_SYMBOLS:
            # The USD wallet: only money entering or leaving Coinbase matters; buys are on the crypto side.
            if kind in ("fiat_deposit", "fiat_withdrawal"):
                flow = "deposit" if kind == "fiat_deposit" else "withdrawal"
                snap.cash_moves.append(CashMove(ext, date, abs(amount), flow))
            return
        if not amount:
            return
        if kind in TRADE_TYPES:
            qty = abs(amount)
            price = usd / qty if usd is not None else Decimal(0)
            snap.trades.append(Trade(ext, date, symbol, "buy" if amount > 0 else "sell", qty, price))
        elif kind in REWARD_TYPES and amount > 0:
            snap.rewards.append(Reward(ext, date, symbol, amount, usd))
        else:
            snap.skipped += 1  # sends/receives and other moves without cost: covered by reconciliation
