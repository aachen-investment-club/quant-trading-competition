from abc import ABC, abstractmethod


class Product(ABC):
    def __init__(self: "Product", id: str) -> None:
        self.id: str = id

    @abstractmethod
    def present_value() -> None:
        raise NotImplementedError("Derived class should implement present_value()")
