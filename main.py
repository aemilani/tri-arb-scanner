import requests
import websocket
import json
import logging
import time
from src.utils import get_binance_fee


BASE_COIN = 'USDT'
INVESTMENT = 1_000  # Starting amount in BASE_COIN
FEE = get_binance_fee(vip_level=3, is_usdc=False, is_maker=False, using_bnb=True)
MIN_PROFIT_USD = 0.01  # Only log if profit is strictly greater than this amount

prices = {}
triangles = []
pair_to_triangles = {}

logging.basicConfig(
    filename='logs/arbitrage_logs.txt',
    level=logging.INFO,
    format='%(asctime)s | %(message)s'
)


def initialize_market_data():
    """Fetches Binance Exchange Info and builds all possible triangles."""
    print("Fetching exchange data from Binance...")
    url = 'https://api.binance.com/api/v3/exchangeInfo'

    try:
        data = requests.get(url).json()
    except Exception as e:
        print(f"Failed to fetch data: {e}")
        return False

    spot_symbols = [s for s in data['symbols'] if s['isSpotTradingAllowed']]

    # Find all coins that trade directly with BASE_COIN (Maps Coin -> Pair, e.g., 'ETH' -> 'ETHUSDT')
    base_pairs = {s['baseAsset']: s['symbol'] for s in spot_symbols if s['quoteAsset'] == BASE_COIN}

    global triangles, pair_to_triangles

    # Iterate through all spot pairs to find valid middle connections
    for s in spot_symbols:
        c1 = s['baseAsset']
        c2 = s['quoteAsset']

        # If BOTH coins in this pair trade with BASE_COIN, we have a valid closed triangle
        if c1 in base_pairs and c2 in base_pairs:
            p1 = base_pairs[c1]  # Base -> C1 (e.g., ETHUSDT)
            p2 = s['symbol']  # C1 <-> C2 (e.g., ETHBTC)
            p3 = base_pairs[c2]  # C2 -> Base (e.g., BTCUSDT)

            tri = {
                'base': BASE_COIN,
                'c1': c1,
                'c2': c2,
                'p1': p1,
                'p2': p2,
                'p3': p3
            }
            triangles.append(tri)

            # Map the pairs to the triangle for instant $O(1)$ websocket lookups
            for p in [p1, p2, p3]:
                if p not in pair_to_triangles:
                    pair_to_triangles[p] = []
                pair_to_triangles[p].append(tri)

    print(f"Initialization complete. Found {len(triangles)} possible {BASE_COIN} triangles.")
    return True


def log_and_print_arb(direction, path, rates, profit_usd, profit_pct):
    """Logs profitable arbs to the file and prints them in green to the console."""
    msg = (f"[{direction}] PATH: {path} | "
           f"RATES: {rates} | "
           f"PROFIT: ${profit_usd:.4f} ({profit_pct:.4f}%)")

    # \033[92m is the ANSI escape code for green text, \033[0m resets it
    print(f"\033[92m+++ ARB FOUND! +++\033[0m {msg}")
    logging.info(msg)


def check_arbitrage(triangle):
    """Calculates forward and reverse paths for a given triangle, factoring in fees."""
    p1, p2, p3 = triangle['p1'], triangle['p2'], triangle['p3']

    # Ensure our local memory has price data for all 3 legs of the triangle
    if p1 not in prices or p2 not in prices or p3 not in prices:
        return

    # -------------------------------------------------------------
    # PATH 1: FORWARD (e.g., USDT -> ETH -> BTC -> USDT)
    # -------------------------------------------------------------
    # Step 1: Buy C1 with BASE_COIN (Divide by Ask)
    rate1 = prices[p1]['ask']
    if rate1 == 0: return
    c1_acquired = (INVESTMENT / rate1) * (1 - FEE)

    # Step 2: Sell C1 for C2 (Multiply by Bid)
    rate2 = prices[p2]['bid']
    c2_acquired = (c1_acquired * rate2) * (1 - FEE)

    # Step 3: Sell C2 for BASE_COIN (Multiply by Bid)
    rate3 = prices[p3]['bid']
    usdt_final = (c2_acquired * rate3) * (1 - FEE)

    profit_usd = usdt_final - INVESTMENT

    if profit_usd > MIN_PROFIT_USD:
        profit_pct = (profit_usd / INVESTMENT) * 100
        path_str = f"{triangle['base']} -> {triangle['c1']} -> {triangle['c2']} -> {triangle['base']}"
        rates_str = f"{p1}:{rate1}, {p2}:{rate2}, {p3}:{rate3}"
        log_and_print_arb("FORWARD", path_str, rates_str, profit_usd, profit_pct)

    # -------------------------------------------------------------
    # PATH 2: REVERSE (e.g., USDT -> BTC -> ETH -> USDT)
    # -------------------------------------------------------------
    # Step 1: Buy C2 with BASE_COIN (Divide by Ask)
    r_rate1 = prices[p3]['ask']
    if r_rate1 == 0: return
    c2_acq_rev = (INVESTMENT / r_rate1) * (1 - FEE)

    # Step 2: Buy C1 with C2 (Divide by Ask of the middle pair)
    r_rate2 = prices[p2]['ask']
    if r_rate2 == 0: return
    c1_acq_rev = (c2_acq_rev / r_rate2) * (1 - FEE)

    # Step 3: Sell C1 for BASE_COIN (Multiply by Bid)
    r_rate3 = prices[p1]['bid']
    usdt_final_rev = (c1_acq_rev * r_rate3) * (1 - FEE)

    profit_usd_rev = usdt_final_rev - INVESTMENT

    if profit_usd_rev > MIN_PROFIT_USD:
        profit_pct_rev = (profit_usd_rev / INVESTMENT) * 100
        path_str = f"{triangle['base']} -> {triangle['c2']} -> {triangle['c1']} -> {triangle['base']}"
        rates_str = f"{p3}:{r_rate1}, {p2}:{r_rate2}, {p1}:{r_rate3}"
        log_and_print_arb("REVERSE", path_str, rates_str, profit_usd_rev, profit_pct_rev)


def on_message(_ws, message):
    data = json.loads(message)

    # Ensure it's a bookTicker payload
    symbol = data.get('s')
    if not symbol:
        return

    # Update local order book state
    prices[symbol] = {
        'bid': float(data['b']),
        'ask': float(data['a'])
    }

    # Instantly trigger math ONLY for the specific triangles affected by this tick
    if symbol in pair_to_triangles:
        for tri in pair_to_triangles[symbol]:
            check_arbitrage(tri)


def on_error(_ws, error):
    print(f"\n[WebSocket Error] {error}")


def on_close(_ws, _close_status_code, _close_msg):
    print("\n[WebSocket Closed] Connection to Binance lost.")


def on_open(_ws):
    print("[WebSocket Opened] Streaming real-time order books. Waiting for profitable arbs...\n")


if __name__ == "__main__":
    if initialize_market_data():
        # Connect to the All Book Tickers stream (!bookTicker)
        # This streams best bid/ask for EVERY symbol on Binance without needing to subscribe to individual pairs.
        socket_url = "wss://stream.binance.com:9443/ws/!bookTicker"

        wsocket = websocket.WebSocketApp(socket_url,
                                         on_open=on_open,
                                         on_message=on_message,
                                         on_error=on_error,
                                         on_close=on_close)

        # Run the websocket, automatically reconnecting if it drops
        while True:
            wsocket.run_forever()
            print("Reconnecting in 5 seconds...")
            time.sleep(5)
