import pandas as pd

def generate_portfolio_allocations(data: pd.DataFrame) -> pd.DataFrame:
    """
    Generates target portfolio allocations based on a rule-based strategy.
    
    Participants should implement their trading logic in this function.

    Args:
        data: A pandas DataFrame with historical multi-asset data for the test period.

    Returns:
        A pandas DataFrame with the target portfolio allocations.
    """
    print("Executing rule-based momentum strategy...")
    
    # --- Example Strategy: Monthly Top 20 Momentum ---
    
    # Ensure data is sorted correctly
    data = data.sort_values(by=['timestamp'])
    
    # Calculate monthly returns for each stock
    monthly_prices = data.reset_index().groupby(['ticker', pd.Grouper(key='timestamp', freq='M')])['close'].last()
    monthly_returns = monthly_prices.groupby('ticker').pct_change().rename('monthly_return')
    
    # Determine the rank of each stock's return for each month
    monthly_ranks = monthly_returns.groupby('timestamp').rank(ascending=False)
    
    # Select the top 20 stocks for each month
    top_20_stocks = monthly_ranks[monthly_ranks <= 20].reset_index()
    
    # --- Create the target allocations DataFrame ---
    allocations = []
    
    # Get all unique trading days from the input data
    all_trading_days = data.index.unique().sort_values()

    # Forward-fill the monthly decisions to each trading day
    for month_end in top_20_stocks['timestamp'].unique():
        current_top_tickers = top_20_stocks[top_20_stocks['timestamp'] == month_end]['ticker'].tolist()
        
        start_date = month_end + pd.DateOffset(days=1)
        end_date = month_end + pd.DateOffset(months=1)
        
        target_days = all_trading_days[(all_trading_days >= start_date) & (all_trading_days <= end_date)]

        # Assign equal weight to each of the top 20 stocks for these days
        # Total allocation will be 1.0 (20 stocks * 0.05)
        weight = 1.0 / len(current_top_tickers) if current_top_tickers else 0

        for day in target_days:
            for ticker in current_top_tickers:
                allocations.append({'timestamp': day, 'ticker': ticker, 'position_size': weight})

    if not allocations:
        print("Warning: No allocations were generated.")
        return pd.DataFrame(columns=['timestamp', 'ticker', 'position_size']).set_index('timestamp')

    # Convert to DataFrame
    submission_df = pd.DataFrame(allocations).set_index('timestamp')
    
    print("Strategy execution complete.")
    return submission_df


def main():
    """
    Main execution function for generating the submission file.
    """
    print("Loading test features for S&P 500...")
    try:
        test_features = pd.read_csv('data/test_features.csv', index_col='timestamp', parse_dates=True)
    except FileNotFoundError:
        print("Error: 'data/test_features.csv' not found.")
        return

    print("Generating portfolio allocations...")
    submission_df = generate_portfolio_allocations(test_features)
    
    # --- Validation ---
    if 'position_size' not in submission_df.columns or 'ticker' not in submission_df.columns:
        raise ValueError("Submission must have 'ticker' and 'position_size' columns.")
    
    daily_allocation = submission_df.groupby('timestamp')['position_size'].apply(lambda x: x.abs().sum())
    if (daily_allocation > 1.0001).any():
        print("Error: Total absolute allocation for a given day exceeds 1.0.")
        return

    # --- Save Submission File ---
    output_path = 'submissions/submission.csv'
    submission_df.reset_index().to_csv(output_path, index=False)
    
    print(f"\nSuccessfully created submission file at: {output_path}")
    print("Submission file head:")
    print(submission_df.head())


if __name__ == "__main__":
    main()
