variable "aws_region" {
  type = string
}

variable "domain_name" {
  description = "The same domain as the dns stack (the dev environment variable DEV_DOMAIN)."
  type        = string

  validation {
    condition     = can(regex("^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z]{2,63}$", var.domain_name)) && length(var.domain_name) <= 240
    error_message = "domain_name must be a lower-case registered domain such as example.com."
  }
}

# The AWS Load Balancer Controller creates each ALB from its Ingress, and AWS invents the DNS name and owns the
# hosted zone id, so the workflow looks both up (aws elbv2 describe-load-balancers) and passes them in. An empty
# value means that ALB does not exist (the viewer ALB only exists after app-expose), so it gets no record.
variable "public_alb_dns_name" {
  description = "DNSName of the viewer ALB (loria-retail-dev-public), or empty when it is not installed."
  type        = string
  default     = ""
}

variable "public_alb_zone_id" {
  description = "CanonicalHostedZoneId of the viewer ALB, or empty."
  type        = string
  default     = ""
}

variable "internal_alb_dns_name" {
  description = "DNSName of the internal ALB (loria-retail-dev), or empty when it is not installed."
  type        = string
  default     = ""
}

variable "internal_alb_zone_id" {
  description = "CanonicalHostedZoneId of the internal ALB, or empty."
  type        = string
  default     = ""
}
