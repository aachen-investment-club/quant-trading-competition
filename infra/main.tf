############################
# VPC + 2 private subnets  #
############################
resource "aws_vpc" "comp" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags                 = { Name = "comp-vpc" }
}

resource "aws_subnet" "private_a" {
  vpc_id            = aws_vpc.comp.id
  cidr_block        = var.private_a_cidr
  availability_zone = var.az_a
  tags              = { Name = "comp-private-a" }
}

resource "aws_subnet" "private_b" {
  vpc_id            = aws_vpc.comp.id
  cidr_block        = var.private_b_cidr
  availability_zone = var.az_b
  tags              = { Name = "comp-private-b" }
}

# One route table for both private subnets (no default route to the internet)
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.comp.id
  tags   = { Name = "comp-private-rt" }
}

resource "aws_route_table_association" "priv_a" {
  subnet_id      = aws_subnet.private_a.id
  route_table_id = aws_route_table.private.id
}

resource "aws_route_table_association" "priv_b" {
  subnet_id      = aws_subnet.private_b.id
  route_table_id = aws_route_table.private.id
}

############################################
# Security Groups                          #
############################################
# ECS tasks SG: no inbound, allow all egress (egress will land on endpoints)
resource "aws_security_group" "ecs_tasks" {
  name        = "comp-ecs-tasks"
  description = "ECS tasks egress"
  vpc_id      = aws_vpc.comp.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "comp-ecs-tasks" }
}

# VPC Endpoint SG for interface endpoints: allow 443 from ECS tasks SG only
resource "aws_security_group" "vpce" {
  name   = "comp-vpce"
  vpc_id = aws_vpc.comp.id

  ingress {
    description     = "HTTPS from ECS tasks"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_tasks.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "comp-vpce" }
}

############################################
# VPC Endpoints (no-NAT pattern)           #
############################################
# Gateway endpoints (attach to private route table)
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.comp.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]
  tags              = { Name = "vpce-s3" }
}

resource "aws_vpc_endpoint" "dynamodb" {
  vpc_id            = aws_vpc.comp.id
  service_name      = "com.amazonaws.${var.region}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]
  tags              = { Name = "vpce-dynamodb" }
}

# Interface endpoints required for Fargate pulls + logging
# ECR (api and dkr), CloudWatch Logs, and STS (some SDKs call STS)
locals {
  vpce_interface_services = [
    "com.amazonaws.${var.region}.ecr.api",
    "com.amazonaws.${var.region}.ecr.dkr",
    "com.amazonaws.${var.region}.logs",
    "com.amazonaws.${var.region}.sts"
  ]
}

resource "aws_vpc_endpoint" "interfaces" {
  for_each            = toset(local.vpce_interface_services)
  vpc_id              = aws_vpc.comp.id
  service_name        = each.value
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.private_a.id, aws_subnet.private_b.id]
  security_group_ids  = [aws_security_group.vpce.id]
  private_dns_enabled = true
  tags                = { Name = "vpce-${split(".", replace(each.value, "com.amazonaws.${var.region}.", ""))[0]}" }
}

############################################
# Outputs for the backend Terraform        #
############################################
output "vpc_id" { value = aws_vpc.comp.id }
output "private_subnet_ids" { value = [aws_subnet.private_a.id, aws_subnet.private_b.id] }
output "ecs_tasks_sg_id" { value = aws_security_group.ecs_tasks.id }

# Buckets
resource "aws_s3_bucket" "submissions" {
  bucket        = var.submissions_bucket_name
  force_destroy = true
}
resource "aws_s3_bucket" "testdata" {
  bucket        = var.testdata_bucket_name
  force_destroy = false
}

resource "aws_dynamodb_table" "scores" {
  name         = "trading_competition_scores"
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


# ECS Cluster
resource "aws_ecs_cluster" "eval" { name = "trading-comp-eval-cluster" }

# IAM roles
data "aws_iam_policy_document" "task_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "task_role" {
  name               = "trading-comp-task-role"
  assume_role_policy = data.aws_iam_policy_document.task_assume.json
}
resource "aws_iam_role" "task_exec_role" {
  name               = "trading-comp-task-exec-role"
  assume_role_policy = data.aws_iam_policy_document.task_assume.json
}
resource "aws_iam_role_policy" "task_policy" {
  name = "trading-comp-task-policy"
  role = aws_iam_role.task_role.id
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      { Effect = "Allow", Action = ["s3:GetObject", "s3:ListBucket"], Resource = [
        aws_s3_bucket.submissions.arn, "${aws_s3_bucket.submissions.arn}/*",
      aws_s3_bucket.testdata.arn, "${aws_s3_bucket.testdata.arn}/*"] },
      { Effect = "Allow", Action = ["dynamodb:PutItem", "dynamodb:Scan", "dynamodb:Query"], Resource = [aws_dynamodb_table.scores.arn] },
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = ["*"] }
    ]
  })
}
resource "aws_iam_role_policy_attachment" "exec_logs" {
  role       = aws_iam_role.task_exec_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Logs
#

# Task Definition (uses your ECR image)
resource "aws_ecs_task_definition" "evaluator" {
  family                   = "trading-comp-evaluator"
  cpu                      = "1024"
  memory                   = "2048"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  execution_role_arn       = aws_iam_role.task_exec_role.arn
  task_role_arn            = aws_iam_role.task_role.arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }
  ephemeral_storage {
    size_in_gib = 21
  }
  container_definitions = jsonencode([{
    name                   = "evaluator",
    image                  = var.image_uri,
    essential              = true,
    command                = ["python", "infra/entrypoint_eval.py"],
    readonlyRootFilesystem = false, #change to false
    logConfiguration = {
      logDriver = "awslogs",
      options   = { awslogs-group = var.aws_cloudwatch_log_group, awslogs-region = var.region, awslogs-stream-prefix = "ecs" }
    }
  }])
}

