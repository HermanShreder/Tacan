import asyncio
import ccxt.async_support as ccxt
import time
from collections import defaultdict
from telegram import Bot
from telegram.ext import Application, CommandHandler

# ================= CONFIG =================
TELEGRAM_TOKEN = "PUT_TOKEN"
CHAT_ID = "PUT_CHAT_ID"

TRADE_SIZE = 500

MIN_SPREAD = 2.5
MIN_VOLUME = 60000
SCAN_DELAY = 15

BLACKLIST = {"USDT","USDC","DAI","TUSD","BUSD","WBTC","WETH"}

bot = Bot(token=TELEGRAM_TOKEN)

exchanges = {}
cache = {}

# ================= PAPER BALANCES =================
balances = defaultdict(lambda: 2000.0)   # per exchange USDT
total_pnl = 0.0

trade_journal = []

EX_LIST = ["binance","bybit","okx","gate","kucoin","bitget","mexc","htx","whitebit"]

# ================= INIT =================
async def init():
    for ex in EX_LIST:
        try:
            obj = getattr(ccxt, ex)({
                "enableRateLimit": True,
                "timeout": 20000
            })
            await obj.load_markets()
            exchanges[ex] = obj
        except:
            pass

# ================= LIQUIDITY =================
async def liquidity(ex, sym):
    try:
        ob = await ex.fetch_order_book(sym, limit=30)
        asks = ob["asks"]
        bids = ob["bids"]

        def calc(side):
            need = TRADE_SIZE
            cost = 0
            amt = 0

            for p, v in side:
                val = p * v
                if cost + val >= need:
                    rest = need - cost
                    amt += rest / p
                    cost += rest
                    break
                else:
                    cost += val
                    amt += v

            if cost < need:
                return None

            return cost / amt

        buy = calc(asks)
        sell = calc(bids)

        if not buy or not sell:
            return None

        return buy, sell

    except:
        return None

# ================= EXECUTION =================
def execute_trade(coin, b_ex, s_ex, entry, exit_price, net):
    global total_pnl

    cost = TRADE_SIZE

    balances[b_ex] -= cost
    profit = net

    balances[s_ex] += cost + profit

    total_pnl += profit

    trade_journal.append({
        "coin": coin,
        "buy": b_ex,
        "sell": s_ex,
        "entry": entry,
        "exit": exit_price,
        "pnl": profit,
        "time": time.time()
    })

# ================= SCAN =================
async def scan():
    global total_pnl

    while True:
        data = {}

        async def fetch(ex):
            try:
                t = await exchanges[ex].fetch_tickers()

                for sym, v in t.items():
                    if "/USDT" not in sym:
                        continue

                    coin = sym.split("/")[0]

                    if coin in BLACKLIST:
                        continue

                    vol = float(v.get("quoteVolume") or 0)
                    if vol < MIN_VOLUME:
                        continue

                    bid = v.get("bid") or 0
                    ask = v.get("ask") or 0

                    if not bid or not ask:
                        continue

                    data.setdefault(sym, {})[ex] = {"bid": bid, "ask": ask}

            except:
                pass

        await asyncio.gather(*[fetch(e) for e in exchanges])

        best = None

        for sym, exd in data.items():
            if len(exd) < 2:
                continue

            coin = sym.split("/")[0]

            buys = sorted(exd.items(), key=lambda x: x[1]["ask"])
            sells = sorted(exd.items(), key=lambda x: x[1]["bid"], reverse=True)

            b_ex, b = buys[0]
            s_ex, s = sells[0]

            if b_ex == s_ex:
                continue

            spread = (s["bid"] - b["ask"]) / b["ask"] * 100

            if spread < MIN_SPREAD:
                continue

            key = f"{coin}_{b_ex}_{s_ex}"

            if key in cache and time.time() - cache[key] < 60:
                continue

            cache[key] = time.time()

            liq = await liquidity(exchanges[b_ex], sym)
            if not liq:
                continue

            pb, ps = liq

            gross = (TRADE_SIZE / pb) * ps - TRADE_SIZE
            net = gross * 0.99  # fee buffer

            if balances[b_ex] < TRADE_SIZE:
                continue

            # ================= EXECUTE PAPER TRADE =================
            execute_trade(coin, b_ex, s_ex, pb, ps, net)

            best = {
                "coin": coin,
                "b": b_ex,
                "s": s_ex,
                "net": net,
                "spread": spread
            }

        if best:
            msg = (
                f"⚡ v8 PAPER TRADE {best['coin']}\n"
                f"{best['b']} → {best['s']}\n"
                f"SPREAD {best['spread']:.2f}%\n"
                f"PROFIT ${best['net']:.2f}\n"
                f"TOTAL PNL ${total_pnl:.2f}"
            )

            try:
                await bot.send_message(CHAT_ID, msg)
            except:
                pass

        await asyncio.sleep(SCAN_DELAY)

# ================= TELEGRAM =================
async def start(update, ctx):
    await update.message.reply_text("v8 PAPER TRADING ACTIVE")

async def stats(update, ctx):
    msg = f"""
TOTAL PNL: ${total_pnl:.2f}

BALANCES:
"""
    for k,v in balances.items():
        msg += f"{k}: ${v:.2f}\n"

    msg += f"\nTRADES: {len(trade_journal)}"

    await update.message.reply_text(msg)

# ================= MAIN =================
async def main():
    await init()

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))

    asyncio.create_task(scan())

    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
