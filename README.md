# Binance Real-Time Triangular Arbitrage Scanner

A high-performance Python script that detects real-time triangular arbitrage opportunities on the Binance Spot market.
By leveraging Binance's WebSocket API for live order book (`bookTicker`) updates, this scanner calculates forward and
reverse arbitrage paths instantly, factoring in real-world trading fees.

### 1. Introduction

Given a stablecoin $S$ and crypto assets $C_1$ and $C_2$, the arbitrage path is:

$$S \rightarrow C_1 \rightarrow C_2 \rightarrow S$$

We have an arbitrage if:

$$\frac{S}{C_1}\cdot \frac{C_1}{C_2} \cdot \frac{C_2}{S} > 1$$

### 2. Mathematical Model & Execution Paths

To turn the theoretical relationship into an executable algorithmic trading strategy, the scanner maps the generic symbols to real order book dynamics. Because market orders cross the spread, we must evaluate the path using the specific **Bid** (selling to the market) and **Ask** (buying from the market) prices, while discounting the exchange fee $f$ at every leg.

Let $I$ be the initial `INVESTMENT` amount in the `BASE_COIN` ($S$).

#### Path A: Forward Arbitrage

The forward path flows as:


$$S \rightarrow C_1 \rightarrow C_2 \rightarrow S$$

1. **Step 1 ($S \rightarrow C_1$):** Buy asset $C_1$ using stablecoin $S$. This transaction executes at the market **Ask** price of the pair $P_1$ ($C_1/S$). The amount of $C_1$ acquired is:

$$A_{C_1} = \left(\frac{I}{\text{Ask}_{P_1}}\right) \cdot (1 - f)$$


2. **Step 2 ($C_1 \rightarrow C_2$):** Sell asset $C_1$ for asset $C_2$. This transaction executes at the market **Bid** price of the intermediate pair $P_2$ ($C_1/C_2$). The amount of $C_2$ acquired is:

$$A_{C_2} = \left(A_{C_1} \cdot \text{Bid}_{P_2}\right) \cdot (1 - f)$$


3. **Step 3 ($C_2 \rightarrow S$):** Sell asset $C_2$ back to stablecoin $S$. This transaction executes at the market **Bid** price of the pair $P_3$ ($C_2/S$).

$$I_{\text{final, Fwd}} = \left(A_{C_2} \cdot \text{Bid}_{P_3}\right) \cdot (1 - f)$$



The total net profit in $S$ is calculated as:


$$\text{Profit}_{\text{USD}} = I_{\text{final, Fwd}} - I$$

#### Path B: Reverse Arbitrage

The reverse path flows in the opposite direction:


$$S \rightarrow C_2 \rightarrow C_1 \rightarrow S$$

1. **Step 1 ($S \rightarrow C_2$):** Buy asset $C_2$ using stablecoin $S$. This transaction executes at the market **Ask** price of the pair $P_3$ ($C_2/S$).

$$A'_{C_2} = \left(\frac{I}{\text{Ask}_{P_3}}\right) \cdot (1 - f)$$


2. **Step 2 ($C_2 \rightarrow C_1$):** Buy asset $C_1$ using asset $C_2$. Since the pair $P_2$ is quoted as $C_1/C_2$, acquiring the base asset ($C_1$) requires buying at the market **Ask** price.

$$A'_{C_1} = \left(\frac{A'_{C_2}}{\text{Ask}_{P_2}}\right) \cdot (1 - f)$$


3. **Step 3 ($C_1 \rightarrow S$):** Sell asset $C_1$ back to stablecoin $S$. This transaction executes at the market **Bid** price of the pair $P_1$ ($C_1/S$).

$$I_{\text{final, Rev}} = \left(A'_{C_1} \cdot \text{Bid}_{P_1}\right) \cdot (1 - f)$$



The total net profit for the reverse sequence is:


$$\text{Profit}_{\text{USD, Rev}} = I_{\text{final, Rev}} - I$$

### 3. High-Performance Architecture

Triangular arbitrage requires ultra-low latency execution. To prevent overhead during runtime, the architecture splits operations into a heavy **Initialization Phase** and a lightweight **Streaming Phase**.

```
[Binance REST API] ──(Initialization)──> Build Triangles & O(1) Map
                                                    │
                                                    ▼
[Binance WebSocket] ──(Live Feed)──> Update Prices ──> Check Arbitrage (Instant Lookup)
```

#### $O(1)$ Complexity Matrix

Instead of looping over all possible combinations every time a price changes, the script maps tickers to their intersecting paths during boot-up using a hash table (`pair_to_triangles`).

* **Space Complexity:** $O(T)$ where $T$ is the total number of valid structural loops.
* **Time Complexity:** $O(1)$ lookups. When a single `bookTicker` stream updates (e.g., `ETHUSDC`), the script instantly targets and evaluates only the specific triangles containing that pair, ignoring the rest of the market.

#### WebSocket Optimization & Stream Management

Binance enforces strict protocol limits on active connections. The scanner circumvents limitations through the following engineering choices:

* **Targeted Subscriptions:** Rather than subscribing to a global, high-volume firehose stream like `!bookTicker` which pushes data for thousands of unneeded pairs, the scanner filters for the exact cross-pairs computed during initialization.
* **Message Chunking:** Subscriptions are batched into arrays of $100$ streams and throttled with a $0.5$-second delay to protect the client IP from being rate-limited during connection handshakes.
* **Stream Cap Safety:** The subscription list automatically caps at $1000$ tickers to safely remain within Binance's single-connection hard ceiling of $1024$ streams.

### 4. Logging & Console Outputs

When an opportunity satisfies the structural constraint ($\text{Profit}_{\text{USD}} > \text{MIN\_PROFIT\_USD}$), it is recorded immediately.

* **Console Output:** Output strings are written using ANSI escape sequences (`\033[92m`) to highlight profitable discoveries in green text for visual monitoring.
* **File Logging:** Thread-safe file writes copy entries directly into `logs/arbitrage_logs.txt` with formatted timestamps, capturing the exact routing sequence and localized transaction rates for subsequent historical backtesting analysis.