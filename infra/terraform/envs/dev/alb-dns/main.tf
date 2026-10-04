# The alias records that point the two dev names at the two ALBs. They live apart from the dns stack because the
# ALBs do not exist when that stack is applied: the AWS Load Balancer Controller creates them from the Ingress that
# app-deploy and app-expose install, and each gets a new DNS name whenever it is recreated (app-expose remove, then
# expose). The workflow passes the current names in; apply again after either ALB is recreated.
#
# Destroying needs no ALB: the records are removed from this stack's state.

locals {
  public_host   = "dev.${var.domain_name}"
  internal_host = "internal.dev.${var.domain_name}"
}

data "aws_route53_zone" "public" {
  name         = var.domain_name
  private_zone = false
}

data "aws_route53_zone" "internal" {
  name         = local.internal_host
  private_zone = true
}

resource "aws_route53_record" "public" {
  #checkov:skip=CKV2_AWS_23:The alias points at an ALB the AWS Load Balancer Controller creates from an Ingress, not at a Terraform resource
  count = var.public_alb_dns_name != "" ? 1 : 0

  zone_id = data.aws_route53_zone.public.zone_id
  name    = local.public_host
  type    = "A"

  alias {
    name                   = var.public_alb_dns_name
    zone_id                = var.public_alb_zone_id
    evaluate_target_health = true
  }
}

resource "aws_route53_record" "internal" {
  #checkov:skip=CKV2_AWS_23:The alias points at an ALB the AWS Load Balancer Controller creates from an Ingress, not at a Terraform resource
  count = var.internal_alb_dns_name != "" ? 1 : 0

  zone_id = data.aws_route53_zone.internal.zone_id
  name    = local.internal_host
  type    = "A"

  alias {
    name                   = var.internal_alb_dns_name
    zone_id                = var.internal_alb_zone_id
    evaluate_target_health = true
  }
}
