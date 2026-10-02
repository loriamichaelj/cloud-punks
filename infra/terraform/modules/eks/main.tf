data "aws_caller_identity" "current" {}

locals {
  iam_prefix = var.iam_name_prefix

  # Needed before nodes can become Ready.
  early_addons = toset(["vpc-cni", "kube-proxy"])
  # Workloads (or DaemonSets that only matter on nodes) that need a node first.
  late_addons = toset(["coredns", "eks-pod-identity-agent", "metrics-server"])
}

# --- secrets encryption key --------------------------------------------------

resource "aws_kms_key" "secrets" {
  description         = "Envelope encryption of Kubernetes secrets for ${var.name}"
  enable_key_rotation = true
}

resource "aws_kms_alias" "secrets" {
  name          = "alias/${var.name}-eks-secrets"
  target_key_id = aws_kms_key.secrets.key_id
}

# --- cluster role ------------------------------------------------------------

data "aws_iam_policy_document" "eks_assume" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]

    principals {
      type        = "Service"
      identifiers = ["eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "cluster" {
  name               = "${local.iam_prefix}-cluster"
  assume_role_policy = data.aws_iam_policy_document.eks_assume.json
}

resource "aws_iam_role_policy_attachment" "cluster" {
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

data "aws_iam_policy_document" "cluster_kms" {
  statement {
    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:ListGrants",
      "kms:DescribeKey",
    ]
    resources = [aws_kms_key.secrets.arn]
  }
}

resource "aws_iam_role_policy" "cluster_kms" {
  name   = "secrets-encryption-key"
  role   = aws_iam_role.cluster.id
  policy = data.aws_iam_policy_document.cluster_kms.json
}

# --- cluster -----------------------------------------------------------------

resource "aws_cloudwatch_log_group" "cluster" {
  name              = "/aws/eks/${var.name}/cluster"
  retention_in_days = var.log_retention_days
}

resource "aws_eks_cluster" "this" {
  name     = var.name
  version  = var.kubernetes_version
  role_arn = aws_iam_role.cluster.arn

  # Add-ons are managed below, so EKS must not install its own copies.
  bootstrap_self_managed_addons = false

  access_config {
    authentication_mode = "API"
    # Access is granted only through the explicit access entries below.
    bootstrap_cluster_creator_admin_permissions = false
  }

  vpc_config {
    subnet_ids              = var.subnet_ids
    endpoint_private_access = true
    endpoint_public_access  = false
  }

  encryption_config {
    resources = ["secrets"]

    provider {
      key_arn = aws_kms_key.secrets.arn
    }
  }

  enabled_cluster_log_types = ["api", "audit", "authenticator"]

  depends_on = [
    aws_iam_role_policy_attachment.cluster,
    aws_iam_role_policy.cluster_kms,
    aws_cloudwatch_log_group.cluster,
  ]
}

# --- access entries (no aws-auth ConfigMap) ----------------------------------

resource "aws_eks_access_entry" "admin" {
  for_each = var.admin_role_arns

  cluster_name  = aws_eks_cluster.this.name
  principal_arn = each.value
}

resource "aws_eks_access_policy_association" "admin" {
  for_each = var.admin_role_arns

  cluster_name  = aws_eks_cluster.this.name
  principal_arn = each.value
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"

  access_scope {
    type = "cluster"
  }

  depends_on = [aws_eks_access_entry.admin]
}

resource "aws_eks_access_entry" "deploy" {
  cluster_name  = aws_eks_cluster.this.name
  principal_arn = var.deploy_role_arn
}

resource "aws_eks_access_policy_association" "deploy" {
  cluster_name  = aws_eks_cluster.this.name
  principal_arn = var.deploy_role_arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSEditPolicy"

  access_scope {
    type       = "namespace"
    namespaces = [var.deploy_namespace]
  }

  depends_on = [aws_eks_access_entry.deploy]
}

# --- node group --------------------------------------------------------------

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "node" {
  name               = "${local.iam_prefix}-node"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_role_policy_attachment" "node" {
  for_each = toset([
    "AmazonEKSWorkerNodePolicy",
    "AmazonEKS_CNI_Policy",
    "AmazonEC2ContainerRegistryReadOnly",
  ])

  role       = aws_iam_role.node.name
  policy_arn = "arn:aws:iam::aws:policy/${each.key}"
}

resource "aws_eks_addon" "early" {
  for_each = local.early_addons

  cluster_name                = aws_eks_cluster.this.name
  addon_name                  = each.key
  addon_version               = lookup(var.addon_versions, each.key, null)
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "PRESERVE"
}

resource "aws_eks_node_group" "default" {
  cluster_name    = aws_eks_cluster.this.name
  node_group_name = "${var.name}-default"
  node_role_arn   = aws_iam_role.node.arn
  subnet_ids      = var.subnet_ids

  ami_type       = var.node_ami_type
  instance_types = var.node_instance_types
  capacity_type  = "ON_DEMAND"
  disk_size      = var.node_disk_size_gib

  scaling_config {
    min_size     = var.node_min_size
    desired_size = var.node_desired_size
    max_size     = var.node_max_size
  }

  update_config {
    max_unavailable = 1
  }

  lifecycle {
    ignore_changes = [scaling_config[0].desired_size]
  }

  depends_on = [
    aws_iam_role_policy_attachment.node,
    aws_eks_addon.early,
  ]
}

resource "aws_eks_addon" "late" {
  for_each = local.late_addons

  cluster_name                = aws_eks_cluster.this.name
  addon_name                  = each.key
  addon_version               = lookup(var.addon_versions, each.key, null)
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "PRESERVE"

  depends_on = [aws_eks_node_group.default]
}
