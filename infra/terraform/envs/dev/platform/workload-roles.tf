# One IAM role per Kubernetes service account that talks to AWS, delivered by EKS Pod
# Identity (DESIGN.md section 13). The Helm chart names a service account after its release,
# so each key below is a release name. Least privilege: a consumer gets its own queue and its
# own tables, the relay gets PutEvents on the bus and nothing else.
#
# The product service, the order API and the UI never call AWS, so they have no role.

locals {
  app_namespace = "retail"
  workload_iam  = "cloudbatch818-loria-retail-dev"

  tables = module.data.table_arns
  key    = module.data.kms_key_arn
  bus    = module.events.bus_arn
  queue  = module.events.queue_arns
  dlq    = module.events.dlq_arns

  # The tables use a customer-managed key, so every caller needs it, but only through DynamoDB.
  dynamodb_key_actions = [
    "kms:Decrypt",
    "kms:Encrypt",
    "kms:ReEncrypt*",
    "kms:GenerateDataKey*",
    "kms:DescribeKey",
    "kms:CreateGrant",
  ]
}

# --- statements shared by several roles -----------------------------------------------------

data "aws_iam_policy_document" "dynamodb_key" {
  statement {
    sid       = "UseTheDataKeyThroughDynamoDb"
    actions   = local.dynamodb_key_actions
    resources = [local.key]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["dynamodb.${var.aws_region}.amazonaws.com"]
    }
  }
}

# --- the roles' policies ----------------------------------------------------------------------

data "aws_iam_policy_document" "inventory_service" {
  source_policy_documents = [data.aws_iam_policy_document.dynamodb_key.json]

  statement {
    sid       = "InventoryTable"
    actions   = ["dynamodb:DescribeTable", "dynamodb:GetItem", "dynamodb:BatchGetItem", "dynamodb:UpdateItem"]
    resources = [local.tables["inventory"]]
  }
}

data "aws_iam_policy_document" "inventory_consumer" {
  source_policy_documents = [data.aws_iam_policy_document.dynamodb_key.json]

  statement {
    sid = "OwnQueue"
    actions = [
      "sqs:GetQueueUrl", "sqs:GetQueueAttributes", "sqs:ReceiveMessage", "sqs:DeleteMessage",
    ]
    resources = [local.queue["to-inventory"]]
  }

  statement {
    sid       = "OwnDeadLetterQueueDepth"
    actions   = ["sqs:GetQueueUrl", "sqs:GetQueueAttributes"]
    resources = [local.dlq["to-inventory"]]
  }

  # The reservation is one TransactWriteItems: a Put on the reservations table and an Update
  # per SKU on the inventory table. IAM checks the underlying write actions.
  statement {
    sid = "InventoryAndReservations"
    actions = [
      "dynamodb:DescribeTable", "dynamodb:GetItem", "dynamodb:BatchGetItem",
      "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:ConditionCheckItem",
    ]
    resources = [local.tables["inventory"], local.tables["reservations"]]
  }

  statement {
    sid       = "PublishOutcomeEvents"
    actions   = ["events:PutEvents"]
    resources = [local.bus]
  }
}

data "aws_iam_policy_document" "order_relay" {
  statement {
    sid       = "PublishOrderEvents"
    actions   = ["events:PutEvents"]
    resources = [local.bus]
  }
}

data "aws_iam_policy_document" "order_consumer" {
  statement {
    sid = "OwnQueue"
    actions = [
      "sqs:GetQueueUrl", "sqs:GetQueueAttributes", "sqs:ReceiveMessage", "sqs:DeleteMessage",
    ]
    resources = [local.queue["to-order"]]
  }

  statement {
    sid       = "OwnDeadLetterQueueDepth"
    actions   = ["sqs:GetQueueUrl", "sqs:GetQueueAttributes"]
    resources = [local.dlq["to-order"]]
  }
}

data "aws_iam_policy_document" "notification_service" {
  source_policy_documents = [data.aws_iam_policy_document.dynamodb_key.json]

  statement {
    sid       = "ReadNotifications"
    actions   = ["dynamodb:DescribeTable", "dynamodb:Query"]
    resources = [local.tables["notifications"]]
  }
}

data "aws_iam_policy_document" "notification_consumer" {
  source_policy_documents = [data.aws_iam_policy_document.dynamodb_key.json]

  statement {
    sid = "OwnQueue"
    actions = [
      "sqs:GetQueueUrl", "sqs:GetQueueAttributes", "sqs:ReceiveMessage", "sqs:DeleteMessage",
    ]
    resources = [local.queue["to-notification"]]
  }

  statement {
    sid       = "OwnDeadLetterQueueDepth"
    actions   = ["sqs:GetQueueUrl", "sqs:GetQueueAttributes"]
    resources = [local.dlq["to-notification"]]
  }

  statement {
    sid       = "WriteNotifications"
    actions   = ["dynamodb:DescribeTable", "dynamodb:PutItem"]
    resources = [local.tables["notifications"]]
  }
}

# --- roles and associations --------------------------------------------------------------------

module "workload_role" {
  source = "../../../modules/pod-identity-role"

  for_each = {
    "inventory-service"     = data.aws_iam_policy_document.inventory_service.json
    "inventory-consumer"    = data.aws_iam_policy_document.inventory_consumer.json
    "order-relay"           = data.aws_iam_policy_document.order_relay.json
    "order-consumer"        = data.aws_iam_policy_document.order_consumer.json
    "notification-service"  = data.aws_iam_policy_document.notification_service.json
    "notification-consumer" = data.aws_iam_policy_document.notification_consumer.json
  }

  role_name       = "${local.workload_iam}-${each.key}"
  cluster_name    = module.eks.cluster_name
  namespace       = local.app_namespace
  service_account = each.key
  policy_json     = each.value
}
