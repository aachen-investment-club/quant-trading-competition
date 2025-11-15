import json
import os, sys, csv, io, time, importlib.util, types, traceback
import boto3
from decimal import Decimal
import numpy as np
import pandas as pd
import logging

s3 = boto3.client("s3")
ddb = boto3.resource("dynamodb")

# --- Configure Logger (to capture logs from copied modules) ---
# Basic config to send logs to CloudWatch
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("local_eval")


# ---- Backtest primitives (COPIED FROM /src FILES) ----

# --- Helper function copied from src/Engine.py ---
def calculate_sharpe_ratio(nav_history, periods_per_year=252):
    """
    Calculates the annualized Sharpe ratio from a list of NAVs.
    Assumes risk-free rate is 0.
    """
    if not nav_history or len(nav_history) < 2:
        return 0.0
    nav_series = pd.Series(nav_history)
    returns = nav_series.pct_change().dropna()
    if returns.empty or returns.std() == 0:
        return 0.0
    mean_return = returns.mean()
    annualized_mean_return = mean_return * periods_per_year
    std_dev = returns.std()
    annualized_std_dev = std_dev * np.sqrt(periods_per_year)
    if annualized_std_dev == 0:
        return 0.0
    sharpe = annualized_mean_return / annualized_std_dev
    return float(sharpe)
# --- End helper function ---


# --- Market class copied from src/pricing/Market.py ---
class Market_local():
    def __init__(self: "Market_local", universe: list[str]) -> None:
        self.universe: list[str] = universe
        self.quotes: dict[str, dict] = {}  # {key: product, value: {key: timestep, value: price}}
        
    def update(self: "Market_local", quote: dict)-> None:
        if quote['id'] != "Clock":
            self.quotes[quote['id']] = quote

    def __str__(self: "Market_local") -> str:
        return str(self.quotes)

# --- Portfolio class copied from src/pricing/Portfolio.py ---
# Note: Removed 'from pricing.Market import Market' as it's now in the same scope
class Portfolio_local():
    def __init__(self, cash: float, market: "Market_local", leverage_limit: float) -> None:
        self.cash: float = cash
        self.market: Market_local = market
        self.positions: dict[str, int] = {}  # key: product, value: quantity
        self.leverage_limit: float = leverage_limit  # max leverage allowed

    def _get_price(self, product: str) -> float:
        """Retrieve the last market price for a given product."""
        if product not in self.market.quotes:
            raise ValueError(f"No quote available for {product}")
        return self.market.quotes[product].get("price", None)
    
    def _get_timestamp(self, product) -> int:
        """Retrieve the current market timestamp for the product quote."""
        if product not in self.market.quotes:
            raise ValueError(f"No quote available for {product}")
        return self.market.quotes[product].get("timestep", None)

    def _gross_exposure(self) -> float:
        """Compute gross exposure = sum(|position| * price)"""
        total = 0.0
        for product, qty in self.positions.items():
            price = self._get_price(product)
            total += abs(qty) * price
        return total

    def _net_asset_value(self) -> float:
        """Compute portfolio net asset value = cash + sum(qty * price)"""
        value = self.cash
        for product, qty in self.positions.items():
            price = self._get_price(product)
            value += qty * price
        return value
    
    def _leverage(self) -> float:
        """Compute current leverage = gross exposure / net asset value"""
        gross = self._gross_exposure()
        net_value = self._net_asset_value()
        return gross / max(net_value, 1e-8)  # Avoid division by zero

    def _check_leverage(self, new_cash: float, new_positions: dict[str, int]) -> bool:
        """Check whether the new portfolio state respects leverage limits."""
        gross = sum(abs(qty) * self._get_price(p) for p, qty in new_positions.items())
        net_value = new_cash + sum(qty * self._get_price(p) for p, qty in new_positions.items())
        leverage = gross / max(net_value, 1e-8)
        return leverage <= self.leverage_limit

    def buy(self, product: str, quantity: int) -> bool:
        """Attempt to buy `quantity` units of `product`."""
        timestamp = self._get_timestamp(product)
        price = self._get_price(product)
        cost = price * quantity

        new_cash = self.cash - cost
        new_positions = self.positions.copy()
        new_positions[product] = new_positions.get(product, 0) + quantity

        if not self._check_leverage(new_cash, new_positions):
            logger.warning(f"{timestamp} | Trade rejected: leverage limit exceeded.")
            return False

        self.cash = new_cash
        self.positions = new_positions
        logger.info(f"{timestamp} | BOUGHT {quantity} {product} @ {price} | new cash={self.cash:.2f}")
        return True

    def sell(self, product: str, quantity: int) -> bool:
        """Attempt to sell `quantity` units of `product` (shorts allowed)."""
        timestamp = self._get_timestamp(product)
        price = self._get_price(product)
        proceeds = price * quantity

        new_cash = self.cash + proceeds
        new_positions = self.positions.copy()
        new_positions[product] = new_positions.get(product, 0) - quantity

        if not self._check_leverage(new_cash, new_positions):
            logger.warning("Trade rejected: leverage limit exceeded.")
            return False

        self.cash = new_cash
        self.positions = new_positions
        logger.info(f"{timestamp} | SOLD {quantity} {product} @ {price} | new cash={self.cash:.2f}")
        return True

    def summary(self) -> dict:
        """Return a snapshot of the portfolio."""
        return {
            "cash": self.cash,
            "positions": self.positions,
            "gross_exposure": self._gross_exposure(),
            "net_value": self._net_asset_value(),
            "leverage": self._leverage(),
        }

    def __str__(self) -> str:
        return str(self.summary())

