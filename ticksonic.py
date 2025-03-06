import os
import sys
import math
import logging
import time
import threading
from datetime import datetime

import pygame
import pygame.sndarray
import numpy as np  
from polygon import WebSocketClient
from polygon.websocket.models import EquityTrade, EquityQuote
from termcolor import colored

from dotenv import load_dotenv

# Load .env file if it exists, without overriding existing environment variables
load_dotenv()

# --- Check for the --silent flag ---
silent = False
if '--silent' in sys.argv:
    silent = True
    sys.argv.remove('--silent')

# Initialize Pygame mixer (only if not silent)
if not silent:
    try:
        pygame.mixer.init()
    except Exception as e:
        logging.error(f"Could not initialize pygame mixer: {e}")
        sys.exit(1)

# Set up logging
logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(message)s')
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

# Environment or default settings
API_KEY = os.getenv('POLYGON_API_KEY', 'YOUR_API_KEY_HERE')
DEFAULT_TICKER = "TSLA"
DEFAULT_THRESHOLD = 90000

# Path to sound files
BUY_SOUND_PATH = os.getenv('BUY_SOUND_PATH', 'sounds/buy.wav')
SELL_SOUND_PATH = os.getenv('SELL_SOUND_PATH', 'sounds/sell.wav')
ABOVE_ASK_SOUND_PATH = os.getenv('ABOVE_ASK_SOUND_PATH', 'sounds/above_ask.wav')
BELOW_BID_SOUND_PATH = os.getenv('BELOW_BID_SOUND_PATH', 'sounds/below_bid.wav')
BETWEEN_BID_ASK_SOUND_PATH = os.getenv('BETWEEN_BID_ASK_SOUND_PATH', 'sounds/between_bid_ask.wav')

# Secondary threshold for “big” trades (e.g., $490k)
BIG_THRESHOLD = 490000.0

# Epsilon for float comparisons
EPSILON = 1e-3

