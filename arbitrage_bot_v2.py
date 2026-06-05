import asyncio
import ccxt.async_support as ccxt
import logging
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import time
from datetime import datetime
from collections import defaultdict
import json

# Настройки логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Telegram настройки
TELEGRAM_TOKEN = "5814224378:AAHlkQ41I-uQ9XXe_jmn5G28Q2x6nXCVNM8"
CHAT_ID = "5253808709"

# API КЛЮЧИ БИРЖ
EXCHANGE_KEYS = {
    'gate': {
        'apiKey': '5d80677222f36e38d07d92f317e45674',
        'secret': '1a4d3c051cb523364b540e87361435a096b20dc51d96df9a91eaf03c6ad55c13',
    },
    'huobi': {
        'apiKey': '29d9fe7e-4b147f7f-dbuqg6hkte-0a894',
        'secret': 'b0925bb5-07815986-b85bf68f-558a5',
    },
    'binance': {
        'apiKey': 'UvxQH98mpFgMRLM0ImIhBBohS3Pl86hVzDifpOUbmkRbDje6nZ0d74bB6oJLSFKt',
        'secret': 'C7LOcLQBBNsF8LWTabxy7sul8mC79pcsbEzlb518rnCE2O4FzejnvZa0j04ZoiEB',
    }
}

# Торговые настройки
TRADE_SIZE_USD = 500
MIN_SPREAD_PCT = 0.5  # Минимальный спред 0.5%
MAX_SPREAD_PCT = 200.0  # Максимальный спред до 200% (для шальных монет)
MIN_VOLUME_USD = 50000
MAX_WITHDRAWAL_TIME_MIN = 60  # Увеличил до 60 минут

# Черный список монет
BLACKLIST_COINS = {'KEY', 'STAR', 'BOND', 'MIRA', 'WILD', 'MAGIC', 'NATIVE', 'USDC', 'USDT', 'DAI'}

# Черный список проблемных сетей
BLACKLIST_NETWORKS = {
    'BSV': {'reason': 'очень долгий вывод', 'max_time': 1440},
    'BCH': {'reason': 'нестабильные выводы', 'max_time': 180},
}