# --- Engine class copied from src/Engine.py ---
# Note: Removed relative imports for Portfolio and Market
class Engine_local():
    def __init__(self, universe: list[str], data_batches: list[list[dict]], strategy_builder, initial_cash=100000.0) -> None:
        self.initial_cash = initial_cash
        self.universe = universe

        # Store pre-processed data directly
        self.data_batches = data_batches
        self.total_data_points = sum(len(batch) for batch in data_batches)

        # Set strategy, portfolio and market
        self.market: Market_local = Market_local(universe)
        self.portfolio: Portfolio_local = Portfolio_local(cash=initial_cash, market=self.market, leverage_limit=10.0)

        # Build the strategy using the provided builder function
        # Build the strategy using the provided builder function
        try:
            self.strategy = strategy_builder(universe)  # Pass the universe parameter
            logger.debug(f"Successfully built trader: {type(self.strategy).__name__}")
        except Exception as e:
            logger.error(f"ERROR: Failed to build trader from submission.py: {e}")
            traceback.print_exc()
            raise

        self.nav_history: list[float] = [initial_cash]

    def run(self) -> None:
        if not hasattr(self.strategy, 'on_quote'):
             logger.error("ERROR: The trader object built by build_trader() does not have an 'on_quote' method.")
             return

        logger.debug("Running cloud evaluation...")
        
        # --- Iterate directly through pre-processed batches ---
        for quote_batch in self.data_batches:
            
            # 1. Update market with all quotes in the batch
            # (The batch includes quotes for all products at one timestamp)
            for q in quote_batch:
                self.market.update(q)

            # 2. Call the trader's logic ONCE per batch
            # This mimics the cloud lambda's event-driven approach
            try:
                self.strategy.on_quote(self.market, self.portfolio)
            except Exception as e:
                # Log errors
                logger.error(f"\n--- ERROR during on_quote ---")
                traceback.print_exc()
                logger.error("--------------------------------\n")
                # Mimic the cloud's behavior of swallowing exceptions
                pass 
            
            # 3. Record NAV history after the batch
            self.nav_history.append(self.portfolio._net_asset_value())

# ---- End of copied code from /src ----


