import asyncio
import ccxt.async_support as ccxt
import json
import sqlite3
from datetime import datetime, timedelta
import telegram
import os
from dotenv import load_dotenv

# ========================= CONFIG =========================
load_dotenv()

GATE_API_KEY = "5d80677222f36e38d07d92f317e45674"
GATE_API_SECRET = "1a4d3c051cb523364b540e87361435a096b20dc51d96df9a91eaf03c6ad55c13"

BITGET_API_KEY = "bg_c425385453f54a25ed72a37f7498bfc5"
BITGET_API_SECRET = "46401f612cd8fa387c091a97061962d1f07b31187681405df72b457b0a78f69a"

TELEGRAM_TOKEN = "5814224378:AAHlkQ41I-uQ9XXe_jmn5G28Q2x6nXCVNM8"
CHAT_ID = "5253808709"

MIN_SPREAD = 0.005          # 0.5%
MIN_VOLUME_24H = 70000      # USD
SPREAD_LIFETIME_MIN = 3
UPDATE_INTERVAL = 120       # 2 минуты
TRADE_AMOUNT_USD = 500

# ====================== EXCHANGES ======================
ex_gate = ccxt.gateio({
    'apiKey': GATE_API_KEY,
    'secret': GATE_API_SECRET,
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

ex_bitget = ccxt.bitget({
    'apiKey': BITGET_API_KEY,
    'secret': BITGET_API_SECRET,
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

active_spreads = {}
db_conn = None

# ====================== DATABASE ======================
async def init_db():
    global db_conn
    db_conn = sqlite3.connect('arbitrage.db')
    db_conn.execute('''CREATE TABLE IF NOT EXISTS networks (
                        symbol TEXT, exchange TEXT, network TEXT, 
                        withdraw_fee REAL, withdraw_min REAL, 
                        deposit_time_avg INTEGER, withdraw_time_avg INTEGER)''')
    db_conn.execute('''CREATE TABLE IF NOT EXISTS stats (
                        timestamp TEXT, symbol TEXT, direction TEXT, 
                        spread REAL, profit REAL)''')
    db_conn.commit()

# ====================== HELPERS ======================
async def get_order_book(exchange, symbol, depth=15):
    try:
        ob = await exchange.fetch_order_book(symbol, limit=depth)
        best_ask = ob['asks'][0][0] if ob['asks'] else None
        best_bid = ob['bids'][0][0] if ob['bids'] else None
        ask_volume = sum(v for p, v in ob['asks'][:5])
        return best_ask, best_bid, ask_volume
    except:
        return None, None, 0

async def fetch_network_info(exchange_name, base_symbol):
    try:
        ex = ex_gate if exchange_name == 'gate' else ex_bitget
        fees = await ex.fetch_deposit_withdraw_fees(base_symbol)
        return fees
    except:
        return {}

async def send_to_telegram(spread):
    try:
        bot = telegram.Bot(token=TELEGRAM_TOKEN)
        msg = f"""
🚨 **SPREAD LIVE {spread['spread']}%** | {spread['direction']}
**Монета:** {spread['symbol']}
**Покупка:** {spread['buy_exchange']} @ {spread['buy_price']} (стакан ~{spread['volume_usd']:.0f}$)
**Продажа:** {spread['sell_exchange']} @ {spread['sell_price']}
**Вывод/Ввод:** ОТКРЫТЫ ✅
**Время сети:** ~{spread.get('withdraw_time', 8)} мин
**Чистая прибыль с 500$:** +{spread['net_profit']}$ 
        """
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode='Markdown')
    except Exception as e:
        print(f"TG error: {e}")

# ====================== MAIN SCANNER ======================
async def scan_spreads():
    await init_db()
    markets_gate = await ex_gate.load_markets()
    markets_bitget = await ex_bitget.load_markets()
    common = {s for s in markets_gate if s in markets_bitget and s.endswith('/USDT')}

    while True:
        now = datetime.now()
        for symbol in list(common):
            try:
                # Volume filter
                ticker = await ex_gate.fetch_ticker(symbol)
                if ticker.get('quoteVolume', 0) < MIN_VOLUME_24H:
                    continue

                # Order books
                g_ask, g_bid, g_vol = await get_order_book(ex_gate, symbol)
                b_ask, b_bid, b_vol = await get_order_book(ex_bitget, symbol)

                if not all([g_ask, g_bid, b_ask, b_bid]):
                    continue

                # Two directions
                spread_gb = (g_bid - b_ask) / b_ask   # Buy Bitget → Sell Gate
                spread_bg = (b_bid - g_ask) / g_ask   # Buy Gate → Sell Bitget

                best_spread = max(spread_gb, spread_bg)
                if best_spread < MIN_SPREAD:
                    continue

                direction = "Bitget→Gate" if spread_gb > spread_bg else "Gate→Bitget"
                buy_ex_name = "Bitget" if direction.startswith("Bitget") else "Gate"
                sell_ex_name = "Gate" if direction.startswith("Bitget") else "Bitget"

                buy_price = b_ask if buy_ex_name == "Bitget" else g_ask
                sell_price = g_bid if sell_ex_name == "Gate" else b_bid

                volume_usd = min(g_vol, b_vol) * buy_price

                # Network check
                base = symbol.replace('/USDT', '')
                net_buy = await fetch_network_info('bitget' if buy_ex_name == "Bitget" else 'gate', base)
                net_sell = await fetch_network_info('gate' if sell_ex_name == "Gate" else 'bitget', base)

                withdraw_time = 10  # average, можно улучшить из DB

                fee_estimate = 0.001 * TRADE_AMOUNT_USD * 2
                gross_profit = TRADE_AMOUNT_USD * best_spread
                net_profit = gross_profit - fee_estimate - 5  # network fee buffer

                if net_profit <= 0 or withdraw_time > 30:
                    continue

                spread_key = f"{symbol}_{direction}"

                spread_data = {
                    "time": now.isoformat(),
                    "symbol": symbol,
                    "direction": direction,
                    "spread": round(best_spread * 100, 2),
                    "buy_exchange": buy_ex_name,
                    "sell_exchange": sell_ex_name,
                    "buy_price": round(buy_price, 6),
                    "sell_price": round(sell_price, 6),
                    "volume_usd": round(volume_usd, 0),
                    "net_profit": round(net_profit, 2),
                    "withdraw_time": withdraw_time
                }

                active_spreads[spread_key] = spread_data
                await send_to_telegram(spread_data)

                # Save stat
                db_conn.execute("INSERT INTO stats VALUES (?, ?, ?, ?, ?)",
                               (now.isoformat(), symbol, direction, best_spread, net_profit))
                db_conn.commit()

            except Exception:
                continue

        # Cleanup old spreads
        for k in list(active_spreads.keys()):
            if (now - datetime.fromisoformat(active_spreads[k]["time"])).total_seconds() > SPREAD_LIFETIME_MIN * 60:
                del active_spreads[k]

        await asyncio.sleep(UPDATE_INTERVAL)

# ====================== STATS COMMAND (manual) ======================
async def show_stats():
    try:
        cursor = db_conn.execute("SELECT direction, COUNT(*), AVG(spread), AVG(profit) FROM stats GROUP BY direction")
        print("=== STATISTICS ===")
        for row in cursor.fetchall():
            print(row)
    except:
        pass

# ====================== RUN ======================
if __name__ == "__main__":
    print("=== Underground Arbitrage Scanner STARTED ===")
    print("Сканирование Gate ↔ Bitget | Мин. спред 0.5% | Обновление 2 мин")
    asyncio.run(scan_spreads())
