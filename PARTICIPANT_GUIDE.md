# Trading Competition — Participant Guide

Welcome to the competition\! This guide explains how to develop your strategy, test it locally, and submit it for evaluation.

## 1\. How Your Strategy is Evaluated

Your submission is run in a secure, event-driven AWS Lambda environment. The process is:

1.  **Submission**: You upload a `submission/` folder containing your `submission.py` file.
2.  **Factory Call**: The evaluator imports your `submission.py` and calls your factory function `build_trader(universe: list[str])`. This must return your trader object.
3.  **Event Loop**: The evaluator reads a hidden test data file batch by batch. For each batch, it calls your trader's primary method: `on_quote(market: Market, portfolio: Portfolio)`.
4.  **Interface**: Your trader must interact with the provided `market` and `portfolio` objects to get prices and execute trades.
5.  **Scoring**: Your final score is the **annualized Sharpe ratio** of your portfolio's NAV history over the backtest.

### The `submission.py` Interface

Your *only* submitted file, `submission/submission.py`, **must** provide three things:

1.  **A `Product` Class**: You must define a class that inherits from `pricing.Product` and implements the `present_value(self, market: Market) -> float` method. This is how the evaluator knows the value of your positions.
2.  **A Trader Class**: This class must have an `on_quote(self, market: Market, portfolio: Portfolio)` method. This is your main logic loop.
3.  **A `build_trader` Function**: This function must return an instance of your Trader Class.

The `pricing` modules (`Product`, `Position`, `Market`, `Portfolio`) are **mocked and provided for you** in the Lambda environment. You just need to import and use them.

## 2\. Local Development

You can develop and test your strategy locally using the provided `src/` directory, which mirrors the cloud environment's class structure.

1.  **Set up Environment**:
    ```bash
    python -m venv .venv
    source .venv/bin/activate  # or .\.venv\Scripts\activate on Windows
    pip install -r requirements.txt
    ```
2.  **Write Your Strategy**: You can write your strategy in a separate file (e.g., `my_strategy.py`) that follows the `src/strategies/Strategy.py` abstract class.
3.  **Test Locally**: Use the `src/Engine.py` backtester to run your strategy against a local data file. You will need to write a small script to configure and run the engine with your strategy.

**Note:** The local `src/Engine.py` is a helper. Your final *submission* must be a single `submission.py` file that uses the `pricing` imports, as shown in the example below.

## 3\. Your `submission.py` File (Example)

Use this as a template for your `submission/submission.py`:

