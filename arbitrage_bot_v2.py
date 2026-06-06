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

TRADE_SIZE_USD = 500
MIN_SPREAD_PCT = 2.0
MAX_SPREAD_PCT = 100.0
MIN_VOLUME_USD = 10000

BLACKLIST_COINS = {'KEY', 'STAR', 'BOND', 'MIRA', 'WILD', 'MAGIC', 'NATIVE', 'USDC', 'USDT', 'DAI', 'BUSD'}

bot = Bot(token=TELEGRAM_TOKEN)
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Глобальные переменные
stats = defaultdict(lambda: {'buy': 0, 'sell': 0, 'profit': 0})
active_spreads = {}
stats_message_id = None
stats_chat_id = None

# ========== DEEPLINKS ДЛЯ ПРИЛОЖЕНИЙ ==========
def get_trade_url(exchange, coin):
    """Генерирует deeplinks для ОТКРЫТИЯ В ПРИЛОЖЕНИЯХ"""
    pair_upper = f"{coin}_USDT"
    coin_lower = coin.lower()
    
    deeplinks = {
        # Deeplinks для мобильных приложений
        'gate': f"gateio://trade/{pair_upper}",
        'kucoin': f"kucoin://trade/{pair_upper}",
        'bitget': f"bitget://spot/{pair_upper}",
        'mexc': f"mexc://trade/{pair_upper}",
        'bybit': f"bybitapp://open/trade/spot?symbol={coin}USDT",
        'okx': f"okx://web/trade?symbol={coin}-USDT",
        'binance': f"binance://trade/{pair_upper}",
        'poloniex': f"poloniex://trade/{pair_upper}",
        'bingx': f"bingx://spot/{pair_upper}",
        
        # Веб-ссылки (открываются в браузере если нет приложения)
        'htx': f"https://www.htx.com/trade/{coin_lower}_usdt",
        'bitmart': f"https://www.bitmart.com/trade/en?symbol={pair_upper}",
        'phemex': f"https://phemex.com/trade/spot/{pair_upper}",
        'coinex': f"https://www.coinex.com/exchange/{coin_lower}-usdt",
        'whitebit': f"https://whitebit.com/trade/{pair_upper}",
        'lbank': f"https://www.lbank.com/trade/{coin_lower}_usdt",
        'ascendex': f"https://ascendex.com/en/broker/trade/spot/{coin_lower}-USDT",
    }
    
    return deeplinks.get(exchange, f"https://www.{exchange}.com/trade/{pair_upper}")

# ========== ФОРМАТ СООБЩЕНИЯ ==========
def format_signal(coin, buy_ex, sell_ex, buy_price, sell_price, net_profit, spread):
    buy_url = get_trade_url(buy_ex, coin)
    sell_url = get_trade_url(sell_ex, coin)
    
    profit_emoji = "🟢" if net_profit > 10 else "🟡" if net_profit > 5 else "🔴"
    
    return (
        f"⚡️ **АРБИТРАЖ: {coin}** ⚡️\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 **КУПИТЬ: {buy_ex.upper()}**\n"
        f"💰 Цена: `{buy_price:.6f} USDT`\n"
        f"🔗 [Открыть в приложении]({buy_url})\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔴 **ПРОДАТЬ: {sell_ex.upper()}**\n"
        f"💰 Цена: `{sell_price:.6f} USDT`\n"
        f"🔗 [Открыть в приложении]({sell_url})\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{profit_emoji} **ПРИБЫЛЬ: +${net_profit:.2f}**\n"
        f"📈 **СПРЕД: {spread:.2f}%**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ **ПРОВЕРЬТЕ ВЫВОД/ДЕПОЗИТ ВРУЧНУЮ!**"
    )

def get_stats_message():
    """Генерирует сообщение со статистикой"""
    total_signals = sum(v['buy'] + v['sell'] for v in stats.values()) // 2
    total_profit = sum(v['profit'] for v in stats.values())
    
    msg = f"📊 **СТАТИСТИКА АРБИТРАЖА** 📊\n"
    msg += f"━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"🕐 {datetime.now().strftime('%H:%M:%S')}\n"
    msg += f"📡 Сигналов: {total_signals}\n"
    msg += f"💰 Профит: ${total_profit:.2f}\n"
    msg += f"🔄 Активных спредов: {len(active_spreads)}\n"
    msg += f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    msg += "🟢 **ГДЕ ДЕРЖАТЬ USDT (покупка):**\n"
    top_buy = sorted(stats.items(), key=lambda x: x[1]['buy'], reverse=True)[:5]
    has_buy = False
    for ex, data in top_buy:
        if data['buy'] > 0:
            msg += f"├ {ex.upper()}: {data['buy']} раз\n"
            has_buy = True
    if not has_buy:
        msg += "├ Пока нет данных...\n"
    
    msg += "\n🔴 **ГДЕ ДЕРЖАТЬ МОНЕТЫ (продажа):**\n"
    top_sell = sorted(stats.items(), key=lambda x: x[1]['sell'], reverse=True)[:5]
    has_sell = False
    for ex, data in top_sell:
        if data['sell'] > 0:
            msg += f"├ {ex.upper()}: {data['sell']} раз\n"
            has_sell = True
    if not has_sell:
        msg += "├ Пока нет данных...\n"
    
    return msg