# --- Expose copied modules so participant imports work ---
mod_pricing = types.ModuleType("pricing")
mod_pricing.Market = Market_local
mod_pricing.Portfolio = Portfolio_local
# Product and Position are not used by submission.py, so we omit them.
sys.modules['pricing'] = mod_pricing
sys.modules['pricing.Market'] = types.ModuleType('pricing.Market'); sys.modules['pricing.Market'].Market = Market_local
sys.modules['pricing.Portfolio'] = types.ModuleType('pricing.Portfolio'); sys.modules['pricing.Portfolio'].Portfolio = Portfolio_local


# --- CSV Reader Logic (Adapted from src/local_eval.py) ---
def read_and_batch_csv_data(csv_bytes: bytes) -> tuple[list[str], list[list[dict]]]:
    """
    Reads the CSV bytes, detects format, determines universe, processes into batches
    suitable for the simplified Engine, and returns universe list and batches.
    """
    logger.debug(f"Reading and batching data from S3 bytes...")
    data_by_product = {} # To hold data temporarily if long format
    all_rows = [] # To hold dicts read from CSV
    universe = []

    try:
        # --- MODIFIED: Read from in-memory bytes instead of a file path ---
        f = io.StringIO(csv_bytes.decode('utf-8'))
        header_line = f.readline().strip()
        headers = [h.strip() for h in header_line.split(',')]
        f.seek(0)
        reader = csv.DictReader(f)
        all_rows = list(reader)
        # --- End modification ---

        logger.debug(f"CSV Headers: {headers}")
        time_col = 'timestep' if 'timestep' in headers else 'timestamp' # Determine time column name

        # --- Format Detection and Universe Extraction (Logic is identical to local_eval) ---
        if 'product_id' in headers: # LONG FORMAT
            logger.debug("Detected LONG format CSV.")
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
                        'timestep': ts,
                        'price': price,
                        'data': {'Price Close': price}
                    }
                    data_by_product[row['product_id']].append(quote)
                 except (ValueError, KeyError) as e:
                    print(f"Skipping row due to error: {e} in row: {row}")

            all_quotes = []
            for ric in universe:
                all_quotes.extend(data_by_product[ric])

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
            logger.debug("Detected WIDE format CSV.")
            universe = sorted([h for h in headers if h != time_col])
            batched_data = []
            for row in all_rows:
                ts = row.get(time_col)
                current_batch = []
                for ric in universe:
                    if row.get(ric) is not None and row[ric] not in ('', 'NaN'):
                        try:
                            price = float(row[ric])
                            quote = {
                                'id': ric,
                                'timestep': ts,
                                'price': price,
                                'data': {'Price Close': price}
                            }
                            current_batch.append(quote)
                        except (ValueError, KeyError) as e:
                             print(f"Skipping value for {ric} due to error: {e} in row: {row}")
                if current_batch: 
                    current_batch.append({'id': 'Clock', 'timestep': ts})
                    batched_data.append(current_batch)

        logger.debug(f"Determined Universe: {universe}")
        logger.debug(f"Processed into {len(batched_data)} batches.")
        return universe, batched_data

    except Exception as e:
        print(f"ERROR: Failed to read or process CSV bytes: {e}")
        traceback.print_exc()
        # Re-raise to be caught by the handler
        raise


