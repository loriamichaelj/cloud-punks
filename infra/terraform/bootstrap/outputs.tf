output "role_arns" {
  description = "Set these as variables on the target GitHub Environment."
  value = {
    AWS_ROLE_ARN_TF     = module.tf.role_arn
    AWS_ROLE_ARN_DEPLOY = module.deploy.role_arn
  }
}
