output "alarm_names" {
  value = [
    aws_cloudwatch_metric_alarm.alb_5xx_rate.alarm_name,
    aws_cloudwatch_metric_alarm.alb_p95_latency.alarm_name,
  ]
}

output "topic_arn" {
  value = local.topic_arn
}
