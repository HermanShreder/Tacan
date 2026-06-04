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
import os

# Настройки
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Telegram настройки
TELEGRAM_TOKEN = "7930993307:AAHuIxRVgr9OD7ZP_D2dbrbEu-JGBdZSnc4"
CHAT_ID = "5253808709"

# Торговые настройки
TRADE_SIZE_USD = 500
MIN_SPREAD_PCT = 0.3
MIN_VOLUME_USD = 10000

# API ключ Binance
BINANCE_API_KEY = "uvxQH98mpFgMRLM0ImIhBBohS3Pl86hVzDifpOUbmkRbDje6nZ0d74bB6oJLSFKt"
BINANCE_SECRET = ""  # НЕ ЗАПОЛНЯТЬ В КОДЕ! Добавьте локально если нужно

# Список всех бирж
EXCHANGES_LIST = [
    'binance', 'bybit', 'okx', 'gate', 'kucoin', 'bitget', 'mexc', 
    'bingx', 'htx', 'kraken', 'coinbase', 'huobi', 'poloniex', 
    'hitbtc', 'exmo', 'bitfinex', 'bitmart', 'lbank', 'ascendex',
    'coinex', 'gateio', 'crypto', 'whitebit', 'bitrue', 'phemex'
]

# Данные по сетям
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

# Статистика
exchange_stats = defaultdict(lambda: {
    'total_spreads': 0,
    'buy_count': 0,
    'sell_count': 0,
    'total_profit': 0,
    'opportunities': []
})

active_spreads = {}
last_update_time = {}
orderbooks_cache = {}

class HealthCheckServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        # Убираем эмодзи из bytes строки
        self.wfile.write(b"Arbitrage Bot is running! | Binance API: Connected")

def run_health_server():
    server = HTTPServer(('0.0.0.0', 10000), HealthCheckServer)
    server.serve_forever()

def get_network_info(network_name):
    for key, info in NETWORKS_INFO.items():
        if key.lower() in network_name.lower() or info['name'].lower() in network_name.lower():
            return info
    return {'name': network_name, 'time_min': 5, 'time_max': 15, 'fee': 0.5, 'speed': '❓', 'risk': 'unknown', 'recommended': False}

async def get_order_book_depth(exchange, symbol, side, amount_usd):
    try:
        cache_key = f"{exchange.id}_{symbol}_{side}"
        current_time = time.time()
        
        if cache_key in orderbooks_cache:
            cached_time, cached_data = orderbooks_cache[cache_key]
            if current_time - cached_time < 2:
                return cached_data
        
        orderbook = await exchange.fetch_order_book(symbol, limit=100)
        orders = orderbook['asks'] if side == 'buy' else orderbook['bids']
        
        if not orders:
            return None, 0, 0
        
        try:
            market = exchange.market(symbol)
            taker_fee = market.get('taker', 0.001)
            if exchange.id == 'binance' and BINANCE_API_KEY:
                taker_fee = 0.00075
        except:
            taker_fee = 0.001
        
        total_cost = 0
        total_amount = 0
        remaining = amount_usd
        levels_used = 0
        
        for price, volume in orders:
            level_cost = price * volume
            levels_used += 1
            
            if level_cost >= remaining:
                amount_needed = remaining / price
                total_amount += amount_needed
                total_cost += remaining
                remaining = 0
                break
            else:
                total_amount += volume
                total_cost += level_cost
                remaining -= level_cost
            
            if levels_used > 50:
                break
        
        if remaining > 0:
            return None, 0, 0
        
        avg_price = total_cost / total_amount
        fee_cost = total_cost * taker_fee
        
        result = (avg_price, total_cost, fee_cost)
        orderbooks_cache[cache_key] = (current_time, result)
        
        if len(orderbooks_cache) > 1000:
            old_keys = [k for k, v in orderbooks_cache.items() if current_time - v[0] > 10]
            for k in old_keys:
                del orderbooks_cache[k]
        
        return result
    except Exception as e:
        logger.error(f"Error orderbook {symbol} on {exchange.id}: {e}")
        return None, 0, 0