# Расширенная база данных сетей
NETWORKS_INFO = {
    # Быстрые сети (до 5 минут)
    'SOL': {'name': 'Solana', 'time_min': 0.03, 'time_max': 0.08, 'fee': 0.0005, 'speed': '⚡️⚡️⚡️', 'risk': 'low', 'recommended': True, 'max_safe_time': 1},
    'SOLANA': {'name': 'Solana', 'time_min': 0.03, 'time_max': 0.08, 'fee': 0.0005, 'speed': '⚡️⚡️⚡️', 'risk': 'low', 'recommended': True, 'max_safe_time': 1},
    'XLM': {'name': 'Stellar', 'time_min': 0.05, 'time_max': 0.08, 'fee': 0.0001, 'speed': '⚡️⚡️⚡️', 'risk': 'low', 'recommended': True, 'max_safe_time': 1},
    'XRP': {'name': 'Ripple', 'time_min': 0.07, 'time_max': 0.17, 'fee': 0.0005, 'speed': '⚡️⚡️⚡️', 'risk': 'low', 'recommended': True, 'max_safe_time': 1},
    'ALGO': {'name': 'Algorand', 'time_min': 0.07, 'time_max': 0.08, 'fee': 0.0005, 'speed': '⚡️⚡️⚡️', 'risk': 'low', 'recommended': True, 'max_safe_time': 1},
    'NEAR': {'name': 'NEAR Protocol', 'time_min': 0.03, 'time_max': 0.08, 'fee': 0.0005, 'speed': '⚡️⚡️⚡️', 'risk': 'low', 'recommended': True, 'max_safe_time': 1},
    'APT': {'name': 'Aptos', 'time_min': 0.02, 'time_max': 0.05, 'fee': 0.0005, 'speed': '⚡️⚡️⚡️⚡️', 'risk': 'low', 'recommended': True, 'max_safe_time': 1},
    'SUI': {'name': 'Sui', 'time_min': 0.02, 'time_max': 0.05, 'fee': 0.0005, 'speed': '⚡️⚡️⚡️⚡️', 'risk': 'low', 'recommended': True, 'max_safe_time': 1},
    'FTM': {'name': 'Fantom', 'time_min': 0.02, 'time_max': 0.05, 'fee': 0.001, 'speed': '⚡️⚡️⚡️', 'risk': 'low', 'recommended': True, 'max_safe_time': 1},
    'AVAX': {'name': 'Avalanche', 'time_min': 0.03, 'time_max': 0.08, 'fee': 0.05, 'speed': '⚡️⚡️', 'risk': 'medium', 'recommended': True, 'max_safe_time': 2},
    'HBAR': {'name': 'Hedera', 'time_min': 0.05, 'time_max': 0.08, 'fee': 0.0001, 'speed': '⚡️⚡️⚡️', 'risk': 'low', 'recommended': True, 'max_safe_time': 1},
    'DOT': {'name': 'Polkadot', 'time_min': 0.17, 'time_max': 0.5, 'fee': 0.10, 'speed': '🟢', 'risk': 'low', 'recommended': True, 'max_safe_time': 2},
    'ATOM': {'name': 'Cosmos', 'time_min': 0.08, 'time_max': 0.17, 'fee': 0.05, 'speed': '🟢', 'risk': 'low', 'recommended': True, 'max_safe_time': 2},
    'TON': {'name': 'TON', 'time_min': 0.08, 'time_max': 0.17, 'fee': 0.20, 'speed': '🟢', 'risk': 'medium', 'recommended': True, 'max_safe_time': 2},
    
    # Средние сети (5-15 минут)
    'BEP20': {'name': 'BSC (BEP20)', 'time_min': 1, 'time_max': 3, 'fee': 0.02, 'speed': '🟢', 'risk': 'low', 'recommended': True, 'max_safe_time': 5},
    'BSC': {'name': 'BSC (BEP20)', 'time_min': 1, 'time_max': 3, 'fee': 0.02, 'speed': '🟢', 'risk': 'low', 'recommended': True, 'max_safe_time': 5},
    'MATIC': {'name': 'Polygon', 'time_min': 1, 'time_max': 3, 'fee': 0.02, 'speed': '🟢', 'risk': 'low', 'recommended': True, 'max_safe_time': 5},
    'POLYGON': {'name': 'Polygon', 'time_min': 1, 'time_max': 3, 'fee': 0.02, 'speed': '🟢', 'risk': 'low', 'recommended': True, 'max_safe_time': 5},
    'ARB': {'name': 'Arbitrum', 'time_min': 1, 'time_max': 2, 'fee': 0.02, 'speed': '🟢', 'risk': 'low', 'recommended': True, 'max_safe_time': 5},
    'ARBITRUM': {'name': 'Arbitrum', 'time_min': 1, 'time_max': 2, 'fee': 0.02, 'speed': '🟢', 'risk': 'low', 'recommended': True, 'max_safe_time': 5},
    'OP': {'name': 'Optimism', 'time_min': 1, 'time_max': 2, 'fee': 0.02, 'speed': '🟢', 'risk': 'low', 'recommended': True, 'max_safe_time': 5},
    'OPTIMISM': {'name': 'Optimism', 'time_min': 1, 'time_max': 2, 'fee': 0.02, 'speed': '🟢', 'risk': 'low', 'recommended': True, 'max_safe_time': 5},
    'BASE': {'name': 'Base', 'time_min': 1, 'time_max': 3, 'fee': 0.03, 'speed': '🟢', 'risk': 'low', 'recommended': True, 'max_safe_time': 5},
    'TRC20': {'name': 'Tron (TRC20)', 'time_min': 1, 'time_max': 3, 'fee': 1.50, 'speed': '🟢', 'risk': 'medium', 'recommended': True, 'max_safe_time': 5},
    'TRX': {'name': 'Tron (TRC20)', 'time_min': 1, 'time_max': 3, 'fee': 1.50, 'speed': '🟢', 'risk': 'medium', 'recommended': True, 'max_safe_time': 5},
    'BNB': {'name': 'BSC (BEP20)', 'time_min': 1, 'time_max': 3, 'fee': 0.15, 'speed': '🟢', 'risk': 'medium', 'recommended': True, 'max_safe_time': 5},
    'LTC': {'name': 'Litecoin', 'time_min': 5, 'time_max': 10, 'fee': 0.05, 'speed': '🟡', 'risk': 'medium', 'recommended': True, 'max_safe_time': 15},
    'ADA': {'name': 'Cardano', 'time_min': 2, 'time_max': 5, 'fee': 0.08, 'speed': '🟡', 'risk': 'low', 'recommended': True, 'max_safe_time': 10},
    
    # Медленные сети (более 15 минут)
    'ERC20': {'name': 'Ethereum (ERC20)', 'time_min': 5, 'time_max': 15, 'fee': 8.0, 'speed': '🔴', 'risk': 'high', 'recommended': False, 'max_safe_time': 30},
    'ETH': {'name': 'Ethereum (ERC20)', 'time_min': 5, 'time_max': 15, 'fee': 8.0, 'speed': '🔴', 'risk': 'high', 'recommended': False, 'max_safe_time': 30},
    'BTC': {'name': 'Bitcoin', 'time_min': 10, 'time_max': 60, 'fee': 2.50, 'speed': '🔴', 'risk': 'high', 'recommended': False, 'max_safe_time': 120},
    'BITCOIN': {'name': 'Bitcoin', 'time_min': 10, 'time_max': 60, 'fee': 2.50, 'speed': '🔴', 'risk': 'high', 'recommended': False, 'max_safe_time': 120},
    'XMR': {'name': 'Monero', 'time_min': 10, 'time_max': 30, 'fee': 0.05, 'speed': '🟡', 'risk': 'medium', 'recommended': False, 'max_safe_time': 45},
    'MONERO': {'name': 'Monero', 'time_min': 10, 'time_max': 30, 'fee': 0.05, 'speed': '🟡', 'risk': 'medium', 'recommended': False, 'max_safe_time': 45},
}

