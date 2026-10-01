data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id

  # Created by the bootstrap stack; see infra/terraform/bootstrap.
  tf_apply_role_arn = "arn:aws:iam::${local.account_id}:role/cloudbatch818-tf-apply-dev"
  deploy_role_arn   = "arn:aws:iam::${local.account_id}:role/cloudbatch818-deploy-dev"
}

module "network" {
  source = "../../../modules/network"

  name                        = var.cluster_name
  cluster_name                = var.cluster_name
  single_nat_gateway          = var.single_nat_gateway
  interface_endpoint_services = var.interface_endpoint_services
}

module "ecr" {
  source = "../../../modules/ecr"

  repository_prefix = var.ecr_repository_prefix
}

module "eks" {
  source = "../../../modules/eks"

  name       = var.cluster_name
  vpc_id     = module.network.vpc_id
  subnet_ids = module.network.private_app_subnet_ids

  admin_role_arns = { tf-apply = local.tf_apply_role_arn }
  deploy_role_arn = local.deploy_role_arn
  addon_versions  = var.addon_versions
}