#resource "aws_cloudwatch_log_group" "ecs" {
#  name              = var.aws_cloudwatch_log_group
#  retention_in_days = 14
#}

resource "aws_lambda_permission" "api_invoke" {
  statement_id  = "AllowHTTPAPIInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.arn
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}


# Orchestrator Lambda (S3 -> ECS)
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
  name               = "trading-comp-orchestrator-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}
resource "aws_iam_role_policy" "lambda_policy" {
  role = aws_iam_role.lambda_role.id
  name = "trading-comp-orchestrator-policy"
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      { Effect = "Allow", Action = ["ecs:RunTask"], Resource = [aws_ecs_task_definition.evaluator.arn] },
      { Effect = "Allow", Action = ["iam:PassRole"], Resource = [aws_iam_role.task_role.arn, aws_iam_role.task_exec_role.arn] },
      { Effect = "Allow", Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"], Resource = ["*"] }
    ]
  })
}
resource "aws_lambda_function" "orchestrator" {
  function_name = "trading-comp-orchestrator"
  role          = aws_iam_role.lambda_role.arn
  handler       = "app.lambda_handler"
  runtime       = "python3.11"
  filename      = "${path.module}/lambda_orchestrator.zip"
  timeout       = 30
  environment {
    variables = {
      ECS_CLUSTER_ARN    = aws_ecs_cluster.eval.arn
      ECS_TASK_DEF_ARN   = aws_ecs_task_definition.evaluator.arn
      SUBMISSIONS_BUCKET = aws_s3_bucket.submissions.bucket
      TESTDATA_BUCKET    = aws_s3_bucket.testdata.bucket
      TESTDATA_KEY       = "hidden/historical_data_EURUSD_1H_2022-01-01_2023-01-01.csv"
      DDB_TABLE          = aws_dynamodb_table.scores.name
      SUBNETS            = join(",", [aws_subnet.private_a.id, aws_subnet.private_b.id])
      SECURITY_GROUPS    = aws_security_group.ecs_tasks.id
      COST_BPS           = "1.0"
      TIMEOUT_SECONDS    = "600"
    }
  }
}
resource "aws_lambda_permission" "allow_s3" {
  statement_id  = "AllowExecutionFromS3"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.orchestrator.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.submissions.arn
}
resource "aws_s3_bucket_notification" "submissions_notify" {
  bucket = aws_s3_bucket.submissions.id
  lambda_function {
    lambda_function_arn = aws_lambda_function.orchestrator.arn
    events              = ["s3:ObjectCreated:*"]
    filter_suffix       = "submission.py"
  }
  depends_on = [aws_lambda_permission.allow_s3]
}

# Leaderboard API: Lambda + API Gateway HTTP API
resource "aws_lambda_function" "api" {
  function_name = "trading-comp-leaderboard"
  role          = aws_iam_role.lambda_role.arn
  handler       = "app.handler"
  runtime       = "python3.11"
  filename      = "${path.module}/api_lambda.zip"
  timeout       = 15
  environment { variables = { DDB_TABLE = aws_dynamodb_table.scores.name } }
}
resource "aws_iam_role_policy" "lambda_api_ddb" {
  role = aws_iam_role.lambda_role.id
  name = "trading-comp-api-ddb"
  policy = jsonencode({
    Version   = "2012-10-17",
    Statement = [{ Effect = "Allow", Action = ["dynamodb:Scan", "dynamodb:Query"], Resource = [aws_dynamodb_table.scores.arn] }]
  })
}
resource "aws_apigatewayv2_api" "http" {
  name          = "trading-comp-api"
  protocol_type = "HTTP"
}
resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.arn
  payload_format_version = "2.0"
}
resource "aws_apigatewayv2_route" "leaderboard" {
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "GET /leaderboard"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}
resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http.id
  name        = "$default"
  auto_deploy = true
}

output "api_endpoint" { value = aws_apigatewayv2_api.http.api_endpoint }
output "submissions_bucket" { value = aws_s3_bucket.submissions.bucket }
output "testdata_bucket" { value = aws_s3_bucket.testdata.bucket }
output "dynamodb_table" { value = aws_dynamodb_table.scores.name }