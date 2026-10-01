output "role_arns" {
  description = "Set these as GitHub Environment variables (tf-plan on the repository, the others on the target environment)."
  value = {
    AWS_ROLE_ARN_TF_PLAN  = module.tf_plan.role_arn
    AWS_ROLE_ARN_TF_APPLY = module.tf_apply.role_arn
    AWS_ROLE_ARN_DEPLOY   = module.deploy.role_arn
  }
}
