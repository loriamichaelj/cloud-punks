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
