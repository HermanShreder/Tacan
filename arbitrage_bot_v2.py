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

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== ТВОИ API КЛЮЧИ ====================
EXCHANGE_CONFIGS = {
    'binance': {
        'apiKey': '29d9fe7e-4b147f7f-dbuqg6hkte-0a894',
        'secret': 'b0925bb5-07815986-b85bf68f-558a5',
        'options': {'defaultType': 'spot'}
    },
    'huobi': {
        'apiKey': '5d80677222f36e38d07d92f317e45674',
        'secret': '1a4d3c051cb523364b540e87361435a096b20dc51d96df9a91eaf03c6ad55c13',
        'options': {'defaultType': 'spot'}
    },
    'gate': {
        'apiKey': 'bg_c425385453f54a25ed72a37f7498bfc5',
        'secret': '46401f612cd8fa387c091a97061962d1f07b31187681405df72b457b0a78f69a',
        'options': {'defaultType': 'spot'}
    },
    'bitget': {
        'apiKey': 'uvxQH98mpFgMRLM0ImIhBBohS3Pl86hVzDifpOUbmkRbDje6nZ0d74bB6oJLSFKt',
        'secret': 'YOUR_BITGET_SECRET_HERE',
        'options': {'defaultType': 'spot'}
    }
}

TELEGRAM_TOKEN = "5814224378:AAHlkQ41I-uQ9XXe_jmn5G28Q2x6nXCVNM8"
CHAT_ID = "5253808709"

TRADE_SIZE_USD = 500
MIN_SPREAD_PCT = 0.3
MAX_SPREAD_PCT = 15.0
MIN_VOLUME_USD = 100000

BLACKLIST_COINS = {'KEY', 'STAR', 'BOND', 'MIRA', 'WILD', 'MAGIC', 'NATIVE'}

EXCHANGES_LIST = [
    'binance', 'bybit', 'okx', 'gate', 'kucoin', 'bitget', 'mexc', 'bingx', 'htx', 'huobi',
    'kraken', 'coinbase', 'poloniex', 'hitbtc', 'bitfinex', 'bitmart', 'lbank', 'ascendex',
    'coinex', 'whitebit', 'bitrue', 'phemex'
]

