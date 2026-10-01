variable "aws_region" {
  type = string
}

variable "cluster_name" {
  description = "Must match eks_cluster_name in the bootstrap stack, which scopes the deploy role to it."
  type        = string
  default     = "retail-dev"
}

variable "ecr_repository_prefix" {
  description = "Must match ecr_repository_prefix in the bootstrap stack."
  type        = string
  default     = "retail"
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