# --- Main Evaluation Function (ADAPTED) ---
def evaluate_submission(py_path, table, participant_id, submission_id, competition_id, test_bucket, test_key, cash=100000.0):
    
    # Load participant submission
    spec = importlib.util.spec_from_file_location("submission", py_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    
    if not hasattr(mod, 'build_trader'):
        raise RuntimeError("submission.py must define build_trader()")

    # Get the factory function
    strategy_builder_func = mod.build_trader

    # Download hidden test data (CSV) from S3
    buf = io.BytesIO()
    s3.download_fileobj(test_bucket, test_key, buf)
    csv_bytes = buf.getvalue()

    # --- NEW: Use the local_eval data processor ---
    # This dynamically finds the universe and creates the batches
    universe, data_batches = read_and_batch_csv_data(csv_bytes)
    
    print(f"Dynamically determined universe: {universe}")
    
    # --- NEW: Use the local Engine ---
    engine = Engine_local(
        universe=universe, 
        data_batches=data_batches, 
        strategy_builder=strategy_builder_func, 
        initial_cash=cash
    )
    
    # Run the backtest
    engine.run()

    # --- NEW: Get results from the Engine ---
    final_nav = engine.portfolio._net_asset_value()
    pnl = final_nav - engine.initial_cash
    percent_return = (final_nav / cash) - 1.0
    
    # Use the consistent Sharpe ratio calculation
    sharpe = calculate_sharpe_ratio(engine.nav_history, periods_per_year=252)

    # The 'score' will be the Sharpe Ratio, used for the GSI
    score = sharpe

    evaluation_id = f"{submission_id}"

    # --- FIX: Removed non-breaking spaces (U+00A0) ---
    item = {
        'participant_id': participant_id,
        'submission_id': evaluation_id,
        'competition_id': competition_id,
        'original_submission_id': submission_id,
        'score': Decimal(str(round(score, 6))),
        'sharpe_ratio': Decimal(str(round(sharpe, 6))),
        'pnl': Decimal(str(round(pnl, 2))),
        'percent_return': Decimal(str(round(percent_return, 6))),
        'final_nav': Decimal(str(round(final_nav, 2))),
        'timestep': int(time.time()),
        'universe': universe, 
        'test_key': test_key,
    }
    table.put_item(Item=item)
    return item

# --- Lambda Handler (ADAPTED) ---
def lambda_handler(event, context):
    submissions_bucket = os.environ['SUBMISSIONS_BUCKET']
    test_bucket = os.environ['TESTDATA_BUCKET'] # Default bucket
    test_key = os.environ.get('TESTDATA_KEY') # Default/Fallback key
    ddb_table_name = os.environ['DDB_TABLE']
    competition_id = os.environ.get('COMPETITION_ID', 'default-comp')

    table = ddb.Table(ddb_table_name)
    submissions_to_process = []

    if 'Records' in event and event['Records'] and 'eventSource' in event['Records'][0]:
        event_source = event['Records'][0]['eventSource']

        # Case 1: Triggered by S3 (New Submission)
        if event_source == 'aws:s3':
            print("Triggered by S3 submission event.")

            eval_test_key = test_key
            eval_test_bucket = test_bucket 
            try:
                response = table.get_item(Key={'participant_id': 'SYSTEM_CONFIG', 'submission_id': 'ACTIVE_TEST_KEY'})
                config = response.get('Item')
                if config:
                    eval_test_key = config['active_test_key']
                    eval_test_bucket = config['active_test_bucket']
                    print(f"Using active test key from DDB: {eval_test_key}")
                else:
                    print("No active test key in DDB, using fallback env var.")
                    if not test_key: raise ValueError("No active key in DDB and TESTDATA_KEY env var not set.")
            except Exception as e:
                print(f"Error fetching active key from DDB, using fallback: {e}")
                if not test_key: raise ValueError(f"DDB fetch failed and TESTDATA_KEY env var not set: {e}")

            for record in event.get('Records', []):
                try:
                    key = record['s3']['object']['key']

                    if not key.endswith('submission.py'):
                        print(f"Skipping key (does not end with submission.py): {key}")
                        continue 
                    parts = key.split('/')
                    if len(parts) < 3:
                        print(f"Skipping key (invalid format): {key}")
                        continue 

                    participant_id = parts[0]
                    submission_id = parts[1]

                    submissions_to_process.append({
                        'participant_id': participant_id,
                        'submission_id': submission_id,
                        's3_key': key,
                        'source': 's3',
                        'test_data_key': eval_test_key,
                        'test_data_bucket': eval_test_bucket
                    })
                except Exception as e:
                    print(f"Error parsing S3 record: {record}. Error: {e}")

        # Case 2: Triggered by SQS (Re-evaluation)
        elif event_source == 'aws:sqs':
            print("Triggered by SQS re-evaluation event.")
            for record in event.get('Records', []):
                try:
                    message_body = json.loads(record['body'])
                    participant_id = message_body['participant_id']
                    submission_id = message_body['submission_id']
                    eval_test_key = message_body['test_data_key']
                    eval_test_bucket = message_body['test_data_bucket']
                    s3_key = f"{participant_id}/{submission_id}/submission.py"

                    submissions_to_process.append({
                        'participant_id': participant_id,
                        'submission_id': submission_id,
                        's3_key': s3_key,
                        'source': 'sqs',
                        'receipt_handle': record.get('receiptHandle'),
                        'test_data_key': eval_test_key,
                        'test_data_bucket': eval_test_bucket 
                    })
                except Exception as e:
                        print(f"Error parsing SQS record: {record}. Error: {e}")

        else:
            print(f"Warning: Unrecognized event source: {event_source}")
            return {'statusCode': 400, 'body': 'Unrecognized event source'}

    else:
       print("Warning: Event format not recognized as S3 or SQS.")
       return {'statusCode': 400, 'body': 'Unrecognized event format'}


    # --- Process the identified submissions ---
    success_count = 0
    failure_count = 0

    for sub_info in submissions_to_process:
        participant_id = sub_info['participant_id']
        submission_id = sub_info['submission_id']
        s3_key = sub_info['s3_key']
        eval_test_key = sub_info['test_data_key']
        eval_test_bucket = sub_info['test_data_bucket']
        local_path = f"/tmp/{participant_id}_{submission_id}_submission.py"

        try:
            print(f"Processing submission: p={participant_id}, s={submission_id}")
            print(f"Using test file: s3://{eval_test_bucket}/{eval_test_key}")

            s3.download_file(submissions_bucket, s3_key, local_path)

            evaluate_submission(
                py_path=local_path,
                table=table,
                participant_id=participant_id,
                submission_id=submission_id,
                competition_id=competition_id,
                # --- REMOVED: universe is dynamic ---
                # universe=universe,
                test_bucket=eval_test_bucket, 
                test_key=eval_test_key 
            )

            print(f"Successfully evaluated: p={participant_id}, s={submission_id}")
            success_count += 1

            if sub_info['source'] == 'sqs' and sub_info.get('receipt_handle'):
                try:
                    sqs_client = boto3.client('sqs')
                    # NOTE: This requires SQS_QUEUE_URL_FOR_EVALUATOR env var to be set in Lambda
                    sqs_eval_queue_url = os.environ.get('SQS_QUEUE_URL_FOR_EVALUATOR') 
                    if sqs_eval_queue_url:
                        sqs_client.delete_message(
                            QueueUrl=sqs_eval_queue_url,
                            ReceiptHandle=sub_info['receipt_handle']
                        )
                        print(f"Deleted SQS message for {participant_id}/{submission_id}")
                    else:
                        print("Warning: SQS Queue URL for evaluator not configured. Cannot delete message.")

                except Exception as sqs_e:
                    print(f"Error deleting SQS message for {participant_id}/{submission_id}: {sqs_e}")


        except Exception as e:
            print(f"ERROR evaluating submission p={participant_id}, s={submission_id}: {e}")
            traceback.print_exc() 
            failure_count += 1
            # Write error record to DynamoDB
            try:
                # --- FIX: Removed non-breaking spaces (U+00A0) ---
                table.put_item(Item={
                    'participant_id': participant_id,
                    'submission_id': submission_id,
                    'competition_id': competition_id,
                    'score': Decimal('-999'), # Indicate error
                    'error': str(e)[:500],
                    'timestamp': int(time.time())
                })
            except Exception as ddb_e:
                print(f"ERROR writing error record to DynamoDB for p={participant_id}, s={submission_id}: {ddb_e}")
        
        finally:
            if os.path.exists(local_path):
                os.remove(local_path)

    print(f"Processing complete. Success: {success_count}, Failures: {failure_count}")
    return {'ok': True, 'processed': success_count, 'failed': failure_count}