async def update_stats_message():
    """Обновляет закрепленное сообщение со статистикой"""
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
        logger.error(f"Ошибка обновления статистики: {e}")

# ========== ОСНОВНАЯ ЛОГИКА ==========
async def scan_exchange(exchange, exchange_name, all_tickers):
    """Сканирует одну биржу и собирает тикеры"""
    try:
        tickers = await exchange.fetch_tickers()
        count = 0
        for symbol, data in tickers.items():
            if not symbol.endswith('/USDT') or 'USDC' in symbol:
                continue
            
            coin = symbol.replace('/USDT', '')
            if coin in BLACKLIST_COINS:
                continue
            
            vol = data.get('quoteVolume', 0)
            bid = data.get('bid', 0)
            ask = data.get('ask', 0)
            
            if vol and bid and ask and vol >= MIN_VOLUME_USD:
                all_tickers[symbol][exchange_name] = {
                    'bid': float(bid),
                    'ask': float(ask),
                    'vol': float(vol)
                }
                count += 1
        
        if count:
            logger.info(f"📊 {exchange_name}: {count} монет")
        return True
    except Exception as e:
        logger.warning(f"⚠️ {exchange_name} ошибка: {str(e)[:50]}")
        return False

async def get_order_book_liquidity(exchange, symbol, side, amount_usd):
    """Проверяет ликвидность стакана (покупка или продажа)"""
    try:
        orderbook = await exchange.fetch_order_book(symbol, limit=10)
        
        if side == 'buy':
            orders = orderbook['asks']
        else:
            orders = orderbook['bids']
        
        if not orders:
            return None, 0
        
        total_cost = 0
        total_amount = 0
        
        for price, volume in orders:
            level_cost = price * volume
            if total_cost + level_cost >= amount_usd:
                need = amount_usd - total_cost
                total_amount += need / price
                total_cost += need
                break
            else:
                total_amount += volume
                total_cost += level_cost
        
        if total_cost >= amount_usd * 0.95 and total_amount > 0:
            return total_cost / total_amount, total_cost
        return None, 0
    except:
        return None, 0

