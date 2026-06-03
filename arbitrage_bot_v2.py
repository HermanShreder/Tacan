import asyncio
import ccxt.pro as ccxtpro
import ccxt.async_support as ccxt
import logging
from telegram import Bot
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- НАСТРОЙКИ (ТВОЙ ID И ТЗ) ---
TELEGRAM_TOKEN = "7930993307:AAHuIxRVgr9OD7ZP_D2dbrbEu-JGBdZSnc4"
CHAT_ID = "5253808709"  
MIN_VOLUME_USD = 100000  # Возвращаем $100k по ТЗ
TRADE_SIZE_USD = 500     # Возвращаем круг $500 по ТЗ
MIN_SPREAD_PCT = 1.0     # Минимальный чистый спред 1% по ТЗ

bot = Bot(token=TELEGRAM_TOKEN)
EXCHANGES_LIST = ['binance', 'bybit', 'okx', 'gate', 'kucoin', 'bitget', 'mexc', 'bingx', 'htx', 'kraken']
active_spreads = {}

class HealthCheckServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"Bot is scanning ALL spot markets!")

def run_health_server():
    try:
        server = HTTPServer(('0.0.0.0', 10000), HealthCheckServer)
        server.serve_forever()
    except Exception as e:
        logging.error(f"Ошибка фейк-сервера: {e}")

async def get_effective_price_and_fees(exchange_obj, symbol, side, target_amount_usd):
    try:
        orderbook = await exchange_obj.fetch_order_book(symbol, limit=20)
        orders = orderbook['asks'] if side == 'buy' else orderbook['bids']
        
        try:
            market = exchange_obj.market(symbol)
            taker_fee_pct = market.get('taker', 0.001)
        except:
            taker_fee_pct = 0.002
        
        total_usd = 0
        total_crypto = 0
        for price, amount in orders:
            cost = price * amount
            if total_usd + cost >= target_amount_usd:
                needed_usd = target_amount_usd - total_usd
                total_crypto += needed_crypto = needed_usd / price
                total_usd += needed_usd
                break
            else:
                total_usd += cost
                total_crypto += amount
        if total_usd < target_amount_usd: return None, 0, 0
        avg_price = total_usd / total_crypto
        return avg_price, total_usd, (target_amount_usd * taker_fee_pct)
    except:
        return None, 0, 0

async def check_networks_and_contracts(coin, ex_buy, ex_sell):
    try:
        buy_curr = ex_buy.currencies.get(coin, {}) if (hasattr(ex_buy, 'currencies') and ex_buy.currencies) else {}
        sell_curr = ex_sell.currencies.get(coin, {}) if (hasattr(ex_sell, 'currencies') and ex_sell.currencies) else {}
        
        if not buy_curr.get('withdraw', True) or not sell_curr.get('deposit', True): return None
        contract_buy = buy_curr.get('address') or buy_curr.get('info', {}).get('contractAddress')
        contract_sell = sell_curr.get('address') or sell_curr.get('info', {}).get('contractAddress')
        
        if contract_buy and contract_sell and str(contract_buy).lower() != str(contract_sell).lower(): return None
        best_network = "AUTO/MAINNET"
        withdraw_fee_crypto = buy_curr.get('fee', 0.0)
        if 'networks' in buy_curr and isinstance(buy_curr['networks'], dict):
            for net_name, net_data in buy_curr['networks'].items():
                if net_data.get('withdraw') and sell_curr.get('networks', {}).get(net_name, {}).get('deposit'):
                    best_network = net_name
                    withdraw_fee_crypto = net_data.get('fee', 0.0)
                    break
        return {"status": "🔓 ОТКРЫТО", "network": best_network, "withdraw_fee_crypto": withdraw_fee_crypto, "time": "3-5 мин"}
    except:
        return {"status": "🔓 ОТКРЫТО", "network": "AUTO/MAINNET", "withdraw_fee_crypto": 0.0, "time": "3-5 мин"}

async def validate_active_spreads(initialized_exchanges):
    to_delete = []
    for spread_id, data in list(active_spreads.items()):
        coin, ex_buy_id, ex_sell_id = spread_id.split('_')
        symbol = f"{coin}/USDT"
        if ex_buy_id not in initialized_exchanges or ex_sell_id not in initialized_exchanges: continue
        try:
            p_buy, _, _ = await get_effective_price_and_fees(initialized_exchanges[ex_buy_id], symbol, 'buy', TRADE_SIZE_USD)
            p_sell, _, _ = await get_effective_price_and_fees(initialized_exchanges[ex_sell_id], symbol, 'sell', TRADE_SIZE_USD)
            still_valid = False
            if p_buy and p_sell:
                if (((p_sell - p_buy) / p_buy) * 100) >= MIN_SPREAD_PCT: still_valid = True
            if not still_valid:
                try: 
                    await bot.delete_message(chat_id=CHAT_ID, message_id=data["message_id"])
                    await asyncio.sleep(0.05)
                except: pass
                to_delete.append(spread_id)
        except: to_delete.append(spread_id)
    for sp_id in to_delete: del active_spreads[sp_id]

