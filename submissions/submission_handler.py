import json
import os
import uuid
import boto3
import base64

# Initialize AWS clients
s3_client = boto3.client('s3')
sqs_client = boto3.client('sqs')

# Get environment variables
# These must be configured in your Lambda function settings
SUBMISSIONS_BUCKET = os.environ.get('SUBMISSIONS_BUCKET')
SQS_QUEUE_URL = os.environ.get('SQS_QUEUE_URL')

def lambda_handler(event, context):
    """
    Handles incoming submissions via API Gateway.
    Validates the request, uploads the submission to S3, and sends a message to SQS.
    """
    print(f"Received event: {event}")

    # --- 1. Authentication and Request Validation ---
    try:
        # API Gateway automatically provides the participant ID associated with the API key
        # This needs to be configured in the API Gateway Authorizer or Usage Plan.
        # For this example, we'll assume it's passed in the request context.
        participant_id = event['requestContext']['authorizer']['principalId']
        print(f"Authenticated participant: {participant_id}")
        
        # The submission file content is in the event body
        # API Gateway may base64-encode the body
        if event.get('isBase64Encoded', False):
            submission_body = base64.b64decode(event['body']).decode('utf-8')
        else:
            submission_body = event['body']

        if not submission_body:
            raise ValueError("Submission body is empty.")

    except (KeyError, TypeError, ValueError) as e:
        print(f"Error validating request: {e}")
        return {
            'statusCode': 400,
            'body': json.dumps({'message': f'Bad Request: Invalid request format or missing data. {e}'})
        }

    # --- 2. Upload Submission to S3 ---
    # Generate a unique key for the S3 object to prevent overwrites
    submission_id = str(uuid.uuid4())
    s3_key = f"{participant_id}/{submission_id}.csv"

    try:
        s3_client.put_object(
            Bucket=SUBMISSIONS_BUCKET,
            Key=s3_key,
            Body=submission_body
        )
        print(f"Successfully uploaded submission to s3://{SUBMISSIONS_BUCKET}/{s3_key}")
    except Exception as e:
        print(f"Error uploading to S3: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'message': 'Internal Server Error: Could not save submission.'})
        }

    # --- 3. Send Message to SQS for Evaluation ---
    message_body = {
        'participantId': participant_id,
        's3Bucket': SUBMISSIONS_BUCKET,
        's3Key': s3_key
    }

    try:
        sqs_client.send_message(
            QueueUrl=SQS_QUEUE_URL,
            MessageBody=json.dumps(message_body)
        )
        print(f"Successfully sent message to SQS: {message_body}")
    except Exception as e:
        print(f"Error sending message to SQS: {e}")
        # Note: In a real-world scenario, you might want to implement a retry mechanism
        # or cleanup the S3 object if the SQS message fails.
        return {
            'statusCode': 500,
            'body': json.dumps({'message': 'Internal Server Error: Could not queue submission for evaluation.'})
        }

    # --- 4. Return Success Response ---
    return {
        'statusCode': 200,
        'body': json.dumps({
            'message': 'Submission received successfully and is queued for evaluation.',
            'submissionId': submission_id
        })
    }
