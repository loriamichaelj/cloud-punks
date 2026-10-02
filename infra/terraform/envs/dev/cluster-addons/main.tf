data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  iam_prefix = "cloudbatch818-loria-retail-dev"
}

# Outputs of the platform stack: the VPC and the RDS master secret.
data "terraform_remote_state" "platform" {
  backend = "s3"

  config = {
    bucket = "loria-retail-tfstate-${local.account_id}-${var.aws_region}"
    key    = "dev/platform/terraform.tfstate"
    region = var.aws_region
  }
}

data "aws_eks_cluster" "this" {
  name = var.cluster_name
}

data "aws_eks_cluster_auth" "this" {
  name = var.cluster_name
}

# --- the application namespace ------------------------------------------------------

resource "kubernetes_namespace_v1" "retail" {
  metadata {
    name = var.namespace
  }
}

# --- AWS Load Balancer Controller ------------------------------------------------------
# Turns Ingress objects into ALBs. The chart also creates the `alb` IngressClass.

module "lbc_role" {
  source = "../../../modules/pod-identity-role"

  role_name       = "${local.iam_prefix}-lbc"
  cluster_name    = var.cluster_name
  namespace       = "kube-system"
  service_account = "aws-load-balancer-controller"
  policy_json     = file("${path.module}/lbc-iam-policy.json")
}

resource "helm_release" "lbc" {
  name       = "aws-load-balancer-controller"
  namespace  = "kube-system"
  repository = "https://aws.github.io/eks-charts"
  chart      = "aws-load-balancer-controller"
  version    = var.lbc_chart_version

  wait    = true
  atomic  = true
  timeout = 600

  values = [yamlencode({
    clusterName  = var.cluster_name
    region       = var.aws_region
    vpcId        = data.terraform_remote_state.platform.outputs.vpc_id
    replicaCount = 1 # one node: a second replica would only compete for it
    serviceAccount = {
      create = true
      name   = "aws-load-balancer-controller"
    }
    resources = {
      requests = { cpu = "50m", memory = "128Mi" }
      limits   = { memory = "256Mi" }
    }
  })]

  # The Pod Identity association must exist before the controller starts, or its first
  # AWS calls fail and the pod restarts.
  depends_on = [module.lbc_role]
}

# --- External Secrets Operator -----------------------------------------------------------
# Copies Secrets Manager values into Kubernetes Secrets. The ClusterSecretStore that points
# it at AWS is created with the dev Helm values, not here: it is a custom resource, and its
# CRD only exists once this release is installed.

data "aws_iam_policy_document" "eso" {
  statement {
    sid     = "ReadRetailSecrets"
    actions = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = [
      data.terraform_remote_state.platform.outputs.db_master_secret_arn,
      "arn:aws:secretsmanager:${var.aws_region}:${local.account_id}:secret:loria-retail-dev/*",
    ]
  }

  # The RDS master secret and the app secrets are encrypted with the data key.
  statement {
    sid       = "DecryptWithTheDataKey"
    actions   = ["kms:Decrypt"]
    resources = ["arn:aws:kms:${var.aws_region}:${local.account_id}:key/*"]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["secretsmanager.${var.aws_region}.amazonaws.com"]
    }
  }
}

module "eso_role" {
  source = "../../../modules/pod-identity-role"

  role_name       = "${local.iam_prefix}-external-secrets"
  cluster_name    = var.cluster_name
  namespace       = "external-secrets"
  service_account = "external-secrets"
  policy_json     = data.aws_iam_policy_document.eso.json
}

resource "helm_release" "eso" {
  name             = "external-secrets"
  namespace        = "external-secrets"
  create_namespace = true
  repository       = "https://external-secrets.io"
  chart            = "external-secrets"
  version          = var.eso_chart_version

  wait    = true
  atomic  = true
  timeout = 600

  values = [yamlencode({
    replicaCount = 1
    serviceAccount = {
      create = true
      name   = "external-secrets"
    }
    webhook        = { replicaCount = 1 }
    certController = { replicaCount = 1 }
  })]

  depends_on = [module.eso_role, helm_release.lbc]
}