def format_amount(amount: float) -> str:
    """
    Convert the numeric amount to a truncated string representation:
      - >= 1,000,000 => 'X.Y million'
      - >= 1,000 => 'X.YK'
      - otherwise => regular format with commas and 2 decimals.
    Floors to one decimal place in the 'K'/'million' cases, removing trailing .0 if present.
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
        # Regular numeric format with commas and 2 decimals
        return f"{amount:,.2f}"

class AudioManager:
    def __init__(self):
        """
        Preload all sounds using Pygame to avoid repeated file I/O.
        """
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
        """
        Create a new Sound object that is pitched up/down from the original by 'pitch_factor'.
        - pitch_factor > 1.0 => Higher pitch
        - pitch_factor < 1.0 => Lower pitch
        Returns the original sound if pitch-shifting results in an empty sample array.
        """
        if not original_sound:
            return None

        # Extract samples as a NumPy array
        sound_array = pygame.sndarray.array(original_sound)

        # Get the number of samples
        if sound_array.ndim == 1:
            # Mono
            num_samples = sound_array.shape[0]
        else:
            # Stereo or multi-channel
            num_samples = sound_array.shape[0]

        # Generate new sample indices based on pitch_factor
        new_indices = np.arange(0, num_samples, 1.0 / pitch_factor)
        new_indices = np.round(new_indices).astype(np.int32)

        # Clip indices so we don't go out of range
        new_indices = new_indices[new_indices < num_samples]

        # If all indices are out of range, fall back to original sound
        if len(new_indices) == 0:
            logging.warning(
                f"Pitch shift resulted in empty array (pitch_factor={pitch_factor}). "
                "Returning original sound."
            )
            return original_sound

        # Resample
        if sound_array.ndim == 1:
            # Mono
            pitched_array = sound_array[new_indices]
        else:
            # Multi-channel
            pitched_array = sound_array[new_indices, :]

        if pitched_array.size == 0:
            logging.warning(
                f"Pitch shift array is empty after indexing (pitch_factor={pitch_factor}). "
                "Returning original sound."
            )
            return original_sound

        new_sound = pygame.sndarray.make_sound(pitched_array)
        return new_sound
                    
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

# Define a silent version of AudioManager whose methods do nothing.
class SilentAudioManager:
    def play_above_ask_sound(self): pass
    def play_above_ask_sound_big(self): pass
    def play_buy_sound(self): pass
    def play_buy_sound_big(self): pass
    def play_between_bid_ask_sound_ask(self): pass
    def play_between_bid_ask_sound(self): pass
    def play_between_bid_ask_sound_bid(self): pass
    def play_sell_sound(self): pass
    def play_sell_sound_big(self): pass
    def play_below_bid_sound(self): pass
    def play_below_bid_sound_big(self): pass


class TradesProcessor:
    def __init__(self, api_key, trade_threshold, big_threshold, silent=False):
        self.api_key = api_key
        self.trade_threshold = trade_threshold
        self.big_threshold = big_threshold        
        # Use SilentAudioManager if silent mode is requested; otherwise use the regular AudioManager.
        self.audio_manager = SilentAudioManager() if silent else AudioManager()
        self.client = WebSocketClient(api_key=self.api_key)
        self.subscriptions = []
        # Store quotes in an instance dict rather than a global.
        self.latest_quotes = {}
        # Threading lock to prevent race conditions in handle_quote_message/handle_trade_message.
        self._lock = threading.Lock()

    def convert_timestamp(self, ts):
        """
        Convert a timestamp (assumed ms) to a formatted string.
        If ts is out of expected range, return 'Invalid timestamp'.
        Adjust if your data is in microseconds/nanoseconds.
        """
        logging.debug(f"Raw timestamp: {ts}")
        if ts and 1e12 <= ts < 2e13:
            dt_obj = datetime.fromtimestamp(ts / 1e3)
            return dt_obj.strftime('%Y-%m-%d %H:%M:%S')
        else:
            return "Invalid timestamp"

    def handle_quote_message(self, quote: EquityQuote):
        try:
            ticker = quote.symbol
            with self._lock:
                self.latest_quotes[ticker] = {
                    'ask': quote.ask_price,
                    'bid': quote.bid_price
                }

            formatted_time = self.convert_timestamp(quote.timestamp)
            logging.info(f"Quote {ticker} at {formatted_time}: "
                         f"Ask={quote.ask_price}, Bid={quote.bid_price}")
        except Exception as e:
            logging.error(f"Error handling quote message: {e}")

    def handle_trade_message(self, trade: EquityTrade):
        try:
            ticker = trade.symbol
            price = trade.price
            volume = trade.size
            amount = price * volume
            timestamp_str = self.convert_timestamp(trade.timestamp)

            # Skip small trades
            if amount < self.trade_threshold:
                logging.debug(f"Trade {ticker} at {timestamp_str} ignored (Amount: ${amount:.2f})")
                return

            with self._lock:
                quote = self.latest_quotes.get(ticker, {})
                ask = quote.get('ask')
                bid = quote.get('bid')

            # Decide if the trade is "big" for second threshold
            is_big_trade = (amount >= self.big_threshold)

            # -------------------------------
            # 1) If bid or ask is unknown, 
            #    treat as "between bid and ask".
            # -------------------------------
            if ask is None or bid is None:
                color = 'white'
                # Print the trade in white
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

            # Otherwise, we have a valid bid/ask
            # Safe float comparisons with EPSILON
            if abs(price - ask) < EPSILON:
                # Price is at ask
                color = 'green'
                sound_map = {
                    False: self.audio_manager.play_buy_sound,
                    True: self.audio_manager.play_buy_sound_big
                }
                sound_map[is_big_trade]()

            elif abs(price - bid) < EPSILON:
                # Price is at bid
                color = 'red'
                sound_map = {
                    False: self.audio_manager.play_sell_sound,
                    True: self.audio_manager.play_sell_sound_big
                }
                sound_map[is_big_trade]()

            elif price > (ask + EPSILON):
                # Price is above ask
                color = 'yellow'
                sound_map = {
                    False: self.audio_manager.play_above_ask_sound,
                    True: self.audio_manager.play_above_ask_sound_big
                }
                sound_map[is_big_trade]()

            elif price < (bid - EPSILON):
                # Price is below bid
                color = 'magenta'
                sound_map = {
                    False: self.audio_manager.play_below_bid_sound,
                    True: self.audio_manager.play_below_bid_sound_big
                }
                sound_map[is_big_trade]()

            else:
                # Price is between bid and ask
                distance_to_ask = abs(price - ask)
                distance_to_bid = abs(price - bid)
                color = 'white'

                # check if price is half-way between bid and ask
                if abs(distance_to_ask - distance_to_bid) < 1e-9:
                    self.audio_manager.play_between_bid_ask_sound()
                else:
                    # Closer to ask
                    if distance_to_ask < distance_to_bid:
                        self.audio_manager.play_between_bid_ask_sound_ask()
                    else:
                        # closer to bid
                        self.audio_manager.play_between_bid_ask_sound_bid()

            # Format and print
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

    def handle_message(self, msgs):
        try:
            for msg in msgs:
                if isinstance(msg, EquityTrade):
                    self.handle_trade_message(msg)
                elif isinstance(msg, EquityQuote):
                    self.handle_quote_message(msg)
                else:
                    logging.warning(f"Unexpected message format: {msg}")
        except Exception as e:
            logging.error(f"Error processing message: {e}")

    def subscribe_to_symbols(self, symbols):
        for symbol in symbols:
            self.client.subscribe(f'T.{symbol}')
            self.client.subscribe(f'Q.{symbol}')
            self.subscriptions.append(symbol)

    def run(self):
        """
        Continuously run the WebSocket client, retrying up to 3 consecutive times.
        On failure, sleeps for 10 seconds before retry. Resets retry count on success.
        """
        max_retries = 3
        delay = 10
        remaining_retries = max_retries

        while True:
            try:
                self.client.run(self.handle_message)
                logging.info("WebSocket client ended or disconnected gracefully.")
                remaining_retries = max_retries
            except KeyboardInterrupt:
                logging.info("KeyboardInterrupt detected. Shutting down gracefully.")
                break
            except Exception as e:
                remaining_retries -= 1
                if remaining_retries > 0:
                    logging.error(
                        f"WebSocket encountered an error: {e}. "
                        f"Retrying in {delay} seconds... (Remaining retries: {remaining_retries})"
                    )
                    time.sleep(delay)
                else:
                    logging.error(
                        f"WebSocket encountered an error: {e}. "
                        f"No more retries left. Shutting down gracefully."
                    )
                    break


def main():
    """
    Usage:
      python ticksonic.py [ticker] [threshold] [big_threshold] [--silent]

    If no arguments are given, defaults to ticker='TSLA', threshold=90000, and big_threshold=490000.
    Examples:
      python script.py TSLA 90000 490000
      python script.py TSLA 90000
      python script.py TSLA
      python script.py
      python script.py --silent
    """
    if len(sys.argv) > 4:
        print("Usage: python script.py [ticker] [threshold] [big_threshold]")
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

    processor = TradesProcessor(API_KEY, threshold, big_threshold, silent=silent)
    processor.subscribe_to_symbols([ticker])
    processor.run()


if __name__ == '__main__':
    main()
