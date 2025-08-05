import json
import os
import boto3
import pandas as pd
import numpy as np
from datetime import datetime

# Initialize AWS clients
s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

# Get environment variables
GROUND_TRUTH_BUCKET = os.environ.get('GROUND_TRUTH_BUCKET')
GROUND_TRUTH_KEY = os.environ.get('GROUND_TRUTH_KEY') # e.g., 'data/test_ground_truth.csv'
LEADERBOARD_TABLE_NAME = os.environ.get('LEADERBOARD_TABLE_NAME')

# --- Constants from portfolio_evaluator ---
INITIAL_CAPITAL = 1_000_000
TRANSACTION_COST_BPS = 5
RISK_FREE_RATE = 0.02

# --- Paste the backtesting functions directly into the Lambda code ---

def run_portfolio_backtest(submission_df: pd.DataFrame, ground_truth_df: pd.DataFrame) -> pd.DataFrame:
    """
    Simulates a multi-asset portfolio strategy with transaction costs.
    """
    # --- 1. Data Preparation ---
    price_data = ground_truth_df.pivot(index='timestamp', columns='ticker', values='close')
    target_weights = submission_df.pivot(index='timestamp', columns='ticker', values='position_size').fillna(0)
    target_weights = target_weights.reindex(price_data.index, method='ffill').fillna(0)
    daily_returns = price_data.pct_change()

    # --- 2. Portfolio Simulation ---
    held_weights = target_weights.shift(1).fillna(0)
    
    # --- 3. Calculate Returns and Costs ---
    portfolio_daily_returns = (held_weights * daily_returns).sum(axis=1)
    turnover = (target_weights - held_weights).abs()
    transaction_costs = turnover.sum(axis=1) * (TRANSACTION_COST_BPS / 10000.0)
    net_daily_returns = portfolio_daily_returns - transaction_costs
    
    # --- 4. Calculate Final Portfolio Value ---
    cumulative_returns = (1 + net_daily_returns).cumprod()
    final_portfolio_value = INITIAL_CAPITAL * cumulative_returns.fillna(1)
    
    results = pd.DataFrame({
        'portfolio_value': final_portfolio_value,
        'net_daily_return': net_daily_returns
    })
    return results.dropna()


def calculate_portfolio_metrics(portfolio_history: pd.DataFrame) -> dict:
    """Calculates final performance metrics for the leaderboard."""
    daily_returns = portfolio_history['net_daily_return']
    
    daily_risk_free_rate = (1 + RISK_FREE_RATE)**(1/252) - 1
    excess_returns = daily_returns - daily_risk_free_rate
    
    sharpe_ratio = 0.0
    if excess_returns.std() != 0:
        sharpe_ratio = (excess_returns.mean() / excess_returns.std()) * np.sqrt(252)

    total_return = (portfolio_history['portfolio_value'].iloc[-1] / portfolio_history['portfolio_value'].iloc[0] - 1) * 100
    
    cumulative_returns = (1 + daily_returns).cumprod()
    running_max = cumulative_returns.cummax()
    drawdown = (cumulative_returns - running_max) / running_max
    max_drawdown = drawdown.min() * 100

    return {
        'sharpeRatio': round(sharpe_ratio, 4),
        'totalReturn': round(total_return, 2),
        'maxDrawdown': round(max_drawdown, 2)
    }

# --- Main Lambda Handler ---

def lambda_handler(event, context):
    """
    Triggered by SQS. Evaluates a submission and updates the leaderboard.
    """
    leaderboard_table = dynamodb.Table(LEADERBOARD_TABLE_NAME)
    
    print(f"Received event with {len(event['Records'])} records.")

    # --- Load Ground Truth Data (once per invocation) ---
    try:
        gt_obj = s3_client.get_object(Bucket=GROUND_TRUTH_BUCKET, Key=GROUND_TRUTH_KEY)
        ground_truth_df = pd.read_csv(gt_obj['Body'], parse_dates=['timestamp'])
    except Exception as e:
        print(f"CRITICAL ERROR: Could not load ground truth data from s3://{GROUND_TRUTH_BUCKET}/{GROUND_TRUTH_KEY}. Error: {e}")
        # This is a fatal error for this invocation, so we raise it to stop processing.
        raise e

    for record in event['Records']:
        try:
            message = json.loads(record['body'])
            participant_id = message['participantId']
            s3_bucket = message['s3Bucket']
            s3_key = message['s3Key']
            
            print(f"Processing submission for participant: {participant_id}, from s3://{s3_bucket}/{s3_key}")

            # --- 1. Download Submission ---
            sub_obj = s3_client.get_object(Bucket=s3_bucket, Key=s3_key)
            submission_df = pd.read_csv(sub_obj['Body'], parse_dates=['timestamp'])

            # --- 2. Validation ---
            daily_alloc = submission_df.groupby('timestamp')['position_size'].apply(lambda x: x.abs().sum())
            if (daily_alloc > 1.0001).any():
                print(f"Validation failed for {participant_id}: Leverage detected.")
                # Optionally, update DynamoDB with a "failed" status
                continue # Skip to the next record

            # --- 3. Run Backtest and Calculate Metrics ---
            portfolio_history = run_portfolio_backtest(submission_df, ground_truth_df)
            metrics = calculate_portfolio_metrics(portfolio_history)
            
            print(f"Evaluation complete for {participant_id}. Metrics: {metrics}")

            # --- 4. Update DynamoDB Leaderboard ---
            leaderboard_table.put_item(
                Item={
                    'participantId': participant_id,
                    # Convert float metrics to Decimal for DynamoDB
                    'sharpeRatio': json.loads(json.dumps(metrics['sharpeRatio']), parse_float=str),
                    'totalReturn': json.loads(json.dumps(metrics['totalReturn']), parse_float=str),
                    'maxDrawdown': json.loads(json.dumps(metrics['maxDrawdown']), parse_float=str),
                    'submissionTimestamp': datetime.utcnow().isoformat()
                }
            )
            print(f"Successfully updated leaderboard for {participant_id}")

        except Exception as e:
            print(f"Error processing record {record['receiptHandle']}: {e}")
            # Continue to the next record without crashing the whole function
            continue
            
    return {
        'statusCode': 200,
        'body': json.dumps('Processing complete.')
    }
