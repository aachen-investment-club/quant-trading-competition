from __future__ import annotations

# --- Participant Imports ---
# These modules are mocked by the evaluator_lambda.py and will only
# be available when running inside the Lambda environment.
try:
    from pricing.Market import Market
    from pricing.Portfolio import Portfolio
except ImportError:
    print("Failed to import backtest modules. Are you running locally?")
    # Define dummy classes for local linting/type-checking if needed
    class Market: pass
    class Portfolio: pass

# --- Setup Logger ---
import logging
logger = logging.getLogger("local_eval")

# --- Define the Trader ---
# This object will be instantiated by the factory function
class TestTrader:
    """
    Here you will define your trading strategy. 

    The TestTrader provides a simple example strategy that:
    - BUYS INTERESTingProduct if it sees the price < 3.0 and has no position.
    - SELLS INTERESTingProducts if it sees the price > 4.5 and has a position.
    """
    def __init__(self) -> None:
        logger.debug("TestTrader initialized.")
        # You can add more initialization logic here if needed.

    def on_quote(self, market: Market, portfolio: Portfolio) -> None:
        """
        This is the main event loop called by the evaluator.
        """
        
        #--- INTERESTingProduct Logic ---
        product = "INTERESTingProduct"

        # Check if we already have a position
        has_long_position = product in portfolio.positions and portfolio.positions[product] > 0
        has_short_position = product in portfolio.positions and portfolio.positions[product] < 0

        price = market.quotes[product]['price']

        # BUY Logic
        if not has_long_position and price < 3.0:
            portfolio.buy(product, 10000)

        # SELL Logic
        elif not has_short_position and price > 4.5:
            portfolio.sell(product, 10000)


        #--- James_Fund_007 Logic ---
        product = "James_Fund_007"

        has_long_position = product in portfolio.positions and portfolio.positions[product] > 0 

        if not has_long_position:
            portfolio.buy(product, 1000)


        # logger.debug(portfolio)  # this will log the total portfolio state


# --- Define the Factory Function ---
# The evaluator_lambda.py will call this function!
def build_trader(universe) -> TestTrader:
    return TestTrader(universe)