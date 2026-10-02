variable "aws_region" {
  type = string
}

variable "name" {
  description = "Prefix of the alarms and of the platform stack's SNS topic (<name>-alarms). Must match cluster_name in the dev/platform stack."
  type        = string
  default     = "loria-retail-dev"
}

variable "alb_arn_suffix" {
  description = "The ALB's CloudWatch dimension, for example app/loria-retail-dev/50dc6c495c0c9188. The AWS Load Balancer Controller creates the ALB after the platform stack, and AWS invents the last part, so alarms-create.yml looks it up and passes it as TF_VAR_alb_arn_suffix."
  type        = string

  validation {
    condition     = can(regex("^app/[A-Za-z0-9-]+/[0-9a-f]+$", var.alb_arn_suffix))
    error_message = "alb_arn_suffix must look like app/<name>/<hex id>."
  }
}

variable "five_xx_percent" {
  description = "Alarm when 5xx responses (the targets' plus the ALB's own) exceed this share of requests. DESIGN.md section 13: availability 99.5%."
  type        = number
  default     = 1
}

variable "min_requests" {
  description = "Below this many requests in a period the rate is not judged: one failed request out of three is not an outage."
  type        = number
  default     = 10
}

variable "p95_seconds" {
  description = "Alarm when p95 TargetResponseTime exceeds this. DESIGN.md section 13: reads 300 ms and create-order 500 ms, so the ALB-level ceiling is the looser."
  type        = number
  default     = 0.5
}
