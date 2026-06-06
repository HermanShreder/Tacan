import asyncio
import ccxt.async_support as ccxt
import logging
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import time
from datetime import datetime
from collections import defaultdict
import json

# === НАСТРОЙКИ ===
TELEGRAM_TOKEN = "5814224378:AAHlkQ41I-uQ9XXe_jmn5G28Q2x6nXCVNM8"
CHAT_ID = "5253808709"

EXCHANGE_KEYS = {
    'gate': {'apiKey': '5d80677222f36e38d07d92f317e45674', 'secret': '1a4d3c051cb523364b540e87361435a096b20dc51d96df9a91eaf03c6ad55c13'},
    'huobi': {'apiKey': '29d9fe7e-4b147f7f-dbuqg6hkte-0a894', 'secret': 'b0925bb5-07815986-b85bf68f-558a5'},
    'binance': {'apiKey': 'UvxQH98mpFgMRLM0ImIhBBohS3Pl86hVzDifpOUbmkRbDje6nZ0d74bB6oJLSFKt', 'secret': 'C7LOcLQBBNsF8LWTabxy7sul8mC79pcsbEzlb518rnCE2O4FzejnvZa0j04ZoiEB'},
}

TRADE_SIZE_USD = 500
LIQUIDITY_CHECK_USD = 1000
MIN_SPREAD_PCT = 0.5
MAX_SPREAD_PCT = 200.0
MIN_VOLUME_USD = 50000
MAX_WITHDRAWAL_TIME_MIN = 60

BLACKLIST_COINS = {'KEY', 'STAR', 'BOND', 'MIRA', 'WILD', 'MAGIC', 'NATIVE'}
BLACKLIST_NETWORKS = {'BSV': {'reason': 'very slow'}, 'BCH': {'reason': 'unstable'}}

NETWORKS_INFO = {
    'SOL': {'time_min': 0.03, 'time_max': 0.08, 'fee': 0.0005, 'speed': '⚡️⚡️⚡️', 'recommended': True},
    'XLM': {'time_min': 0.05, 'time_max': 0.08, 'fee': 0.0001, 'speed': '⚡️⚡️⚡️', 'recommended': True},
    'XRP': {'time_min': 0.07, 'time_max': 0.17, 'fee': 0.0005, 'speed': '⚡️⚡️⚡️', 'recommended': True},
    'BEP20': {'time_min': 1, 'time_max': 3, 'fee': 0.02, 'speed': '🟢', 'recommended': True},
    'BSC': {'time_min': 1, 'time_max': 3, 'fee': 0.02, 'speed': '🟢', 'recommended': True},
    'ERC20': {'time_min': 5, 'time_max': 15, 'fee': 8.0, 'speed': '🔴', 'recommended': False},
    'TRC20': {'time_min': 1, 'time_max': 3, 'fee': 1.50, 'speed': '🟢', 'recommended': True},
    'MATIC': {'time_min': 1, 'time_max': 3, 'fee': 0.02, 'speed': '🟢', 'recommended': True},
    'ARB': {'time_min': 1, 'time_max': 2, 'fee': 0.02, 'speed': '🟢', 'recommended': True},
    'OP': {'time_min': 1, 'time_max': 2, 'fee': 0.02, 'speed': '🟢', 'recommended': True},
    'DOGE': {'time_min': 2, 'time_max': 5, 'fee': 0.5, 'speed': '🟡', 'recommended': True},
    'XMR': {'time_min': 10, 'time_max': 30, 'fee': 0.05, 'speed': '🟡', 'recommended': False},
}

# Глобальные переменные
exchange_stats = defaultdict(lambda: {'buy_count': 0, 'sell_count': 0, 'total_profit': 0, 'last_signal': 0})
detected_candidates = {}
active_spreads = {}
spread_last_seen = {}
stats_message_id = None
stats_chat_id = None

bot = Bot(token=TELEGRAM_TOKEN)
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def get_network_info(network_name):
    net = network_name.upper()
    for key, info in NETWORKS_INFO.items():
        if key.upper() == net or net in key.upper():
            return {**info, 'network': key}
    return {'time_min': 5, 'time_max': 15, 'fee': 0.5, 'speed': '❓', 'recommended': False, 'network': network_name}

