import asyncio
import ccxt.async_support as ccxt
import logging
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import time
from datetime import datetime
from collections import defaultdict

# === НАСТРОЙКИ ===
TELEGRAM_TOKEN = "5814224378:AAHlkQ41I-uQ9XXe_jmn5G28Q2x6nXCVNM8"
CHAT_ID = "5253808709"

# API ключи только для бирж, где есть ключи
EXCHANGE_KEYS = {
    'gate': {'apiKey': '5d80677222f36e38d07d92f317e45674', 'secret': '1a4d3c051cb523364b540e87361435a096b20dc51d96df9a91eaf03c6ad55c13'},
}

TRADE_SIZE_USD = 500
LIQUIDITY_CHECK_USD = 1000
MIN_SPREAD_PCT = 0.8  # Увеличил минимальный спред до 0.8% чтобы отсеять мусор
MAX_SPREAD_PCT = 200.0
MIN_VOLUME_USD = 30000  # Уменьшил объем до 30к чтобы больше монет находить

# Черный список монет
BLACKLIST_COINS = {'KEY', 'STAR', 'BOND', 'MIRA', 'WILD', 'MAGIC', 'NATIVE', 'USDC', 'USDT', 'DAI', 'BUSD', 'TUSD'}

# Черный список сетей - НЕ ИСПОЛЬЗУЕМ
BLACKLIST_NETWORKS = {
    'BSV': {'reason': 'разные сети у бирж'},
    'BCH': {'reason': 'нестабильные выводы'},
}

# Расширенная база сетей
NETWORKS_INFO = {
    # Быстрые сети
    'SOL': {'time_min': 0.03, 'time_max': 0.08, 'fee': 0.0005, 'speed': '⚡️⚡️⚡️', 'recommended': True},
    'SOLANA': {'time_min': 0.03, 'time_max': 0.08, 'fee': 0.0005, 'speed': '⚡️⚡️⚡️', 'recommended': True},
    'XLM': {'time_min': 0.05, 'time_max': 0.08, 'fee': 0.0001, 'speed': '⚡️⚡️⚡️', 'recommended': True},
    'XRP': {'time_min': 0.07, 'time_max': 0.17, 'fee': 0.0005, 'speed': '⚡️⚡️⚡️', 'recommended': True},
    'TRX': {'time_min': 1, 'time_max': 3, 'fee': 1.50, 'speed': '🟢', 'recommended': True},
    'TRC20': {'time_min': 1, 'time_max': 3, 'fee': 1.50, 'speed': '🟢', 'recommended': True},
    
    # Сети EVM
    'BEP20': {'time_min': 1, 'time_max': 3, 'fee': 0.02, 'speed': '🟢', 'recommended': True},
    'BSC': {'time_min': 1, 'time_max': 3, 'fee': 0.02, 'speed': '🟢', 'recommended': True},
    'ERC20': {'time_min': 5, 'time_max': 15, 'fee': 8.0, 'speed': '🔴', 'recommended': False},
    'ETH': {'time_min': 5, 'time_max': 15, 'fee': 8.0, 'speed': '🔴', 'recommended': False},
    'MATIC': {'time_min': 1, 'time_max': 3, 'fee': 0.02, 'speed': '🟢', 'recommended': True},
    'POLYGON': {'time_min': 1, 'time_max': 3, 'fee': 0.02, 'speed': '🟢', 'recommended': True},
    'ARB': {'time_min': 1, 'time_max': 2, 'fee': 0.02, 'speed': '🟢', 'recommended': True},
    'ARBITRUM': {'time_min': 1, 'time_max': 2, 'fee': 0.02, 'speed': '🟢', 'recommended': True},
    'OP': {'time_min': 1, 'time_max': 2, 'fee': 0.02, 'speed': '🟢', 'recommended': True},
    'OPTIMISM': {'time_min': 1, 'time_max': 2, 'fee': 0.02, 'speed': '🟢', 'recommended': True},
    'AVAX': {'time_min': 0.03, 'time_max': 0.08, 'fee': 0.05, 'speed': '⚡️⚡️', 'recommended': True},
    'AVALANCHE': {'time_min': 0.03, 'time_max': 0.08, 'fee': 0.05, 'speed': '⚡️⚡️', 'recommended': True},
    'FTM': {'time_min': 0.02, 'time_max': 0.05, 'fee': 0.001, 'speed': '⚡️⚡️⚡️', 'recommended': True},
    'FANTOM': {'time_min': 0.02, 'time_max': 0.05, 'fee': 0.001, 'speed': '⚡️⚡️⚡️', 'recommended': True},
    
    # Альткоины
    'DOGE': {'time_min': 2, 'time_max': 5, 'fee': 0.5, 'speed': '🟡', 'recommended': True},
    'LTC': {'time_min': 5, 'time_max': 10, 'fee': 0.05, 'speed': '🟡', 'recommended': True},
    'DOT': {'time_min': 0.17, 'time_max': 0.5, 'fee': 0.10, 'speed': '🟢', 'recommended': True},
    'ATOM': {'time_min': 0.08, 'time_max': 0.17, 'fee': 0.05, 'speed': '🟢', 'recommended': True},
    'NEAR': {'time_min': 0.03, 'time_max': 0.08, 'fee': 0.0005, 'speed': '⚡️⚡️⚡️', 'recommended': True},
    'APT': {'time_min': 0.02, 'time_max': 0.05, 'fee': 0.0005, 'speed': '⚡️⚡️⚡️⚡️', 'recommended': True},
    'SUI': {'time_min': 0.02, 'time_max': 0.05, 'fee': 0.0005, 'speed': '⚡️⚡️⚡️⚡️', 'recommended': True},
    
    # Медленные - не рекомендуем
    'BTC': {'time_min': 10, 'time_max': 60, 'fee': 2.50, 'speed': '🔴', 'recommended': False},
    'BITCOIN': {'time_min': 10, 'time_max': 60, 'fee': 2.50, 'speed': '🔴', 'recommended': False},
}