exchange_stats = defaultdict(lambda: {'buy_count': 0, 'sell_count': 0, 'total_profit': 0})
detected_candidates = {} 
active_spreads = {}      
spread_last_seen = {}    

bot = Bot(token=TELEGRAM_TOKEN)

class HealthCheckServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"Bot is running. Full scan mode.")

def run_health_server():
    try:
        server = HTTPServer(('0.0.0.0', 10000), HealthCheckServer)
        server.serve_forever()
    except Exception as e:
        logger.error(f"Health server error: {e}")

def is_network_blacklisted(network_name):
    for blacklisted, info in BLACKLIST_NETWORKS.items():
        if blacklisted.lower() in network_name.lower():
            return True, info['reason'], info['max_time']
    return False, None, None

def get_network_info(network_name):
    """Расширенный поиск информации о сети"""
    network_upper = network_name.upper()
    
    # Прямое совпадение
    for key, info in NETWORKS_INFO.items():
        if key.upper() == network_upper:
            is_blacklisted, reason, max_time = is_network_blacklisted(key)
            if is_blacklisted:
                return {**info, 'blacklisted': True, 'blacklist_reason': reason}
            return info
    
    # Частичное совпадение
    for key, info in NETWORKS_INFO.items():
        if key.upper() in network_upper or network_upper in key.upper():
            is_blacklisted, reason, max_time = is_network_blacklisted(key)
            if is_blacklisted:
                return {**info, 'blacklisted': True, 'blacklist_reason': reason}
            return info
    
    # Неизвестная сеть - логируем для добавления в базу
    logger.warning(f"⚠️ Неизвестная сеть: {network_name}, добавляем в базу с дефолтными значениями")
    
    # Динамически добавляем неизвестную сеть
    NETWORKS_INFO[network_upper] = {
        'name': network_name, 
        'time_min': 5, 
        'time_max': 15, 
        'fee': 0.5, 
        'speed': '❓', 
        'risk': 'unknown', 
        'recommended': False,
        'unknown': True,
        'max_safe_time': 30
    }
    
    return NETWORKS_INFO[network_upper]

