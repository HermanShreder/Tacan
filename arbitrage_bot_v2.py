import ccxt
import pandas as pd
import numpy as np
import time
import websocket
import json
import threading
import telegram

from sklearn.ensemble import RandomForestClassifier

# =========================
# CONFIG (ОБНОВЛЕНО)
# =========================

TELEGRAM_TOKEN = "5814224378:AAHlkQ41I-uQ9XXe_jmn5G28Q2x6nXCVNM8"
CHAT_ID = "5253808709"

# API ключи Binance (только для чтения)
API_KEY = "KCfiKalMMyNTy7kjDzTeLyd6LvnCnrkDgCQC4WfXmAqmihvPDTyCDs69Ib4O6HvQ"
API_SECRET = "oH2BdROQbwpL9YiXNAMITQLARAOx61rgT5WWZKKTLPaY1LyaIzcCUlewum8HA3UO"

exchange = ccxt.binance({
    "enableRateLimit": True,
    "apiKey": API_KEY,
    "secret": API_SECRET,
})

bot = telegram.Bot(token=TELEGRAM_TOKEN)

SYMBOL = "BTC/USDT"

# =========================
# WS ORDERBOOK
# =========================

orderbook = {"bids": [], "asks": []}

def on_message(ws, msg):
    global orderbook
    data = json.loads(msg)
    orderbook["bids"] = data.get("bids", [])
    orderbook["asks"] = data.get("asks", [])

def start_ws():
    ws = websocket.WebSocketApp(
        "wss://stream.binance.com:9443/ws/btcusdt@depth20@100ms",
        on_message=on_message
    )
    ws.run_forever()

threading.Thread(target=start_ws, daemon=True).start()

# =========================
# DATA
# =========================

def get_df(tf):
    df = pd.DataFrame(
        exchange.fetch_ohlcv(SYMBOL, tf, limit=300),
        columns=["t","o","h","l","c","v"]
    )
    return df

# =========================
# FEATURES (ML INPUT)
# =========================

def make_features(df):
    df["ret"] = df["c"].pct_change()
    df["vol"] = df["v"]

    df["atr"] = (df["h"] - df["l"]).rolling(14).mean()
    df["ema20"] = df["c"].ewm(span=20).mean()
    df["ema100"] = df["c"].ewm(span=100).mean()

    df["trend"] = df["ema20"] - df["ema100"]

    df["volatility"] = df["atr"] / df["c"]

    df = df.dropna()

    X = df[["ret", "vol", "trend", "volatility"]]
    return X, df

# =========================
# LABELS (RULE BASED TRAINING)
# =========================

def label_market(df):
    labels = []
    for i in range(len(df)):
        if abs(df["trend"].iloc[i]) < df["c"].iloc[i] * 0.002:
            labels.append(0)  # FLAT
        elif df["trend"].iloc[i] > 0:
            labels.append(1)  # UP
        else:
            labels.append(2)  # DOWN
    return np.array(labels[:len(df)])

# =========================
# TRAIN MODEL
# =========================

def train_model():
    df = get_df("15m")
    X, df = make_features(df)
    y = label_market(df)
    X = X.iloc[:len(y)]
    model = RandomForestClassifier(n_estimators=100, max_depth=6, random_state=42)
    model.fit(X, y)
    return model

model = train_model()

# =========================
# ORDER FLOW
# =========================

def imbalance():
    bids = orderbook["bids"]
    asks = orderbook["asks"]
    if not bids or not asks:
        return 0.5
    b = sum(float(x[1]) for x in bids[:20])
    a = sum(float(x[1]) for x in asks[:20])
    return b / (b + a + 1e-9)

# =========================
# GRID BACKTEST ENGINE
# =========================

def simulate_grid(df, low, high, n=20):
    step = (high-low)/n
    pnl = 0
    pos = []
    price = df["c"].values
    balance = 460
    for p in price:
        for i in range(n):
            level = low + i*step
            if p <= level and level not in pos:
                pos.append(level)
            if p >= level and level in pos:
                pnl += (p-level)/level * (balance/n)
                pos.remove(level)
    return pnl

# =========================
# OPTIMIZER (FUND CORE)
# =========================

def optimize_grid(df):
    price = df["c"].iloc[-1]
    atr = (df["h"]-df["l"]).rolling(14).mean().iloc[-1]
    best = {"pnl": -999}
    for mult in [2,3,4]:
        low = price - atr*mult
        high = price + atr*mult
        pnl = simulate_grid(df, low, high)
        if pnl > best["pnl"]:
            best = {"pnl": pnl, "low": low, "high": high, "mult": mult}
    return best

# =========================
# STRATEGY DECISION (AI CORE)
# =========================

def predict_state(df):
    X, df = make_features(df)
    last = X.iloc[-1:]
    pred = model.predict(last)[0]
    return ["FLAT","UP","DOWN"][pred]

# =========================
# TELEGRAM
# =========================

def send(msg):
    try:
        bot.send_message(CHAT_ID, msg)
    except Exception as e:
        print("Telegram error:", e)

# =========================
# LOOP
# =========================

last = 0

while True:
    df = get_df("15m")
    state = predict_state(df)
    opt = optimize_grid(df)
    imb = imbalance()

    report = f"""
AI FUND BOT

State: {state}
OrderFlow: {imb:.2f}

BEST GRID:
Low: {opt['low']:.2f}
High: {opt['high']:.2f}
Mult: {opt['mult']}
SimPnL: ${opt['pnl']:.2f}
"""
    print(report)
    send(report)
    time.sleep(60)
