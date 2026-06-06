import asyncio
import ccxt.async_support as ccxt
import sqlite3
import logging
from datetime import datetime, timedelta
import telegram
from telegram import ReplyKeyboardMarkup, KeyboardButton
from itertools import combinations

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('arbitrage_god.log', encoding='utf-8'), logging.StreamHandler()]
)

# ========================= API КЛЮЧИ =========================
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

# ========================= НАСТРОЙКИ GOD MODE =========================
MIN_SPREAD = 0.006
MIN_VOLUME_24H = 80000
UPDATE_INTERVAL = 25
TRADE_AMOUNT_USD = 400
MAX_SYMBOLS = 120

COMMISSIONS = {'Gate': 0.002, 'Bitget': 0.001, 'Huobi': 0.002, 'Binance': 0.001, 'Kucoin': 0.001}

PREFERRED_NETWORK = {'Gate': 'TRC20', 'Bitget': 'TRC20', 'Huobi': 'TRC20', 'Binance': 'BEP20', 'Kucoin': 'TRC20'}

# ========================= ГЛОБАЛЬНЫЕ =========================
exchanges = {}
active_spreads = {}
db_conn = None
tg_bot = None

# ========================= РЕАЛЬНАЯ ПРОВЕРКА СЕТЕЙ + КОНТРАКТОВ =========================
async def get_token_info(ex, symbol):
    asset = symbol.split('/')[0]
    try:
        currencies = await ex.fetch_currencies()
        if asset in currencies:
            return currencies[asset]
    except:
        pass
    return None

async def check_can_withdraw(exchange_name, symbol):
    asset = symbol.split('/')[0]
    ex = exchanges.get(exchange_name)
    if not ex: 
        return True, PREFERRED_NETWORK.get(exchange_name, 'TRC20'), 1.0, 5

    try:
        fees = await ex.fetch_deposit_withdraw_fees(asset)
        net_key = PREFERRED_NETWORK.get(exchange_name, 'TRC20')
        if net_key in fees:
            w_info = fees[net_key].get('withdraw', {})
            enabled = w_info.get('enabled', True)
            fee = w_info.get('fee', 1.0)
            return enabled, net_key, float(fee), 5
    except:
        pass
    return True, PREFERRED_NETWORK.get(exchange_name, 'TRC20'), 1.0, 5

async def check_can_deposit(exchange_name, symbol):
    asset = symbol.split('/')[0]
    ex = exchanges.get(exchange_name)
    if not ex: 
        return True
    try:
        fees = await ex.fetch_deposit_withdraw_fees(asset)
        net_key = PREFERRED_NETWORK.get(exchange_name, 'TRC20')
        if net_key in fees:
            return fees[net_key].get('deposit', {}).get('enabled', True)
    except:
        pass
    return True

async def get_transfer_info(buy_ex, sell_ex, symbol, amount):
    can_w, net, fee, ttime = await check_can_withdraw(buy_ex, symbol)
    if not can_w:
        return False, "Вывод закрыт", 0, 0
    can_d = await check_can_deposit(sell_ex, symbol)
    if not can_d:
        return False, "Ввод закрыт", 0, 0
    return True, "OK", fee, ttime

# ========================= ИНИТ =========================
async def init_db():
    global db_conn
    db_conn = sqlite3.connect('arbitrage_god.db', check_same_thread=False)
    db_conn.execute('''CREATE TABLE IF NOT EXISTS stats 
        (ts TEXT, symbol TEXT, buy_ex TEXT, sell_ex TEXT, spread REAL, profit REAL)''')
    db_conn.commit()

async def init_exchanges():
    global exchanges, tg_bot
    tg_bot = telegram.Bot(token=TELEGRAM_TOKEN)

    exchanges = {
        'Gate': ccxt.gateio({'apiKey': GATE_API_KEY, 'secret': GATE_API_SECRET, 'enableRateLimit': True}),
        'Bitget': ccxt.bitget({'apiKey': BITGET_API_KEY, 'secret': BITGET_API_SECRET, 'enableRateLimit': True}),
        'Huobi': ccxt.htx({'apiKey': HUOBI_API_KEY, 'secret': HUOBI_API_SECRET, 'enableRateLimit': True}),
        'Binance': ccxt.binance({'apiKey': BINANCE_API_KEY, 'secret': BINANCE_API_SECRET, 'enableRateLimit': True}),
        'Kucoin': ccxt.kucoin({'apiKey': KUCOIN_API_KEY, 'secret': KUCOIN_API_SECRET, 'enableRateLimit': True})
    }

    for name, ex in exchanges.items():
        try:
            await ex.load_markets()
            logging.info(f"✅ {name} READY")
        except Exception as e:
            logging.error(f"❌ {name}: {e}")

