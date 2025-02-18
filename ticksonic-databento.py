import os
import sys
import math
import logging
import time
import threading
from datetime import datetime, timedelta

import pygame
import pygame.sndarray
import numpy as np
import databento as db
from termcolor import colored

from dotenv import load_dotenv
from zoneinfo import ZoneInfo

# Load .env file if it exists
load_dotenv()

# Initialize Pygame mixer
try:
    pygame.mixer.init()
except Exception as e:
    logging.error(f"Could not initialize pygame mixer: {e}")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logging.getLogger('databento').setLevel(logging.WARNING)

# Environment settings
API_KEY = os.getenv('DATABENTO_API_KEY', 'YOUR_API_KEY_HERE')
DEFAULT_THRESHOLD = 90000
DATASET = "EQUS.MINI"  # Nasdaq TotalView-ITCH

# Path to sound files
BUY_SOUND_PATH = os.getenv('BUY_SOUND_PATH', 'sounds/buy.wav')
SELL_SOUND_PATH = os.getenv('SELL_SOUND_PATH', 'sounds/sell.wav')
ABOVE_ASK_SOUND_PATH = os.getenv('ABOVE_ASK_SOUND_PATH', 'sounds/above_ask.wav')
BELOW_BID_SOUND_PATH = os.getenv('BELOW_BID_SOUND_PATH', 'sounds/below_bid.wav')
BETWEEN_BID_ASK_SOUND_PATH = os.getenv('BETWEEN_BID_ASK_SOUND_PATH', 'sounds/between_bid_ask.wav')

BIG_THRESHOLD = 490000.0
EPSILON = 1e-3  # in dollars

def format_amount(amount: float) -> str:
    if amount >= 1_000_000:
        millions = amount / 1_000_000
        floored = math.floor(millions * 10) / 10
        if floored.is_integer():
            floored = int(floored)
        return f"{floored} million"
    elif amount >= 1_000:
        thousands = amount / 1_000
        floored = math.floor(thousands * 10) / 10
        if floored.is_integer():
            floored = int(floored)
        return f"{floored}K"
    else:
        return f"{amount:,.2f}"

class AudioManager:
    def __init__(self):
        try:
            self.buy_sound = pygame.mixer.Sound(BUY_SOUND_PATH)
            self.sell_sound = pygame.mixer.Sound(SELL_SOUND_PATH)
            self.above_ask_sound = pygame.mixer.Sound(ABOVE_ASK_SOUND_PATH)
            self.below_bid_sound = pygame.mixer.Sound(BELOW_BID_SOUND_PATH)
            self.between_bid_ask_sound = pygame.mixer.Sound(BETWEEN_BID_ASK_SOUND_PATH)
        except Exception as e:
            logging.error(f"Error loading sound files: {e}")
            sys.exit(1)
        # Create pitch-shifted versions for "big" trades
        self.above_ask_sound_big = self.pitch_shift_sound(self.above_ask_sound, 1.5)
        self.buy_sound_big = self.pitch_shift_sound(self.buy_sound, 1.5)
        self.sell_sound_big = self.pitch_shift_sound(self.sell_sound, 0.8)
        self.below_bid_sound_big = self.pitch_shift_sound(self.below_bid_sound, 0.8)
        self.between_bid_ask_sound_ask = self.pitch_shift_sound(self.between_bid_ask_sound, 1.5)
        self.between_bid_ask_sound_bid = self.pitch_shift_sound(self.between_bid_ask_sound, 0.8)
        
    @staticmethod
    def pitch_shift_sound(original_sound: pygame.mixer.Sound, pitch_factor: float) -> pygame.mixer.Sound:
        if not original_sound:
            return None
        sound_array = pygame.sndarray.array(original_sound)
        num_samples = sound_array.shape[0]
        new_indices = np.arange(0, num_samples, 1.0 / pitch_factor)
        new_indices = np.round(new_indices).astype(int)
        new_indices = new_indices[new_indices < num_samples]
        if len(new_indices) == 0:
            logging.warning(f"Pitch shift resulted in empty array (pitch_factor={pitch_factor}).")
            return original_sound
        pitched_array = sound_array[new_indices] if sound_array.ndim == 1 else sound_array[new_indices, :]
        if pitched_array.size == 0:
            logging.warning(f"Pitch shift array is empty after indexing (pitch_factor={pitch_factor}).")
            return original_sound
        return pygame.sndarray.make_sound(pitched_array)

    # Define methods to play sounds
    def play_buy_sound(self):
        self.buy_sound.play()
    def play_sell_sound(self):
        self.sell_sound.play()
    def play_above_ask_sound(self):
        self.above_ask_sound.play()
    def play_below_bid_sound(self):
        self.below_bid_sound.play()
    def play_buy_sound_big(self):
        self.buy_sound_big.play()
    def play_sell_sound_big(self):
        self.sell_sound_big.play()
    def play_above_ask_sound_big(self):
        self.above_ask_sound_big.play()
    def play_below_bid_sound_big(self):
        self.below_bid_sound_big.play()
    def play_between_bid_ask_sound_ask(self):
        self.between_bid_ask_sound_ask.play()
    def play_between_bid_ask_sound_bid(self):
        self.between_bid_ask_sound_bid.play()
    def play_between_bid_ask_sound(self):
        self.between_bid_ask_sound.play()

