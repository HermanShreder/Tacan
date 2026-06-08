import ccxt
import pandas as pd
import numpy as np
import time
import websocket
import json
import threading
import telegram
from datetime import datetime
import requests
import csv
import os
from scipy.signal import argrelextrema

# =========================
# НАСТРОЙКИ СТРАТЕГИИ (СИМУЛЯТОР)
# =========================
SYMBOL = "BTC/USDT"
COMMISSION = 0.001
INITIAL_BALANCE = 500.0
RISK_PER_TRADE = 0.20            # 20% от текущего баланса на один ордер
MAX_POSITIONS = 5                # максимум открытых позиций
MAX_TOTAL_RISK = 0.7             # суммарная загрузка капитала не более 70%

RSI_PERIOD = 14
RSI_OVERSOLD = 35
RSI_OVERBOUGHT = 65
BB_PERIOD = 20
BB_STD = 2
EMA_SHORT = 20
EMA_LONG = 50
VOLUME_MA_PERIOD = 20
MIN_VOLUME_RATIO = 1.3
MIN_VOLUME_ABS = 50              # минимальный абсолютный объём (BTC) для ликвидности

ORDERBOOK_DEPTH = 20
CLUSTER_THRESHOLD = 3.0
MAX_PRICE_ABOVE_SUPPORT = 0.001  # 0.1% выше поддержки
ORDER_TIMEOUT = 120              # тайм-аут лимитного ордера 2 минуты

# Параметры тейк-профита (без стоп-лосса)
TAKE_PROFIT_ATR_MULT = 1.5
TAKE_PROFIT_MAX_PCT = 3.0

# Защита от волатильности
VOLATILITY_TIMEOUT_SEC = 300
VOLATILITY_THRESHOLD_PCT = 1.5
VOLATILITY_LOOKBACK_SEC = 60

# Дневные лимиты
DAILY_LOSS_LIMIT_PCT = 5.0        # при достижении просадки 5% за день – остановка
DAILY_PROFIT_TARGET_PCT = 3.0     # цель 3% в день – снижаем риск

# Новостной модуль
NEWS_API_KEY = "YOUR_CRYPTOPANIC_API_KEY"
NEWS_CHECK_INTERVAL = 60
NEWS_WORDLIST = ["BTC", "bitcoin", "ETF", "halving", "резкий рост", "принятие закона"]
NEWS_RISK_PCT = 0.3
NEWS_GRID_ORDERS = 5
NEWS_GRID_RANGE_PCT = 2.0

# Логирование
LOG_TRADES_CSV = "trades_log.csv"
LOG_EVENTS_TXT = "events_log.txt"

TELEGRAM_TOKEN = "5814224378:AAHlkQ41I-uQ9XXe_jmn5G28Q2x6nXCVNM8"
CHAT_ID = "5253808709"
API_KEY = "KCfiKalMMyNTy7kjDzTeLyd6LvnCnrkDgCQC4WfXmAqmihvPDTyCDs69Ib4O6HvQ"
API_SECRET = "oH2BdROQbwpL9YiXNAMITQLARAOx61rgT5WWZKKTLPaY1LyaIzcCUlewum8HA3UO"

exchange = ccxt.binance({
    "enableRateLimit": True,
    "apiKey": API_KEY,
    "secret": API_SECRET
})
bot = telegram.Bot(token=TELEGRAM_TOKEN)

# Глобальные переменные
balance = INITIAL_BALANCE
total_pnl = 0.0
positions = []              # каждая позиция: {'entry_price', 'amount', 'cost', 'take_profit', 'entry_time'}
pending_orders = []
trade_log = []
orderbook = {"bids": [], "asks": []}
support_levels = []         # {'price': float, 'strength': float, 'first_seen': float}
resistance_levels = []
last_orderbook_update = 0

volatility_pause_until = 0
last_price_time = 0
last_price = None
news_mode_active = False
news_orders = []
news_balance_reserved = 0.0
last_news_time = 0

peak_balance = INITIAL_BALANCE
max_drawdown = 0.0
trade_history = []
daily_start_balance = INITIAL_BALANCE
last_reset_day = datetime.now().day

# =========================
# ВЕБСОКЕТ
# =========================
def on_message(ws, msg):
    global orderbook
    try:
        data = json.loads(msg)
        orderbook["bids"] = data.get("bids", [])
        orderbook["asks"] = data.get("asks", [])
    except:
        pass

