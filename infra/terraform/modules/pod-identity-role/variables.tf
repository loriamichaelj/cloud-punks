variable "role_name" {
  description = "IAM role name. The apply role can only manage cloudbatch818-loria-retail-dev-*."
  type        = string

  validation {
    condition     = startswith(var.role_name, "cloudbatch818-loria-retail-dev")
    error_message = "Role names must start with cloudbatch818-loria-retail-dev."
  }
}

variable "cluster_name" {
  type = string
}

variable "namespace" {
  description = "Namespace of the service account that assumes the role."
  type        = string
}

variable "service_account" {
  description = "Name of the Kubernetes service account that assumes the role."
  type        = string
}

variable "policy_json" {
  description = "Inline policy document for the role."
  type        = string
}
