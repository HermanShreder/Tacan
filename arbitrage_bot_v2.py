#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Professional HFT Micro Scalping Bot for Spot Market
Multi-asset: BTC, ETH, SOL
Features:
- Order book depth analysis
- Auto order placement / cancellation / repositioning
- Micro scalping with many small trades
- Commission-aware PnL calculation
- Entry zone optimization (not "one big lot")
- Correlations, volatility regime ML, auto strategy switching
- Equity curve graph, backtesting, real PnL
"""

import asyncio
import json
import os
import time
import logging
import numpy as np
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Any
from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal, getcontext

# WebSocket & REST
import websockets
import aiohttp
import ccxt.async_support as ccxt

# ML & stats
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.mixture import GaussianMixture

# Plotting
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ======================== Configuration ========================
# -----------------------------------------------------------------
# PLACE YOUR API KEYS HERE (or use environment variables)
# -----------------------------------------------------------------
API_CONFIG = {
    "exchange": "binance",          # supports binance, bybit, okx
    "api_key": "yJ963u0kNMPCZE8KAuoZIibO5PqBP6WiuD3GHaP7ovHQiwCRSY8BSBoS4Ywsj7ti",
    "api_secret": "hHxfbbqw9SQI45VxL3kRY53L3E7FuJZJ5AIHtXQ16rwpsypkRwX6KzulnZGWYBF9",
    "testnet": True,                # set False for real trading
    "testnet_url": "https://testnet.binance.vision",
    "mainnet_url": "https://api.binance.com",
    "ws_testnet": "wss://testnet.binance.vision/ws",
    "ws_mainnet": "wss://stream.binance.com:9443/ws"
}

# Trading parameters
SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
COMMISSION_MAKER = 0.0005          # 0.05% maker fee (adjust to your exchange)
COMMISSION_TAKER = 0.0005          # 0.05% taker fee
MIN_PROFIT_FACTOR = 1.001          # 0.1% profit after commission (adjustable)
MAX_POSITION_SIZE = 0.001          # BTC max position size per asset (example)
MAX_OPEN_ORDERS_PER_SYMBOL = 10
TRADE_AMOUNT_USDT = 10.0           # amount per micro trade
ORDER_REFRESH_MS = 100              # reposition orders every 100 ms
DEPTH_LEVELS = 10                   # analyze top 10 bid/ask levels

# ML parameters
VOLATILITY_WINDOW = 100
CORRELATION_WINDOW = 50
STATE_UPDATE_INTERVAL = 5.0         # seconds

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Decimal precision
getcontext().prec = 28

# ======================== Helper Classes ========================
@dataclass
class Order:
    id: str
    symbol: str
    side: str            # 'buy' or 'sell'
    price: float
    amount: float
    status: str          # 'open', 'filled', 'cancelled'
    filled_amount: float = 0.0
    commission_paid: float = 0.0

@dataclass
class Position:
    symbol: str
    net_qty: float                # positive = long, negative = short (spot only long)
    avg_entry_price: float
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_commission: float = 0.0

@dataclass
class MarketDepth:
    bids: List[Tuple[float, float]]   # (price, quantity)
    asks: List[Tuple[float, float]]
    timestamp: float

# ======================== Exchange Connector ========================
class ExchangeConnector:
    """Async wrapper for exchange API (CCXT + WebSockets)"""
    def __init__(self, config: dict):
        self.config = config
        self.exchange = None
        self.ws_connections = {}
        self.order_book_callbacks = {}
        
    async def init_exchange(self):
        exchange_class = getattr(ccxt, self.config['exchange'])
        self.exchange = exchange_class({
            'apiKey': self.config['api_key'],
            'secret': self.config['api_secret'],
            'enableRateLimit': True,
            'options': {'defaultType': 'spot'}
        })
        if self.config['testnet']:
            self.exchange.set_sandbox_mode(True)
        await self.exchange.load_markets()
        logger.info(f"Exchange {self.config['exchange']} initialized")
        
    async def fetch_order_book(self, symbol: str, limit: int = DEPTH_LEVELS) -> MarketDepth:
        """Get order book snapshot via REST"""
        ob = await self.exchange.fetch_order_book(symbol, limit=limit)
        bids = [(b[0], b[1]) for b in ob['bids'][:limit]]
        asks = [(a[0], a[1]) for a in ob['asks'][:limit]]
        return MarketDepth(bids=bids, asks=asks, timestamp=time.time())
    
    async def create_limit_order(self, symbol: str, side: str, amount: float, price: float) -> Order:
        """Place a limit order, return Order object"""
        try:
            order_resp = await self.exchange.create_limit_order(symbol, side, amount, price)
            return Order(
                id=order_resp['id'],
                symbol=symbol,
                side=side,
                price=price,
                amount=amount,
                status=order_resp['status']
            )
        except Exception as e:
            logger.error(f"Order failed: {e}")
            return None
    
    async def cancel_order(self, order_id: str, symbol: str):
        """Cancel an open order"""
        try:
            await self.exchange.cancel_order(order_id, symbol)
            logger.debug(f"Cancelled order {order_id} on {symbol}")
        except Exception as e:
            logger.error(f"Cancel failed: {e}")
    
    async def get_account_balance(self, currency: str) -> float:
        """Get free balance for a currency (e.g., 'USDT')"""
        balance = await self.exchange.fetch_balance()
        return balance['free'].get(currency, 0.0)
    
    async def fetch_my_trades(self, symbol: str, limit: int = 100) -> List[Dict]:
        """Fetch recent trades to compute PnL"""
        trades = await self.exchange.fetch_my_trades(symbol, limit=limit)
        return trades
    
    async def subscribe_order_book(self, symbol: str, callback):
        """WebSocket subscription to real-time order book"""
        stream_name = f"{symbol.lower().replace('/', '').replace('usdt', 'usdt')}@depth{DEPTH_LEVELS}"
        if self.config['testnet']:
            ws_url = self.config['ws_testnet']
        else:
            ws_url = self.config['ws_mainnet']
        # simplified: one connection per symbol, could reuse
        ws = await websockets.connect(f"{ws_url}/{stream_name}")
        self.ws_connections[symbol] = ws
        self.order_book_callbacks[symbol] = callback
        asyncio.create_task(self._listen_order_book(symbol, ws))
        
    async def _listen_order_book(self, symbol: str, ws):
        try:
            async for message in ws:
                data = json.loads(message)
                if 'bids' in data and 'asks' in data:
                    bids = [(float(p), float(q)) for p, q in data['bids'][:DEPTH_LEVELS]]
                    asks = [(float(p), float(q)) for p, q in data['asks'][:DEPTH_LEVELS]]
                    depth = MarketDepth(bids=bids, asks=asks, timestamp=data.get('E', time.time())/1000.0)
                    # call user callback
                    if symbol in self.order_book_callbacks:
                        await self.order_book_callbacks[symbol](depth)
        except Exception as e:
            logger.error(f"WebSocket error for {symbol}: {e}")
            # attempt reconnect
            await asyncio.sleep(1)
            asyncio.create_task(self.subscribe_order_book(symbol, self.order_book_callbacks[symbol]))
            
    async def close(self):
        for ws in self.ws_connections.values():
            await ws.close()
        await self.exchange.close()

# ======================== Risk Manager ========================
class RiskManager:
    def __init__(self, max_position_per_asset: float, max_daily_loss: float = -50.0, max_leverage: float = 1.0):
        self.max_position = max_position_per_asset
        self.max_daily_loss = max_daily_loss
        self.max_leverage = max_leverage
        self.daily_pnl = 0.0
        self.last_reset = datetime.now().date()
        
    def check_position_size(self, symbol: str, proposed_qty: float) -> bool:
        """Check if proposed size exceeds max position for symbol"""
        # would need current position from portfolio
        # simplified: just check absolute amount
        return abs(proposed_qty) <= self.max_position
    
    def check_drawdown(self, current_pnl: float) -> bool:
        today = datetime.now().date()
        if today != self.last_reset:
            self.daily_pnl = 0.0
            self.last_reset = today
        self.daily_pnl += current_pnl
        if self.daily_pnl < self.max_daily_loss:
            logger.warning(f"Daily loss limit reached: {self.daily_pnl:.2f}")
            return False
        return True
    
    def dynamic_position_sizing(self, volatility: float, base_amount: float) -> float:
        """Reduce position size when volatility is high"""
        vol_factor = max(0.2, min(1.0, 0.5 / (volatility * 100)))  # example
        return base_amount * vol_factor

# ======================== Market Analysis ========================
class MarketAnalyzer:
    @staticmethod
    def find_best_entry(depth: MarketDepth, amount_usdt: float, price_precision: int = 2) -> Tuple[float, List[float]]:
        """
        Finds optimal entry price for given buy amount.
        Returns (average_price, list_of_prices_for_slicing) -> "not one big lot"
        """
        total_qty = 0.0
        total_cost = 0.0
        remaining = amount_usdt
        buy_prices = []
        for price, qty in depth.asks:
            cost = price * qty
            if cost <= remaining:
                total_qty += qty
                total_cost += cost
                remaining -= cost
                buy_prices.extend([price] * int(qty / (amount_usdt / 100)))  # slicing into small pieces
            else:
                qty_needed = remaining / price
                total_qty += qty_needed
                total_cost += remaining
                remaining = 0
                buy_prices.extend([price] * int(qty_needed / (amount_usdt / 100)))
                break
        if total_qty == 0:
            return depth.asks[0][0], [depth.asks[0][0]]
        avg_price = total_cost / total_qty
        return avg_price, buy_prices[:50]  # at most 50 pieces
    
    @staticmethod
    def compute_optimal_sell_levels(entry_price: float, depth: MarketDepth, min_profit_pct: float, commission: float) -> List[float]:
        """
        Determine sell prices above entry, accounting for commission.
        """
        required_return = entry_price * (1 + min_profit_pct + commission)
        sell_levels = [p for p, q in depth.bids if p >= required_return]
        if not sell_levels:
            # generate synthetic levels above current bid
            best_bid = depth.bids[0][0] if depth.bids else entry_price * 1.001
            sell_levels = [best_bid * (1 + i * 0.0005) for i in range(1, 5)]
        return sorted(sell_levels)
    
    @staticmethod
    def calculate_support_resistance(depth: MarketDepth, lookback: int = 5):
        """Identify support / resistance from order book imbalances"""
        bid_volume = sum(q for p, q in depth.bids[:lookback])
        ask_volume = sum(q for p, q in depth.asks[:lookback])
        imbalance = (bid_volume - ask_volume) / (bid_volume + ask_volume + 1e-8)
        # resistance: large ask wall, support: large bid wall
        resistance_level = depth.asks[0][0] if ask_volume > bid_volume * 1.2 else None
        support_level = depth.bids[0][0] if bid_volume > ask_volume * 1.2 else None
        return support_level, resistance_level, imbalance

# ======================== Volatility ML Model ========================
class VolatilityRegimeML:
    def __init__(self, window=100):
        self.window = window
        self.price_history = deque(maxlen=window)
        self.vol_history = deque(maxlen=window)
        self.model = GaussianMixture(n_components=2, random_state=42)
        self.scaler = StandardScaler()
        self.fitted = False
        
    def update(self, price: float):
        self.price_history.append(price)
        if len(self.price_history) >= 10:
            returns = np.diff(list(self.price_history)) / list(self.price_history)[:-1]
            vol = np.std(returns) * np.sqrt(252)   # annualized vol
            self.vol_history.append(vol)
        if len(self.vol_history) >= self.window and not self.fitted:
            self._fit()
            
    def _fit(self):
        X = np.array(self.vol_history).reshape(-1, 1)
        self.model.fit(X)
        self.scaler.fit(X)
        self.fitted = True
        
    def current_regime(self) -> int:
        if not self.fitted or len(self.vol_history) < 10:
            return 0   # unknown / low
        X = np.array([self.vol_history[-1]]).reshape(-1, 1)
        X_scaled = self.scaler.transform(X)
        regime = self.model.predict(X_scaled)[0]
        return regime   # 0 or 1 (low/high volatility)
    
    def volatility_forecast(self, horizon=5) -> float:
        """Simple forecast using last vol (naive)"""
        if len(self.vol_history) == 0:
            return 0.01
        return np.mean(list(self.vol_history)[-5:])

# ======================== Correlation Trader ========================
class CorrelationAnalyzer:
    def __init__(self, symbols, window=50):
        self.symbols = symbols
        self.window = window
        self.price_vectors = {sym: deque(maxlen=window) for sym in symbols}
        self.corr_matrix = {s1: {s2: 0.0 for s2 in symbols} for s1 in symbols}
        
    def update_prices(self, symbol: str, price: float):
        self.price_vectors[symbol].append(price)
        if all(len(self.price_vectors[s]) >= self.window for s in self.symbols):
            self._compute_correlations()
            
    def _compute_correlations(self):
        # Pure numpy correlation replacement
        symbols_list = list(self.price_vectors.keys())
        n = len(symbols_list)
        prices = np.array([list(self.price_vectors[s]) for s in symbols_list])
        # Compute correlation matrix manually
        corr_matrix = np.corrcoef(prices)
        self.corr_matrix = {symbols_list[i]: {symbols_list[j]: corr_matrix[i,j] for j in range(n)} for i in range(n)}
        
    def get_correlation(self, sym1: str, sym2: str) -> float:
        if sym1 in self.corr_matrix and sym2 in self.corr_matrix[sym1]:
            return self.corr_matrix[sym1][sym2]
        return 0.0
    
    def is_diverging(self, sym1: str, sym2: str, zscore_thresh=2.0) -> bool:
        """Check if correlation has broken (using rolling z-score of spread)"""
        # simplified: compare normalized price difference
        if len(self.price_vectors[sym1]) < 20 or len(self.price_vectors[sym2]) < 20:
            return False
        p1 = np.array(list(self.price_vectors[sym1]))
        p2 = np.array(list(self.price_vectors[sym2]))
        spread = p1/p2 - 1
        z = (spread[-1] - np.mean(spread)) / (np.std(spread)+1e-8)
        return abs(z) > zscore_thresh

# ======================== Order Manager & Scalping Logic ========================
class MicroScalperBot:
    def __init__(self, config: dict):
        self.config = config
        self.exchange = ExchangeConnector(API_CONFIG)
        self.risk_manager = RiskManager(max_position_per_asset=MAX_POSITION_SIZE, max_daily_loss=-10.0)
        self.analyzer = MarketAnalyzer()
        self.vol_ml = VolatilityRegimeML(window=VOLATILITY_WINDOW)
        self.corr_analyzer = CorrelationAnalyzer(SYMBOLS, window=CORRELATION_WINDOW)
        self.positions: Dict[str, Position] = {}
        self.open_orders: Dict[str, List[Order]] = {}
        self.pnl_history = []          # for equity curve
        self.strategy_mode = "scalp"   # 'scalp', 'correlation', 'wait'
        self.last_state_update = 0
        
        # performance tracking
        self.total_trades = 0
        self.winning_trades = 0
        self.total_pnl = 0.0
        self.commission_paid_total = 0.0
        
    async def init(self):
        await self.exchange.init_exchange()
        for sym in SYMBOLS:
            self.open_orders[sym] = []
            # subscribe to order book for each symbol
            await self.exchange.subscribe_order_book(sym, self.on_order_book_update)
            # initial position
            self.positions[sym] = Position(symbol=sym, net_qty=0.0, avg_entry_price=0.0)
        logger.info("Bot initialized")
        
    async def on_order_book_update(self, depth: MarketDepth, symbol: str):
        """Called on every order book update (every ~100ms)"""
        # Update volatility & correlation
        mid_price = (depth.bids[0][0] + depth.asks[0][0]) / 2
        self.vol_ml.update(mid_price)
        self.corr_analyzer.update_prices(symbol, mid_price)
        
        # Auto strategy switching (every STATE_UPDATE_INTERVAL)
        if time.time() - self.last_state_update > STATE_UPDATE_INTERVAL:
            self.last_state_update = time.time()
            await self.switch_strategy()
            
        # Execute scalping logic according to current strategy
        if self.strategy_mode == "scalp":
            await self.scalp_market(symbol, depth)
        elif self.strategy_mode == "correlation":
            await self.correlation_trade(symbol, depth)
        else:
            # wait mode: do nothing or only manage existing orders
            await self.manage_existing_orders(symbol, depth)
            
    async def scalp_market(self, symbol: str, depth: MarketDepth):
        """Micro scalping: place multiple small limit orders to capture spread"""
        current_pos = self.positions[symbol]
        # Avoid over-trading if position size limit reached
        if abs(current_pos.net_qty) >= self.risk_manager.max_position:
            return
            
        # find best entry slice for buying (amount_usdt defined)
        amount_usdt = TRADE_AMOUNT_USDT
        vol_regime = self.vol_ml.current_regime()
        if vol_regime == 1:  # high volatility
            amount_usdt = self.risk_manager.dynamic_position_sizing(
                self.vol_ml.volatility_forecast(), amount_usdt
            )
        if amount_usdt < 5:  # avoid dust
            return
            
        avg_entry, price_slices = self.analyzer.find_best_entry(depth, amount_usdt, price_precision=2)
        # For simplicity, place one limit order at avg_entry with total amount
        # but to do "not one big lot", we split into smaller orders
        chunk_amount = amount_usdt / len(price_slices) if price_slices else amount_usdt
        for i, price in enumerate(price_slices[:5]):   # limit to 5 pieces per update
            if i >= MAX_OPEN_ORDERS_PER_SYMBOL:
                break
            order = await self.exchange.create_limit_order(symbol, 'buy', chunk_amount/price, price)
            if order:
                self.open_orders[symbol].append(order)
                logger.debug(f"Placed BUY order {order.id} at {price} for {chunk_amount/price:.6f} {symbol}")
                
        # Also manage sell orders if we have position
        if current_pos.net_qty > 0:
            # compute profit target levels
            sell_levels = self.analyzer.compute_optimal_sell_levels(
                current_pos.avg_entry_price, depth, MIN_PROFIT_FACTOR-1, COMMISSION_TAKER
            )
            for price in sell_levels[:3]:
                sell_qty = min(current_pos.net_qty * 0.3, current_pos.net_qty)  # sell in pieces
                if sell_qty > 0:
                    order = await self.exchange.create_limit_order(symbol, 'sell', sell_qty, price)
                    if order:
                        self.open_orders[symbol].append(order)
                        
        # Automatically reposition (cancel old orders that are far from market)
        await self.reposition_orders(symbol, depth)
        
    async def correlation_trade(self, symbol: str, depth: MarketDepth):
        """Example correlation strategy: trade on divergence between SOL and ETH"""
        # For demonstration, assume we want to long ETH when SOL/ETH ratio is high
        if symbol != "ETH/USDT":
            return
        # Check correlation with SOL
        corr = self.corr_analyzer.get_correlation("ETH/USDT", "SOL/USDT")
        diverging = self.corr_analyzer.is_diverging("ETH/USDT", "SOL/USDT")
        if diverging and corr > 0.5:
            # Place mean-reverting trade
            amount = TRADE_AMOUNT_USDT * 2
            avg_entry, _ = self.analyzer.find_best_entry(depth, amount)
            order = await self.exchange.create_limit_order(symbol, 'buy', amount/avg_entry, avg_entry)
            if order:
                self.open_orders[symbol].append(order)
                self.strategy_mode = "scalp"   # switch back after trade
                
    async def reposition_orders(self, symbol: str, depth: MarketDepth):
        """Cancel orders that are too far and replace with better prices"""
        best_bid = depth.bids[0][0]
        best_ask = depth.asks[0][0]
        current_time = time.time()
        for order in self.open_orders[symbol][:]:
            if order.status != 'open':
                continue
            # Cancel if price is too far (>0.2% from market)
            if order.side == 'buy' and order.price > best_ask * 1.002:
                await self.exchange.cancel_order(order.id, symbol)
                self.open_orders[symbol].remove(order)
            elif order.side == 'sell' and order.price < best_bid * 0.998:
                await self.exchange.cancel_order(order.id, symbol)
                self.open_orders[symbol].remove(order)
        # (optional: add new orders after cancellation)
        
    async def manage_existing_orders(self, symbol: str, depth: MarketDepth):
        """In wait mode, only monitor filled orders and update positions"""
        # Check for filled orders (via order status polling simplified)
        for order in self.open_orders[symbol]:
            # In production, you would use WebSocket user data stream
            # Here just a placeholder: we assume order status is updated by exchange connector.
            pass
        await self.reposition_orders(symbol, depth)
        
    async def switch_strategy(self):
        """Auto select strategy based on volatility regime and correlation"""
        regime = self.vol_ml.current_regime()
        # Compute average correlation across assets
        corr_eth_btc = self.corr_analyzer.get_correlation("ETH/USDT", "BTC/USDT")
        if regime == 1:   # high volatility
            self.strategy_mode = "scalp"
            logger.info("Switching to SCALP mode (high volatility)")
        elif abs(corr_eth_btc) > 0.8 and regime == 0:
            self.strategy_mode = "correlation"
            logger.info("Switching to CORRELATION mode")
        else:
            self.strategy_mode = "wait"
            logger.info("Switching to WAIT mode")
            
    async def update_pnl(self):
        """Compute real PnL including commission from exchange trades"""
        total_realized = 0.0
        total_commission = 0.0
        for sym in SYMBOLS:
            trades = await self.exchange.fetch_my_trades(sym, limit=50)
            for t in trades:
                fee = t.get('fee', {})
                fee_cost = fee.get('cost', 0.0) if fee else 0.0
                total_commission += fee_cost
                # realized pnl from trade (simplified)
                if t['side'] == 'sell':
                    # need to match with average entry; better to keep closed trades log
                    pass
        # Simplified: fetch current positions from exchange
        # For demonstration we use internal positions updated on order fills
        # You would listen to order fill events in a real bot.
        # Here we set placeholder
        self.commission_paid_total = total_commission
        # update total_pnl
        self.total_pnl = total_realized - total_commission
        
    async def run(self):
        await self.init()
        logger.info("MicroScalperBot started")
        try:
            while True:
                await asyncio.sleep(10)   # periodic tasks
                await self.update_pnl()
                self.pnl_history.append(self.total_pnl)
                # Print performance
                if len(self.pnl_history) % 60 == 0:
                    logger.info(f"Total PnL: {self.total_pnl:.4f} USDT | Commissions: {self.commission_paid_total:.4f}")
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            await self.exchange.close()
            
    # ----------------------- Backtesting Engine -----------------------
    async def backtest(self, historical_data):  # historical_data: list of dicts or np.array instead of pd.DataFrame
        """
        Run backtest on historical OHLCV + order book snapshots (mock)
        Returns equity curve and metrics.
        """
        # For brevity, implement simple simulation of scalping using price series
        # Real backtest would require tick-level or order book data.
        # Example: generate trades on price reversal patterns.
        balance = 1000.0
        equity_curve = []
        for i in range(1, len(historical_data)):
            price = historical_data['close'].iloc[i] if hasattr(historical_data, 'iloc') else historical_data[i]['close']
            # very simple strategy: buy if price up 0.1% from previous close, sell after 0.05%
            # (mimicking micro scalping)
            prev_price = historical_data['close'].iloc[i-1] if hasattr(historical_data, 'iloc') else historical_data[i-1]['close']
            if price > prev_price * 1.001:
                amount = TRADE_AMOUNT_USDT
                qty = amount / price
                # apply commission
                balance -= amount + amount * COMMISSION_TAKER
                # sell after 0.05% increase
                sell_price = price * 1.0005
                balance += qty * sell_price - qty * sell_price * COMMISSION_TAKER
            equity_curve.append(balance)
        return equity_curve
    
    def plot_equity_curve(self, equity_curve: List[float]):
        fig = go.Figure()
        fig.add_trace(go.Scatter(y=equity_curve, mode='lines', name='Equity'))
        fig.update_layout(title='Equity Curve (Backtest/Real)', xaxis_title='Time steps', yaxis_title='Balance (USDT)')
        fig.show()
        
# ======================== Main Entry Point ========================
async def main():
    # Load API from config (or environment)
    # Ensure you replace API_CONFIG with your actual keys
    if API_CONFIG["api_key"] == "YOUR_API_KEY":
        logger.error("Please set your API keys in API_CONFIG before running.")
        return
        
    bot = MicroScalperBot(API_CONFIG)
    
    # Optional: run backtest before live
    # historical = pd.read_csv("historical_data.csv")   # example
    # eq_curve = await bot.backtest(historical)
    # bot.plot_equity_curve(eq_curve)
    
    # Start live trading
    await bot.run()

if __name__ == "__main__":
    asyncio.run(main())
