# Binance Real-Time Triangular Arbitrage Scanner

A high-performance Python script that detects real-time triangular arbitrage opportunities on the Binance Spot market. By leveraging Binance's WebSocket API for live order book (`bookTicker`) updates, this scanner calculates forward and reverse arbitrage paths instantly, factoring in real-world trading fees and order book bid/ask spreads.

---

## 1. Introduction & Theoretical Foundation

Given a stablecoin base asset $S$ and two intermediary crypto cryptocurrency assets $C_1$ and $C_2$, a classic triangular arbitrage path takes the form:

$$S \rightarrow C_1 \rightarrow C_2 \rightarrow S$$

Theoretically, a gross risk-free profit exists if the product of the cross-exchange exchange rates is strictly greater than 1:

$$\frac{S}{C_1}\cdot \frac{C_1}{C_2} \cdot \frac{C_2}{S} > 1$$

In live production environments, this expression must expand to account for order book spreads (crossing the bid-ask matrix) and operational fees deducted by the matching engine at each execution hop.

## Features

* **Real-Time Data Streaming:** Uses WebSockets to listen to live best bid/ask prices (`bookTicker`) rather than relying on slow REST API polling.
* **$O(1)$ Lookup Optimization:** Pre-calculates all valid triangle paths during initialization and maps them directly to specific trading pairs for instant execution when a price updates.
* **Targeted Subscriptions:** Bypasses WebSocket bloat by only subscribing to the specific pairs needed to form closed triangles with the chosen base coin, automatically chunking requests to respect Binance's API limits.
* **Bi-Directional Checking:** Evaluates both **Forward** (e.g., USDC -> ETH -> BTC -> USDC) and **Reverse** (e.g., USDC -> BTC -> ETH -> USDC) paths simultaneously.
* **Accurate Fee Calculation:** Integrates with a custom utility to factor in the specific Binance VIP level, Maker/Taker status, and BNB fee discounts to ensure logged profits are mathematically viable.

---

## 2. Mathematical Model & Execution Paths

Let $I$ be the initial `INVESTMENT` amount in the `BASE_COIN` ($S$), and let $f$ represent the trading fee percentage (expressed as a decimal fraction). Because market orders cross the order book spread, transactions are processed uniquely depending on path directionality.

### Path A: Forward Arbitrage

The forward path flows sequentially as:


$$S \rightarrow C_1 \rightarrow C_2 \rightarrow S$$

1. **Step 1 ($S \rightarrow C_1$):** Buy asset $C_1$ using stablecoin $S$. This transaction executes at the market **Ask** price of the pair $P_1$ ($C_1/S$). The net amount of $C_1$ acquired after fees is:

    $$A_{C_1} = \left(\frac{I}{\text{Ask}_{P_1}}\right) \cdot (1 - f)$$

2. **Step 2 ($C_1 \rightarrow C_2$):** Sell asset $C_1$ for asset $C_2$. This transaction executes at the market **Bid** price of the intermediate cross-pair $P_2$ ($C_1/C_2$). The net amount of $C_2$ acquired is:

    $$A_{C_2} = \left(A_{C_1} \cdot \text{Bid}_{P_2}\right) \cdot (1 - f)$$

3. **Step 3 ($C_2 \rightarrow S$):** Sell asset $C_2$ back to stablecoin $S$. This transaction executes at the market **Bid** price of the pair $P_3$ ($C_2/S$). The final amount of $S$ returned is:

    $$I_{\text{final, Fwd}} = \left(A_{C_2} \cdot \text{Bid}_{P_3}\right) \cdot (1 - f)$$

The total net profit in $S$ is calculated as:

$$\text{Profit}_{\text{USD, Fwd}} = I_{\text{final, Fwd}} - I$$

### Path B: Reverse Arbitrage

The reverse path flows in the opposite direction:


$$S \rightarrow C_2 \rightarrow C_1 \rightarrow S$$

1. **Step 1 ($S \rightarrow C_2$):** Buy asset $C_2$ using stablecoin $S$. This transaction executes at the market **Ask** price of the pair $P_3$ ($C_2/S$).

    $$A'_{C_2} = \left(\frac{I}{\text{Ask}_{P_3}}\right) \cdot (1 - f)$$

2. **Step 2 ($C_2 \rightarrow C_1$):** Buy asset $C_1$ using asset $C_2$. Since the pair $P_2$ is structurally quoted as $C_1/C_2$, acquiring the base asset ($C_1$) using the quote asset ($C_2$) requires buying at the market **Ask** price:

    $$A'_{C_1} = \left(\frac{A'_{C_2}}{\text{Ask}_{P_2}}\right) \cdot (1 - f)$$

