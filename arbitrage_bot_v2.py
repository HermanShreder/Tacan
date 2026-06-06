#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ULTIMATE ARBITRAGE SPREAD SCANNER v2026 - GROK UNDERGROUND GOD MODE
Improved: Strict withdraw + deposit OPEN check (with fallback to 'info' fields)
Only signals pairs where BOTH withdraw and deposit are confirmed OPEN
Clear status labels in every signal: Ввод открыт / Вывод закрыт etc.
Profit calculated strictly from orderbook executable prices.
"""

import asyncio
import ccxt.async_support as ccxt
import logging
import time
from datetime import datetime
from collections import defaultdict
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# === НАСТРОЙКИ ===
TELEGRAM_TOKEN = "5814224378:AAHlkQ41I-uQ9XXe_jmn5G28Q2x6nXCVNM8"
CHAT_ID = "5253808709"

EXCHANGE_KEYS = {
    'gate': {'apiKey': '5d80677222f36e38d07d92f317e45674', 'secret': '1a4d3c051cb523364b540e87361435a096b20dc51d96df9a91eaf03c6ad55c13'},
    'huobi': {'apiKey': '29d9fe7e-4b147f7f-dbuqg6hkte-0a894', 'secret': 'b0925bb5-07815986-b85bf68f-558a5'},
    'binance': {'apiKey': 'UvxQH98mpFgMRLM0ImIhBBohS3Pl86hVzDifpOUbmkRbDje6nZ0d74bB6oJLSFKt', 'secret': 'C7LOcLQBBNsF8LWTabxy7sul8mC79pcsbEzlb518rnCE2O4FzejnvZa0j04ZoiEB'},
    'bitget': {
        'apiKey': 'bg_c425385453f54a25ed72a37f7498bfc5',
        'secret': '46401f612cd8fa387c091a97061962d1f07b31187681405df72b457b0a78f69a'
    },
    # Добавь свои ключи Bybit и OKX для лучших лимитов и более точной информации по сетям:
    # 'bybit': {'apiKey': 'YOUR_KEY', 'secret': 'YOUR_SECRET'},
    # 'okx': {'apiKey': 'YOUR_KEY', 'secret': 'YOUR_SECRET', 'password': 'YOUR_PASSPHRASE'},
}

TRADE_SIZE_USD = 500
LIQUIDITY_CHECK_USD = 1000
MIN_SPREAD_PCT = 0.5
MAX_SPREAD_PCT = 200.0
MIN_VOLUME_USD = 50000
BLACKLIST_COINS = {'KEY', 'STAR', 'BOND', 'MIRA', 'WILD', 'MAGIC', 'NATIVE'}

NETWORKS_INFO = {
    'SOL': {'time_min': 0.03, 'time_max': 0.08, 'fee': 0.0005, 'speed': '⚡'},
    'XLM': {'time_min': 0.05, 'time_max': 0.08, 'fee': 0.0001, 'speed': '⚡'},
    'XRP': {'time_min': 0.07, 'time_max': 0.17, 'fee': 0.0005, 'speed': '⚡'},
    'BEP20': {'time_min': 1, 'time_max': 3, 'fee': 0.02, 'speed': ''},
    'BSC': {'time_min': 1, 'time_max': 3, 'fee': 0.02, 'speed': ''},
    'ERC20': {'time_min': 5, 'time_max': 15, 'fee': 8.0, 'speed': ''},
    'TRC20': {'time_min': 1, 'time_max': 3, 'fee': 1.50, 'speed': ''},
    'MATIC': {'time_min': 1, 'time_max': 3, 'fee': 0.02, 'speed': ''},
    'ARB': {'time_min': 1, 'time_max': 2, 'fee': 0.02, 'speed': ''},
    'OP': {'time_min': 1, 'time_max': 2, 'fee': 0.02, 'speed': ''},
    'DOGE': {'time_min': 2, 'time_max': 5, 'fee': 0.5, 'speed': ''},
}

exchange_stats = defaultdict(lambda: {'buy_count': 0, 'sell_count': 0, 'total_profit': 0})
detected_candidates = {}
active_spreads = {}
spread_last_seen = {}
stats_message_id = None
stats_chat_id = None
bot = Bot(token=TELEGRAM_TOKEN)
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_network_info(network_name):
    network = network_name.upper()
    for key, info in NETWORKS_INFO.items():
        if key.upper() == network or network in key.upper():
            return {**info, 'network': key}
    return {'time_min': 5, 'time_max': 15, 'fee': 0.5, 'speed': '', 'network': network_name}

def generate_deeplink(exchange, coin):
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
        orderbook = await exchange.fetch_order_book(symbol, limit=50)
        orders = orderbook['asks'] if side == 'buy' else orderbook['bids']
        if not orders:
            return None, 0, 0
        try:
            taker_fee = exchange.market(symbol).get('taker', 0.001)
        except:
            taker_fee = 0.001
        total_cost, total_amount = 0.0, 0.0
        for price, volume in orders:
            level_usd = price * volume
            if total_cost + level_usd >= required_usd:
                needed = required_usd - total_cost
                total_amount += needed / price
                total_cost += needed
                break
            else:
                total_amount += volume
                total_cost += level_usd
        if total_cost < required_usd or total_amount == 0:
            return None, 0, 0
        avg_price = total_cost / total_amount
        fee_cost = required_usd * taker_fee
        return avg_price, total_cost, fee_cost
    except Exception as e:
        logger.debug(f"Orderbook error {exchange.id} {symbol}: {str(e)[:60]}")
        return None, 0, 0

async def check_common_network(buy_exchange, sell_exchange, coin):
    """
    УЛЬТРА-СТРОГАЯ ПРОВЕРКА ДЛЯ ВСЕХ БИРЖ (особенно Bitget)
    withdraw и deposit должны быть явно подтверждены как OPEN
    Приоритет: info.withdrawEnable / depositEnable (Bitget, Binance и др.)
    """
    def _is_open(net_info, direction):
        """Надёжное извлечение статуса для Bitget и других"""
        if not isinstance(net_info, dict):
            return False
        # 1. CCXT normalized
        val = net_info.get(direction)
        if val is True or (isinstance(val, str) and val.lower() in ('true', '1', 'yes')):
            return True
        # 2. Глубокий поиск в info (Bitget использует withdrawEnable / depositEnable)
        info = net_info.get('info') or {}
        if isinstance(info, dict):
            keys = []
            if direction == 'withdraw':
                keys = ['withdrawEnable', 'withdraw_enable', 'canWithdraw', 'can_withdraw', 'withdraw', 'enableWithdraw']
            else:
                keys = ['depositEnable', 'deposit_enable', 'canDeposit', 'can_deposit', 'deposit', 'enableDeposit']
            for k in keys:
                v = info.get(k)
                if v is True or (isinstance(v, str) and v.lower() in ('true', '1', 'yes')):
                    return True
                if isinstance(v, (int, float)) and v > 0:
                    return True
        return False

    try:
        if not buy_exchange.currencies or coin not in buy_exchange.currencies:
            await buy_exchange.fetch_currencies()
        if not sell_exchange.currencies or coin not in sell_exchange.currencies:
            await sell_exchange.fetch_currencies()

        buy_cur = buy_exchange.currencies.get(coin, {})
        sell_cur = sell_exchange.currencies.get(coin, {})

        buy_nets = buy_cur.get('networks', {}) or buy_cur.get('info', {}).get('networks', {})
        sell_nets = sell_cur.get('networks', {}) or sell_cur.get('info', {}).get('networks', {})

        common = []
        for bnet, binfo in buy_nets.items():
            b_withdraw = _is_open(binfo, 'withdraw')
            if not b_withdraw:
                continue

            bfee = float(binfo.get('fee', 0) or 0)

            for snet, sinfo in sell_nets.items():
                if bnet.upper() != snet.upper() and bnet.upper() not in snet.upper():
                    continue

                s_deposit = _is_open(sinfo, 'deposit')
                if s_deposit:
                    sfee = float(sinfo.get('fee', 0) or 0)
                    common.append({
                        'network': bnet.upper(),
                        'buy_fee': bfee,
                        'sell_fee': sfee,
                        'total': bfee + sfee,
                        'buy_withdraw_open': True,
                        'sell_deposit_open': True,
                        'is_fallback': False
                    })

        if common:
            common.sort(key=lambda x: x['total'])
            return common[0]

        return {
            'network': 'NO OPEN NETWORK',
            'buy_fee': 0, 'sell_fee': 0, 'total': 0,
            'buy_withdraw_open': False,
            'sell_deposit_open': False,
            'is_fallback': True
        }

    except Exception as e:
        logger.warning(f"Network check error for {coin}: {str(e)[:80]}")
        return {
            'network': 'ERROR',
            'buy_fee': 0, 'sell_fee': 0, 'total': 0,
            'buy_withdraw_open': False,
            'sell_deposit_open': False,
            'is_fallback': True
        }

def format_signal(coin, buy_ex, sell_ex, p_buy, p_sell, buy_fee, sell_fee, net_info, net_profit, net_spread):
    link_buy = generate_deeplink(buy_ex, coin)
    link_sell = generate_deeplink(sell_ex, coin)
    net_details = get_network_info(net_info['network'])

    # Чёткие статусы
    withdraw_status = "✅ ВЫВОД ОТКРЫТ" if net_info.get('buy_withdraw_open') else "❌ ВЫВОД ЗАКРЫТ"
    deposit_status = "✅ ВВОД ОТКРЫТ" if net_info.get('sell_deposit_open') else "❌ ВВОД ЗАКРЫТ"

    net_status = "✅ СЕТЬ ПОДТВЕРЖДЕНА" if not net_info.get('is_fallback') else "⚠️ РУЧНАЯ ПРОВЕРКА СЕТИ"

    return (
        f"🚨 АРБИТРАЖНЫЙ СПРЕД: #{coin} 🚨\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"**ПОКУПКА: {buy_ex.upper()}**\n"
        f"├ Цена (orderbook VWAP): `{p_buy:.8f} USDT`\n"
        f"├ Сумма: `${TRADE_SIZE_USD}`\n"
        f"└ [Открыть]({link_buy})\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"**ПРОДАЖА: {sell_ex.upper()}**\n"
        f"├ Цена (orderbook VWAP): `{p_sell:.8f} USDT`\n"
        f"└ [Открыть]({link_sell})\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"**СЕТЬ: {net_info['network']}**\n"
        f"├ {withdraw_status} ({buy_ex.upper()})\n"
        f"├ {deposit_status} ({sell_ex.upper()})\n"
        f"├ Комиссия вывода: ${net_info['buy_fee']:.2f}\n"
        f"├ Комиссия депозита: ${net_info['sell_fee']:.2f}\n"
        f"├ Время: {net_details.get('time_min', 5)}-{net_details.get('time_max', 15)} мин\n"
        f"└ {net_status}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"**ЧИСТАЯ ПРИБЫЛЬ (по ордерам):**\n"
        f"├ Чистый спред: **{net_spread:.2f}%**\n"
        f"└ Чистый профит: **+${net_profit:.2f}**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

def get_stats_message():
    total_signals = sum(s['buy_count'] + s['sell_count'] for s in exchange_stats.values())
    total_profit = sum(s['total_profit'] for s in exchange_stats.values())
    stats_msg = "📊 АРБИТРАЖНАЯ СТАТИСТИКА v2026\n"
    stats_msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    stats_msg += f"🕒 {datetime.now().strftime('%H:%M:%S')}\n\n"
    stats_msg += f"Сигналов: {total_signals} | Мат.прибыль: ${total_profit:.2f}\n"
    stats_msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    stats_msg += "**ТОП ДЛЯ ПОКУПКИ:**\n"
    for ex, data in sorted(exchange_stats.items(), key=lambda x: x[1]['buy_count'], reverse=True)[:5]:
        if data['buy_count'] > 0:
            stats_msg += f"├ {ex.upper()}: {data['buy_count']} раз\n"
    stats_msg += "\n**ТОП ДЛЯ ПРОДАЖИ:**\n"
    for ex, data in sorted(exchange_stats.items(), key=lambda x: x[1]['sell_count'], reverse=True)[:5]:
        if data['sell_count'] > 0:
            stats_msg += f"├ {ex.upper()}: {data['sell_count']} раз\n"
    stats_msg += f"\nАктивных связок: {len(active_spreads)}"
    return stats_msg

async def update_stats_message():
    global stats_message_id, stats_chat_id
    if not stats_message_id or not stats_chat_id:
        return
    try:
        await bot.edit_message_text(
            chat_id=stats_chat_id,
            message_id=stats_message_id,
            text=get_stats_message(),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Обновить", callback_data='refresh_stats')]]),
            parse_mode="Markdown"
        )
    except:
        pass

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global stats_message_id, stats_chat_id
    stats_msg = get_stats_message()
    keyboard = [[InlineKeyboardButton("🔄 Обновить", callback_data='refresh_stats')]]
    message = await update.message.reply_text(stats_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    stats_message_id = message.message_id
    stats_chat_id = update.message.chat_id
    await update.message.reply_text(
        "🚀 **Арбитражный бот v2026 — УЛУЧШЕННАЯ ВЕРСИЯ**\n\n"
        "✅ Только спреды где ВЫВОД и ВВОД ОТКРЫТЫ\n"
        "✅ Чёткие метки: ✅ ВЫВОД ОТКРЫТ / ❌ ВВОД ЗАКРЫТ\n"
        "✅ Расчёт прибыли строго по ордербуку\n"
        "✅ Binance / Bybit / OKX + 18 бирж\n\n"
        "/active — активные связки\n"
        "/stats — статистика"
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global stats_message_id, stats_chat_id
    message = await update.message.reply_text(get_stats_message(), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Обновить", callback_data='refresh_stats')]]), parse_mode="Markdown")
    stats_message_id = message.message_id
    stats_chat_id = update.message.chat_id

async def active_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not active_spreads:
        await update.message.reply_text("Нет активных связок")
        return
    msg = "📋 **АКТИВНЫЕ СПРЕДЫ (только с открытыми сетями):**\n"
    for key, data in list(active_spreads.items())[:8]:
        age = int(time.time() - data.get('created_at', time.time()))
        msg += f"├ {data['coin']}: {data['buy_ex'].upper()} → {data['sell_ex'].upper()} | {data.get('network')} | {age}с\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == 'refresh_stats':
        try:
            await query.edit_message_text(get_stats_message(), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Обновить", callback_data='refresh_stats')]]), parse_mode="Markdown")
        except:
            pass

# ========== СКАНЕР ==========

async def scan_all_markets():
    logger.info("=== GODMODE v2026 SCAN STARTED ===")
    
    exchanges = {}
    list_exchanges = ['binance', 'bybit', 'okx', 'gate', 'kucoin', 'bitget', 'mexc', 'bingx', 'htx', 'kraken', 'coinbase', 'huobi', 'poloniex', 'bitfinex', 'bitmart', 'lbank', 'ascendex', 'coinex', 'whitebit', 'bitrue', 'phemex']

    for ex_id in list_exchanges:
        try:
            ex_class = getattr(ccxt, ex_id)
            config = {'enableRateLimit': True, 'timeout': 25000, 'options': {'defaultType': 'spot'}}
            if ex_id in EXCHANGE_KEYS:
                config.update(EXCHANGE_KEYS[ex_id])
            if ex_id == 'binance':
                config['options']['adjustForTimeDifference'] = True
            instance = ex_class(config)
            await instance.load_markets()
            exchanges[ex_id] = instance
            logger.info(f"✅ {ex_id} подключена ({len(instance.markets)} markets)")
        except Exception as e:
            logger.warning(f"⚠️ Пропущена {ex_id}: {str(e)[:70]}")

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
                    vol = t.get('quoteVolume')
                    bid = t.get('bid')
                    ask = t.get('ask')
                    if vol is None or bid is None or ask is None:
                        continue
                    if float(vol) >= MIN_VOLUME_USD and float(bid) > 0 and float(ask) > 0:
                        all_tickers.setdefault(sym, {})[ex_id] = {'bid': float(bid), 'ask': float(ask)}
            except Exception as e:
                logger.debug(f"fetch_tickers {ex_id} error: {str(e)[:50]}")

        try:
            await asyncio.wait_for(
                asyncio.gather(*(fetch_ticker(eid, ex) for eid, ex in exchanges.items()), return_exceptions=True),
                timeout=50
            )
        except asyncio.TimeoutError:
            logger.warning("Partial scan (some exchanges slow)")

        fresh_keys = set()
        logger.info(f"Скан #{scan_count}: пар с объёмом = {len(all_tickers)}")

        for symbol, data in all_tickers.items():
            coin = symbol.split('/')[0]
            if len(data) < 2:
                continue

            buy_list = sorted(data.items(), key=lambda x: x[1]['ask'])[:3]
            sell_list = sorted(data.items(), key=lambda x: x[1]['bid'], reverse=True)[:3]

            for buy_ex, buy_d in buy_list:
                for sell_ex, sell_d in sell_list:
                    if buy_ex == sell_ex:
                        continue

                    raw_spread = (sell_d['bid'] - buy_d['ask']) / buy_d['ask'] * 100
                    if raw_spread < MIN_SPREAD_PCT or raw_spread > MAX_SPREAD_PCT:
                        continue

                    # === ГЛАВНАЯ ПРОВЕРКА ===
                    net_info = await check_common_network(exchanges[buy_ex], exchanges[sell_ex], coin)

                    # Пропускаем ВСЁ, если нет открытой сети для вывода+ввода
                    if net_info.get('is_fallback') or not net_info.get('buy_withdraw_open') or not net_info.get('sell_deposit_open'):
                        continue

                    key = f"{coin}_{buy_ex}_{sell_ex}_{net_info['network']}"
                    fresh_keys.add(key)
                    spread_last_seen[key] = current_time

                    if key in active_spreads:
                        continue
                    if key in detected_candidates and current_time - detected_candidates[key] < 90:
                        continue

                    # Реальные цены из ордербука
                    p_buy, _, _ = await get_order_book_liquidity(exchanges[buy_ex], symbol, 'buy', LIQUIDITY_CHECK_USD)
                    p_sell, _, _ = await get_order_book_liquidity(exchanges[sell_ex], symbol, 'sell', LIQUIDITY_CHECK_USD)
                    if not p_buy or not p_sell:
                        continue

                    try:
                        t_buy = exchanges[buy_ex].market(symbol).get('taker', 0.001)
                        t_sell = exchanges[sell_ex].market(symbol).get('taker', 0.001)
                    except:
                        t_buy = t_sell = 0.001

                    b_fee_trade = TRADE_SIZE_USD * t_buy
                    s_fee_trade = TRADE_SIZE_USD * t_sell
                    total_fees = b_fee_trade + s_fee_trade + net_info['buy_fee'] + net_info['sell_fee']

                    amount_bought = TRADE_SIZE_USD / p_buy
                    gross = amount_bought * p_sell - TRADE_SIZE_USD
                    net_profit = gross - total_fees
                    net_spread = (net_profit / TRADE_SIZE_USD) * 100

                    if net_spread >= MIN_SPREAD_PCT:
                        exchange_stats[buy_ex]['buy_count'] += 1
                        exchange_stats[buy_ex]['total_profit'] += net_profit / 2
                        exchange_stats[sell_ex]['sell_count'] += 1
                        exchange_stats[sell_ex]['total_profit'] += net_profit / 2

                        await update_stats_message()

                        message = format_signal(coin, buy_ex, sell_ex, p_buy, p_sell, b_fee_trade, s_fee_trade, net_info, net_profit, net_spread)

                        try:
                            m = await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="Markdown", disable_web_page_preview=True)
                            active_spreads[key] = {
                                'message_id': m.message_id, 'coin': coin,
                                'buy_ex': buy_ex, 'sell_ex': sell_ex,
                                'network': net_info['network'], 'created_at': current_time
                            }
                            detected_candidates[key] = current_time
                        except Exception as e:
                            logger.error(f"Send error: {e}")

        # Очистка
        for k in list(detected_candidates.keys()):
            if k not in fresh_keys:
                detected_candidates.pop(k, None)

        to_remove = [k for k, data in active_spreads.items() if k not in fresh_keys and current_time - spread_last_seen.get(k, 0) > 120]
        for k in to_remove:
            try:
                await bot.delete_message(chat_id=CHAT_ID, message_id=active_spreads[k]['message_id'])
            except:
                pass
            active_spreads.pop(k, None)
            spread_last_seen.pop(k, None)

        logger.info(f"Скан #{scan_count} завершён за {time.time()-scan_start:.1f}с | Активных: {len(active_spreads)}")
        await asyncio.sleep(60)

async def post_init(application: Application) -> None:
    asyncio.create_task(scan_all_markets())
    logger.info("Фоновая задача сканирования запущена.")

def main():
    application = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("active", active_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    logger.info("🚀 Telegram Polling запущен (GodMode v2026)")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
