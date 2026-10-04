variable "aws_region" {
  type = string
}

variable "name" {
  description = "The platform stack's cluster_name: the VPC carries it as its Name tag, and the private zone is associated with that VPC."
  type        = string
  default     = "loria-retail-dev"
}

variable "domain_name" {
  description = "The domain registered in Route 53, for example example.com (the dev environment variable DEV_DOMAIN). It must already have a public hosted zone, which registering it creates. The stack builds dev.<domain> for the viewer ALB and internal.dev.<domain> for the internal ALB."
  type        = string

  validation {
    condition     = can(regex("^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z]{2,63}$", var.domain_name)) && length(var.domain_name) <= 240
    error_message = "domain_name must be a lower-case registered domain such as example.com."
  }
}
