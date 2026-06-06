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

EXCHANGE_KEYS = {
    'gate': {'apiKey': '5d80677222f36e38d07d92f317e45674', 'secret': '1a4d3c051cb523364b540e87361435a096b20dc51d96df9a91eaf03c6ad55c13'},
    'huobi': {'apiKey': '29d9fe7e-4b147f7f-dbuqg6hkte-0a894', 'secret': 'b0925bb5-07815986-b85bf68f-558a5'},
    'binance': {'apiKey': 'UvxQH98mpFgMRLM0ImIhBBohS3Pl86hVzDifpOUbmkRbDje6nZ0d74bB6oJLSFKt', 'secret': 'C7LOcLQBBNsF8LWTabxy7sul8mC79pcsbEzlb518rnCE2O4FzejnvZa0j04ZoiEB'},
}

TRADE_SIZE_USD = 500
LIQUIDITY_CHECK_USD = 1000
MIN_SPREAD_PCT = 0.45
MAX_SPREAD_PCT = 200.0
MIN_VOLUME_USD = 50000

BLACKLIST_COINS = {'KEY', 'STAR', 'BOND', 'MIRA', 'WILD', 'MAGIC', 'NATIVE'}
BLACKLIST_NETWORKS = {'BSV', 'BCH'}

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
currency_cache = {}
markets_cache = {}
stats_message_id = None
stats_chat_id = None

bot = Bot(token=TELEGRAM_TOKEN)
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def get_network_info(network_name):
    net = network_name.upper()
    for key, info in NETWORKS_INFO.items():
        if key.upper() == net or net in key.upper() or key.upper() in net:
            return {**info, 'network': key}
    return {'time_min': 5, 'time_max': 15, 'fee': 0.5, 'speed': '❓', 'recommended': False, 'network': network_name}

def generate_deeplink(exchange, coin):
    pair = f"{coin}_USDT".upper()
    lower_coin = coin.lower()
    links = {
        'binance': f"binance://trade/{pair}",
        'bybit': f"bybitapp://open/trade/spot?symbol={coin}USDT",
        'okx': f"okx://web/trade?symbol={coin}-USDT",
        'gate': f"gateio://trade/{pair}",
        'huobi': f"https://www.htx.com/trade/{lower_coin}_usdt",
        'htx': f"https://www.htx.com/trade/{lower_coin}_usdt",
        # добавь остальные по необходимости
    }
    return links.get(exchange, f"https://{exchange}.com/trade/{coin}_USDT")

async def get_order_book_liquidity(exchange, symbol, side, required_usd):
    try:
        orderbook = await exchange.fetch_order_book(symbol, limit=50)
        orders = orderbook['asks'] if side == 'buy' else orderbook['bids']
        if not orders:
            return None, 0, 0

        total_cost = 0.0
        total_amount = 0.0
        for price, volume in orders[:40]:
            level_usd = float(price) * float(volume)
            if total_cost + level_usd >= required_usd:
                need = required_usd - total_cost
                total_amount += need / float(price)
                total_cost += need
                break
            total_amount += float(volume)
            total_cost += level_usd

        if total_cost < required_usd * 0.85:
            return None, 0, 0

        avg_price = total_cost / total_amount
        taker_fee = exchange.market(symbol).get('taker', 0.002)
        fee_usd = total_cost * taker_fee
        return avg_price, total_cost, fee_usd
    except Exception as e:
        logger.debug(f"Liquidity fail {exchange.id} {symbol} {side}: {e}")
        return None, 0, 0

async def fetch_currencies_safe(exchange):
    if exchange.id in currency_cache and time.time() - currency_cache[exchange.id]['ts'] < 600:
        return currency_cache[exchange.id]['data']
    try:
        currencies = await exchange.fetch_currencies()
        currency_cache[exchange.id] = {'data': currencies, 'ts': time.time()}
        return currencies
    except Exception as e:
        logger.warning(f"fetch_currencies fail {exchange.id}: {e}")
        return currency_cache.get(exchange.id, {}).get('data', {})

