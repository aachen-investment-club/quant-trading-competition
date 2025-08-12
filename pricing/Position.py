from backtest.pricing.Product import Product
from backtest.pricing.Market import Market


class Position():
    def __init__(self, product: Product, quantity):
        self.product = product
        self.quantity = quantity
        self.price = None

    def mark_to_market(self, market: Market):
        '''Mark to market value of the position'''
        return self.product.present_value(market) * self.quantity

    def rebalance(self, new_price: float, new_quantity: float):
        '''Rebalance position'''
        self.price = (self.price * self.quantity + new_price * new_quantity) / (self.quantity + new_quantity)  # average price
        self.quantity += new_quantity  # add new quantity

    def __str__(self):
        return f"{self.product} {self.quantity} {self.price}"