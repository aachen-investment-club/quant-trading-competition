from abc import ABC, abstractmethod
import pandas as pd

class Strategy(ABC):
    """Abstract base class for trading strategies."""

    @abstractmethod
    def fit(self, df: pd.DataFrame) -> None:
        """Optional: fit on training data (participants do this locally)."""
        pass

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """Return Series of signals in {-1, 0, +1} indexed like df."""
        pass
