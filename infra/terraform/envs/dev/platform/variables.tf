variable "aws_region" {
  type = string
}

variable "cluster_name" {
  description = "Must match eks_cluster_name in the bootstrap stack, which scopes the deploy role to it."
  type        = string
  default     = "loria-retail-dev"
}

variable "ecr_repository_prefix" {
  description = "Must match ecr_repository_prefix in the bootstrap stack."
  type        = string
  default     = "loria-retail"
}

variable "single_nat_gateway" {
  type    = bool
  default = true
}

variable "interface_endpoint_services" {
  type    = set(string)
  default = ["ecr.api", "ecr.dkr", "sts", "secretsmanager", "sqs", "events", "logs"]
}

variable "addon_versions" {
  type    = map(string)
  default = {}
}

variable "name_prefix" {
  description = "Prefix for the events and DynamoDB resources (loria-retail-events, loria-inventory, ...)."
  type        = string
  default     = "loria"
}

variable "db_deletion_protection" {
  description = "Off in dev so platform-destroy can remove RDS. DESIGN.md asks for protection; turn it on for prod."
  type        = bool
  default     = false
}

variable "db_skip_final_snapshot" {
  description = "True in dev: the data is disposable. False for prod."
  type        = bool
  default     = true
}

variable "github_repository" {
  description = "owner/repo the in-VPC runner registers with."
  type        = string
  default     = "loriamichaelj/retail-platform"
}

variable "alarm_email" {
  description = "Where alarms and budget warnings go. The dev environment secret ALARM_EMAIL, passed by platform-create.yml; empty means no subscription and no budget."
  type        = string
  default     = ""
  sensitive   = true
}

variable "monthly_budget_usd" {
  description = "Monthly cost ceiling for the Budgets alert (DESIGN.md section 13, Phase 4)."
  type        = number
  default     = 350
}

variable "node_desired_size" {
  description = "Nodes in the managed group. Two since Phase 4: one node's 29 pods and 2 vCPU could not hold the app plus Container Insights, Prometheus and Grafana (measured 2 Oct 2026: 25 of 29 pods, 67% of CPU requested)."
  type        = number
  default     = 2
}

variable "log_retention_days" {
  description = "Retention of the Container Insights log groups."
  type        = number
  default     = 7
}
