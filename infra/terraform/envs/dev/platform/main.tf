data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id

  # Created by the bootstrap stack; see infra/terraform/bootstrap.
  tf_role_arn     = "arn:aws:iam::${local.account_id}:role/cloudbatch818-loria-retail-tf-dev"
  deploy_role_arn = "arn:aws:iam::${local.account_id}:role/cloudbatch818-loria-retail-deploy-dev"
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

  name            = var.cluster_name
  iam_name_prefix = "cloudbatch818-loria-retail-dev"
  vpc_id          = module.network.vpc_id
  subnet_ids      = module.network.private_app_subnet_ids

  admin_role_arns = { tf = local.tf_role_arn }
  deploy_role_arn = local.deploy_role_arn
  addon_versions  = var.addon_versions
}

module "events" {
  source = "../../../modules/events"

  prefix          = var.name_prefix
  iam_name_prefix = "cloudbatch818-loria-retail-dev"

  # Built by scripts/package_lambda.py: the platform workflows run it before plan and before apply.
  lambda_zip_path = "${path.root}/../../../../../dist/low-stock-alert.zip"
}

module "data" {
  source = "../../../modules/data"

  name                     = var.cluster_name
  table_prefix             = var.name_prefix
  vpc_id                   = module.network.vpc_id
  data_subnet_ids          = module.network.private_data_subnet_ids
  client_security_group_id = module.eks.cluster_security_group_id

  # Dev is destroyed when idle (platform-destroy.yml), so the instance must be removable.
  db_deletion_protection = var.db_deletion_protection
  db_skip_final_snapshot = var.db_skip_final_snapshot
}

module "runners" {
  source = "../../../modules/runners"

  name                      = var.cluster_name
  iam_name_prefix           = "cloudbatch818-loria-retail-dev"
  vpc_id                    = module.network.vpc_id
  subnet_ids                = module.network.private_app_subnet_ids
  cluster_security_group_id = module.eks.cluster_security_group_id
  github_repository         = var.github_repository
}

# The in-VPC runner creates the application databases and roles (scripts/db_init.py, run by
# app-database.yml). That is the only reason it reaches PostgreSQL; the pods get in through the
# cluster security group rule inside the data module.
resource "aws_vpc_security_group_ingress_rule" "postgres_from_runner" {
  security_group_id            = module.data.postgres_security_group_id
  description                  = "PostgreSQL from the in-VPC runner"
  referenced_security_group_id = module.runners.security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}
