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

# Логтау баптаулары
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Telegram баптаулары (Жаңа токен қойылды)
TELEGRAM_TOKEN = "5814224378:AAHlkQ41I-uQ9XXe_jmn5G28Q2x6nXCVNM8"
CHAT_ID = "5253808709"

# Сауда баптаулары
TRADE_SIZE_USD = 500
MIN_SPREAD_PCT = 0.3
MAX_SPREAD_PCT = 15.0   
MIN_VOLUME_USD = 100000 

# Монеталардың қара тізімі
BLACKLIST_COINS = {'KEY', 'STAR', 'BOND', 'MIRA', 'WILD', 'MAGIC', 'NATIVE'}

# Биржалар тізімі
EXCHANGES_LIST = [
    'binance', 'bybit', 'okx', 'gate', 'kucoin', 'bitget', 'mexc', 
    'bingx', 'htx', 'kraken', 'coinbase', 'huobi', 'poloniex', 
    'hitbtc', 'exmo', 'bitfinex', 'bitmart', 'lbank', 'ascendex',
    'coinex', 'whitebit', 'bitrue', 'phemex'
]

# Желілер туралы мәліметтер
NETWORKS_INFO = {
    'SOL': {'name': 'Solana', 'time_min': 0.03, 'time_max': 0.08, 'fee': 0.0005, 'speed': '⚡️⚡️⚡️', 'risk': 'low', 'recommended': True},
    'XLM': {'name': 'Stellar', 'time_min': 0.05, 'time_max': 0.08, 'fee': 0.0001, 'speed': '⚡️⚡️⚡️', 'risk': 'low', 'recommended': True},
    'XRP': {'name': 'Ripple', 'time_min': 0.07, 'time_max': 0.17, 'fee': 0.0005, 'speed': '⚡️⚡️⚡️', 'risk': 'low', 'recommended': True},
    'ALGO': {'name': 'Algorand', 'time_min': 0.07, 'time_max': 0.08, 'fee': 0.0005, 'speed': '⚡️⚡️⚡️', 'risk': 'low', 'recommended': True},
    'NEAR': {'name': 'NEAR Protocol', 'time_min': 0.03, 'time_max': 0.08, 'fee': 0.0005, 'speed': '⚡️⚡️⚡️', 'risk': 'low', 'recommended': True},
    'APT': {'name': 'Aptos', 'time_min': 0.02, 'time_max': 0.05, 'fee': 0.0005, 'speed': '⚡️⚡️⚡️⚡️', 'risk': 'low', 'recommended': True},
    'SUI': {'name': 'Sui', 'time_min': 0.02, 'time_max': 0.05, 'fee': 0.0005, 'speed': '⚡️⚡️⚡️⚡️', 'risk': 'low', 'recommended': True},
    'FTM': {'name': 'Fantom', 'time_min': 0.02, 'time_max': 0.05, 'fee': 0.001, 'speed': '⚡️⚡️⚡️', 'risk': 'low', 'recommended': True},
    'AVAX': {'name': 'Avalanche C-Chain', 'time_min': 0.03, 'time_max': 0.08, 'fee': 0.05, 'speed': '⚡️⚡️', 'risk': 'medium', 'recommended': True},
    'HBAR': {'name': 'Hedera', 'time_min': 0.05, 'time_max': 0.08, 'fee': 0.0001, 'speed': '⚡️⚡️⚡️', 'risk': 'low', 'recommended': True},
    'MATIC': {'name': 'Polygon', 'time_min': 1, 'time_max': 3, 'fee': 0.02, 'speed': '🟢', 'risk': 'low', 'recommended': True},
    'ARB': {'name': 'Arbitrum', 'time_min': 1, 'time_max': 2, 'fee': 0.02, 'speed': '🟢', 'risk': 'low', 'recommended': True},
    'OP': {'name': 'Optimism', 'time_min': 1, 'time_max': 2, 'fee': 0.02, 'speed': '🟢', 'risk': 'low', 'recommended': True},
    'BASE': {'name': 'Base', 'time_min': 1, 'time_max': 3, 'fee': 0.03, 'speed': '🟢', 'risk': 'low', 'recommended': True},
    'BNB': {'name': 'BNB Smart Chain', 'time_min': 1, 'time_max': 3, 'fee': 0.15, 'speed': '🟢', 'risk': 'medium', 'recommended': True},
    'TRX': {'name': 'Tron (TRC-20)', 'time_min': 1, 'time_max': 3, 'fee': 1.50, 'speed': '🟡', 'risk': 'medium', 'recommended': False},
    'LTC': {'name': 'Litecoin', 'time_min': 5, 'time_max': 10, 'fee': 0.05, 'speed': '🟡', 'risk': 'medium', 'recommended': True},
    'DOT': {'name': 'Polkadot', 'time_min': 0.17, 'time_max': 0.5, 'fee': 0.10, 'speed': '🟢', 'risk': 'low', 'recommended': True},
    'ATOM': {'name': 'Cosmos', 'time_min': 0.08, 'time_max': 0.17, 'fee': 0.05, 'speed': '🟢', 'risk': 'low', 'recommended': True},
    'TON': {'name': 'TON', 'time_min': 0.08, 'time_max': 0.17, 'fee': 0.20, 'speed': '🟢', 'risk': 'medium', 'recommended': True},
    'ADA': {'name': 'Cardano', 'time_min': 2, 'time_max': 5, 'fee': 0.08, 'speed': '🟡', 'risk': 'low', 'recommended': True},
    'BTC': {'name': 'Bitcoin', 'time_min': 10, 'time_max': 60, 'fee': 2.50, 'speed': '🔴', 'risk': 'low', 'recommended': False},
    'ETH': {'name': 'Ethereum', 'time_min': 1, 'time_max': 15, 'fee': 10.0, 'speed': '🔴', 'risk': 'medium', 'recommended': False},
}

