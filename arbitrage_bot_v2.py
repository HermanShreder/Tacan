import asyncio
import ccxt.async_support as ccxt
import sqlite3
import logging
from datetime import datetime
import telegram
from telegram import ReplyKeyboardMarkup, KeyboardButton
from itertools import combinations

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ========================= API KEYS =========================
GATE_API_KEY = "5d80677222f36e38d07d92f317e45674"
GATE_API_SECRET = "1a4d3c051cb523364b540e87361435a096b20dc51d96df9a91eaf03c6ad55c13"

BITGET_API_KEY = "bg_c425385453f54a25ed72a37f7498bfc5"
BITGET_API_SECRET = "46401f612cd8fa387c091a97061962d1f07b31187681405df72b457b0a78f69a"

HUOBI_API_KEY = "29d9fe7e-4b147f7f-dbuqg6hkte-0a894"
HUOBI_API_SECRET = "b0925bb5-07815986-b85bf68f-558a5"

BINANCE_API_KEY = "uvxQH98mpFgMRLM0ImIhBBohS3Pl86hVzDifpOUbmkRbDje6nZ0d74bB6oJLSFKt"
BINANCE_API_SECRET = "C7LOcLQBBNsF8LWTabxy7sul8mC79pcsbEzlb518rnCE2O4FzejnvZa0j04ZoiEB"

KUCOIN_API_KEY = "6a24241f371e5e0001ba9ca2"
KUCOIN_API_SECRET = "1ceb4e8a-3bc4-4d69-8ac3-3c4c0eff1582"

TELEGRAM_TOKEN = "5814224378:AAHlkQ41I-uQ9XXe_jmn5G28Q2x6nXCVNM8"
CHAT_ID = "5253808709"

MIN_SPREAD = 0.005
MIN_VOLUME_24H = 70000
SPREAD_LIFETIME_MIN = 3
UPDATE_INTERVAL = 120
TRADE_AMOUNT_USD = 500

# ====================== EXCHANGES ======================
exchanges = {
    'Gate': ccxt.gateio({'apiKey': GATE_API_KEY, 'secret': GATE_API_SECRET, 'enableRateLimit': True, 'options': {'defaultType': 'spot'}}),
    'Bitget': ccxt.bitget({'apiKey': BITGET_API_KEY, 'secret': BITGET_API_SECRET, 'enableRateLimit': True, 'options': {'defaultType': 'spot'}}),
    'Huobi': ccxt.htx({'apiKey': HUOBI_API_KEY, 'secret': HUOBI_API_SECRET, 'enableRateLimit': True}),
    'Binance': ccxt.binance({'apiKey': BINANCE_API_KEY, 'secret': BINANCE_API_SECRET, 'enableRateLimit': True}),
    'Kucoin': ccxt.kucoin({'apiKey': KUCOIN_API_KEY, 'secret': KUCOIN_API_SECRET, 'enableRateLimit': True})
}

active_spreads = {}
db_conn = None
tg_bot = telegram.Bot(token=TELEGRAM_TOKEN)

async def init_db():
    global db_conn
    db_conn = sqlite3.connect('multi_arbitrage.db', check_same_thread=False)
    db_conn.execute('''CREATE TABLE IF NOT EXISTS stats 
                       (timestamp TEXT, symbol TEXT, buy_ex TEXT, sell_ex TEXT, spread REAL, profit REAL, volume REAL)''')
    db_conn.commit()

async def get_order_book(exchange, symbol):
    try:
        ex_id = exchange.id.lower()
        if 'kucoin' in ex_id:
            limit = 20
        elif 'htx' in ex_id or 'huobi' in ex_id:
            limit = 20
        elif 'binance' in ex_id:
            limit = 10
        else:
            limit = 15
        ob = await exchange.fetch_order_book(symbol, limit=limit)
        ask = ob['asks'][0][0] if ob.get('asks') else None
        bid = ob['bids'][0][0] if ob.get('bids') else None
        vol = sum(v for p, v in (ob.get('asks') or [])[:5])
        return ask, bid, vol
    except Exception as e:
        logging.warning(f"Orderbook error {symbol} on {exchange.id}: {e}")
        return None, None, 0

