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
