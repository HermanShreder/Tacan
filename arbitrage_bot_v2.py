import requests
import time
from collections import deque

# =========================
# CONFIG
# =========================

SYMBOL = "BTCUSDT"

START_BALANCE = 1000

MAKER_FEE = 0.0002   # 0.02%
TAKER_FEE = 0.001    # 0.1%

SLIPPAGE = 0.0003

balance = START_BALANCE

position = None
orders = []

prices = deque(maxlen=100)

# =========================
# REAL MARKET DATA
# =========================

def get_price():
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={SYMBOL}"
    return float(requests.get(url).json()["price"])

def get_orderbook():
    url = f"https://api.binance.com/api/v3/depth?symbol={SYMBOL}&limit=10"
    data = requests.get(url).json()

    bids = [(float(p), float(q)) for p, q in data["bids"]]
    asks = [(float(p), float(q)) for p, q in data["asks"]]

    return bids, asks

# =========================
# STRATEGY (simple edge)
# =========================

def signal():
    if len(prices) < 10:
        return 0

    return prices[-1] - prices[-5]

# =========================
# ORDER SIZE
# =========================

def size(price):
    return (balance * 0.01) / price

# =========================
# MARKET IMPACT SIMULATION
# =========================

def market_buy(bids, asks, amount):
    cost = 0
    remaining = amount

    for price, qty in asks:
        if remaining <= 0:
            break

        fill = min(qty, remaining)
        cost += fill * price
        remaining -= fill

    avg_price = cost / amount if amount > 0 else 0
    return avg_price * (1 + SLIPPAGE)

def market_sell(bids, asks, amount):
    revenue = 0
    remaining = amount

    for price, qty in bids:
        if remaining <= 0:
            break

        fill = min(qty, remaining)
        revenue += fill * price
        remaining -= fill

    avg_price = revenue / amount if amount > 0 else 0
    return avg_price * (1 - SLIPPAGE)

# =========================
# EXECUTION
# =========================

def open_long(price, bids, asks):
    global position, balance

    amount = size(price)
    exec_price = market_buy(bids, asks, amount)

    cost = exec_price * amount
    fee = cost * TAKER_FEE

    balance -= (cost + fee)

    position = {
        "entry": exec_price,
        "amount": amount
    }

    print("BUY @", exec_price, "amt:", amount)

def close_long(price, bids, asks):
    global position, balance

    amount = position["amount"]

    exec_price = market_sell(bids, asks, amount)

    revenue = exec_price * amount
    fee = revenue * TAKER_FEE

    pnl = revenue - fee - (position["entry"] * amount)

    balance += pnl

    print("SELL @", exec_price, "PNL:", pnl, "BAL:", balance)

    position = None

# =========================
# LOOP
# =========================

print("PRO SIMULATOR STARTED")

while True:
    try:
        price = get_price()
        bids, asks = get_orderbook()

        prices.append(price)

        sig = signal()

        print("PRICE:", price, "SIG:", sig, "BAL:", round(balance, 2))

        # ENTRY
        if position is None and sig > 3:
            open_long(price, bids, asks)

        # EXIT
        elif position is not None and sig < 0:
            close_long(price, bids, asks)

        time.sleep(1)

    except Exception as e:
        print("ERR:", e)
        time.sleep(2)
