variable "name" {
  description = "Name prefix for every resource, for example loria-retail-dev."
  type        = string
}

variable "cluster_name" {
  description = "EKS cluster whose subnets these are; used for the kubernetes.io/cluster tags."
  type        = string
}

variable "cidr_block" {
  type    = string
  default = "10.20.0.0/16"
}

variable "az_count" {
  description = "Availability zones to span (DESIGN.md: 3)."
  type        = number
  default     = 3

  validation {
    condition     = var.az_count >= 2 && var.az_count <= 3
    error_message = "Use 2 or 3 AZs; an RDS subnet group needs at least two."
  }
}

variable "single_nat_gateway" {
  description = "One NAT gateway in the first AZ (dev) instead of one per AZ (prod)."
  type        = bool
  default     = true
}

variable "interface_endpoint_services" {
  description = "Interface endpoints to create, by service suffix (com.amazonaws.<region>.<suffix>). Empty list disables them. Each endpoint costs about $7.30 per AZ per month."
  type        = set(string)
  default     = ["ecr.api", "ecr.dkr", "sts", "secretsmanager", "sqs", "events", "logs"]
}

variable "interface_endpoint_az_count" {
  description = "AZs that get an endpoint network interface. 1 is enough for a one-node dev cluster; use az_count in prod."
  type        = number
  default     = 1
}
