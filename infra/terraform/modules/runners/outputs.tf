output "security_group_id" {
  value = aws_security_group.runner.id
}

output "github_token_secret_name" {
  description = "Put the fine-grained PAT here (SecretString)."
  value       = aws_secretsmanager_secret.github_token.name
}

output "github_token_secret_arn" {
  value = aws_secretsmanager_secret.github_token.arn
}

output "autoscaling_group_name" {
  value = aws_autoscaling_group.runner.name
}

output "role_arn" {
  value = aws_iam_role.runner.arn
}
