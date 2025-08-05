# Software Design: Quantitative Trading Competition Platform

## 1. Overview

This document outlines the software design for a quantitative trading competition platform. The system is composed of two primary components: a local **Participant Environment** for strategy development and a cloud-native **AWS Backend** for submission evaluation and leaderboard management.

The design prioritizes a clear separation of concerns, scalability, and a professional experience for participants, allowing them to focus on strategy development rather than infrastructure. It accommodates two distinct development paths: a traditional rule-based algorithmic approach and a data-science-driven machine learning approach.

---

## 2. Participant Environment Design

The participant environment is a self-contained kit distributed as a `.zip` archive. Its design is intended to be simple, intuitive, and language-agnostic, though the provided templates are in Python.

### 2.1. Directory Structure

```
.
├── data/
│   ├── train.csv         # Historical multi-asset data for research
│   └── test_features.csv # Feature data for the evaluation period
├── submissions/
│   └── (empty)           # Directory for the generated submission file
├── src/
│   ├── train_model.py        # Template for the Machine Learning path
│   ├── predict.py            # Template to generate submission from a trained model
│   └── trading_strategy.py   # Template for the Rule-Based path
├── requirements.txt      # Core Python dependencies
└── README.md             # Instructions for participants
```

### 2.2. Data Format

To handle a large universe of stocks like the S&P 500, all data (`train.csv`, `test_features.csv`) is provided in a **long format**. This is a standard and efficient way to represent panel data.

| timestamp | ticker | close | volume |
| :--- | :--- | ---: | ---: |
| 2022-01-03 | AAPL | 182.01 | 104487900 |
| 2022-01-03 | MSFT | 334.75 | 32674300 |
| ... | ... | ... | ... |

### 2.3. Submission Format

The core output of the participant's work is a `submission.csv` file. This file represents the participant's desired portfolio allocation for each day of the test period.

* **Format**: CSV with columns `timestamp`, `ticker`, `position_size`.
* **`position_size`**: A float between `-1.0` and `1.0`.
    * Positive values indicate a long position (e.g., `0.05` = 5% of portfolio value).
    * Negative values indicate a short position (e.g., `-0.02` = 2% of portfolio value).
* **Constraint**: The sum of the absolute values of `position_size` for any single `timestamp` must not exceed `1.0`. This enforces a no-leverage rule.

### 2.4. Development Paths & Core Scripts

* **`trading_strategy.py` (Rule-Based Path)**: A self-contained script where a user implements a `generate_portfolio_allocations` function. This function takes the test data as input and directly outputs the final portfolio weights based on programmatic rules (e.g., technical indicators, momentum).

* **`train_model.py` (ML Path)**: A script for data scientists to perform feature engineering and train a predictive model on `train.csv`. The key output is a serialized model file (e.g., `trading_model.joblib`).

* **`predict.py` (ML Path)**: This script loads the pre-trained model, applies the *identical* feature engineering to `test_features.csv`, and translates the model's predictions into the final `position_size` allocations for the submission file.

---

## 3. AWS Backend Architecture

The backend is a fully serverless, event-driven architecture designed for scalability, resilience, and cost-efficiency.

### 3.1. Architectural Diagram (Component Flow)

```
                  +-----------------+      +-----------------+      +---------------------+
Participant --(1)->|  API Gateway  |--(2)->|  Lambda (Submit)|--(3)->| SQS (Submissions)   |
(Uploads CSV)     | (POST /submit)  |      |   Validator     |      |        Queue        |
                  +-----------------+      +-------+---------+      +----------+----------+
                                                   | (Saves to)                | (4) Triggers
                                                   v                           v
                                          +--------+---------+      +----------+----------+
                                          | S3 (Submissions) |      |  Lambda (Evaluate)  |
                                          +------------------+      +----------+----------+
                                                                               | (Reads from)
                                                                               v
                                                                    +----------+----------+
                                                                    | S3 (Ground Truth)   |
                                                                    +---------------------+
                                                                               | (Writes to)
                                                                               v
                                                                    +----------+----------+
                                                                    |  DynamoDB Leaderboard |
                                                                    +---------------------+
```

### 3.2. Service Components

* **Amazon S3 (Simple Storage Service)**
    * `submissions-bucket`: Private bucket to store raw `submission.csv` files uploaded by participants.
    * `ground-truth-bucket`: Highly restricted private bucket containing the complete, secret test data with price information (`test_ground_truth.csv`). Only accessible by the evaluation Lambda.
    * `leaderboard-website-bucket`: Publicly accessible bucket configured for static website hosting to display the leaderboard.

* **IAM (Identity and Access Management)**
    * `SubmissionLambdaRole`: Grants the submission Lambda permissions to write to the submissions S3 bucket and send messages to the SQS queue.
    * `EvaluationLambdaRole`: Grants the evaluation Lambda permissions to read from both the submissions and ground-truth S3 buckets, read/delete messages from SQS, and write results to the DynamoDB table.

