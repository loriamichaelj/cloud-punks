# Names and certificates for the two dev ALBs (DESIGN.md section 13). Nothing here depends on the ALBs: the AWS
# Load Balancer Controller creates them from the Ingress, and the alias records that point at them are the alb-dns
# stack. Apply this one first, after the platform stack, so the certificate is issued before the Ingress asks for it.
#
# The domain and its public hosted zone are created by registering the domain in the Route 53 console, by hand, so
# this stack only reads the zone. Destroying it can never remove the domain's name servers.

locals {
  public_host   = "dev.${var.domain_name}"
  internal_host = "internal.dev.${var.domain_name}"
}

data "aws_route53_zone" "public" {
  name         = var.domain_name
  private_zone = false
}

data "aws_vpc" "this" {
  tags = { Name = var.name }
}

# One public certificate for both names. The internal ALB is reached only from inside the VPC, but ACM can only
# validate a public name over public DNS, so the validation records for both names live in the public zone. ACM
# renews it by itself for as long as those records stay.
resource "aws_acm_certificate" "dev" {
  domain_name               = local.public_host
  subject_alternative_names = [local.internal_host]
  validation_method         = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "validation" {
  for_each = {
    for o in aws_acm_certificate.dev.domain_validation_options : o.domain_name => {
      name   = o.resource_record_name
      type   = o.resource_record_type
      record = o.resource_record_value
    }
  }

  zone_id         = data.aws_route53_zone.public.zone_id
  name            = each.value.name
  type            = each.value.type
  records         = [each.value.record]
  ttl             = 60
  allow_overwrite = true
}

# Waits until the certificate is ISSUED, so a later `app-deploy` finds it.
resource "aws_acm_certificate_validation" "dev" {
  certificate_arn         = aws_acm_certificate.dev.arn
  validation_record_fqdns = [for r in aws_route53_record.validation : r.fqdn]
}

# The internal name exists only inside the VPC: a private zone has no public name servers, so from outside the
# name does not resolve at all. The alias to the internal ALB is the alb-dns stack.
resource "aws_route53_zone" "internal" {
  #checkov:skip=CKV2_AWS_39:Query logging is for public zones; this private zone holds one alias record inside the VPC
  #checkov:skip=CKV2_AWS_38:DNSSEC signing applies to public hosted zones
  name    = local.internal_host
  comment = "Internal ALB name for dev (${var.name}), visible inside the VPC only"

  vpc {
    vpc_id = data.aws_vpc.this.id
  }
}