async def get_order_book_depth(exchange, symbol, side, amount_usd):
    try:
        orderbook = await exchange.fetch_order_book(symbol, limit=20)
        orders = orderbook['asks'] if side == 'buy' else orderbook['bids']
        if not orders or len(orders) == 0:
            return None, 0, 0
        
        try:
            market = exchange.market(symbol)
            taker_fee = float(market.get('taker', 0.003))
        except:
            taker_fee = 0.003
            
        total_cost = 0
        total_amount = 0
        for level in orders:
            if not level or len(level) < 2:
                continue
            price = float(level[0] or 0)
            volume = float(level[1] or 0)
            if price == 0 or volume == 0:
                continue
            
            level_cost = price * volume
            if total_cost + level_cost >= amount_usd:
                needed_usd = amount_usd - total_cost
                total_amount += needed_usd / price
                total_cost += needed_usd
                break
            else:
                total_amount += volume
                total_cost += level_cost
                
        if total_cost < amount_usd or total_amount == 0:
            return None, 0, 0
        avg_price = total_cost / total_amount
        return avg_price, total_cost, (amount_usd * taker_fee)
    except Exception as e:
        return None, 0, 0

def generate_buy_link(exchange_id, symbol):
    coin = symbol.split('/')[0]
    pair = symbol.replace('/', '')
    base_urls = {
        'binance': f"https://www.binance.com/en/trade/{coin}_USDT",
        'bybit': f"https://www.bybit.com/trade/spot/{coin}/USDT",
        'okx': f"https://www.okx.com/trade-spot/{coin.lower()}-usdt",
        'gate': f"https://www.gate.io/trade/{coin}_USDT",
        'kucoin': f"https://www.kucoin.com/trade/{coin}-USDT",
        'mexc': f"https://www.mexc.com/exchange/{coin}_USDT",
        'bitget': f"https://www.bitget.com/spot/{pair}",
        'kraken': f"https://trade.kraken.com/markets/kraken/{coin.lower()}/usdt",
        'coinbase': f"https://www.coinbase.com/advanced-trading/{coin}-USDT",
        'huobi': f"https://www.htx.com/trade/{coin.lower()}_usdt",
        'htx': f"https://www.htx.com/trade/{coin.lower()}_usdt",
        'bingx': f"https://bingx.com/en/spot/{pair}",
        'bitmart': f"https://www.bitmart.com/trade/en?symbol={pair}",
        'phemex': f"https://phemex.com/trade/spot/{pair}",
    }
    return base_urls.get(exchange_id, f"https://{exchange_id}.com/trade/{coin}_USDT")

