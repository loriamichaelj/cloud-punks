variable "name" {
  description = "Cluster name, for example loria-retail-dev."
  type        = string
}

variable "iam_name_prefix" {
  description = "Prefix for the IAM roles this module creates. The apply role can only manage cloudbatch818-loria-retail-dev-*."
  type        = string

  validation {
    condition     = startswith(var.iam_name_prefix, "cloudbatch818-loria-retail-dev")
    error_message = "IAM role names must start with cloudbatch818-loria-retail-dev."
  }
}

variable "kubernetes_version" {
  description = "Pinned minor version. 1.36 is the newest EKS version in standard support (DESIGN.md section 13)."
  type        = string
  default     = "1.36"
}

variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  description = "Private-app subnets for the control plane network interfaces and the node group."
  type        = list(string)
}

variable "node_instance_types" {
  type    = list(string)
  default = ["m7g.large"]
}

variable "node_ami_type" {
  description = "AL2023 arm64 to match the Graviton instance type."
  type        = string
  default     = "AL2023_ARM_64_STANDARD"
}

variable "node_disk_size_gib" {
  type    = number
  default = 50
}

variable "node_min_size" {
  type    = number
  default = 1
}

variable "node_desired_size" {
  type    = number
  default = 1
}

variable "node_max_size" {
  description = "One above the desired size so a node-group update can bring a replacement up before the old node drains."
  type        = number
  default     = 2
}

variable "admin_role_arns" {
  description = "Role name => ARN of IAM roles that get cluster-admin through an access entry (the Terraform apply role)."
  type        = map(string)
  default     = {}
}

variable "deploy_role_arn" {
  description = "IAM role that deploys with Helm. It gets AmazonEKSEditPolicy in the deploy namespace only."
  type        = string
}

variable "deploy_namespace" {
  type    = string
  default = "retail"
}

variable "deploy_kubernetes_group" {
  description = "Kubernetes group the deploy role belongs to. The cluster-addons stack grants it access to ExternalSecrets in the deploy namespace; keep the two defaults the same."
  type        = string
  default     = "retail-deployers"
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "addon_versions" {
  description = "Pin add-on versions here (addon name => version). A missing key uses the EKS default version for the cluster version; fill them in once the apply shows what that default is."
  type        = map(string)
  default     = {}
}