3. **Step 3 ($C_1 \rightarrow S$):** Sell asset $C_1$ back to stablecoin $S$. This transaction executes at the market **Bid** price of the pair $P_1$ ($C_1/S$).

    $$I_{\text{final, Rev}} = \left(A'_{C_1} \cdot \text{Bid}_{P_1}\right) \cdot (1 - f)$$

The total net profit for the reverse sequence is:

$$\text{Profit}_{\text{USD, Rev}} = I_{\text{final, Rev}} - I$$

---

## 3. High-Performance Architecture

Triangular arbitrage requires ultra-low latency execution. To prevent overhead during runtime, the architecture splits operations into a heavy, computationally decoupled **Initialization Phase** and a lightweight, event-driven **Streaming Phase**.

```
[Binance REST API] ──(Initialization)──> Build Triangles & O(1) Map
                                                    │
                                                    ▼
[Binance WebSocket] ──(Live Feed)──> Update Prices ──> Check Arbitrage (Instant Lookup)
```

### $O(1)$ Complexity Matrix

Instead of looping over all possible market combinations every time a singular price vector moves, the script maps tickers to their intersecting paths during boot-up using a hash table (`pair_to_triangles`).

* **Space Complexity:** $O(T)$ where $T$ is the total number of valid structural loops identified.
* **Time Complexity:** $O(1)$ lookups. When a single `bookTicker` stream updates (e.g., `ETHUSDC`), the runtime engine targets and evaluates only the specific triangles containing that pair, ignoring the rest of the market.

### WebSocket Optimization & Stream Management

Binance enforces strict protocol limits on active connection nodes. The scanner circumvents limitations through the following engineering choices:

* **Targeted Subscriptions:** Rather than subscribing to a global, high-volume firehose stream like `!bookTicker` which pushes data for thousands of unneeded pairs, the scanner filters for the exact cross-pairs computed during initialization.
* **Message Chunking:** Subscriptions are batched into arrays of $100$ streams and throttled with a $0.5$-second delay to protect the client IP from being rate-limited during connection handshakes.
* **Stream Cap Safety:** The subscription list automatically caps at $1000$ tickers to safely remain within Binance's single-connection hard ceiling of $1024$ streams.

---

## 4. Prerequisites

* **Python:** Version 3.7 or higher.
* **Libraries:** `requests`, `websocket-client` (Note: ensure you install `websocket-client`, not `websocket`).

---

## 5. Configuration

You can adjust the bot's behavior by modifying the global variables at the top of the main Python file.

| Variable | Default Value | Description                                                      |
| --- | --- |------------------------------------------------------------------|
| **`BASE_COIN`** | `'USDC'` | The starting and ending asset for your triangular paths.         |
| **`INVESTMENT`** | `1_000` | The simulated starting balance used to calculate total profit.   |
| **`MIN_PROFIT_USD`** | `0.01` | The minimum strict dollar profit required to log an opportunity. |
| **`FEE`** | `get_binance_fee(...)` | The specific trading fee rate, fetched via the utility function. |

---

## 6. Project Structure & Setup

The scanner is designed to be "plug-and-play."

**1. Install Dependencies:** Ensure you have the core networking libraries installed:

```bash
pip install requests websocket-client
```

**2. Run the Scanner:** Fire up the engine from your terminal:

```bash
python main.py
```

### How It Works

1. **Initialization (`initialize_market_data`):** The script queries the Binance Exchange Info API to find all actively trading Spot pairs. It filters for pairs containing your `BASE_COIN` and systematically builds a list of closed 3-step loops (triangles).
2. **Environment Check:** Before connecting to the stream, the script ensures a `/logs` directory exists to prevent any I/O errors during high-frequency events.
3. **Connection (`on_open`):** It chunks relevant pairs into batches of 100 and subscribes to their live order book updates.
4. **Evaluation (`check_arbitrage`):** Every time a pair's best bid or ask price changes, the script looks up every triangle containing that pair and simulates a trade. It accounts for the bid/ask spread and subtracts the specific `FEE` at each of the three steps.
5. **Logging:** Profitable hits are printed in green to your console and appended to `logs/arbitrage_logs.txt`.

---

## 7. Disclaimer & Limitations

* **Execution Not Included:** This is a **scanner**, not an execution bot. It only identifies and logs opportunities. Executing these trades requires adding API keys, managing asynchronous orders, and handling partial fills.
* **Latency & Slippage:** In live markets, arbitrage opportunities often disappear in milliseconds. By the time this script calculates a profitable path via WebSockets, high-frequency trading firms co-located with Binance servers may have already consumed the liquidity.
* **Volume Limitations:** The script currently checks the *best* bid/ask prices but does not check order book *depth*. If an arbitrage path shows a $\$5$ profit but only has $\$10$ of liquidity at that specific price, a $\$1,000$ market order will incur heavy slippage, resulting in a loss.
* **Not Financial Advice:** Use this software for educational and research purposes only. Trade at your own risk.
