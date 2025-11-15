# AIC Quant Competition — Participant Guide 🚀

**Welcome to the Aachen Investment Club's internal Quant Competition\!**

We're excited to have you here. This competition is a fun way to learn about and practice algorithmic trading. Don't worry if you're new to this—this guide is designed to be beginner-friendly and walk you through every step, from setup to submission.

Please find a team partner in our list on notion. The goal is to design, test, and submit a trading strategy on synthetic price data.

This guide explains how to use the provided Docker environment to develop your strategy, test it locally, and submit it for evaluation. Let's get started\!

-----

## 1\. How Your Strategy is Evaluated


### Submission Process

Your submission is run in a secure, event-driven AWS Lambda environment. The process is:

1.  **Submission**: You upload a `submission/` folder containing your `submission.py` file. ([see file](submission/submission.py))
2.  **Factory Call**: The evaluator imports your `submission.py` and calls your factory function `build_trader()`. This must return your trader object.
3.  **Event Loop**: The evaluator reads a hidden test data file (like a CSV of prices) one step at a time. For each step (or "batch"), it calls your trader's primary method: `on_quote(market: Market, portfolio: Portfolio)`.
4.  **Interface**: Your trader must interact with the provided `market` and `portfolio` objects to get prices and execute trades.

### Scoring
Your final score is the **Sharpe ratio** \(SR\) of your portfolio’s net asset value over the evaluation period. The Sharpe ratio measures **risk-adjusted return**: it shows how much return your strategy earns for the risk taken. The excess return is just your strategy's returns \(R\) (we assume a risk-free rate \(R_f = 0\)), and the risk is measured by the standard deviation of your returns \(\sigma\).


$$SR = \frac{R - R_f}{\sigma} = \frac{R}{\sigma}$$

## 2. How to build your Strategy

### The `submission.py` Interface
([See file](submission/submission.py))

Your *only* submitted file, `submission/submission.py`, **must** provide two things:

-  **A Trader Class**: This class must have an `on_quote(market: Market, portfolio: Portfolio)` method. This is your main logic loop.
-  **A `build_trader` Function**: This function must return an instance of your Trader Class.

The `pricing` modules (`Market` and `Portfolio`) are **mocked and provided for you** in the Lambda environment. You just need to import and use them like follows.

### The `Market.py` Interface
([See file](src/pricing/Market.py))

How to retrieve the **universe of products** you can trade on:
```py
all_products = market.universe  # returns list[str]
```

How to retrieve **market prices** at the **current timestep**:
```py
quote = market.quotes["INTERESTingProduct"]  # returns a dict: {key: timestep, value: price}
```

### The `Portfolio.py` Interface
([See file](src/pricing/Portfolio.py))

How to **initiate trades**:
```py
# BUY
portfolio.buy(product="INTERESTingProduct", quantity=100)
# SELL
portfolio.sell(product="INTERESTingProduct", quantity=100)
```

**Information** you can retrieve from your portfolio:
```py
cash = portfolio.cash
positions = portfolio.postitions  # returns dict: {key: product, value: quantity}
nav = portfolio._net_asset_value()
gross = portfolio._gross_exposure()
leverage = portfolio._leverage()
```

### Initial Portfolio Settings
You'll start with:
- Initial Cash Amount = 100.000
- Leverage Limit = 10

while
- Leverage = Gross Exposure / Net Asset Value
- Net Asset Value = Cash + Market Value of your Positions
- Gross Exposure = sum over your positions ( | quantity | * market price )

Therefore, as we take the norm of quantity, longs and shorts do not cancel out when computing the leverage. Since this is the first time we host this competition with the given datasets, maybe we have to adjust the leverage limit in future rounds.

-----

## 3\. Local Development Setup (Docker)

*All local development* and testing should be done using the provided *Docker environment*. This ensures your code runs with the exact same dependencies as the cloud evaluator. As a code editor we recommend VS Code

0.  **Install Docker and VS Code**
    * Go to https://code.visualstudio.com/ to install VS Code.
    * Go to https://www.docker.com/products/docker-desktop/ to install Docker Desktop. 

1.  **Build the Docker Image**:
    Make sure the Docker Desktop program is running/open. From the root of the project, run the build command. This reads the `Dockerfile`, installs all dependencies from `requirements.txt`, and sets up the helper commands.

    ```bash
    docker build -t trading-comp-env .
    ```