def start_websocket():
    ws = websocket.WebSocketApp(
        "wss://stream.binance.com:9443/ws/btcusdt@depth20@100ms",
        on_message=on_message
    )
    ws.run_forever()

threading.Thread(target=start_websocket, daemon=True).start()

# =========================
# ИНДИКАТОРЫ
# =========================
def get_indicators():
    ohlcv = exchange.fetch_ohlcv(SYMBOL, "5m", limit=200)
    df = pd.DataFrame(ohlcv, columns=["ts", "o", "h", "l", "c", "v"])
    df["ts"] = pd.to_datetime(df["ts"], unit='ms')
    delta = df["c"].diff()
    gain = delta.where(delta > 0, 0).rolling(RSI_PERIOD).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(RSI_PERIOD).mean()
    df["rsi"] = 100 - (100 / (1 + gain / loss))
    df["bb_mid"] = df["c"].rolling(BB_PERIOD).mean()
    bb_std = df["c"].rolling(BB_PERIOD).std()
    df["bb_upper"] = df["bb_mid"] + BB_STD * bb_std
    df["bb_lower"] = df["bb_mid"] - BB_STD * bb_std
    df["ema_short"] = df["c"].ewm(span=EMA_SHORT, adjust=False).mean()
    df["ema_long"] = df["c"].ewm(span=EMA_LONG, adjust=False).mean()
    df["volume_ma"] = df["v"].rolling(VOLUME_MA_PERIOD).mean()
    tr = np.maximum(df["h"] - df["l"], 
                    np.maximum(abs(df["h"] - df["c"].shift()), 
                               abs(df["l"] - df["c"].shift())))
    df["atr"] = tr.rolling(14).mean()
    return df.dropna()

# =========================
# ДИНАМИЧЕСКИЕ УРОВНИ ИЗ ОРДЕРБУКА (С ОЦЕНКОЙ СИЛЫ)
# =========================
def detect_clusters_with_strength(orderbook_side):
    """Возвращает список словарей с ценой, силой и временем первого появления"""
    if not orderbook_side:
        return []
    levels = [(float(p), float(v)) for p, v in orderbook_side[:ORDERBOOK_DEPTH]]
    if len(levels) < 3:
        return []
    clusters = []
    avg_vol = sum(v for _, v in levels) / len(levels)
    for i, (price, vol) in enumerate(levels):
        left_vol = levels[i-1][1] if i > 0 else vol
        right_vol = levels[i+1][1] if i < len(levels)-1 else vol
        local_avg = (left_vol + right_vol) / 2
        if vol > local_avg * CLUSTER_THRESHOLD and vol > avg_vol * 1.5:
            strength = min(vol / (avg_vol * 1.5), 2.0)
            clusters.append({
                'price': price,
                'strength': strength,
                'first_seen': time.time(),
                'current_vol': vol
            })
    return clusters

def update_support_resistance_dynamic():
    global support_levels, resistance_levels, last_orderbook_update
    if not orderbook["bids"] or not orderbook["asks"]:
        return
    new_supports = detect_clusters_with_strength(orderbook["bids"])
    new_resists = detect_clusters_with_strength(orderbook["asks"])
    
    for old in support_levels[:]:
        if not any(abs(n['price'] - old['price']) < 5 for n in new_supports):
            support_levels.remove(old)
    for ns in new_supports:
        existing = next((s for s in support_levels if abs(s['price'] - ns['price']) < 5), None)
        if existing:
            existing['strength'] = max(existing['strength'], ns['strength'])
            existing['current_vol'] = ns['current_vol']
            existing['first_seen'] = min(existing['first_seen'], ns['first_seen'])
        else:
            support_levels.append(ns)
    
    for old in resistance_levels[:]:
        if not any(abs(n['price'] - old['price']) < 5 for n in new_resists):
            resistance_levels.remove(old)
    for nr in new_resists:
        existing = next((s for s in resistance_levels if abs(s['price'] - nr['price']) < 5), None)
        if existing:
            existing['strength'] = max(existing['strength'], nr['strength'])
            existing['current_vol'] = nr['current_vol']
            existing['first_seen'] = min(existing['first_seen'], nr['first_seen'])
        else:
            resistance_levels.append(nr)
    
    last_orderbook_update = time.time()

