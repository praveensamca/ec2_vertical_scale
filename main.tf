provider "aws" {
  region = "ap-south-1"
}

## Building package with dependencies

resource "null_resource" "requests_zip" {
  provisioner "local-exec" {
    command = <<EOT
    zip -r python.zip python
    EOT
  }
}

data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "lambda_function" # Path to your Lambda code folder
  output_path = "lambda_function.zip"
}


## Uploading lambda layer
resource "aws_lambda_layer_version" "lambda_layer" {
  filename   = "requests.zip"
  layer_name = "requests"

  compatible_runtimes = ["python3.13"]
}

# Create S3 bucket for Lambda deployment package
resource "aws_s3_bucket" "lambda_bucket" {
  bucket = "awsinstanceschedulardabb"
  acl    = "private"
}

# IAM Role for Lambda
resource "aws_iam_role" "lambda_exec_role" {
  name = "aws_instance_lambda"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action    = "sts:AssumeRole"
        Effect    = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

# Attach managed policy for Lambda execution
resource "aws_iam_role_policy_attachment" "lambda_exec_policy" {
  role       = aws_iam_role.lambda_exec_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Upload deployment package to S3
resource "aws_s3_object" "lambda_zip_upload" {
  bucket = aws_s3_bucket.lambda_bucket.id
  key    = "lambda_function.zip"
  source = data.archive_file.lambda_zip.output_path
  etag   = filemd5(data.archive_file.lambda_zip.output_path)
}

# Lambda Function
resource "aws_lambda_function" "my_lambda" {
  function_name    = "schedularService"
  role             = aws_iam_role.lambda_exec_role.arn
  handler          = "main.lambda_handler"
  runtime          = "python3.13"
  s3_bucket        = aws_s3_bucket.lambda_bucket.id
  s3_key           = aws_s3_object.lambda_zip_upload.key
  timeout = 300
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  layers = [
    aws_lambda_layer_version.lambda_layer.arn
  ]
  environment {
    variables = {
      regular_size=var.regular_size
      down_size=var.down_size
      access_key=var.access_key
      secret_key=var.secret_key
      region=var.region
    }
  }
}

# Create dynamo db to maintain service status
resource "aws_dynamodb_table" "users" {
  name           = "schedular"  # DynamoDB table name
  billing_mode   = "PAY_PER_REQUEST"  # or "PAY_PER_REQUEST"
  hash_key       = "timeofday"  # Primary key (Partition key)
  attribute {
    name = "timeofday"
    type = "S"  # String
  }
}

# Create an EventBridge rule with a cron schedule
resource "aws_cloudwatch_event_rule" "eventbridge_cron_rule_morning" {
  name                = "morning-cron-schedular_morning"
  description         = "An EventBridge rule that triggers based on a cron schedule"
  schedule_expression = "cron(0 3 ? * MON-SAT *)" # Cron expression for 6 PM UTC, Monday through Friday
}

# Create an EventBridge rule with a cron schedule
resource "aws_cloudwatch_event_rule" "eventbridge_cron_rule_evening" {
  name                = "morning-cron-schedular_evening"
  description         = "An EventBridge rule that triggers based on a cron schedule"
  schedule_expression = "cron(0 15 ? * MON-SAT *)" # Cron expression for 6 PM UTC, Monday through Friday
}

# Define the target for the EventBridge rule
resource "aws_cloudwatch_event_target" "eventbridge_target_morning" {
  rule      = aws_cloudwatch_event_rule.eventbridge_cron_rule_morning.name
  target_id = "event_bridge_morning"
  arn       = aws_lambda_function.my_lambda.arn # Replace with your Lambda or other target ARN
}

# Define the target for the EventBridge rule evening
resource "aws_cloudwatch_event_target" "eventbridge_target_evening" {
  rule      = aws_cloudwatch_event_rule.eventbridge_cron_rule_evening.name
  target_id = "event_bridge_evening"
  arn       = aws_lambda_function.my_lambda.arn # Replace with your Lambda or other target ARN
}

# Grant permissions for EventBridge to invoke the target
resource "aws_lambda_permission" "eventbridge_permission_morning" {
  statement_id  = "AllowExecutionFromEventBridgeMorning"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.my_lambda.function_name # Replace with your Lambda function name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.eventbridge_cron_rule_morning.arn
}

resource "aws_lambda_permission" "eventbridge_permission_evening" {
  statement_id  = "AllowExecutionFromEventBridgeEvening"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.my_lambda.function_name # Replace with your Lambda function name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.eventbridge_cron_rule_evening.arn
}
