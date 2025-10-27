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
        self.tradelog[id] = {"timestep": self.market.quotes[id]['timestep'], "quantity": p.quantity, "price": p.price}
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
    header = csv_bytes.splitlines()[0].decode('utf-8')
    use_long = 'id' in header.split(',')
    iterator = iter_quotes_from_csv_long(csv_bytes, universe) if use_long else iter_quotes_from_csv_wide(csv_bytes, universe)

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

    item = {
        'participant_id': participant_id,
        'submission_id':  submission_id,
        'competition_id': competition_id,
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
    test_bucket        = os.environ['TESTDATA_BUCKET']
    test_key           = os.environ['TESTDATA_KEY']
    ddb_table_name     = os.environ['DDB_TABLE']
    universe           = os.environ.get('UNIVERSE', 'EURUSD,GBPUSD,USDJPY').split(',')
    competition_id     = os.environ.get('COMPETITION_ID', 'default-comp')
    
    table = ddb.Table(ddb_table_name)

    for record in event.get('Records', []):
        if record.get('eventSource') != 'aws:s3':
            continue
        key = record['s3']['object']['key']
        if not key.endswith('submission.py'):
            continue
        parts = key.split('/')
        if len(parts) < 3:
            continue
        
        participant_id = parts[0]
        submission_id  = parts[1]

        local_path = f"/tmp/{participant_id}_{submission_id}_submission.py"
        s3.download_file(submissions_bucket, key, local_path)

        try:
            evaluate_submission(
                local_path, table, 
                participant_id, submission_id, competition_id, 
                universe, test_bucket, test_key
            )
        except Exception as e:
            table.put_item(Item={
                'participant_id': participant_id,
                'submission_id':  submission_id,
                'competition_id': competition_id,
                'score':          Decimal('-999'),
                'error':          str(e)[:500],
                'timestep':      int(time.time())
            })
    return {'ok': True}