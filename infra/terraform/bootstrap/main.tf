data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  env        = var.target_environment
  prefix     = "cloudbatch818"

  sub_pull_request = "repo:${var.github_repository}:pull_request"
  sub_environment  = "repo:${var.github_repository}:environment:${local.env}"

  bucket_arn = "arn:aws:s3:::${var.state_bucket_name}"
}

# Plan role: reads everything, reads state, and may only create and remove
# lock files. Fork PRs get no OIDC token, so they cannot assume it.
data "aws_iam_policy_document" "tf_plan" {
  statement {
    sid       = "ListStateBucket"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [local.bucket_arn]
  }

  statement {
    sid       = "ReadState"
    actions   = ["s3:GetObject"]
    resources = ["${local.bucket_arn}/*"]
  }

  statement {
    sid       = "WriteLockfilesOnly"
    actions   = ["s3:PutObject", "s3:DeleteObject"]
    resources = ["${local.bucket_arn}/*.tflock"]
  }
}

# Apply role: broad by design (DESIGN.md section 13, accepted gap). IAM is the
# one area kept narrow: it can manage only cloudbatch818-retail-* roles and
# policies, so it cannot edit the tf-plan, tf-apply or deploy roles.
data "aws_iam_policy_document" "tf_apply" {
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
      "arn:aws:iam::${local.account_id}:role/${local.prefix}-retail-*",
      "arn:aws:iam::${local.account_id}:policy/${local.prefix}-retail-*",
      "arn:aws:iam::${local.account_id}:instance-profile/${local.prefix}-retail-*",
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

  statement {
    sid       = "DescribeCluster"
    actions   = ["eks:DescribeCluster"]
    resources = ["arn:aws:eks:${var.aws_region}:${local.account_id}:cluster/${var.eks_cluster_name}"]
  }
}

module "tf_plan" {
  source = "../modules/github-oidc"

  role_name           = "${local.prefix}-tf-plan"
  subject             = local.sub_pull_request
  managed_policy_arns = ["arn:aws:iam::aws:policy/ReadOnlyAccess"]
  inline_policies     = { state-read-and-lock = data.aws_iam_policy_document.tf_plan.json }
}

module "tf_apply" {
  source = "../modules/github-oidc"

  role_name       = "${local.prefix}-tf-apply-${local.env}"
  subject         = local.sub_environment
  inline_policies = { platform = data.aws_iam_policy_document.tf_apply.json }
}

module "deploy" {
  source = "../modules/github-oidc"

  role_name       = "${local.prefix}-deploy-${local.env}"
  subject         = local.sub_environment
  inline_policies = { ecr-and-eks-describe = data.aws_iam_policy_document.deploy.json }
}
