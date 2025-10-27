import os
import boto3
import json
from boto3.dynamodb.conditions import Key
import time

dynamodb = boto3.resource('dynamodb')
sqs = boto3.client('sqs')

table_name = os.environ['DDB_TABLE_NAME']
queue_url = os.environ['SQS_QUEUE_URL']
table = dynamodb.Table(table_name)

# --- Helper to get all unique participant IDs ---
# Note: A Scan is potentially slow/expensive for large tables.
# Consider adding a GSI like (PK: competition_id, SK: participant_id)
# if you have many participants, and query that instead.
def get_all_participant_ids():
    participant_ids = set()
    scan_kwargs = {}
    done = False
    start_key = None
    while not done:
        if start_key:
            scan_kwargs['ExclusiveStartKey'] = start_key
        response = table.scan(ProjectionExpression="participant_id", **scan_kwargs)
        for item in response.get('Items', []):
            # --- ADD THIS IF-STATEMENT ---
            if item['participant_id'] != 'SYSTEM_CONFIG':
                participant_ids.add(item['participant_id'])
        start_key = response.get('LastEvaluatedKey', None)
        done = start_key is None
    print(f"Found {len(participant_ids)} unique participants.")
    return list(participant_ids)

def get_latest_submissions_by_participant():
    """
    Scans the table and finds the latest submission_id for all
    participants.
    Returns: A dict of {participant_id: latest_submission_id}
    """
    participant_submissions = {}
    scan_kwargs = {}
    done = False
    start_key = None
    
    # We must project (get) submission_id to find the latest one
    projection = "participant_id, submission_id"

    while not done:
        if start_key:
            scan_kwargs['ExclusiveStartKey'] = start_key
        
        response = table.scan(ProjectionExpression=projection, **scan_kwargs)
        
        for item in response.get('Items', []):
            pid = item.get('participant_id')
            sid = item.get('submission_id')
            
            # Skip non-participant items
            if not pid or pid == 'SYSTEM_CONFIG' or not sid:
                continue

            # Check if this submission is later than one we've already seen
            if pid not in participant_submissions or sid > participant_submissions[pid]:
                participant_submissions[pid] = sid
                
        start_key = response.get('LastEvaluatedKey', None)
        done = start_key is None
        
    print(f"Found {len(participant_submissions)} unique participants.")
    return participant_submissions

def lambda_handler(event, context):
    print("Orchestrator triggered by test data update.")

    # --- NEW: Get the new test file from the S3 event ---
    new_test_data_key = None
    new_test_data_bucket = None
    try:
        record = event.get('Records', [])[0] # Get first trigger
        new_test_data_key = record['s3']['object']['key']
        new_test_data_bucket = record['s3']['bucket']['name']
        if not new_test_data_key.endswith('.csv'):
             print(f"Object is not a .csv file ({new_test_data_key}). Aborting.")
             return {'statusCode': 200, 'body': 'Skipped non-csv file.'}
        print(f"Processing update for new test file: s3://{new_test_data_bucket}/{new_test_data_key}")
    except (IndexError, KeyError) as e:
        print(f"Error parsing S3 event, cannot determine new test file: {e}")
        return {'statusCode': 400, 'body': 'Could not parse S3 event.'}

    # --- NEW: Update the "active" test key in DDB ---
    try:
        config_item = {
            'participant_id': 'SYSTEM_CONFIG', 
            'submission_id': 'ACTIVE_TEST_KEY',
            'active_test_key': new_test_data_key,
            'active_test_bucket': new_test_data_bucket,
            'timestamp': int(time.time())
        }
        table.put_item(Item=config_item)
        print(f"Updated active test key in DDB to: {new_test_data_key}")
    except Exception as e:
        print(f"ERROR: Failed to update active test key in DDB: {e}")
        # Fail fast, as this is a critical step
        return {'statusCode': 500, 'body': f'Failed to update DDB config: {e}'}

    all_latest_submissions = get_latest_submissions_by_participant()
    submissions_to_reevaluate = []

    # --- MODIFIED: Loop over the dict from the helper ---
    for participant_id, latest_submission_id in all_latest_submissions.items():
        if latest_submission_id:
            submissions_to_reevaluate.append({
                'participant_id': participant_id,
                'submission_id': latest_submission_id
            })
            # This log will now appear
            print(f"Queueing re-evaluation for {participant_id} / {latest_submission_id}")
        else:
            print(f"No submissions found for participant {participant_id}")

    # Send messages to SQS
    message_count = 0
    for submission in submissions_to_reevaluate:
        try:
            # --- MODIFIED: Add test file info to SQS message ---
            # (You should already have this, but double-check)
            message_body = {
                'participant_id': submission['participant_id'],
                'submission_id': submission['submission_id'],
                'test_data_key': new_test_data_key, # Get this from your S3 event parsing
                'test_data_bucket': new_test_data_bucket # Get this from your S3 event parsing
            }
            sqs.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps(message_body)
            )
            message_count += 1
        except Exception as e:
            print(f"Error sending SQS message for {submission['participant_id']}: {e}")

    print(f"Successfully queued {message_count} submissions for re-evaluation.")
    return {'statusCode': 200, 'body': f'Queued {message_count} submissions.'}