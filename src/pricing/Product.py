from abc import ABC, abstractmethod
from pricing.Market import Market


class Product(ABC):
    def __init__(self: "Product", id: str) -> None:
        self.id: str = id

    @abstractmethod
    def present_value(self: "Product", market: Market) -> float:
        raise NotImplementedError("Derived class should implement present_value()")