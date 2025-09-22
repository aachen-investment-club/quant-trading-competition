# Trading Competition — Host/Operator Guide

This guide shows how to **set up the evaluator end‑to‑end**, **run Terraform**, **push the evaluator image**, **upload test data**, **test the pipeline**, and **find logs**.

> Assumes the repository structure provided by the project (Dockerfile, `infra/`, `src/`, `submission/`, `tools/`), and a no‑NAT Fargate design with VPC endpoints.

---

## 1) Architecture overview

- **Submissions (S3)** — Participants upload `submission/` via `tools/submit.py` to `s3://<SUBMISSIONS_BUCKET>/<PARTICIPANT_ID>/<SUBMISSION_ID>/...` (`submission.py` uploaded last as the trigger).
- **S3 → Orchestrator Lambda** — S3 event filter `suffix = "submission.py"`. Lambda extracts `participant_id` / `submission_id` and **`RunTask`** on ECS.
- **ECS Fargate (private)** — Uses a pre‑built **evaluator image** from **ECR**. No public IP, no NAT. Access to AWS APIs is via **VPC Endpoints**:
  - Gateway: **S3**, **DynamoDB**
  - Interface: **ECR (api & dkr)**, **CloudWatch Logs**, **STS**
- **Evaluator Entrypoint** — `python infra/entrypoint_eval.py` in the container:
  1) download test CSV (`TESTDATA_BUCKET` + `TESTDATA_KEY`),
  2) download submission prefix,
  3) `build_strategy()` → `generate_signals(df)`,
  4) compute metrics/score,
  5) `PutItem` to **DynamoDB `trading_competition_scores`**.
- **Leaderboard API** — Lambda + API Gateway HTTP API (`GET /leaderboard`) reads from DynamoDB and returns JSON for your UI.

---

## 2) Prerequisites

- **AWS account** with permissions to create: VPC, subnets, route tables, VPC endpoints, ECS, IAM roles/policies, Lambda, API Gateway, S3, DynamoDB, CloudWatch.
- **Terraform** (>= 1.5), **AWS CLI v2**, **Docker** and **git** on your workstation.
- If you **cannot** create CloudWatch Log Groups via Terraform, you must create them **manually** (see §6).

---

## 3) Build & push the evaluator image (ECR)

1. Create (or choose) an **ECR repository**, note its URI (e.g. `123456789012.dkr.ecr.eu-central-1.amazonaws.com/trading-comp-evaluator:latest`).  
2. Authenticate Docker to ECR:
   ```bash
   aws ecr get-login-password --region <REGION>      | docker login --username AWS --password-stdin <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com
   ```
3. From the repo root, build and push:
   ```bash
   docker build -t trading-comp-evaluator:latest .
   docker tag trading-comp-evaluator:latest <ECR_URI>
   docker push <ECR_URI>
   ```
4. Use this image URI for `var.image_uri` in Terraform.

> **Important**: The Docker build context must include `infra/entrypoint_eval.py`. Ensure your `.dockerignore` **does not** exclude `infra/`.

---

## 4) Configure Terraform

Review/adjust `infra/variables.tf`. Prepare a `terraform.tfvars` (example):

```hcl
region                  = "eu-central-1"
vpc_cidr                = "10.20.0.0/16"
private_a_cidr          = "10.20.1.0/24"
private_b_cidr          = "10.20.2.0/24"
az_a                    = "eu-central-1a"
az_b                    = "eu-central-1b"

submissions_bucket_name = "trading-comp-submissions-<uniq>"
testdata_bucket_name    = "trading-comp-testdata-<uniq>"

image_uri               = "123456789012.dkr.ecr.eu-central-1.amazonaws.com/trading-comp-evaluator:latest"
aws_cloudwatch_log_group = "trading-comp-evaluator"  # must exist if you can't create via TF
```

Initialize and apply:
```bash
cd infra
terraform init
terraform plan -out=tfplan
terraform apply tfplan
```

Terraform creates:
- VPC + **two private subnets**, private route table
- Security Groups (ECS tasks egress only; VPC endpoint SG allows 443 from tasks SG)
- **VPC endpoints**: S3 (Gateway), DynamoDB (Gateway), ECR api/dkr (Interface), CloudWatch Logs (Interface), STS (Interface)
- **S3** buckets: submissions (force_destroy=true), testdata (force_destroy=false)
- **DynamoDB**: `trading_competition_scores` (PAY_PER_REQUEST, PK=`participant_id`, SK=`submission_id`)
- **ECS cluster** + **TaskDefinition** with awslogs (group name from `var.aws_cloudwatch_log_group`)
- **Lambdas**: Orchestrator (S3→ECS) and Leaderboard API
- **API Gateway HTTP API** with route `GET /leaderboard`
- S3 **notification** on the submissions bucket, filtered to `suffix="submission.py"`