# ========== ТЕЛЕГРАМ БОТ С КНОПКОЙ ==========
async def telegram_bot():
    """Обработчик команд Telegram с кнопкой статистики"""
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        global stats_message_id, stats_chat_id
        
        # Отправляем статистику с кнопкой
        stats_msg = get_stats_message()
        keyboard = [[InlineKeyboardButton("🔄 Обновить", callback_data='refresh_stats')]]
        
        msg = await update.message.reply_text(
            stats_msg,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        
        stats_message_id = msg.message_id
        stats_chat_id = update.message.chat_id
        
        # Информационное сообщение
        await update.message.reply_text(
            "✅ **Арбитраж бот работает**\n\n"
            f"💰 Сумма сделки: ${TRADE_SIZE_USD}\n"
            f"📈 Мин. спред: {MIN_SPREAD_PCT}%\n"
            f"📊 Мин. объем: ${MIN_VOLUME_USD:,}\n\n"
            "📊 Статистика с кнопкой вверху\n"
            "🔄 /stats - Обновить статистику"
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
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
    # Держим бота живым
    while True:
        await asyncio.sleep(1)

# ========== ОСНОВНОЙ ЦИКЛ СКАНЕРА ==========
async def main_scanner():
    """Главный сканер арбитража"""
    logger.info("="*50)
    logger.info("ЗАПУСК АРБИТРАЖНОГО СКАНЕРА")
    logger.info(f"Сумма: ${TRADE_SIZE_USD}, мин. спред: {MIN_SPREAD_PCT}%")
    logger.info("="*50)
    
    # Расширенный список бирж
    exchange_list = [
        'gate', 'kucoin', 'bitget', 'mexc', 'htx', 
        'poloniex', 'bitmart', 'phemex', 'coinex', 'whitebit',
        'lbank', 'ascendex', 'bingx', 'bybit', 'okx'
    ]
    
    exchanges = {}
    for ex_id in exchange_list:
        try:
            ex_class = getattr(ccxt, ex_id)
            config = {'enableRateLimit': True, 'timeout': 15000}
            
            if ex_id in ['bybit', 'okx']:
                config['options'] = {'defaultType': 'spot'}
            
            instance = ex_class(config)
            await instance.load_markets()
            exchanges[ex_id] = instance
            logger.info(f"✅ Загружена: {ex_id}")
        except Exception as e:
            logger.warning(f"❌ Не загружена {ex_id}: {str(e)[:50]}")
    
    logger.info(f"✅ Загружено бирж: {len(exchanges)}")
    
    scan_count = 0
    
    while True:
        try:
            scan_start = time.time()
            scan_count += 1
            all_tickers = {}
            
            # Сбор данных со всех бирж
            tasks = [scan_exchange(ex, name, all_tickers) for name, ex in exchanges.items()]
            await asyncio.gather(*tasks)
            
            logger.info(f"🔄 Скан #{scan_count}: {len(all_tickers)} монет")
            
            found_signals = 0
            
            # Поиск спредов
            for symbol, markets in all_tickers.items():
                if len(markets) < 2:
                    continue
                
                coin = symbol.replace('/USDT', '')
                
                # Находим лучшую цену покупки (самый низкий ask)
                best_buy = min(markets.items(), key=lambda x: x[1]['ask'])
                # Находим лучшую цену продажи (самый высокий bid)
                best_sell = max(markets.items(), key=lambda x: x[1]['bid'])
                
                if best_buy[0] == best_sell[0]:
                    continue
                
                buy_price = best_buy[1]['ask']
                sell_price = best_sell[1]['bid']
                
                raw_spread = (sell_price - buy_price) / buy_price * 100
                
                if raw_spread < MIN_SPREAD_PCT or raw_spread > MAX_SPREAD_PCT:
                    continue
                
                # Проверяем ликвидность на бирже покупки
                buy_ex = exchanges.get(best_buy[0])
                if buy_ex:
                    avg_price, _ = await get_order_book_liquidity(buy_ex, symbol, 'buy', TRADE_SIZE_USD)
                    if avg_price:
                        buy_price = avg_price
                    else:
                        continue
                
                # Проверяем ликвидность на бирже продажи
                sell_ex = exchanges.get(best_sell[0])
                if sell_ex:
                    avg_price, _ = await get_order_book_liquidity(sell_ex, symbol, 'sell', TRADE_SIZE_USD)
                    if avg_price:
                        sell_price = avg_price
                    else:
                        continue
                
                # Расчет комиссий (0.2% на каждой бирже)
                buy_fee = TRADE_SIZE_USD * 0.002
                sell_fee = TRADE_SIZE_USD * 0.002
                
                # Валовая прибыль
                gross_profit = (TRADE_SIZE_USD / buy_price) * sell_price - TRADE_SIZE_USD
                
                # Чистая прибыль
                net_profit = gross_profit - buy_fee - sell_fee
                
                if net_profit < 1:
                    continue
                
                net_spread = (net_profit / TRADE_SIZE_USD) * 100
                
                if net_spread >= MIN_SPREAD_PCT:
                    # Обновляем статистику
                    stats[best_buy[0]]['buy'] += 1
                    stats[best_buy[0]]['profit'] += net_profit / 2
                    stats[best_sell[0]]['sell'] += 1
                    stats[best_sell[0]]['profit'] += net_profit / 2
                    
                    # Обновляем сообщение со статистикой
                    await update_stats_message()
                    
                    # Отправляем сигнал
                    msg = format_signal(
                        coin, best_buy[0], best_sell[0],
                        buy_price, sell_price, net_profit, net_spread
                    )
                    
                    try:
                        await bot.send_message(
                            chat_id=CHAT_ID,
                            text=msg,
                            parse_mode="Markdown",
                            disable_web_page_preview=True
                        )
                        found_signals += 1
                        logger.info(f"✅ СИГНАЛ: {coin} {best_buy[0]}→{best_sell[0]} | спред: {net_spread:.2f}% | профит: ${net_profit:.2f}")
                    except Exception as e:
                        logger.error(f"Ошибка отправки: {e}")
                    
                    await asyncio.sleep(2)
            
            scan_time = time.time() - scan_start
            logger.info(f"✅ Скан #{scan_count} за {scan_time:.1f}с | Сигналов: {found_signals}")
            
        except Exception as e:
            logger.error(f"Ошибка в сканере: {e}")
        
        await asyncio.sleep(15)

# ========== ЗАПУСК ==========
async def main():
    await asyncio.gather(
        main_scanner(),
        telegram_bot()
    )

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Бот остановлен")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
