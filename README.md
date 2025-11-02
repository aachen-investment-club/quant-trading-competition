# AIC Quant Trading Competition — Participant Guide 🚀

**Welcome to the Aachen Investment Club's (AIC) internal Quant Trading Competition\!**

We're excited to have you here. This competition is a fun way to learn about and practice algorithmic trading. Don't worry if you're new to this—this guide is designed to be beginner-friendly and walk you through every step, from setup to submission.

Please find a team partner in our list on notion. The goal is to design, test, and submit a trading strategy.

This guide explains how to use the provided Docker environment to develop your strategy, test it locally, and submit it for evaluation. Let's get started\!

-----

## 1\. How Your Strategy is Evaluated

Your submission is run in a secure, event-driven AWS Lambda environment. The process is:

1.  **Submission**: You upload a `submission/` folder containing your `submission.py` file.
2.  **Factory Call**: The evaluator imports your `submission.py` and calls your factory function `build_trader(universe: list[str])`. This must return your trader object.
3.  **Event Loop**: The evaluator reads a hidden test data file (like a CSV of prices) one step at a time. For each step (or "batch"), it calls your trader's primary method: `on_quote(market: Market, portfolio: Portfolio)`.
4.  **Interface**: Your trader must interact with the provided `market` and `portfolio` objects to get prices and execute trades.
5.  **Scoring**: Your final score is the **Sharpe ratio** of your portfolio's NAV history over the backtest.

### The `submission.py` Interface

Your *only* submitted file, `submission/submission.py`, **must** provide three things:

1.  **A `Product` Class**: You must define a class that inherits from `pricing.Product` and implements the `present_value(self, market: Market) -> float` method. This is how the evaluator's portfolio simulation knows the value of your positions.
2.  **A Trader Class**: This class must have an `on_quote(self, market: Market, portfolio: Portfolio)` method. This is your main logic loop.
3.  **A `build_trader` Function**: This function must return an instance of your Trader Class.

The `pricing` modules (`Product`, `Position`, `Market`, `Portfolio`) are **mocked and provided for you** in the Lambda environment. You just need to import and use them.

-----

## 2\. Local Development Setup (Docker)

All local development and testing should be done using the provided Docker environment. This ensures your code runs with the exact same dependencies as the cloud evaluator.

1.  **Build the Docker Image**:
    From the root of the project, run the build command. This reads the `Dockerfile`, installs all dependencies from `requirements.txt`, and sets up the helper commands.

    ```bash
    docker build -t trading-comp-env .
    ```

3.  **Get the latest test data**:
    From the root of the project, run the docker command. This downloads the latest train data file and stores it into /data in your root directory.

    ```bash
    # For PowerShell
    docker run --rm --env-file .env -v "${PWD}:/usr/src/app" trading-comp-env sync-data

    # For macOS/Linux (note the quotes)
    docker run --rm --env-file .env -v "$(pwd):/usr/src/app" trading-comp-env sync-data
    ```


You now have two main options for local development: data exploration with Jupyter or backtesting your `submission.py`.

-----

## 3\. Data Exploration (Jupyter & VS Code)

To explore the data or experiment with models, you can run a Jupyter server inside the Docker container and connect to it directly from VS Code.
1. **Install the Jupyter Extension for VS Code**
    Go the extensions tab on the left side and install the Jupyter extension from Microsoft.
2.  **Run the Jupyter Server**:
    Run the container to start the Jupyter server. This command also mounts your current directory (`-v`) and forwards the port (`-p`).

    ```bash
    docker run --rm -p 127.0.0.1:8888:8888 -v "${PWD}:/usr/src/app" trading-comp-env jupyter notebook --ip=0.0.0.0 --port=8888 --no-browser --allow-root
    ```

3.  **Connect VS Code**:

      * In the terminal output from the previous step, **copy the URL** that includes the token (it looks like `http://127.0.0.1:8888/?token=...`).
      * Create or open a Jupyter Notebook file (e.g., notebooks/my_analysis.ipynb).
      * In the top-right corner of the notebook, click the "Select Kernel" button.
      * From the dropdown, choose "Jupyter Server".
      * Select "Existing" from the next list.
      * Paste the full URL (with token) you copied from your terminal and press Enter.
    You can now run code in your notebook, and it will execute inside the Docker container with all the correct libraries.
-----

## 4\. Local Backtest Evaluation

This is the most important step for debugging\! It lets you test your `submission/submission.py` file locally using the exact same evaluation logic as the cloud environment. This helps you find bugs and see the expected performance metrics before submitting.

1.  **Prepare Data:** Make sure the competition data file is located at `data/comp_data.csv` relative to the project root.

2.  **Ensure `submission.py` is Ready:** Place your final code in the `submission/submission.py` file.

3.  **Run the Local Evaluator:**
    The Docker container provides a helper command `local-eval`. Run it from the project's root directory:

    ```bash
    # Run evaluation using data/comp_data.csv and submission/submission.py
    # For PowerShell
    docker run --rm -v "${PWD}:/usr/src/app" trading-comp-env local-eval

    # For macOS/Linux
    docker run --rm -v "$(pwd):/usr/src/app" trading-comp-env local-eval
    ```

    This command automatically defaults to using `submission/submission.py` as the input file.

4.  **Check Output:** The script will:

      * Load your `submission.py`.
      * Read and process `data/comp_data.csv`.
      * Run the backtest, printing any logs or errors generated by your `on_quote` method.
      * Print the final performance metrics (Sharpe Ratio, PnL, etc.). This lets you see how your strategy is performing before you submit it.

This allows you to iterate quickly and confirm your strategy behaves as expected before using one of your official submissions.

-----

## 5\. Your `submission.py` File (Example)

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
        
        ric = "PRODUCT_A" # Trade only one product for simplicity
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
```

-----

## 6\. How to Submit

The Docker image packages all dependencies and adds a helper command `submit`.

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

3.  **Run Submission Script**: From the root directory, run the `submit` command via Docker. This will securely use your `.env` file and upload your `submission/` directory.

    ```bash
    # For PowerShell
    docker run --rm --env-file .env -v "${PWD}:/usr/src/app" trading-comp-env submit

    # For macOS/Linux
    docker run --rm --env-file .env -v "$(pwd):/usr/src/app" trading-comp-env submit
    ```

-----

## 7\. Rules & Guidelines

  * **File**: You must submit a single `submission/submission.py`.
  * **Timeout**: Your submission has **15 minutes** (900 seconds) to run. If it exceeds this, it will fail.
  * **Available Libraries**: The Lambda environment is lightweight\! It only includes the Python 3.11 standard library, `boto3`, **`numpy`**, and **`pandas`**. Libraries like `scikit-learn` or `xgboost` are available in your local Docker environment for *training* models, but **cannot be imported** in your final `submission.py`.
  * **Error Handling**: If your `on_quote` function raises an exception, the evaluator will catch it, log it, and move to the next data batch. Your backtest will continue, but you may miss trades.

Good luck\!