def find_best_support(current_price):
    candidates = [s for s in support_levels if s['price'] < current_price]
    if not candidates:
        return None
    best = min(candidates, key=lambda x: (current_price - x['price']) / (x['strength'] + 0.1))
    return best

def find_best_resistance(current_price):
    candidates = [r for r in resistance_levels if r['price'] > current_price]
    if not candidates:
        return None
    best = min(candidates, key=lambda x: (x['price'] - current_price) / (x['strength'] + 0.1))
    return best

# =========================
# ДИНАМИЧЕСКИЕ УРОВНИ ИЗ ЦЕНЫ (локальные экстремумы)
# =========================
def find_local_extrema(df, order=10):
    high_points = argrelextrema(df['c'].values, np.greater, order=order)[0]
    low_points = argrelextrema(df['c'].values, np.less, order=order)[0]
    support_prices = [df['c'].iloc[i] for i in low_points]
    resistance_prices = [df['c'].iloc[i] for i in high_points]
    support_prices = sorted(set(support_prices))
    resistance_prices = sorted(set(resistance_prices))
    return support_prices, resistance_prices

def merge_levels_with_price_extrema():
    global support_levels, resistance_levels
    df = get_indicators()
    price_supports, price_resists = find_local_extrema(df, order=8)
    for ps in price_supports:
        if not any(abs(ps - s['price']) < 10 for s in support_levels):
            support_levels.append({'price': ps, 'strength': 0.8, 'first_seen': time.time(), 'current_vol': 0})
    for pr in price_resists:
        if not any(abs(pr - r['price']) < 10 for r in resistance_levels):
            resistance_levels.append({'price': pr, 'strength': 0.8, 'first_seen': time.time(), 'current_vol': 0})

# =========================
# ЛОГИРОВАНИЕ И СТАТИСТИКА
# =========================
def update_drawdown(current_balance):
    global peak_balance, max_drawdown
    if current_balance > peak_balance:
        peak_balance = current_balance
    dd = (peak_balance - current_balance) / peak_balance * 100
    if dd > max_drawdown:
        max_drawdown = dd
    return dd

