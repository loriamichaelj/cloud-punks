variable "aws_region" {
  type = string
}

variable "oidc_subject_prefix" {
  description = "Start of every OIDC sub claim for this repository. With immutable subjects it is repo:<owner>@<owner id>/<repo>@<repo id>; see the repository's actions/oidc/customization/sub."
  type        = string

  validation {
    condition     = startswith(var.oidc_subject_prefix, "repo:")
    error_message = "The prefix must start with repo:."
  }
}

variable "state_bucket_name" {
  description = "Terraform state bucket created by the first job of bootstrap.yml."
  type        = string
}

variable "target_environment" {
  description = "GitHub Environment (and state key prefix) the apply and deploy roles serve."
  type        = string
  default     = "dev"
}

variable "ecr_repository_prefix" {
  description = "ECR repositories the deploy role may push to and pull from: <prefix>/*."
  type        = string
  default     = "loria-retail"
}

variable "eks_cluster_name" {
  description = "EKS cluster the deploy role may describe. Must match the name the eks module uses."
  type        = string
  default     = "loria-retail-dev"
}
