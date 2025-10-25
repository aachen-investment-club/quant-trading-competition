import os, sys, csv, io, time, importlib.util, types, traceback
import boto3
from decimal import Decimal

s3  = boto3.client("s3")
ddb = boto3.resource("dynamodb")

# ---- Backtest primitives (mirror participant API) ----
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
        return self.product.present_value(market) * self.quantity
    def rebalance(self, new_price, new_quantity):
        self.price = (self.price * self.quantity + new_price * new_quantity) / (self.quantity + new_quantity)
        self.quantity += new_quantity

class Portfolio():
    def __init__(self, cash, market):
        self.cash = cash; self.market = market; self.positions = {}
        self.tradelog = {ric: [] for ric in market.universe}
    def nav(self):
        mtm = sum([p.mark_to_market(self.market) for p in self.positions.values()])
        return self.cash + mtm
    def enter(self, new_position):
        ts = self.market.quotes[new_position.product.id]['timestamp']
        new_position.price = new_position.product.present_value(self.market)
        if self.cash < new_position.price * new_position.quantity:
            raise Exception("Insufficient funds")
        self.cash -= new_position.price * new_position.quantity
        if new_position.product.id in self.positions:
            cur = self.positions[new_position.product.id]
            cur.rebalance(new_position.price, new_position.quantity)
        else:
            self.positions[new_position.product.id] = new_position
        self.tradelog[new_position.product.id].append({"timestamp": ts, "quantity": new_position.quantity, "price": new_position.price})
    def exit(self, id):
        if id not in self.positions: raise Exception("Position not found")
        p = self.positions[id]
        self.cash += p.mark_to_market(self.market)
        self.tradelog[id] = {"timestamp": self.market.quotes[id]['timestamp'], "quantity": p.quantity, "price": p.price}
        self.positions.pop(id)

# Expose expected modules so participant imports work
mod_bt = types.ModuleType("backtest"); mod_pricing = types.ModuleType("backtest.pricing")
mod_pricing.Market = Market
mod_pricing.Product = Product
mod_pricing.Position = Position
mod_pricing.Portfolio = Portfolio
sys.modules['backtest'] = mod_bt
sys.modules['backtest.pricing'] = mod_pricing
sys.modules['backtest.pricing.Market']    = types.ModuleType('backtest.pricing.Market');    sys.modules['backtest.pricing.Market'].Market    = Market
sys.modules['backtest.pricing.Product']   = types.ModuleType('backtest.pricing.Product');   sys.modules['backtest.pricing.Product'].Product   = Product
sys.modules['backtest.pricing.Position']  = types.ModuleType('backtest.pricing.Position');  sys.modules['backtest.pricing.Position'].Position = Position
sys.modules['backtest.pricing.Portfolio'] = types.ModuleType('backtest.pricing.Portfolio'); sys.modules['backtest.pricing.Portfolio'].Portfolio = Portfolio

# ---- CSV readers ----
def iter_quotes_from_csv_long(csv_bytes, universe):
    # long format: timestamp,id,price (plus ignored columns)
    f = io.StringIO(csv_bytes.decode('utf-8'))
    reader = csv.DictReader(f)
    last_ts = None; batch = []
    for row in reader:
        if row.get('id') not in universe: 
            continue
        ts = row.get('timestamp')
        q = {'id': row['id'], 'timestamp': ts, 'price': float(row['price'])}
        if last_ts is None: last_ts = ts
        if ts != last_ts:
            yield batch
            batch = [q]; last_ts = ts
        else:
            batch.append(q)
    if batch:
        yield batch

def iter_quotes_from_csv_wide(csv_bytes, universe):
    # wide format: timestamp, EURUSD, GBPUSD, ...
    f = io.StringIO(csv_bytes.decode('utf-8'))
    reader = csv.DictReader(f)
    for row in reader:
        ts = row.get('timestamp')
        batch = []
        for ric in universe:
            if ric in row and row[ric] not in (None, '', 'NaN'):
                batch.append({'id': ric, 'timestamp': ts, 'price': float(row[ric])})
        if batch:
            yield batch

def evaluate_submission(py_path, table, participant_id, submission_id, universe, test_bucket, test_key, cash=100000.0):
    # Load participant submission
    spec = importlib.util.spec_from_file_location("submission", py_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
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

    for batch in iterator:
        for q in batch:
            market.update(q)
        try:
            trader.on_quote(market, portfolio)
        except Exception:
            # swallow trader exceptions to avoid breaking the run
            pass

    pnl = portfolio.nav() - cash
    score = pnl / cash

    item = {
        'participant_id': participant_id,
        'submission_id':  submission_id,
        'score':          Decimal(str(round(score, 6))),
        'pnl':            Decimal(str(round(pnl, 2))),
        'timestamp':      int(time.time()),
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
            evaluate_submission(local_path, table, participant_id, submission_id, universe, test_bucket, test_key)
        except Exception as e:
            table.put_item(Item={
                'participant_id': participant_id,
                'submission_id':  submission_id,
                'score':          Decimal('0'),
                'error':          str(e)[:500],
                'timestamp':      int(time.time())
            })
    return {'ok': True}