async def check_common_network(buy_exchange, sell_exchange, coin):
    try:
        cur_buy = await fetch_currencies_safe(buy_exchange)
        cur_sell = await fetch_currencies_safe(sell_exchange)
        
        if not cur_buy or coin not in cur_buy or coin not in cur_sell:
            return None

        def extract_networks(curr_info):
            nets = curr_info.get('networks') or curr_info.get('info', {}).get('networks', {}) or curr_info.get('networkList', [])
            if isinstance(nets, list):
                return {str(n.get('network') or n.get('chain') or n.get('id') or n.get('code') or '').upper(): n for n in nets if n}
            if isinstance(nets, dict):
                return {str(k).upper(): v for k, v in nets.items()}
            return {}

        buy_nets = extract_networks(cur_buy[coin])
        sell_nets = extract_networks(cur_sell[coin])

        common = []
        for bnet_name, binfo in buy_nets.items():
            if not binfo:
                continue
            withdraw_enabled = (
                binfo.get('withdraw') is True or 
                str(binfo.get('withdrawEnable') or binfo.get('withdraw', '')).lower() in ('true', '1', 'yes', 'enabled', 'ok')
            )
            if not withdraw_enabled:
                continue

            bfee = float(binfo.get('withdrawFee') or binfo.get('fee') or binfo.get('withdraw_fee') or 0.5)

            for snet_name, sinfo in sell_nets.items():
                if str(bnet_name).upper() != str(snet_name).upper():
                    continue
                deposit_enabled = (
                    sinfo.get('deposit') is True or 
                    str(sinfo.get('depositEnable') or sinfo.get('deposit', '')).lower() in ('true', '1', 'yes', 'enabled', 'ok')
                )
                if not deposit_enabled:
                    continue

                sfee = float(sinfo.get('depositFee') or sinfo.get('fee') or sinfo.get('deposit_fee') or 0.5)

                common.append({
                    'network': bnet_name,
                    'buy_fee': bfee,
                    'sell_fee': sfee,
                    'total': bfee + sfee,
                    'withdraw_enabled': True,
                    'deposit_enabled': True
                })

        if not common:
            return None
        common.sort(key=lambda x: x['total'])
        return common[0]

    except Exception as e:
        logger.debug(f"Net check fail {coin} {buy_exchange.id}-{sell_exchange.id}: {e}")
        return None

def format_signal(coin, buy_ex, sell_ex, p_buy, p_sell, buy_fee, sell_fee, net_info, net_profit, net_spread, volume):
    link_buy = generate_deeplink(buy_ex, coin)
    link_sell = generate_deeplink(sell_ex, coin)
    net_details = get_network_info(net_info['network'])
    return (
        f"⚡️ **АРБИТРАЖ #{coin}** ⚡️\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 **BUY {buy_ex.upper()}**\n"
        f"├ Цена: `{p_buy:.8f}`\n"
        f"├ Сумма: `${TRADE_SIZE_USD}`\n"
        f"└ [Открыть]({link_buy})\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔴 **SELL {sell_ex.upper()}**\n"
        f"├ Цена: `{p_sell:.8f}`\n"
        f"└ [Открыть]({link_sell})\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 **СЕТЬ {net_info['network']}** — ВЫВОД И ВВОД ОТКРЫТЫ ✅\n"
        f"├ 📤 Вывод: `${net_info.get('buy_fee', 0):.4f}`\n"
        f"├ 📥 Ввод: `${net_info.get('sell_fee', 0):.4f}`\n"
        f"├ ⏱ {net_details['time_min']}-{net_details['time_max']} мин\n"
        f"└ {net_details['speed']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 **VOLUME**: `${volume:,.0f}` USDT\n"
        f"💸 **КОМИССИИ**:\n"
        f"├ Торговые: `${buy_fee + sell_fee:.2f}`\n"
        f"├ Сеть: `${net_info.get('buy_fee',0) + net_info.get('sell_fee',0):.2f}`\n"
        f"└ **ИТОГО**: `${buy_fee + sell_fee + net_info.get('buy_fee',0) + net_info.get('sell_fee',0):.2f}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💎 **ПРИБЫЛЬ**: **+${net_profit:.2f}** ({net_spread:.2f}%)\n"
        f"✅ Реальный спред с ликвидностью"
    )

