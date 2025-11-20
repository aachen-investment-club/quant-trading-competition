#!/usr/bin/env python3
"""
local_eval.py

Runs a local backtest evaluation mimicking the cloud evaluator lambda.
ENFORCES CLOUD CONSTRAINTS: Blocks disallowed imports to prevent "works locally, fails in cloud" issues.

Usage:
    python local_eval.py <path_to_submission_py>
"""

import logging
import sys
import os
import importlib.util
import csv
import traceback
from datetime import datetime

# import own modules
from src.Engine import calculate_sharpe_ratio, Engine

# --- Create Logger Object ---
os.makedirs("logs", exist_ok=True)
timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
log_filename = os.path.join("logs", f"local_eval_{timestamp}.log")

logger = logging.getLogger("local_eval")
logger.setLevel(logging.DEBUG)
logger.propagate = False

file_handler = logging.FileHandler(log_filename)
file_handler.setLevel(logging.DEBUG)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

formatter = logging.Formatter(fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

# --- CLOUD COMPATIBILITY ENFORCEMENT ---
def enforce_cloud_constraints():
    """
    The Lambda environment only has Python Std Lib, Numpy, Pandas, and Boto3.
    We must BLOCK other libraries (sklearn, scipy, etc.) that exist in this Docker image
    but will cause the submission to crash in the cloud.
    """
    print("\n" + "!"*60)
    print("  CLOUD COMPATIBILITY CHECK")
    print("  Only 'submission.py' is uploaded. Local helper files are IGNORED.")
    print("  Allowed external libs: numpy, pandas, boto3.")
    print("!"*60 + "\n")

    # List of common data science libraries provided in Docker for *exploration* # but NOT available in the Lambda evaluator.
    FORBIDDEN_MODULES = [
        "scikit-learn", "sklearn", 
        "scipy", 
        "xgboost", 
        "lightgbm", 
        "matplotlib", 
        "seaborn", 
        "statsmodels", 
        "tensorflow", 
        "torch", 
        "keras"
    ]

    blocked_count = 0
    for mod_name in FORBIDDEN_MODULES:
        # We poison the module cache. If the user tries to import these, 
        # python will raise an ImportError immediately.
        sys.modules[mod_name] = None
        # Block submodules too if they are already loaded or to be safe
        if mod_name == "scikit-learn": sys.modules["sklearn"] = None
    
    logger.info(f"Enforced cloud constraints. {len(FORBIDDEN_MODULES)} non-lambda libraries blocked.")


# --- CSV Reader Logic ---
def read_and_batch_csv_data(csv_path: str) -> tuple[list[str], list[list[dict]]]:
    logger.debug(f"Reading and batching data from: {csv_path}")
    all_rows = []
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            header_line = f.readline().strip()
            headers = [h.strip() for h in header_line.split(',')]
            f.seek(0)
            reader = csv.DictReader(f)
            all_rows = list(reader)

        time_col = 'timestep' if 'timestep' in headers else 'timestamp'
        
        if 'product_id' in headers: # LONG FORMAT
            universe = sorted(list(set(row['product_id'] for row in all_rows)))
            data_by_product = {ric: [] for ric in universe}
            price_col = 'mid_price'
            for row in all_rows:
                 try:
                    price = float(row[price_col])
                    ts = row[time_col]
                    quote = {'id': row['product_id'], 'timestep': ts, 'price': price, 'data': {'Price Close': price}}
                    data_by_product[row['product_id']].append(quote)
                 except (ValueError, KeyError): pass

            all_quotes = []
            for ric in universe: all_quotes.extend(data_by_product[ric])
            all_quotes.sort(key=lambda q: (q['timestep'], q['id']))

            batched_data = []
            current_batch = []
            last_ts = None
            for quote in all_quotes:
                ts = quote['timestep']
                if last_ts is None: last_ts = ts
                if ts != last_ts:
                    if current_batch:
                         current_batch.append({'id': 'Clock', 'timestep': last_ts})
                         batched_data.append(current_batch)
                    current_batch = [quote]
                    last_ts = ts
                else:
                    current_batch.append(quote)
            if current_batch:
                 current_batch.append({'id': 'Clock', 'timestep': last_ts})
                 batched_data.append(current_batch)

        else: # WIDE FORMAT
            universe = sorted([h for h in headers if h != time_col])
            batched_data = []
            for row in all_rows:
                ts = row.get(time_col)
                current_batch = []
                for ric in universe:
                    if row.get(ric) and row[ric] not in ('', 'NaN'):
                        try:
                            price = float(row[ric])
                            quote = {'id': ric, 'timestep': ts, 'price': price, 'data': {'Price Close': price}}
                            current_batch.append(quote)
                        except ValueError: pass
                if current_batch:
                    current_batch.append({'id': 'Clock', 'timestep': ts})
                    batched_data.append(current_batch)

        return universe, batched_data
    except Exception as e:
        print(f"ERROR: Failed to process CSV file {csv_path}: {e}")
        sys.exit(1)

# --- Load Submission ---
def load_submission(submission_path: str):
    logger.debug(f"Loading submission from: {submission_path}")
    
    # 1. Enforce constraints BEFORE loading the file
    enforce_cloud_constraints()

    try:
        spec = importlib.util.spec_from_file_location("submission", submission_path)
        if spec is None: raise ImportError(f"Could not load spec for {submission_path}")
        mod = importlib.util.module_from_spec(spec)
       
        # Mock pricing modules so imports don't fail
        sys.modules['pricing'] = importlib.import_module('src.pricing')
        sys.modules['pricing.Market'] = importlib.import_module('src.pricing.Market')
        sys.modules['pricing.Portfolio'] = importlib.import_module('src.pricing.Portfolio')

        spec.loader.exec_module(mod)

        if not hasattr(mod, 'build_trader'):
            raise AttributeError("submission.py must define 'build_trader(universe)'")
        
        return mod.build_trader
    
    except ImportError as e:
        print(f"\n❌ IMPORT ERROR: {e}")
        print("   Remember: The cloud environment DOES NOT have libraries like sklearn, scipy, or xgboost.")
        print("   You must use only standard Python, numpy, and pandas.\n")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Failed to load submission.py: {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    data_path = os.path.join(os.path.dirname(project_root), "data", "comp_data.csv")
    
    if len(sys.argv) != 2:
        print("Usage: python local_eval.py <path_to_submission_py>")
        if not os.path.exists(data_path):
            print(f"ERROR: Default data file not found at {data_path}")
            sys.exit(1)
        submission_path = "submission/submission.py" # Default
    else:
        submission_path = sys.argv[1]

    if not os.path.exists(data_path):
         print(f"ERROR: Data file not found at {data_path}. Run 'sync-data' first.")
         sys.exit(1)

    strategy_builder_func = load_submission(submission_path)
    universe, data_batches = read_and_batch_csv_data(data_path)

    try:
        # Pass universe to the builder (Fixes the signature mismatch)
        engine = Engine(universe, data_batches, strategy_builder_func, initial_cash=100000.0)
        engine.run()
    except Exception as e:
        print(f"\n--- ERROR during Engine Run ---")
        traceback.print_exc()
        sys.exit(1)
    
    final_nav = engine.portfolio._net_asset_value()
    pnl = final_nav - engine.initial_cash
    sharpe = calculate_sharpe_ratio(engine.nav_history)

    logger.info("--- Local Evaluation Metrics ---")
    logger.info(f"Final NAV:         {final_nav:,.2f}")
    logger.info(f"Total PnL:         {pnl:,.2f}")
    logger.info(f"Annualized Sharpe: {sharpe:.4f}")
    logger.debug("Local evaluation complete.")