async def get_orderbook(ex, symbol):
    try:
        limit = 20 if ex.id == 'kucoin' else 10
        ob = await ex.fetch_order_book(symbol, limit=limit)
        ask = ob['asks'][0][0] if ob.get('asks') else None
        bid = ob['bids'][0][0] if ob.get('bids') else None
        depth = sum(p * v for p, v in ob.get('asks', [])[:5])
        return ask, bid, depth
    except Exception as e:
        logging.debug(f"OB error {symbol}@{ex.id}: {str(e)[:80]}")
        return None, None, 0

async def send_alert(data):
    try:
        emoji = "🔥🔥🔥" if data['spread'] > 1.5 else "💰"
        msg = f"""
{emoji} **GOD SPREAD {data['spread']}%** {emoji}
**{data['symbol']}**
→ Купить: {data['buy_ex']} @ {data['buy_price']}
→ Продать: {data['sell_ex']} @ {data['sell_price']}
**Прибыль с ${TRADE_AMOUNT_USD}: +${data['net_profit']:.2f}**
**Сеть:** {data['network']} | ~{data['time_est']} мин
        """
        keyboard = [[KeyboardButton("/stats"), KeyboardButton("/top")]]
        await tg_bot.send_message(CHAT_ID, msg, parse_mode='Markdown', reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    except:
        pass

# ========================= MAIN SCANNER =========================
async def scan_god_mode():
    await init_db()
    await init_exchanges()

    all_symbols = set()
    for ex in exchanges.values():
        try:
            all_symbols.update([s for s in ex.markets if s.endswith('/USDT')])
        except:
            pass

    logging.info(f"🚀 Сканирую {len(all_symbols)} пар...")

    ex_list = list(exchanges.items())

    while True:
        now = datetime.now()
        found = 0
        for symbol in list(all_symbols)[:MAX_SYMBOLS]:
            try:
                ticker = await list(exchanges.values())[0].fetch_ticker(symbol)
                if ticker.get('quoteVolume', 0) < MIN_VOLUME_24H:
                    continue

                for i, (n1, e1) in enumerate(ex_list):
                    for n2, e2 in ex_list[i+1:]:
                        a1, b1, d1 = await get_orderbook(e1, symbol)
                        a2, b2, d2 = await get_orderbook(e2, symbol)
                        if not all([a1, b1, a2, b2]):
                            continue

                        s1 = (b2 - a1) / a1
                        s2 = (b1 - a2) / a2
                        spread = max(s1, s2)
                        if spread < MIN_SPREAD:
                            continue

                        if s1 > s2:
                            buy_ex, sell_ex, buy_p, sell_p = n1, n2, a1, b2
                        else:
                            buy_ex, sell_ex, buy_p, sell_p = n2, n1, a2, b1

                        can, _, fee, ttime = await get_transfer_info(buy_ex, sell_ex, symbol, TRADE_AMOUNT_USD)
                        if not can:
                            continue

                        comm_b = COMMISSIONS.get(buy_ex, 0.002)
                        comm_s = COMMISSIONS.get(sell_ex, 0.002)
                        slip = 0.003 if TRADE_AMOUNT_USD > min(d1, d2)*0.25 else 0.001

                        qty = TRADE_AMOUNT_USD / buy_p
                        cost = TRADE_AMOUNT_USD * (1 + comm_b + slip)
                        rev = qty * sell_p * (1 - comm_s - slip)
                        profit = rev - cost - fee

                        if profit < 8:
                            continue

                        key = f"{symbol}_{buy_ex}_{sell_ex}"
                        if key in active_spreads and abs(active_spreads[key]['spread'] - spread*100) < 0.25:
                            continue

                        data = {
                            "time": now.isoformat(),
                            "symbol": symbol,
                            "buy_ex": buy_ex,
                            "sell_ex": sell_ex,
                            "spread": round(spread*100, 2),
                            "buy_price": round(buy_p, 8),
                            "sell_price": round(sell_p, 8),
                            "net_profit": round(profit, 2),
                            "network": PREFERRED_NETWORK.get(buy_ex),
                            "time_est": ttime
                        }

                        active_spreads[key] = data
                        found += 1
                        await send_alert(data)

                        db_conn.execute("INSERT INTO stats VALUES (?,?,?,?,?,?)", 
                            (now.isoformat(), symbol, buy_ex, sell_ex, spread, profit))
                        db_conn.commit()

            except:
                continue

        # Cleanup
        for k in list(active_spreads.keys()):
            if (now - datetime.fromisoformat(active_spreads[k]["time"])).total_seconds() > 180:
                del active_spreads[k]

        logging.info(f"Скан завершён | Найдено: {found} | Активных спредов: {len(active_spreads)}")
        await asyncio.sleep(UPDATE_INTERVAL)

async def main():
    print("\n🔥 UNDERGROUND ARBITRAGE GOD MODE v6.9 STARTED 🔥\n")
    try:
        await scan_god_mode()
    finally:
        if db_conn: db_conn.close()
        for ex in exchanges.values():
            await ex.close()

if __name__ == "__main__":
    asyncio.run(main())
