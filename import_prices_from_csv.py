# import_prices_from_csv.py
# Run this script locally to import historical commodity prices from CSV into the Neon database.

import os
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
from sqlmodel import SQLModel, Field, Session, create_engine

load_dotenv()

# ==================== CONFIG ====================
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("Missing DATABASE_URL in .env")

# Commodities to import (based on your provided dict, only those present in CSV)
COMMODITY_MAP = {
    'XAUUSD': ('XAU', 'Gold'),
    'XAGUSD': ('XAG', 'Silver'),
    'XPDUSD': ('XPD', 'Palladium'),
    # Uncomment if you want to include Platinum (it's in the CSV but commented in your dict)
    'XPTUSD': ('XPT', 'Platinum'),
}

# CSV file path (assume it's in the same directory; adjust if needed)
CSV_FILE = '.datafiles/commodities_1H.csv'  # Updated path based on your error message

engine = create_engine(DATABASE_URL, echo=False)

# ==================== MODELS ====================
class CommodityPrice(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    symbol: str = Field(max_length=10, index=True)        # e.g., XAU, BTC, XAG
    name: str = Field(max_length=50)                     # Human readable
    usd_price: float
    fetched_at: datetime = Field(index=True)  # We'll set this manually from CSV 'time'

# Create table if it doesn't exist
SQLModel.metadata.create_all(engine)

# ==================== IMPORT FUNCTION ====================
def import_from_csv():
    print(f"\n=== Importing from {CSV_FILE} @ {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%SZ')} ===\n")

    # Read CSV using pandas
    try:
        df = pd.read_csv(CSV_FILE)
        print(f"Loaded CSV with {len(df)} rows.")
    except Exception as e:
        raise RuntimeError(f"Failed to read CSV: {e}")

    # Define cutoff datetime
    cutoff = datetime(2025, 12, 30, 15, 0, 0)

    # Prepare list of dict entries (for bulk_insert_mappings)
    entries = []
    for _, row in df.iterrows():
        time_str = row['time']
        if pd.isna(time_str):
            print(f"Skipping row with missing time: {row}")
            continue
        try:
            fetched_at = datetime.strptime(str(time_str), '%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError) as e:
            print(f"Skipping row with invalid time: {time_str} ({e})")
            continue

        # Skip rows at or after the cutoff
        if fetched_at >= cutoff:
            continue

        for col, (symbol, name) in COMMODITY_MAP.items():
            if col in df.columns and pd.notna(row[col]):
                try:
                    usd_price = float(row[col])
                    entry = {
                        'symbol': symbol,
                        'name': name,
                        'usd_price': usd_price,
                        'fetched_at': fetched_at
                    }
                    entries.append(entry)
                except ValueError:
                    print(f"Skipping invalid price for {symbol} at {time_str}")

    if not entries:
        print("No valid data to import.")
        return

    # Bulk insert using mappings (avoids RETURNING/sentinel issues)
    with Session(engine) as session:
        session.bulk_insert_mappings(CommodityPrice, entries)
        session.commit()
    print(f"Inserted {len(entries)} records.")

# ==================== MAIN ====================
if __name__ == "__main__":
    import_from_csv()
    print("\nImport complete!\n")