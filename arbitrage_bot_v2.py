import ccxt
import time
import numpy as np

# =========================
# CONFIG
# =========================

API_KEY = "0986dfa480a2ffe13627f24de011fcc0"
API_SECRET = "89bf4a4ab66704d68c9bf40d9bb3448180545209434e49d769fafa9456b86834"

SYMBOL = "BTC/USDT"

START_BALANCE = 1000

FEE = 0.001
SLIPPAGE = 0.0005

MAX_DRAWDOWN = 0.1

balance = START_BALANCE
peak = START_BALANCE
position = None

prices = []
pnl_history = []

# =========================
# EXCHANGE
# =========================

exchange = ccxt.gateio({
    "apiKey": API_KEY,
    "secret": API_SECRET,
    "enableRateLimit": True,
    "options": {"defaultType": "spot"}
})

exchange.set_sandbox_mode(True)

# =========================
# DATA
# =========================

def price():
    return exchange.fetch_ticker(SYMBOL)["last"]

def book():
    ob = exchange.fetch_order_book(SYMBOL, limit=20)
    return ob["bids"], ob["asks"]

# =========================
# FEATURE LAYER
# =========================

def imbalance(bids, asks):
    b = sum([x[1] for x in bids])
    a = sum([x[1] for x in asks])
    return (b - a) / (b + a + 1e-9)

def momentum():
    if len(prices) < 5:
        return 0
    return prices[-1] - prices[-3]

def trend():
    if len(prices) < 20:
        return 0
    return np.mean(prices[-5:]) - np.mean(prices[-20:])

def volatility():
    if len(prices) < 20:
        return 0
    return np.std(prices[-20:])

# =========================
# MARKET REGIME (INSTITUTIONAL CORE)
# =========================

def regime():
    vol = volatility()
    mom = abs(momentum())

    if vol > 60:
        return "risk_off"
    if mom > 12:
        return "trend"
    return "mean_reversion"

# =========================
# STRATEGY PORTFOLIO (FUND STYLE)
# =========================

def strat_mean_reversion(bids, asks):
    return -momentum() * 0.6 + imbalance(bids, asks) * 0.4

def strat_trend(bids, asks):
    return trend() * 0.6 + momentum() * 0.4

def strat_microflow(bids, asks):
    return imbalance(bids, asks)

# =========================
# STRATEGY ROUTER (ALLOCATION ENGINE)
# =========================

def ensemble_signal(bids, asks, reg):
    if reg == "trend":
        return strat_trend(bids, asks)

    if reg == "mean_reversion":
        return strat_mean_reversion(bids, asks)

    return strat_microflow(bids, asks)

# =========================
# EXPECTED VALUE MODEL
# =========================

def expected_value(sig):
    vol = volatility()
    cost = FEE + SLIPPAGE
    return sig - cost - (vol * 0.01)

# =========================
# CAPITAL ALLOCATION (INSTITUTIONAL RISK)
# =========================

def position_size(p, ev):
    kelly = max(0.1, min(ev, 1))
    return (balance * 0.01) * kelly / p

# =========================
# RISK ENGINE (HEDGE FUND STYLE)
# =========================

def risk_check():
    global peak

    peak = max(peak, balance)
    dd = (peak - balance) / peak

    return dd < MAX_DRAWDOWN

# =========================
# EXECUTION LAYER
# =========================

def buy(p, amount):
    global position

    exec_price = p * (1 + SLIPPAGE)

    exchange.create_market_buy_order(SYMBOL, amount)

    position = {
        "entry": exec_price,
        "amount": amount,
        "time": time.time()
    }

    print("BUY", exec_price, amount)

def sell(p):
    global balance, position

    exec_price = p * (1 - SLIPPAGE)

    entry = position["entry"]
    amount = position["amount"]

    exchange.create_market_sell_order(SYMBOL, amount)

    pnl = (exec_price - entry) * amount
    pnl -= (entry + exec_price) * amount * FEE

    balance += pnl
    pnl_history.append(pnl)

    print("SELL", exec_price, "PNL:", pnl, "BAL:", balance)

    position = None

# =========================
# STRATEGY PERFORMANCE SCORING (FUND LOGIC)
# =========================

def strategy_health():
    if len(pnl_history) < 10:
        return 0

    pnl = np.array(pnl_history)
    return np.mean(pnl) / (np.std(pnl) + 1e-9)

# =========================
# LOOP
# =========================

print("INSTITUTIONAL ENGINE STARTED")

while True:
    try:
        p = price()
        bids, asks = book()

        prices.append(p)
        if len(prices) > 100:
            prices.pop(0)

        reg = regime()

        sig = ensemble_signal(bids, asks, reg)
        ev = expected_value(sig)

        # dynamic confidence adjustment (fund logic)
        perf = strategy_health()
        ev *= (1 + perf)

        # =========================
        # RISK FILTER
        # =========================

        if not risk_check():
            print("DRAWDOWN STOP")
            time.sleep(2)
            continue

        # =========================
        # ENTRY
        # =========================

        if position is None:
            if reg != "risk_off" and ev > 0.25:
                amt = position_size(p, ev)
                buy(p, amt)

        # =========================
        # EXIT
        # =========================

        else:
            hold = time.time() - position["time"]

            if ev < 0 or reg == "risk_off" or hold > 5:
                sell(p)

        print(
            "P:", p,
            "REG:", reg,
            "SIG:", round(sig, 4),
            "EV:", round(ev, 4),
            "BAL:", round(balance, 2)
        )

        time.sleep(1)

    except Exception as e:
        print("ERR:", e)
        time.sleep(2)