```python
# --- These imports are provided by the Lambda environment ---
from pricing.Product import Product
from pricing.Position import Position
from pricing.Market import Market
from pricing.Portfolio import Portfolio

# --- 1. Define Your Product Class ---
class MyFX(Product):
    """A simple Product that gets its price from the market quotes."""
    def __init__(self, id: str):
        super().__init__(id)

    def present_value(self, market: Market) -> float:
        """Reads the 'price' from the quote provided by the evaluator."""
        if self.id not in market.quotes:
            return 0.0
        return market.quotes[self.id]['price']

# --- 2. Define Your Trader Class ---
class MyTrader:
    """A simple moving average crossover trader."""
    def __init__(self, universe: list[str]):
        self.products = {ric: MyFX(ric) for ric in universe}
        
        # Store price history
        self.history = {ric: [] for ric in universe}
        self.fast_ma = 5
        self.slow_ma = 20
        print(f"MyTrader initialized for {universe}")

    def on_quote(self, market: Market, portfolio: Portfolio):
        """This is called on every new batch of quotes."""
        
        ric = "EURUSD" # Trade only one product for simplicity
        if ric not in market.quotes:
            return

        # --- 1. Update Data ---
        price = market.quotes[ric]['price']
        self.history[ric].append(price)
        if len(self.history[ric]) > self.slow_ma:
            self.history[ric].pop(0) # Keep history bounded
        else:
            return # Not enough data to trade

        # --- 2. Calculate Signals ---
        fast = sum(self.history[ric][-self.fast_ma:]) / self.fast_ma
        slow = sum(self.history[ric]) / len(self.history[ric])
        
        has_position = ric in portfolio.positions

        # --- 3. Execute Trades ---
        try:
            # Go Long
            if fast > slow and not has_position:
                pos = Position(self.products[ric], quantity=100)
                portfolio.enter(pos)
                
            # Go Flat
            elif fast < slow and has_position:
                portfolio.exit(ric)
                
        except Exception as e:
            # Portfolio.enter/exit can fail (e.g., insufficient funds)
            print(f"Trade Error: {e}")

# --- 3. Define the Factory Function (REQUIRED) ---
def build_trader(universe: list[str]) -> MyTrader:
    """This function is called by the evaluator to get your trader."""
    return MyTrader(universe)


## 4\. How to Submit

1.  **Get Credentials**: Your host will provide you with:

      * `AWS_REGION`
      * `AWS_ACCESS_KEY_ID`
      * `AWS_SECRET_ACCESS_KEY`
      * `SUBMISSIONS_BUCKET`
      * `PARTICIPANT_ID`

2.  **Create `.env` File**: Create a file named `.env` in the root of the `quant-trading-competition` directory. Paste your credentials into it.

    ```
    AWS_REGION=eu-central-1
    SUBMISSIONS_BUCKET=your-comp-submissions-unique
    PARTICIPANT_ID=your-unique-id
    AWS_ACCESS_KEY_ID=...
    AWS_SECRET_ACCESS_KEY=...
    ```

3.  **Run Submission Script**: From the root directory, run `tools/submit.py`.

    ```bash
    python tools/submit.py
    ```

    You can also provide a custom label for your submission:

    ```bash
    SUBMISSION_ID=my-first-try python tools/submit.py
    ```

    ### Alternative: use the Docker helper image
   The repository's Docker image packages all Python dependencies and adds two helper commands (`submit` and `local-eval`). Build it once from the project root, then run submissions or local evaluations without installing anything locally:
   ```bash
   docker build -t trading-comp-env .
   docker run --rm --env-file .env -v "${PWD}:/usr/src/app" trading-comp-env submit
   ```

## 5\. Rules & Guidelines

  * **File**: You must submit a single `submission/submission.py`.
  * **Timeout**: Your submission has **15 minutes** (900 seconds) to run. If it exceeds this, it will fail.
  * **Available Libraries**: The Lambda environment includes the Python 3.11 standard library, `boto3`, **`numpy`**, and **`pandas`**. You *cannot* import other libraries like `scikit-learn` or `xgboost`.
  * **Error Handling**: If your `on_quote` function raises an exception, the evaluator will catch it, log it, and move to the next data batch. Your backtest will continue, but you may miss trades.

## 6. Local Evaluation

You can test your `submission.py` file locally using the exact same evaluation logic as the cloud environment. This helps you debug and see the expected performance metrics before submitting.

1.  **Prepare Data:** Make sure the competition data file is located at `data/comp_data.csv` relative to the project root.
2.  **Ensure `submission.py` is Ready:** Place your final code in the `submission/submission.py` file.
3.  **Run the Local Evaluator:** From the project's root directory, run the `local_eval.py` script, providing the path to your submission file.

    ```bash
    # Run evaluation using data/comp_data.csv and submission/submission.py
    python local_eval.py submission/submission.py
    ```

    Using the Docker helper image (defaults to `submission/submission.py` if you omit the argument):

    ```bash
    docker run --rm -v "${PWD}:/usr/src/app" trading-comp-env local-eval
    ```

4.  **Check Output:** The script will:
    * Load your `submission.py`.
    * Read and process `data/comp_data.csv`.
    * Run the backtest, printing any logs or errors generated by your `on_quote` method.
    * Print the final performance metrics (Sharpe Ratio, PnL, etc.), calculated exactly as they are in the cloud evaluator.

This allows you to iterate quickly and confirm your strategy behaves as expected before using one of your official submissions.

Good luck\!
