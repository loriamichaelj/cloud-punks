data "aws_region" "current" {}

# --- the GitHub token -------------------------------------------------------------
# Terraform makes the empty secret only. Put the fine-grained token in it by hand
# (see the README): a value created here would sit in Terraform state.

resource "aws_secretsmanager_secret" "github_token" {
  #checkov:skip=CKV2_AWS_57:The secret holds a GitHub token created by hand; Secrets Manager cannot rotate it
  #checkov:skip=CKV_AWS_149:The token secret uses the default Secrets Manager key
  name                    = "${var.name}-runner-github-token"
  description             = "Fine-grained PAT (Administration: read and write on ${var.github_repository}) the runner uses to register"
  recovery_window_in_days = 0
}

# --- instance role -----------------------------------------------------------------

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "runner" {
  name               = "${var.iam_name_prefix}-runner"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

# Session Manager is the only way in: the instance has no inbound rule and no SSH key.
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.runner.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "read_token" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.github_token.arn]
  }
}

resource "aws_iam_role_policy" "read_token" {
  name   = "read-github-token"
  role   = aws_iam_role.runner.id
  policy = data.aws_iam_policy_document.read_token.json
}

resource "aws_iam_instance_profile" "runner" {
  name = "${var.iam_name_prefix}-runner"
  role = aws_iam_role.runner.name
}

# --- network -----------------------------------------------------------------------

resource "aws_security_group" "runner" {
  name        = "${var.name}-runner"
  description = "In-VPC GitHub runner: no inbound traffic"
  vpc_id      = var.vpc_id

  tags = { Name = "${var.name}-runner" }
}

resource "aws_vpc_security_group_egress_rule" "all" {
  security_group_id = aws_security_group.runner.id
  description       = "GitHub, package sources and the AWS APIs"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

# The EKS API is private. This lets the runner reach it.
resource "aws_vpc_security_group_ingress_rule" "cluster_api_from_runner" {
  security_group_id            = var.cluster_security_group_id
  description                  = "Kubernetes API from the in-VPC runner"
  referenced_security_group_id = aws_security_group.runner.id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}

# --- the instance ----------------------------------------------------------------------

resource "aws_launch_template" "runner" {
  name_prefix   = "${var.name}-runner-"
  image_id      = "resolve:ssm:/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"
  instance_type = var.instance_type

  update_default_version = true

  iam_instance_profile {
    arn = aws_iam_instance_profile.runner.arn
  }

  vpc_security_group_ids = [aws_security_group.runner.id]

  # IMDSv2 only, one hop: a container on the host could not reach it either.
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  block_device_mappings {
    device_name = "/dev/xvda"

    ebs {
      volume_size           = var.volume_size_gib
      volume_type           = "gp3"
      encrypted             = true
      delete_on_termination = true
    }
  }

  user_data = base64encode(templatefile("${path.module}/user-data.sh.tftpl", {
    github_repository = var.github_repository
    region            = data.aws_region.current.region
    secret_id         = aws_secretsmanager_secret.github_token.name
    labels            = var.labels
    runner_version    = var.runner_version
    runner_sha256     = var.runner_sha256
    helm_version      = var.helm_version
    helm_sha256       = var.helm_sha256
    kubectl_version   = var.kubectl_version
    kubectl_sha256    = var.kubectl_sha256
    uv_version        = var.uv_version
    python_version    = var.python_version
  }))

  tag_specifications {
    resource_type = "instance"
    tags          = { Name = "${var.name}-runner" }
  }

  tag_specifications {
    resource_type = "volume"
    tags          = { Name = "${var.name}-runner" }
  }
}

resource "aws_autoscaling_group" "runner" {
  name                = "${var.name}-runner"
  min_size            = 1
  max_size            = 1
  desired_capacity    = 1
  vpc_zone_identifier = var.subnet_ids
  health_check_type   = "EC2"

  # The version number, not "$Latest": a literal never differs, so a change to the launch template (a new
  # user data, say) would leave this group unchanged and the refresh below would never replace the instance.
  launch_template {
    id      = aws_launch_template.runner.id
    version = aws_launch_template.runner.latest_version
  }

  # One instance: replace it even though that means a short gap with no runner.
  instance_refresh {
    strategy = "Rolling"

    preferences {
      min_healthy_percentage = 0
    }
  }

  tag {
    key                 = "Name"
    value               = "${var.name}-runner"
    propagate_at_launch = true
  }
}
