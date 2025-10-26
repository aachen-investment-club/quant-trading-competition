from abc import ABC, abstractmethod
from pricing.Portfolio import Portfolio
from pricing.Market import Market


class Strategy(ABC):
    def __init__(self: "Strategy", name: str, portfolio: Portfolio) -> None:
        self.name: str = name  # name of the strategy
        self.portfolio: Portfolio = portfolio

    @abstractmethod
    def on_quote(self: "Strategy", market: Market, portfolio: Portfolio) -> None:
        raise NotImplementedError("Derived class should implement on_quote()")