from __future__ import annotations
import types

# --- Participant Imports ---
# These modules are mocked by the evaluator_lambda.py and will only
# be available when running inside the Lambda environment.
try:
    from pricing.Product import Product
    from pricing.Position import Position
    from pricing.Market import Market
    from pricing.Portfolio import Portfolio
except ImportError:
    print("Failed to import backtest modules. Are you running locally?")
    # Define dummy classes for local linting/type-checking if needed
    class Product: pass
    class Position: pass
    class Market: pass
    class Portfolio: pass

# --- 1. Define a Product ---
# Participants MUST define a concrete Product class so the
# evaluator's Portfolio can call .present_value()

class SimpleFX(Product):
    """A simple product implementation that reads from market quotes."""
    def __init__(self: "SimpleFX", id: str) -> None:
        super().__init__(id)

    def present_value(self: "SimpleFX", market: Market) -> float:
        """
        Gets the current price from the market quotes.
        The Lambda's CSV reader provides 'price' and 'data'.
        """
        if self.id not in market.quotes:
            return 0.0  # No price available yet
        
        # Use the 'price' field provided by the Lambda's CSV reader
        return market.quotes[self.id]['price']

# --- 2. Define the Trader ---
# This object will be instantiated by the factory
class TestTrader:
    """
    A simple test trader that:
    - Buys 100 EURUSD if it sees the price > 1.1 and has no position.
    - Sells all EURUSD if it sees the price < 1.05 and has a position.
    """
    def __init__(self, universe: list[str]):
        self.universe = universe
        self.products = {}
        for ric in universe:
            self.products[ric] = SimpleFX(ric)
            
        print(f"TestTrader initialized for universe: {universe}")

    def on_quote(self, market: Market, portfolio: Portfolio) -> None:
        """
        This is the main event loop called by the evaluator.
        """
        # We only care about INTERESTingProduct for this test
        ric = "INTERESTingProduct"
        if ric not in self.products or ric not in market.quotes:
            # Not enough data to trade
            return

        price = market.quotes[ric]['price']
        
        # Check if we already have a position
        has_position = ric in portfolio.positions

        # --- Entry Logic ---
        if not has_position and price > 1.1:
            print(f"Price {price} > 1.1. Entering position.")
            try:
                # Create a new position object
                pos = Position(self.products[ric], quantity=100)
                # Enter the position
                portfolio.enter(pos)
            except Exception as e:
                print(f"Error entering position: {e}")

        # --- Exit Logic ---
        elif has_position and price < 1.05:
            print(f"Price {price} < 1.05. Exiting position.")
            try:
                # Exit the position by its ID
                portfolio.exit(ric)
            except Exception as e:
                print(f"Error exiting position: {e}")

# --- 3. Define the Factory Function ---
# The evaluator_lambda.py will call this function!
def build_trader(universe: list[str]) -> TestTrader:
    """
    Factory function to build and return the trader instance.
    """
    return TestTrader(universe)