NETWORKS_INFO = {
    'SOL': {'name': 'Solana', 'time_min': 0.03, 'time_max': 0.08, 'fee': 0.0005, 'speed': '⚡', 'risk': 'low', 'recommended': True},
    'XLM': {'name': 'Stellar', 'time_min': 0.05, 'time_max': 0.08, 'fee': 0.0001, 'speed': '⚡', 'risk': 'low', 'recommended': True},
    'XRP': {'name': 'Ripple', 'time_min': 0.07, 'time_max': 0.17, 'fee': 0.0005, 'speed': '⚡', 'risk': 'low', 'recommended': True},
    'ALGO': {'name': 'Algorand', 'time_min': 0.07, 'time_max': 0.08, 'fee': 0.0005, 'speed': '⚡', 'risk': 'low', 'recommended': True},
    'NEAR': {'name': 'NEAR Protocol', 'time_min': 0.03, 'time_max': 0.08, 'fee': 0.0005, 'speed': '⚡', 'risk': 'low', 'recommended': True},
    'APT': {'name': 'Aptos', 'time_min': 0.02, 'time_max': 0.05, 'fee': 0.0005, 'speed': '⚡⚡', 'risk': 'low', 'recommended': True},
    'SUI': {'name': 'Sui', 'time_min': 0.02, 'time_max': 0.05, 'fee': 0.0005, 'speed': '⚡⚡', 'risk': 'low', 'recommended': True},
    'FTM': {'name': 'Fantom', 'time_min': 0.02, 'time_max': 0.05, 'fee': 0.001, 'speed': '⚡', 'risk': 'low', 'recommended': True},
    'AVAX': {'name': 'Avalanche C-Chain', 'time_min': 0.03, 'time_max': 0.08, 'fee': 0.05, 'speed': '⚡', 'risk': 'medium', 'recommended': True},
    'HBAR': {'name': 'Hedera', 'time_min': 0.05, 'time_max': 0.08, 'fee': 0.0001, 'speed': '⚡', 'risk': 'low', 'recommended': True},
    'MATIC': {'name': 'Polygon', 'time_min': 1, 'time_max': 3, 'fee': 0.02, 'speed': '', 'risk': 'low', 'recommended': True},
    'ARB': {'name': 'Arbitrum', 'time_min': 1, 'time_max': 2, 'fee': 0.02, 'speed': '', 'risk': 'low', 'recommended': True},
    'OP': {'name': 'Optimism', 'time_min': 1, 'time_max': 2, 'fee': 0.02, 'speed': '', 'risk': 'low', 'recommended': True},
    'BASE': {'name': 'Base', 'time_min': 1, 'time_max': 3, 'fee': 0.03, 'speed': '', 'risk': 'low', 'recommended': True},
    'BNB': {'name': 'BNB Smart Chain', 'time_min': 1, 'time_max': 3, 'fee': 0.15, 'speed': '', 'risk': 'medium', 'recommended': True},
    'TRX': {'name': 'Tron (TRC-20)', 'time_min': 1, 'time_max': 3, 'fee': 1.50, 'speed': '', 'risk': 'medium', 'recommended': False},
    'LTC': {'name': 'Litecoin', 'time_min': 5, 'time_max': 10, 'fee': 0.05, 'speed': '', 'risk': 'medium', 'recommended': True},
    'DOT': {'name': 'Polkadot', 'time_min': 0.17, 'time_max': 0.5, 'fee': 0.10, 'speed': '', 'risk': 'low', 'recommended': True},
    'ATOM': {'name': 'Cosmos', 'time_min': 0.08, 'time_max': 0.17, 'fee': 0.05, 'speed': '', 'risk': 'low', 'recommended': True},
    'TON': {'name': 'TON', 'time_min': 0.08, 'time_max': 0.17, 'fee': 0.20, 'speed': '', 'risk': 'medium', 'recommended': True},
    'ADA': {'name': 'Cardano', 'time_min': 2, 'time_max': 5, 'fee': 0.08, 'speed': '', 'risk': 'low', 'recommended': True},
    'BTC': {'name': 'Bitcoin', 'time_min': 10, 'time_max': 60, 'fee': 2.50, 'speed': '', 'risk': 'low', 'recommended': False},
    'ETH': {'name': 'Ethereum', 'time_min': 1, 'time_max': 15, 'fee': 10.0, 'speed': '', 'risk': 'medium', 'recommended': False},
}

exchange_stats = defaultdict(lambda: {'buy_count': 0, 'sell_count': 0, 'total_profit': 0})
active_spreads = {}
bot = Bot(token=TELEGRAM_TOKEN)

class HealthCheckServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"WS Arbitrage Bot RUNNING - Ultra Low Latency Mode")

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
    return {'name': network_name, 'time_min': 5, 'time_max': 15, 'fee': 0.5, 'speed': '', 'risk': 'unknown', 'recommended': False}

async def get_order_book_depth(exchange, symbol, side, amount_usd):
    try:
        orderbook = await exchange.fetch_order_book(symbol, limit=20)
        orders = orderbook['asks'] if side == 'buy' else orderbook['bids']
        if not orders or len(orders) == 0:
            return None, 0, 0
        market = exchange.market(symbol)
        taker_fee = float(market.get('taker', 0.003))
        total_cost = 0.0
        total_amount = 0.0
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
    except Exception:
        return None, 0, 0

async def check_withdrawal_network(exchange, coin):
    try:
        if hasattr(exchange, 'currencies') and exchange.currencies and coin in exchange.currencies:
            currency_info = exchange.currencies[coin]
            networks = currency_info.get('networks', {}) or {}
            available_networks = []
            for net_name, net_info in networks.items():
                can_dep = net_info.get('deposit', False) or net_info.get('depositEnabled', False)
                can_wd = net_info.get('withdraw', False) or net_info.get('withdrawEnabled', False)
                fee = float(net_info.get('withdrawFee') or net_info.get('fee') or 0.5)
                status = f"ВВОД: {'✅ ОТКРЫТ' if can_dep else '❌ ЗАКРЫТ'} | ВЫВОД: {'✅ ОТКРЫТ' if can_wd else '❌ ЗАКРЫТ'}"
                # ОБА ДОЛЖНЫ БЫТЬ ОТКРЫТЫ
                if can_dep and can_wd:
                    available_networks.append({
                        'name': net_name.upper(),
                        'fee': fee,
                        'status': status
                    })
            if available_networks:
                available_networks.sort(key=lambda x: x['fee'])
                best = available_networks[0]
                net_details = get_network_info(best['name'])
                return {
                    'network': best['name'],
                    'fee': best['fee'],
                    'time_min': net_details['time_min'],
                    'time_max': net_details['time_max'],
                    'speed_icon': net_details.get('speed', ''),
                    'recommended': net_details.get('recommended', True),
                    'status': best['status']
                }
        return {'network': 'MAINNET/AUTO', 'fee': 0.1, 'time_min': 3, 'time_max': 5, 'speed_icon': '', 'recommended': True, 'status': 'ВВОД/ВЫВОД: ПРОВЕРЬ РУКАМИ'}
    except Exception:
        return {'network': 'MAINNET/AUTO', 'fee': 0.1, 'time_min': 3, 'time_max': 5, 'speed_icon': '', 'recommended': True, 'status': 'ВВОД/ВЫВОД: ПРОВЕРЬ РУКАМИ'}