def log_trade(entry_price, exit_price, pnl, pnl_pct, reason):
    global trade_history
    trade = {
        'timestamp': datetime.now().isoformat(),
        'entry_price': entry_price,
        'exit_price': exit_price,
        'pnl_usdt': pnl,
        'pnl_pct': pnl_pct,
        'reason': reason
    }
    trade_history.append(trade)
    file_exists = os.path.isfile(LOG_TRADES_CSV)
    with open(LOG_TRADES_CSV, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=trade.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(trade)
    with open(LOG_EVENTS_TXT, 'a', encoding='utf-8') as f:
        f.write(f"{datetime.now()} | СДЕЛКА: вход {entry_price} выход {exit_price} PnL {pnl:.2f} ({pnl_pct:.2f}%) - {reason}\n")

def log_event(message):
    with open(LOG_EVENTS_TXT, 'a', encoding='utf-8') as f:
        f.write(f"{datetime.now()} | {message}\n")
    print(message)

def compute_statistics():
    if len(trade_history) == 0:
        return
    pnl_pcts = [t['pnl_pct'] for t in trade_history]
    wins = [p for p in pnl_pcts if p > 0]
    losses = [p for p in pnl_pcts if p < 0]
    winrate = len(wins)/len(pnl_pcts)*100 if pnl_pcts else 0
    avg_win = np.mean(wins) if wins else 0
    avg_loss = np.mean(losses) if losses else 0
    total_return = (balance - INITIAL_BALANCE) / INITIAL_BALANCE * 100
    stats = f"""
    ========== СТАТИСТИКА СТРАТЕГИИ ==========
    Всего сделок: {len(trade_history)}
    Винрейт: {winrate:.2f}%
    Средняя прибыль: {avg_win:.2f}%
    Средний убыток: {avg_loss:.2f}%
    Максимальная просадка: {max_drawdown:.2f}%
    Общий PnL: {total_pnl:.2f} USDT
    Общая доходность: {total_return:.2f}%
    Текущий баланс: {balance:.2f} USDT
    ==========================================
    """
    with open("statistics.txt", "w", encoding='utf-8') as f:
        f.write(stats)
    print(stats)
    bot.send_message(CHAT_ID, stats)

# =========================
# ДНЕВНЫЕ ЛИМИТЫ
# =========================
def check_daily_limits():
    global daily_start_balance, last_reset_day, RISK_PER_TRADE
    today = datetime.now().day
    if today != last_reset_day:
        daily_start_balance = balance
        last_reset_day = today
        log_event(f"📅 Новый день. Стартовый баланс: {balance:.2f} USDT")
        return True
    daily_pnl = balance - daily_start_balance
    daily_pnl_pct = (daily_pnl / daily_start_balance) * 100
    if daily_pnl_pct <= -DAILY_LOSS_LIMIT_PCT:
        log_event(f"❌ Дневной убыток {daily_pnl_pct:.2f}% превысил лимит {DAILY_LOSS_LIMIT_PCT}%. Остановка.")
        cancel_all_orders()
        return False
    if daily_pnl_pct >= DAILY_PROFIT_TARGET_PCT:
        new_risk = RISK_PER_TRADE * 0.5
        if new_risk != RISK_PER_TRADE:
            log_event(f"✅ Цель {DAILY_PROFIT_TARGET_PCT}% достигнута. Снижаем риск {RISK_PER_TRADE*100:.0f}% → {new_risk*100:.0f}%")
            RISK_PER_TRADE = new_risk
    return True

# =========================
# ЗАЩИТА ОТ ВОЛАТИЛЬНОСТИ
# =========================
def check_volatility_timeout(current_price):
    global volatility_pause_until, last_price, last_price_time
    now = time.time()
    if last_price is not None and last_price_time is not None:
        delta_pct = abs(current_price - last_price) / last_price * 100
        time_diff = now - last_price_time
        if time_diff <= VOLATILITY_LOOKBACK_SEC and delta_pct >= VOLATILITY_THRESHOLD_PCT:
            volatility_pause_until = now + VOLATILITY_TIMEOUT_SEC
            log_event(f"⚠️ Резкое движение {delta_pct:.2f}% за {time_diff:.0f} сек. Пауза {VOLATILITY_TIMEOUT_SEC} сек.")
            cancel_all_orders()
            return True
    last_price = current_price
    last_price_time = now
    return False

def is_volatility_paused():
    return time.time() < volatility_pause_until

# =========================
# НОВОСТНОЙ МОДУЛЬ (БЕЗ СТОП-ЛОССА)
# =========================
def fetch_news():
    url = f"https://cryptopanic.com/api/v1/posts/?auth_token={NEWS_API_KEY}&currencies=BTC&kind=news"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return r.json().get('results', [])
    except:
        pass
    return []

def contains_keywords(text):
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in NEWS_WORDLIST)

def check_for_important_news():
    global news_mode_active, last_news_time, news_orders, news_balance_reserved
    now = time.time()
    if now - last_news_time < NEWS_CHECK_INTERVAL:
        return
    last_news_time = now
    if news_mode_active:
        return
    news_list = fetch_news()
    for article in news_list:
        title = article.get('title', '')
        if contains_keywords(title):
            log_event(f"🔔 ВАЖНАЯ НОВОСТЬ: {title}")
            activate_news_grid()
            break

def activate_news_grid():
    global news_mode_active, news_orders, news_balance_reserved, balance, pending_orders
    if news_mode_active:
        return
    reserved = balance * NEWS_RISK_PCT
    if reserved < 50:
        log_event("Недостаточно средств для новостной сетки (минимум 50 USDT)")
        return
    news_balance_reserved = reserved
    cancel_all_pending_orders()
    ticker = exchange.fetch_ticker(SYMBOL)
    current_price = ticker['last']
    step = (current_price * NEWS_GRID_RANGE_PCT / 100) * 2 / NEWS_GRID_ORDERS
    start_price = current_price * (1 - NEWS_GRID_RANGE_PCT/100)
    news_orders = []
    amount_per_order = reserved / NEWS_GRID_ORDERS
    for i in range(NEWS_GRID_ORDERS):
        price = start_price + i * step
        amount_btc = amount_per_order / price
        news_orders.append({
            'price': price,
            'side': 'buy',
            'amount_btc': amount_btc,
            'amount_usdt': amount_per_order,
            'placed_at': time.time()
        })
    news_mode_active = True
    log_event(f"📰 Новостная сетка: {NEWS_GRID_ORDERS} ордеров, диапазон {start_price:.2f}–{price:.2f}, резерв {reserved:.2f} USDT")
    bot.send_message(CHAT_ID, f"📰 Новостная сетка активирована!")

