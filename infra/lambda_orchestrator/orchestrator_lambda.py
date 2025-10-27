import os
import boto3
import json
from boto3.dynamodb.conditions import Key

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
            participant_ids.add(item['participant_id'])
        start_key = response.get('LastEvaluatedKey', None)
        done = start_key is None
    print(f"Found {len(participant_ids)} unique participants.")
    return list(participant_ids)

# --- Helper to get the latest submission ID for a participant ---
def get_latest_submission_id(participant_id):
    response = table.query(
        KeyConditionExpression=Key('participant_id').eq(participant_id),
        ScanIndexForward=False,  # Sort by submission_id descending (latest first)
        Limit=1,
        ProjectionExpression="submission_id"
    )
    items = response.get('Items', [])
    if items:
        return items[0]['submission_id']
    else:
        return None

def lambda_handler(event, context):
    print("Orchestrator triggered by test data update.")

    # Optional: You could check event records to ensure it's the specific file
    # for record in event.get('Records', []):
    #     s3_key = record['s3']['object']['key']
    #     print(f"Processing update for S3 key: {s3_key}")

    all_participants = get_all_participant_ids()
    submissions_to_reevaluate = []

    for participant_id in all_participants:
        latest_submission_id = get_latest_submission_id(participant_id)
        if latest_submission_id:
            submissions_to_reevaluate.append({
                'participant_id': participant_id,
                'submission_id': latest_submission_id
            })
            print(f"Queueing re-evaluation for {participant_id} / {latest_submission_id}")
        else:
            print(f"No submissions found for participant {participant_id}")

    # Send messages to SQS
    message_count = 0
    for submission in submissions_to_reevaluate:
        try:
            sqs.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps(submission)
            )
            message_count += 1
        except Exception as e:
            print(f"Error sending SQS message for {submission['participant_id']}: {e}")

    print(f"Successfully queued {message_count} submissions for re-evaluation.")
    return {'statusCode': 200, 'body': f'Queued {message_count} submissions.'}