# Объединяем HTX и Huobi в одну биржу
EXCHANGE_ALIAS = {
    'huobi': 'htx',
    'htx': 'htx'
}

exchange_stats = defaultdict(lambda: {'buy_count': 0, 'sell_count': 0, 'total_profit': 0, 'last_signal': 0})
detected_candidates = {}
active_spreads = {}
spread_last_seen = {}

bot = Bot(token=TELEGRAM_TOKEN)
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def get_network_info(network_name):
    """Расширенный поиск информации о сети"""
    net_upper = network_name.upper()
    
    # Прямое совпадение
    for key, info in NETWORKS_INFO.items():
        if key.upper() == net_upper:
            return {**info, 'network': key}
    
    # Частичное совпадение
    for key, info in NETWORKS_INFO.items():
        if key.upper() in net_upper or net_upper in key.upper():
            return {**info, 'network': key}
    
    # Неизвестная сеть - добавляем в базу с дефолтными значениями
    logger.warning(f"⚠️ Неизвестная сеть: {network_name}")
    return {
        'time_min': 10, 'time_max': 30, 'fee': 0.5, 'speed': '❓', 
        'recommended': False, 'network': network_name, 'unknown': True
    }

def normalize_exchange_name(exchange_id):
    """Нормализует название биржи (HTX и Huobi - одно и то же)"""
    if exchange_id in ['huobi', 'htx']:
        return 'htx'
    return exchange_id

def generate_deeplink(exchange, coin):
    """Генерирует ссылку для открытия пары"""
    exchange = normalize_exchange_name(exchange)
    
    deeplinks = {
        'bitget': f"bitget://spot/{coin}_USDT",
        'gate': f"gateio://trade/{coin}_USDT",
        'kucoin': f"kucoin://market/{coin}_USDT",
        'poloniex': f"poloniex://trade/{coin}_USDT",
        'htx': f"https://www.htx.com/trade/{coin.lower()}_usdt",
        'binance': f"https://www.binance.com/en/trade/{coin}_USDT",
        'bybit': f"https://www.bybit.com/trade/spot/{coin}/USDT",
        'okx': f"https://www.okx.com/trade-spot/{coin.lower()}-usdt",
    }
    return deeplinks.get(exchange, f"https://{exchange}.com/trade/{coin}_USDT")

