# Trading Competition — Host Guide

This guide details the setup and operation of the competition infrastructure. This architecture uses an **S3-triggered AWS Lambda** function for evaluation, **DynamoDB** for leaderboard storage, and a **new SQS-based orchestration flow** for re-evaluating all submissions when the test data is updated.

## 1\. Architecture Overview

The infrastructure now supports two distinct automated workflows:

### Flow A: New Participant Submission

This is the primary flow for scoring a new submission.

1.  **Submission (S3)**: A participant uploads their `submission/` folder (containing `submission.py`) to the `submissions_bucket_name` using the `tools/submit.py` script.
2.  **Trigger (S3 Event)**: An S3 `s3:ObjectCreated:*` event, filtered for the `submission.py` suffix, invokes the **Evaluator Lambda** (`evaluator_lambda.py`).
3.  **Evaluate (Lambda)**: The **Evaluator Lambda** executes:
      * It reads the *currently active test file path* from the `SYSTEM_CONFIG` item in DynamoDB.
      * It downloads the participant's `submission.py` and the *active* test data CSV.
      * It imports the participant's `build_trader(universe)` factory function.
      * It runs an event-driven backtest.
      * It calculates the final **annualized Sharpe ratio** (`score`).
4.  **Record (DynamoDB)**: The Lambda writes the results to the `trading_competition_scores` DynamoDB table.

-----

### Flow B: Re-evaluation (New Test Data)

This new flow allows the host to re-score *all* participants against a new dataset (e.g., when moving from `train1.csv` to `train2.csv`).

1.  **Host Upload (S3)**: The host uploads a new test data file (e.g., `hidden/train2.csv`) to the `testdata_bucket_name`.
2.  **Trigger (S3 Event)**: An S3 `s3:ObjectCreated:*` event (filtered for `.csv` files) invokes the new **Orchestrator Lambda** (`orchestrator_lambda.py`).
3.  **Orchestrate (Lambda)**: The **Orchestrator Lambda** executes:
      * **Updates Config**: It writes to DynamoDB, updating the `SYSTEM_CONFIG` item to set this *new* file as the `active_test_key`.
      * **Scans Table**: It scans the DynamoDB table to find the latest submission for *every unique participant*.
      * **Queues Jobs**: It sends one message for each participant to an **SQS Queue**. This message contains the `participant_id`, their latest `submission_id`, and the new `test_data_key`.
4.  **Trigger (SQS Event)**: The **SQS Queue** is configured as a trigger for the **Evaluator Lambda**. As messages arrive, AWS Lambda automatically invokes the Evaluator Lambda, passing it the SQS message.
5.  **Evaluate (Lambda)**: The **Evaluator Lambda**'s handler detects it was triggered by SQS. It parses the job details from the message and runs the backtest for that specific participant using the new test data.
6.  **Record (DynamoDB)**: The Lambda writes a *new* evaluation record to the DynamoDB table, creating a separate score entry for the new test set.

## 2\. Prerequisites

  * **AWS Account** with permissions to create S3, Lambda, IAM, DynamoDB, and SQS.
  * **Terraform** (\>= 1.2).
  * **AWS CLI v2**.
  * **Python 3.10+** (for local scripts).
  * **Docker** (optional, to use the bundled helper image).

## 3\. Infrastructure Setup (Terraform)

1.  **Configure Variables**: Create a `terraform.tfvars` file in the `infra/` directory. You *must* set the bucket names and the path to your *initial* test data.

    ```hcl
    # Example terraform.tfvars
    region                  = "eu-central-1"
    submissions_bucket_name = "your-comp-submissions-unique"
    testdata_bucket_name    = "your-comp-testdata-unique"

    # This ID is used for the DDB GSI to separate leaderboards
    competition_id          = "quant-comp-2025" 

    # Path (key) to the test data you will upload
    # This is also used as the *default* key for the evaluator
    testdata_key            = "hidden/train1.csv"

    ```

2.  **Deploy Infrastructure**: Run Terraform from the `infra/` directory.

    ```bash
    cd infra
    terraform init
    terraform plan -out=tfplan
    terraform apply tfplan
    ```

    This creates:

      * The S3 buckets (submissions and test data).
      * The DynamoDB table (with the GSI).
      * The **Evaluator Lambda** function.
      * The **Orchestrator Lambda** function.
      * The **SQS Queue** that connects the Orchestrator to the Evaluator.
      * All necessary IAM Roles and triggers.

## 4\. Post-Deployment Setup

### 4.1 Create Lambda Deployment Package (CRITICAL)

The evaluator Lambda requires **`numpy`** and **`pandas`**. You *must* create a Lambda Layer that includes them.

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

### 4.2 Upload Initial Test Data

You must upload your *initial* hidden test data to the S3 bucket and key specified in your `terraform.tfvars` (`testdata_key`).

```bash
# Example:
aws s3 cp data/comp_data.csv s3://your-comp-testdata-unique/hidden/train1.csv
```

**Important:** Uploading this *first* file will trigger the **Orchestrator Lambda** (Flow B). It will update the `SYSTEM_CONFIG` in DynamoDB and then scan for participants. Since there are no participants yet, it will simply queue 0 jobs and finish. This is normal and confirms the setup is working.

### 4.3 Participant Management

To create credentials (`.env` file contents) for a new participant, use the provided PowerShell script. This script automates the creation of an IAM user, a restrictive S3-only policy, and an access key.

1.  **Configure Script**: Edit `add_particpant.ps1` and set the `$SubmissionsBucket` and `$AwsRegion` variables at the top of the file.
2.  **Run Script**: Execute the script from a PowerShell terminal where your AWS CLI is configured with host (admin) permissions.
    ```powershell
    ./add_particpant.ps1
    ```
3.  **Distribute Credentials**: The script will output the complete contents for a participant's `.env` file. Securely send this text to the new participant.

## 5\. Monitoring the Competition

### 5.1 Testing the Pipelines

You should test *both* workflows.

**1. Test Flow A (New Submission):**

  * Configure your *own* `.env` file with credentials for a test participant (generated from step 4.3).
  * Run the submission script: `python tools/submit.py`.
  * Check the logs in **CloudWatch** for `/aws/lambda/trading-comp-evaluator-lambda`. You should see it triggered by S3 and running the backtest.

**2. Test Flow B (Re-evaluation):**

  * After at least one participant is in DynamoDB, upload a *new* test file (e.g., `data/comp_data_2.csv`) to your `testdata_bucket`.
    ```bash
    aws s3 cp data/comp_data_2.csv s3://your-comp-testdata-unique/hidden/train2.csv
    ```
  * **Check CloudWatch** for `/aws/lambda/trading-comp-orchestrator-lambda`. You should see logs that it was triggered, updated the DDB config, found 1 (or more) participants, and queued them for re-evaluation.
  * **Check CloudWatch** again for `/aws/lambda/trading-comp-evaluator-lambda`. You should see *new* logs appear shortly after. The log message should indicate it was triggered by SQS (`Triggered by SS re-evaluation event.`).

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
aws s3 rb s3://your-comp-submissions-unique --force
aws s3 rb s3://your-comp-testdata-unique --force

cd infra
terraform destroy
```