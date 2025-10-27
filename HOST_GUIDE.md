# Trading Competition — Host Guide

This guide details the setup and operation of the competition infrastructure. This architecture uses an **S3-triggered AWS Lambda** function for evaluation and **DynamoDB** for leaderboard storage.

## 1. Architecture Overview

1.  **Submission (S3)**: Participants upload their `submission/` folder (containing `submission.py`) to the `submissions_bucket_name` using the `tools/submit.py` script.
2.  **Trigger (S3 Event)**: An S3 `s3:ObjectCreated:*` event, filtered for the `submission.py` suffix, invokes the evaluator Lambda function.
3.  **Evaluate (Lambda)**: The `evaluator_lambda.py` function executes:
    * It downloads the participant's `submission.py`.
    * It downloads the hidden test data CSV from the `testdata_bucket_name`.
    * It imports the participant's `build_trader(universe)` factory function.
    * It runs an event-driven backtest by calling the trader's `on_quote(market, portfolio)` method for each data batch.
    * It calculates the final **annualized Sharpe ratio**, which serves as the primary `score`.
4.  **Record (DynamoDB)**: The Lambda writes the results (participant_id, submission_id, score, pnl, etc.) to the `trading_competition_scores` DynamoDB table.
5.  **Leaderboard (DynamoDB GSI)**: The table's Global Secondary Index (`LeaderboardIndex`) provides an efficient, real-time leaderboard by sorting all participants by `score`.

## 2. Prerequisites

* **AWS Account** with permissions to create S3, Lambda, IAM, and DynamoDB.
* **Terraform** (>= 1.2).
* **AWS CLI v2**.
* **Python 3.10+** (for local scripts).
* **Docker** (optional, to use the bundled helper image that contains all Python dependencies and CLI shortcuts).

## 3. Infrastructure Setup (Terraform)

1.  **Configure Variables**: Create a `terraform.tfvars` file in the `infra/` directory. You *must* set the bucket names.

    ```hcl
    # Example terraform.tfvars
    region                  = "eu-central-1"
    submissions_bucket_name = "your-comp-submissions-unique"
    testdata_bucket_name    = "your-comp-testdata-unique"
    
    # This ID is used for the DDB GSI to separate leaderboards
    competition_id          = "quant-comp-2025" 
    
    # Path to the test data you will upload
    testdata_key            = "hidden/"

    ```

2.  **Deploy Infrastructure**: Run Terraform from the `infra/` directory.

    ```bash
    cd infra
    terraform init
    terraform plan -out=tfplan
    terraform apply tfplan
    ```
    This creates the S3 buckets (with public access blocked), the DynamoDB table (with the GSI), and the evaluator Lambda function.

## 4. Post-Deployment Setup

### 4.1 Create Lambda Deployment Package (CRITICAL)

The evaluator Lambda requires **`numpy`** and **`pandas`** to calculate the Sharpe ratio, but these are not included in the default Lambda runtime. You must create a Lambda Layer or a deployment package that includes them.

**Example (using a Lambda Layer):**

1.  Create a local directory, install packages, and zip them.
    ```bash
    mkdir -p python/lib/python3.11/site-packages
    pip install numpy pandas -t ./python/lib/python3.11/site-packages
    zip -r pandas_numpy_layer.zip python
    ```
2.  Publish the Lambda Layer via the AWS CLI:
    ```bash
    aws lambda publish-layer-version --layer-name pandas-numpy-layer --description "Pandas and Numpy dependencies" --zip-file fileb://pandas_numpy_layer.zip --compatible-runtimes python3.11
    ```
3.  Note the `LayerVersionArn` from the output. Go to the AWS Lambda console, find your `trading-comp-evaluator-lambda` function, and **manually add this layer** to it.

### 4.2 Upload Test Data

You must upload your hidden test data to the S3 bucket and key specified in your `terraform.tfvars`.

```bash
aws s3 cp data/comp_data.csv s3://comp-submission-bucket/hidden/comp_data.csv
```

### 4.3 Create Participant IAM Policies

Each participant needs an IAM User (or Role) with credentials. Attach a policy that **only** allows them to write to their specific prefix in the submissions bucket.

**Policy Template (replace `<SUBMISSIONS_BUCKET>` and `<PARTICIPANT_ID>`):**

```
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::<SUBMISSIONS_BUCKET>/<PARTICIPANT_ID>/*"
    }
  ]
}
```

Provide each participant with:

1.  Their AWS credentials (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`).
2.  Their unique `PARTICIPANT_ID`.
3.  The `SUBMISSIONS_BUCKET` name.
4.  The AWS `REGION`.

## 5\. Monitoring the Competition

### 5.1 Testing the Pipeline

1.  Configure your *own* `.env` file with credentials for a test participant (e.g., `PARTICIPANT_ID=host-test`).
2.  Create a test `submission/submission.py` (you can use the one from the previous response).
3.  Run the submission script from the project root:
```bash
python tools/submit.py
```
Using the Docker helper image instead:
```bash
docker build -t trading-comp-env .
docker run --rm --env-file .env -v "${PWD}:/usr/src/app" trading-comp-env submit
docker run --rm -v "${PWD}:/usr/src/app" trading-comp-env local-eval
```
4.  Check the logs in **CloudWatch**: Go to Log Groups \> `/aws/lambda/trading-comp-evaluator-lambda` to see the execution output, score, or any errors.

### 5.2 Viewing the Leaderboard

The leaderboard is read directly from the DynamoDB GSI. You can query it using the AWS CLI.

```bash
# Query the GSI to get the top 10 scores
# (Replace 'quant-comp-2025' with your 'competition_id')

aws dynamodb query \
    --table-name trading_competition_scores \
    --index-name LeaderboardIndex \
    --key-condition-expression "competition_id = :cid" \
    --expression-attribute-values '{":cid": {"S": "quant-comp-2025"}}' \
    --no-scan-index-forward \
    --page-size 10
```

  * `--no-scan-index-forward`: Sorts the `score` in descending order (highest first).

## 6\. Clean-Up

When the competition is over, destroy the infrastructure from the `infra/` directory:

```bash
# Note: You must manually empty the S3 buckets first,
# or Terraform will fail.
aws s3 rb s3://comp-submission-bucket --force
aws s3 rb s3://comp-eval-bucket --force

cd infra
terraform destroy

```