async def get_order_book_liquidity(exchange, symbol, side, required_usd):
    """Проверяет ликвидность стакана на сумму required_usd"""
    try:
        orderbook = await exchange.fetch_order_book(symbol, limit=20)
        orders = orderbook['asks'] if side == 'buy' else orderbook['bids']
        if not orders:
            return None, 0, 0
        
        taker_fee = exchange.market(symbol).get('taker', 0.003)
        total_cost = 0
        total_amount = 0
        
        for price, volume in orders:
            level_usd = price * volume
            if total_cost + level_usd >= required_usd:
                need = required_usd - total_cost
                total_amount += need / price
                total_cost += need
                break
            else:
                total_amount += volume
                total_cost += level_usd
        
        if total_cost < required_usd or total_amount == 0:
            return None, 0, 0
        
        avg_price = total_cost / total_amount
        return avg_price, total_cost, required_usd * taker_fee
    except Exception as e:
        return None, 0, 0

async def check_common_network(buy_exchange, sell_exchange, coin):
    """Проверяет общие сети для вывода и депозита"""
    try:
        cur_buy = await buy_exchange.fetch_currencies()
        cur_sell = await sell_exchange.fetch_currencies()
        
        if coin not in cur_buy or coin not in cur_sell:
            return None
        
        buy_nets = cur_buy[coin].get('networks', {})
        sell_nets = cur_sell[coin].get('networks', {})
        
        if not buy_nets or not sell_nets:
            return None
        
        common = []
        
        for net, binfo in buy_nets.items():
            # Проверяем вывод на бирже покупки
            if not binfo.get('withdraw', False):
                continue
            
            buy_fee = float(binfo.get('fee', 0.5))
            if buy_fee == 0 or buy_fee > 100:  # Отсекаем нереальные комиссии
                continue
            
            for snet, sinfo in sell_nets.items():
                # Проверяем депозит на бирже продажи
                if not sinfo.get('deposit', False):
                    continue
                
                # Сравниваем сети (без учета регистра и спецсимволов)
                net_clean = net.upper().replace('_', '').replace('-', '').replace(' ', '')
                snet_clean = snet.upper().replace('_', '').replace('-', '').replace(' ', '')
                
                if net_clean == snet_clean or net_clean in snet_clean or snet_clean in net_clean:
                    sell_fee = float(sinfo.get('fee', 0.5))
                    if sell_fee == 0 or sell_fee > 100:
                        continue
                    
                    # Проверяем черный список сетей
                    if net_clean in [b.upper() for b in BLACKLIST_NETWORKS]:
                        continue
                    
                    common.append({
                        'network': net.upper(),
                        'buy_fee': buy_fee,
                        'sell_fee': sell_fee,
                        'total': buy_fee + sell_fee
                    })
        
        if not common:
            return None
        
        # Сортируем по сумме комиссий
        common.sort(key=lambda x: x['total'])
        return common[0]
    except Exception as e:
        return None

