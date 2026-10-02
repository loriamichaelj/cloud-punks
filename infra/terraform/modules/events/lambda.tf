# The low-stock-alert function (DESIGN.md section 6): EventBridge invokes it directly for every
# InventoryReserved. For each item below the threshold it prints one CloudWatch Embedded Metric
# Format line, which is both the `low_stock` log entry and the LowStockDetected metric. It calls
# no other AWS API, so its role can only write its own logs and send to its dead-letter queue.
#
# Mirrors the Lambda, rule and target in local/localstack/init/ready.d/10-bootstrap.sh.

locals {
  function_name = "${var.prefix}-low-stock-alert"
}

resource "aws_cloudwatch_log_group" "low_stock" {
  name              = "/aws/lambda/${local.function_name}"
  retention_in_days = var.log_retention_days
}

# Asynchronous invocations that still fail after the built-in retries end up here.
resource "aws_sqs_queue" "low_stock_dlq" {
  name                      = "${local.function_name}-dlq"
  message_retention_seconds = 1209600 # 14 days
  sqs_managed_sse_enabled   = true
}

data "aws_iam_policy_document" "low_stock_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "low_stock" {
  name               = "${var.iam_name_prefix}-low-stock-alert"
  assume_role_policy = data.aws_iam_policy_document.low_stock_assume.json
}

data "aws_iam_policy_document" "low_stock" {
  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.low_stock.arn}:*"]
  }

  statement {
    sid       = "DeadLetter"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.low_stock_dlq.arn]
  }
}

resource "aws_iam_role_policy" "low_stock" {
  name   = "permissions"
  role   = aws_iam_role.low_stock.id
  policy = data.aws_iam_policy_document.low_stock.json
}

resource "aws_lambda_function" "low_stock" {
  function_name = local.function_name
  role          = aws_iam_role.low_stock.arn
  runtime       = "python3.13"
  architectures = ["arm64"]
  handler       = "handler.lambda_handler"
  memory_size   = 128
  timeout       = 10

  filename         = var.lambda_zip_path
  source_code_hash = filebase64sha256(var.lambda_zip_path)

  environment {
    variables = {
      LOW_STOCK_THRESHOLD = tostring(var.low_stock_threshold)
    }
  }

  dead_letter_config {
    target_arn = aws_sqs_queue.low_stock_dlq.arn
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.low_stock.name
  }

  # The group and the policy must exist first, or the function creates its own group or fails
  # its first write.
  depends_on = [aws_cloudwatch_log_group.low_stock, aws_iam_role_policy.low_stock]
}

resource "aws_cloudwatch_event_rule" "low_stock" {
  name           = "${var.prefix}-to-low-stock"
  event_bus_name = aws_cloudwatch_event_bus.this.name

  event_pattern = jsonencode({
    detail-type = ["InventoryReserved"]
  })
}

resource "aws_cloudwatch_event_target" "low_stock" {
  rule           = aws_cloudwatch_event_rule.low_stock.name
  event_bus_name = aws_cloudwatch_event_bus.this.name
  target_id      = "lambda"
  arn            = aws_lambda_function.low_stock.arn
}

# Only this rule may invoke the function.
resource "aws_lambda_permission" "from_rule" {
  statement_id  = "AllowEventBridgeRule"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.low_stock.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.low_stock.arn
}
