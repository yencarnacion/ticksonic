Below is an example of how you might rewrite your Polygon‐based program to use the Interactive Brokers API via IB Gateway (using the popular “ib_insync” library). In this version the program connects to IB Gateway, subscribes to market data for a given stock (e.g. TSLA), and processes “trade‐like” updates by checking the last traded price, bid, and ask values. (Because IB’s market data “ticks” are not delivered exactly as separate “trade” and “quote” messages, we use the ticker’s fields to infer similar conditions.) 

Make sure you’ve installed ib_insync (via pip) and that your IB Gateway (or TWS) is running with API access enabled. You may also need to set environment variables (or modify the constants below) for IB connection settings and sound file paths.

Below is the complete code:

---

```python
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
from termcolor import colored

from dotenv import load_dotenv
from ib_insync import IB, Stock, util

# Load .env file if it exists
load_dotenv()

# Initialize Pygame mixer
try:
    pygame.mixer.init()
except Exception as e:
    logging.error(f"Could not initialize pygame mixer: {e}")
    sys.exit(1)

logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(message)s')

# Environment/default settings
DEFAULT_TICKER = "TSLA"
DEFAULT_THRESHOLD = 90000
BIG_THRESHOLD = 490000.0

# Path to sound files (set these in your .env or change the defaults)
BUY_SOUND_PATH = os.getenv('BUY_SOUND_PATH', 'sounds/buy.wav')
SELL_SOUND_PATH = os.getenv('SELL_SOUND_PATH', 'sounds/sell.wav')
ABOVE_ASK_SOUND_PATH = os.getenv('ABOVE_ASK_SOUND_PATH', 'sounds/above_ask.wav')
BELOW_BID_SOUND_PATH = os.getenv('BELOW_BID_SOUND_PATH', 'sounds/below_bid.wav')
BETWEEN_BID_ASK_SOUND_PATH = os.getenv('BETWEEN_BID_ASK_SOUND_PATH', 'sounds/between_bid_ask.wav')

# IB Gateway connection settings (set these via .env if desired)
IB_HOST = os.getenv('IB_HOST', '127.0.0.1')
IB_PORT = int(os.getenv('IB_PORT', '7497'))  # e.g. 7497 for paper trading
IB_CLIENT_ID = int(os.getenv('IB_CLIENT_ID', '1'))

EPSILON = 1e-3

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

        # Pre-generate pitched versions for “big” trades
        self.above_ask_sound_big = self.pitch_shift_sound(self.above_ask_sound, pitch_factor=1.5)
        self.buy_sound_big = self.pitch_shift_sound(self.buy_sound, pitch_factor=1.5)
        self.sell_sound_big = self.pitch_shift_sound(self.sell_sound, pitch_factor=0.8)
        self.below_bid_sound_big = self.pitch_shift_sound(self.below_bid_sound, pitch_factor=0.8)
        # Closer to bid or ask sounds for between bid/ask
        self.between_bid_ask_sound_ask = self.pitch_shift_sound(self.between_bid_ask_sound, pitch_factor=1.5)
        self.between_bid_ask_sound_bid = self.pitch_shift_sound(self.between_bid_ask_sound, pitch_factor=0.8)
        
    @staticmethod
    def pitch_shift_sound(original_sound: pygame.mixer.Sound, pitch_factor: float) -> pygame.mixer.Sound:
        if not original_sound:
            return None
        sound_array = pygame.sndarray.array(original_sound)
        if sound_array.ndim == 1:
            num_samples = sound_array.shape[0]
        else:
            num_samples = sound_array.shape[0]
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

class TradesProcessor:
    def __init__(self, trade_threshold, big_threshold):
        self.trade_threshold = trade_threshold
        self.big_threshold = big_threshold        
        self.audio_manager = AudioManager()
        self._lock = threading.Lock()
        # Connect to IB Gateway/TWS using ib_insync
        self.ib = IB()
        try:
            self.ib.connect(IB_HOST, IB_PORT, clientId=IB_CLIENT_ID)
            logging.info(f"Connected to IB Gateway at {IB_HOST}:{IB_PORT} with clientId {IB_CLIENT_ID}")
        except Exception as e:
            logging.error(f"Failed to connect to IB Gateway: {e}")
            sys.exit(1)
        # Dictionary to hold ticker objects per symbol
        self.tickers = {}

    def handle_tick(self, ticker):
        try:
            symbol = ticker.contract.symbol
            timestamp_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            price = ticker.last
            volume = ticker.lastSize

            # If no trade data, skip
            if price is None or volume is None or volume == 0:
                return

            amount = price * volume
            if amount < self.trade_threshold:
                logging.debug(f"Trade {symbol} at {timestamp_str} ignored (Amount: ${amount:.2f})")
                return

            bid = ticker.bid
            ask = ticker.ask
            is_big_trade = (amount >= self.big_threshold)

            if bid is None or ask is None:
                self.audio_manager.play_between_bid_ask_sound()
                formatted_amount = format_amount(amount)
                price_str = f"{price:,.2f}"
                on_color = 'on_grey' if is_big_trade else None
                attrs = ['bold'] if is_big_trade else []
                print(colored(
                    f"Price: {price_str} | Amount: ${formatted_amount} | Time: {timestamp_str} | Ticker: {symbol}",
                    color='white',
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
                f"Price: {price_str} | Amount: ${formatted_amount} | Time: {timestamp_str} | Ticker: {symbol}",
                color=color,
                on_color=on_color,
                attrs=attrs
            ))
        except Exception as e:
            logging.error(f"Error handling tick for {ticker.contract.symbol}: {e}")

    def subscribe_to_symbols(self, symbols):
        for symbol in symbols:
            contract = Stock(symbol, 'SMART', 'USD')
            # Request market data for the contract
            ticker = self.ib.reqMktData(contract, '', False, False)
            self.tickers[symbol] = ticker
            # Add our tick handler callback
            ticker.updateEvent += self.handle_tick

    def run(self):
        try:
            logging.info("Starting IB event loop.")
            self.ib.run()  # This will block and process events
        except KeyboardInterrupt:
            logging.info("KeyboardInterrupt detected. Disconnecting from IB Gateway.")
            self.ib.disconnect()
        except Exception as e:
            logging.error(f"Error in IB event loop: {e}")
            self.ib.disconnect()

def main():
    """
    Usage:
      python script.py [ticker] [threshold] [big_threshold]
    If no arguments are provided, defaults are used.
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

    processor = TradesProcessor(threshold, big_threshold)
    processor.subscribe_to_symbols([ticker])
    processor.run()

if __name__ == '__main__':
    main()
```

---

### Explanation

1. **IB Connection:**  
   We use `ib_insync.IB()` to connect to IB Gateway/TWS with the settings specified by the environment (or defaults).

2. **Market Data Subscription:**  
   In `subscribe_to_symbols()`, we create a Stock contract for the ticker, request market data (with `reqMktData`), and attach a callback (`handle_tick`) to process updates.

3. **Trade Logic:**  
   The callback `handle_tick()` examines the last traded price (and volume) along with the bid and ask values. It then determines whether to trigger a “buy,” “sell,” or “between bid/ask” sound based on price comparisons using a small epsilon.

4. **Sound Playback:**  
   The `AudioManager` class preloads sound files and provides methods to play normal or “big” versions of each sound (pitch-shifted).

5. **Execution:**  
   The `main()` function parses command‑line arguments and starts the IB event loop (via `ib.run()`).

This program mirrors the logic of your original Polygon version but is reworked to obtain and process live IB market data via the IB Gateway API.

Be sure to adjust any file paths or connection parameters as needed for your environment.