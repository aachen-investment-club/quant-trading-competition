import json
import os, sys, csv, io, time, importlib.util, types, traceback
import boto3
from decimal import Decimal
import numpy as np
import pandas as pd

s3  = boto3.client("s3")
ddb = boto3.resource("dynamodb")

# ---- Backtest primitives (mirror participant API) ----
# NOTE: Keeping these classes as requested, as they are required by this
# standalone Lambda function's current packaging setup.
class Market():
    def __init__(self, universe):
        self.universe = universe
        self.quotes = {}
    def update(self, quote):
        if quote['id'] != "Clock":
            self.quotes[quote['id']] = quote

class Product:
    def __init__(self, id): self.id = id
    def present_value(self, market): raise NotImplementedError

class Position:
    def __init__(self, product, quantity):
        self.product  = product
        self.quantity = quantity
        self.price    = None
    def mark_to_market(self, market):
        # HACK: This is a flaw in the original logic. 
        # The participant's submission must define present_value on the product it returns.
        # We will assume the provided 'Stock.py' logic is what's used.
        if hasattr(self.product, 'present_value') and callable(self.product.present_value):
             return self.product.present_value(market) * self.quantity
        else:
            # Fallback for simple products that don't have the method
            try:
                return market.quotes[self.product.id]['price'] * self.quantity
            except:
                return 0 # Or some other sensible default if market quote isn't ready
                
    def rebalance(self, new_price, new_quantity):
        if self.price is None: self.price = 0.0 # Handle first entry
        # avoid division by zero if total quantity becomes 0 (shouldn't happen on enter)
        if (self.quantity + new_quantity) != 0:
            self.price = (self.price * self.quantity + new_price * new_quantity) / (self.quantity + new_quantity)
        else:
            self.price = 0.0
        self.quantity += new_quantity

class Portfolio():
    def __init__(self, cash, market):
        self.cash = cash; self.market = market; self.positions = {}
        self.tradelog = {ric: [] for ric in market.universe}
    def nav(self):
        mtm = sum([p.mark_to_market(self.market) for p in self.positions.values()])
        return self.cash + mtm
    def enter(self, new_position):
        # HACK: Same logic as Position.mark_to_market.
        # We must get the price from the participant's product implementation.
        try:
            if hasattr(new_position.product, 'present_value') and callable(new_position.product.present_value):
                new_position.price = new_position.product.present_value(self.market)
            else:
                 new_position.price = self.market.quotes[new_position.product.id]['price']
        except:
             # Cannot enter position if price is unknown
             print(f"Warning: Could not get price for {new_position.product.id}. Skipping trade.")
             return

        ts = self.market.quotes[new_position.product.id]['timestep']

        if self.cash < new_position.price * new_position.quantity:
            # Don't raise, just log. This matches the "swallow trader exceptions" logic later.
            print(f"Warning: Insufficient funds to enter {new_position.product.id}. Skipping trade.")
            return
            
        self.cash -= new_position.price * new_position.quantity
        if new_position.product.id in self.positions:
            cur = self.positions[new_position.product.id]
            cur.rebalance(new_position.price, new_position.quantity)
        else:
            self.positions[new_position.product.id] = new_position
        self.tradelog[new_position.product.id].append({"timestep": ts, "quantity": new_position.quantity, "price": new_position.price})
    def exit(self, id):
        if id not in self.positions: 
            print(f"Warning: Attempted to exit position not found: {id}. Skipping trade.")
            return
            
        p = self.positions[id]
        
        try:
             # HACK: Use the product's PV method if available
            if hasattr(p.product, 'present_value') and callable(p.product.present_value):
                exit_value = p.product.present_value(self.market) * p.quantity
            else:
                exit_value = self.market.quotes[id]['price'] * p.quantity
        except:
            print(f"Warning: Could not get exit price for {id}. Using last MTM.")
            exit_value = p.mark_to_market(self.market) # Fallback

        self.cash += exit_value
        self.tradelog[id].append({"timestep": self.market.quotes[id]['timestep'], "quantity": -p.quantity, "price": p.price})
        self.positions.pop(id)

