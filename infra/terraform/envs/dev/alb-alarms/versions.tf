terraform {
  required_version = ">= 1.11"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.67"
    }
  }

  # Bucket, key and region come from -backend-config in alarms-create.yml and alarms-destroy.yml.
  backend "s3" {
    use_lockfile = true
    encrypt      = true
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "retail-platform"
      Environment = "dev"
      ManagedBy   = "terraform"
      Stack       = "dev/alb-alarms"
    }
  }
}
