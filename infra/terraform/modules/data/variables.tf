variable "name" {
  description = "Name prefix for the stores, for example loria-retail-dev."
  type        = string
}

variable "table_prefix" {
  description = "DynamoDB table name prefix, for example loria. The services read the full names from INVENTORY_TABLE, RESERVATIONS_TABLE and NOTIFICATIONS_TABLE."
  type        = string
}

variable "vpc_id" {
  type = string
}

variable "data_subnet_ids" {
  description = "Private-data subnets for RDS and ElastiCache. RDS needs at least two AZs even when Single-AZ."
  type        = list(string)
}

variable "client_security_group_id" {
  description = "The EKS cluster security group, which the pods use. It is the only source allowed to reach RDS and Valkey."
  type        = string
}

# --- RDS ---------------------------------------------------------------------

variable "db_instance_class" {
  type    = string
  default = "db.t4g.small"
}

variable "db_allocated_storage_gib" {
  type    = number
  default = 20
}

variable "db_multi_az" {
  description = "Single-AZ in dev, Multi-AZ in prod."
  type        = bool
  default     = false
}

variable "db_engine_version" {
  description = "Major version only, so AWS picks its default 17.x minor. Pin a minor here once the first apply shows which one was chosen."
  type        = string
  default     = "17"
}

variable "db_backup_retention_days" {
  type    = number
  default = 7
}

variable "db_deletion_protection" {
  description = "True for anything that must survive. Dev sets it false so platform-destroy can remove the instance."
  type        = bool
  default     = true
}

variable "db_skip_final_snapshot" {
  type    = bool
  default = false
}

# --- Valkey ------------------------------------------------------------------

variable "cache_node_type" {
  type    = string
  default = "cache.t4g.micro"
}

variable "cache_engine_version" {
  type    = string
  default = "9.0"
}
