locals {
  bus_name = "${var.prefix}-retail-events"

  # Queue and rule names as in the local bootstrap script; detail types as in DESIGN.md section 6.
  routes = {
    "to-inventory" = {
      queue        = "inventory-order-events"
      detail_types = ["OrderCreated"]
    }
    "to-order" = {
      queue        = "order-inventory-events"
      detail_types = ["InventoryReserved", "InventoryFailed"]
    }
    "to-notification" = {
      queue        = "notification-events"
      detail_types = ["InventoryReserved", "InventoryFailed", "OrderStatusUpdated"]
    }
  }
}

resource "aws_cloudwatch_event_bus" "this" {
  name = local.bus_name
}

# Replay source: every retail.* event for a week.
resource "aws_cloudwatch_event_archive" "all" {
  name             = "${local.bus_name}-archive"
  event_source_arn = aws_cloudwatch_event_bus.this.arn
  retention_days   = var.archive_retention_days

  event_pattern = jsonencode({
    source = [{ prefix = "retail." }]
  })
}

# --- queues ------------------------------------------------------------------

resource "aws_sqs_queue" "dlq" {
  for_each = local.routes

  name                      = "${var.prefix}-${each.value.queue}-dlq"
  message_retention_seconds = 1209600 # 14 days
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "this" {
  for_each = local.routes

  name                       = "${var.prefix}-${each.value.queue}"
  visibility_timeout_seconds = var.visibility_timeout_seconds
  receive_wait_time_seconds  = 20
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq[each.key].arn
    maxReceiveCount     = var.max_receive_count
  })
}

resource "aws_sqs_queue_redrive_allow_policy" "dlq" {
  for_each = local.routes

  queue_url = aws_sqs_queue.dlq[each.key].id

  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.this[each.key].arn]
  })
}

# --- routing -----------------------------------------------------------------

resource "aws_cloudwatch_event_rule" "route" {
  for_each = local.routes

  name           = "${var.prefix}-${each.key}"
  event_bus_name = aws_cloudwatch_event_bus.this.name

  event_pattern = jsonencode({
    detail-type = each.value.detail_types
  })
}

resource "aws_cloudwatch_event_target" "queue" {
  for_each = local.routes

  rule           = aws_cloudwatch_event_rule.route[each.key].name
  event_bus_name = aws_cloudwatch_event_bus.this.name
  target_id      = "queue"
  arn            = aws_sqs_queue.this[each.key].arn
}

# EventBridge -> SQS needs a queue policy scoped to the rule. Without it the rule
# matches and nothing arrives; the failure is silent (DESIGN.md section 6).
data "aws_iam_policy_document" "from_rule" {
  for_each = local.routes

  statement {
    sid       = "AllowRule"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.this[each.key].arn]

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_cloudwatch_event_rule.route[each.key].arn]
    }
  }
}

resource "aws_sqs_queue_policy" "from_rule" {
  for_each = local.routes

  queue_url = aws_sqs_queue.this[each.key].id
  policy    = data.aws_iam_policy_document.from_rule[each.key].json
}