async def check_withdrawal_network(exchange, coin):
    try:
        if hasattr(exchange, 'currencies') and exchange.currencies:
            if coin in exchange.currencies:
                currency_info = exchange.currencies[coin]
                networks = currency_info.get('networks', {})
                
                available_networks = []
                for net_name, net_info in networks.items():
                    withdraw_enabled = net_info.get('withdraw', False)
                    deposit_enabled = net_info.get('deposit', False)
                    fee = net_info.get('fee', float('inf'))
                    
                    if withdraw_enabled and deposit_enabled:
                        available_networks.append({
                            'name': net_name,
                            'fee': fee,
                            'withdraw_enabled': withdraw_enabled,
                            'deposit_enabled': deposit_enabled
                        })
                
                if available_networks:
                    available_networks.sort(key=lambda x: x['fee'])
                    best_network = available_networks[0]
                    network_info = get_network_info(best_network['name'])
                    
                    if network_info['fee'] > 1.0 and len(available_networks) > 1:
                        for net in available_networks:
                            alt_info = get_network_info(net['name'])
                            if alt_info['fee'] < 0.5:
                                best_network = net
                                network_info = alt_info
                                break
                    
                    return {
                        'network': best_network['name'],
                        'fee': best_network['fee'],
                        'time_min': network_info['time_min'],
                        'time_max': network_info['time_max'],
                        'speed_icon': network_info['speed'],
                        'risk': network_info['risk'],
                        'recommended': network_info.get('recommended', True)
                    }
        
        return {
            'network': 'MAINNET',
            'fee': 0.1,
            'time_min': 5,
            'time_max': 15,
            'speed_icon': '🟡',
            'risk': 'medium',
            'recommended': True
        }
    except Exception as e:
        logger.error(f"Error networks for {coin} on {exchange.id}: {e}")
        return None

def generate_buy_link(exchange_id, symbol):
    coin = symbol.split('/')[0]
    pair = symbol.replace('/', '')
    
    base_urls = {
        'binance': f"https://www.binance.com/en/trade/{pair}?type=spot",
        'bybit': f"https://www.bybit.com/trade/spot/{pair}",
        'okx': f"https://www.okx.com/trade-spot/{symbol.replace('/', '-')}",
        'gate': f"https://www.gate.io/trade/{symbol.replace('/', '_')}",
        'kucoin': f"https://www.kucoin.com/trade/{symbol.replace('/', '-')}",
        'mexc': f"https://www.mexc.com/exchange/{symbol.replace('/', '_')}",
        'bitget': f"https://www.bitget.com/spot/{pair}",
        'kraken': f"https://trade.kraken.com/markets/kraken/{symbol.replace('/', '/')}",
        'coinbase': f"https://www.coinbase.com/advanced-trading/{symbol.replace('/', '-')}",
        'huobi': f"https://www.huobi.com/en-us/exchange/{symbol.replace('/', '_')}",
        'bingx': f"https://bingx.com/en/spot/{pair}",
        'bitmart': f"https://www.bitmart.com/trade/en?symbol={pair}",
        'phemex': f"https://phemex.com/trade/spot/{pair}",
    }
    return base_urls.get(exchange_id, f"https://{exchange_id}.com/trade/{pair}")

async def send_arbitrage_signal(coin, buy_exchange, sell_exchange, buy_price, sell_price, 
                                 buy_fee, sell_fee, network_info, net_profit, spread_pct, 
                                 depth_buy, depth_sell):
    link_buy = generate_buy_link(buy_exchange.id, f"{coin}/USDT")
    link_sell = generate_buy_link(sell_exchange.id, f"{coin}/USDT")
    
    time_min = network_info.get('time_min', 5)
    time_max = network_info.get('time_max', 15)
    recommended = network_info.get('recommended', True)
    speed_icon = network_info.get('speed_icon', '🟡')
    
    rec_icon = "RECOMMENDED" if recommended else "EXPENSIVE NETWORK"
    
    message = (
        f"🚨 ARBITRAGE FOUND! 🚨\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Coin: {coin}\n"
        f"Spread: {spread_pct:.2f}%\n"
        f"Profit: ${net_profit:.2f}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"BUY: {buy_exchange.id.upper()}\n"
        f"Price: ${buy_price:.6f}\n"
        f"Depth: ${depth_buy:.0f}\n"
        f"Link: {link_buy}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"SELL: {sell_exchange.id.upper()}\n"
        f"Price: ${sell_price:.6f}\n"
        f"Depth: ${depth_sell:.0f}\n"
        f"Link: {link_sell}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"NETWORK: {network_info['network']}\n"
        f"Fee: ${network_info['fee']:.4f}\n"
        f"Time: {time_min}-{time_max} min\n"
        f"{speed_icon} {rec_icon}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"FEES:\n"
        f"Trading: ${buy_fee + sell_fee:.2f}\n"
        f"Network: ${network_info['fee']:.2f}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Update: every 30 sec\n"
        f"Status: Active"
    )
    
    return message