async def scan_markets():
    while True:
        logging.info("🔄 Шаг 1: Подключение к биржам...")
        exchanges = {}
        all_usdt_symbols = set()
        
        # Подключаем биржи и собираем ВСЕ их монеты
        for ex_id in EXCHANGES_LIST:
            try:
                ex_class = getattr(ccxt, ex_id)
                ex_instance = ex_class({'enableRateLimit': True})
                await ex_instance.load_markets()
                
                if ex_instance.markets and isinstance(ex_instance.markets, dict):
                    exchanges[ex_id] = ex_instance
                    # Фильтруем только СПОТ и только к USDT
                    for sym, market_data in ex_instance.markets.items():
                        if market_data.get('spot') and sym.endswith('/USDT'):
                            all_usdt_symbols.add(sym)
                else:
                    await ex_instance.close()
            except Exception as e:
                pass # Пропускаем гео-блокированные биржи без падения скрипта
                
        logging.info(f"📊 Всего уникальных USDT пар обнаружено на биржах: {len(all_usdt_symbols)}")
        
        try:
            # Сканируем абсолютно КАЖДУЮ найденную пару
            for symbol in all_usdt_symbols:
                coin = symbol.split('/')[0] # Получаем чистое имя монеты (например BTC)
                
                # Ищем на каких биржах есть эта пара
                available_exchanges = []
                for ex_id, ex in exchanges.items():
                    if ex.markets and isinstance(ex.markets, dict) and symbol in ex.markets:
                        available_exchanges.append(ex_id)
                        
                if len(available_exchanges) < 2: continue
                
                prices = {}
                for ex_id in available_exchanges:
                    ex = exchanges[ex_id]
                    try:
                        ticker = await ex.fetch_ticker(symbol)
                        if not ticker or ticker.get('quoteVolume', 0) < MIN_VOLUME_USD: continue
                        
                        buy_p, _, b_fee = await get_effective_price_and_fees(ex, symbol, 'buy', TRADE_SIZE_USD)
                        sell_p, _, s_fee = await get_effective_price_and_fees(ex, symbol, 'sell', TRADE_SIZE_USD)
                        if buy_p and sell_p: prices[ex_id] = {'buy': buy_p, 'sell': sell_p, 'b_fee': b_fee, 's_fee': s_fee}
                    except: continue
                
                for ex_buy_id, buy_data in prices.items():
                    for ex_sell_id, sell_data in prices.items():
                        if ex_buy_id == ex_sell_id: continue
                        p_buy, p_sell = buy_data['buy'], sell_data['sell']
                        if (((p_sell - p_buy) / p_buy) * 100) < MIN_SPREAD_PCT: continue
                        
                        spread_id = f"{coin}_{ex_buy_id}_{ex_sell_id}"
                        if spread_id in active_spreads: continue
                        
                        net_info = await check_networks_and_contracts(coin, exchanges[ex_buy_id], exchanges[ex_sell_id])
                        if not net_info: continue
                        
                        fee_buy_trade, fee_sell_trade = buy_data['b_fee'], sell_data['s_fee']
                        fee_withdraw_usd = net_info['withdraw_fee_crypto'] * p_buy
                        total_fees = fee_buy_trade + fee_sell_trade + fee_withdraw_usd
                        
                        net_profit_usd = ((TRADE_SIZE_USD / p_buy) * p_sell - TRADE_SIZE_USD) - total_fees
                        net_spread_pct = (net_profit_usd / TRADE_SIZE_USD) * 100
                        if net_spread_pct < MIN_SPREAD_PCT: continue 
                        
                        link_buy = f"https://{ex_buy_id}.com/trade/{coin}_USDT"
                        link_sell = f"https://{ex_sell_id}.com/trade/{coin}_USDT"
                        
                        msg_text = (
                            f"⚡️ **НАЙДЕН АРБИТРАЖНЫЙ СПРЕД: #{coin}** ⚡️\n━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"🟢 **ПОКУПКА: {ex_buy_id.upper()}**\n💵 Цена: `{p_buy:.4f} USDT`\n📊 Объем: `${TRADE_SIZE_USD}`\n"
                            f"📦 Сеть: `{net_info['network']}` | **{net_info['status']}**\n⏱ Время: ~`{net_info['time']}`\n🔗 [Купить]({link_buy})\n\n"
                            f"🔴 **ПРОДАЖА: {ex_sell_id.upper()}**\n💵 Цена: `{p_sell:.4f} USDT`\n📥 Сеть: `{net_info['network']}` | **{net_info['status']}**\n🔗 [Продать]({link_sell})\n━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"💸 **РАСХОДЫ НА КОМИССИИ:**\n├ Торговые: `${fee_buy_trade + fee_sell_trade:.2f}`\n└ Сеть: `${fee_withdraw_usd:.2f}`\n💰 Всего издержек: `${total_fees:.2f}`\n━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"💎 **ЧИСТАЯ ДОХОДНОСТЬ:**\n💰 Профит: **+${net_profit_usd:.2f}**\n📈 Спред: **{net_spread_pct:.2f}%**\n\n⏳ *Отслеживание актуальности...*"
                        )
                        try:
                            msg = await bot.send_message(chat_id=CHAT_ID, text=msg_text, parse_mode="Markdown", disable_web_page_preview=True)
                            active_spreads[spread_id] = {"message_id": msg.message_id, "start_time": asyncio.get_event_loop().time()}
                            await asyncio.sleep(0.05)
                        except Exception as e: logging.error(f"TG error: {e}")
            await validate_active_spreads(exchanges)
        except Exception as e:
            logging.error(f"Внутренняя ошибка итерации: {e}")
        finally:
            for ex_id, ex in exchanges.items():
                try: await ex.close()
                except: pass
            logging.info("🔒 Круг завершен. Сессии очищены.")
        await asyncio.sleep(5)

if __name__ == '__main__':
    threading.Thread(target=run_health_server, daemon=True).start()
    asyncio.run(scan_markets())
