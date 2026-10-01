variable "aws_region" {
  type = string
}

variable "github_repository" {
  description = "owner/repo, as in github.repository. Used to build the exact OIDC sub claims."
  type        = string
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
  default     = "retail"
}

variable "eks_cluster_name" {
  description = "EKS cluster the deploy role may describe. Must match the name the eks module uses."
  type        = string
  default     = "retail-dev"
}