def format_signal(coin, buy_ex, sell_ex, p_buy, p_sell, buy_fee, sell_fee, net_info, net_profit, net_spread):
    """Форматирует сообщение о сигнале"""
    buy_ex = normalize_exchange_name(buy_ex)
    sell_ex = normalize_exchange_name(sell_ex)
    link_buy = generate_deeplink(buy_ex, coin)
    link_sell = generate_deeplink(sell_ex, coin)
    net_details = get_network_info(net_info['network'])
    
    # Определяем статус сети
    if net_details.get('recommended', False):
        net_status = "✅ РЕКОМЕНДУЕТСЯ"
    elif net_details.get('unknown', False):
        net_status = "⚠️ НЕИЗВЕСТНАЯ СЕТЬ"
    else:
        net_status = "⚠️ ПРОВЕРЬТЕ ВРУЧНУЮ"
    
    return (
        f"⚡️ **НАЙДЕН АРБИТРАЖНЫЙ СПРЕД: #{coin}** ⚡️\n"
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
        f"📦 **СЕТЬ: {net_info['network']}** {net_status}\n"
        f"├ 📤 Вывод ({buy_ex.upper()}): `${net_info['buy_fee']:.4f}`\n"
        f"├ 📥 Депозит ({sell_ex.upper()}): `${net_info['sell_fee']:.4f}`\n"
        f"├ ⏱ Время: {net_details['time_min']}-{net_details['time_max']} мин\n"
        f"└ 🏁 Скорость: {net_details['speed']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💸 **КОМИССИИ:**\n"
        f"├ 📊 Торговые: `${buy_fee + sell_fee:.2f}`\n"
        f"├ 📤 Вывод: `${net_info['buy_fee']:.2f}`\n"
        f"└ 📥 Депозит: `${net_info['sell_fee']:.2f}`\n"
        f"├ ─────────────────\n"
        f"└ **ИТОГО: `${buy_fee + sell_fee + net_info['buy_fee'] + net_info['sell_fee']:.2f}`**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💎 **ЧИСТАЯ ПРИБЫЛЬ:**\n"
        f"├ 📈 Чистый спред: **{net_spread:.2f}%**\n"
        f"└ 💰 Чистый профит: **+${net_profit:.2f}**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

# ========== ТЕЛЕГРАМ КОМАНДЫ ==========
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ **Арбитражный бот запущен**\n\n"
        "📌 Проверка ликвидности на $1000\n"
        "📌 Спред удаляется при исчезновении\n"
        "📌 Deeplinks: Bitget, Gate, KuCoin, Poloniex\n"
        "📌 HTX и Huobi объединены в одну биржу\n\n"
        "📊 /stats - Статистика по биржам\n"
        "🔄 /active - Активные спреды"
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает статистику по биржам"""
    total_signals = sum(s['buy_count'] + s['sell_count'] for s in exchange_stats.values())
    total_profit = sum(s['total_profit'] for s in exchange_stats.values())
    
    stats_msg = "📊 **АРБИТРАЖНАЯ СТАТИСТИКА** 📊\n"
    stats_msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    stats_msg += f"🕐 {datetime.now().strftime('%H:%M:%S')}\n\n"
    stats_msg += f"💎 **Всего сигналов:** {total_signals}\n"
    stats_msg += f"💰 **Мат. профит:** ${total_profit:.2f}\n"
    stats_msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    stats_msg += "🟢 **ГДЕ ДЕРЖАТЬ USDT (покупка):**\n"
    top_buy = sorted(exchange_stats.items(), key=lambda x: x[1]['buy_count'], reverse=True)[:5]
    has_buy = False
    for ex, data in top_buy:
        if data['buy_count'] > 0:
            stats_msg += f"├ {ex.upper()}: {data['buy_count']} раз(а)\n"
            has_buy = True
    if not has_buy:
        stats_msg += "├ Пока нет данных...\n"
    
    stats_msg += "\n🔴 **ГДЕ ДЕРЖАТЬ МОНЕТЫ (продажа):**\n"
    top_sell = sorted(exchange_stats.items(), key=lambda x: x[1]['sell_count'], reverse=True)[:5]
    has_sell = False
    for ex, data in top_sell:
        if data['sell_count'] > 0:
            stats_msg += f"├ {ex.upper()}: {data['sell_count']} раз(а)\n"
            has_sell = True
    if not has_sell:
        stats_msg += "├ Пока нет данных...\n"
    
    stats_msg += f"\n🔄 **Активных спредов:** {len(active_spreads)}"
    
    keyboard = [[InlineKeyboardButton("🔄 Обновить", callback_data='refresh_stats')]]
    await update.message.reply_text(stats_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def active_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает активные спреды"""
    if not active_spreads:
        await update.message.reply_text("🔍 Нет активных спредов в данный момент")
        return
    
    msg = "🔄 **АКТИВНЫЕ СПРЕДЫ:**\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    for key, data in list(active_spreads.items())[:10]:
        age = int(time.time() - data.get('created_at', time.time()))
        msg += f"├ {data['coin']}: {data['buy_ex']} → {data['sell_ex']}\n"
        msg += f"├   Сеть: {data.get('network', '?')} | {age} сек\n"
        msg += f"└━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кнопок"""
    query = update.callback_query
    await query.answer()
    
    if query.data == 'refresh_stats':
        total_signals = sum(s['buy_count'] + s['sell_count'] for s in exchange_stats.values())
        total_profit = sum(s['total_profit'] for s in exchange_stats.values())
        
        stats_msg = "📊 **АРБИТРАЖНАЯ СТАТИСТИКА** 📊\n"
        stats_msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        stats_msg += f"🕐 {datetime.now().strftime('%H:%M:%S')}\n\n"
        stats_msg += f"💎 **Всего сигналов:** {total_signals}\n"
        stats_msg += f"💰 **Мат. профит:** ${total_profit:.2f}\n"
        stats_msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        stats_msg += "🟢 **ГДЕ ДЕРЖАТЬ USDT (покупка):**\n"
        top_buy = sorted(exchange_stats.items(), key=lambda x: x[1]['buy_count'], reverse=True)[:5]
        for ex, data in top_buy:
            if data['buy_count'] > 0:
                stats_msg += f"├ {ex.upper()}: {data['buy_count']} раз(а)\n"
        
        stats_msg += "\n🔴 **ГДЕ ДЕРЖАТЬ МОНЕТЫ (продажа):**\n"
        top_sell = sorted(exchange_stats.items(), key=lambda x: x[1]['sell_count'], reverse=True)[:5]
        for ex, data in top_sell:
            if data['sell_count'] > 0:
                stats_msg += f"├ {ex.upper()}: {data['sell_count']} раз(а)\n"
        
        stats_msg += f"\n🔄 **Активных спредов:** {len(active_spreads)}"
        
        keyboard = [[InlineKeyboardButton("🔄 Обновить", callback_data='refresh_stats')]]
        await query.edit_message_text(stats_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ========== ОСНОВНОЙ СКАНЕР ==========
async def scan_all_markets():
    logger.info("="*50)
    logger.info("ЗАПУСК АРБИТРАЖНОГО БОТА")
    logger.info("="*50)
    
    # Список бирж для сканирования (без binance/bybit из-за гео-блокировки)
    exchange_list = ['gate', 'kucoin', 'bitget', 'mexc', 'htx', 'poloniex', 'bitmart', 'phemex', 'coinex', 'whitebit']
    
    exchanges = {}
    for ex_id in exchange_list:
        try:
            ex_class = getattr(ccxt, ex_id)
            config = {'enableRateLimit': True, 'timeout': 15000}
            if ex_id in EXCHANGE_KEYS:
                config.update(EXCHANGE_KEYS[ex_id])
            instance = ex_class(config)
            await instance.load_markets()
            # Нормализуем имя биржи
            normalized_name = normalize_exchange_name(ex_id)
            exchanges[normalized_name] = instance
            logger.info(f"✅ Загружена: {normalized_name}")
        except Exception as e:
            logger.warning(f"⚠️ Пропущена {ex_id}: {str(e)[:50]}")
    
    logger.info(f"✅ Загружено бирж: {len(exchanges)}")
    
    scan_count = 0
    
    while True:
        scan_start = time.time()
        scan_count += 1
        all_tickers = {}
        current_time = time.time()
        
        async def fetch_ticker(ex_id, ex_obj):
            try:
                tickers = await ex_obj.fetch_tickers()
                for sym, t in tickers.items():
                    if '/USDT' in sym and not sym.startswith('USDC'):
                        coin = sym.split('/')[0]
                        if coin in BLACKLIST_COINS:
                            continue
                        vol = float(t.get('quoteVolume', 0))
                        bid = float(t.get('bid', 0))
                        ask = float(t.get('ask', 0))
                        if vol >= MIN_VOLUME_USD and bid > 0 and ask > 0:
                            all_tickers.setdefault(sym, {})[ex_id] = {'bid': bid, 'ask': ask}
            except Exception as e:
                pass
        
        await asyncio.gather(*(fetch_ticker(eid, ex) for eid, ex in exchanges.items()))
        
        fresh_keys = set()
        logger.info(f"🔄 Скан #{scan_count}: {len(all_tickers)} монет, {len(exchanges)} бирж")
        
        # Обработка каждой монеты
        for symbol, data in all_tickers.items():
            coin = symbol.split('/')[0]
            if len(data) < 2:
                continue
            
            # Берем топ-5 бирж для покупки и продажи
            buy_list = sorted(data.items(), key=lambda x: x[1]['ask'])[:5]
            sell_list = sorted(data.items(), key=lambda x: x[1]['bid'], reverse=True)[:5]
            
            for buy_ex, buy_d in buy_list:
                for sell_ex, sell_d in sell_list:
                    if buy_ex == sell_ex:
                        continue
                    
                    # Расчет сырого спреда
                    raw_spread = (sell_d['bid'] - buy_d['ask']) / buy_d['ask'] * 100
                    if raw_spread < MIN_SPREAD_PCT or raw_spread > MAX_SPREAD_PCT:
                        continue
                    
                    # Проверяем общие сети
                    net_info = await check_common_network(exchanges[buy_ex], exchanges[sell_ex], coin)
                    if not net_info:
                        continue
                    
                    # Уникальный ключ спреда
                    key = f"{coin}_{buy_ex}_{sell_ex}_{net_info['network']}"
                    fresh_keys.add(key)
                    spread_last_seen[key] = current_time
                    
                    # Проверяем активность и кандидатов
                    if key in active_spreads:
                        continue
                    if key in detected_candidates:
                        if current_time - detected_candidates[key] < 60:
                            continue
                    if key not in detected_candidates:
                        detected_candidates[key] = current_time
                        continue
                    
                    # Проверяем ликвидность
                    p_buy, _, buy_fee_liquidity = await get_order_book_liquidity(
                        exchanges[buy_ex], symbol, 'buy', LIQUIDITY_CHECK_USD
                    )
                    p_sell, _, sell_fee_liquidity = await get_order_book_liquidity(
                        exchanges[sell_ex], symbol, 'sell', LIQUIDITY_CHECK_USD
                    )
                    
                    if not p_buy or not p_sell:
                        continue
                    
                    # Расчет торговых комиссий
                    taker_buy = exchanges[buy_ex].market(symbol).get('taker', 0.003)
                    taker_sell = exchanges[sell_ex].market(symbol).get('taker', 0.003)
                    b_fee_trade = TRADE_SIZE_USD * taker_buy
                    s_fee_trade = TRADE_SIZE_USD * taker_sell
                    
                    # Расчет чистой прибыли
                    total_fees = b_fee_trade + s_fee_trade + net_info['buy_fee'] + net_info['sell_fee']
                    gross = ((TRADE_SIZE_USD / p_buy) * p_sell - TRADE_SIZE_USD)
                    net_profit = gross - total_fees
                    net_spread = (net_profit / TRADE_SIZE_USD) * 100
                    
                    if net_spread >= MIN_SPREAD_PCT:
                        # Обновляем статистику
                        exchange_stats[buy_ex]['buy_count'] += 1
                        exchange_stats[buy_ex]['total_profit'] += net_profit / 2
                        exchange_stats[buy_ex]['last_signal'] = current_time
                        exchange_stats[sell_ex]['sell_count'] += 1
                        exchange_stats[sell_ex]['total_profit'] += net_profit / 2
                        exchange_stats[sell_ex]['last_signal'] = current_time
                        
                        # Отправка сигнала
                        msg = format_signal(
                            coin, buy_ex, sell_ex, p_buy, p_sell,
                            b_fee_trade, s_fee_trade, net_info,
                            net_profit, net_spread
                        )
                        
                        try:
                            m = await bot.send_message(
                                chat_id=CHAT_ID, text=msg, 
                                parse_mode="Markdown", disable_web_page_preview=True
                            )
                            active_spreads[key] = {
                                'message_id': m.message_id,
                                'coin': coin, 'buy_ex': buy_ex, 'sell_ex': sell_ex,
                                'network': net_info['network'], 'created_at': current_time
                            }
                            detected_candidates.pop(key, None)
                            logger.info(f"✅ СИГНАЛ: {coin} {buy_ex}→{sell_ex} | спред: {net_spread:.2f}% | профит: ${net_profit:.2f}")
                        except Exception as e:
                            logger.error(f"Ошибка отправки: {e}")
        
        # Очистка старых кандидатов
        for k in list(detected_candidates.keys()):
            if k not in fresh_keys:
                del detected_candidates[k]
        
        # Удаление неактивных спредов
        to_remove = []
        for k, data in list(active_spreads.items()):
            if k not in fresh_keys:
                last_seen = spread_last_seen.get(k, 0)
                if current_time - last_seen > 60:  # 60 секунд без появления
                    to_remove.append(k)
        
        for k in to_remove:
            try:
                await bot.delete_message(chat_id=CHAT_ID, message_id=active_spreads[k]['message_id'])
                logger.info(f"🗑️ Удалён спред {active_spreads[k]['coin']}")
            except Exception as e:
                logger.error(f"Ошибка удаления: {e}")
            finally:
                active_spreads.pop(k, None)
                spread_last_seen.pop(k, None)
                detected_candidates.pop(k, None)
        
        scan_time = time.time() - scan_start
        logger.info(f"✅ Скан #{scan_count} за {scan_time:.1f}с | Найдено спредов: {len(active_spreads)}")
        
        await asyncio.sleep(15)

# ========== ЗАПУСК ==========
async def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("active", active_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    # Запускаем сканер в фоне
    asyncio.create_task(scan_all_markets())
    
    # Запускаем бота
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
    # Держим бота живым
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

if __name__ == '__main__':
    asyncio.run(main())
