import requests
import pandas as pd
import logging
import time
from datetime import datetime, timedelta, UTC
from src.utils import get_binance_fee


BASE_COIN = 'USDT'
INVESTMENT = 1_000  # Starting amount in BASE_COIN
FEE = get_binance_fee(vip_level=3, is_usdc=False, is_maker=False, using_bnb=True)
MIN_PROFIT_USD = 0.01  # Only log if profit is strictly greater than this amount

prices = {}
kline_cache = {}  # Prevents redundant API calls and IP bans

logging.basicConfig(
    filename='logs/historical_arbitrage_logs.txt',
    level=logging.INFO,
    format='%(message)s'
)


def get_all_triangles():
    """Fetches Binance Exchange Info and builds all possible triangles."""
    print("Fetching exchange data from Binance...")
    url = 'https://api.binance.com/api/v3/exchangeInfo'

    try:
        data = requests.get(url).json()
    except Exception as e:
        print(f"Failed to fetch exchange info: {e}")
        return []

    # Filter for active spot pairs
    spot_symbols = [s for s in data['symbols'] if s['isSpotTradingAllowed'] and s['status'] == 'TRADING']

    # Find all coins that trade directly with USDT
    usdt_pairs = {s['baseAsset']: s['symbol'] for s in spot_symbols if s['quoteAsset'] == BASE_COIN}

    triangles = []

    for s in spot_symbols:
        c1 = s['baseAsset']
        c2 = s['quoteAsset']

        if c1 in usdt_pairs and c2 in usdt_pairs:
            triangles.append({
                'base': BASE_COIN,
                'c1': c1,
                'c2': c2,
                'p1': usdt_pairs[c1],  # Base -> C1
                'p2': s['symbol'],  # C1 <-> C2
                'p3': usdt_pairs[c2]  # C2 -> Base
            })

    print(f"Initialization complete. Found {len(triangles)} possible {BASE_COIN} triangles.")
    return triangles


def log_and_print_arb(timestamp, direction, path, rates, profit_usd, profit_pct):
    """Logs individual profitable arbs with their historical timestamp."""
    msg = (f"[{timestamp}] [{direction}] PATH: {path} | "
           f"RATES: {rates} | "
           f"PROFIT: ${profit_usd:.4f} ({profit_pct:.4f}%)")

    print(f"\033[92m+++ ARB FOUND! +++\033[0m {msg}")
    logging.info(msg)


def check_arbitrage(triangle, timestamp):
    """Calculates forward and reverse paths. Returns profit and transaction count."""
    p1, p2, p3 = triangle['p1'], triangle['p2'], triangle['p3']
    minute_profit = 0.0
    minute_txs = 0

    if p1 not in prices or p2 not in prices or p3 not in prices:
        return minute_profit, minute_txs

    # -------------------------------------------------------------
    # PATH 1: FORWARD (e.g., USDT -> ETH -> BTC -> USDT)
    # -------------------------------------------------------------
    rate1 = prices[p1]['ask']
    if rate1 > 0:
        c1_acquired = (INVESTMENT / rate1) * (1 - FEE)
        rate2 = prices[p2]['bid']
        c2_acquired = (c1_acquired * rate2) * (1 - FEE)
        rate3 = prices[p3]['bid']
        usdt_final = (c2_acquired * rate3) * (1 - FEE)

        profit_usd = usdt_final - INVESTMENT

        if profit_usd > MIN_PROFIT_USD:
            profit_pct = (profit_usd / INVESTMENT) * 100
            path_str = f"{triangle['base']} -> {triangle['c1']} -> {triangle['c2']} -> {triangle['base']}"
            rates_str = f"{p1}:{rate1:.4f}, {p2}:{rate2:.6f}, {p3}:{rate3:.4f}"
            log_and_print_arb(timestamp, "FORWARD", path_str, rates_str, profit_usd, profit_pct)

            minute_profit += profit_usd
            minute_txs += 1

    # -------------------------------------------------------------
    # PATH 2: REVERSE (e.g., USDT -> BTC -> ETH -> USDT)
    # -------------------------------------------------------------
    r_rate1 = prices[p3]['ask']
    if r_rate1 > 0:
        c2_acq_rev = (INVESTMENT / r_rate1) * (1 - FEE)
        r_rate2 = prices[p2]['ask']
        if r_rate2 > 0:
            c1_acq_rev = (c2_acq_rev / r_rate2) * (1 - FEE)
            r_rate3 = prices[p1]['bid']
            usdt_final_rev = (c1_acq_rev * r_rate3) * (1 - FEE)

            profit_usd_rev = usdt_final_rev - INVESTMENT

            if profit_usd_rev > MIN_PROFIT_USD:
                profit_pct_rev = (profit_usd_rev / INVESTMENT) * 100
                path_str = f"{triangle['base']} -> {triangle['c2']} -> {triangle['c1']} -> {triangle['base']}"
                rates_str = f"{p3}:{r_rate1:.4f}, {p2}:{r_rate2:.6f}, {p1}:{r_rate3:.4f}"
                log_and_print_arb(timestamp, "REVERSE", path_str, rates_str, profit_usd_rev, profit_pct_rev)

                minute_profit += profit_usd_rev
                minute_txs += 1

    return minute_profit, minute_txs


