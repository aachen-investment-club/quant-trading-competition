import pandas as pd
from tqdm import tqdm
import os

# own modules
from pricing.Portfolio import Portfolio
from pricing.Market import Market
from datastream.Datastream import Datastream
from datastream.EODSource import EODSource
from strategies.Strategy import Strategy


class Engine():
    def __init__(self, universe: list[str], data: dict, strategy: Strategy) -> None:

        # create datasources
        sources = []
        for ric in universe:
            sources.append(EODSource(ric, data[ric]))

        # create datasource manager
        self.datastream: Datastream = Datastream(
            data_sources=sources,
            clock_cycle=pd.Timedelta(days=1)
        )

        # set strategy, portfolio and market
        self.strategy: Strategy = strategy
        self.portfolio: Portfolio = self.strategy.portfolio
        self.market: Market = self.strategy.portfolio.market

        # backtest results
        self.portfolio_nav: dict[pd.timestep, float] = {}


    def run(self) -> None:
        
        # loop through data
        with tqdm(total=self.datastream.total_data_obj) as pbar:  # init progress bar
            while True:

                # get next data object
                quote_batch = self.datastream.pop_next_batch()

                # break if done
                if not quote_batch:
                    break
                
                # update market with all quotes in batch
                is_clock_tick = False
                for quote in quote_batch:
                    self.market.update(quote)
                    if quote['id'] == 'Clock':
                        is_clock_tick = True
                
                # --- THIS IS THE KEY CHANGE ---
                # Call strategy once per batch, matching the Lambda's logic
                try:
                    self.strategy.on_quote(self.market, self.portfolio)
                except Exception as e:
                    print(f"Strategy Error: {e}")
                    # swallow strategy exceptions
                    pass

                # track backtest results
                if is_clock_tick:
                    clock_ts = next(q['timestep'] for q in quote_batch if q['id'] == 'Clock')
                    self.portfolio_nav[clock_ts] = self.portfolio.nav()

                # update progress bar
                pbar.update(len(quote_batch))

        # returns = pd.Series(self.portfolio_nav).pct_change().dropna()

    def save(self, dir: str) -> None:
        # (save logic as before)
        ...