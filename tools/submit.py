
#!/usr/bin/env python3

"""
Submit your strategy folder to the competition S3 bucket.

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

import os, sys, time
from pathlib import Path

import boto3
from dotenv import load_dotenv
from botocore.exceptions import BotoCoreError, NoCredentialsError, ClientError
load_dotenv()
REQUIRED_ENVS = ["AWS_REGION", "SUBMISSIONS_BUCKET", "PARTICIPANT_ID"]

def die(msg, code=2):
    print(f"[submit] ERROR: {msg}", file=sys.stderr)
    sys.exit(code)

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

    print("\n[submit] Done. Your evaluation will start shortly.")
    print(f"[submit] Track progress in CloudWatch Logs or check the leaderboard in a minute.")
    print(f"[submit] Submission prefix: s3://{bucket}/{prefix}")

if __name__ == "__main__":
    main()
