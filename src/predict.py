import pandas as pd
import joblib

# --- Configuration ---
MODEL_FILE_PATH = 'trading_model.joblib'
TOP_N_STOCKS = 20  # Number of stocks to include in the portfolio (long and short)

def feature_engineering(df: pd.DataFrame) -> pd.DataFrame:
    """
    Creates features for the machine learning model.
    
    IMPORTANT: This function must be IDENTICAL to the one in train_model.py
    to ensure consistency between training and prediction.
    """
    print("Applying feature engineering to test data...")
    df = df.sort_values(by=['ticker', 'timestamp'])
    
    for window in [21, 63, 126, 252]:
        df[f'momentum_{window}d'] = df.groupby('ticker')['close'].pct_change(periods=window)
        
    df['volatility_63d'] = df.groupby('ticker')['close'].pct_change().rolling(window=63).std()
    
    return df

def generate_allocations_from_model(data: pd.DataFrame, model) -> pd.DataFrame:
    """
    Uses the trained model to predict returns and generate portfolio allocations.
    """
    print("Generating allocations from model predictions...")
    
    # We only need the last day of features for each stock to make our prediction
    latest_features = data.groupby('ticker').last()
    
    # Define feature columns (must match training)
    features = [col for col in latest_features.columns if col not in ['ticker', 'timestamp', 'close', 'volume']]
    
    # Drop rows with any NaNs that might have resulted from feature engineering
    latest_features = latest_features.dropna(subset=features)
    
    if latest_features.empty:
        print("Warning: No valid data to predict on after feature engineering.")
        return pd.DataFrame()
        
    X_test = latest_features[features]
    
    # --- Make Predictions ---
    predictions = model.predict(X_test)
    latest_features['predicted_return'] = predictions
    
    # --- Strategy: Go long the top N, short the bottom N ---
    # Rank stocks by their predicted future return
    latest_features = latest_features.sort_values(by='predicted_return', ascending=False)
    
    # Select the top N for long positions and bottom N for short positions
    long_stocks = latest_features.head(TOP_N_STOCKS)
    short_stocks = latest_features.tail(TOP_N_STOCKS)
    
    # Assign equal weights
    long_weight = 0.5 / TOP_N_STOCKS  # Allocate 50% of portfolio to longs
    short_weight = -0.5 / TOP_N_STOCKS # Allocate 50% of portfolio to shorts
    
    allocations = {}
    for ticker in long_stocks.index:
        allocations[ticker] = long_weight
    for ticker in short_stocks.index:
        allocations[ticker] = short_weight
        
    return pd.DataFrame.from_dict(allocations, orient='index', columns=['position_size'])


def main():
    """
    Main execution function for generating the final submission file.
    """
    print("Loading the trained model...")
    try:
        model = joblib.load(MODEL_FILE_PATH)
    except FileNotFoundError:
        print(f"Error: Model file '{MODEL_FILE_PATH}' not found. Please run train_model.py first.")
        return

    print("Loading test features data...")
    try:
        test_data = pd.read_csv('data/test_features.csv', parse_dates=['timestamp'])
    except FileNotFoundError:
        print("Error: 'data/test_features.csv' not found.")
        return

    # --- Feature Engineering ---
    # It's crucial this step is identical to the training script
    features_df = feature_engineering(test_data)
    
    # --- Generate Allocations ---
    # The model predicts the best stocks to hold for the entire test period.
    # We will apply these allocations across all days in the test set.
    target_allocations = generate_allocations_from_model(features_df, model)
    
    if target_allocations.empty:
        print("No allocations were generated. Exiting.")
        return

    # --- Create Submission File ---
    # Create a row for each stock and each day in the test period
    all_days = test_data['timestamp'].unique()
    all_tickers = target_allocations.index
    
    submission_index = pd.MultiIndex.from_product([all_days, all_tickers], names=['timestamp', 'ticker'])
    submission_df = pd.DataFrame(index=submission_index)
    
    # Map the target weights to the submission DataFrame
    submission_df = submission_df.join(target_allocations).fillna(0)
    
    # --- Save Submission File ---
    output_path = 'submissions/submission.csv'
    submission_df.reset_index().to_csv(output_path, index=False)
    
    print(f"\nSuccessfully created submission file at: {output_path}")
    print("Example allocations for the first day:")
    print(submission_df.head(TOP_N_STOCKS * 2))


if __name__ == "__main__":
    main()
