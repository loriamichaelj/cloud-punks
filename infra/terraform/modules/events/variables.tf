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

variable "iam_name_prefix" {
  description = "Prefix for the IAM role this module creates. The apply role can only manage cloudbatch818-loria-retail-dev-*."
  type        = string

  validation {
    condition     = startswith(var.iam_name_prefix, "cloudbatch818-loria-retail-dev")
    error_message = "IAM role names must start with cloudbatch818-loria-retail-dev."
  }
}

variable "lambda_zip_path" {
  description = "The low-stock-alert package, built by scripts/package_lambda.py before plan and again before apply."
  type        = string
}

variable "low_stock_threshold" {
  description = "A SKU with fewer units than this left after a reservation is reported (DESIGN.md section 6: 5)."
  type        = number
  default     = 5
}

variable "log_retention_days" {
  type    = number
  default = 30
}