async def stats_command():
    stats_message = "STATISTICS\n━━━━━━━━━━━━━━━━━━━\n\n"
    
    stats_message += f"Last update: {datetime.now().strftime('%H:%M:%S')}\n\n"
    
    stats_message += "TOP EXCHANGES FOR BUY:\n"
    buy_stats = [(ex_id, stats['buy_count']) for ex_id, stats in exchange_stats.items() if stats['buy_count'] > 0]
    buy_stats.sort(key=lambda x: x[1], reverse=True)
    
    for ex_id, count in buy_stats[:5]:
        total = sum(s['buy_count'] for s in exchange_stats.values())
        pct = (count / total) * 100 if total > 0 else 0
        stats_message += f"{ex_id.upper()}: {count} times ({pct:.1f}%)\n"
    
    stats_message += "\nTOP EXCHANGES FOR SELL:\n"
    sell_stats = [(ex_id, stats['sell_count']) for ex_id, stats in exchange_stats.items() if stats['sell_count'] > 0]
    sell_stats.sort(key=lambda x: x[1], reverse=True)
    
    for ex_id, count in sell_stats[:5]:
        total = sum(s['sell_count'] for s in exchange_stats.values())
        pct = (count / total) * 100 if total > 0 else 0
        stats_message += f"{ex_id.upper()}: {count} times ({pct:.1f}%)\n"
    
    total_opp = sum(s['buy_count'] + s['sell_count'] for s in exchange_stats.values())
    total_profit = sum(s['total_profit'] for s in exchange_stats.values())
    
    stats_message += f"\n━━━━━━━━━━━━━━━━━━━\n"
    stats_message += f"TOTAL:\n"
    stats_message += f"Signals: {total_opp}\n"
    stats_message += f"Profit: ${total_profit:.2f}\n"
    
    return stats_message