def get_cached_klines(symbol, start_time, end_time, interval="1m"):
    """Fetches klines from cache if available, otherwise downloads from Binance."""
    if symbol in kline_cache:
        return kline_cache[symbol]

    print(f"  > Downloading data for {symbol}...")
    url = 'https://api.binance.com/api/v3/klines'
    params = {
        'symbol': symbol,
        'interval': interval,
        'startTime': int(start_time.timestamp() * 1000),
        'endTime': int(end_time.timestamp() * 1000),
        'limit': 1000
    }

    try:
        response = requests.get(url, params=params)
        data = response.json()

        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time',
                                         'quote_asset_volume', 'trades', 'taker_buy_base', 'taker_buy_quote', 'ignore'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = df[['timestamp', 'close']]
        df.set_index('timestamp', inplace=True)
        df['close'] = df['close'].astype(float)
        df.rename(columns={'close': symbol}, inplace=True)

        # Save to cache to prevent pulling this pair again
        kline_cache[symbol] = df

        # Respect Binance API rate limits
        time.sleep(0.1)

        return df
    except Exception as e:
        print(f"Error fetching data for {symbol}: {e}")
        return pd.DataFrame()


def run_backtest_for_triangle(triangle, start_time, end_time):
    """Aligns historical data for 3 pairs, simulates arbitrage, and tallies profit."""
    global prices

    print(f"\n--- Testing {triangle['base']} -> {triangle['c1']} -> {triangle['c2']} ---")

    df_p1 = get_cached_klines(triangle['p1'], start_time, end_time)
    df_p2 = get_cached_klines(triangle['p2'], start_time, end_time)
    df_p3 = get_cached_klines(triangle['p3'], start_time, end_time)

    combined_df = pd.concat([df_p1, df_p2, df_p3], axis=1).dropna()

    if combined_df.empty:
        print("  > No overlapping data found. Skipping.")
        return

    triangle_total_profit = 0.0
    triangle_total_txs = 0

    for timestamp, row in combined_df.iterrows():
        prices[triangle['p1']] = {'bid': row[triangle['p1']], 'ask': row[triangle['p1']]}
        prices[triangle['p2']] = {'bid': row[triangle['p2']], 'ask': row[triangle['p2']]}
        prices[triangle['p3']] = {'bid': row[triangle['p3']], 'ask': row[triangle['p3']]}

        profit, txs = check_arbitrage(triangle, timestamp)

        triangle_total_profit += profit
        triangle_total_txs += txs

    # Report Total Summary for this Triangle
    summary_msg = (f"=== SUMMARY: {triangle['c1']}/{triangle['c2']} | "
                   f"Trades Executed: {triangle_total_txs} | "
                   f"Total Profit: ${triangle_total_profit:.4f} ===\n")
    print(summary_msg)

    # Log the summary to the file as well
    if triangle_total_txs > 0:
        logging.info(summary_msg)

    return triangle_total_profit


if __name__ == "__main__":
    hours_to_test = 12
    kline_end_time = datetime.now(UTC)
    kline_start_time = kline_end_time - timedelta(hours=hours_to_test)

    print(f"Global Backtest Period: {kline_start_time} to {kline_end_time} (UTC)")

    all_triangles = get_all_triangles()

    total_profit = 0
    for idx, tri in enumerate(all_triangles):
        print(f"\n[Progress: {idx + 1}/{len(all_triangles)}]")
        profit = run_backtest_for_triangle(tri, kline_start_time, kline_end_time)
        total_profit += profit
    print("\nGlobal backtest complete. All results saved to logs/historical_arbitrage_logs.txt")
    print(f"Total profit: {total_profit}")