* **API Gateway**
    * Provides a RESTful `POST /submit` endpoint for file uploads.
    * Secured using **API Keys**, which are generated and distributed to each participant for authentication and usage tracking.
    * Acts as a proxy, forwarding valid requests directly to the submission Lambda function.

* **AWS Lambda: `submission-handler`**
    * **Trigger**: API Gateway `POST` request.
    * **Responsibilities**:
        1.  Authenticates the request via the provided `x-api-key` header.
        2.  Performs initial validation on the submission (e.g., file size, basic CSV structure).
        3.  Saves the file to the `submissions-bucket` with a unique name (e.g., `participant-id_timestamp.csv`).
        4.  Pushes a JSON message to the SQS queue containing the S3 file path and participant ID.
        5.  Returns an immediate `200 OK` response to the participant, confirming receipt.

* **Amazon SQS (Simple Queue Service)**
    * **Name**: `SubmissionsQueue`
    * **Purpose**: Decouples the submission process from the more intensive evaluation process. This queue acts as a durable buffer, ensuring that every submission is processed reliably, even under heavy load or in case of transient evaluation failures.

* **AWS Lambda: `evaluation-engine`**
    * **Trigger**: New messages in the `SubmissionsQueue`.
    * **Responsibilities**: This is the core evaluation engine. See section 4.2 for detailed logic.
        1.  Receives a message from SQS.
        2.  Downloads the participant's submission and the ground truth data from S3.
        3.  Performs a full backtest simulation.
        4.  Calculates performance metrics (Sharpe Ratio, etc.).
        5.  Writes the results to the DynamoDB `Leaderboard` table.
        6.  Deletes the message from the SQS queue upon successful completion.

* **Amazon DynamoDB**
    * **Table Name**: `Leaderboard`
    * **Schema**:
        * `participantId` (String, Partition Key)
        * `sharpeRatio` (Number)
        * `totalReturn` (Number)
        * `maxDrawdown` (Number)
        * `submissionTimestamp` (String)
    * **Indexes**: A Global Secondary Index (GSI) on `sharpeRatio` allows for efficient querying to rank participants and display the leaderboard.

---

## 4. Core Logic and Data Flow

### 4.1. Submission and Validation Flow

1.  Participant sends a `POST` request to the API Gateway `/submit` endpoint with their `submission.csv` in the body and their unique key in the `x-api-key` header.
2.  API Gateway validates the key and forwards the request to the `submission-handler` Lambda.
3.  The Lambda saves the file to S3 and enqueues a message in SQS: `{"participantId": "user-123", "s3_path": "s3://submissions-bucket/user-123_1662402000.csv"}`.
4.  The `evaluation-engine` Lambda is triggered by this message.

### 4.2. Evaluation Logic (Portfolio Backtester)

The `evaluation-engine` performs a vectorized backtest for maximum performance.

1.  **Data Loading**: Loads the participant's submission and the ground truth prices from S3 into pandas DataFrames.
2.  **Data Pivoting**: Both DataFrames are pivoted from a long format to a wide format, where the index is `timestamp` and columns are the stock `ticker`s. This aligns the data and prepares it for efficient matrix operations.
    ```python
    # Example pivot
    price_data = ground_truth_df.pivot(index='timestamp', columns='ticker', values='close')
    target_weights = submission_df.pivot(index='timestamp', columns='ticker', values='position_size')
    ```
3.  **Alignment & Forward-Fill**: The `target_weights` DataFrame is reindexed to match the `price_data` index, and `method='ffill'` is used to carry over the previous day's allocation to non-trading days (weekends/holidays).
4.  **Daily Returns Calculation**: Daily percentage changes are calculated for the `price_data`.
5.  **Portfolio Returns Simulation**:
    * The weights held throughout a given day are the target weights from the *previous* day's close. This is achieved with `.shift(1)`.
    * The portfolio's gross daily return is calculated as the dot product of the held weights and the daily returns for each asset: `(held_weights * daily_returns).sum(axis=1)`.
6.  **Transaction Cost Calculation**:
    * Turnover is the absolute change in weights from one day to the next: `(target_weights - held_weights).abs()`.
    * The total transaction cost for a day is the sum of all turnover multiplied by a basis point fee: `turnover.sum(axis=1) * (TRANSACTION_COST_BPS / 10000.0)`.
7.  **Net Returns**: The transaction cost is subtracted from the gross daily return to get the net daily return.
8.  **Equity Curve**: The final portfolio value is calculated by applying the cumulative product of `(1 + net_daily_returns)` to the `INITIAL_CAPITAL`.

### 4.3. Performance Metrics

From the daily net returns series, the following key metrics are calculated:

* **Sharpe Ratio (Annualized)**: The primary ranking metric. It is the annualized mean of excess returns (daily net return - daily risk-free rate) divided by the annualized standard deviation of excess returns.
* **Total Return**: The total percentage gain or loss of the portfolio over the entire evaluation period.
* **Maximum Drawdown**: The largest peak-to-trough percentage drop in the portfolio's equity curve, indicating the worst loss suffered.
