# Container logs and pod metrics (Phase 4, P4.2): the Amazon CloudWatch Observability EKS add-on, which
# runs the CloudWatch agent (Container Insights metrics) and Fluent Bit (container logs) as DaemonSets
# and an operator. EKS installs it through its own API, so this stack needs no access to the private
# cluster endpoint. The agent assumes its role through EKS Pod Identity like the workloads do.

locals {
  insights_namespace = "amazon-cloudwatch"
  insights_prefix    = "/aws/containerinsights/${var.cluster_name}"
}

# Created here, not by the agent, so each has a retention. The agent writes to these names.
resource "aws_cloudwatch_log_group" "container_insights" {
  #checkov:skip=CKV_AWS_158:Container logs in dev use the CloudWatch-owned key; a customer-managed key is not required
  #checkov:skip=CKV_AWS_338:Seven days is enough in dev; keep a year in prod
  for_each = toset(["application", "dataplane", "host", "performance"])

  name              = "${local.insights_prefix}/${each.key}"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "cloudwatch_agent" {
  #checkov:skip=CKV_AWS_356:ec2:Describe* and PutMetricData cannot be limited to a resource; the log actions are limited to this cluster's groups
  statement {
    sid = "WriteThisClustersLogs"
    actions = [
      "logs:CreateLogGroup", # the groups exist; Fluent Bit still asks, and an access-denied here is only noise
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogStreams",
      "logs:PutRetentionPolicy",
    ]
    resources = flatten([for g in aws_cloudwatch_log_group.container_insights : [g.arn, "${g.arn}:*"]])
  }

  statement {
    sid       = "FindLogGroups"
    actions   = ["logs:DescribeLogGroups"]
    resources = ["*"]
  }

  statement {
    sid       = "PublishContainerInsightsMetrics"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = ["ContainerInsights"]
    }
  }

  statement {
    sid       = "DescribeTheNode"
    actions   = ["ec2:DescribeTags", "ec2:DescribeVolumes"]
    resources = ["*"]
  }
}

module "cloudwatch_agent_role" {
  source = "../../../modules/pod-identity-role"

  role_name       = "${local.workload_iam}-cloudwatch-agent"
  cluster_name    = var.cluster_name
  namespace       = local.insights_namespace
  service_account = "cloudwatch-agent"
  policy_json     = data.aws_iam_policy_document.cloudwatch_agent.json
}

resource "aws_eks_addon" "cloudwatch_observability" {
  cluster_name                = module.eks.cluster_name
  addon_name                  = "amazon-cloudwatch-observability"
  addon_version               = lookup(var.addon_versions, "amazon-cloudwatch-observability", null)
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "PRESERVE"

  # Nodes first (the add-on's pods need somewhere to run), then the log groups and the role.
  depends_on = [
    module.eks,
    module.cloudwatch_agent_role,
    aws_cloudwatch_log_group.container_insights,
  ]
}

# One saved query: paste a correlation id, read the order's whole path across the services in time order.
# Console: CloudWatch, Logs Insights, Queries, "retail/trace-a-correlation-id".
resource "aws_cloudwatch_query_definition" "trace_correlation_id" {
  name = "retail/trace-a-correlation-id"

  log_group_names = [aws_cloudwatch_log_group.container_insights["application"].name]

  query_string = <<-EOT
    fields @timestamp, kubernetes.container_name as process, log
    | filter @message like "PASTE-A-CORRELATION-ID-HERE"
    | sort @timestamp asc
    | limit 200
  EOT
}
