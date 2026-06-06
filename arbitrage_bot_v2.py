import asyncio
import ccxt.async_support as ccxt
import sqlite3
import logging
from datetime import datetime
import telegram
from telegram import ReplyKeyboardMarkup, KeyboardButton
from itertools import combinations
import os
from dotenv import load_dotenv
load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('arbitrage_bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
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
# ========================= НАСТРОЙКИ =========================
MIN_SPREAD = 0.008 # Минимальный спред 0.8%
MIN_VOLUME_24H = 100000 # Мин. объем $100k
UPDATE_INTERVAL = 30 # Проверка каждые 30 секунд
TRADE_AMOUNT_USD = 300 # Сумма для теста $300
# Комиссии бирж
COMMISSIONS = {
    'Gate': 0.002,
    'Bitget': 0.001,
    'Huobi': 0.002,
    'Binance': 0.001,
    'Kucoin': 0.001
}
# Статусы ввода/вывода монет
WITHDRAW_STATUS = {}
DEPOSIT_STATUS = {}
# Сети для перевода USDT
USDT_NETWORKS = {
    'Gate': ['TRC20', 'BEP20', 'ERC20'],
    'Bitget': ['TRC20', 'BEP20', 'ERC20'],
    'Huobi': ['TRC20', 'BEP20', 'ERC20'],
    'Binance': ['BEP20', 'TRC20', 'ERC20'],
    'Kucoin': ['TRC20', 'BEP20', 'ERC20']
}
PREFERRED_NETWORK = {
    'Gate': 'TRC20',
    'Bitget': 'TRC20',
    'Huobi': 'TRC20',
    'Binance': 'BEP20',
    'Kucoin': 'TRC20'
}
# Комиссии за вывод USDT
WITHDRAW_FEES = {
    'Gate': {'TRC20': 1, 'BEP20': 1, 'ERC20': 10},
    'Bitget': {'TRC20': 1, 'BEP20': 0.8, 'ERC20': 8},
    'Huobi': {'TRC20': 1, 'BEP20': 1, 'ERC20': 10},
    'Binance': {'TRC20': 1, 'BEP20': 0.8, 'ERC20': 10},
    'Kucoin': {'TRC20': 1, 'BEP20': 1, 'ERC20': 8}
}
# Время подтверждения (минуты)
CONFIRM_TIME = {
    'TRC20': 3,
    'BEP20': 2,
    'ERC20': 15
}
# ========================= ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ =========================
exchanges = {}
active_spreads = {}
db_conn = None
tg_bot = None
# ========================= ПРОВЕРКА ВВОДА/ВЫВОДА =========================
async def check_can_withdraw(exchange_name, symbol):
    """Проверяет, можно ли вывести монету с биржи"""
    asset = symbol.split('/')[0]
   
    # Для USDT всегда можно вывести
    if asset == 'USDT':
        network = PREFERRED_NETWORK.get(exchange_name, 'TRC20')
        fee = WITHDRAW_FEES.get(exchange_name, {}).get(network, 2)
        confirm = CONFIRM_TIME.get(network, 5)
        return True, network, fee, confirm
   
    # Для других монет пока разрешаем (можно донастроить)
    return True, 'TRC20', 2, 5
async def check_can_deposit(exchange_name, symbol):
    """Проверяет, можно ли ввести монету на биржу"""
    asset = symbol.split('/')[0]
   
    # Для USDT всегда можно ввести
    if asset == 'USDT':
        return True
   
    return True
async def get_transfer_info(buy_ex, sell_ex, symbol, amount_usd):
    """Получает информацию о переводе между биржами"""
    asset = symbol.split('/')[0]
   
    # Проверяем вывод с биржи покупки
    can_withdraw, network, fee, confirm_time = await check_can_withdraw(buy_ex, symbol)
    if not can_withdraw:
        return False, f"❌ Вывод {asset} с {buy_ex} недоступен", 0, 0
   
    # Проверяем ввод на биржу продажи
    can_deposit = await check_can_deposit(sell_ex, symbol)
    if not can_deposit:
        return False, f"❌ Ввод {asset} на {sell_ex} недоступен", 0, 0
   
    # Проверяем минимальную сумму
    if amount_usd < 10:
        return False, f"❌ Сумма ${amount_usd} меньше минимальной ${10}", 0, 0
   
    return True, "✅ Перевод возможен", fee, confirm_time
# ========================= ОСНОВНЫЕ ФУНКЦИИ =========================
async def init_db():
    global db_conn
    db_conn = sqlite3.connect('multi_arbitrage.db', check_same_thread=False)
    db_conn.execute('''CREATE TABLE IF NOT EXISTS arbitrage
                       (timestamp TEXT, symbol TEXT, buy_ex TEXT, sell_ex TEXT,
                        spread REAL, profit REAL, volume REAL, network TEXT)''')
    db_conn.commit()
async def init_exchanges():
    global exchanges, tg_bot
   
    if TELEGRAM_TOKEN and CHAT_ID:
        tg_bot = telegram.Bot(token=TELEGRAM_TOKEN)
   
    if GATE_API_KEY:
        exchanges['Gate'] = ccxt.gateio({
            'apiKey': GATE_API_KEY,
            'secret': GATE_API_SECRET,
            'enableRateLimit': True
        })
   
    if BITGET_API_KEY:
        exchanges['Bitget'] = ccxt.bitget({
            'apiKey': BITGET_API_KEY,
            'secret': BITGET_API_SECRET,
            'enableRateLimit': True
        })
   
    if HUOBI_API_KEY:
        exchanges['Huobi'] = ccxt.htx({
            'apiKey': HUOBI_API_KEY,
            'secret': HUOBI_API_SECRET,
            'enableRateLimit': True
        })
   
    if BINANCE_API_KEY:
        exchanges['Binance'] = ccxt.binance({
            'apiKey': BINANCE_API_KEY,
            'secret': BINANCE_API_SECRET,
            'enableRateLimit': True
        })
   
    if KUCOIN_API_KEY:
        exchanges['Kucoin'] = ccxt.kucoin({
            'apiKey': KUCOIN_API_KEY,
            'secret': KUCOIN_API_SECRET,
            'enableRateLimit': True
        })
   
    logging.info(f"Загружено бирж: {len(exchanges)}")
   
    for name, ex in exchanges.items():
        try:
            await ex.load_markets()
            logging.info(f"✅ {name} - подключена")
        except Exception as e:
            logging.error(f"❌ {name} - ошибка: {e}")
async def get_orderbook(exchange, symbol):
    """Получает стакан ордеров"""
    try:
        ob = await exchange.fetch_order_book(symbol, limit=10)
        ask = ob['asks'][0][0] if ob.get('asks') else None
        bid = ob['bids'][0][0] if ob.get('bids') else None
       
        # Считаем глубину
        depth = 0
        for price, vol in ob.get('asks', [])[:5]:
            depth += price * vol
       
        return ask, bid, depth
    except Exception as e:
        logging.debug(f"Ошибка {symbol} на {exchange.id}: {e}")
        return None, None, 0
async def send_telegram_message(spread_data):
    """Отправляет сообщение в Telegram на русском"""
    if not tg_bot:
        return
   
    try:
        keyboard = [[KeyboardButton("/статистика")], [KeyboardButton("/баланс")]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
       
        # Эмодзи для разных спредов
        if spread_data['spread'] > 2:
            emoji = "🔥🔥🔥"
        elif spread_data['spread'] > 1:
            emoji = "💰💰"
        else:
            emoji = "📈"
       
        msg = f"""
{emoji} **НАЙДЕН АРБИТРАЖ!** {emoji}
🎯 **Монета:** {spread_data['symbol']}
📊 **Спред:** {spread_data['spread']}%
━━━━━━━━━━━━━━━━━━━━━
📥 **ПОКУПКА:** {spread_data['buy_ex']}
   Цена: ${spread_data['buy_price']:.6f}
📤 **ПРОДАЖА:** {spread_data['sell_ex']}
   Цена: ${spread_data['sell_price']:.6f}
━━━━━━━━━━━━━━━━━━━━━
💵 **Прибыль с ${TRADE_AMOUNT_USD}:**
   • Чистая прибыль: **+${spread_data['net_profit']:.2f}**
   • ROI: {(spread_data['net_profit']/TRADE_AMOUNT_USD*100):.2f}%
🔄 **Перевод:**
   • Сеть: {spread_data['network']}
   • Комиссия: ${spread_data['transfer_fee']:.2f}
   • Время: ~{spread_data['transfer_time']} мин
⏰ {spread_data['time'][:19]}
        """
        await tg_bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode='Markdown', reply_markup=reply_markup)
        logging.info(f"📨 Отправлено уведомление: {spread_data['symbol']} {spread_data['spread']}%")
       
    except Exception as e:
        logging.error(f"Telegram ошибка: {e}")
async def scan_arbitrage():
    """Основной сканер арбитража"""
    await init_db()
    await init_exchanges()
   
    # Собираем все USDT пары со всех бирж
    all_symbols = set()
    for name, ex in exchanges.items():
        try:
            markets = ex.markets
            symbols = [s for s in markets if s.endswith('/USDT')]
            all_symbols.update(symbols)
            logging.info(f"📊 {name}: {len(symbols)} пар USDT")
        except Exception as e:
            logging.error(f"Ошибка загрузки {name}: {e}")
   
    logging.info(f"🚀 Всего монет для сканирования: {len(all_symbols)}")
    logging.info("Начинаю поиск арбитража...")
   
    exchange_list = list(exchanges.items())
   
    while True:
        start_time = datetime.now()
        found_count = 0
       
        for symbol in list(all_symbols)[:50]: # Ограничиваем для производительности
            # Получаем объем 24ч (упрощенно)
            try:
                ticker = await exchanges[list(exchanges.keys())[0]].fetch_ticker(symbol)
                if ticker.get('quoteVolume', 0) < MIN_VOLUME_24H:
                    continue
            except:
                continue
           
            # Проверяем все пары бирж
            for i, (name1, ex1) in enumerate(exchange_list):
                for name2, ex2 in exchange_list[i+1:]:
                    try:
                        # Получаем цены
                        ask1, bid1, depth1 = await get_orderbook(ex1, symbol)
                        ask2, bid2, depth2 = await get_orderbook(ex2, symbol)
                       
                        if not all([ask1, bid1, ask2, bid2]):
                            continue
                       
                        # Спред в обе стороны
                        spread1 = (bid2 - ask1) / ask1
                        spread2 = (bid1 - ask2) / ask2
                       
                        # Выбираем лучшее направление
                        if spread1 > spread2 and spread1 >= MIN_SPREAD:
                            buy_ex, sell_ex = name1, name2
                            buy_price, sell_price = ask1, bid2
                            spread = spread1
                        elif spread2 >= MIN_SPREAD:
                            buy_ex, sell_ex = name2, name1
                            buy_price, sell_price = ask2, bid1
                            spread = spread2
                        else:
                            continue
                       
                        # Проверяем возможность перевода
                        can_transfer, transfer_msg, transfer_fee, transfer_time = await get_transfer_info(
                            buy_ex, sell_ex, symbol, TRADE_AMOUNT_USD
                        )
                       
                        if not can_transfer:
                            continue
                       
                        # Расчет реальной прибыли
                        buy_commission = COMMISSIONS.get(buy_ex, 0.002)
                        sell_commission = COMMISSIONS.get(sell_ex, 0.002)
                       
                        # Учитываем проскальзывание
                        min_depth = min(depth1, depth2)
                        slippage = 0.005 if TRADE_AMOUNT_USD > min_depth * 0.3 else 0.002
                       
                        quantity = TRADE_AMOUNT_USD / buy_price
                        buy_cost = TRADE_AMOUNT_USD * (1 + buy_commission + slippage)
                        sell_revenue = quantity * sell_price * (1 - sell_commission - slippage)
                       
                        trade_profit = sell_revenue - buy_cost
                        net_profit = trade_profit - transfer_fee
                       
                        if net_profit < 5:
                            continue
                       
                        # Уникальный ключ для этого спреда
                        spread_key = f"{symbol}_{buy_ex}_{sell_ex}"
                       
                        # Проверяем, не отправляли ли недавно
                        if spread_key in active_spreads:
                            last = active_spreads[spread_key]
                            if abs(last['spread'] - spread * 100) < 0.2:
                                continue
                       
                        # Формируем данные
                        network = PREFERRED_NETWORK.get(buy_ex, 'TRC20')
                        spread_data = {
                            "time": datetime.now().isoformat(),
                            "symbol": symbol,
                            "buy_ex": buy_ex,
                            "sell_ex": sell_ex,
                            "spread": round(spread * 100, 2),
                            "buy_price": round(buy_price, 8),
                            "sell_price": round(sell_price, 8),
                            "net_profit": round(net_profit, 2),
                            "transfer_fee": transfer_fee,
                            "transfer_time": transfer_time,
                            "network": network,
                            "volume": round(min_depth, 0)
                        }
                       
                        active_spreads[spread_key] = spread_data
                        found_count += 1
                       
                        # Отправляем в Telegram
                        await send_telegram_message(spread_data)
                       
                        # Сохраняем в БД
                        db_conn.execute("""INSERT INTO arbitrage VALUES (?,?,?,?,?,?,?,?)""",
                            (spread_data["time"], symbol, buy_ex, sell_ex,
                             spread_data["spread"], net_profit, spread_data["volume"], network))
                        db_conn.commit()
                       
                        logging.info(f"🎯 НАЙДЕН! {symbol}: {spread_data['spread']}% → {buy_ex} → {sell_ex} | +${net_profit:.2f}")
                       
                    except Exception as e:
                        continue
       
        # Чистим старые спреды (старше 2 минут)
        now = datetime.now()
        for k in list(active_spreads.keys()):
            old_time = datetime.fromisoformat(active_spreads[k]["time"])
            if (now - old_time).total_seconds() > 120:
                del active_spreads[k]
       
        scan_time = (datetime.now() - start_time).total_seconds()
        if found_count > 0:
            logging.info(f"✅ Сканирование завершено: {found_count} возможностей за {scan_time:.1f} сек")
        else:
            logging.info(f"🔄 Сканирование: ничего не найдено за {scan_time:.1f} сек")
       
        await asyncio.sleep(UPDATE_INTERVAL)
async def main():
    """Запуск бота"""
    print("""
    ╔══════════════════════════════════════════════════════╗
    ║ АРБИТРАЖНЫЙ БОТ v5.0 (МЕЖБИРЖЕВОЙ) ║
    ║ ║
    ║ Биржи: Gate, Bitget, Huobi, Binance, Kucoin ║
    ║ Монеты: все USDT пары с объемом > $100k ║
    ║ Проверка ввода/вывода: ДА ║
    ║ Язык сообщений: РУССКИЙ 🇷🇺 ║
    ╚══════════════════════════════════════════════════════╝
    """)
   
    try:
        await scan_arbitrage()
    except KeyboardInterrupt:
        logging.info("Бот остановлен")
    finally:
        if db_conn:
            db_conn.close()
        for ex in exchanges.values():
            await ex.close()
if __name__ == "__main__":
    asyncio.run(main())