def generate_deeplink(exchange, coin):
    """Deeplinks: приложения где возможно, для HTX/Huobi — браузер"""
    pair = f"{coin}_USDT".upper()
    lower_coin = coin.lower()

    links = {
        'bitget': f"bitget://spot/{pair}",
        'gate': f"gateio://trade/{pair}",
        'kucoin': f"kucoin://trade/{pair}",
        'poloniex': f"poloniex://trade/{pair}",
        'binance': f"binance://trade/{pair}",
        'bybit': f"bybitapp://open/trade/spot?symbol={coin}USDT",
        'okx': f"okx://web/trade?symbol={coin}-USDT",
        'mexc': f"mexc://trade/{pair}",
        'bingx': f"bingx://spot/{pair}",
        'huobi': f"https://www.htx.com/trade/{lower_coin}_usdt",
        'htx': f"https://www.htx.com/trade/{lower_coin}_usdt",
        'kraken': f"https://www.kraken.com/prices/{lower_coin}",
        'coinbase': f"https://www.coinbase.com/price/{lower_coin}",
        'bitfinex': f"https://trading.bitfinex.com/t/{coin}:UST",
        'bitmart': f"https://www.bitmart.com/trade/en?symbol={pair}",
        'lbank': f"https://www.lbank.com/trade/{lower_coin}_usdt",
        'ascendex': f"https://ascendex.com/en/basic/cashtrade-spottrading/usdt/{lower_coin}",
        'coinex': f"https://www.coinex.com/exchange/{lower_coin}-usdt",
        'whitebit': f"https://whitebit.com/trade/{pair}",
        'bitrue': f"https://www.bitrue.com/trade/{lower_coin}_usdt",
        'phemex': f"https://phemex.com/spot/trade/{pair}",
        'hitbtc': f"https://hitbtc.com/{pair}",
        'exmo': f"https://exmo.com/en/trade/{pair}"
    }
    return links.get(exchange, f"https://{exchange}.com/trade/{coin}_USDT")

async def get_order_book_liquidity(exchange, symbol, side, required_usd):
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
    except:
        return None, 0, 0

async def check_common_network(buy_exchange, sell_exchange, coin):
    try:
        cur_buy = await buy_exchange.fetch_currencies()
        cur_sell = await sell_exchange.fetch_currencies()
        if coin not in cur_buy or coin not in cur_sell:
            return None
        buy_nets = cur_buy[coin].get('networks', {})
        sell_nets = cur_sell[coin].get('networks', {})
        common = []
        for net, binfo in buy_nets.items():
            if not binfo.get('withdraw'):
                continue
            bfee = float(binfo.get('fee', 0.5))
            if bfee == 0:
                continue
            for snet, sinfo in sell_nets.items():
                if snet.upper() == net.upper() or net.upper() in snet.upper() or snet.upper() in net.upper():
                    if not sinfo.get('deposit'):
                        continue
                    sfee = float(sinfo.get('fee', 0.5))
                    if sfee == 0:
                        continue
                    common.append({'network': net.upper(), 'buy_fee': bfee, 'sell_fee': sfee, 'total': bfee+sfee})
        if not common:
            return None
        common.sort(key=lambda x: x['total'])
        return common[0]
    except:
        return None

def format_signal(coin, buy_ex, sell_ex, p_buy, p_sell, buy_fee, sell_fee, net_info, net_profit, net_spread):
    link_buy = generate_deeplink(buy_ex, coin)
    link_sell = generate_deeplink(sell_ex, coin)
    net_details = get_network_info(net_info['network'])
    return (
        f"⚡️ **НАЙДЕН АРБИТРАЖНЫЙ СПРЕД: #{coin}** ⚡️\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 **ПОКУПКА: {buy_ex.upper()}**\n"
        f"├ 💵 Цена: `{p_buy:.8f} USDT`\n"
        f"├ 📊 Сумма: `${TRADE_SIZE_USD}`\n"
        f"└ 🔗 [Открыть в приложении]({link_buy})\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔴 **ПРОДАЖА: {sell_ex.upper()}**\n"
        f"├ 💵 Цена: `{p_sell:.8f} USDT`\n"
        f"└ 🔗 [Открыть в приложении]({link_sell})\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 **ОБЩАЯ СЕТЬ: {net_info['network']}**\n"
        f"├ 📤 Вывод ({buy_ex.upper()}): `${net_info['buy_fee']:.4f}`\n"
        f"├ 📥 Депозит ({sell_ex.upper()}): `${net_info['sell_fee']:.4f}`\n"
        f"├ ⏱ Время: {net_details['time_min']}-{net_details['time_max']} мин\n"
        f"└ 🏁 Скорость: {net_details['speed']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💸 **КОМИССИИ:**\n"
        f"├ 📊 Торговые: `${buy_fee + sell_fee:.2f}`\n"
        f"├ 📤 Вывод: `${net_info['buy_fee']:.2f}`\n"
        f"├ 📥 Депозит: `${net_info['sell_fee']:.2f}`\n"
        f"├ ─────────────────\n"
        f"└ **ИТОГО: `${buy_fee + sell_fee + net_info['buy_fee'] + net_info['sell_fee']:.2f}`**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💎 **ЧИСТАЯ ПРИБЫЛЬ:**\n"
        f"├ 📈 Чистый спред: **{net_spread:.2f}%**\n"
        f"└ 💰 Чистый профит: **+${net_profit:.2f}**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Вывод и депозит в ОДНОЙ сети: {net_info['network']}"
    )

