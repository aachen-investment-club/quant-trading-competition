#!/usr/bin/env python3
"""
Check the status of a specific submission ID in the cloud DynamoDB table.
Usage: python tools/check_status.py <SUBMISSION_ID>
"""

import os
import sys
import boto3
import time
from decimal import Decimal

# Try to load .env manually if python-dotenv is not installed in the minimal env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

def check_submission_status(submission_id):
    # Configuration
    # These env vars are set by the Docker container or your .env file
    PARTICIPANT_ID = os.environ.get("PARTICIPANT_ID")
    REGION = os.environ.get("AWS_REGION", "eu-central-1")
    # The default table name from Terraform
    TABLE_NAME = os.environ.get("DDB_TABLE", "trading_competition_scores")

    if not PARTICIPANT_ID:
        print("❌ Error: PARTICIPANT_ID not set. Are you running this via Docker?")
        return

    print(f"Checking status for Participant: {PARTICIPANT_ID}, Submission: {submission_id}...")
    print(f"Region: {REGION}, Table: {TABLE_NAME}")

    try:
        dynamodb = boto3.resource('dynamodb', region_name=REGION)
        table = dynamodb.Table(TABLE_NAME)

        response = table.get_item(
            Key={
                'participant_id': PARTICIPANT_ID,
                'submission_id': submission_id
            }
        )
    except Exception as e:
        print(f"❌ Error connecting to AWS: {e}")
        print("   Check your .env file credentials.")
        return

    item = response.get('Item')
    
    if not item:
        print("\n⚠️  Record not found yet.")
        print("   - The evaluation might still be running (it takes 1-3 minutes).")
        print("   - Or the submission ID is incorrect.")
        print("   - Or the evaluator crashed before writing to DB (check imports!).")
        return

    print("\n" + "="*40)
    
    # Check for Error
    if 'error' in item:
        print("❌ EVALUATION FAILED")
        print("-" * 40)
        print(f"Error Message from Cloud:\n{item['error']}")
        print("-" * 40)
        print("Common fixes:")
        print("1. Did you import a disallowed library (sklearn, scipy)?")
        print("2. Did you include helper files? (Only submission.py is used)")
        print("3. Does build_trader() accept the 'universe' argument?")
    else:
        print("✅ EVALUATION SUCCESS")
        print("-" * 40)
        print(f"Sharpe Ratio:   {item.get('sharpe_ratio', 'N/A')}")
        print(f"Score:          {item.get('score', 'N/A')}")
        print(f"PnL:            {item.get('pnl', 'N/A')}")
        print(f"Final NAV:      {item.get('final_nav', 'N/A')}")
    
    print("="*40 + "\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: check-status <SUBMISSION_ID>")
        print("   or: python tools/check_status.py <SUBMISSION_ID>")
        sys.exit(1)
    
    sub_id = sys.argv[1]
    check_submission_status(sub_id)