# Expose expected modules so participant imports work
mod_pricing = types.ModuleType("pricing")
mod_pricing.Market = Market
mod_pricing.Product = Product
mod_pricing.Position = Position
mod_pricing.Portfolio = Portfolio
sys.modules['pricing'] = mod_pricing
sys.modules['pricing.Market']    = types.ModuleType('pricing.Market');    sys.modules['pricing.Market'].Market    = Market
sys.modules['pricing.Product']   = types.ModuleType('pricing.Product');   sys.modules['pricing.Product'].Product   = Product
sys.modules['pricing.Position']  = types.ModuleType('pricing.Position');  sys.modules['pricing.Position'].Position = Position
sys.modules['pricing.Portfolio'] = types.ModuleType('pricing.Portfolio'); sys.modules['pricing.Portfolio'].Portfolio = Portfolio

# ---- CSV readers ----
def iter_quotes_from_csv_long(csv_bytes, universe):
    # long format: timestep,id,price (plus ignored columns)
    f = io.StringIO(csv_bytes.decode('utf-8'))
    reader = csv.DictReader(f)
    last_ts = None; batch = []
    for row in reader:
        if row.get('id') not in universe: 
            continue
        ts = row.get('timestep')
        # HACK: Support the 'Stock.py' file which expects a dict-like data object
        q = {'id': row['id'], 'timestep': ts, 'price': float(row['price']), 'data': {'Price Close': float(row['price'])}}
        if last_ts is None: last_ts = ts
        if ts != last_ts:
            yield batch
            batch = [q]; last_ts = ts
        else:
            batch.append(q)
    if batch:
        yield batch

def iter_quotes_from_csv_wide(csv_bytes, universe):
    # wide format: timestep, EURUSD, GBPUSD, ...
    f = io.StringIO(csv_bytes.decode('utf-8'))
    reader = csv.DictReader(f)
    for row in reader:
        ts = row.get('timestep')
        batch = []
        for ric in universe:
            if ric in row and row[ric] not in (None, '', 'NaN'):
                price = float(row[ric])
                # HACK: Support the 'Stock.py' file which expects a dict-like data object
                batch.append({'id': ric, 'timestep': ts, 'price': price, 'data': {'Price Close': price}})
        if batch:
            yield batch

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

    # Annualize mean return
    mean_return = returns.mean()
    annualized_mean_return = mean_return * periods_per_year

    # Annualize standard deviation
    std_dev = returns.std()
    annualized_std_dev = std_dev * np.sqrt(periods_per_year)

    if annualized_std_dev == 0:
        return 0.0

    sharpe = annualized_mean_return / annualized_std_dev
    return float(sharpe)

