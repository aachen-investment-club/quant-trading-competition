#!/usr/bin/env python3

"""
local_eval.py

Runs a local backtest evaluation mimicking the cloud evaluator lambda,
reading data directly from data/comp_data.csv.

Usage:
    python local_eval.py <path_to_submission_py>

Example:
    python local_eval.py submission/submission.py
"""

import sys
import os
import importlib.util
import pandas as pd
import csv
import traceback
from collections import defaultdict
from src.Engine import calculate_sharpe_ratio # Import the helper

# --- Assumes your local backtest code is in the 'src' directory ---
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

# Import necessary components from your local 'src' directory
try:
    from src.Engine import Engine
    # Datastream/EODSource no longer needed here
except ImportError as e:
    print(f"Error importing local backtest modules: {e}")
    print("Please ensure src/Engine.py exists.")
    sys.exit(1)

# --- CSV Reader Logic (Simplified from Lambda, processes into batches) ---
def read_and_batch_csv_data(csv_path: str) -> tuple[list[str], list[list[dict]]]:
    """
    Reads the CSV, detects format, determines universe, processes into batches
    suitable for the simplified Engine, and returns universe list and batches.
    """
    print(f"Reading and batching data from: {csv_path}")
    data_by_product = {} # To hold data temporarily if long format
    all_rows = [] # To hold dicts read from CSV
    universe = []

    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            header_line = f.readline().strip()
            headers = [h.strip() for h in header_line.split(',')]
            f.seek(0)
            reader = csv.DictReader(f)
            all_rows = list(reader)

        print(f"CSV Headers: {headers}")
        time_col = 'timestep' if 'timestep' in headers else 'timestamp' # Determine time column name

        # --- Format Detection and Universe Extraction ---
        if 'product_id' in headers: # LONG FORMAT
            print("Detected LONG format CSV.")
            universe = sorted(list(set(row['product_id'] for row in all_rows)))
            data_by_product = {ric: [] for ric in universe}
            price_col = 'mid_price' # Adjust if your price column is different
            for row in all_rows:
                 try:
                    price = float(row[price_col])
                    ts = row[time_col]
                    # Structure matches what lambda CSV reader produces
                    quote = {
                        'id': row['product_id'],
                        'timestamp': ts,
                        'price': price,
                        'data': {'Price Close': price}
                    }
                    data_by_product[row['product_id']].append(quote)
                 except (ValueError, KeyError) as e:
                    print(f"Skipping row due to error: {e} in row: {row}")

            # Now, simulate batching by timestamp (like lambda's iter_quotes_from_csv_long)
            all_quotes = []
            for ric in universe:
                all_quotes.extend(data_by_product[ric])

            # Sort all quotes by timestamp first, then by id
            all_quotes.sort(key=lambda q: (q['timestamp'], q['id']))

            batched_data = []
            current_batch = []
            last_ts = None
            for quote in all_quotes:
                ts = quote['timestamp']
                if last_ts is None: last_ts = ts

                if ts != last_ts:
                    # Add clock tick to previous batch before starting new one
                    if current_batch:
                         current_batch.append({'id': 'Clock', 'timestamp': last_ts})
                         batched_data.append(current_batch)
                    current_batch = [quote] # Start new batch
                    last_ts = ts
                else:
                    current_batch.append(quote)

            if current_batch: # Add the last batch
                 current_batch.append({'id': 'Clock', 'timestamp': last_ts})
                 batched_data.append(current_batch)

        else: # WIDE FORMAT
            print("Detected WIDE format CSV.")
            universe = sorted([h for h in headers if h != time_col])
            batched_data = []
            for row in all_rows:
                ts = row.get(time_col)
                current_batch = []
                for ric in universe:
                    if row.get(ric) is not None and row[ric] not in ('', 'NaN'):
                        try:
                            price = float(row[ric])
                            # Structure matches what lambda CSV reader produces
                            quote = {
                                'id': ric,
                                'timestamp': ts,
                                'price': price,
                                'data': {'Price Close': price}
                            }
                            current_batch.append(quote)
                        except (ValueError, KeyError) as e:
                             print(f"Skipping value for {ric} due to error: {e} in row: {row}")
                if current_batch: # Add batch only if it has data
                    # Add clock tick
                    current_batch.append({'id': 'Clock', 'timestamp': ts})
                    batched_data.append(current_batch)

        print(f"Determined Universe: {universe}")
        print(f"Processed into {len(batched_data)} batches.")
        return universe, batched_data

    except FileNotFoundError:
        print(f"ERROR: Data file not found at {csv_path}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Failed to read or process CSV file {csv_path}: {e}")
        traceback.print_exc()
        sys.exit(1)


