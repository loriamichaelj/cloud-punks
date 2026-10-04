output "vpc_id" {
  value = module.network.vpc_id
}

output "private_app_subnet_ids" {
  value = module.network.private_app_subnet_ids
}

output "private_data_subnet_ids" {
  value = module.network.private_data_subnet_ids
}

output "ecr_repository_urls" {
  value = module.ecr.repository_urls
}

output "eks_cluster_name" {
  value = module.eks.cluster_name
}

output "eks_cluster_security_group_id" {
  value = module.eks.cluster_security_group_id
}

output "event_bus_name" {
  value = module.events.bus_name
}

output "queue_names" {
  value = module.events.queue_names
}

output "db_endpoint" {
  value = module.data.db_endpoint
}

output "db_master_secret_arn" {
  value = module.data.db_master_secret_arn
}

output "cache_url" {
  value = module.data.cache_url
}

output "table_names" {
  value = module.data.table_names
}

output "runner_github_token_secret" {
  description = "Store the fine-grained PAT in this secret before the runner can register."
  value       = module.runners.github_token_secret_name
}

output "runner_autoscaling_group" {
  value = module.runners.autoscaling_group_name
}

output "workload_role_arns" {
  description = "Release name => Pod Identity role ARN. The chart names each service account after its release."
  value       = { for k, m in module.workload_role : k => m.role_arn }
}

output "low_stock_function_name" {
  value = module.events.low_stock_function_name
}

output "low_stock_log_group_name" {
  value = module.events.low_stock_log_group_name
}

output "alarm_topic_arn" {
  value = module.monitoring.topic_arn
}

output "alarm_names" {
  value = module.monitoring.alarm_names
}

output "market_email_function_name" {
  value = module.events.market_email_function_name
}
