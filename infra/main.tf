# ---------- VARIABLES ----------
variable "region" {
  type    = string
  default = "eu-central-1"
}
variable "submissions_bucket_name" {
  type        = string
  description = "e.g. \"trading-comp-submission-bucket\""
  default     = "comp-submission-bucket"
}
variable "testdata_bucket_name" {
  type        = string
  description = "e.g. \"trading-comp-test-bucket\""
  default     = "comp-eval-bucket"
}
variable "testdata_key" {
  type    = string
  default = "hidden/comp_data.csv"
}
variable "lambda_timeout" {
  type = number
  default = 900
}
variable "lambda_memory_mb" {
  type    = number
  default = 1024
}
variable "create_buckets" {
  type        = bool
  default     = true
  description = "set true to let TF create the buckets"
}
variable "lambda_source_dir" {
  type        = string
  default     = null
  description = "Optional override for the evaluator Lambda source folder"
}
variable "table_name" {
  type    = string
  default = "trading_competition_scores"
}

variable "competition_id" {
  type        = string
  default     = "quant-comp-2025"
  description = "The identifier for the DynamoDB GSI Hash Key."
}

variable "orchestrator_lambda_source_dir" {
  type        = string
  description = "Source directory for the re-evaluation orchestrator Lambda"
}


# ---------- OPTIONAL: CREATE BUCKETS OR REUSE EXISTING ----------
resource "aws_s3_bucket" "submissions" {
  count         = var.create_buckets ? 1 : 0
  bucket        = var.submissions_bucket_name
  force_destroy = false
}

resource "aws_s3_bucket_public_access_block" "submissions_block" {
  count  = var.create_buckets ? 1 : 0
  bucket = aws_s3_bucket.submissions[0].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket" "testdata" {
  count         = var.create_buckets ? 1 : 0
  bucket        = var.testdata_bucket_name
  force_destroy = false
}