def format_signal_text(coin, buy_ex, sell_ex, p_buy, p_sell, buy_fee, sell_fee, common_network, net_profit, net_spread, processing_time):
    link_buy = generate_buy_link(buy_ex, f"{coin}/USDT")
    link_sell = generate_buy_link(sell_ex, f"{coin}/USDT")
    
    net_details = get_network_info(common_network['network'])
    
    if net_details.get('blacklisted', False):
        overall_status = "⛔️ СЕТЬ В ЧЕРНОМ СПИСКЕ"
        overall_icon = "⛔️"
    elif net_details.get('recommended', False):
        overall_status = "✅ РЕКОМЕНДУЕТСЯ"
        overall_icon = "✅"
    else:
        overall_status = "⚠️ ПРОВЕРЬТЕ СЕТЬ"
        overall_icon = "⚠️"
    
    return (
        f"⚡️ **НАЙДЕН АРБИТРАЖНЫЙ СПРЕД: #{coin}** ⚡️\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{overall_icon} **СТАТУС:** {overall_status}\n"
        f"⏱ **Время обработки:** {processing_time:.2f} сек\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 **ПОКУПКА: {buy_ex.upper()}**\n"
        f"├ 💵 Цена: `{p_buy:.8f} USDT`\n"
        f"├ 📊 Сумма: `${TRADE_SIZE_USD}`\n"
        f"└ 🔗 [Открыть пару]({link_buy})\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔴 **ПРОДАЖА: {sell_ex.upper()}**\n"
        f"├ 💵 Цена: `{p_sell:.8f} USDT`\n"
        f"└ 🔗 [Открыть пару]({link_sell})\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 **ОБЩАЯ СЕТЬ: {common_network['network']}**\n"
        f"├ 📤 Комиссия вывода ({buy_ex.upper()}): `${common_network['buy_fee']:.4f}`\n"
        f"├ 📥 Комиссия депозита ({sell_ex.upper()}): `${common_network['sell_fee']:.4f}`\n"
        f"├ ⏱ Время перевода: {net_details.get('time_min', 5)}-{net_details.get('time_max', 15)} мин\n"
        f"└ 🏁 Скорость: {net_details.get('speed', '❓')}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💸 **КОМИССИИ:**\n"
        f"├ 📊 Торговые: `${buy_fee + sell_fee:.2f}`\n"
        f"├ 📤 Вывод: `${common_network['buy_fee']:.2f}`\n"
        f"└ 📥 Депозит: `${common_network['sell_fee']:.2f}`\n"
        f"├ ─────────────────\n"
        f"└ **ИТОГО: `${buy_fee + sell_fee + common_network['buy_fee'] + common_network['sell_fee']:.2f}`**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💎 **ЧИСТАЯ ПРИБЫЛЬ:**\n"
        f"├ 📈 Чистый спред: **{net_spread:.2f}%**\n"
        f"└ 💰 Чистый профит: **+${net_profit:.2f}**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ **Вывод и депозит в ОДНОЙ сети: {common_network['network']}**"
    )

async def stats_command():
    stats_message = "📊 **АРБИТРАЖНАЯ СТАТИСТИКА** 📊\n"
    stats_message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    stats_message += f"🕐 Время: {datetime.now().strftime('%H:%M:%S')}\n\n"
    
    total_opp = sum(s['buy_count'] + s['sell_count'] for s in exchange_stats.values())
    total_profit = sum(s['total_profit'] for s in exchange_stats.values())
    
    stats_message += f"💎 Всего сигналов: **{total_opp}**\n"
    stats_message += f"💰 Мат. профит: **${total_profit:.2f}**\n"
    stats_message += f"📊 Мин. объем: ${MIN_VOLUME_USD:,}\n"
    stats_message += f"📈 Макс. спред: {MAX_SPREAD_PCT}%\n"
    stats_message += f"🌐 Известных сетей: {len(NETWORKS_INFO)}\n"
    stats_message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    stats_message += "🟢 **ТОП БИРЖ ДЛЯ ПОКУПКИ:**\n"
    top_buy = sorted(exchange_stats.items(), key=lambda x: x[1]['buy_count'], reverse=True)[:5]
    for ex, data in top_buy:
        if data['buy_count'] > 0:
            stats_message += f" ├ {ex.upper()}: **{data['buy_count']}** раз\n"
    
    stats_message += "\n🔴 **ТОП БИРЖ ДЛЯ ПРОДАЖИ:**\n"
    top_sell = sorted(exchange_stats.items(), key=lambda x: x[1]['sell_count'], reverse=True)[:5]
    for ex, data in top_sell:
        if data['sell_count'] > 0:
            stats_message += f" ├ {ex.upper()}: **{data['sell_count']}** раз\n"
    
    stats_message += f"\n🔄 **Активных спредов:** {len(active_spreads)}\n"
    stats_message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    return stats_message

