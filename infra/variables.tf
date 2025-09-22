variable "region" {
  type    = string
  default = "eu-central-1"
}

variable "vpc_cidr" {
  type    = string
  default = "10.42.0.0/16"
}

variable "private_a_cidr" {
  type    = string
  default = "10.42.1.0/24"
}

variable "private_b_cidr" {
  type    = string
  default = "10.42.2.0/24"
}

variable "az_a" {
  type    = string
  default = "eu-central-1a"
}

variable "az_b" {
  type    = string
  default = "eu-central-1b"
}

variable "image_uri" {
  type    = string
  default = "058264123925.dkr.ecr.eu-central-1.amazonaws.com/trading-comp-evaluator:latest"
}

variable "submissions_bucket_name" {
  type    = string
  default = "trading-comp-submission-bucket"
}

variable "testdata_bucket_name" {
  type    = string
  default = "trading-comp-testdata-bucket"
}

variable "aws_cloudwatch_log_group" {
  type    = string
  default = "trading-comp-evaluator"
}