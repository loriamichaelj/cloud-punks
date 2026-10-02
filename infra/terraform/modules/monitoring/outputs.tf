output "topic_arn" {
  description = "The SNS topic every alarm notifies. Later alarms (ALB, pods, outbox) use it too."
  value       = aws_sns_topic.alarms.arn
}

output "alarm_names" {
  value = sort([for a in aws_cloudwatch_metric_alarm.this : a.alarm_name])
}
