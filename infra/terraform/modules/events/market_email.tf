# The market-activity-email function (DESIGN.md section 16.11): EventBridge invokes it for every
# MarketActivity on a CloudPunk (up for bid, taken off, a bid placed or withdrawn, a sale), and it
# sends one email with the CloudPunk's picture through SES. The address is the dev environment
# secret ALARM_EMAIL (var.activity_email); it is the SES identity, the sender and the recipient,
# so SES's sandbox (send only to verified addresses) is enough. AWS emails that address a
# verification link when the identity is created; nothing is delivered until it is clicked.
#
# Without an address nothing here is created. Mirrors the function, rule and target in
# local/localstack/init/ready.d/10-bootstrap.sh, where LocalStack keeps the mail instead.

locals {
  market_email_enabled  = nonsensitive(var.activity_email != "")
  market_email_function = "${var.prefix}-market-activity-email"
}

resource "aws_ses_email_identity" "activity" {
  count = local.market_email_enabled ? 1 : 0
  email = var.activity_email
}

resource "aws_cloudwatch_log_group" "market_email" {
  #checkov:skip=CKV_AWS_158:The log group uses the default CloudWatch Logs encryption; a customer-managed key is not required in dev
  #checkov:skip=CKV_AWS_338:30 days of retention is enough in dev; keep a year in prod
  count             = local.market_email_enabled ? 1 : 0
  name              = "/aws/lambda/${local.market_email_function}"
  retention_in_days = var.log_retention_days
}

# Asynchronous invocations that still fail after the built-in retries (an SES error) end up here.
resource "aws_sqs_queue" "market_email_dlq" {
  count                     = local.market_email_enabled ? 1 : 0
  name                      = "${local.market_email_function}-dlq"
  message_retention_seconds = 1209600 # 14 days
  sqs_managed_sse_enabled   = true
}

resource "aws_iam_role" "market_email" {
  count              = local.market_email_enabled ? 1 : 0
  name               = "${var.iam_name_prefix}-market-activity-email"
  assume_role_policy = data.aws_iam_policy_document.low_stock_assume.json # the same Lambda trust
}

data "aws_iam_policy_document" "market_email" {
  count = local.market_email_enabled ? 1 : 0

  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.market_email[0].arn}:*"]
  }

  statement {
    sid       = "DeadLetter"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.market_email_dlq[0].arn]
  }

  # Send as the one verified address, and nothing else in SES.
  statement {
    sid       = "SendAsTheVerifiedAddress"
    actions   = ["ses:SendRawEmail"]
    resources = [aws_ses_email_identity.activity[0].arn]
  }
}

resource "aws_iam_role_policy" "market_email" {
  count  = local.market_email_enabled ? 1 : 0
  name   = "permissions"
  role   = aws_iam_role.market_email[0].id
  policy = data.aws_iam_policy_document.market_email[0].json
}

resource "aws_lambda_function" "market_email" {
  #checkov:skip=CKV_AWS_115:No reserved concurrency: the account limit is enough in dev
  #checkov:skip=CKV_AWS_117:The function calls SES only, so a VPC would only add NAT cost
  #checkov:skip=CKV_AWS_173:The variables are the owner's own address and are encrypted at rest with the AWS-managed key; no secret
  #checkov:skip=CKV_AWS_272:Code signing is not used for a small function built from this repository
  #checkov:skip=CKV_AWS_50:X-Ray is not needed for a function that sends one email
  count         = local.market_email_enabled ? 1 : 0
  function_name = local.market_email_function
  role          = aws_iam_role.market_email[0].arn
  runtime       = "python3.13"
  architectures = ["arm64"]
  handler       = "handler.lambda_handler"
  memory_size   = 256 # drawing the 240 x 240 picture is pure Python
  timeout       = 15

  filename         = var.market_email_zip_path
  source_code_hash = filebase64sha256(var.market_email_zip_path)

  environment {
    variables = {
      EMAIL_FROM = var.activity_email
      EMAIL_TO   = var.activity_email
    }
  }

  dead_letter_config {
    target_arn = aws_sqs_queue.market_email_dlq[0].arn
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.market_email[0].name
  }

  depends_on = [aws_cloudwatch_log_group.market_email, aws_iam_role_policy.market_email]
}

# Only CloudPunks: the cloud acceptance suite's own item (E2E-...) makes activity too.
resource "aws_cloudwatch_event_rule" "market_email" {
  count          = local.market_email_enabled ? 1 : 0
  name           = "${var.prefix}-to-market-activity-email"
  event_bus_name = aws_cloudwatch_event_bus.this.name

  event_pattern = jsonencode({
    detail-type = ["MarketActivity"]
    detail      = { data = { sku = [{ prefix = "CP-" }] } }
  })
}

resource "aws_cloudwatch_event_target" "market_email" {
  count          = local.market_email_enabled ? 1 : 0
  rule           = aws_cloudwatch_event_rule.market_email[0].name
  event_bus_name = aws_cloudwatch_event_bus.this.name
  target_id      = "lambda"
  arn            = aws_lambda_function.market_email[0].arn
}

resource "aws_lambda_permission" "market_email_from_rule" {
  count         = local.market_email_enabled ? 1 : 0
  statement_id  = "AllowEventBridgeRule"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.market_email[0].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.market_email[0].arn
}
