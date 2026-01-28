# update_prices.py   ← run this every 15–60 minutes

import os
import requests
from datetime import datetime
from dotenv import load_dotenv
from sqlmodel import SQLModel, Field, Session, create_engine, select
from flask import abort

load_dotenv()

# ==================== CONFIG ====================
DATABASE_URL = os.getenv("DATABASE_URL")
EXCHANGE_API_KEY = os.getenv("EXCHANGE_RATE_API_KEY")
METAL_PRICE_API_KEY = os.getenv("METAL_PRICE_API_KEY")  # New API key for metalpriceapi.com

if not DATABASE_URL or not EXCHANGE_API_KEY:
    raise RuntimeError("Missing DATABASE_URL or EXCHANGE_RATE_API_KEY in .env")

# Add this check if you want to enforce the new key, but it's only needed for platinum
if not METAL_PRICE_API_KEY:
    print("Warning: METAL_PRICE_API_KEY not set in .env – platinum updates will fail.")

# Currencies to track vs USD
CURRENCIES_OF_INTEREST = ["GBP", "EUR", "CNY", "JPY", "RUB"]

# Commodities to track (symbol → friendly name)
COMMODITIES = {
    "XAU": "Gold",
    "XAG": "Silver",
    "XPT": "Platinum",  # Uncommented/added for platinum support
    "XPD": "Palladium",
    "BTC": "Bitcoin",
    "HG": "Copper (per pound)",  # HG = Copper futures symbol
}

engine = create_engine(DATABASE_URL, echo=False)

# ==================== MODELS ====================
class CommodityPrice(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    symbol: str = Field(max_length=10, index=True)        # e.g., XAU, BTC, XAG
    name: str = Field(max_length=50)                     # Human readable
    usd_price: float
    fetched_at: datetime = Field(default_factory=datetime.utcnow, index=True)

class FXRate(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    currency: str = Field(max_length=3, index=True)
    rate_vs_usd: float
    fetched_at: datetime = Field(default_factory=datetime.utcnow, index=True)

# Create tables if they don't exist
SQLModel.metadata.create_all(engine)

# ==================== CORE FUNCTIONS ====================
def fetch_commodity_prices() -> dict:
    """
    Fetches latest USD prices for all commodities from gold-api.com
    Returns dict like: {"XAU":  {"price": 2350.5, "name": "Gold"}, ...}
    """
    prices = {}
    base_url = "https://api.gold-api.com/price"

    for symbol in COMMODITIES.keys():
        if symbol == "XPT":  # Skip platinum – handled separately
            continue
        try:
            resp = requests.get(f"{base_url}/{symbol}", timeout=10)
            if resp.status_code == 404:
                print(f"Warning: Symbol {symbol} not supported by gold-api.com (yet?)")
                continue
            resp.raise_for_status()
            data = resp.json()
            price = data.get("price")
            if price is not None:
                prices[symbol] = float(price)
                print(f"Fetched {COMMODITIES[symbol]} ({symbol}): ${price:,.2f}")
            else:
                print(f"Warning: No price data for {symbol}")
        except Exception as e:
            print(f"Error fetching {symbol}: {e}")

    return prices

def fetch_platinum_price() -> dict:
    """
    Fetches latest USD price for platinum (XPT) from metalpriceapi.com
    Returns dict like: {"XPT": price} or empty dict on failure
    """
    symbol = "XPT"
    prices = {}
    base_url = "https://api.metalpriceapi.com/v1/latest"
    api_key = os.getenv("METAL_PRICE_API_KEY")
    
    if not api_key:
        print("Error: METAL_PRICE_API_KEY not set in .env")
        return prices

    params = {
        "api_key": api_key,
        "base": "USD",
        "currencies": "XPT"
    }

    try:
        resp = requests.get(base_url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        if not data.get("success"):
            print(f"Error: API response success=false for {symbol}")
            return prices
        
        price = data["rates"].get("USDXPT")
        if price is not None:
            prices[symbol] = float(price)
            print(f"Fetched {COMMODITIES[symbol]} ({symbol}): ${price:,.2f}")
        else:
            print(f"Warning: No USDXPT price data for {symbol}")
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")

    return prices

def save_commodity_prices(price_dict: dict):
    """Save fetched commodity prices into the unified table"""
    if not price_dict:
        print("No commodity prices to save.")
        return

    with Session(engine) as session:
        for symbol, usd_price in price_dict.items():
            entry = CommodityPrice(
                symbol=symbol,
                name=COMMODITIES[symbol],
                usd_price=usd_price,
            )
            session.add(entry)
        session.commit()
    print(f"Saved {len(price_dict)} commodity prices.")

def save_all_fx_rates():
    """Fetch and store latest FX rates vs USD"""
    print(f"Updating FX rates @ {datetime.utcnow().isoformat()}Z")

    try:
        resp = requests.get(
            f"https://v6.exchangerate-api.com/v6/{EXCHANGE_API_KEY}/latest/USD",
            timeout=12
        )
        resp.raise_for_status()
        rates_dict = resp.json()["conversion_rates"]
    except Exception as e:
        print(f"Exchange rate API failed: {e}")
        return

    with Session(engine) as session:
        for currency in CURRENCIES_OF_INTEREST:
            if currency in rates_dict:
                session.add(FXRate(currency=currency, rate_vs_usd=rates_dict[currency]))
        session.commit()
    print(f"Saved FX rates for {len(CURRENCIES_OF_INTEREST)} currencies.")


def price_update(request):
    """HTTP Cloud Function.
    Args:
        request (flask.Request): The request object.
        ?task=commodities  or ?task=fx or ?task=platinum
    """
    task = request.args.get('task')
    if task == 'commodities':
        commodity_prices = fetch_commodity_prices()
        save_commodity_prices(commodity_prices)
        return "Commodities updated", 200
    elif task == 'fx':
        save_all_fx_rates()
        return "FX rates updated", 200
    elif task == 'platinum':
        platinum_prices = fetch_platinum_price()
        save_commodity_prices(platinum_prices)
        return "Platinum updated", 200
    else:
        abort(400, "Invalid task. Use ?task=commodities or ?task=fx or ?task=platinum")


# # ==================== MAIN ====================
# if __name__ == "__main__":
#     print(f"\n=== Price Update Run @ {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%SZ')} ===\n")

#     # 1. Update all commodities (excluding platinum)
#     commodity_prices = fetch_commodity_prices()
#     save_commodity_prices(commodity_prices)

#     # 2. Update platinum separately (limited to 5x/day)
#     platinum_prices = fetch_platinum_price()
#     save_commodity_prices(platinum_prices)

#     # 3. Update FX rates
#     save_all_fx_rates()

#     print("\nUpdate complete!\n")