# --- Load Participant Code (Remains the same) ---
def load_submission(submission_path: str):
    """Loads the build_trader function from the participant's submission.py."""
    print(f"Loading submission from: {submission_path}")
    try:
        spec = importlib.util.spec_from_file_location("submission", submission_path)
        if spec is None:
             raise ImportError(f"Could not load spec for module at path: {submission_path}")
        mod = importlib.util.module_from_spec(spec)
        # --- Add local src modules to prevent import errors in submission ---
        # This makes `from pricing.Product import Product` work locally
        sys.modules['pricing'] = importlib.import_module('src.pricing')
        sys.modules['pricing.Market'] = importlib.import_module('src.pricing.Market')
        sys.modules['pricing.Portfolio'] = importlib.import_module('src.pricing.Portfolio')
        sys.modules['pricing.Position'] = importlib.import_module('src.pricing.Position')
        sys.modules['pricing.Product'] = importlib.import_module('src.pricing.Product')
        # --- End local module injection ---

        spec.loader.exec_module(mod)

        if not hasattr(mod, 'build_trader'):
            raise AttributeError("submission.py must define a 'build_trader(universe)' function.")

        return mod.build_trader # Return the function itself
    except FileNotFoundError:
        print(f"ERROR: Submission file not found at {submission_path}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Failed to load submission.py: {e}")
        traceback.print_exc()
        sys.exit(1)


# --- Main Execution Logic ---
if __name__ == "__main__":
    # --- FIXED DATA PATH ---
    data_path = os.path.join(project_root, "data", "comp_data.csv")

    if len(sys.argv) != 2: # Only submission path needed now
        print("Usage: python local_eval.py <path_to_submission_py>")
        print(f"\nAttempting to use default data path: {data_path}")
        # sys.exit(1) # Keep going if only submission path missing
        if not os.path.exists(data_path):
            print(f"ERROR: Default data file not found at {data_path}")
            sys.exit(1)
        submission_path = sys.argv[1] # Still requires submission path
    else:
        submission_path = sys.argv[1]
        if not os.path.exists(data_path):
             print(f"ERROR: Default data file not found at {data_path}")
             sys.exit(1)


    # 1. Load submission code
    strategy_builder_func = load_submission(submission_path)

    # 2. Read data and process into batches
    universe, data_batches = read_and_batch_csv_data(data_path)

    # 3. Initialize and run the engine
    try:
        # Pass the builder function and batched data to the Engine
        engine = Engine(universe, data_batches, strategy_builder_func, initial_cash=100000.0)
        engine.run()
    except Exception as e:
        print(f"\n--- ERROR during Engine Initialization or Run ---")
        traceback.print_exc()
        print("--------------------------------------------------\n")
        sys.exit(1)

    
    
    final_nav = engine.portfolio.nav()
    pnl = final_nav - engine.initial_cash
    sharpe = calculate_sharpe_ratio(engine.nav_history) # Pass the nav_history

    print("\n--- Local Evaluation Metrics ---")
    print(f"Final NAV:         {final_nav:,.2f}")
    print(f"Total PnL:         {pnl:,.2f}")
    print(f"Annualized Sharpe: {sharpe:.4f}")
    # Optional: Save results
    # engine.save("./local_results")

    print("Local evaluation complete.")