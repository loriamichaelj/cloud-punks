variable "role_name" {
  description = "IAM role name. Must start with the prefix the bootstrap role is allowed to manage."
  type        = string

  validation {
    condition     = startswith(var.role_name, "cloudbatch818-")
    error_message = "Role names must start with cloudbatch818-."
  }
}

variable "subject" {
  description = "Exact OIDC sub claim the role trusts, for example repo:owner/repo:environment:dev. No wildcards."
  type        = string

  validation {
    condition     = !can(regex("[*?]", var.subject))
    error_message = "The trust subject must be exact: no wildcards."
  }
}

variable "managed_policy_arns" {
  description = "Managed policies to attach. The bootstrap role may only attach ReadOnlyAccess and cloudbatch818-* policies."
  type        = list(string)
  default     = []
}

variable "inline_policies" {
  description = "Inline policies as name => JSON document."
  type        = map(string)
  default     = {}
}

variable "max_session_duration" {
  description = "Maximum session length in seconds."
  type        = number
  default     = 3600
}