def run_telegram_bot():
    from telegram.ext import Application, CommandHandler, CallbackQueryHandler
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    async def stats_handler(update, context):
        stats_text = await stats_command()
        keyboard = [[InlineKeyboardButton("Refresh Statistics", callback_data='refresh_stats')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(stats_text, reply_markup=reply_markup)
    
    async def button_handler(update, context):
        query = update.callback_query
        await query.answer()
        
        if query.data == 'refresh_stats':
            stats_text = await stats_command()
            await query.edit_message_text(stats_text)
    
    application.add_handler(CommandHandler("stats", stats_handler))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    application.run_polling(allowed_updates=['message', 'callback_query'])

async def scan_all_markets():
    scan_count = 0
    last_stats_time = time.time()
    
    while True:
        scan_count += 1
        start_time = time.time()
        logger.info(f"Scan #{scan_count} - Starting...")
        
        exchanges = {}
        try:
            for exchange_id in EXCHANGES_LIST:
                try:
                    exchange_class = getattr(ccxt, exchange_id)
                    config = {
                        'enableRateLimit': True,
                        'rateLimit': 1200,
                        'timeout': 30000,
                    }
                    
                    if exchange_id == 'binance' and BINANCE_API_KEY:
                        config['apiKey'] = BINANCE_API_KEY
                        config['secret'] = BINANCE_SECRET
                    
                    exchange = exchange_class(config)
                    await exchange.load_markets()
                    exchanges[exchange_id] = exchange
                    logger.info(f"Connected: {exchange_id.upper()}")
                except Exception as e:
                    logger.warning(f"Failed: {exchange_id} - {str(e)[:50]}")
            
            all_tickers = {}
            for ex_id, exchange in exchanges.items():
                try:
                    tickers = await exchange.fetch_tickers()
                    count = 0
                    for symbol, ticker in tickers.items():
                        if '/USDT' in symbol:
                            volume = ticker.get('quoteVolume', 0)
                            if volume >= MIN_VOLUME_USD:
                                if symbol not in all_tickers:
                                    all_tickers[symbol] = {}
                                all_tickers[symbol][ex_id] = {
                                    'bid': ticker.get('bid', 0),
                                    'ask': ticker.get('ask', 0),
                                    'volume': volume,
                                    'last': ticker.get('last', 0)
                                }
                                count += 1
                    logger.info(f"{ex_id.upper()}: {count} coins with volume > ${MIN_VOLUME_USD}")
                except Exception as e:
                    logger.error(f"Ticker error {ex_id}: {e}")
            
            logger.info(f"Total unique coins: {len(all_tickers)}")
            
            opportunities_found = 0
            processed = 0
            
            for symbol, exchange_data in all_tickers.items():
                coin = symbol.split('/')[0]
                processed += 1
                
                if processed % 100 == 0:
                    logger.info(f"Processed {processed}/{len(all_tickers)} coins...")
                
                buy_list = []
                sell_list = []
                
                for ex_id, data in exchange_data.items():
                    if data['ask'] > 0 and data['volume'] > 0:
                        buy_list.append((ex_id, data['ask'], data['volume']))
                    if data['bid'] > 0 and data['volume'] > 0:
                        sell_list.append((ex_id, data['bid'], data['volume']))
                
                for buy_ex, buy_price, buy_vol in buy_list[:5]:
                    for sell_ex, sell_price, sell_vol in sell_list[:5]:
                        if buy_ex == sell_ex:
                            continue
                        
                        raw_spread = ((sell_price - buy_price) / buy_price) * 100
                        if raw_spread < MIN_SPREAD_PCT * 1.5:
                            continue
                        
                        network_info = await check_withdrawal_network(exchanges[buy_ex], coin)
                        if not network_info:
                            continue
                        
                        buy_result = await get_order_book_depth(
                            exchanges[buy_ex], symbol, 'buy', TRADE_SIZE_USD
                        )
                        sell_result = await get_order_book_depth(
                            exchanges[sell_ex], symbol, 'sell', TRADE_SIZE_USD
                        )
                        
                        if not buy_result[0] or not sell_result[0]:
                            continue
                        
                        real_buy_price, buy_total, buy_fee = buy_result
                        real_sell_price, sell_total, sell_fee = sell_result
                        
                        real_spread = ((real_sell_price - real_buy_price) / real_buy_price) * 100
                        
                        total_fees = buy_fee + sell_fee + network_info['fee']
                        gross_profit = ((TRADE_SIZE_USD / real_buy_price) * real_sell_price - TRADE_SIZE_USD)
                        net_profit = gross_profit - total_fees
                        net_spread = (net_profit / TRADE_SIZE_USD) * 100
                        
                        if net_spread >= MIN_SPREAD_PCT:
                            opportunities_found += 1
                            
                            exchange_stats[buy_ex]['buy_count'] += 1
                            exchange_stats[buy_ex]['total_profit'] += net_profit
                            exchange_stats[sell_ex]['sell_count'] += 1
                            exchange_stats[sell_ex]['total_profit'] += net_profit
                            
                            spread_key = f"{coin}_{buy_ex}_{sell_ex}"
                            if spread_key in last_update_time:
                                if time.time() - last_update_time[spread_key] < 300:
                                    continue
                            
                            message = await send_arbitrage_signal(
                                coin, exchanges[buy_ex], exchanges[sell_ex],
                                real_buy_price, real_sell_price,
                                buy_fee, sell_fee, network_info,
                                net_profit, net_spread,
                                buy_total, sell_total
                            )
                            
                            try:
                                bot = Bot(token=TELEGRAM_TOKEN)
                                await bot.send_message(
                                    chat_id=CHAT_ID,
                                    text=message,
                                    disable_web_page_preview=True
                                )
                                last_update_time[spread_key] = time.time()
                                logger.info(f"SIGNAL! {coin} | Spread: {net_spread:.2f}% | Profit: ${net_profit:.2f}")
                                await asyncio.sleep(0.2)
                            except Exception as e:
                                logger.error(f"Telegram error: {e}")
            
            scan_time = time.time() - start_time
            logger.info(f"Scan #{scan_count} completed in {scan_time:.1f}sec | Opportunities: {opportunities_found}")
            
            if time.time() - last_stats_time > 3600:
                stats_text = await stats_command()
                bot = Bot(token=TELEGRAM_TOKEN)
                await bot.send_message(chat_id=CHAT_ID, text=stats_text)
                last_stats_time = time.time()
            
        except Exception as e:
            logger.error(f"Scan error: {e}")
        finally:
            for exchange in exchanges.values():
                try:
                    await exchange.close()
                except:
                    pass
        
        await asyncio.sleep(30)

if __name__ == '__main__':
    print("""
    ========================================
         ARBITRAGE BOT v2.0 - STARTING
    ========================================
    Binance API: Connected
    Orderbooks: Active (depth 100)
    Exchanges: 25+
    Networks: 20+ with real fees
    ========================================
    """)
    
    threading.Thread(target=run_health_server, daemon=True).start()
    
    bot_thread = threading.Thread(target=run_telegram_bot, daemon=True)
    bot_thread.start()
    
    asyncio.run(scan_all_markets())