def get_stats_message():
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
    return stats_msg

async def update_stats_message():
    global stats_message_id, stats_chat_id
    if not stats_message_id or not stats_chat_id:
        return
    try:
        stats_msg = get_stats_message()
        keyboard = [[InlineKeyboardButton("🔄 Обновить", callback_data='refresh_stats')]]
        await bot.edit_message_text(
            chat_id=stats_chat_id,
            message_id=stats_message_id,
            text=stats_msg,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Не удалось обновить статистику: {e}")

# ========== ТЕЛЕГРАМ КОМАНДЫ ==========
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global stats_message_id, stats_chat_id
    stats_msg = get_stats_message()
    keyboard = [[InlineKeyboardButton("🔄 Обновить", callback_data='refresh_stats')]]
    msg = await update.message.reply_text(
        stats_msg,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    stats_message_id = msg.message_id
    stats_chat_id = update.message.chat_id

    await update.message.reply_text(
        "✅ **Арбитражный бот запущен**\n\n"
        "📌 Проверка ликвидности на $1000\n"
        "📌 Спред удаляется при исчезновении\n"
        "📌 Deeplinks для приложений (Huobi/HTX — браузер)\n\n"
        "📊 Статистика обновляется автоматически при каждом сигнале\n"
        "🔄 /active - Активные спреды\n"
        "📈 /stats - Показать статистику заново"
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global stats_message_id, stats_chat_id
    stats_msg = get_stats_message()
    keyboard = [[InlineKeyboardButton("🔄 Обновить", callback_data='refresh_stats')]]
    msg = await update.message.reply_text(
        stats_msg,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    stats_message_id = msg.message_id
    stats_chat_id = update.message.chat_id

async def active_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not active_spreads:
        await update.message.reply_text("🔍 Нет активных спредов в данный момент")
        return
    msg = "🔄 **АКТИВНЫЕ СПРЕДЫ:**\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    for key, data in list(active_spreads.items())[:10]:
        age = int(time.time() - data.get('created_at', time.time()))
        msg += f"├ {data['coin']}: {data['buy_ex']} → {data['sell_ex']}\n"
        msg += f"├   Сеть: {data.get('network', '?')} | {age} сек назад\n"
        msg += f"└━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == 'refresh_stats':
        stats_msg = get_stats_message()
        keyboard = [[InlineKeyboardButton("🔄 Обновить", callback_data='refresh_stats')]]
        await query.edit_message_text(
            stats_msg,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

# ========== ОСНОВНОЙ СКАНЕР ==========
async def scan_all_markets():
    logger.info("="*50)
    logger.info("ЗАПУСК АРБИТРАЖНОГО БОТА")
    logger.info("="*50)
    
    exchanges = {}
    exchange_list = [
        'binance', 'bybit', 'okx', 'gate', 'kucoin', 'bitget', 'mexc',
        'bingx', 'htx', 'kraken', 'coinbase', 'huobi', 'poloniex',
        'hitbtc', 'exmo', 'bitfinex', 'bitmart', 'lbank', 'ascendex',
        'coinex', 'whitebit', 'bitrue', 'phemex'
    ]
    
    for ex_id in exchange_list:
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
            logger.info(f"✅ Загружена: {ex_id}")
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
                    if '/USDT' not in sym or sym.startswith('USDC'):
                        continue
                    coin = sym.split('/')[0]
                    if coin in BLACKLIST_COINS:
                        continue
                    try:
                        vol = t.get('quoteVolume')
                        bid = t.get('bid')
                        ask = t.get('ask')
                        if None in (vol, bid, ask):
                            continue
                        vol = float(vol)
                        bid = float(bid)
                        ask = float(ask)
                        if vol >= MIN_VOLUME_USD and bid > 0 and ask > 0:
                            all_tickers.setdefault(sym, {})[ex_id] = {'bid': bid, 'ask': ask}
                    except (ValueError, TypeError):
                        continue
            except:
                pass
        
        await asyncio.gather(*(fetch_ticker(eid, ex) for eid, ex in exchanges.items()))
        
        fresh_keys = set()
        logger.info(f"🔄 Скан #{scan_count}: {len(all_tickers)} монет, {len(exchanges)} бирж")
        
        for symbol, data in all_tickers.items():
            coin = symbol.split('/')[0]
            if len(data) < 2:
                continue
            
            buy_list = sorted(data.items(), key=lambda x: x[1]['ask'])[:5]
            sell_list = sorted(data.items(), key=lambda x: x[1]['bid'], reverse=True)[:5]
            
            for buy_ex, buy_d in buy_list:
                for sell_ex, sell_d in sell_list:
                    if buy_ex == sell_ex:
                        continue
                    
                    raw_spread = (sell_d['bid'] - buy_d['ask']) / buy_d['ask'] * 100
                    if raw_spread < MIN_SPREAD_PCT or raw_spread > MAX_SPREAD_PCT:
                        continue
                    
                    net_info = await check_common_network(exchanges[buy_ex], exchanges[sell_ex], coin)
                    if not net_info:
                        continue
                    
                    key = f"{coin}_{buy_ex}_{sell_ex}_{net_info['network']}"
                    fresh_keys.add(key)
                    spread_last_seen[key] = current_time
                    
                    if key in active_spreads:
                        continue
                    if key in detected_candidates:
                        if current_time - detected_candidates[key] < 60:
                            continue
                    if key not in detected_candidates:
                        detected_candidates[key] = current_time
                        continue
                    
                    p_buy, _, buy_fee = await get_order_book_liquidity(exchanges[buy_ex], symbol, 'buy', LIQUIDITY_CHECK_USD)
                    p_sell, _, sell_fee = await get_order_book_liquidity(exchanges[sell_ex], symbol, 'sell', LIQUIDITY_CHECK_USD)
                    if not p_buy or not p_sell:
                        continue
                    
                    taker_buy = exchanges[buy_ex].market(symbol).get('taker', 0.003)
                    taker_sell = exchanges[sell_ex].market(symbol).get('taker', 0.003)
                    b_fee_trade = TRADE_SIZE_USD * taker_buy
                    s_fee_trade = TRADE_SIZE_USD * taker_sell
                    
                    total_fees = b_fee_trade + s_fee_trade + net_info['buy_fee'] + net_info['sell_fee']
                    gross = ((TRADE_SIZE_USD / p_buy) * p_sell - TRADE_SIZE_USD)
                    net_profit = gross - total_fees
                    net_spread = (net_profit / TRADE_SIZE_USD) * 100
                    
                    if net_spread >= MIN_SPREAD_PCT:
                        exchange_stats[buy_ex]['buy_count'] += 1
                        exchange_stats[buy_ex]['total_profit'] += net_profit / 2
                        exchange_stats[buy_ex]['last_signal'] = current_time
                        exchange_stats[sell_ex]['sell_count'] += 1
                        exchange_stats[sell_ex]['total_profit'] += net_profit / 2
                        exchange_stats[sell_ex]['last_signal'] = current_time
                        
                        await update_stats_message()
                        
                        msg = format_signal(coin, buy_ex, sell_ex, p_buy, p_sell,
                                           b_fee_trade, s_fee_trade, net_info,
                                           net_profit, net_spread)
                        try:
                            m = await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown", disable_web_page_preview=True)
                            active_spreads[key] = {
                                'message_id': m.message_id,
                                'coin': coin,
                                'buy_ex': buy_ex,
                                'sell_ex': sell_ex,
                                'network': net_info['network'],
                                'created_at': current_time
                            }
                            detected_candidates.pop(key, None)
                            logger.info(f"✅ СИГНАЛ: {coin} {buy_ex}→{sell_ex} | спред: {net_spread:.2f}% | профит: ${net_profit:.2f}")
                        except Exception as e:
                            logger.error(f"Ошибка отправки: {e}")
        
        for k in list(detected_candidates.keys()):
            if k not in fresh_keys:
                del detected_candidates[k]
        
        to_remove = []
        for k, data in list(active_spreads.items()):
            if k not in fresh_keys:
                last_seen = spread_last_seen.get(k, 0)
                if current_time - last_seen > 45:
                    to_remove.append(k)
        
        for k in to_remove:
            try:
                await bot.delete_message(chat_id=CHAT_ID, message_id=active_spreads[k]['message_id'])
                logger.info(f"🗑️ Удалён спред {active_spreads[k]['coin']}")
            except:
                pass
            active_spreads.pop(k, None)
            spread_last_seen.pop(k, None)
            detected_candidates.pop(k, None)
        
        scan_time = time.time() - scan_start
        logger.info(f"✅ Скан #{scan_count} завершён за {scan_time:.1f}с | Активных спредов: {len(active_spreads)}")
        
        await asyncio.sleep(15)

# ========== ЗАПУСК ==========
async def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("active", active_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    asyncio.create_task(scan_all_markets())
    
    logger.info("🚀 Запуск Telegram бота...")
    await app.run_polling()

if __name__ == '__main__':
    asyncio.run(main())
