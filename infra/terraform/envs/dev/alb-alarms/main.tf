# The two ALB alarms DESIGN.md section 13 asks for. They live apart from the platform stack because the
# ALB does not exist when that stack is planned: the AWS Load Balancer Controller creates it from the
# Ingress that app-deploy.yml installs. Everything this stack needs is passed in or derived from a name,
# so it can be destroyed even after the ALB is gone.

data "aws_caller_identity" "current" {}

locals {
  # The topic the monitoring module in the platform stack creates.
  topic_arn = "arn:aws:sns:${var.aws_region}:${data.aws_caller_identity.current.account_id}:${var.name}-alarms"
}

resource "aws_cloudwatch_metric_alarm" "alb_5xx_rate" {
  alarm_name          = "${var.name}-alb-5xx-rate"
  alarm_description   = "More than ${var.five_xx_percent}% of requests through the ALB got a 5xx (from the pods or from the ALB itself)."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  threshold           = var.five_xx_percent
  treat_missing_data  = "notBreaching"

  alarm_actions = [local.topic_arn]
  ok_actions    = [local.topic_arn]

  metric_query {
    id    = "rate"
    label = "5xx percent"
    # The 5xx counts only report in periods that had one, so a gap means zero, not "no data".
    expression  = "IF(requests > ${var.min_requests}, 100 * (FILL(target_5xx, 0) + FILL(elb_5xx, 0)) / requests, 0)"
    return_data = true
  }

  metric_query {
    id = "requests"
    metric {
      namespace   = "AWS/ApplicationELB"
      metric_name = "RequestCount"
      period      = 300
      stat        = "Sum"
      dimensions  = { LoadBalancer = var.alb_arn_suffix }
    }
  }

  metric_query {
    id = "target_5xx"
    metric {
      namespace   = "AWS/ApplicationELB"
      metric_name = "HTTPCode_Target_5XX_Count"
      period      = 300
      stat        = "Sum"
      dimensions  = { LoadBalancer = var.alb_arn_suffix }
    }
  }

  metric_query {
    id = "elb_5xx"
    metric {
      namespace   = "AWS/ApplicationELB"
      metric_name = "HTTPCode_ELB_5XX_Count"
      period      = 300
      stat        = "Sum"
      dimensions  = { LoadBalancer = var.alb_arn_suffix }
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "alb_p95_latency" {
  alarm_name          = "${var.name}-alb-p95-latency"
  alarm_description   = "p95 response time of the targets behind the ALB is above ${var.p95_seconds} s."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "TargetResponseTime"
  dimensions          = { LoadBalancer = var.alb_arn_suffix }
  extended_statistic  = "p95"
  period              = 300
  evaluation_periods  = 3
  threshold           = var.p95_seconds
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = [local.topic_arn]
  ok_actions    = [local.topic_arn]
}
