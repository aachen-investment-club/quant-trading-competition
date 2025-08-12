from backtest.pricing.Product import Product
from backtest.pricing.Market import Market


class Stock(Product):
    def __init__(self: "Stock", id: str) -> None:
        super().__init__(id)  # call the constructor of the parent class

    def present_value(self: "Stock", market: Market) -> None:
        ''' Present value of a stock is the current trading price'''
        return market.quotes[self.id]['data']['Price Close']
    
    def __str__(self: "Stock") -> str:
        return self.id + " " + str(self.present_value())
