variable "prefix" {
  description = "Name prefix for every resource, for example loria. Mirrors local/localstack/init/ready.d/10-bootstrap.sh, which creates the same resources without it."
  type        = string
}

variable "archive_retention_days" {
  description = "EventBridge archive retention (DESIGN.md section 6: 7 days, cloud only, enables replay)."
  type        = number
  default     = 7
}

variable "max_receive_count" {
  type    = number
  default = 5
}

variable "visibility_timeout_seconds" {
  type    = number
  default = 60
}
