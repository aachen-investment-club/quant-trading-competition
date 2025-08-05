# S&P 500 Quantitative Trading Competition

Welcome to the S&P 500 Quantitative Trading Competition! Your challenge is to develop a trading strategy that generates the best risk-adjusted returns by trading a portfolio of S&P 500 constituent stocks.

This repository contains everything you need to get started, develop your strategy, and generate a valid submission file.

---
## Getting Started

1.  **Prerequisites**: Make sure you have Python 3.8+ installed.
2.  **Clone the Repository**: Get a local copy of this competition kit.
3.  **Install Dependencies**: Open your terminal in the project root and run the following command to install the required Python libraries:
    ```bash
    pip install -r requirements.txt
    ```

---
## Project Structure

Here is an overview of the key files and directories:

```
.
├── data/
│   ├── train.csv         # Historical multi-asset data for research and model training
│   └── test_features.csv # Feature data for the evaluation period
├── submissions/
│   └── (empty)           # Your generated submission.csv will be saved here
├── src/
│   ├── train_model.py        # Template for the Machine Learning path
│   ├── predict.py            # Template for using a trained model
│   └── trading_strategy.py   # Template for the Rule-Based path
├── requirements.txt      # Required Python packages
└── README.md             # You are here!
```

---
## How to Participate

You can choose one of two paths to develop your strategy. Both paths will result in a `submission.csv` file with the same required format.

### Path A: The Algorithmic Trader (Rule-Based Strategy)

This path is for those who want to implement a strategy directly using technical indicators, price patterns, or other programmatic rules.

1.  **Open `src/trading_strategy.py`**: This is the only file you need to edit for this path.
2.  **Implement Your Logic**: Modify the `generate_portfolio_allocations` function. The provided template contains a simple monthly momentum strategy. You can replace it entirely with your own logic.
3.  **Generate Your Submission**: Run the script from your terminal:
    ```bash
    python src/trading_strategy.py
    ```
    If successful, this will create a `submission.csv` file inside the `submissions/` directory.

### Path B: The Data Scientist (Machine Learning Strategy)

This path is for those who want to use historical data to train a predictive model. This is a two-step process.

#### Step 1: Train Your Model

1.  **Open `src/train_model.py`**: This file is a template for training a machine learning model.
2.  **Engineer Features**: Modify the `feature_engineering` function to create predictive signals from the data.
3.  **Train a Model**: The template uses `LightGBM`, but you can replace it with any model you prefer (e.g., `XGBoost`, `scikit-learn` models, or a neural network). The script will save your trained model as `trading_model.joblib`.
4.  **Run the Training Script**:
    ```bash
    python src/train_model.py
    ```

#### Step 2: Generate Predictions and Allocations

1.  **Open `src/predict.py`**: This script uses your saved model to generate the final submission.
2.  **Ensure Consistency**: The `feature_engineering` function in this file **must be identical** to the one in `train_model.py`.
3.  **Define Your Allocation Strategy**: Modify the `generate_allocations_from_model` function to translate your model's predictions into portfolio weights. The template shows how to go long the top-ranked stocks and short the bottom-ranked stocks.
4.  **Generate Your Submission**:
    ```bash
    python src/predict.py
    ```
    This will load your saved model, apply it to the test data, and create your `submission.csv` file in the `submissions/` directory.

---
## Submission Format

The final `submission.csv` file must contain three columns: `timestamp`, `ticker`, and `position_size`.

| timestamp | ticker | position_size |
| :--- | :--- | ---: |
| 2024-01-02 | AAPL | 0.10 |
| 2024-01-02 | MSFT | 0.08 |
| 2024-01-02 | NVDA | -0.05 |
| ... | ... | ... |

-   **`position_size`**: A float between **-1.0** and **1.0** representing the fraction of your portfolio's total value allocated to a stock.
    -   Positive values are long positions.
    -   Negative values are short positions.

---
## Important Rules

-   **No Leverage**: For any given `timestamp`, the sum of the **absolute** values of all your `position_size` entries cannot exceed **1.0**. The validation check in the scripts will prevent you from creating a file that violates this rule.

-   **Data Usage**: You must only use the data provided in the `data/` directory to generate your submission. Using external data is not permitted.

Good luck!