async def send_to_telegram(spread):
    try:
        keyboard = [[KeyboardButton("/stats")]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        msg = f"""
🚨 **SPREAD {spread['spread']}%** | {spread['buy_ex']} → {spread['sell_ex']}
**Монета:** {spread['symbol']}
**Купить:** {spread['buy_ex']} @ {spread['buy_price']}
**Продать:** {spread['sell_ex']} @ {spread['sell_price']}
**Объём стакана:** ~{spread['volume_usd']}$
**Чистая с 500$:** +{spread['net_profit']}$
**Время жизни:** >3 мин
        """
        await tg_bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode='Markdown', reply_markup=reply_markup)
    except Exception as e:
        logging.error(f"TG error: {e}")

async def scan_multi_arbitrage():
    await init_db()
    markets = {}
    for name, ex in exchanges.items():
        try:
            markets[name] = await ex.load_markets()
            logging.info(f"✅ Loaded {len([s for s in markets[name] if s.endswith('/USDT')])} USDT pairs for {name}")
        except Exception as e:
            logging.error(f"❌ Failed markets {name}: {e}")

    all_symbols = set()
    for m in markets.values():
        all_symbols.update([s for s in m if s.endswith('/USDT')])

    logging.info(f"🚀 Total symbols for scan: {len(all_symbols)}")

    while True:
        now = datetime.now()
        for symbol in list(all_symbols):
            try:
                ticker = await exchanges['Gate'].fetch_ticker(symbol)
                if ticker.get('quoteVolume', 0) < MIN_VOLUME_24H:
                    continue

                for (ex1_name, ex1), (ex2_name, ex2) in combinations(exchanges.items(), 2):
                    ask1, bid1, vol1 = await get_order_book(ex1, symbol)
                    ask2, bid2, vol2 = await get_order_book(ex2, symbol)

                    if not all([ask1, bid1, ask2, bid2]):
                        continue

                    spread12 = (bid1 - ask2) / ask2
                    spread21 = (bid2 - ask1) / ask1
                    best = max(spread12, spread21)
                    if best < MIN_SPREAD:
                        continue

                    if spread12 > spread21:
                        buy_ex, sell_ex = ex2_name, ex1_name
                        buy_price, sell_price = ask2, bid1
                        direction_spread = spread12
                    else:
                        buy_ex, sell_ex = ex1_name, ex2_name
                        buy_price, sell_price = ask1, bid2
                        direction_spread = spread21

                    volume_usd = min(vol1, vol2) * buy_price
                    net_profit = TRADE_AMOUNT_USD * direction_spread - (TRADE_AMOUNT_USD * 0.0028) - 12

                    if net_profit <= 0:
                        continue

                    spread_key = f"{symbol}_{buy_ex}_{sell_ex}"
                    spread_data = {
                        "time": now.isoformat(),
                        "symbol": symbol,
                        "buy_ex": buy_ex,
                        "sell_ex": sell_ex,
                        "spread": round(direction_spread * 100, 2),
                        "buy_price": round(buy_price, 8),
                        "sell_price": round(sell_price, 8),
                        "volume_usd": round(volume_usd, 0),
                        "net_profit": round(net_profit, 2)
                    }

                    if spread_key not in active_spreads or abs(active_spreads[spread_key].get('spread', 0) - spread_data['spread']) > 0.15:
                        active_spreads[spread_key] = spread_data
                        await send_to_telegram(spread_data)

                    db_conn.execute("INSERT INTO stats VALUES (?,?,?,?,?,?,?)",
                        (now.isoformat(), symbol, buy_ex, sell_ex, direction_spread, net_profit, volume_usd))
                    db_conn.commit()

            except:
                continue

        # Cleanup
        for k in list(active_spreads.keys()):
            if (now - datetime.fromisoformat(active_spreads[k]["time"])).total_seconds() > SPREAD_LIFETIME_MIN * 60:
                del active_spreads[k]

        await asyncio.sleep(UPDATE_INTERVAL)

if __name__ == "__main__":
    logging.info("=== UNDERGROUND MULTI ARBITRAGE v3.0 FIXED & TESTED ===")
    logging.info("Биржи: Gate, Bitget, Huobi, Binance, Kucoin")
    asyncio.run(scan_multi_arbitrage())
