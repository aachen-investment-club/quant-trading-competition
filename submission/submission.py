from __future__ import annotations

try:
    from pricing.Market import Market
    from pricing.Portfolio import Portfolio
except ImportError:
    class Market: pass
    class Portfolio: pass

import logging
logger = logging.getLogger("local_eval")

class TestTrader:
    def __init__(self, universe: None) -> None: 
        logger.debug("TestTrader initialized.")
        self.universe = universe
        self.fast_window = 5
        self.slow_window = 50 
        self.base_size = 100
        self.history = []

    def on_quote(self, market: Market, portfolio: Portfolio) -> None:
        # Check if required products exist
        if "INTERESTingProduct" not in market.quotes or "James_Fund_007" not in market.quotes:
            return

        # Get latest prices
        quote_interest = market.quotes["INTERESTingProduct"]["price"]
        quote_fund = market.quotes["James_Fund_007"]["price"]

        # Save data
        self.history.append(quote_interest)

        # Need enough points for both MAs
        if len(self.history) < self.slow_window:
            return

        # ✅ Manual moving average calculation (no pandas)
        fast_ma = sum(self.history[-self.fast_window:]) / self.fast_window
        slow_ma = sum(self.history[-self.slow_window:]) / self.slow_window

        # --- MOMENTUM LOGIC ---

        # BUY signal: fast MA crosses above slow MA
        if fast_ma > slow_ma:
            position_size = self.base_size

            # Optional dynamic sizing based on trend strength
            trend_strength = abs(fast_ma - slow_ma)
            position_size *= (1 + trend_strength)

            portfolio.buy("James_Fund_007", int(position_size))

        # SELL signal: fast MA crosses below slow MA
        elif fast_ma < slow_ma:
            position_size = self.base_size

            trend_strength = abs(fast_ma - slow_ma)
            position_size *= (1 + trend_strength)

            portfolio.sell("James_Fund_007", int(position_size))

def build_trader(universe=None) -> TestTrader: 
    if universe is None:
        universe = ["INTERESTingProduct", "James_Fund_007"]
    return TestTrader(universe)