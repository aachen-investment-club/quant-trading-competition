#!/usr/bin/env python3

"""
data_generator.py

Generates synthetic financial time series data for the quant trading competition.
Supports multiple products and different underlying statistical distributions.
"""

import numpy as np
import pandas as pd

def generate_gbm(s0: float, mu: float, sigma: float, dt: float, n_steps: int) -> np.ndarray:
    """
    Generates a price path using Geometric Brownian Motion (GBM).
    
    s0: Initial price
    mu: Drift coefficient
    sigma: Volatility coefficient
    dt: Time step (e.g., 1/252 for daily)
    n_steps: Number of steps to simulate
    """
    # Standard normal random variables
    w = np.random.standard_normal(size=n_steps)
    
    # GBM formula
    drift = (mu - 0.5 * sigma**2) * dt
    diffusion = sigma * np.sqrt(dt) * w
    
    # Calculate returns
    returns = np.exp(drift + diffusion)
    
    # Prepend s0 and calculate path
    path = np.zeros(n_steps + 1)
    path[0] = s0
    path[1:] = s0 * returns.cumprod()
    
    return path[1:] # Return only the generated steps, not s0

def generate_ou(s0: float, theta: float, mu: float, sigma: float, dt: float, n_steps: int) -> np.ndarray:
    """
    Generates a price path using the Ornstein-Uhlenbeck (mean-reverting) process.
    
    s0: Initial price
    theta: Speed of reversion
    mu: Long-term mean
    sigma: Volatility
    dt: Time step
    n_steps: Number of steps to simulate
    """
    prices = np.zeros(n_steps)
    prices[0] = s0
    
    # Standard normal random variables
    w = np.random.standard_normal(size=n_steps)
    
    for t in range(1, n_steps):
        # OU formula
        drift = theta * (mu - prices[t-1]) * dt
        diffusion = sigma * np.sqrt(dt) * w[t]
        prices[t] = prices[t-1] + drift + diffusion
        
        # Ensure non-negative prices
        if prices[t] < 0:
            prices[t] = 0
            
    return prices

def generate_fat_tails(s0: float, mu: float, sigma: float, df: int, dt: float, n_steps: int) -> np.ndarray:
    """
    Generates a price path with fat tails using a Student's t-distribution.
    
    s0: Initial price
    mu: Drift coefficient
    sigma: Volatility coefficient
    df: Degrees of freedom (lower df = fatter tails, e.g., 3-5)
    dt: Time step
    n_steps: Number of steps to simulate
    """
    # Random variables from Student's t-distribution, scaled by dt
    # We scale the t-distribution to have the desired std dev (sigma)
    t_vars = np.random.standard_t(df, size=n_steps)
    
    # Adjust variance
    # Var(t) = df / (df - 2) for df > 2
    if df > 2:
        scale_factor = sigma * np.sqrt(dt * (df - 2) / df)
    else:
        # For df<=2, variance is infinite, just use sigma as a scale
        scale_factor = sigma * np.sqrt(dt)
        
    t_scaled = t_vars * scale_factor
    
    # Add drift
    drift = (mu - 0.5 * sigma**2) * dt
    returns = np.exp(drift + t_scaled)
    
    # Prepend s0 and calculate path
    path = np.zeros(n_steps + 1)
    path[0] = s0
    path[1:] = s0 * returns.cumprod()
    
    return path[1:]

def generate_dataset(product_configs: list, index_config: dict, n_steps: int, dt: float = 1.0) -> list[dict]:
    """
    Generates the full dataset for all products and a correlated index.
    
    product_configs: List of dicts, each specifying a product
    index_config: A single dict specifying the index
    n_steps: Number of time steps
    dt: Time step value
    """
    
    dataset = []
    
    # First, generate the main index
    print(f"Generating index: {index_config['id']}...")
    if index_config['type'] == 'gbm':
        index_prices = generate_gbm(
            index_config['s0'], 
            index_config['mu'], 
            index_config['sigma'], 
            dt, n_steps
        )
    else:
        # Default to GBM for index if type is unknown
        index_prices = generate_gbm(1000, 0.02, 0.1, dt, n_steps)

    # Generate each product's price data
    for config in product_configs:
        print(f"Generating product: {config['id']} (Type: {config['type']})...")
        
        s0 = config.get('s0', 100)
        mu = config.get('mu', 0.05)
        sigma = config.get('sigma', 0.2)
        
        if config['type'] == 'gbm':
            prices = generate_gbm(s0, mu, sigma, dt, n_steps)
        elif config['type'] == 'ou':
            theta = config.get('theta', 0.1) # Reversion speed
            prices = generate_ou(s0, theta, mu, sigma, dt, n_steps)
        elif config['type'] == 'fat_tails':
            df = config.get('df', 4) # Degrees of freedom
            prices = generate_fat_tails(s0, mu, sigma, df, dt, n_steps)
        else:
            print(f"Warning: Unknown type {config['type']}. Defaulting to GBM.")
            prices = generate_gbm(s0, mu, sigma, dt, n_steps)

        # Format the data as requested
        for i in range(n_steps):
            dataset.append({
                'time_step': i,
                'product_id': config['id'],
                'mid_price': prices[i],
                'index_value': index_prices[i]
            })
            
    # Sort by time_step and then product_id for clean output
    dataset_sorted = sorted(dataset, key=lambda x: (x['time_step'], x['product_id']))
    
    return dataset_sorted

if __name__ == "__main__":
    
    N_STEPS = 1000 # Number of time steps to generate
    DT = 1 / 252   # Time step (e.g., 1 day)

    # 1. Define the competition index
    # This will be shared across all product records
    index_conf = {
        'id': 'GLOBAL_INDEX',
        'type': 'gbm',
        's0': 1000,
        'mu': 0.03,
        'sigma': 0.1
    }

    # 2. Define the products for the competition
    product_confs = [
        {
            'id': 'PRODUCT_A',
            'type': 'gbm',      # Standard random walk
            's0': 100,
            'mu': 0.05,
            'sigma': 0.2
        },
        {
            'id': 'PRODUCT_B',
            'type': 'ou',       # Mean-reverting
            's0': 50,
            'mu': 55,           # Long-term mean
            'theta': 0.1,       # Speed of reversion
            'sigma': 0.3
        },
        {
            'id': 'PRODUCT_C',
            'type': 'fat_tails',# Black-swan-style events
            's0': 200,
            'mu': 0.01,
            'sigma': 0.4,
            'df': 3             # Low degrees of freedom = very fat tails
        }
    ]

    # 3. Generate the data
    competition_data = generate_dataset(product_confs, index_conf, N_STEPS, DT)
    
    # 4. Convert to DataFrame and save to CSV
    df = pd.DataFrame(competition_data)
    
    output_file = "competition_comp_data.csv"
    df.to_csv(output_file, index=False)
    
    print(f"\nSuccessfully generated {len(competition_data)} data points.")
    print(f"Saved to {output_file}")
    print("\nData head:")
    print(df.head(10))
    print("\nData tail:")
    print(df.tail(10))