class TradesProcessor:
    def __init__(self, api_key, trade_threshold, big_threshold, ticker, mode="live", start_time=None, end_time=None):
        self.api_key = api_key
        self.trade_threshold = trade_threshold
        self.big_threshold = big_threshold        
        self.ticker = ticker.upper()  # Ensure uppercase
        self.audio_manager = AudioManager()
        self.mode = mode
        self.start_time = start_time
        self.end_time = end_time
        self.latest_quote = {}  # Stores (ask, bid) for each ticker
        self._lock = threading.Lock()
        
        if mode == "live":
            self.client = db.Live(key=self.api_key)
        else:
            self.client = db.Historical(key=self.api_key)

    def convert_timestamp(self, ts):
        try:
            dt_obj = datetime.fromtimestamp(ts / 1e9, tz=ZoneInfo("UTC"))
            dt_eastern = dt_obj.astimezone(ZoneInfo("America/New_York"))
            return dt_eastern.strftime('%Y-%m-%d %H:%M:%S')
        except Exception as e:
            logging.error(f"Error converting timestamp {ts}: {e}")
            return "Invalid timestamp"

    def run_historical_debug(self):
        data = self.client.timeseries.get_range(
            dataset=DATASET,
            symbols=[self.ticker],
            schema="tbbo",
            stype_in="raw_symbol",
            start=self.start_time.isoformat(),
            end=self.end_time.isoformat(),
        )
        start_wall = time.time()
        with open("debug.txt", "w") as f:
            for record in data:
                if time.time() - start_wall >= 30:
                    break
                f.write(str(record) + "\n")
        print("Debug output written to debug.txt (first 30 seconds of raw data).")

    def run_live(self):
        self.client.add_callback(self.handle_record)
        self.client.subscribe(
            dataset=DATASET,
            schema="trades",
            symbols=[self.ticker],
            stype_in="raw_symbol"
        )
        self.client.subscribe(
            dataset=DATASET,
            schema="bbo-1s",
            symbols=[self.ticker],
            stype_in="raw_symbol"
        )
        self.client.start()
        self.client.block_for_close()

    def run_historical(self):
        current_start = self.start_time
        current_end = self.end_time

        while True:
            logging.info(f"Fetching data from {current_start.isoformat()} to {current_end.isoformat()}")
            data = list(self.client.timeseries.get_range(
                dataset=DATASET,
                symbols=[self.ticker],
                schema="tbbo",
                stype_in="raw_symbol",
                start=current_start.isoformat(),
                end=current_end.isoformat(),
            ))
            if not data:
                logging.info("No more data returned. Exiting historical loop.")
                break

            prev_ts = None
            for record in data:
                current_ts = getattr(record, "ts_event", None)
                if prev_ts is not None and current_ts is not None:
                    sleep_time = (current_ts - prev_ts) / 1e9
                    sleep_time = max(0, sleep_time)
                    time.sleep(sleep_time)
                self.handle_record(record)
                prev_ts = current_ts

                if current_ts is not None:
                    record_dt = datetime.fromtimestamp(current_ts / 1e9, tz=ZoneInfo("UTC"))
                    time_left = current_end - record_dt
                    if time_left < timedelta(minutes=2):
                        logging.info("Extending window by 1 hour.")
                        current_start = current_end
                        current_end = current_end + timedelta(hours=1)
                        break
            else:
                logging.info("Finished processing current window.")
                break

    def handle_record(self, record):
        try:
            ticker = getattr(record, 'symbol', self.ticker).upper()

            # Process BBO updates (live mode)
            raw_bid = getattr(record, 'bid_px_00', None)
            raw_ask = getattr(record, 'ask_px_00', None)
            if (raw_bid is None or raw_ask is None) and hasattr(record, 'levels') and record.levels:
                level0 = record.levels[0]
                raw_bid = getattr(level0, 'bid_px', raw_bid)
                raw_ask = getattr(level0, 'ask_px', raw_ask)
            
            def convert_price(value):
                return value if value < 10000 else value / 1e9

            if raw_bid is not None and raw_ask is not None:
                bid = convert_price(raw_bid)
                ask = convert_price(raw_ask)
                with self._lock:
                    self.latest_quote[ticker] = (ask, bid)
                    logging.debug(f"(BBO) Updated quote for {ticker}: ask={ask}, bid={bid}")
                if not hasattr(record, 'price'):  # Pure BBO update
                    return

            # Process trade events
            raw_price = getattr(record, 'price', None)
            raw_volume = getattr(record, 'size', None)
            ts = getattr(record, 'ts_event', None)
            if raw_price is None or raw_volume is None or ts is None:
                return

            price = convert_price(raw_price)
            volume = raw_volume
            amount = price * volume

            # Filter out trades below the threshold
            if amount < self.trade_threshold:
                return            

            timestamp_str = self.convert_timestamp(ts)
            
            with self._lock:
                ask, bid = self.latest_quote.get(ticker, (None, None))

            mid_px = (ask + bid) / 2.0 if (ask is not None and bid is not None) else None
            is_big_trade = (amount >= self.big_threshold)

            # Determine color and sound
            if ask is None or bid is None:
                color = 'white'
                self.audio_manager.play_between_bid_ask_sound()
            else:
                if abs(price - ask) < EPSILON:
                    color = 'green'
                    (self.audio_manager.play_buy_sound_big() if is_big_trade else self.audio_manager.play_buy_sound())
                elif abs(price - bid) < EPSILON:
                    color = 'red'
                    (self.audio_manager.play_sell_sound_big() if is_big_trade else self.audio_manager.play_sell_sound())
                elif price > (ask + EPSILON):
                    color = 'yellow'
                    (self.audio_manager.play_above_ask_sound_big() if is_big_trade else self.audio_manager.play_above_ask_sound())
                elif price < (bid - EPSILON):
                    color = 'magenta'
                    (self.audio_manager.play_below_bid_sound_big() if is_big_trade else self.audio_manager.play_below_bid_sound())
                else:
                    distance_to_ask = abs(price - ask)
                    distance_to_bid = abs(price - bid)
                    color = 'white'
                    if abs(distance_to_ask - distance_to_bid) < 1e-9:
                        self.audio_manager.play_between_bid_ask_sound()
                    elif distance_to_ask < distance_to_bid:
                        self.audio_manager.play_between_bid_ask_sound_ask()
                    else:
                        self.audio_manager.play_between_bid_ask_sound_bid()

            formatted_amount = format_amount(amount)
            price_str = f"{price:,.2f}"
            mid_str = f"{mid_px:,.2f}" if mid_px is not None else "N/A"
            attrs = ['bold'] if is_big_trade else []
            print(colored(
                f"Price: {price_str} | Mid: {mid_str} | Amount: ${formatted_amount} | Time: {timestamp_str} | Ticker: {ticker}",
                color=color,
                attrs=attrs
            ))
        except Exception as e:
            logging.error(f"Error handling record: {e}")

    def run(self):
        if self.mode == "live":
            self.run_live()
        elif self.mode == "historical_debug":
            self.run_historical_debug()
        else:
            self.run_historical()

