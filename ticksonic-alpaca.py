import os
import sys
import math
import logging
import time
import threading
import json
from datetime import datetime

import pygame
import pygame.sndarray
import numpy as np
import websocket
from termcolor import colored
from dotenv import load_dotenv

# Load .env file (if present) without overriding existing environment variables
load_dotenv()

# Initialize Pygame mixer
try:
    pygame.mixer.init()
except Exception as e:
    logging.error(f"Could not initialize pygame mixer: {e}")
    sys.exit(1)

# Set up logging
logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(message)s')

# Environment variables and default settings
ALPACA_API_KEY = os.getenv('ALPACA_API_KEY', 'YOUR_API_KEY_HERE')
ALPACA_API_SECRET = os.getenv('ALPACA_API_SECRET', 'YOUR_API_SECRET_HERE')
# Choose your feed: e.g., 'sip' or 'iex' (see :contentReference[oaicite:1]{index=1})
ALPACA_FEED = os.getenv('ALPACA_FEED', 'sip')
ALPACA_STREAM_URL = os.getenv('ALPACA_STREAM_URL', f"wss://stream.data.alpaca.markets/v2/{ALPACA_FEED}")

DEFAULT_TICKER = "TSLA"
DEFAULT_THRESHOLD = 90000
BIG_THRESHOLD = 490000.0

# Paths to sound files (customize as needed)
BUY_SOUND_PATH = os.getenv('BUY_SOUND_PATH', 'sounds/buy.wav')
SELL_SOUND_PATH = os.getenv('SELL_SOUND_PATH', 'sounds/sell.wav')
ABOVE_ASK_SOUND_PATH = os.getenv('ABOVE_ASK_SOUND_PATH', 'sounds/above_ask.wav')
BELOW_BID_SOUND_PATH = os.getenv('BELOW_BID_SOUND_PATH', 'sounds/below_bid.wav')
BETWEEN_BID_ASK_SOUND_PATH = os.getenv('BETWEEN_BID_ASK_SOUND_PATH', 'sounds/between_bid_ask.wav')

EPSILON = 1e-3

def format_amount(amount: float) -> str:
    """
    Format a numeric amount into a truncated string representation.
    """
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

        # Pre-generate pitched versions for "big" trades
        self.above_ask_sound_big = self.pitch_shift_sound(self.above_ask_sound, pitch_factor=1.5)
        self.buy_sound_big = self.pitch_shift_sound(self.buy_sound, pitch_factor=1.5)
        self.sell_sound_big = self.pitch_shift_sound(self.sell_sound, pitch_factor=0.8)
        self.below_bid_sound_big = self.pitch_shift_sound(self.below_bid_sound, pitch_factor=0.8)
        # Closer to bid or ask sounds
        self.between_bid_ask_sound_ask = self.pitch_shift_sound(self.between_bid_ask_sound, pitch_factor=1.5)
        self.between_bid_ask_sound_bid = self.pitch_shift_sound(self.between_bid_ask_sound, pitch_factor=0.8)
    
    @staticmethod
    def pitch_shift_sound(original_sound: pygame.mixer.Sound, pitch_factor: float) -> pygame.mixer.Sound:
        if not original_sound:
            return None
        sound_array = pygame.sndarray.array(original_sound)
        num_samples = sound_array.shape[0]  # works for mono and multi-channel alike
        new_indices = np.arange(0, num_samples, 1.0 / pitch_factor)
        new_indices = np.round(new_indices).astype(np.int32)
        new_indices = new_indices[new_indices < num_samples]
        if len(new_indices) == 0:
            logging.warning(f"Pitch shift resulted in empty array (pitch_factor={pitch_factor}). Returning original sound.")
            return original_sound
        if sound_array.ndim == 1:
            pitched_array = sound_array[new_indices]
        else:
            pitched_array = sound_array[new_indices, :]
        if pitched_array.size == 0:
            logging.warning(f"Pitch shift array is empty after indexing (pitch_factor={pitch_factor}). Returning original sound.")
            return original_sound
        return pygame.sndarray.make_sound(pitched_array)

    def play_above_ask_sound(self):
        if self.above_ask_sound is not None:
            self.above_ask_sound.play()

    def play_above_ask_sound_big(self):
        if self.above_ask_sound_big is not None:
            self.above_ask_sound_big.play()

    def play_buy_sound(self):
        if self.buy_sound is not None:
            self.buy_sound.play()

    def play_buy_sound_big(self):
        if self.buy_sound_big is not None:
            self.buy_sound_big.play()

    def play_between_bid_ask_sound_ask(self):
        if self.between_bid_ask_sound_ask is not None:
            self.between_bid_ask_sound_ask.play()

    def play_between_bid_ask_sound(self):
        if self.between_bid_ask_sound is not None:
            self.between_bid_ask_sound.play()

    def play_between_bid_ask_sound_bid(self):
        if self.between_bid_ask_sound_bid is not None:
            self.between_bid_ask_sound_bid.play()

    def play_sell_sound(self):
        if self.sell_sound is not None:
            self.sell_sound.play()

    def play_sell_sound_big(self):
        if self.sell_sound_big is not None:
            self.sell_sound_big.play()

    def play_below_bid_sound(self):
        if self.below_bid_sound is not None:
            self.below_bid_sound.play()

    def play_below_bid_sound_big(self):
        if self.below_bid_sound_big is not None:
            self.below_bid_sound_big.play()