exchange_stats = defaultdict(lambda: {'buy_count': 0, 'sell_count': 0, 'total_profit': 0})
detected_candidates = {} 
active_spreads = {}      

bot = Bot(token=TELEGRAM_TOKEN)

class HealthCheckServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"Bot is running with the new token. Strict deletion mode active!")

def run_health_server():
    try:
        server = HTTPServer(('0.0.0.0', 10000), HealthCheckServer)
        server.serve_forever()
    except Exception as e:
        logger.error(f"Health server error: {e}")

def get_network_info(network_name):
    for key, info in NETWORKS_INFO.items():
        if key.lower() in network_name.lower() or info['name'].lower() in network_name.lower():
            return info
    return {'name': network_name, 'time_min': 5, 'time_max': 15, 'fee': 0.5, 'speed': '❓', 'risk': 'unknown', 'recommended': False}

async def get_order_book_depth(exchange, symbol, side, amount_usd):
    try:
        orderbook = await exchange.fetch_order_book(symbol, limit=20)
        orders = orderbook['asks'] if side == 'buy' else orderbook['bids']
        if not orders or len(orders) == 0: return None, 0, 0
        
        try:
            market = exchange.market(symbol)
            taker_fee = float(market.get('taker', 0.003))
        except:
            taker_fee = 0.003
            
        total_cost = 0
        total_amount = 0
        for level in orders:
            if not level or len(level) < 2: continue
            price = float(level[0] or 0)
            volume = float(level[1] or 0)
            if price == 0 or volume == 0: continue
            
            level_cost = price * volume
            if total_cost + level_cost >= amount_usd:
                needed_usd = amount_usd - total_cost
                total_amount += needed_usd / price
                total_cost += needed_usd
                break
            else:
                total_amount += volume
                total_cost += level_cost
                
        if total_cost < amount_usd or total_amount == 0: return None, 0, 0
        avg_price = total_cost / total_amount
        return avg_price, total_cost, (amount_usd * taker_fee)
    except:
        return None, 0, 0

async def check_withdrawal_network(exchange, coin):
    try:
        if hasattr(exchange, 'currencies') and exchange.currencies and coin in exchange.currencies:
            currency_info = exchange.currencies[coin]
            networks = currency_info.get('networks', {})
            available_networks = []
            for net_name, net_info in networks.items():
                if net_info.get('withdraw', False) and net_info.get('deposit', False):
                    available_networks.append({
                        'name': net_name,
                        'fee': float(net_info.get('fee', 0.5) or 0.5)
                    })
            if available_networks:
                available_networks.sort(key=lambda x: x['fee'])
                best_network = available_networks[0]
                net_details = get_network_info(best_network['name'])
                return {
                    'network': best_network['name'].upper(),
                    'fee': best_network['fee'],
                    'time_min': net_details['time_min'],
                    'time_max': net_details['time_max'],
                    'speed_icon': net_details['speed'],
                    'recommended': net_details.get('recommended', True)
                }
        return {'network': 'MAINNET/AUTO', 'fee': 0.1, 'time_min': 3, 'time_max': 5, 'speed_icon': '🟢', 'recommended': True}
    except:
        return {'network': 'MAINNET/AUTO', 'fee': 0.1, 'time_min': 3, 'time_max': 5, 'speed_icon': '🟢', 'recommended': True}