---

## 5) One‑time AWS setup outside Terraform

### 5.1 CloudWatch Log Group (if TF cannot create it)
If you lack permission to create log groups via Terraform:
```bash
aws logs create-log-group --log-group-name "trading-comp-evaluator" --region <REGION>
aws logs put-retention-policy --log-group-name "trading-comp-evaluator" --retention-in-days 14 --region <REGION>
```
Ensure the **name exactly** matches `var.aws_cloudwatch_log_group`.

> The **awslogs** driver can create **log streams**, but **not** the **log group**. Without the group, you won’t see ECS task logs.

### 5.2 Upload the test dataset
Upload the official CSV to the testdata bucket and key that the Lambda passes to the task (matches your Terraform env vars), e.g.:
```bash
aws s3 cp data/historical_data_EURUSD_15_2022-01-01_2023-01-01.csv   s3://<TESTDATA_BUCKET>/hidden/historical_data_EURUSD_15_2022-01-01_2023-01-01.csv
```
This must match `TESTDATA_KEY` in the Lambda’s environment (as wired by Terraform).

### 5.3 Participant permissions
Give each participant `s3:PutObject` on their own prefix in the submissions bucket, e.g. a policy on their IAM user/role:
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["s3:PutObject"],
    "Resource": "arn:aws:s3:::<SUBMISSIONS_BUCKET>/<PARTICIPANT_ID>/*"
  }]
}
```

---

## 6) Testing the pipeline

### 6.1 Local smoke test of the evaluator image
Run the image and check the entrypoint is present:
```bash
docker run --rm -it <ECR_URI> sh -lc "python -V && ls -l infra/entrypoint_eval.py"
```
If the file is missing, re‑build from the **repository root** (so `COPY . .` includes `infra/`).

### 6.2 End‑to‑end test using the submit tool
1. Provide a **test participant** with credentials allowing `s3:PutObject` to their prefix.
2. On a dev machine, from repo root:
   ```bash
   export AWS_REGION=<REGION>
   export SUBMISSIONS_BUCKET=<YOUR_SUBMISSIONS_BUCKET>
   export PARTICIPANT_ID=tester01
   python tools/submit.py
   ```
3. Verify:
   - **Lambda (orchestrator) logs** in CloudWatch show a `RunTask` call.
   - An **ECS task** runs in your cluster (Fargate).
   - **ECS task logs** appear under the configured log group (e.g. `/ecs/trading-comp-evaluator`).
   - A **DynamoDB item** appears in `trading_competition_scores` with `participant_id=tester01`.
   - **API Gateway** `GET /leaderboard` returns JSON including your test record.

### 6.3 Call the API
Fetch the leaderboard (Terraform outputs the URL as `api_endpoint`):
```bash
curl -s https://https://llu0q677b4.execute-api.eu-central-1.amazonaws.com.execute-api.eu-central-1.amazonaws.com/leaderboard | jq .
```
https://llu0q677b4.execute-api.eu-central-1.amazonaws.com
---

## 7) Logs & monitoring


- **ECS Task logs** — CloudWatch Logs under your **Log Group** (e.g. `/ecs/trading-comp-evaluator`), stream prefix `"ecs"` (from the TaskDefinition).  
- **Orchestrator Lambda** — CloudWatch Logs: `/aws/lambda/trading-comp-orchestrator`.
- **Leaderboard Lambda** — CloudWatch Logs: `/aws/lambda/trading-comp-leaderboard`.
- **ECS events** — Check the ECS Cluster → Tasks for state transitions and failures.

---

## 9) Operational tips

- **Timeouts**: The orchestrator can pass `TIMEOUT_SECONDS` to the task; implement a watchdog in the entrypoint if needed.
- **Costs**: `COST_BPS` can be tuned in the Lambda environment for consistent comparisons.
- **Retention**: Set log retention (e.g., 14 days) to control costs.
- **Housekeeping**: Consider lifecycle rules on the submissions bucket.
- **Updating the evaluator**: Push a new image tag and update `var.image_uri` → `terraform apply` to roll out a new TaskDefinition revision.

---

## 10) Clean‑up

Destroy the environment:
```bash
cd infra
terraform destroy
```
If buckets are non‑empty or you created log groups manually, empty/delete them before destroy (or use `force_destroy=true` where appropriate).
