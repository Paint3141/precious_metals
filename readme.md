# Commodity & FX Price Tracker

A lightweight Google Cloud Functions-based system that periodically fetches and stores USD prices for key commodities (Gold, Silver, Palladium, Bitcoin, Copper) and selected FX rates (GBP, EUR, CNY, JPY, RUB). It also monitors significant price movements and sends alerts via Telegram.

## Features

- **Periodic price updates**  
  Fetches latest commodity prices from [gold-api.com](https://gold-api.com) and FX rates from [exchangerate-api.com](https://www.exchangerate-api.com).

- **Persistent storage**  
  Stores historical prices in a PostgreSQL database using SQLModel.

- **Price movement alerts**  
  Checks for large percentage changes over 1-day (≥2%), 1-week (≥5%), and 1-month (≥10%) periods with per-commodity cooldowns to avoid spam.

- **Telegram notifications**  
  Sends formatted Markdown alerts to a specified chat when thresholds are breached.

## Repository Structure
├── update_prices.py          # Main update function (scheduled every 15–60 min)
├── check_and_alert.py        # Daily alert checker function
└── requirements.txt          # (recommended) dependencies


### `update_prices.py`

Cloud Function HTTP trigger that supports two tasks:

- `?task=commodities` → Fetches and saves latest commodity prices (Gold, Silver, Palladium, Bitcoin, Copper)
- `?task=fx` → Fetches and saves latest FX rates vs USD for configured currencies

Designed to be triggered frequently (every 15–60 minutes) via Cloud Scheduler.

### `check_and_alert.py`

Separate Cloud Function (typically scheduled once per day) that:

1. Queries the latest and historical commodity prices
2. Calculates percentage changes over multiple time windows
3. Triggers Telegram alerts only if thresholds are met and cooldown period has passed
4. Records sent alerts in a `sent_alerts` table to prevent duplicates

## Database Schema

Two main tables (auto-created on first run):

- `commodityprice`
  - `id` (PK)
  - `symbol` (e.g., XAU, BTC)
  - `name` (human-readable)
  - `usd_price`
  - `fetched_at` (UTC timestamp)

- `fxrate`
  - `id` (PK)
  - `currency` (e.g., EUR)
  - `rate_vs_usd`
  - `fetched_at` (UTC timestamp)

- `sent_alerts` (used by alert function)
  - `symbol`, `label` (daily/weekly/monthly) → composite unique key
  - `last_sent_at` (TIMESTAMPTZ)

## Environment Variables (required)

Both functions expect these in Cloud Functions environment or `.env` locally:

- `DATABASE_URL` → PostgreSQL connection string
- `EXCHANGE_RATE_API_KEY` → API key for exchangerate-api.com (only needed for `update_prices.py`)
- `TELEGRAM_BOT_TOKEN` → Telegram bot token (only needed for `check_and_alert.py`)
- `TELEGRAM_CHAT_ID` → Target chat ID for alerts (only needed for `check_and_alert.py`)

## Deployment Notes

- Deploy as two separate Google Cloud Functions (HTTP triggers).
- Use Cloud Scheduler:
  - `update_prices` → every 15–60 minutes (e.g., `*/30 * * * *`)
  - `check_and_alert` → once daily (e.g., `0 9 * * *`)

## Local Testing

```bash
pip install sqlmodel psycopg[binary] python-dotenv requests flask
# Create .env with required variables
python update_prices.py  # (with mocked request for HTTP trigger)