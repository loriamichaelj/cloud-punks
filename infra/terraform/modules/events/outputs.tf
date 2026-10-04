output "bus_name" {
  description = "EVENT_BUS_NAME for the relay and the inventory consumer."
  value       = aws_cloudwatch_event_bus.this.name
}

output "bus_arn" {
  description = "Scope events:PutEvents for the producers to this."
  value       = aws_cloudwatch_event_bus.this.arn
}

output "queue_names" {
  description = "Route name => QUEUE_NAME for the consumer that reads it."
  value       = { for k, q in aws_sqs_queue.this : k => q.name }
}

output "queue_arns" {
  description = "Route name => queue ARN, to scope each consumer's receive and delete."
  value       = { for k, q in aws_sqs_queue.this : k => q.arn }
}

output "dlq_names" {
  value = { for k, q in aws_sqs_queue.dlq : k => q.name }
}

output "dlq_arns" {
  description = "Route name => DLQ ARN, for the DLQ alarms."
  value       = { for k, q in aws_sqs_queue.dlq : k => q.arn }
}

output "low_stock_function_name" {
  value = aws_lambda_function.low_stock.function_name
}

output "low_stock_log_group_name" {
  description = "Where the low_stock records are. The deploy role may read this one group, for the acceptance test."
  value       = aws_cloudwatch_log_group.low_stock.name
}

output "low_stock_dlq_arn" {
  description = "For the DLQ alarms."
  value       = aws_sqs_queue.low_stock_dlq.arn
}

output "rule_names" {
  description = "Route name => EventBridge rule name, for the FailedInvocations alarms."
  value       = { for k, r in aws_cloudwatch_event_rule.route : k => r.name }
}

output "low_stock_rule_name" {
  value = aws_cloudwatch_event_rule.low_stock.name
}

output "low_stock_dlq_name" {
  value = aws_sqs_queue.low_stock_dlq.name
}

output "market_email_function_name" {
  description = "The market-activity-email function, or null without an address."
  value       = one(aws_lambda_function.market_email[*].function_name)
}

output "market_email_dlq_name" {
  value = one(aws_sqs_queue.market_email_dlq[*].name)
}
