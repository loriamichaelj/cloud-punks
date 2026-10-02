variable "name" {
  description = "Name prefix, for example loria-retail-dev."
  type        = string
}

variable "iam_name_prefix" {
  description = "Prefix for the IAM role and instance profile. The apply role can only manage cloudbatch818-loria-retail-dev-*."
  type        = string

  validation {
    condition     = startswith(var.iam_name_prefix, "cloudbatch818-loria-retail-dev")
    error_message = "IAM names must start with cloudbatch818-loria-retail-dev."
  }
}

variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  description = "Private-app subnets."
  type        = list(string)
}

variable "cluster_security_group_id" {
  description = "The EKS cluster security group. The runner is allowed to reach the private API on 443 through it."
  type        = string
}

variable "github_repository" {
  description = "owner/repo the runner registers with. A repository-level runner serves only this repository."
  type        = string
}

variable "labels" {
  description = "Runner labels. Workflows target runs-on: [self-hosted, retail-vpc]."
  type        = string
  default     = "retail-vpc"
}

variable "instance_type" {
  type    = string
  default = "t4g.small"
}

variable "volume_size_gib" {
  type    = number
  default = 30
}

# Pinned downloads. Each comes with the checksum from the publisher.
variable "runner_version" {
  type    = string
  default = "2.337.0"
}

variable "runner_sha256" {
  type    = string
  default = "9b1dc70626422526e3c94767cf024896beb15da5342a3f4819bf2feac13e0393"
}

variable "helm_version" {
  description = "Helm 4: the Makefile and app-deploy use --rollback-on-failure."
  type        = string
  default     = "4.3.0"
}

variable "helm_sha256" {
  type    = string
  default = "31c5794dd55c66a51e6b7d2e2ac7a114ae8b1de41ff1d9ba51748ac973b06a08"
}

variable "kubectl_version" {
  description = "Within one minor version of the cluster (1.36)."
  type        = string
  default     = "1.36.5"
}

variable "kubectl_sha256" {
  type    = string
  default = "88fc1aca8fd0c1b44fe379f67c39bd6858bdfc50241dc55775f84d0f5b31da3a"
}

variable "uv_version" {
  description = "Same as the Dockerfiles, pr.yml and the app-test workflow."
  type        = string
  default     = "0.12.15"
}

variable "python_version" {
  type    = string
  default = "3.13"
}
