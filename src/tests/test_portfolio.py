import pytest
import logging

from pricing.Market import Market
from pricing.Portfolio import Portfolio

# Enable visible logs when running tests
logging.basicConfig(level=logging.INFO)

@pytest.fixture
def market():
    """Create a simple market with one product."""
    m = Market(["AAPL"])
    m.update({"id": "AAPL", "price": 100})
    return m


@pytest.fixture
def portfolio(market):
    """Create a fresh portfolio with $10,000 cash."""
    return Portfolio(10000, market, leverage_limit=2.0)


def test_buy_within_leverage(portfolio):
    """Buying within leverage limit should succeed."""
    result = portfolio.buy("AAPL", 100)  # cost = 10,000
    assert result is True, "Expected buy to succeed within leverage limit"
    summary = portfolio.summary()
    assert summary["leverage"] <= portfolio.leverage_limit
    assert summary["cash"] == 0
    assert summary["positions"]["AAPL"] == 100


def test_buy_exceed_leverage(portfolio):
    """Buying too much should fail due to leverage restriction."""
    # First, buy some to use up leverage
    assert portfolio.buy("AAPL", 100) is True
    # Then, try to exceed limit
    result = portfolio.buy("AAPL", 150)  # would exceed 2x leverage
    assert result is False, "Expected buy to fail when exceeding leverage"
    # Position should remain unchanged
    assert portfolio.positions["AAPL"] == 100


def test_short_within_leverage(portfolio):
    """Short selling within leverage limit should succeed."""
    result = portfolio.sell("AAPL", 100)  # short 100 shares at 100
    assert result is True, "Expected short sell within leverage limit to succeed"
    summary = portfolio.summary()
    assert summary["leverage"] <= portfolio.leverage_limit
    assert portfolio.positions["AAPL"] == -100
    assert pytest.approx(summary["cash"], rel=1e-3) == 20000  # received proceeds


def test_short_exceed_leverage(portfolio):
    """Short selling too much should fail due to leverage limit."""
    # Try to short too large a position
    result = portfolio.sell("AAPL", 300)  # short 300 shares → leverage > 2x
    assert result is False, "Expected short sell to fail due to leverage limit"
    assert "AAPL" not in portfolio.positions or portfolio.positions["AAPL"] == 0


# --- New Test Case for Combined Long and Short Positions ---

@pytest.fixture
def market_two_products():
    """Market with two products."""
    m = Market(["AAPL", "TSLA"])
    m.update({"id": "AAPL", "price": 100})
    m.update({"id": "TSLA", "price": 200})
    return m

@pytest.fixture
def portfolio_two_products(market_two_products):
    """Portfolio with $10,000 cash."""
    return Portfolio(10000, market_two_products, leverage_limit=2.0)

def test_combined_long_short_two_products(portfolio_two_products):
    """
    Test combined long and short positions across two products.
    Ensure leverage limit is enforced correctly.
    """
    # Buy 50 AAPL shares (cost = 50 * 100 = 5,000)
    assert portfolio_two_products.buy("AAPL", 50) is True

    # Short 40 TSLA shares (proceeds = 40 * 200 = 8,000)
    # Gross exposure = 5,000 + 8,000 = 13,000
    # Leverage = 13,000 / 10,000 = 1.3x < 2x => should succeed
    assert portfolio_two_products.sell("TSLA", 40) is True

    # Attempt to buy more AAPL to exceed leverage
    # Buy 50 more AAPL shares (cost = 80 * 100 = 8,000)
    # New gross exposure = |130 AAPL|*100 + |40 TSLA|*200 = 13,000 + 8,000 = 23,000
    # Leverage = 23,000 / 10,000 = 2.3x > 2x => should fail
    result = portfolio_two_products.buy("AAPL", 80)
    assert result is False, "Expected buy to fail because combined leverage exceeds limit"