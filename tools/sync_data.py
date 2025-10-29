#!/usr/bin/env python
import boto3
import os

# --- FIX: Read the region from environment variables ---
aws_region = os.environ.get('AWS_REGION')

if not aws_region:
    print("ERROR: You must set the AWS_REGION environment variable.")
    print("       (e.g., in your .env file)")
    exit(1)

print(f'Connecting to AWS services in region: {aws_region}...')
try:
    # --- FIX: Pass the region to the boto3 constructors ---
    ddb = boto3.resource('dynamodb', region_name=aws_region)
    s3 = boto3.client('s3', region_name=aws_region)
    
    table = ddb.Table(os.environ.get('DDB_TABLE', 'trading_competition_scores'))
    item = table.get_item(Key={'participant_id': 'SYSTEM_CONFIG', 'submission_id': 'ACTIVE_TEST_KEY'}).get('Item')

    if not item:
        print('ERROR: Could not find SYSTEM_CONFIG in DynamoDB.')
        exit(1)

    key = item['active_test_key']
    bucket = item['active_test_bucket']

    os.makedirs('data', exist_ok=True)
    print(f'Downloading s3://{bucket}/{key} to data/comp_data.csv')
    s3.download_file(bucket, key, 'data/comp_data.csv')
    print('Download complete.')

except Exception as e:
    print(f"An error occurred: {e}")
    exit(1)