def generate_buy_link(exchange_id, symbol):
    coin = symbol.split('/')[0]
    pair = symbol.replace('/', '')
    base_urls = {
        'binance': f"https://www.binance.com/en/trade/{coin}_USDT?type=spot",
        'bybit': f"https://www.bybit.com/trade/spot/{coin}/USDT",
        'okx': f"https://www.okx.com/trade-spot/{coin.lower()}-usdt",
        'gate': f"https://www.gate.io/trade/{coin}_USDT",
        'kucoin': f"https://www.kucoin.com/trade/{coin}-USDT",
        'bitget': f"https://www.bitget.com/spot/{pair}",
        'huobi': f"https://www.huobi.com/en-us/exchange/{coin.lower()}_usdt",
        'mexc': f"https://www.mexc.com/exchange/{coin}_USDT",
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
        f"⚡ НАЙДЕН АРБИТРАЖНЫЙ СПРЕД: #{coin} ⚡\n"
        f"**{net_info.get('status', '')}**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"**ПОКУПКА: {buy_ex.upper()}**\n"
        f"Цена: `{p_buy:.4f} USDT`\n"
        f"Круг: `${TRADE_SIZE_USD}`\n"
        f"[Открыть на {buy_ex.upper()}]({link_buy})\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"**ПРОДАЖА: {sell_ex.upper()}**\n"
        f"Цена: `{p_sell:.4f} USDT`\n"
        f"[Открыть на {sell_ex.upper()}]({link_sell})\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"**СЕТЬ: {net_info['network']}**\n"
        f"├ Комиссия сети: `${net_info['fee']:.3f}`\n"
        f"└ Время: `{net_info['time_min']}-{net_info['time_max']} мин` {net_info.get('speed_icon', '')}\n"
        f"{rec_icon}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"**ЧИСТАЯ ДОХОДНОСТЬ:**\n"
        f"Профит: **+${net_profit:.2f}**\n"
        f"Спред: **{net_spread:.2f}%**"
    )

async def watch_exchange_tickers(exchange, ex_id, global_tickers):
    while True:
        try:
            if hasattr(exchange, 'watch_tickers') and exchange.has.get('watchTickers'):
                tickers = await exchange.watch_tickers()
                for sym, t in tickers.items():
                    if '/USDT' not in sym or sym.startswith('USDC'): continue
                    coin = sym.split('/')[0]
                    if coin in BLACKLIST_COINS: continue
                    vol = float(t.get('quoteVolume') or t.get('volume') or 0)
                    bid = float(t.get('bid') or 0)
                    ask = float(t.get('ask') or 0)
                    if vol >= MIN_VOLUME_USD and bid > 0 and ask > 0:
                        if sym not in global_tickers:
                            global_tickers[sym] = {}
                        global_tickers[sym][ex_id] = {'bid': bid, 'ask': ask, 'vol': vol}
            else:
                await asyncio.sleep(12)
                tickers = await exchange.fetch_tickers()
                for sym, t in tickers.items():
                    if '/USDT' not in sym or sym.startswith('USDC'): continue
                    coin = sym.split('/')[0]
                    if coin in BLACKLIST_COINS: continue
                    vol = float(t.get('quoteVolume') or 0)
                    bid = float(t.get('bid') or 0)
                    ask = float(t.get('ask') or 0)
                    if vol >= MIN_VOLUME_USD and bid > 0 and ask > 0:
                        if sym not in global_tickers:
                            global_tickers[sym] = {}
                        global_tickers[sym][ex_id] = {'bid': bid, 'ask': ask, 'vol': vol}
        except Exception as e:
            logger.warning(f"WS/Poll error {ex_id}: {e}")
            await asyncio.sleep(5)

