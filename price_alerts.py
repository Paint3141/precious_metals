import os
import requests
import psycopg
from dotenv import load_dotenv
from datetime import datetime, timedelta
from datetime import timezone  # Important!

load_dotenv()

def fetch_and_save_prices(request):  # GCF HTTP trigger entry point

    conn_string = os.environ['DATABASE_URL']
    bot_token = os.environ['TELEGRAM_BOT_TOKEN']
    chat_id = os.environ['TELEGRAM_CHAT_ID']

    alerts = []

    # Use timezone-aware UTC now
    current_time = datetime.now(timezone.utc)

    with psycopg.connect(conn_string) as conn:
        with conn.cursor() as cur:

            # Get unique commodities
            cur.execute("SELECT DISTINCT symbol FROM commodityprice")
            commodity_names = [row[0] for row in cur.fetchall()]

            # Define thresholds
            thresholds = [
                {"period": "1 day",   "days": 1,  "pct": 2,  "label": "daily"},
                {"period": "1 week",  "days": 7,  "pct": 5,  "label": "weekly"},
                {"period": "1 month", "days": 30, "pct": 10, "label": "monthly"},
            ]

            for name in commodity_names:

                print(f"Processing {name}")

                # Get current (latest) price
                cur.execute("""
                    SELECT usd_price FROM commodityprice
                    WHERE symbol = %s
                    ORDER BY fetched_at DESC LIMIT 1
                """, (name,))
                current_price_row = cur.fetchone()
                if not current_price_row:
                    continue
                current_price = current_price_row[0]

                for thresh in thresholds:

                    label = thresh['label']

                    cooldown_period = timedelta(days=thresh['days'])

                    # Check when this alert type was last sent
                    cur.execute("""
                        SELECT last_sent_at FROM sent_alerts
                        WHERE symbol = %s AND label = %s
                    """, (name, label))
                    last_sent_row = cur.fetchone()

                    if last_sent_row:
                        last_sent_at = last_sent_row[0]  # This is timezone-aware (TIMESTAMPTZ)
                        if current_time - last_sent_at < cooldown_period:
                            print(f"  Skipping {name} {label} alert - cooldown active")
                            continue

                    # Calculate cutoff for historical price (also timezone-aware)
                    cutoff_timestamp = current_time - cooldown_period

                    cur.execute("""
                        SELECT usd_price FROM commodityprice
                        WHERE symbol = %s
                          AND fetched_at <= %s
                        ORDER BY fetched_at DESC LIMIT 1
                    """, (name, cutoff_timestamp))
                    old_price_row = cur.fetchone()

                    if not old_price_row:
                        continue
                    old_price = old_price_row[0]

                    if old_price == 0:
                        continue

                    pct_change = (current_price - old_price) / old_price * 100

                    if abs(pct_change) >= thresh['pct']:
                        direction = "up" if pct_change > 0 else "down"
                        emoji = "📈" if direction == "up" else "📉"

                        alert_lines = [
                            f"\n{emoji} *{name}* moved *{abs(pct_change):.2f}%* {direction} "
                            f"in the last {thresh['period']}\n",
                            f"   • Old price: ${old_price:,.2f}",
                            f"   • New price: ${current_price:,.2f}",
                            f"   • {thresh['label']} alert ≥ {thresh['pct']}%"
                        ]

                        alerts.append("\n".join(alert_lines))

                        # Record/update the alert sent time (timezone-aware)
                        cur.execute("""
                            INSERT INTO sent_alerts (symbol, label, last_sent_at)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (symbol, label) DO UPDATE
                            SET last_sent_at = EXCLUDED.last_sent_at
                        """, (name, label, current_time))

                        print(f"  Alert triggered and recorded for {name} {label}")

            # Commit all sent_alerts updates
            conn.commit()

    # Send alerts via Telegram
    if alerts:
        message = "*Commodity Price Alerts*\n\n" + "\n\n".join(alerts)
        message += f"\n\n_Timestamp: {current_time.strftime('%Y-%m-%d %H:%M UTC')}_"

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            'chat_id': chat_id,
            'text': message,
            'parse_mode': 'Markdown'
        }

        try:
            response = requests.post(url, data=payload, timeout=10)
            if response.status_code == 200:
                print("Telegram message sent successfully")
            else:
                print(f"Telegram send failed: {response.status_code} {response.text}")
        except Exception as e:
            print(f"Exception sending Telegram message: {e}")
    else:
        print("No alerts to send")

    return 'Price check complete', 200
