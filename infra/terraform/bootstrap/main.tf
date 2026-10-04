data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  env        = var.target_environment
  prefix     = "cloudbatch818-loria-retail"

  sub_environment = "${var.oidc_subject_prefix}:environment:${local.env}"

  bucket_arn = "arn:aws:s3:::${var.state_bucket_name}"
}

# Terraform role, for both plan and apply: broad by design (DESIGN.md section 13,
# accepted gap). It trusts only the dev environment, so every use passes the
# environment's reviewer. IAM is the one area kept narrow: it can manage only
# cloudbatch818-loria-retail-dev-* roles and policies, so it cannot edit the
# bootstrap, terraform or deploy roles.
data "aws_iam_policy_document" "tf" {
  #checkov:skip=CKV_AWS_107:The Terraform role is broad by design: an accepted dev gap in DESIGN.md section 13. IAM stays limited to cloudbatch818-loria-retail-dev-* and state to dev/*
  #checkov:skip=CKV_AWS_108:The Terraform role is broad by design: an accepted dev gap in DESIGN.md section 13
  #checkov:skip=CKV_AWS_109:The Terraform role is broad by design: an accepted dev gap in DESIGN.md section 13
  #checkov:skip=CKV_AWS_110:The Terraform role is broad by design: an accepted dev gap in DESIGN.md section 13. IAM is limited to the dev-prefixed names
  #checkov:skip=CKV_AWS_111:The Terraform role is broad by design: an accepted dev gap in DESIGN.md section 13
  #checkov:skip=CKV_AWS_356:The Terraform role is broad by design: an accepted dev gap in DESIGN.md section 13
  statement {
    sid       = "StateForEnvironment"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${local.bucket_arn}/${local.env}/*"]
  }

  statement {
    sid       = "ListStateBucket"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [local.bucket_arn]
  }

  statement {
    sid = "PlatformServices"
    actions = [
      "acm:*",
      "application-autoscaling:*",
      "autoscaling:*",
      "budgets:*",
      "cloudwatch:*",
      "dynamodb:*",
      "ec2:*",
      "ecr:*",
      "eks:*",
      "elasticache:*",
      "elasticloadbalancing:*",
      "events:*",
      "kms:*",
      "lambda:*",
      "logs:*",
      "rds:*",
      "secretsmanager:*",
      "ses:*", # the market activity email's identity (DESIGN.md section 16.11)
      "sns:*",
      "sqs:*",
      "ssm:*",
      "tag:*",
    ]
    resources = ["*"]
  }

  statement {
    sid = "ManageRetailRolesAndPolicies"
    actions = [
      "iam:CreateRole",
      "iam:DeleteRole",
      "iam:GetRole",
      "iam:UpdateRole",
      "iam:UpdateRoleDescription",
      "iam:UpdateAssumeRolePolicy",
      "iam:TagRole",
      "iam:UntagRole",
      "iam:ListRoleTags",
      "iam:PutRolePolicy",
      "iam:GetRolePolicy",
      "iam:DeleteRolePolicy",
      "iam:ListRolePolicies",
      "iam:AttachRolePolicy",
      "iam:DetachRolePolicy",
      "iam:ListAttachedRolePolicies",
      "iam:ListInstanceProfilesForRole",
      "iam:PassRole",
      "iam:CreatePolicy",
      "iam:DeletePolicy",
      "iam:GetPolicy",
      "iam:TagPolicy",
      "iam:UntagPolicy",
      "iam:ListPolicyTags",
      "iam:CreatePolicyVersion",
      "iam:DeletePolicyVersion",
      "iam:GetPolicyVersion",
      "iam:ListPolicyVersions",
      "iam:CreateInstanceProfile",
      "iam:DeleteInstanceProfile",
      "iam:GetInstanceProfile",
      "iam:TagInstanceProfile",
      "iam:UntagInstanceProfile",
      "iam:AddRoleToInstanceProfile",
      "iam:RemoveRoleFromInstanceProfile",
    ]
    resources = [
      "arn:aws:iam::${local.account_id}:role/${local.prefix}-${local.env}-*",
      "arn:aws:iam::${local.account_id}:policy/${local.prefix}-${local.env}-*",
      "arn:aws:iam::${local.account_id}:instance-profile/${local.prefix}-${local.env}-*",
    ]
  }

  statement {
    sid       = "ServiceLinkedRoles"
    actions   = ["iam:CreateServiceLinkedRole", "iam:DeleteServiceLinkedRole", "iam:GetRole"]
    resources = ["arn:aws:iam::${local.account_id}:role/aws-service-role/*"]
  }

  statement {
    sid = "ReadIamReferenceData"
    actions = [
      "iam:GetOpenIDConnectProvider",
      "iam:ListOpenIDConnectProviders",
      "iam:ListRoles",
      "iam:ListPolicies",
    ]
    resources = ["*"]
  }
}

# Deploy role: push and pull images, describe the cluster. Cluster access
# itself comes from an EKS access entry created by the eks module.
data "aws_iam_policy_document" "deploy" {
  #checkov:skip=CKV_AWS_356:logs:GetQueryResults and logs:StopQuery do not support resource-level permissions; logs:StartQuery is limited to the application log group
  # app-deploy's acceptance test checks that a low-stock reservation reaches the Lambda. Read
  # access to this one log group, and nothing else in CloudWatch.
  statement {
    sid       = "ReadLowStockLogs"
    actions   = ["logs:FilterLogEvents"]
    resources = ["arn:aws:logs:${var.aws_region}:${local.account_id}:log-group:${var.low_stock_log_group}:*"]
  }

  # The acceptance suite traces one order across the services in the application container logs.
  # StartQuery is limited to this group; the other two actions cannot be limited to a resource.
  statement {
    sid       = "QueryContainerLogs"
    actions   = ["logs:StartQuery"]
    resources = ["arn:aws:logs:${var.aws_region}:${local.account_id}:log-group:${var.container_log_group}:*"]
  }

  statement {
    sid       = "ReadQueryResults"
    actions   = ["logs:GetQueryResults", "logs:StopQuery"]
    resources = ["*"]
  }

  statement {
    sid       = "EcrLogin"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid = "EcrPushPull"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:DescribeImages",
      "ecr:GetDownloadUrlForLayer",
      "ecr:InitiateLayerUpload",
      "ecr:ListImages",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]
    resources = ["arn:aws:ecr:${var.aws_region}:${local.account_id}:repository/${var.ecr_repository_prefix}/*"]
  }

  # Used by app-destroy.yml to remove images. The repositories themselves belong
  # to the platform stack and are not touched.
  statement {
    sid       = "EcrDeleteImages"
    actions   = ["ecr:BatchDeleteImage"]
    resources = ["arn:aws:ecr:${var.aws_region}:${local.account_id}:repository/${var.ecr_repository_prefix}/*"]
  }

  statement {
    sid       = "DescribeCluster"
    actions   = ["eks:DescribeCluster"]
    resources = ["arn:aws:eks:${var.aws_region}:${local.account_id}:cluster/${var.eks_cluster_name}"]
  }
}

# Database role: used only by app-database.yml and app-seed.yml on the in-VPC runner. It reads
# the RDS master secret to create the application databases and roles, writes their passwords to
# Secrets Manager, and puts the starting stock into the inventory table. It can do nothing else:
# no RDS changes, no other secrets, no other tables, no ECR, no EKS.
data "aws_iam_policy_document" "db" {
  statement {
    sid       = "FindTheInstance"
    actions   = ["rds:DescribeDBInstances"]
    resources = ["arn:aws:rds:${var.aws_region}:${local.account_id}:db:${var.db_instance_identifier}"]
  }

  # RDS names its managed master secret rds!db-<uuid>.
  statement {
    sid       = "ReadTheMasterSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = ["arn:aws:secretsmanager:${var.aws_region}:${local.account_id}:secret:rds!db-*"]
  }

  # The master secret is encrypted with the data key; reading it needs that key, through
  # Secrets Manager only.
  statement {
    sid       = "DecryptThroughSecretsManager"
    actions   = ["kms:Decrypt"]
    resources = ["arn:aws:kms:${var.aws_region}:${local.account_id}:key/*"]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["secretsmanager.${var.aws_region}.amazonaws.com"]
    }
  }

  statement {
    sid = "ApplicationDatabaseSecrets"
    actions = [
      "secretsmanager:CreateSecret",
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret",
      "secretsmanager:TagResource",
    ]
    resources = ["arn:aws:secretsmanager:${var.aws_region}:${local.account_id}:secret:${var.db_secret_prefix}/*"]
  }

  # app-seed.yml: starting stock. PutItem only, on the one table.
  statement {
    sid       = "SeedTheInventoryTable"
    actions   = ["dynamodb:PutItem"]
    resources = ["arn:aws:dynamodb:${var.aws_region}:${local.account_id}:table/${var.inventory_table_name}"]
  }

  # The table uses a customer-managed key, so writing to it needs that key, through DynamoDB.
  statement {
    sid = "UseTheDataKeyThroughDynamoDb"
    actions = [
      "kms:Decrypt",
      "kms:Encrypt",
      "kms:ReEncrypt*",
      "kms:GenerateDataKey*",
      "kms:DescribeKey",
      "kms:CreateGrant",
    ]
    resources = ["arn:aws:kms:${var.aws_region}:${local.account_id}:key/*"]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["dynamodb.${var.aws_region}.amazonaws.com"]
    }
  }
}

module "tf" {
  source = "../modules/github-oidc"

  role_name       = "${local.prefix}-tf-${local.env}"
  subject         = local.sub_environment
  inline_policies = { platform = data.aws_iam_policy_document.tf.json }
}

module "deploy" {
  source = "../modules/github-oidc"

  role_name       = "${local.prefix}-deploy-${local.env}"
  subject         = local.sub_environment
  inline_policies = { ecr-and-eks-describe = data.aws_iam_policy_document.deploy.json }
}

module "db" {
  source = "../modules/github-oidc"

  role_name       = "${local.prefix}-db-${local.env}"
  subject         = local.sub_environment
  inline_policies = { database-init = data.aws_iam_policy_document.db.json }
}
