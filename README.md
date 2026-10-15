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

## Security

- **Two-factor authentication** (`backend/security/`): TOTP from any authenticator app, enrolled with a QR
  code and confirmed with a code; 10 single-use recovery codes (stored as HMACs). Login is two steps: the
  password returns a 5-minute signed token, and only the code creates the session. Codes can't be replayed.
- `MFA_REQUIRED=1` forces every user to enroll before using the API.
- `/admin` honors 2FA: its password-only login form is replaced by a redirect to the app's login, and admin
  pages refuse sessions that skipped the second factor. To reset a user who lost both phone and recovery
  codes, delete their TOTP device in the admin (or `manage.py shell`).
- Secrets in the database (TOTP seeds, Plaid tokens) are encrypted with `FIELD_ENCRYPTION_KEY`.

## Bank connections (Plaid)

`backend/connections/` links brokers, retirement accounts and bank accounts through Plaid Link
(Conexiones page). Set `PLAID_CLIENT_ID`, `PLAID_SECRET` and `PLAID_ENV` (`sandbox` to try it with Plaid's
test banks — user `user_good`, password `pass_good`).

- The Plaid `access_token` is stored encrypted (`FIELD_ENCRYPTION_KEY`) and never sent to the browser.
- Each Plaid account feeds one portfolio account: a new one by default, or one you choose; it can also be
  switched off. Credit cards and loans are listed but not synced.
- Sync (button, or `manage.py plaid_sync` daily from the scheduler) imports investment transactions
  idempotently: buys, sells, dividends, interest, fees → ledger; deposits/withdrawals/contributions →
  cash flows. Then each account is **reconciled** with the holdings the institution reports: units older
  than Plaid's ~24 months of history become an opening balance at the broker's average cost (dated before
  the first known trade), and anything still off — cash, splits, undetailed transfers — is fixed as of
  today. Adjustments are rebuilt on every sync, never stacked.
- Funds without a public ticker (401k collective trusts) are priced with the institution's price.
- If the institution asks to log in again, the connection is flagged and "Reconectar" opens Link in
  update mode.

## Domain model

| Model | Purpose |
|---|---|
| `Account` | Broker/IRA/401k/crypto/bank/loan/equity… `is_liquid` separates accessible money from retirement; `tax_treatment` (taxable / tax-deferred / tax-free) drives the after-tax estimate. |
| `Asset` | Symbol + class + price source (`yahoo`/`coingecko`/`manual`), plus `underlying` (e.g. "S&P 500"), `sector` and an optional `exposures` breakdown for multi-asset funds. |
| `Transaction` | Ledger entry: buy, sell, dividend, interest, staking, fee, split, transfer. Positions are derived from these (average cost); dividends/interest/fees move the account's USD cash. |
| `CashFlow` | Deposits/withdrawals/employer match into an account — used for "return vs. deposited". |
| `AllocationTarget` | Target % per asset within an account → rebalance amounts. |
| `EquityGrant` | Private-company options; unexercised valued at (FMV − strike). |
| `Snapshot` | Daily net-worth photo for the history chart. |
| `PriceHistory` | Daily closes from Yahoo (crypto as `SOL-USD`) for owned assets and benchmarks. |
| `UserSettings` | TP/SL %, retirement assumptions, benchmark, concentration limit, flat tax rates. |

Debt assets (class `debt`) are stored as positive balances and subtract from net worth.

## Analytics

- **Performance** (`services/performance.py`): holdings are re-valued daily from the ledger and `PriceHistory`.
  Time-weighted return (TWR) per period vs. a benchmark, money-weighted return (XIRR; not annualized for
  periods under a year), and a "same contributions in the benchmark" comparison. Flows are measured at the
  security level (buy = money in, sell = money out; dividends/interest/staking stay as return). Private
  equity and debt are excluded. `refresh_prices` also fetches missing history.
- **Exposure** (`services/exposure.py`): look-through by category, grouping by underlying (VOO + FXAIX →
  S&P 500) and by sector (e.g. crypto assets + crypto-company options), with alerts above the limit.
- **After-tax net worth** (`services/positions.py`): flat-rate estimate — FIFO tax lots in taxable accounts
  (short-term at the ordinary rate, long-term at the capital-gains rate), the full balance of tax-deferred
  accounts, NSO spread as ordinary income and ISO spread at capital-gains rates.
- **Tax lots** (`services/taxes.py`): short/long-term gains, tax-loss-harvesting candidates with wash-sale
  flags (securities only), and gains about to turn long-term.
- **Household allocation** (`services/allocation.py`): target mix by exposure category, drift vs. a threshold,
  and a sell plan that trims tax-advantaged accounts first, then the lowest embedded tax per dollar.
- **Risk** (`services/risk.py`): 12-month volatility and drawdown, per-holding volatility, return
  correlations, and stress scenarios (crypto winter, recession, 2008-style, inflation) plus a custom one;
  sector shocks (e.g. crypto-company equity) apply when more severe than the category shock.
- **Private equity** (`services/equity.py`): cliff + monthly vesting, liquidity discount, exercise cost,
  NSO tax / ISO AMT preference, and expiration alerts. Only vested equity counts toward net worth.
- **Planning** (`services/planning.py`): budget (`BudgetItem`) with savings rate and emergency-fund months
  (cash in accessible accounts vs. essential expenses); liabilities (`Liability`, subtracted from net worth)
  in avalanche order with pay-vs-invest verdicts; Monte Carlo retirement in today's dollars — lognormal
  returns, contributions + employer match, budget spending (or the withdrawal rate) minus Social Security,
  success probability, 10/50/90 bands and the financial-independence number and age. Seeded, so the same
  inputs give the same answer.
