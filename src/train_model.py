import pandas as pd
import numpy as np
import lightgbm as lgb
import joblib  # For saving the model

# --- Configuration ---
# Participants can adjust these parameters
MODEL_FILE_PATH = 'trading_model.joblib'
HORIZON = 21  # Predict returns 21 trading days (approx. 1 month) into the future
TRAIN_END_DATE = '2023-12-31' # Use data up to this date for training

def feature_engineering(df: pd.DataFrame) -> pd.DataFrame:
    """
    Creates features for the machine learning model.
    
    Args:
        df: DataFrame with historical price data.

    Returns:
        DataFrame with engineered features.
    """
    print("Starting feature engineering...")
    
    # Ensure data is sorted for time-series calculations
    df = df.sort_values(by=['ticker', 'timestamp'])
    
    # --- Feature Creation ---
    # Example features: Momentum (rolling returns) over different windows
    for window in [21, 63, 126, 252]:
        df[f'momentum_{window}d'] = df.groupby('ticker')['close'].pct_change(periods=window)
        
    # Example feature: Volatility (rolling standard deviation of returns)
    df['volatility_63d'] = df.groupby('ticker')['close'].pct_change().rolling(window=63).std()
    
    # --- Target Variable Creation ---
    # The target is the future return over the specified HORIZON
    # We use .shift(-HORIZON) to look into the future
    df['target_return'] = df.groupby('ticker')['close'].pct_change(periods=HORIZON).shift(-HORIZON)
    
    print("Feature engineering complete.")
    return df.dropna()


def train_model(features_df: pd.DataFrame):
    """
    Trains a LightGBM model and saves it to a file.

    Args:
        features_df: DataFrame containing the features and the target variable.
    """
    print("Starting model training...")
    
    # Define features (X) and target (y)
    features = [col for col in features_df.columns if col not in ['ticker', 'timestamp', 'close', 'volume', 'target_return']]
    X = features_df[features]
    y = features_df['target_return']

    print(f"Training on {len(X)} samples with {len(features)} features.")
    
    # --- Model Training ---
    # LightGBM is a good choice for tabular data: it's fast and powerful.
    lgbm = lgb.LGBMRegressor(
        objective='regression_l1',  # L1 loss is often robust for financial data
        n_estimators=500,
        learning_rate=0.05,
        num_leaves=31,
        n_jobs=-1,  # Use all available CPU cores
        seed=42
    )
    
    lgbm.fit(X, y)
    
    # --- Save the Trained Model ---
    joblib.dump(lgbm, MODEL_FILE_PATH)
    print(f"Model successfully trained and saved to '{MODEL_FILE_PATH}'")
    
    # Optional: Display feature importances
    feature_importance = pd.DataFrame({'feature': features, 'importance': lgbm.feature_importances_})
    print("\nTop 10 Feature Importances:")
    print(feature_importance.sort_values(by='importance', ascending=False).head(10))


def main():
    """
    Main execution function for the training script.
    """
    print("Loading training data...")
    try:
        # Load the full training dataset provided by the competition
        full_data = pd.read_csv('data/train.csv', parse_dates=['timestamp'])
    except FileNotFoundError:
        print("Error: 'data/train.csv' not found. Please place it in the 'data' directory.")
        return
        
    # --- Data Preparation ---
    # Filter data to the training period to avoid any lookahead bias
    train_data = full_data[full_data['timestamp'] <= TRAIN_END_DATE]
    
    # --- Feature Engineering ---
    features_df = feature_engineering(train_data)
    
    # --- Model Training ---
    train_model(features_df)


if __name__ == "__main__":
    main()