def check_news_grid_orders(current_price):
    global news_mode_active, news_orders, positions, balance
    if not news_mode_active:
        return
    executed = []
    for order in news_orders:
        if current_price <= order['price']:
            if any(pos['entry_price'] == order['price'] for pos in positions):
                log_event(f"⚠️ Новостной ордер {order['price']:.2f} уже исполнен")
                executed.append(order)
                continue
            cost = order['amount_usdt'] * (1 + COMMISSION)
            if cost > balance:
                log_event(f"❌ Недостаточно средств для новостной покупки {order['price']:.2f}")
                executed.append(order)
                continue
            balance -= cost
            take_profit = calculate_take_profit(order['price'], None)
            positions.append({
                "entry_price": order['price'],
                "entry_time": datetime.now(),
                "amount": order['amount_btc'],
                "cost": cost,
                "take_profit": take_profit
            })
            log_event(f"🟢 НОВОСТНАЯ ПОКУПКА по {order['price']:.2f}, {order['amount_btc']:.5f} BTC, TP {take_profit:.2f}")
            bot.send_message(CHAT_ID, f"🟢 Новостная покупка {order['price']:.2f}")
            executed.append(order)
            break
    for o in executed:
        news_orders.remove(o)
    if len(news_orders) == 0 or len(positions) >= MAX_POSITIONS:
        news_mode_active = False
        news_balance_reserved = 0
        log_event("Новостная сетка завершена")
        bot.send_message(CHAT_ID, "Новостная сетка завершена")

def cancel_news_grid():
    global news_mode_active, news_orders, balance, news_balance_reserved
    if news_mode_active:
        news_orders = []
        news_mode_active = False
        news_balance_reserved = 0
        log_event("Новостная сетка отменена")

# =========================
# ДИНАМИЧЕСКИЙ ТЕЙК-ПРОФИТ (БЕЗ СТОП-ЛОССА)
# =========================
def find_nearest_resistance_above(price):
    best = find_best_resistance(price)
    return best['price'] if best else None

def calculate_take_profit(entry_price, atr):
    resist = find_nearest_resistance_above(entry_price)
    if resist:
        tp = resist * (1 - 0.0005)
        max_tp = entry_price * (1 + TAKE_PROFIT_MAX_PCT / 100)
        if tp > max_tp:
            tp = max_tp
        min_tp = entry_price * (1 + 2*COMMISSION + 0.002)
        if tp < min_tp:
            tp = min_tp
        return tp
    else:
        if atr is not None:
            tp = entry_price + atr * TAKE_PROFIT_ATR_MULT
        else:
            tp = entry_price * (1 + TAKE_PROFIT_MAX_PCT / 100)
        max_tp = entry_price * (1 + TAKE_PROFIT_MAX_PCT / 100)
        if tp > max_tp:
            tp = max_tp
        return tp

# =========================
# УПРАВЛЕНИЕ ПОЗИЦИЯМИ И ОРДЕРАМИ (БЕЗ СТОПОВ)
# =========================
def close_position(pos, exit_price, reason):
    global balance, total_pnl
    revenue = exit_price * pos['amount']
    commission_sell = revenue * COMMISSION
    net_revenue = revenue - commission_sell
    pnl = net_revenue - pos['cost']
    balance += pnl
    total_pnl += pnl
    pnl_pct = (pnl / pos['cost']) * 100
    log_trade(pos['entry_price'], exit_price, pnl, pnl_pct, reason)
    update_drawdown(balance)
    msg = (f"\n🔒 ЗАКРЫТА ПОЗИЦИЯ [{reason}]\n"
           f"   Вход {pos['entry_price']:.2f} → Выход {exit_price:.2f}\n"
           f"   PnL: {pnl:.2f} USDT ({pnl_pct:.2f}%)\n"
           f"   Баланс: {balance:.2f} USDT | Общий PnL: {total_pnl:.2f}")
    trade_log.append(msg)
    print(msg)
    bot.send_message(CHAT_ID, msg)
    log_event(msg)