def generate_buy_link(exchange_id, symbol):
    coin = symbol.split('/')[0]
    pair = symbol.replace('/', '')
    base_urls = {
        'binance': f"https://www.binance.com/en/trade/{coin}_USDT?type=spot",
        'bybit': f"https://www.bybit.com/trade/spot/{coin}/USDT",
        'okx': f"https://www.okx.com/trade-spot/{coin.lower()}-usdt",
        'gate': f"https://www.gate.io/trade/{coin}_USDT",
        'kucoin': f"https://www.kucoin.com/trade/{coin}-USDT",
        'mexc': f"https://www.mexc.com/exchange/{coin}_USDT",
        'bitget': f"https://www.bitget.com/spot/{pair}",
        'kraken': f"https://trade.kraken.com/markets/kraken/{coin.lower()}/usdt",
        'coinbase': f"https://www.coinbase.com/advanced-trading/{coin}-USDT",
        'huobi': f"https://www.huobi.com/en-us/exchange/{coin.lower()}_usdt",
        'bingx': f"https://bingx.com/en/spot/{pair}",
        'bitmart': f"https://www.bitmart.com/trade/en?symbol={pair}",
        'phemex': f"https://phemex.com/trade/spot/{pair}",
    }
    return base_urls.get(exchange_id, f"https://{exchange_id}.com/trade/{coin}_USDT")

def format_signal_text(coin, buy_ex, sell_ex, p_buy, p_sell, buy_fee, sell_fee, net_info, net_profit, net_spread):
    link_buy = generate_buy_link(buy_ex, f"{coin}/USDT")
    link_sell = generate_buy_link(sell_ex, f"{coin}/USDT")
    rec_icon = "RECOMMENDED" if net_info.get('recommended', True) else "EXPENSIVE NETWORK"
    
    return (
        f"⚡️ **НАЙДЕН АРБИТРАЖНЫЙ СПРЕД: #{coin}** ⚡️\n"
        f"⚠️ **ВАЖНО: РУКАМИ ПРОВЕРЯЙ ВВОД/ВЫВОД НА БИРЖАХ!**\n━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 **ПОКУПКА: {buy_ex.upper()}**\n💵 Цена: `{p_buy:.4f} USDT`\n📊 Круг: `${TRADE_SIZE_USD}`\n🔗 [Открыть пару на {buy_ex.upper()}]({link_buy})\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔴 **ПРОДАЖА: {sell_ex.upper()}**\n💵 Цена: `{p_sell:.4f} USDT`\n🔗 [Открыть пару на {sell_ex.upper()}]({link_sell})\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 **СЕТЬ: {net_info['network']}**\n├ Комиссия сети: `${net_info['fee']:.2f}`\n└ Время перевода: `{net_info['time_min']}-{net_info['time_max']} мин`\n"
        f"{net_info['speed_icon']} **{rec_icon}**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💸 **РАСХОДЫ НА КОМИССИИ:**\n├ Торговые: `${buy_fee + sell_fee:.2f}`\n└ Сеть: `${net_info['fee']:.2f}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💎 **ЧИСТАЯ ДОХОДНОСТЬ:**\n💰 Профит: **+${net_profit:.2f}**\n📈 Спред: **{net_spread:.2f}%**"
    )

