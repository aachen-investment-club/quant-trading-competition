import pandas as pd
import numpy as np
import traceback
import logging

# --- Use relative imports if running scripts from parent dir ---
from .pricing.Portfolio import Portfolio
from .pricing.Market import Market

logger = logging.getLogger("local_eval")

# --- Helper function copied from evaluator_lambda.py ---
def calculate_sharpe_ratio(nav_history, periods_per_year=252):
    """
    Calculates the annualized Sharpe ratio from a list of NAVs.
    Assumes risk-free rate is 0.
    """
    if not nav_history or len(nav_history) < 2:
        return 0.0
    nav_series = pd.Series(nav_history)
    returns = nav_series.pct_change().dropna()
    if returns.empty or returns.std() == 0:
        return 0.0
    mean_return = returns.mean()
    annualized_mean_return = mean_return * periods_per_year
    std_dev = returns.std()
    annualized_std_dev = std_dev * np.sqrt(periods_per_year)
    if annualized_std_dev == 0:
        return 0.0
    sharpe = annualized_mean_return / annualized_std_dev
    return float(sharpe)
# --- End helper function ---

class Engine():
    def __init__(self, universe: list[str], data_batches: list[list[dict]], strategy_builder, initial_cash=100000.0) -> None:
        self.initial_cash = initial_cash
        self.universe = universe

        # Store pre-processed data directly
        self.data_batches = data_batches
        self.total_data_points = sum(len(batch) for batch in data_batches)

        # Set strategy, portfolio and market
        self.market: Market = Market(universe)
        self.portfolio: Portfolio = Portfolio(cash=initial_cash, market=self.market, leverage_limit=10.0)

        # Build the strategy using the provided builder function
        try:
            self.strategy = strategy_builder(universe)
            logger.debug(f"Successfully built trader: {type(self.strategy).__name__}")
        except Exception as e:
            logger.error(f"ERROR: Failed to build trader from submission.py: {e}")
            traceback.print_exc()
            raise

        self.nav_history: list[float] = [initial_cash]

    def run(self) -> None:
        if not hasattr(self.strategy, 'on_quote'):
             logger.error("ERROR: The trader object built by build_trader() does not have an 'on_quote' method.")
             return

        logger.debug("Running local evlauation...")
        
        # --- Iterate directly through pre-processed batches ---
        for quote_batch in self.data_batches:
            
            # 1. Update market with all quotes in the batch
            # (The batch includes quotes for all products at one timestamp)
            for q in quote_batch:
                self.market.update(q)

            # 2. Call the trader's logic ONCE per batch
            # This mimics the cloud lambda's event-driven approach
            try:
                self.strategy.on_quote(self.market, self.portfolio)
            except Exception as e:
                # Log errors locally to help debugging
                logger.error(f"\n--- ERROR during on_quote ---")
                traceback.print_exc()
                logger.error("--------------------------------\n")
                # Mimic the cloud's behavior of swallowing exceptions
                pass 
            
            # 3. Record NAV history after the batch
            self.nav_history.append(self.portfolio._net_asset_value())