def add_pending_order(price, current_balance, current_price, atr):
    global pending_orders
    if len(pending_orders) + len(positions) >= MAX_POSITIONS:
        return False
    if any(abs(o['price'] - price) < 0.5 for o in pending_orders):
        log_event(f"⚠️ Ордер на {price:.2f} уже существует, дубликат пропущен")
        return False
    total_allocated = sum(p['cost'] for p in positions) + sum(o['amount_usdt'] for o in pending_orders)
    if total_allocated / current_balance > MAX_TOTAL_RISK:
        log_event(f"⚠️ Лимит загрузки капитала {MAX_TOTAL_RISK*100:.0f}%")
        return False
    pos_size = current_balance * RISK_PER_TRADE
    if pos_size < 10:
        return False
    amount_btc = pos_size / price
    amount_usdt = pos_size
    if current_price > price * (1 + MAX_PRICE_ABOVE_SUPPORT):
        return False
    pending_orders.append({
        'price': price,
        'side': 'buy',
        'amount_btc': amount_btc,
        'amount_usdt': amount_usdt,
        'placed_at': time.time(),
        'atr': atr
    })
    return True

def check_pending_orders(current_price):
    global pending_orders, balance, positions
    if not pending_orders:
        return
    executed = []
    for i, order in enumerate(pending_orders):
        if is_volatility_paused():
            cancel_all_pending_orders()
            log_event("Отмена всех ордеров из-за волатильности")
            break
        if time.time() - order['placed_at'] > ORDER_TIMEOUT:
            executed.append(i)
            continue
        if order['side'] == 'buy' and current_price <= order['price']:
            already_has = any(pos['entry_price'] == order['price'] for pos in positions)
            if already_has:
                log_event(f"⚠️ Ордер {order['price']:.2f} уже исполнен, пропускаем")
                executed.append(i)
                continue
            exec_price = order['price']
            amount = order['amount_btc']
            cost = order['amount_usdt'] * (1 + COMMISSION)
            if cost > balance:
                log_event(f"❌ Недостаточно средств для {exec_price:.2f}")
                executed.append(i)
                continue
            balance -= cost
            take_profit = calculate_take_profit(exec_price, order['atr'])
            positions.append({
                "entry_price": exec_price,
                "entry_time": datetime.now(),
                "amount": amount,
                "cost": cost,
                "take_profit": take_profit
            })
            msg = f"🟢 ПОКУПКА по {exec_price:.2f}, {amount:.5f} BTC, TP {take_profit:.2f}"
            trade_log.append(msg)
            print(msg)
            bot.send_message(CHAT_ID, msg)
            log_event(msg)
            executed.append(i)
    for i in sorted(executed, reverse=True):
        pending_orders.pop(i)

def cancel_all_pending_orders():
    global pending_orders
    pending_orders = []

def cancel_all_orders():
    cancel_all_pending_orders()
    cancel_news_grid()

# =========================
# СИГНАЛ НА ПОКУПКУ
# =========================
def evaluate_buy_signal(current_price, df, best_support):
    last = df.iloc[-1]
    rsi = last['rsi']
    price = last['c']
    bb_lower = last['bb_lower']
    volume = last['v']
    volume_ma = last['volume_ma']
    ema_short = last['ema_short']
    ema_long = last['ema_long']
    
    if rsi > 55:
        return False, f"RSI={rsi:.1f} > 55"
    if volume < MIN_VOLUME_ABS:
        return False, f"Объём {volume:.0f} < {MIN_VOLUME_ABS}"
    
    rsi_ok = rsi < RSI_OVERSOLD
    near_lower = abs(price - bb_lower) / bb_lower < 0.005
    volume_ok = volume > volume_ma * MIN_VOLUME_RATIO
    trend_up = ema_short > ema_long
    cnt = sum([rsi_ok, near_lower, volume_ok, trend_up])
    if cnt >= 2 and best_support:
        if current_price > best_support['price'] * (1 + MAX_PRICE_ABOVE_SUPPORT):
            return False, f"Цена далеко от поддержки {best_support['price']:.2f}"
        if best_support['strength'] < 1.2:
            return False, f"Поддержка слабая (сила {best_support['strength']:.2f})"
        reason = f"Индикаторы {cnt}/4 + поддержка {best_support['price']:.2f} (сила {best_support['strength']:.2f})"
        return True, reason
    return False, f"Индикаторов {cnt}/4"