def evaluate_submission(py_path, table, participant_id, submission_id, competition_id, universe, test_bucket, test_key, cash=100000.0):
    # Load participant submission
    spec = importlib.util.spec_from_file_location("submission", py_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    
    # This interface is different from your `submission.py` file, but I am keeping it
    # as you requested to keep this Lambda.
    if not hasattr(mod, 'build_trader'):
        raise RuntimeError("submission.py must define build_trader(universe)")

    # Download hidden test data (CSV) from S3
    buf = io.BytesIO()
    s3.download_fileobj(test_bucket, test_key, buf)
    csv_bytes = buf.getvalue()

    # Try to detect format
    header_line = csv_bytes.splitlines()[0].decode('utf-8')
    headers = [h.strip() for h in header_line.split(',')]
    
    use_long = 'id' in headers or 'product_id' in headers # Check for long format
    
    if use_long:
        # For LONG format, we must read the file to find all unique IDs
        print("Detecting universe from LONG format CSV...")
        f_for_universe = io.StringIO(csv_bytes.decode('utf-8'))
        reader = csv.DictReader(f_for_universe)
        universe_set = set()
        id_col = 'id' if 'id' in headers else 'product_id'
        for row in reader:
            if row.get(id_col):
                universe_set.add(row[id_col])
        universe = sorted(list(universe_set))
        iterator = iter_quotes_from_csv_long(csv_bytes, universe)
    else:
        # For WIDE format, universe is the headers (minus time)
        print("Detecting universe from WIDE format CSV...")
        time_col = 'timestep' if 'timestep' in headers else 'timestamp'
        universe = sorted([h for h in headers if h.lower() != time_col])
        iterator = iter_quotes_from_csv_wide(csv_bytes, universe)
        
    print(f"Dynamically determined universe: {universe}")

    market = Market(universe)
    portfolio = Portfolio(cash=cash, market=market)
    trader = mod.build_trader(universe)

    # CHANGED: Track NAV history for Sharpe calculation
    nav_history = [cash] # Start with initial cash
    
    for batch in iterator:
        for q in batch:
            market.update(q)
        try:
            # This is the event-based backtest loop
            trader.on_quote(market, portfolio)
        except Exception:
            # swallow trader exceptions to avoid breaking the run
            pass
        
        # CHANGED: Record NAV after each batch (e.g., each day)
        nav_history.append(portfolio.nav())

    # --- CHANGED: Calculate metrics ---
    final_nav = portfolio.nav()
    pnl = final_nav - cash
    percent_return = (final_nav / cash) - 1.0
    
    # Assuming data is daily, use 252 periods
    # If your data is hourly, you might change 252 to (252 * 8) or similar
    sharpe = calculate_sharpe_ratio(nav_history, periods_per_year=252)

    # The 'score' will be the Sharpe Ratio, used for the GSI
    score = sharpe

    evaluation_id = f"{submission_id}#{test_key}"

    item = {
        'participant_id': participant_id,
        'submission_id':  evaluation_id, # <-- Use the new unique ID as the Sort Key
        'competition_id': competition_id,
        'original_submission_id': submission_id, # <-- Store the original ID for the orchestrator
        'score':          Decimal(str(round(score, 6))),
        'sharpe_ratio':   Decimal(str(round(sharpe, 6))),
        'pnl':            Decimal(str(round(pnl, 2))),
        'percent_return': Decimal(str(round(percent_return, 6))),
        'final_nav':      Decimal(str(round(final_nav, 2))),
        'timestep':       int(time.time()),
        'universe':       universe,
        'test_key':       test_key,
    }
    table.put_item(Item=item)
    return item

def lambda_handler(event, context):
    submissions_bucket = os.environ['SUBMISSIONS_BUCKET']
    test_bucket        = os.environ['TESTDATA_BUCKET'] # Default bucket
    test_key           = os.environ.get('TESTDATA_KEY') # Default/Fallback key
    ddb_table_name     = os.environ['DDB_TABLE']
    universe           = os.environ.get('UNIVERSE', '').split(',') 
    competition_id     = os.environ.get('COMPETITION_ID', 'default-comp')

    table = ddb.Table(ddb_table_name)
    submissions_to_process = []

    if 'Records' in event and event['Records'] and 'eventSource' in event['Records'][0]:
        event_source = event['Records'][0]['eventSource']

        # Case 1: Triggered by S3 (New Submission)
        if event_source == 'aws:s3':
            print("Triggered by S3 submission event.")

            # --- NEW: Get active test key from DDB for S3 triggers ---
            eval_test_key = test_key     # Start with fallback
            eval_test_bucket = test_bucket # Start with fallback
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
            # --- End new block ---

            for record in event.get('Records', []):
                try:
                    key = record['s3']['object']['key']

                    # --- THIS IS THE MISSING LOGIC ---
                    if not key.endswith('submission.py'):
                        print(f"Skipping key (does not end with submission.py): {key}")
                        continue # Skip this record
                    parts = key.split('/')
                    if len(parts) < 3:
                        print(f"Skipping key (invalid format): {key}")
                        continue # Skip this record

                    participant_id = parts[0]
                    submission_id  = parts[1]
                    # --- END OF MISSING LOGIC ---

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

                    # --- NEW: Get test key from SQS message ---
                    eval_test_key = message_body['test_data_key']
                    eval_test_bucket = message_body['test_data_bucket']

                    s3_key = f"{participant_id}/{submission_id}/submission.py"

                    submissions_to_process.append({
                        'participant_id': participant_id,
                        'submission_id': submission_id,
                        's3_key': s3_key,
                        'source': 'sqs',
                        'receipt_handle': record.get('receiptHandle'),
                        'test_data_key': eval_test_key,      # <-- ADD
                        'test_data_bucket': eval_test_bucket # <-- ADD
                    })
                except Exception as e:
                     print(f"Error parsing SQS record: {record}. Error: {e}")

        else:
            print(f"Warning: Unrecognized event source: {event_source}")
            return {'statusCode': 400, 'body': 'Unrecognized event source'}

    else:
         # Handle potential direct invocation or other formats if needed
        print("Warning: Event format not recognized as S3 or SQS.")
        # Attempt to parse as direct invocation if necessary, otherwise return error
        # Example: if 'participant_id' in event and 'submission_id' in event: ...
        return {'statusCode': 400, 'body': 'Unrecognized event format'}


    # --- Process the identified submissions ---
    success_count = 0
    failure_count = 0

    for sub_info in submissions_to_process:
        participant_id = sub_info['participant_id']
        submission_id = sub_info['submission_id']
        s3_key = sub_info['s3_key']

        # --- MODIFIED: Use dynamic test keys ---
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
                universe=universe,
                test_bucket=eval_test_bucket, # <-- PASS DYNAMIC
                test_key=eval_test_key        # <-- PASS DYNAMIC
            )

            print(f"Successfully evaluated: p={participant_id}, s={submission_id}")
            success_count += 1

            # If triggered by SQS, delete the message upon success
            if sub_info['source'] == 'sqs' and sub_info.get('receipt_handle'):
                 try:
                     sqs_client = boto3.client('sqs')
                     sqs_queue_url = context.invoked_function_arn.replace(context.function_name, '').replace('function', 'queue').replace('arn:aws:lambda', 'https://sqs').replace(':','/') # Infer queue URL (might need adjustment)
                     # Or get queue URL from environment if passed
                     # sqs_queue_url = os.environ['SQS_QUEUE_URL'] 
                     
                     # Need to get the actual queue URL the trigger is associated with
                     event_source_arn = next((m['eventSourceARN'] for m in context.event_source_mappings if m['eventSourceARN'].startswith('arn:aws:sqs')), None)
                     if event_source_arn:
                         # Extract queue name and construct URL (this depends on region/account)
                         # Example: Construct URL based on ARN parts
                         # This part is tricky and might require passing the queue URL as an env var
                         # For now, let's assume you pass SQS_QUEUE_URL to evaluator too.
                         sqs_eval_queue_url = os.environ.get('SQS_QUEUE_URL_FOR_EVALUATOR') # Needs to be added to TF
                         if sqs_eval_queue_url:
                             sqs_client.delete_message(
                                 QueueUrl=sqs_eval_queue_url,
                                 ReceiptHandle=sub_info['receipt_handle']
                             )
                             print(f"Deleted SQS message for {participant_id}/{submission_id}")
                         else:
                             print("Warning: SQS Queue URL for evaluator not configured. Cannot delete message.")
                     else:
                        print("Warning: Could not determine SQS event source ARN. Cannot delete message.")

                 except Exception as sqs_e:
                     print(f"Error deleting SQS message for {participant_id}/{submission_id}: {sqs_e}")


        except Exception as e:
            print(f"ERROR evaluating submission p={participant_id}, s={submission_id}: {e}")
            traceback.print_exc() # Print full traceback to CloudWatch
            failure_count += 1
            # Write error record to DynamoDB
            try:
                table.put_item(Item={
                    'participant_id': participant_id,
                    'submission_id':  submission_id,
                    'competition_id': competition_id,
                    'score':          Decimal('-999'), # Indicate error
                    'error':          str(e)[:500],
                    'timestamp':      int(time.time())
                })
            except Exception as ddb_e:
                 print(f"ERROR writing error record to DynamoDB for p={participant_id}, s={submission_id}: {ddb_e}")
            # Do NOT delete SQS message on failure, let it retry or go to DLQ

        finally:
            # Clean up downloaded file
            if os.path.exists(local_path):
                os.remove(local_path)

    print(f"Processing complete. Success: {success_count}, Failures: {failure_count}")
    # Return structure might vary depending on source, but OK is generally fine
    return {'ok': True, 'processed': success_count, 'failed': failure_count}