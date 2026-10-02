variable "name" {
  description = "Prefix for the topic, the alarms and the budget, for example loria-retail-dev."
  type        = string
}

variable "alarm_email" {
  description = "Where alarms and budget warnings are sent. Empty creates the topic and alarms but no subscription and no budget. Held as the dev environment secret ALARM_EMAIL, never in the repository."
  type        = string
  default     = ""
  sensitive   = true
}

variable "monthly_budget_usd" {
  description = "Monthly cost ceiling for the AWS Budgets alert."
  type        = number
  default     = 350
}

variable "budget_tag_filter" {
  description = "Cost-allocation tag the budget is limited to (key$value). The tag must be activated in Billing, Cost allocation tags, or the budget sees no cost."
  type        = string
  default     = "user:Project$retail-platform"
}

variable "event_bus_name" {
  type = string
}

variable "queue_names" {
  description = "Route name => queue name, from the events module."
  type        = map(string)
}

variable "dlq_names" {
  description = "Route name => dead-letter queue name."
  type        = map(string)
}

variable "rule_names" {
  description = "Route name => EventBridge rule name."
  type        = map(string)
}

variable "low_stock_function_name" {
  type = string
}

variable "low_stock_rule_name" {
  type = string
}

variable "low_stock_dlq_name" {
  type = string
}

variable "db_identifier" {
  type = string
}

variable "db_allocated_storage_gib" {
  description = "Allocated storage; the free-space alarm fires below one tenth of it."
  type        = number
}

variable "queue_age_seconds" {
  description = "DESIGN.md section 13: the oldest message in a queue older than this is an alarm."
  type        = number
  default     = 120
}

variable "db_cpu_percent" {
  type    = number
  default = 80
}

variable "db_connections" {
  description = "About two thirds of what a db.t4g.small allows; the pools are 10 connections per replica."
  type        = number
  default     = 150
}

variable "db_freeable_memory_bytes" {
  type    = number
  default = 134217728 # 128 MiB
}

variable "db_transaction_ids" {
  description = "DESIGN.md section 13: wraparound risk above 1 billion used transaction IDs."
  type        = number
  default     = 1000000000
}
