output "db_endpoint" {
  description = "DB_HOST for the product and order services (the host, no port)."
  value       = aws_db_instance.this.address
}

output "db_port" {
  value = aws_db_instance.this.port
}

output "db_master_secret_arn" {
  description = "Secrets Manager secret holding the RDS master credentials. Used once, by the bootstrap migration that creates the app roles."
  value       = aws_db_instance.this.master_user_secret[0].secret_arn
}

output "cache_url" {
  description = "CACHE_URL: rediss:// because transit encryption is on."
  value       = "rediss://${aws_elasticache_replication_group.this.primary_endpoint_address}:6379/0"
}

output "table_names" {
  description = "INVENTORY_TABLE, RESERVATIONS_TABLE and NOTIFICATIONS_TABLE."
  value = {
    INVENTORY_TABLE     = aws_dynamodb_table.this["inventory"].name
    RESERVATIONS_TABLE  = aws_dynamodb_table.this["reservations"].name
    NOTIFICATIONS_TABLE = aws_dynamodb_table.this["notifications"].name
  }
}

output "table_arns" {
  description = "Table key => ARN, to scope each service's Pod Identity role."
  value       = { for k, t in aws_dynamodb_table.this : k => t.arn }
}

output "kms_key_arn" {
  description = "The data-tier key, for the workload roles that read DynamoDB."
  value       = aws_kms_key.data.arn
}

output "postgres_security_group_id" {
  description = "Allow more clients in with aws_vpc_security_group_ingress_rule (the runner does, for db_init)."
  value       = aws_security_group.postgres.id
}
