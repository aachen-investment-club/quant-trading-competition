#!/usr/bin/env python3

"""
Submit your strategy folder to the competition S3 bucket.

Enhanced with import validation and error simulation.

Usage (inside the project folder on your machine):
    # Set required env vars once:
    export AWS_REGION=eu-central-1
    export SUBMISSIONS_BUCKET=your-submissions-bucket
    export PARTICIPANT_ID=alice123

    # Option A: use current timestamp as SUBMISSION_ID
    python tools/submit.py

    # Option B: explicitly set a submission id
    SUBMISSION_ID=myv1 python tools/submit.py

This uploads all files under ./submission/ to:
  s3://$SUBMISSIONS_BUCKET/$PARTICIPANT_ID/$SUBMISSION_ID/...

and UPLOADS `submission.py` LAST to avoid race conditions
with the S3 trigger (evaluation starts when `submission.py` appears).
"""

import os, sys, time, importlib.util, traceback, types
from pathlib import Path
from datetime import datetime

import boto3
from dotenv import load_dotenv
from botocore.exceptions import BotoCoreError, NoCredentialsError, ClientError

load_dotenv()
REQUIRED_ENVS = ["AWS_REGION", "SUBMISSIONS_BUCKET", "PARTICIPANT_ID"]

def die(msg, code=2):
    print(f"[submit] ERROR: {msg}", file=sys.stderr)
    sys.exit(code)

def validate_submission_imports(submission_path):
    """
    Validate that the submission can be imported and has the required structure.
    Simulates the Lambda environment as closely as possible.
    """
    print("[submit] Validating submission imports...")
    
    # Simulate Lambda's module injection
    class Market_local:
        def __init__(self, universe):
            self.universe = universe
            self.quotes = {}
        def update(self, quote):
            if quote['id'] != "Clock":
                self.quotes[quote['id']] = quote

    class Portfolio_local:
        def __init__(self, cash, market, leverage_limit):
            self.cash = cash
            self.market = market
            self.positions = {}
            self.leverage_limit = leverage_limit
        def _get_price(self, product):
            return 100.0  # Mock price
        def buy(self, product, quantity):
            return True
        def sell(self, product, quantity):
            return True

    # Inject modules like Lambda does
    mod_pricing = types.ModuleType("pricing")
    mod_pricing.Market = Market_local
    mod_pricing.Portfolio = Portfolio_local
    sys.modules['pricing'] = mod_pricing
    sys.modules['pricing.Market'] = types.ModuleType('pricing.Market')
    sys.modules['pricing.Market'].Market = Market_local
    sys.modules['pricing.Portfolio'] = types.ModuleType('pricing.Portfolio')
    sys.modules['pricing.Portfolio'].Portfolio = Portfolio_local

    try:
        # Import the submission
        spec = importlib.util.spec_from_file_location("submission", submission_path)
        if spec is None:
            raise ImportError(f"Could not create spec from {submission_path}")
        
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        
        # Check for required function
        if not hasattr(mod, 'build_trader'):
            raise AttributeError("submission.py must define a 'build_trader' function")
        trader = mod.build_trader()
        # Check for required method
        if not hasattr(trader, 'on_quote'):
            raise AttributeError("Trader object must have an 'on_quote' method")
        
        print("[submit] ✓ All imports and structure validated successfully")
        return True
        
    except Exception as e:
        print(f"[submit] ❌ Import validation failed:")
        print(f"[submit] Error: {e}")
        print(f"[submit] Traceback (similar to Lambda output):")
        traceback.print_exc()
        return False

def simulate_lambda_error_output(submission_path):
    """
    Simulate what the Lambda evaluator would output for common errors
    """
    print("\n[submit] Lambda Error Simulation:")
    print("=" * 50)
    
    # Common error patterns from Lambda
    common_errors = {
        "ModuleNotFoundError": "ERROR: Failed to build trader from submission.py",
        "AttributeError": "ERROR: The trader object built by build_trader() does not have an 'on_quote' method",
        "TypeError": "ERROR during on_quote",
        "ImportError": "ERROR: Failed to build trader from submission.py"
    }
    
    try:
        validate_submission_imports(submission_path)
        print("[submit] ✓ Submission would likely succeed in Lambda")
    except Exception as e:
        error_type = type(e).__name__
        lambda_message = common_errors.get(error_type, "ERROR during evaluation")
        print(f"[submit] Lambda would report: {lambda_message}")
        print(f"[submit] Full error: {e}")

def main():
    missing = [e for e in REQUIRED_ENVS if not os.environ.get(e)]
    if missing:
        die(f"Missing env vars: {', '.join(missing)}")

    region = os.environ["AWS_REGION"]
    bucket = os.environ["SUBMISSIONS_BUCKET"]
    participant = os.environ["PARTICIPANT_ID"]
    submission_id = os.environ.get("SUBMISSION_ID")
    if not submission_id:
        submission_id = time.strftime("%Y%m%d-%H%M%S")

    src_dir = Path(__file__).resolve().parents[1] / "submission"
    if not src_dir.exists():
        die(f"Submission folder not found: {src_dir}")

    submission_py = src_dir / "submission.py"
    if not submission_py.exists():
        die(f"submission.py not found in: {src_dir}")

    # Validate imports before uploading
    if not validate_submission_imports(str(submission_py)):
        print("\n[submit] Would you like to see how Lambda would report this error? (y/n)")
        if input().lower().startswith('y'):
            simulate_lambda_error_output(str(submission_py))
        
        print("\n[submit] Upload aborted due to validation errors.")
        print("[submit] Please fix the issues above and try again.")
        sys.exit(1)

    s3 = boto3.client("s3", region_name=region)

    # Collect files; upload everything except submission.py first
    files = [p for p in src_dir.rglob("*") if p.is_file()]
    files_non_trigger = [p for p in files if p.name != "submission.py"]
    file_trigger = [p for p in files if p.name == "submission.py"]

    if not file_trigger:
        die("submission.py not found under ./submission/")

    prefix = f"{participant}/{submission_id}/"
    
    def upload(path: Path):
        rel = str(path.relative_to(src_dir)).replace("\\", "/")
        key = prefix + rel
        extra = {}
        try:
            s3.upload_file(str(path), bucket, key, ExtraArgs=extra)
            print(f"[submit] uploaded s3://{bucket}/{key}")
        except (BotoCoreError, ClientError, NoCredentialsError) as e:
            die(f"Failed to upload {path}: {e}")

    print(f"[submit] Uploading to s3://{bucket}/{prefix}")
    for p in files_non_trigger:
        upload(p)

    # Upload trigger last
    upload(file_trigger[0])

    print("\n[submit] ✅ Done. Your evaluation will start shortly.")
    print(f"[submit] 📊 Track progress in CloudWatch Logs or check the leaderboard in a minute.")
    print(f"[submit] 📁 Submission prefix: s3://{bucket}/{prefix}")
    print(f"[submit] ⏰ Submission ID: {submission_id}")
    print(f"[submit] 👤 Participant ID: {participant}")

if __name__ == "__main__":
    main()