async def process_single_symbol(symbol, exchange_data, exchanges, fresh_keys):
    coin = symbol.split('/')[0]
    buy_list = sorted([(eid, d['ask']) for eid, d in exchange_data.items() if eid in exchanges], key=lambda x: x[1])[:3]
    sell_list = sorted([(eid, d['bid']) for eid, d in exchange_data.items() if eid in exchanges], key=lambda x: x[1], reverse=True)[:3]
    for buy_ex, ask_p in buy_list:
        for sell_ex, bid_p in sell_list:
            if buy_ex == sell_ex: continue
            raw_spread = ((bid_p - ask_p) / ask_p) * 100
            if raw_spread < MIN_SPREAD_PCT or raw_spread > MAX_SPREAD_PCT: continue
            spread_key = f"{coin}_{buy_ex}_{sell_ex}"
            fresh_keys.add(spread_key)
            p_buy, _, b_fee = await get_order_book_depth(exchanges[buy_ex], symbol, 'buy', TRADE_SIZE_USD)
            p_sell, _, s_fee = await get_order_book_depth(exchanges[sell_ex], symbol, 'sell', TRADE_SIZE_USD)
            if not (p_buy and p_sell): continue
            net_info = await check_withdrawal_network(exchanges[buy_ex], coin)
            total_fees = b_fee + s_fee + net_info['fee']
            gross_profit = ((TRADE_SIZE_USD / p_buy) * p_sell - TRADE_SIZE_USD)
            net_profit = gross_profit - total_fees
            net_spread = (net_profit / TRADE_SIZE_USD) * 100
            if MIN_SPREAD_PCT <= net_spread <= MAX_SPREAD_PCT:
                msg_text = format_signal_text(coin, buy_ex, sell_ex, p_buy, p_sell, b_fee, s_fee, net_info, net_profit, net_spread)
                if spread_key in active_spreads:
                    try:
                        await bot.edit_message_text(
                            chat_id=CHAT_ID,
                            message_id=active_spreads[spread_key]["message_id"],
                            text=msg_text,
                            parse_mode="Markdown",
                            disable_web_page_preview=True
                        )
                    except:
                        pass
                else:
                    try:
                        msg = await bot.send_message(
                            chat_id=CHAT_ID,
                            text=msg_text,
                            parse_mode="Markdown",
                            disable_web_page_preview=True
                        )
                        active_spreads[spread_key] = {
                            "message_id": msg.message_id,
                            "coin": coin,
                            "buy_ex": buy_ex,
                            "sell_ex": sell_ex,
                            "net_info": net_info
                        }
                    except:
                        pass

async def main_scanner():
    global_tickers = {}
    exchanges = {}
    logger.info("Инициализация бирж...")
    for ex_id in EXCHANGES_LIST:
        try:
            config = EXCHANGE_CONFIGS.get(ex_id, {})
            ex_class = getattr(ccxt, ex_id)
            instance = ex_class({**config, 'enableRateLimit': True, 'timeout': 20000})
            await instance.load_markets()
            exchanges[ex_id] = instance
            asyncio.create_task(watch_exchange_tickers(instance, ex_id, global_tickers))
            logger.info(f"✓ {ex_id} загружен с WS")
        except Exception as e:
            logger.warning(f"✗ {ex_id}: {e}")
    while True:
        try:
            current_time = time.time()
            fresh_keys = set()
            for symbol, data in list(global_tickers.items()):
                await process_single_symbol(symbol, data, exchanges, fresh_keys)
            for k in list(active_spreads.keys()):
                if k not in fresh_keys:
                    try:
                        await bot.delete_message(chat_id=CHAT_ID, message_id=active_spreads[k]["message_id"])
                    except:
                        pass
                    active_spreads.pop(k, None)
            await asyncio.sleep(4)
        except Exception as e:
            logger.error(f"Main scanner error: {e}")
            await asyncio.sleep(10)

if __name__ == '__main__':
    threading.Thread(target=run_health_server, daemon=True).start()
    asyncio.run(main_scanner())