def main():
    """
    Usage:
      Live mode: python script.py [ticker] [threshold] [big_threshold]
      Historical mode: python script.py [ticker] [threshold] [big_threshold] [YYYYMMDD] [hhmm(am/pm)]
      Historical debug: python script.py [ticker] [threshold] [big_threshold] [YYYYMMDD] [hhmm(am/pm)] debug
      
      Examples:
        python script.py TSLA 90000 490000
        python script.py tsla 90000 490000 20250214 0930am
        python script.py tsla 90000 490000 20250214 0930am debug
    """
    arg_len = len(sys.argv)
    if arg_len not in (4, 6, 7):
        print("Invalid arguments. See usage in docstring.")
        sys.exit(1)

    ticker = sys.argv[1].upper()
    try:
        threshold = float(sys.argv[2])
        big_threshold = float(sys.argv[3])
    except ValueError:
        print("Error: threshold and big_threshold must be numeric.")
        sys.exit(1)

    if arg_len >= 6:
        mode = "historical"
        date_str = sys.argv[4]
        time_str = sys.argv[5]
        if arg_len == 7 and sys.argv[6].lower() == "debug":
            mode = "historical_debug"
        try:
            dt_date = datetime.strptime(date_str, "%Y%m%d").date()
            dt_time = datetime.strptime(time_str.lower(), "%I%M%p").time()
            local_dt = datetime.combine(dt_date, dt_time, tzinfo=ZoneInfo("America/New_York"))
            start_dt = local_dt.astimezone(ZoneInfo("UTC"))
            end_dt = start_dt + timedelta(hours=1)
        except Exception as e:
            print(f"Error parsing date/time: {e}")
            sys.exit(1)
    else:
        mode = "live"
        start_dt = None
        end_dt = None

    processor = TradesProcessor(API_KEY, threshold, big_threshold, ticker,
                               mode=mode, start_time=start_dt, end_time=end_dt)
    processor.run()

if __name__ == '__main__':
    main()
