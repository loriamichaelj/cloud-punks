variable "aws_region" {
  type = string
}

variable "cluster_name" {
  description = "Must match cluster_name in the dev/platform stack."
  type        = string
  default     = "loria-retail-dev"
}

variable "namespace" {
  description = "Namespace the application releases install into."
  type        = string
  default     = "retail"
}

variable "deploy_group" {
  description = "Kubernetes group of the deploy role (set on its EKS access entry by the platform stack's eks module, variable deploy_kubernetes_group)."
  type        = string
  default     = "retail-deployers"
}

# Pinned chart versions. Bump these deliberately.
variable "lbc_chart_version" {
  description = "AWS Load Balancer Controller chart (app v3.5.0). lbc-iam-policy.json is the matching upstream policy."
  type        = string
  default     = "3.5.0"
}

variable "eso_chart_version" {
  description = "External Secrets Operator chart (app v2.11.0)."
  type        = string
  default     = "2.11.0"
}