# =========================
# ОСНОВНОЙ ЦИКЛ
# =========================
def main():
    global volatility_pause_until, last_price, last_price_time, RISK_PER_TRADE
    print("🚀 СИМУЛЯТОР (БЕЗ СТОП-ЛОССОВ, ТОЛЬКО ТЕЙК-ПРОФИТ) ЗАПУЩЕН")
    bot.send_message(CHAT_ID, "🚀 Запущен симулятор: только покупки по индикаторам+поддержкам, тейк-профит, без стоп-лоссов")
    time.sleep(2)
    update_support_resistance_dynamic()
    merge_levels_with_price_extrema()
    last_merge_time = time.time()
    
    while True:
        try:
            df = get_indicators()
            current_price = df["c"].iloc[-1]
            last = df.iloc[-1]
            
            if not check_daily_limits():
                time.sleep(60)
                continue
            
            check_volatility_timeout(current_price)
            if is_volatility_paused():
                time.sleep(30)
                continue
            
            check_for_important_news()
            if news_mode_active:
                check_news_grid_orders(current_price)
            
            if time.time() - last_orderbook_update > 5:
                update_support_resistance_dynamic()
                if time.time() - last_merge_time > 1800:
                    merge_levels_with_price_extrema()
                    last_merge_time = time.time()
                # Корректируем тейк-профиты открытых позиций
                for pos in positions:
                    old_tp = pos['take_profit']
                    new_tp = calculate_take_profit(pos['entry_price'], None)
                    if abs(new_tp - old_tp) > 5:
                        pos['take_profit'] = new_tp
                        log_event(f"🔄 TP для {pos['entry_price']:.2f}: {old_tp:.2f} → {new_tp:.2f}")
            
            check_pending_orders(current_price)
            
            # Закрытие по тейк-профиту или перекупленности
            for pos in positions[:]:
                if current_price >= pos['take_profit']:
                    close_position(pos, current_price, "Тейк-профит")
                    positions.remove(pos)
                else:
                    rsi = last['rsi']
                    bb_upper = last['bb_upper']
                    if rsi > RSI_OVERBOUGHT and current_price > bb_upper:
                        close_position(pos, current_price, "RSI перекуплен + верхняя полоса")
                        positions.remove(pos)
            
            # Новые ордера
            if len(positions) + len(pending_orders) < MAX_POSITIONS and not news_mode_active:
                best_support = find_best_support(current_price)
                ok, reason = evaluate_buy_signal(current_price, df, best_support)
                if ok:
                    atr = last['atr']
                    if add_pending_order(best_support['price'], balance, current_price, atr):
                        msg = f"📝 Новый ордер на {best_support['price']:.2f} | {reason}"
                        print(msg)
                        bot.send_message(CHAT_ID, msg)
                        log_event(msg)
            
            update_drawdown(balance)
            print(f"\n{'='*80}")
            print(f"🕒 {datetime.now().strftime('%H:%M:%S')} | Цена BTC: {current_price:.2f} USDT")
            print(f"📊 RSI={last['rsi']:.1f} | BB низ={last['bb_lower']:.0f} верх={last['bb_upper']:.0f}")
            print(f"📦 Объём={last['v']:.0f} | Средний={last['volume_ma']:.0f}")
            if support_levels:
                best = find_best_support(current_price)
                if best:
                    print(f"🛡️ Лучшая поддержка: {best['price']:.2f} (сила {best['strength']:.2f})")
            if resistance_levels:
                best_r = find_best_resistance(current_price)
                if best_r:
                    print(f"⚔️ Лучшее сопротивление: {best_r['price']:.2f} (сила {best_r['strength']:.2f})")
            print(f"💰 Баланс: {balance:.2f} USDT | PnL: {total_pnl:.2f} | Просадка: {max_drawdown:.2f}%")
            print(f"📊 Позиций: {len(positions)} | Отложенных ордеров: {len(pending_orders)}")
            if positions:
                print("📌 Открытые позиции:")
                for i, p in enumerate(positions):
                    print(f"   {i+1}. Вход {p['entry_price']:.2f}, TP {p['take_profit']:.2f}, размер {p['amount']:.5f} BTC")
            if pending_orders:
                print(f"⏳ Ордера на покупку: {[round(o['price'],2) for o in pending_orders]}")
            if news_mode_active:
                print(f"📰 Новостная сетка: {len(news_orders)} ордеров")
            print(f"{'='*80}")
            
            if int(time.time()) % 120 < 30:
                compute_statistics()
            
            time.sleep(30)
            
        except Exception as e:
            error_msg = f"❌ Ошибка: {e}"
            print(error_msg)
            bot.send_message(CHAT_ID, error_msg)
            log_event(error_msg)
            time.sleep(30)

if __name__ == "__main__":
    main()