async def stats_command():
    stats_message = "📊 **АРБИТРАЖНАЯ СТАТИСТИКА** 📊\n━━━━━━━━━━━━━━━━━━━━━━\n"
    stats_message += f"Время выгрузки: {datetime.now().strftime('%H:%M:%S')}\n\n"
    
    total_opp = sum(s['buy_count'] + s['sell_count'] for s in exchange_stats.values())
    total_profit = sum(s['total_profit'] for s in exchange_stats.values())
    
    stats_message += f"💎 Всего сигналов поймано: **{total_opp}**\n"
    stats_message += f"💰 Математический профит: **${total_profit:.2f}**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    
    stats_message += "🟢 **ТОП БИРЖ ДЛЯ ПОКУПКИ:**\n"
    top_buy = sorted(exchange_stats.items(), key=lambda x: x[1]['buy_count'], reverse=True)[:3]
    has_buy_data = False
    for ex, data in top_buy:
        if data['buy_count'] > 0:
            stats_message += f" ├ {ex.upper()}: **{data['buy_count']}** раз(а)\n"
            has_buy_data = True
    if not has_buy_data: stats_message += " ├ Данные пока отсутствуют...\n"
            
    stats_message += "\n🔴 **ТОП БИРЖ ДЛЯ ПРОДАЖИ:**\n"
    top_sell = sorted(exchange_stats.items(), key=lambda x: x[1]['sell_count'], reverse=True)[:3]
    has_sell_data = False
    for ex, data in top_sell:
        if data['sell_count'] > 0:
            stats_message += f" ├ {ex.upper()}: **{data['sell_count']}** раз(а)\n"
            has_sell_data = True
    if not has_sell_data: stats_message += " ├ Данные пока отсутствуют...\n"
            
    stats_message += "━━━━━━━━━━━━━━━━━━━━━━"
    return stats_message

