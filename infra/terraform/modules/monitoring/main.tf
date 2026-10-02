# The alarms that need nothing but AWS's own metrics: queues and their dead-letter queues, EventBridge
# rules, the low-stock Lambda and RDS. They notify one SNS topic. The application's own signals (outbox
# age, orders stuck, pod restarts) and the ALB are separate: see DESIGN.md section 13, Phase 4.

resource "aws_sns_topic" "alarms" {
  #checkov:skip=CKV_AWS_26:The topic carries alarm text only, and CloudWatch alarms cannot publish to a topic encrypted with the AWS-managed key
  name = "${var.name}-alarms"
}

resource "aws_sns_topic_subscription" "email" {
  count = nonsensitive(var.alarm_email != "") ? 1 : 0

  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

locals {
  # One entry per alarm. Every entry has the same shape so the maps can be merged.
  queue_age = {
    for k, q in var.queue_names : "queue-age-${k}" => {
      description         = "The oldest message in ${q} is older than ${var.queue_age_seconds} s: its consumer is stopped or failing."
      namespace           = "AWS/SQS"
      metric_name         = "ApproximateAgeOfOldestMessage"
      dimensions          = { QueueName = q }
      statistic           = "Maximum"
      period              = 60
      evaluation_periods  = 2
      threshold           = var.queue_age_seconds
      comparison_operator = "GreaterThanThreshold"
    }
  }

  dead_letters = {
    for k, q in merge(var.dlq_names, { "low-stock" = var.low_stock_dlq_name }) : "dlq-${k}" => {
      description         = "${q} holds a message: something failed past its retries. Peek it, fix the cause, redrive."
      namespace           = "AWS/SQS"
      metric_name         = "ApproximateNumberOfMessagesVisible"
      dimensions          = { QueueName = q }
      statistic           = "Maximum"
      period              = 60
      evaluation_periods  = 1
      threshold           = 0
      comparison_operator = "GreaterThanThreshold"
    }
  }

  rule_failures = {
    for k, r in merge(var.rule_names, { "low-stock" = var.low_stock_rule_name }) : "rule-failed-${k}" => {
      description         = "EventBridge rule ${r} could not deliver to its target."
      namespace           = "AWS/Events"
      metric_name         = "FailedInvocations"
      dimensions          = { EventBusName = var.event_bus_name, RuleName = r }
      statistic           = "Sum"
      period              = 300
      evaluation_periods  = 1
      threshold           = 0
      comparison_operator = "GreaterThanThreshold"
    }
  }

  database = {
    "db-cpu" = {
      description         = "RDS CPU above ${var.db_cpu_percent}% for 15 minutes."
      metric_name         = "CPUUtilization"
      statistic           = "Average"
      period              = 300
      evaluation_periods  = 3
      threshold           = var.db_cpu_percent
      comparison_operator = "GreaterThanThreshold"
    }
    "db-connections" = {
      description         = "RDS has more than ${var.db_connections} connections: a runaway pool or an HPA scale-out."
      metric_name         = "DatabaseConnections"
      statistic           = "Average"
      period              = 300
      evaluation_periods  = 2
      threshold           = var.db_connections
      comparison_operator = "GreaterThanThreshold"
    }
    "db-freeable-memory" = {
      description         = "RDS freeable memory is below ${var.db_freeable_memory_bytes / 1048576} MiB."
      metric_name         = "FreeableMemory"
      statistic           = "Average"
      period              = 300
      evaluation_periods  = 2
      threshold           = var.db_freeable_memory_bytes
      comparison_operator = "LessThanThreshold"
    }
    "db-free-storage" = {
      description         = "RDS free storage is below a tenth of the ${var.db_allocated_storage_gib} GiB allocated."
      metric_name         = "FreeStorageSpace"
      statistic           = "Average"
      period              = 300
      evaluation_periods  = 1
      threshold           = var.db_allocated_storage_gib * 1073741824 / 10
      comparison_operator = "LessThanThreshold"
    }
    "db-transaction-ids" = {
      description         = "PostgreSQL has used more than ${var.db_transaction_ids} transaction IDs: wraparound risk, vacuum is not keeping up."
      metric_name         = "MaximumUsedTransactionIDs"
      statistic           = "Maximum"
      period              = 300
      evaluation_periods  = 1
      threshold           = var.db_transaction_ids
      comparison_operator = "GreaterThanThreshold"
    }
  }

  database_alarms = {
    for k, a in local.database : k => merge(a, {
      namespace  = "AWS/RDS"
      dimensions = { DBInstanceIdentifier = var.db_identifier }
    })
  }

  lambda_errors = {
    "lambda-low-stock-errors" = {
      description         = "The low-stock Lambda reported an error."
      namespace           = "AWS/Lambda"
      metric_name         = "Errors"
      dimensions          = { FunctionName = var.low_stock_function_name }
      statistic           = "Sum"
      period              = 300
      evaluation_periods  = 1
      threshold           = 0
      comparison_operator = "GreaterThanThreshold"
    }
  }

  alarms = merge(local.queue_age, local.dead_letters, local.rule_failures, local.database_alarms, local.lambda_errors)
}

resource "aws_cloudwatch_metric_alarm" "this" {
  for_each = local.alarms

  alarm_name          = "${var.name}-${each.key}"
  alarm_description   = each.value.description
  namespace           = each.value.namespace
  metric_name         = each.value.metric_name
  dimensions          = each.value.dimensions
  statistic           = each.value.statistic
  period              = each.value.period
  evaluation_periods  = each.value.evaluation_periods
  threshold           = each.value.threshold
  comparison_operator = each.value.comparison_operator

  # A queue or a rule that has not been used reports nothing; that is not an alarm.
  treat_missing_data = "notBreaching"

  alarm_actions = [aws_sns_topic.alarms.arn]
  ok_actions    = [aws_sns_topic.alarms.arn]
}

# Cost, limited to what this project tags. Needs the Project cost-allocation tag activated in Billing,
# and an address to send to.
resource "aws_budgets_budget" "monthly" {
  count = nonsensitive(var.alarm_email != "") ? 1 : 0

  name         = "${var.name}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name   = "TagKeyValue"
    values = [var.budget_tag_filter]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alarm_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alarm_email]
  }
}