def run_telegram_bot():
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    async def start_handler(update, context):
        await update.message.reply_text(
            "✅ **Арбитражный бот запущен!**\n\n"
            "**Настройки:**\n"
            f"✓ ПОЛНЫЙ перебор ВСЕХ бирж\n"
            f"✓ Поиск по ВСЕМ монетам (объем от ${MIN_VOLUME_USD:,})\n"
            f"✓ Максимальный спред до {MAX_SPREAD_PCT}%\n"
            f"✓ Проверка ОДИНАКОВЫХ сетей\n"
            f"✓ База {len(NETWORKS_INFO)} сетей\n\n"
            "**Команды:**\n"
            "📊 /stats - Статистика"
        )
    
    async def stats_handler(update, context):
        stats_text = await stats_command()
        keyboard = [[InlineKeyboardButton("🔄 Обновить", callback_data='refresh_stats')]]
        await update.message.reply_text(stats_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        
    async def button_handler(update, context):
        query = update.callback_query
        await query.answer()
        if query.data == 'refresh_stats':
            stats_text = await stats_command()
            keyboard = [[InlineKeyboardButton("🔄 Обновить", callback_data='refresh_stats')]]
            try: 
                await query.edit_message_text(stats_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            except: 
                pass
            
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("stats", stats_handler))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.run_polling(allowed_updates=['message', 'callback_query'])

async def scan_all_markets():
    logger.info("="*50)
    logger.info("ЗАПУСК АРБИТРАЖНОГО БОТА")
    logger.info(f"Поиск по ВСЕМ монетам с объемом от ${MIN_VOLUME_USD:,}")
    logger.info(f"Максимальный спред: {MAX_SPREAD_PCT}%")
    logger.info(f"База данных сетей: {len(NETWORKS_INFO)}")
    logger.info("="*50)
    
    exchanges = {}
    for ex_id in EXCHANGES_LIST:
        try:
            ex_class = getattr(ccxt, ex_id)
            config = {'enableRateLimit': True, 'timeout': 15000}
            if ex_id in EXCHANGE_KEYS:
                config.update(EXCHANGE_KEYS[ex_id])
            if ex_id in ['binance', 'bybit', 'okx']:
                config['options'] = {'defaultType': 'spot'}
            instance = ex_class(config)
            await instance.load_markets()
            exchanges[ex_id] = instance
            logger.info(f"✅ Загружена биржа: {ex_id}")
        except Exception as e:
            logger.warning(f"⚠️ Не загружена {ex_id}: {e}")

    logger.info(f"✅ Загружено бирж: {len(exchanges)}")
    
    scan_count = 0
    
    while True:
        scan_start_time = time.time()
        scan_count += 1
        all_tickers = {}
        current_time = time.time()

        async def fetch_tickers_safe(ex_id, exchange_obj):
            try:
                tickers = await exchange_obj.fetch_tickers()
                for sym, t in tickers.items():
                    if '/USDT' in sym and not sym.startswith('USDC'):
                        coin = sym.split('/')[0]
                        if coin in BLACKLIST_COINS: 
                            continue
                        vol = float(t.get('quoteVolume') or 0)
                        bid = float(t.get('bid') or 0)
                        ask = float(t.get('ask') or 0)
                        if vol >= MIN_VOLUME_USD and bid > 0 and ask > 0:
                            if sym not in all_tickers:
                                all_tickers[sym] = {}
                            all_tickers[sym][ex_id] = {'bid': bid, 'ask': ask, 'vol': vol}
            except Exception as e:
                pass

        await asyncio.gather(*[fetch_tickers_safe(eid, ex) for eid, ex in exchanges.items()])
        
        fresh_detected_keys = set()
        logger.info(f"🔄 Скан #{scan_count} | Найдено {len(all_tickers)} монет | Бирж: {len(exchanges)}")

        async def process_single_symbol(symbol, exchange_data):
            coin = symbol.split('/')[0]
            
            buy_exchanges = [(eid, d['ask']) for eid, d in exchange_data.items()]
            sell_exchanges = [(eid, d['bid']) for eid, d in exchange_data.items()]
            
            buy_exchanges.sort(key=lambda x: x[1])
            sell_exchanges.sort(key=lambda x: x[1], reverse=True)
            
            for buy_ex, ask_p in buy_exchanges:
                for sell_ex, bid_p in sell_exchanges:
                    if buy_ex == sell_ex: 
                        continue
                    
                    raw_spread = ((bid_p - ask_p) / ask_p) * 100
                    if raw_spread < MIN_SPREAD_PCT or raw_spread > MAX_SPREAD_PCT: 
                        continue
                    
                    common_networks = []
                    
                    try:
                        if hasattr(exchanges[buy_ex], 'fetch_currencies') and hasattr(exchanges[sell_ex], 'fetch_currencies'):
                            currencies_buy = await exchanges[buy_ex].fetch_currencies()
                            currencies_sell = await exchanges[sell_ex].fetch_currencies()
                            
                            if coin in currencies_buy and coin in currencies_sell:
                                buy_networks = currencies_buy[coin].get('networks', {})
                                sell_networks = currencies_sell[coin].get('networks', {})
                                
                                for net_name, buy_net_info in buy_networks.items():
                                    if not buy_net_info.get('withdraw', False):
                                        continue
                                    
                                    buy_fee = float(buy_net_info.get('fee', 0.5))
                                    if buy_fee == 0:
                                        continue
                                    
                                    for sell_net_name, sell_net_info in sell_networks.items():
                                        # Улучшенное сравнение сетей
                                        net_name_clean = net_name.upper().replace('_', '').replace('-', '')
                                        sell_net_clean = sell_net_name.upper().replace('_', '').replace('-', '')
                                        
                                        if net_name_clean == sell_net_clean or net_name_clean in sell_net_clean or sell_net_clean in net_name_clean:
                                            if not sell_net_info.get('deposit', False):
                                                continue
                                            
                                            sell_fee = float(sell_net_info.get('fee', 0.5))
                                            if sell_fee == 0:
                                                continue
                                            
                                            is_blacklisted, reason, _ = is_network_blacklisted(net_name)
                                            if is_blacklisted:
                                                continue
                                            
                                            common_networks.append({
                                                'network': net_name.upper(),
                                                'buy_fee': buy_fee,
                                                'sell_fee': sell_fee,
                                                'total_fee': buy_fee + sell_fee
                                            })
                                            logger.debug(f"Найдена сеть {net_name} для {coin}")
                            
                    except Exception as e:
                        continue
                    
                    if not common_networks:
                        continue
                    
                    common_networks.sort(key=lambda x: x['total_fee'])
                    best_network = common_networks[0]
                    
                    spread_key = f"{coin}_{buy_ex}_{sell_ex}_{best_network['network']}"
                    fresh_detected_keys.add(spread_key)
                    spread_last_seen[spread_key] = current_time
                    
                    if spread_key in active_spreads: 
                        continue
                    
                    if spread_key in detected_candidates:
                        if current_time - detected_candidates[spread_key] < 60:
                            continue
                    
                    if spread_key not in detected_candidates:
                        detected_candidates[spread_key] = current_time
                        continue
                    
                    p_buy, _, b_fee = await get_order_book_depth(exchanges[buy_ex], symbol, 'buy', TRADE_SIZE_USD)
                    p_sell, _, s_fee = await get_order_book_depth(exchanges[sell_ex], symbol, 'sell', TRADE_SIZE_USD)
                    
                    if p_buy and p_sell:
                        total_fees = b_fee + s_fee + best_network['buy_fee'] + best_network['sell_fee']
                        gross_profit = ((TRADE_SIZE_USD / p_buy) * p_sell - TRADE_SIZE_USD)
                        net_profit = gross_profit - total_fees
                        net_spread = (net_profit / TRADE_SIZE_USD) * 100
                        
                        if MIN_SPREAD_PCT <= net_spread <= MAX_SPREAD_PCT:
                            exchange_stats[buy_ex]['buy_count'] += 1
                            exchange_stats[buy_ex]['total_profit'] += (net_profit / 2)
                            exchange_stats[sell_ex]['sell_count'] += 1
                            exchange_stats[sell_ex]['total_profit'] += (net_profit / 2)
                            
                            processing_time = time.time() - scan_start_time
                            
                            msg_text = format_signal_text(coin, buy_ex, sell_ex, p_buy, p_sell, b_fee, s_fee, best_network, net_profit, net_spread, processing_time)
                            try:
                                msg = await bot.send_message(chat_id=CHAT_ID, text=msg_text, parse_mode="Markdown", disable_web_page_preview=True)
                                active_spreads[spread_key] = {
                                    "message_id": msg.message_id, 
                                    "coin": coin, 
                                    "buy_ex": buy_ex, 
                                    "sell_ex": sell_ex,
                                    "network": best_network['network'],
                                    "created_at": current_time
                                }
                                detected_candidates.pop(spread_key, None)
                                logger.info(f"✅ СИГНАЛ: {coin} {buy_ex}→{sell_ex} | сеть: {best_network['network']} | спред: {net_spread:.2f}% | профит: ${net_profit:.2f}")
                            except Exception as e:
                                logger.error(f"Ошибка отправки: {e}")

        chunks = list(all_tickers.items())
        for i in range(0, len(chunks), 50):
            await asyncio.gather(*[process_single_symbol(sym, edata) for sym, edata in chunks[i:i+50]])
            await asyncio.sleep(0.1)
        
        for k in list(detected_candidates.keys()):
            if k not in fresh_detected_keys:
                del detected_candidates[k]
        
        spreads_to_remove = []
        for spread_key, spread_data in list(active_spreads.items()):
            if spread_key not in fresh_detected_keys:
                last_seen = spread_last_seen.get(spread_key, 0)
                if current_time - last_seen > 60:
                    spreads_to_remove.append(spread_key)
            else:
                spread_last_seen[spread_key] = current_time
        
        for spread_key in spreads_to_remove:
            try:
                spread_data = active_spreads.get(spread_key)
                if spread_data:
                    await bot.delete_message(chat_id=CHAT_ID, message_id=spread_data["message_id"])
                    logger.info(f"🗑️ Удален спред {spread_data['coin']}")
            except:
                pass
            finally:
                active_spreads.pop(spread_key, None)
                spread_last_seen.pop(spread_key, None)
                detected_candidates.pop(spread_key, None)
        
        scan_time = time.time() - scan_start_time
        logger.info(f"✅ Скан #{scan_count} завершен за {scan_time:.2f} сек | Найдено спредов: {len(active_spreads)}")
                    
        await asyncio.sleep(15)

EXCHANGES_LIST = [
    'binance', 'bybit', 'okx', 'gate', 'kucoin', 'bitget', 'mexc', 
    'bingx', 'htx', 'kraken', 'coinbase', 'huobi', 'poloniex', 
    'hitbtc', 'exmo', 'bitfinex', 'bitmart', 'lbank', 'ascendex',
    'coinex', 'whitebit', 'bitrue', 'phemex'
]

if __name__ == '__main__':
    threading.Thread(target=run_health_server, daemon=True).start()
    threading.Thread(target=run_telegram_bot, daemon=True).start()
    asyncio.run(scan_all_markets())
