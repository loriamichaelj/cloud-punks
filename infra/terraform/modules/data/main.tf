# One key for the data tier: RDS storage and its master secret, and the DynamoDB tables.
resource "aws_kms_key" "data" {
  description         = "Encryption of the ${var.name} data stores"
  enable_key_rotation = true
}

resource "aws_kms_alias" "data" {
  name          = "alias/${var.name}-data"
  target_key_id = aws_kms_key.data.key_id
}

# --- security groups -----------------------------------------------------------

resource "aws_security_group" "postgres" {
  name        = "${var.name}-postgres"
  description = "PostgreSQL from the EKS pods"
  vpc_id      = var.vpc_id

  tags = { Name = "${var.name}-postgres" }
}

resource "aws_vpc_security_group_ingress_rule" "postgres_from_pods" {
  security_group_id            = aws_security_group.postgres.id
  description                  = "PostgreSQL from the EKS cluster security group"
  referenced_security_group_id = var.client_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_security_group" "valkey" {
  name        = "${var.name}-valkey"
  description = "Valkey from the EKS pods"
  vpc_id      = var.vpc_id

  tags = { Name = "${var.name}-valkey" }
}

resource "aws_vpc_security_group_ingress_rule" "valkey_from_pods" {
  security_group_id            = aws_security_group.valkey.id
  description                  = "Valkey from the EKS cluster security group"
  referenced_security_group_id = var.client_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 6379
  to_port                      = 6379
}

# --- RDS for PostgreSQL --------------------------------------------------------
# The two databases (product_db, order_db) and the owner/app roles inside them are
# created by the bootstrap migration, not by Terraform.

resource "aws_db_subnet_group" "this" {
  name       = "${var.name}-data"
  subnet_ids = var.data_subnet_ids
}

# Refuse connections that are not TLS.
resource "aws_db_parameter_group" "postgres" {
  name   = "${var.name}-postgres"
  family = "postgres${var.db_engine_version}"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }
}

resource "aws_db_instance" "this" {
  identifier = var.name

  engine         = "postgres"
  engine_version = var.db_engine_version
  instance_class = var.db_instance_class

  allocated_storage = var.db_allocated_storage_gib
  storage_type      = "gp3"
  storage_encrypted = true
  kms_key_id        = aws_kms_key.data.arn

  username = "retail_admin"
  # RDS creates and rotates the master password in Secrets Manager. It never appears in
  # Terraform state or outputs.
  manage_master_user_password   = true
  master_user_secret_kms_key_id = aws_kms_key.data.arn

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.postgres.id]
  parameter_group_name   = aws_db_parameter_group.postgres.name
  publicly_accessible    = false
  multi_az               = var.db_multi_az

  backup_retention_period         = var.db_backup_retention_days
  copy_tags_to_snapshot           = true
  deletion_protection             = var.db_deletion_protection
  skip_final_snapshot             = var.db_skip_final_snapshot
  final_snapshot_identifier       = var.db_skip_final_snapshot ? null : "${var.name}-final"
  auto_minor_version_upgrade      = true
  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]
}

# --- ElastiCache for Valkey ------------------------------------------------------

resource "aws_elasticache_subnet_group" "this" {
  name       = "${var.name}-data"
  subnet_ids = var.data_subnet_ids
}

# One node, no cluster mode. TLS in transit and encryption at rest. AUTH is not set
# yet: the token would have to be generated and handed to Terraform, which puts it in
# state; reachability is limited to the cluster security group meanwhile.
resource "aws_elasticache_replication_group" "this" {
  replication_group_id = var.name
  description          = "${var.name} Valkey cache"

  engine               = "valkey"
  engine_version       = var.cache_engine_version
  node_type            = var.cache_node_type
  port                 = 6379
  parameter_group_name = "default.valkey${split(".", var.cache_engine_version)[0]}"

  num_cache_clusters         = 1
  automatic_failover_enabled = false
  multi_az_enabled           = false

  subnet_group_name  = aws_elasticache_subnet_group.this.name
  security_group_ids = [aws_security_group.valkey.id]

  transit_encryption_enabled = true
  at_rest_encryption_enabled = true
}

# --- DynamoDB ------------------------------------------------------------------------

locals {
  tables = {
    inventory = {
      name     = "${var.table_prefix}-inventory"
      hash_key = "sku"
      ttl      = false
    }
    reservations = {
      name     = "${var.table_prefix}-inventory-reservations"
      hash_key = "order_id"
      ttl      = true
    }
    notifications = {
      name      = "${var.table_prefix}-notifications"
      hash_key  = "order_id"
      range_key = "event_id"
      ttl       = true
    }
  }
}

resource "aws_dynamodb_table" "this" {
  for_each = local.tables

  name         = each.value.name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = each.value.hash_key
  range_key    = lookup(each.value, "range_key", null)

  attribute {
    name = each.value.hash_key
    type = "S"
  }

  dynamic "attribute" {
    for_each = lookup(each.value, "range_key", null) == null ? [] : [each.value.range_key]
    content {
      name = attribute.value
      type = "S"
    }
  }

  ttl {
    attribute_name = "ttl"
    enabled        = each.value.ttl
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.data.arn
  }
}
