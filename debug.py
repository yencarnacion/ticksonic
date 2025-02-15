import os
import sys
import time
from datetime import datetime, timedelta

import databento as db
from zoneinfo import ZoneInfo  # Requires Python 3.9+
from dotenv import load_dotenv

# Load environment variables (including DATABENTO_API_KEY)
load_dotenv()

API_KEY = os.getenv('DATABENTO_API_KEY', 'YOUR_API_KEY_HERE')
DATASET = "XNAS.ITCH"  # Nasdaq TotalView-ITCH

def main():
    if len(sys.argv) < 6:
        print("Usage: python debug.py <ticker> <threshold> <big_threshold> <YYYYMMDD> <hhmm(am/pm)> debug")
        sys.exit(1)

    # Convert ticker to uppercase
    ticker = sys.argv[1].upper()

    # Parse numeric thresholds (unused in debug mode but required for consistency)
    try:
        threshold = float(sys.argv[2])
        big_threshold = float(sys.argv[3])
    except ValueError:
        print("Error: threshold and big_threshold must be numeric.")
        sys.exit(1)

    # Parse date and time; assume provided time is Eastern Time
    date_str = sys.argv[4]
    time_str = sys.argv[5]
    try:
        dt_date = datetime.strptime(date_str, "%Y%m%d").date()
        dt_time = datetime.strptime(time_str.lower(), "%I%M%p").time()
        local_dt = datetime.combine(dt_date, dt_time, tzinfo=ZoneInfo("America/New_York"))
        start_dt = local_dt.astimezone(ZoneInfo("UTC"))
    except Exception as e:
        print(f"Error parsing date/time: {e}")
        sys.exit(1)
    # For this debug mode we use a 1‑hour window.
    end_dt = start_dt + timedelta(hours=1)

    # Create a historical client and fetch TBBO data.
    client = db.Historical(key=API_KEY)
    data = client.timeseries.get_range(
        dataset=DATASET,
        symbols=[ticker],
        schema="tbbo",
        stype_in="raw_symbol",
        start=start_dt.isoformat(),
        end=end_dt.isoformat(),
    )

    # Write raw records to debug.txt for the first 30 seconds (wall‑clock time).
    start_wall = time.time()
    record_count = 0
    with open("debug.txt", "w") as f:
        for record in data:
            if time.time() - start_wall >= 30:
                break
            f.write(str(record) + "\n")
            record_count += 1

    print(f"Debug output written to debug.txt. Total records written: {record_count}")

if __name__ == '__main__':
    main()
