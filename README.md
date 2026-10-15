# Patrimonio — personal net-worth tracker

Track every account and asset (brokerage, Roth IRA, 401k, crypto, metals, cash, loans, private equity
options) in one place, with live prices, allocation targets, history and a retirement projection.

- **backend/** — Django 5.2 + DRF. Source of truth is a transaction ledger; positions, average cost,
  P/L, rebalancing and the summary are computed from it (`portfolio/services/positions.py`).
- **frontend/** — React + TypeScript (Vite), TanStack Query, Recharts. Mobile-friendly.
- Prices: Yahoo Finance (stocks/ETFs/funds, metals via futures `GC=F`, `SI=F`) and CoinGecko (crypto).
  Any asset can have a manual price that overrides the live one (e.g. 401k funds without a ticker).
- Auth: Django session + CSRF. The built React app is served by Django (WhiteNoise), so it's one
  origin and one container in production.

## Local development

```bash
# backend
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
export DEBUG=1                      # SQLite, no SECRET_KEY needed
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py import_excel ../StockMarket_organizado.xlsx --user <you>   # optional, one-off
.venv/bin/python manage.py refresh_prices
.venv/bin/python manage.py runserver

# frontend (another terminal) — http://localhost:5173, proxies /api to :8000
cd frontend && npm install && npm run dev
```

Tests: `cd backend && .venv/bin/pytest`

`import_excel` reads the `StockMarket_organizado.xlsx` layout (Resumen, Posiciones, Crypto-Trades,
Metales, Equity, Historial). Pass `--reset` to wipe that user's data and re-import. Trades without a
date in the sheet are imported with today's date and flagged in their notes.

## Production

```bash
cp env.example .env   # set SECRET_KEY, ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS, POSTGRES_PASSWORD
docker compose up -d --build
docker compose exec web python manage.py createsuperuser
```

Put it behind HTTPS (Caddy, Cloudflare Tunnel, Fly.io/Render/Railway all work); with `DEBUG=0` cookies
are secure-only and HTTP redirects to HTTPS. The `scheduler` service refreshes prices hourly and saves
a daily snapshot. On a PaaS without compose, run the same image and schedule
`python manage.py take_snapshot` daily.

## Domain model

| Model | Purpose |
|---|---|
| `Account` | Broker/IRA/401k/crypto/bank/loan/equity… `is_liquid` separates accessible money from retirement. |
| `Asset` | Symbol + class + price source (`yahoo`/`coingecko`/`manual`). |
| `Transaction` | Buy/sell with qty, price, fees. Positions are derived from these (average cost). |
| `CashFlow` | Deposits/withdrawals into an account — used for "return vs. deposited". |
| `AllocationTarget` | Target % per asset within an account → rebalance amounts. |
| `EquityGrant` | Private-company options; unexercised valued at (FMV − strike). |
| `Snapshot` | Daily net-worth photo for the history chart. |
| `UserSettings` | Take-profit/stop-loss %, retirement-projection assumptions. |

Debt assets (class `debt`) are stored as positive balances and subtract from net worth.
