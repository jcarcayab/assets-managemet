"""Minimal Plaid API client (plain JSON over HTTPS; see https://plaid.com/docs/api/)."""

import datetime as dt

import requests
from django.conf import settings

BASE_URLS = {
    "sandbox": "https://sandbox.plaid.com",
    "production": "https://production.plaid.com",
}
TRANSACTIONS_PAGE = 500


class PlaidError(Exception):
    def __init__(self, code: str | None, message: str | None, status: int = 400):
        super().__init__(f"{code}: {message}")
        self.code = code or "UNKNOWN"
        self.message = message or ""
        self.status = status


def configured() -> bool:
    return bool(settings.PLAID_CLIENT_ID and settings.PLAID_SECRET)


class PlaidClient:
    def __init__(self, client_id: str | None = None, secret: str | None = None, env: str | None = None):
        self.client_id = client_id or settings.PLAID_CLIENT_ID
        self.secret = secret or settings.PLAID_SECRET
        self.env = env or settings.PLAID_ENV
        if self.env not in BASE_URLS:
            raise ValueError(f"PLAID_ENV must be one of {sorted(BASE_URLS)}")

    def post(self, path: str, body: dict) -> dict:
        resp = requests.post(
            f"{BASE_URLS[self.env]}{path}",
            json={"client_id": self.client_id, "secret": self.secret, **body},
            timeout=30,
        )
        try:
            data = resp.json()
        except ValueError:
            raise PlaidError("INVALID_RESPONSE", f"HTTP {resp.status_code}", resp.status_code) from None
        if resp.status_code >= 400 or data.get("error_code"):
            message = data.get("display_message") or data.get("error_message")
            raise PlaidError(data.get("error_code"), message, resp.status_code)
        return data

    # -- Link ----------------------------------------------------------------------------------------

    def create_link_token(self, user_id: int, access_token: str | None = None) -> str:
        body = {
            "client_name": "Patrimonio",
            "user": {"client_user_id": str(user_id)},
            "country_codes": ["US"],
            "language": "es",
        }
        if access_token:
            body["access_token"] = access_token  # update mode: re-authenticate an existing item
        else:
            body["products"] = ["investments"]
        if settings.PLAID_REDIRECT_URI:
            body["redirect_uri"] = settings.PLAID_REDIRECT_URI  # needed for OAuth institutions in production
        return self.post("/link/token/create", body)["link_token"]

    def exchange_public_token(self, public_token: str) -> tuple[str, str]:
        data = self.post("/item/public_token/exchange", {"public_token": public_token})
        return data["access_token"], data["item_id"]

    # -- data ----------------------------------------------------------------------------------------

    def institution_name(self, institution_id: str) -> str:
        if not institution_id:
            return ""
        data = self.post("/institutions/get_by_id", {"institution_id": institution_id, "country_codes": ["US"]})
        return data["institution"]["name"]

    def get_item(self, access_token: str) -> dict:
        return self.post("/item/get", {"access_token": access_token})["item"]

    def get_accounts(self, access_token: str) -> list[dict]:
        return self.post("/accounts/get", {"access_token": access_token})["accounts"]

    def get_holdings(self, access_token: str) -> dict:
        return self.post("/investments/holdings/get", {"access_token": access_token})

    def get_investment_transactions(self, access_token: str, start: dt.date, end: dt.date) -> dict:
        """All investment transactions in [start, end], following Plaid's offset pagination."""
        transactions, securities, offset = [], {}, 0
        while True:
            data = self.post(
                "/investments/transactions/get",
                {
                    "access_token": access_token,
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "options": {"count": TRANSACTIONS_PAGE, "offset": offset},
                },
            )
            page = data["investment_transactions"]
            transactions += page
            securities.update({s["security_id"]: s for s in data.get("securities", [])})
            offset += len(page)
            if not page or offset >= data.get("total_investment_transactions", 0):
                break
        return {"investment_transactions": transactions, "securities": list(securities.values())}

    def remove_item(self, access_token: str) -> None:
        self.post("/item/remove", {"access_token": access_token})


def get_client() -> PlaidClient:
    return PlaidClient()
