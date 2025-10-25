# ---------- VARIABLES ----------
variable "region" { 
  type = string  
  default = "eu-central-1" 
}
variable "submissions_bucket_name" {
  type        = string
  description = "e.g. \"trading-comp-submission-bucket\""
}
variable "testdata_bucket_name" {
  type        = string
  description = "e.g. \"trading-comp-test-bucket\""
}
variable "testdata_key" {
  type    = string
  default = "hidden/forex_test.csv"
}
variable "universe_csv" {
  type    = string
  default = "EURUSD,GBPUSD,USDJPY"
}
variable "lambda_timeout" {
  type    = number
  default = 60
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
# ---------- OPTIONAL: CREATE BUCKETS OR REUSE EXISTING ----------
resource "aws_s3_bucket" "submissions" {
  count        = var.create_buckets ? 1 : 0
  bucket       = var.submissions_bucket_name
  force_destroy = false
}

resource "aws_s3_bucket" "testdata" {
  count        = var.create_buckets ? 1 : 0
  bucket       = var.testdata_bucket_name
  force_destroy = false
}

data "aws_s3_bucket" "submissions" {
  count = var.create_buckets ? 0 : 1
  bucket = var.submissions_bucket_name
}

data "aws_s3_bucket" "testdata" {
  count = var.create_buckets ? 0 : 1
  bucket = var.testdata_bucket_name
}

locals {
  submissions_bucket_arn = var.create_buckets ? aws_s3_bucket.submissions[0].arn : data.aws_s3_bucket.submissions[0].arn
  submissions_bucket_id  = var.create_buckets ? aws_s3_bucket.submissions[0].id  : data.aws_s3_bucket.submissions[0].id
  testdata_bucket_arn    = var.create_buckets ? aws_s3_bucket.testdata[0].arn    : data.aws_s3_bucket.testdata[0].arn
  testdata_bucket_id     = var.create_buckets ? aws_s3_bucket.testdata[0].id     : data.aws_s3_bucket.testdata[0].id
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
    sid     = "Logs"
    effect  = "Allow"
    actions = ["logs:CreateLogGroup","logs:CreateLogStream","logs:PutLogEvents"]
    resources = ["arn:aws:logs:${var.region}:${data.aws_caller_identity.current.account_id}:*"]
  }

  statement {
    sid     = "S3ReadTestData"
    effect  = "Allow"
    actions = ["s3:GetObject"]
    resources = [
      "${local.testdata_bucket_arn}/${var.testdata_key}"
    ]
  }

  statement {
    sid     = "S3ReadSubmissionsObjects"
    effect  = "Allow"
    actions = ["s3:GetObject"]
    resources = ["${local.submissions_bucket_arn}/*"]
  }

  statement {
    sid     = "DDBWriteScores"
    effect  = "Allow"
    actions = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.scores.arn]
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
  function_name = "trading-comp-evaluator-lambda"
  role          = aws_iam_role.lambda_role.arn
  handler       = "evaluator_lambda.lambda_handler"
  runtime       = "python3.11"
  filename      = data.archive_file.evaluator_zip.output_path
  timeout       = var.lambda_timeout
  memory_size   = var.lambda_memory_mb
  source_code_hash = data.archive_file.evaluator_zip.output_base64sha256

  environment {
    variables = {
      SUBMISSIONS_BUCKET = local.submissions_bucket_id
      TESTDATA_BUCKET    = local.testdata_bucket_id
      TESTDATA_KEY       = var.testdata_key
      DDB_TABLE          = aws_dynamodb_table.scores.name
      UNIVERSE           = var.universe_csv
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

# ---------- OUTPUTS ----------
output "lambda_name"     { value = aws_lambda_function.evaluator.function_name }
output "scores_table"    { value = aws_dynamodb_table.scores.name }
output "submissions_arn" { value = local.submissions_bucket_arn }
output "testdata_key"    { value = var.testdata_key }