2.  **Get Credentials**: After you registered your team, your competition host will provide you with:

    * `AWS_REGION`
    * `SUBMISSIONS_BUCKET`
    * `PARTICIPANT_ID`
    * `AWS_ACCESS_KEY_ID`
    * `AWS_SECRET_ACCESS_KEY`

3.  **Create `.env` File**: Create a file named `.env` in the root of the `quant-trading-competition` directory. Paste your credentials into it.

    ```
    AWS_REGION=eu-central-1
    SUBMISSIONS_BUCKET=your-comp-submissions-unique
    PARTICIPANT_ID=your-unique-id
    AWS_ACCESS_KEY_ID=...
    AWS_SECRET_ACCESS_KEY=...
    ```

3.  **Download Train Data**:
    Make sure the Docker Desktop program is running/open. From the root of the project, run the docker command. This downloads the latest train data file and stores it into /data in your root directory.

    ```bash
    # For PowerShell
    docker run --rm --env-file .env -v "${PWD}:/usr/src/app" trading-comp-env sync-data

    # For macOS/Linux (note the quotes)
    docker run --rm --env-file .env -v "$(pwd):/usr/src/app" trading-comp-env sync-data
    ```


You now have two main options for local development: **data exploration** with Jupyter or **evaluating** your `submission.py` on the downloaded train data.

-----

## 4\. Data Exploration (Jupyter & VS Code)

To explore the data or experiment with models, you can run a Jupyter server inside the Docker container and connect to it directly from VS Code.
1. **Install the Jupyter Extension for VS Code**
    Go the extensions tab on the left side and install the Jupyter extension from Microsoft.
2.  **Run the Jupyter Server**:
    Run the container to start the Jupyter server. This command also mounts your current directory (`-v`) and forwards the port (`-p`).
    Make sure the Docker Desktop program is running/open. 
    ```bash
    docker run --rm -p 127.0.0.1:8888:8888 -v "${PWD}:/usr/src/app" trading-comp-env jupyter notebook --ip=0.0.0.0 --port=8888 --no-browser --allow-root
    ```

3.  **Connect VS Code**:

      * In the terminal output from the previous step, **copy the URL** that includes the token (it looks like `http://127.0.0.1:8888/?token=...`).
      * Create or open a Jupyter Notebook file (e.g., src/notebooks/data_exploration_template.ipynb).
      * In the top-right corner of the notebook, click the "Select Kernel" button.
      * From the dropdown, choose "Jupyter Server".
      * Select "Existing" from the next list.
      * Paste the full URL (with token) you copied from your terminal and press Enter.
    You can now run code in your notebook, and it will execute inside the Docker container with all the correct libraries.

-----

## 5\. Local Evaluation

This is the most important step for debugging\! It lets you test your `submission/submission.py` file locally using the exact same evaluation logic as the cloud environment. This helps you find bugs and see the expected performance metrics before submitting.

1.  **Prepare Data:** Make sure the competition data file is located at `data/comp_data.csv` relative to the project root.

2.  **Ensure `submission.py` is Ready:** Place your final code in the `submission/submission.py` file.

3.  **Run the Local Evaluator:**
    The Docker container provides a helper command `local-eval`. Run it from the project's root directory:
    Make sure the Docker Desktop program is running/open. 
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

## 6\. How to Submit

The Docker image packages all dependencies and adds a helper command `submit`.

**Run Submission Script**: From the root directory, run the `submit` command via Docker. This will securely use your `.env` file and upload your `submission/` directory. Make sure the Docker Desktop program is running/open. 
    
```bash
# For PowerShell
docker run --rm --env-file .env -v "${PWD}:/usr/src/app" trading-comp-env submit

# For macOS/Linux
docker run --rm --env-file .env -v "$(pwd):/usr/src/app" trading-comp-env submit
```

You can see your result on this website: https://www.aachen-investment-club.de/teams/quant/leaderboard.

-----

## 7\. Rules & Guidelines

  * **File**: You must submit a single `submission/submission.py`.
  * **Timeout**: Your submission has **15 minutes** (900 seconds) to run. If it exceeds this, it will fail.
  * **Available Libraries**: The Lambda environment is lightweight\! It only includes the Python 3.11 standard library, `boto3`, **`numpy`**, and **`pandas`**. Libraries like `scikit-learn` or `xgboost` are available in your local Docker environment for *training* models, but **cannot be imported** in your final `submission.py`.
  * **Error Handling**: If your `on_quote` function raises an exception, the evaluator will catch it, log it, and move to the next data batch. Your backtest will continue, but you may miss trades.

Good luck\!