class TradesProcessor:
    def __init__(self, api_key, api_secret, trade_threshold, big_threshold, ticker):
        self.api_key = api_key
        self.api_secret = api_secret
        self.trade_threshold = trade_threshold
        self.big_threshold = big_threshold
        self.ticker = ticker
        self.audio_manager = AudioManager()
        self.latest_quotes = {}
        self._lock = threading.Lock()
        self.ws = None

    def convert_timestamp(self, ts_str):
        """
        Convert an RFC‑3339 timestamp string (with nanosecond precision) to a human‑readable format.
        Limits fractional seconds to 6 digits.
        """
        try:
            if '.' in ts_str:
                base, frac = ts_str.split('.')
                frac = frac.rstrip("Z")[:6]
                ts_str = base + '.' + frac + '+00:00'
            dt_obj = datetime.fromisoformat(ts_str)
            return dt_obj.strftime('%Y-%m-%d %H:%M:%S')
        except Exception as e:
            logging.error(f"Timestamp conversion error: {e}")
            return "Invalid timestamp"

    def handle_quote_message(self, quote):
        try:
            ticker = quote.get("S")
            ask = quote.get("ap")
            bid = quote.get("bp")
            with self._lock:
                self.latest_quotes[ticker] = {'ask': ask, 'bid': bid}
            formatted_time = self.convert_timestamp(quote.get("t"))
            logging.info(f"Quote {ticker} at {formatted_time}: Ask={ask}, Bid={bid}")
        except Exception as e:
            logging.error(f"Error handling quote message: {e}")

    def handle_trade_message(self, trade):
        try:
            ticker = trade.get("S")
            price = trade.get("p")
            volume = trade.get("s")
            amount = price * volume
            timestamp_str = self.convert_timestamp(trade.get("t"))

            # Skip small trades
            if amount < self.trade_threshold:
                logging.debug(f"Trade {ticker} at {timestamp_str} ignored (Amount: ${amount:.2f})")
                return

            with self._lock:
                quote = self.latest_quotes.get(ticker, {})
                ask = quote.get('ask')
                bid = quote.get('bid')

            is_big_trade = (amount >= self.big_threshold)

            if ask is None or bid is None:
                color = 'white'
                self.audio_manager.play_between_bid_ask_sound()
                formatted_amount = format_amount(amount)
                price_str = f"{price:,.2f}"
                on_color = 'on_grey' if is_big_trade else None
                attrs = ['bold'] if is_big_trade else []
                print(colored(
                    f"Price: {price_str} | Amount: ${formatted_amount} | Time: {timestamp_str} | Ticker: {ticker}",
                    color=color,
                    on_color=on_color,
                    attrs=attrs
                ))
                return

            if abs(price - ask) < EPSILON:
                color = 'green'
                if is_big_trade:
                    self.audio_manager.play_buy_sound_big()
                else:
                    self.audio_manager.play_buy_sound()
            elif abs(price - bid) < EPSILON:
                color = 'red'
                if is_big_trade:
                    self.audio_manager.play_sell_sound_big()
                else:
                    self.audio_manager.play_sell_sound()
            elif price > (ask + EPSILON):
                color = 'yellow'
                if is_big_trade:
                    self.audio_manager.play_above_ask_sound_big()
                else:
                    self.audio_manager.play_above_ask_sound()
            elif price < (bid - EPSILON):
                color = 'magenta'
                if is_big_trade:
                    self.audio_manager.play_below_bid_sound_big()
                else:
                    self.audio_manager.play_below_bid_sound()
            else:
                distance_to_ask = abs(price - ask)
                distance_to_bid = abs(price - bid)
                color = 'white'
                if abs(distance_to_ask - distance_to_bid) < 1e-9:
                    self.audio_manager.play_between_bid_ask_sound()
                else:
                    if distance_to_ask < distance_to_bid:
                        self.audio_manager.play_between_bid_ask_sound_ask()
                    else:
                        self.audio_manager.play_between_bid_ask_sound_bid()

            formatted_amount = format_amount(amount)
            price_str = f"{price:,.2f}"
            on_color = 'on_grey' if is_big_trade else None
            attrs = ['bold'] if is_big_trade else []
            print(colored(
                f"Price: {price_str} | Amount: ${formatted_amount} | Time: {timestamp_str} | Ticker: {ticker}",
                color=color,
                on_color=on_color,
                attrs=attrs
            ))
        except Exception as e:
            logging.error(f"Error handling trade message: {e}")

    def handle_message(self, message):
        """
        Processes a received message string (which may contain a JSON array of messages).
        """
        try:
            data = json.loads(message)
            if isinstance(data, dict):
                data = [data]
            for msg in data:
                if "T" not in msg:
                    continue
                if msg["T"] == "t":
                    self.handle_trade_message(msg)
                elif msg["T"] == "q":
                    self.handle_quote_message(msg)
                else:
                    logging.info(f"Received message: {msg}")
        except Exception as e:
            logging.error(f"Error processing message: {e}")

    def on_open(self, ws):
        logging.info("WebSocket connection opened.")
        # Send authentication message per Alpaca's protocol
        auth_msg = {
            "action": "auth",
            "key": self.api_key,
            "secret": self.api_secret
        }
        ws.send(json.dumps(auth_msg))
        # Subscribe to trades and quotes for the specified ticker
        subscribe_msg = {
            "action": "subscribe",
            "trades": [self.ticker],
            "quotes": [self.ticker]
        }
        ws.send(json.dumps(subscribe_msg))

    def on_message(self, ws, message):
        self.handle_message(message)

    def on_error(self, ws, error):
        logging.error(f"WebSocket error: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        logging.info(f"WebSocket closed: {close_status_code} - {close_msg}")

    def run(self):
        """
        Continuously run the WebSocket client. Retries on errors up to 3 times, sleeping 10 seconds between attempts.
        """
        max_retries = 3
        delay = 10
        remaining_retries = max_retries

        while True:
            try:
                self.ws = websocket.WebSocketApp(
                    ALPACA_STREAM_URL,
                    on_open=self.on_open,
                    on_message=self.on_message,
                    on_error=self.on_error,
                    on_close=self.on_close
                )
                self.ws.run_forever()
                logging.info("WebSocket connection ended gracefully.")
                remaining_retries = max_retries
            except KeyboardInterrupt:
                logging.info("KeyboardInterrupt detected. Shutting down gracefully.")
                break
            except Exception as e:
                remaining_retries -= 1
                if remaining_retries > 0:
                    logging.error(
                        f"WebSocket encountered an error: {e}. Retrying in {delay} seconds... (Remaining retries: {remaining_retries})"
                    )
                    time.sleep(delay)
                else:
                    logging.error(
                        f"WebSocket encountered an error: {e}. No more retries left. Shutting down gracefully."
                    )
                    break

def main():
    """
    Usage:
      python ticksonic-alpaca.py [ticker] [threshold] [big_threshold]

    Defaults:
      ticker = TSLA, threshold = 90000, big_threshold = 490000.
    """
    if len(sys.argv) > 4:
        print("Usage: python ticksonic-alpaca.py [ticker] [threshold] [big_threshold]")
        sys.exit(1)

    if len(sys.argv) == 1:
        ticker = DEFAULT_TICKER
        threshold = DEFAULT_THRESHOLD
        big_threshold = BIG_THRESHOLD
    elif len(sys.argv) == 2:
        ticker = sys.argv[1].upper()
        threshold = DEFAULT_THRESHOLD
        big_threshold = BIG_THRESHOLD
    elif len(sys.argv) == 3:
        ticker = sys.argv[1].upper()
        try:
            threshold = float(sys.argv[2])
        except ValueError:
            print("Error: threshold must be a numeric value.")
            sys.exit(1)
        big_threshold = BIG_THRESHOLD
    else:  # exactly 4 arguments
        ticker = sys.argv[1].upper()
        try:
            threshold = float(sys.argv[2])
        except ValueError:
            print("Error: threshold must be a numeric value.")
            sys.exit(1)
        try:
            big_threshold = float(sys.argv[3])
        except ValueError:
            print("Error: big_threshold must be a numeric value.")
            sys.exit(1)

    processor = TradesProcessor(ALPACA_API_KEY, ALPACA_API_SECRET, threshold, big_threshold, ticker)
    processor.run()

if __name__ == '__main__':
    main()
