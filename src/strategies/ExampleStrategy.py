from strategies.Strategy import Strategy
from pricing.Portfolio import Portfolio
from pricing.Position import Position
from pricing.Stock import Stock
from pricing.Market import Market


class ExampleStrategy(Strategy):
    def __init__(self, name: str, portfolio: Portfolio, hyperparams: dict) -> None:
        super().__init__(name, portfolio)  # call the constructor of the parent class
        self.hyperparams: dict = hyperparams  # strategy specific hyperparameters
        
    def on_quote(self: "ExampleStrategy", market: Market, portfolio: Portfolio) -> None:
        
        # This strategy only acts on 'Clock' ticks
        if 'Clock' not in market.quotes:
            return
            
        timestep = market.quotes['Clock']['timestep']

        if timestep == self.hyperparams['buy_date']:
            new_position = Position(Stock(self.hyperparams['ric']), 100)
            portfolio.enter(new_position)

        if timestep == self.hyperparams['sell_date']:
            portfolio.exit("JPM.N")