resource "aws_s3_bucket_public_access_block" "testdata_block" {
  count  = var.create_buckets ? 1 : 0
  bucket = aws_s3_bucket.testdata[0].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

data "aws_s3_bucket" "submissions" {
  count  = var.create_buckets ? 0 : 1
  bucket = var.submissions_bucket_name
}

data "aws_s3_bucket" "testdata" {
  count  = var.create_buckets ? 0 : 1
  bucket = var.testdata_bucket_name
}

locals {
  submissions_bucket_arn = var.create_buckets ? aws_s3_bucket.submissions[0].arn : data.aws_s3_bucket.submissions[0].arn
  submissions_bucket_id  = var.create_buckets ? aws_s3_bucket.submissions[0].id : data.aws_s3_bucket.submissions[0].id
  testdata_bucket_arn    = var.create_buckets ? aws_s3_bucket.testdata[0].arn : data.aws_s3_bucket.testdata[0].arn
  testdata_bucket_id     = var.create_buckets ? aws_s3_bucket.testdata[0].id : data.aws_s3_bucket.testdata[0].id
  lambda_source_dir      = coalesce(var.lambda_source_dir, "${path.module}/lambda")
}

# ---------- DYNAMODB TABLE ----------
resource "aws_dynamodb_table" "scores" {
  name         = var.table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "participant_id"
  range_key    = "submission_id"

  attribute {
    name = "participant_id"
    type = "S"
  }
  attribute {
    name = "submission_id"
    type = "S"
  }
  # CHANGED: Added attributes for the new GSI
  attribute {
    name = "competition_id"
    type = "S"
  }
  attribute {
    name = "score"
    type = "N"
  }

  global_secondary_index {
    name            = "LeaderboardIndex"
    hash_key        = "competition_id"
    range_key       = "score"
    write_capacity  = 0 
    read_capacity   = 0 
    projection_type = "ALL"
  }
}

# ---------- PACKAGE LAMBDA FROM LOCAL SOURCE ----------
# Expect file at: ${local.lambda_source_dir}/evaluator_lambda.py
data "archive_file" "evaluator_zip" {
  type        = "zip"
  output_path = "${path.module}/evaluator_lambda.zip"
  source {
    filename = "evaluator_lambda.py"
    content  = file("${local.lambda_source_dir}/evaluator_lambda.py")
  }
}

# ---------- IAM ROLE FOR LAMBDA ----------
data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda_role" {
  name               = "trading-comp-evaluator-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

# Inline policy: CloudWatch Logs, S3 GetObject (testdata + submissions), DynamoDB PutItem
data "aws_iam_policy_document" "lambda_policy" {
  statement {
    sid       = "Logs"
    effect    = "Allow"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:${var.region}:${data.aws_caller_identity.current.account_id}:*"]
  }

  statement {
    sid       = "S3ReadTestData"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = [
      "${local.testdata_bucket_arn}/${var.testdata_key}"
    ]
  }

  statement {
    sid       = "S3ReadSubmissionsObjects"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${local.submissions_bucket_arn}/*"]
  }

  statement {
    sid     = "DDBWriteScores"
    effect  = "Allow"
    actions = ["dynamodb:PutItem"]
    resources = [
      aws_dynamodb_table.scores.arn,
      # CHANGED: Added permission to write to the GSI
      "${aws_dynamodb_table.scores.arn}/index/LeaderboardIndex"
    ]
  }

  statement {
    sid    = "SQSReadReevaluation"
    effect = "Allow"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes"
    ]
    resources = [aws_sqs_queue.reevaluation_queue.arn]
  }
}

resource "aws_iam_role_policy" "lambda_inline" {
  name   = "trading-comp-evaluator-lambda-policy"
  role   = aws_iam_role.lambda_role.id
  policy = data.aws_iam_policy_document.lambda_policy.json
}

data "aws_caller_identity" "current" {}

# ---------- LAMBDA FUNCTION ----------
resource "aws_lambda_function" "evaluator" {
  function_name    = "trading-comp-evaluator-lambda"
  role             = aws_iam_role.lambda_role.arn
  handler          = "evaluator_lambda.lambda_handler"
  runtime          = "python3.11"
  filename         = data.archive_file.evaluator_zip.output_path
  timeout          = var.lambda_timeout
  memory_size      = var.lambda_memory_mb
  source_code_hash = data.archive_file.evaluator_zip.output_base64sha256

  environment {
    variables = {
      SUBMISSIONS_BUCKET = local.submissions_bucket_id
      TESTDATA_BUCKET    = local.testdata_bucket_id
      TESTDATA_KEY       = var.testdata_key
      DDB_TABLE          = aws_dynamodb_table.scores.name
      COMPETITION_ID     = var.competition_id
    }
  }
}

# ---------- ALLOW S3 TO INVOKE LAMBDA ----------
resource "aws_lambda_permission" "allow_s3_invoke" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.evaluator.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = local.submissions_bucket_arn
}

# ---------- S3 EVENT NOTIFICATION (ObjectCreated + suffix: submission.py) ----------
resource "aws_s3_bucket_notification" "submissions_notify" {
  bucket = local.submissions_bucket_id

  lambda_function {
    lambda_function_arn = aws_lambda_function.evaluator.arn
    events              = ["s3:ObjectCreated:*"]
    filter_suffix       = "submission.py"
  }

  depends_on = [aws_lambda_permission.allow_s3_invoke]
}

# --- Add SQS Queue Resource ---
resource "aws_sqs_queue" "reevaluation_queue" {
  name                      = "trading-comp-reevaluation-queue"
  delay_seconds             = 0
  max_message_size          = 262144 # 256 KiB
  message_retention_seconds = 86400  # 1 day
  receive_wait_time_seconds = 10
  visibility_timeout_seconds = var.lambda_timeout
}

# --- Add IAM Role & Policy for Orchestrator Lambda ---
data "aws_iam_policy_document" "orchestrator_lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "orchestrator_lambda_role" {
  name               = "trading-comp-orchestrator-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.orchestrator_lambda_assume.json
}

data "aws_iam_policy_document" "orchestrator_lambda_policy" {
  # Basic Lambda execution permissions (CloudWatch Logs)
  statement {
    sid       = "Logs"
    effect    = "Allow"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:${var.region}:${data.aws_caller_identity.current.account_id}:*"]
  }
  # Permission to query DynamoDB table and GSI
  statement {
    sid    = "DDBReadScores"
    effect = "Allow"
    actions = [
      "dynamodb:Query",
      "dynamodb:Scan" # Scan might be needed to get all participant IDs initially
    ]
    resources = [
      aws_dynamodb_table.scores.arn,
      "${aws_dynamodb_table.scores.arn}/index/*" # Access to GSIs
    ]
  }
  # Permission to send messages to the SQS queue
  statement {
    sid       = "SQSSendMessage"
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.reevaluation_queue.arn]
  }
}

resource "aws_iam_role_policy" "orchestrator_lambda_inline" {
  name   = "trading-comp-orchestrator-lambda-policy"
  role   = aws_iam_role.orchestrator_lambda_role.id
  policy = data.aws_iam_policy_document.orchestrator_lambda_policy.json
}

# --- Package and Create Orchestrator Lambda Function ---
data "archive_file" "orchestrator_lambda_zip" {
  type        = "zip"
  output_path = "${path.module}/orchestrator_lambda.zip"
  source_dir  = coalesce(var.orchestrator_lambda_source_dir, "${path.module}/lambda_orchestrator")
}

resource "aws_lambda_function" "orchestrator" {
  function_name    = "trading-comp-orchestrator-lambda"
  role             = aws_iam_role.orchestrator_lambda_role.arn
  handler          = "orchestrator_lambda.lambda_handler" # Assumes filename is orchestrator_lambda.py
  runtime          = "python3.11"
  filename         = data.archive_file.orchestrator_lambda_zip.output_path
  timeout          = 300 # 5 minutes should be enough to query DDB and send SQS messages
  memory_size      = 256 # Usually doesn't need much memory
  source_code_hash = data.archive_file.orchestrator_lambda_zip.output_base64sha256

  environment {
    variables = {
      DDB_TABLE_NAME = aws_dynamodb_table.scores.name
      SQS_QUEUE_URL  = aws_sqs_queue.reevaluation_queue.id # Use .id for Queue URL
    }
  }
}

# --- Add S3 Trigger for Test Data Bucket to Orchestrator ---
resource "aws_lambda_permission" "allow_testdata_s3_invoke_orchestrator" {
  statement_id  = "AllowTestDataS3InvokeOrchestrator"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.orchestrator.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = local.testdata_bucket_arn
  # Add source_account if buckets are in different accounts
}

resource "aws_s3_bucket_notification" "testdata_notify_orchestrator" {
  bucket = local.testdata_bucket_id

  lambda_function {
    lambda_function_arn = aws_lambda_function.orchestrator.arn
    events              = ["s3:ObjectCreated:*"]
    # Filter specifically for your test data file
    filter_prefix = split("/", var.testdata_key)[0] # e.g., "hidden"
    filter_suffix = split("/", var.testdata_key)[1] # e.g., "test_data.csv"
  }

  depends_on = [aws_lambda_permission.allow_testdata_s3_invoke_orchestrator]
}

# 1. Add SQS Trigger
resource "aws_lambda_event_source_mapping" "evaluator_sqs_trigger" {
  event_source_arn = aws_sqs_queue.reevaluation_queue.arn
  function_name    = aws_lambda_function.evaluator.arn
  batch_size       = 1 # Process one submission re-evaluation at a time
  enabled          = true
}


# ---------- OUTPUTS ----------
output "lambda_name" { value = aws_lambda_function.evaluator.function_name }
output "scores_table" { value = aws_dynamodb_table.scores.name }
output "submissions_arn" { value = local.submissions_bucket_arn }
output "testdata_key" { value = var.testdata_key }