def run_telegram_bot():
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    async def start_handler(update, context):
        await update.message.reply_text(
            "✅ Бот успешно запущен и сканирует биржи!\n\n"
            "**Доступные команды:**\n"
            "📊 /stats - развернутая статистика по биржам"
        )
    
    async def stats_handler(update, context):
        stats_text = await stats_command()
        keyboard = [[InlineKeyboardButton("🔄 Обновить статистику", callback_data='refresh_stats')]]
        await update.message.reply_text(stats_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        
    async def button_handler(update, context):
        query = update.callback_query
        await query.answer()
        if query.data == 'refresh_stats':
            stats_text = await stats_command()
            keyboard = [[InlineKeyboardButton("🔄 Обновить статистику", callback_data='refresh_stats')]]
            try: await query.edit_message_text(stats_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            except: pass
            
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("stats", stats_handler))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.run_polling(allowed_updates=['message', 'callback_query'])

async def scan_all_markets():
    logger.info("⏳ Инициализация бирж (выполняется один раз при старте)...")
    exchanges = {}
    for ex_id in EXCHANGES_LIST:
        try:
            ex_class = getattr(ccxt, ex_id)
            instance = ex_class({'enableRateLimit': True, 'timeout': 15000})
            await instance.load_markets()
            exchanges[ex_id] = instance
        except: continue

    scan_count = 0
    while True:
        scan_count += 1
        logger.info(f"🔄 Скан круг #{scan_count}... В телеграме висит {len(active_spreads)} спредов")
        all_tickers = {}
        current_time = time.time()

        async def fetch_tickers_safe(ex_id, exchange_obj):
            try:
                tickers = await exchange_obj.fetch_tickers()
                for sym, t in tickers.items():
                    if '/USDT' in sym and not sym.startswith('USDC'):
                        coin = sym.split('/')[0]
                        if coin in BLACKLIST_COINS: continue
                        
                        vol = float(t.get('quoteVolume') or 0)
                        bid = float(t.get('bid') or 0)
                        ask = float(t.get('ask') or 0)
                        if vol >= MIN_VOLUME_USD and bid > 0 and ask > 0:
                            if sym not in all_tickers: all_tickers[sym] = {}
                            all_tickers[sym][ex_id] = {'bid': bid, 'ask': ask, 'vol': vol}
            except: pass

        await asyncio.gather(*[fetch_tickers_safe(eid, ex) for eid, ex in exchanges.items()])
        
        fresh_detected_keys = set()

        async def process_single_symbol(symbol, exchange_data):
            coin = symbol.split('/')[0]
            buy_list = sorted([(eid, d['ask']) for eid, d in exchange_data.items()], key=lambda x: x[1])[:3]
            sell_list = sorted([(eid, d['bid']) for eid, d in exchange_data.items()], key=lambda x: x[1], reverse=True)[:3]
            
            for buy_ex, ask_p in buy_list:
                for sell_ex, bid_p in sell_list:
                    if buy_ex == sell_ex: continue
                    
                    raw_spread = ((bid_p - ask_p) / ask_p) * 100
                    if raw_spread < MIN_SPREAD_PCT or raw_spread > MAX_SPREAD_PCT: continue
                    
                    spread_key = f"{coin}_{buy_ex}_{sell_ex}"
                    fresh_detected_keys.add(spread_key)
                    
                    if spread_key in active_spreads: continue
                    
                    if spread_key not in detected_candidates:
                        detected_candidates[spread_key] = current_time
                        continue
                    
                    if current_time - detected_candidates[spread_key] < 120:
                        continue
                    
                    p_buy, _, b_fee = await get_order_book_depth(exchanges[buy_ex], symbol, 'buy', TRADE_SIZE_USD)
                    p_sell, _, s_fee = await get_order_book_depth(exchanges[sell_ex], symbol, 'sell', TRADE_SIZE_USD)
                    
                    if p_buy and p_sell:
                        net_info = await check_withdrawal_network(exchanges[buy_ex], coin)
                        total_fees = b_fee + s_fee + net_info['fee']
                        gross_profit = ((TRADE_SIZE_USD / p_buy) * p_sell - TRADE_SIZE_USD)
                        net_profit = gross_profit - total_fees
                        net_spread = (net_profit / TRADE_SIZE_USD) * 100
                        
                        if MIN_SPREAD_PCT <= net_spread <= MAX_SPREAD_PCT:
                            exchange_stats[buy_ex]['buy_count'] += 1
                            exchange_stats[buy_ex]['total_profit'] += (net_profit / 2)
                            exchange_stats[sell_ex]['sell_count'] += 1
                            exchange_stats[sell_ex]['total_profit'] += (net_profit / 2)
                            
                            msg_text = format_signal_text(coin, buy_ex, sell_ex, p_buy, p_sell, b_fee, s_fee, net_info, net_profit, net_spread)
                            try:
                                msg = await bot.send_message(chat_id=CHAT_ID, text=msg_text, parse_mode="Markdown", disable_web_page_preview=True)
                                active_spreads[spread_key] = {
                                    "message_id": msg.message_id, "coin": coin, "buy_ex": buy_ex, "sell_ex": sell_ex, "net_info": net_info
                                }
                            except: pass

        chunks = list(all_tickers.items())
        for i in range(0, len(chunks), 30):
            await asyncio.gather(*[process_single_symbol(sym, edata) for sym, edata in chunks[i:i+30]])
            await asyncio.sleep(0.05)
            
        for k in list(detected_candidates.keys()):
            if k not in fresh_detected_keys and k not in active_spreads:
                del detected_candidates[k]
        
        # ЕСКІРГЕН НЕМЕСЕ ӨЗЕКТІ ЕМЕС СПРЕДТЕРДІ ТЕЛЕГРАМНАН ӨШІРУ
        for spread_id in list(active_spreads.keys()):
            data = active_spreads[spread_id]
            
            if spread_id not in fresh_detected_keys:
                try: await bot.delete_message(chat_id=CHAT_ID, message_id=data["message_id"])
                except: pass
                del active_spreads[spread_id]
                continue
                
            buy_ex = data["buy_ex"]
            sell_ex = data["sell_ex"]
            symbol = f"{data['coin']}/USDT"
            
            try:
                p_buy, _, b_fee = await get_order_book_depth(exchanges[buy_ex], symbol, 'buy', TRADE_SIZE_USD)
                p_sell, _, s_fee = await get_order_book_depth(exchanges[sell_ex], symbol, 'sell', TRADE_SIZE_USD)
                
                still_alive = False
                if p_buy and p_sell:
                    total_fees = b_fee + s_fee + data["net_info"]['fee']
                    gross_profit = ((TRADE_SIZE_USD / p_buy) * p_sell - TRADE_SIZE_USD)
                    net_profit = gross_profit - total_fees
                    net_spread = (net_profit / TRADE_SIZE_USD) * 100
                    
                    if MIN_SPREAD_PCT <= net_spread <= MAX_SPREAD_PCT:
                        still_alive = True
                        
                # Егер спред шектен (0.3%) төмендесе, хабарлама бірден өшіріледі
                if not still_alive:
                    try: await bot.delete_message(chat_id=CHAT_ID, message_id=data["message_id"])
                    except: pass
                    del active_spreads[spread_id]
            except:
                try: await bot.delete_message(chat_id=CHAT_ID, message_id=data["message_id"])
                except: pass
                del active_spreads[spread_id]

        await asyncio.sleep(10)

if __name__ == '__main__':
    threading.Thread(target=run_health_server, daemon=True).start()
    threading.Thread(target=run_telegram_bot, daemon=True).start()
    asyncio.run(scan_all_markets())
