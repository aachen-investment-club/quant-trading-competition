"""
Portfolio management module for trading simulation.

This module defines the Portfolio class, which manages cash and positions,
enforcing leverage limits and providing methods to buy and sell products.

Author: Mathis Makarski + ChatGPT
Date: 2025-11-02
"""

import logging
from pricing.Market import Market

logger = logging.getLogger("local_eval")

class Portfolio():
    def __init__(self, cash: float, market: "Market", leverage_limit: float) -> None:
        self.cash: float = cash
        self.market: Market = market
        self.positions: dict[str, int] = {}  # key: product, value: quantity
        self.leverage_limit: float = leverage_limit  # max leverage allowed

    def _get_price(self, product: str) -> float:
        """Retrieve the last market price for a given product."""
        if product not in self.market.quotes:
            raise ValueError(f"No quote available for {product}")
        return self.market.quotes[product].get("price", None)
    
    def _get_timestep(self, product) -> int:
        """Retrieve the current market timestep for the product quote."""
        if product not in self.market.quotes:
            raise ValueError(f"No quote available for {product}")
        return self.market.quotes[product].get("timestep", None)

    def _gross_exposure(self) -> float:
        """Compute gross exposure = sum(|position| * price)"""
        total = 0.0
        for product, qty in self.positions.items():
            price = self._get_price(product)
            total += abs(qty) * price
        return total

    def _net_asset_value(self) -> float:
        """Compute portfolio net asset value = cash + sum(qty * price)"""
        value = self.cash
        for product, qty in self.positions.items():
            price = self._get_price(product)
            value += qty * price
        return value
    
    def _leverage(self) -> float:
        """Compute current leverage = gross exposure / net asset value"""
        gross = self._gross_exposure()
        net_value = self._net_asset_value()
        return gross / max(net_value, 1e-8)  # Avoid division by zero

    def _check_leverage(self, new_cash: float, new_positions: dict[str, int]) -> bool:
        """Check whether the new portfolio state respects leverage limits."""
        gross = sum(abs(qty) * self._get_price(p) for p, qty in new_positions.items())
        net_value = new_cash + sum(qty * self._get_price(p) for p, qty in new_positions.items())
        leverage = gross / max(net_value, 1e-8)
        return leverage <= self.leverage_limit

    def buy(self, product: str, quantity: int) -> bool:
        """Attempt to buy `quantity` units of `product`."""
        timestep = self._get_timestep(product)
        price = self._get_price(product)
        cost = price * quantity

        new_cash = self.cash - cost
        new_positions = self.positions.copy()
        new_positions[product] = new_positions.get(product, 0) + quantity

        if not self._check_leverage(new_cash, new_positions):
            logger.warning(f"{timestep} | Trade rejected: leverage limit exceeded.")
            return False

        self.cash = new_cash
        self.positions = new_positions
        logger.info(f"{timestep} | BOUGHT {quantity} {product} @ {price} | new cash={self.cash:.2f}")
        return True

    def sell(self, product: str, quantity: int) -> bool:
        """Attempt to sell `quantity` units of `product` (shorts allowed)."""
        timestep = self._get_timestep(product)
        price = self._get_price(product)
        proceeds = price * quantity

        new_cash = self.cash + proceeds
        new_positions = self.positions.copy()
        new_positions[product] = new_positions.get(product, 0) - quantity

        if not self._check_leverage(new_cash, new_positions):
            logger.warning(f"{timestep} | Trade rejected: leverage limit exceeded.")
            return False

        self.cash = new_cash
        self.positions = new_positions
        logger.info(f"{timestep} | SOLD {quantity} {product} @ {price} | new cash={self.cash:.2f}")
        return True

    def summary(self) -> dict:
        """Return a snapshot of the portfolio."""
        return {
            "cash": self.cash,
            "positions": self.positions,
            "gross_exposure": self._gross_exposure(),
            "net_value": self._net_asset_value(),
            "leverage": self._leverage(),
        }

    def __str__(self) -> str:
        return str(self.summary())