def get_stats_message():
    total_signals = sum(s['buy_count'] + s['sell_count'] for s in exchange_stats.values())
    total_profit = sum(s['total_profit'] for s in exchange_stats.values())
    stats_msg = "📊 **СТАТИСТИКА АРБИТРАЖА** 📊\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    stats_msg += f"🕐 {datetime.now().strftime('%H:%M:%S')}\n\n"
    stats_msg += f"Сигналов: **{total_signals}** | Профит: **${total_profit:.2f}**\n"
    stats_msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    stats_msg += "🟢 ПОКУПКА:\n"
    for ex, data in sorted(exchange_stats.items(), key=lambda x: x[1]['buy_count'], reverse=True)[:7]:
        if data['buy_count'] > 0:
            stats_msg += f"├ {ex.upper()}: {data['buy_count']}\n"
    stats_msg += "\n🔴 ПРОДАЖА:\n"
    for ex, data in sorted(exchange_stats.items(), key=lambda x: x[1]['sell_count'], reverse=True)[:7]:
        if data['sell_count'] > 0:
            stats_msg += f"├ {ex.upper()}: {data['sell_count']}\n"
    stats_msg += f"\n🔄 Активно: **{len(active_spreads)}**"
    return stats_msg

async def update_stats_message():
    global stats_message_id, stats_chat_id
    if not stats_message_id or not stats_chat_id:
        return
    try:
        stats_msg = get_stats_message()
        keyboard = [[InlineKeyboardButton("🔄 Обновить", callback_data='refresh_stats')]]
        await bot.edit_message_text(chat_id=stats_chat_id, message_id=stats_message_id, text=stats_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except:
        pass

# ========== КОМАНДЫ ==========
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global stats_message_id, stats_chat_id
    stats_msg = get_stats_message()
    keyboard = [[InlineKeyboardButton("🔄 Обновить", callback_data='refresh_stats')]]
    msg = await update.message.reply_text(stats_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    stats_message_id = msg.message_id
    stats_chat_id = update.message.chat_id
    await update.message.reply_text("✅ **БОТ ЗАПУЩЕН** — проверка сетей + ликвидность + объём")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global stats_message_id, stats_chat_id
    stats_msg = get_stats_message()
    keyboard = [[InlineKeyboardButton("🔄 Обновить", callback_data='refresh_stats')]]
    msg = await update.message.reply_text(stats_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    stats_message_id = msg.message_id
    stats_chat_id = update.message.chat_id

async def active_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not active_spreads:
        await update.message.reply_text("Нет активных")
        return
    msg = "🔄 **АКТИВНЫЕ:**\n"
    for key, data in list(active_spreads.items())[:15]:
        age = int(time.time() - data.get('created_at', time.time()))
        msg += f"{data['coin']} | {data['buy_ex']}→{data['sell_ex']} | {data.get('network')} | {age}s\n"
    await update.message.reply_text(msg)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == 'refresh_stats':
        stats_msg = get_stats_message()
        keyboard = [[InlineKeyboardButton("🔄 Обновить", callback_data='refresh_stats')]]
        await query.edit_message_text(stats_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ========== СКАНЕР ==========
async def scan_all_markets():
    logger.info("=== АРБИТРАЖ БОТ ЗАПУЩЕН — ПОЛНАЯ ВЕРСИЯ ===")
   
    exchanges = {}
    exchange_list = ['binance', 'bybit', 'okx', 'gate', 'kucoin', 'bitget', 'mexc', 'bingx', 'htx', 'huobi',
                     'kraken', 'poloniex', 'hitbtc', 'exmo', 'bitfinex', 'bitmart', 'lbank', 'ascendex',
                     'coinex', 'whitebit', 'bitrue', 'phemex']

    for ex_id in exchange_list:
        try:
            ex_class = getattr(ccxt, ex_id)
            config = {'enableRateLimit': True, 'timeout': 25000}
            if ex_id in EXCHANGE_KEYS:
                config.update(EXCHANGE_KEYS[ex_id])
            if ex_id in ['binance', 'bybit', 'okx', 'htx', 'huobi']:
                config.setdefault('options', {})['defaultType'] = 'spot'
            instance = ex_class(config)
            await instance.load_markets()
            exchanges[ex_id] = instance
            logger.info(f"✅ {ex_id} загружена")
        except Exception as e:
            logger.warning(f"Пропущена {ex_id}: {str(e)[:70]}")

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
                    if '/USDT' not in sym or sym.startswith(('USDC', 'USDT')):
                        continue
                    coin = sym.split('/')[0]
                    if coin in BLACKLIST_COINS:
                        continue
                    vol = t.get('quoteVolume') or t.get('info', {}).get('quoteVolume') or 0
                    bid = t.get('bid')
                    ask = t.get('ask')
                    if None in (bid, ask) or float(vol) < MIN_VOLUME_USD:
                        continue
                    all_tickers.setdefault(sym, {})[ex_id] = {
                        'bid': float(bid),
                        'ask': float(ask),
                        'volume': float(vol)
                    }
            except:
                pass

        await asyncio.gather(*(fetch_ticker(eid, ex) for eid, ex in exchanges.items()), return_exceptions=True)

        fresh_keys = set()
        logger.info(f"Скан #{scan_count} | пар: {len(all_tickers)}")

        for symbol, data in all_tickers.items():
            coin = symbol.split('/')[0]
            if len(data) < 2:
                continue

            buy_list = sorted(data.items(), key=lambda x: x[1]['ask'])[:8]
            sell_list = sorted(data.items(), key=lambda x: x[1]['bid'], reverse=True)[:8]

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
                    if key in detected_candidates and current_time - detected_candidates[key] < 40:
                        continue
                    if key not in detected_candidates:
                        detected_candidates[key] = current_time
                        continue

                    p_buy, _, buy_fee_trade = await get_order_book_liquidity(exchanges[buy_ex], symbol, 'buy', LIQUIDITY_CHECK_USD)
                    p_sell, _, sell_fee_trade = await get_order_book_liquidity(exchanges[sell_ex], symbol, 'sell', LIQUIDITY_CHECK_USD)
                    if not p_buy or not p_sell:
                        continue

                    b_fee_trade = TRADE_SIZE_USD * exchanges[buy_ex].market(symbol).get('taker', 0.002)
                    s_fee_trade = TRADE_SIZE_USD * exchanges[sell_ex].market(symbol).get('taker', 0.002)
                    total_fees = b_fee_trade + s_fee_trade + net_info['buy_fee'] + net_info['sell_fee']
                    gross = ((TRADE_SIZE_USD / p_buy) * p_sell - TRADE_SIZE_USD)
                    net_profit = gross - total_fees
                    net_spread = (net_profit / TRADE_SIZE_USD) * 100

                    if net_spread >= MIN_SPREAD_PCT:
                        exchange_stats[buy_ex]['buy_count'] += 1
                        exchange_stats[buy_ex]['total_profit'] += net_profit / 2
                        exchange_stats[sell_ex]['sell_count'] += 1
                        exchange_stats[sell_ex]['total_profit'] += net_profit / 2
                        await update_stats_message()

                        volume = max(buy_d.get('volume', 0), sell_d.get('volume', 0))
                        msg = format_signal(coin, buy_ex, sell_ex, p_buy, p_sell, b_fee_trade, s_fee_trade, net_info, net_profit, net_spread, volume)
                        m = await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown", disable_web_page_preview=True)
                        active_spreads[key] = {'message_id': m.message_id, 'coin': coin, 'buy_ex': buy_ex, 'sell_ex': sell_ex, 'network': net_info['network'], 'created_at': current_time}
                        detected_candidates.pop(key, None)
                        logger.info(f"СИГНАЛ {coin} {buy_ex}→{sell_ex} {net_spread:.2f}% +${net_profit:.2f}")

        # Очистка старья
        for k in list(detected_candidates.keys()):
            if k not in fresh_keys:
                detected_candidates.pop(k, None)
        to_remove = [k for k, d in active_spreads.items() if k not in fresh_keys and current_time - spread_last_seen.get(k, 0) > 55]
        for k in to_remove:
            try:
                await bot.delete_message(chat_id=CHAT_ID, message_id=active_spreads[k]['message_id'])
            except:
                pass
            active_spreads.pop(k, None)
            spread_last_seen.pop(k, None)

        logger.info(f"Скан #{scan_count} done {time.time()-scan_start:.1f}s | active: {len(active_spreads)}")
        await asyncio.sleep(11)

async def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("active", active_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    asyncio.create_task(scan_all_markets())
    await app.run_polling()

if __name__ == '__main__':
    asyncio.run(main())
