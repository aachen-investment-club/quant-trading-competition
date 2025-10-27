import pandas as pd
import numpy as np
from tqdm import tqdm
import os
import time
from decimal import Decimal
import traceback

# --- Use relative imports if running scripts from parent dir ---
from .pricing.Portfolio import Portfolio
from .pricing.Market import Market

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
        # --- Store pre-processed data directly ---
        self.data_batches = data_batches
        self.total_data_points = sum(len(batch) for batch in data_batches)

        # set strategy, portfolio and market
        self.market: Market = Market(universe)
        self.portfolio: Portfolio = Portfolio(cash=initial_cash, market=self.market)

        # Build the strategy using the provided builder function
        try:
            self.strategy = strategy_builder(self.universe)
            print(f"Successfully built trader: {type(self.strategy).__name__}")
        except Exception as e:
            print(f"ERROR: Failed to build trader from submission.py: {e}")
            traceback.print_exc()
            raise

        self.nav_history: list[float] = [initial_cash]

    # --- MODIFIED run ---
    def run(self) -> None:
        if not hasattr(self.strategy, 'on_quote'):
             print("ERROR: The trader object built by build_trader() does not have an 'on_quote' method.")
             return

        print("Starting local backtest...")
        # --- Iterate directly through pre-processed batches ---
        with tqdm(total=self.total_data_points) as pbar:
            for quote_batch in self.data_batches:
                if not quote_batch: # Skip empty batches if any
                    continue