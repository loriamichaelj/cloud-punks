output "public_host" {
  description = "The viewer ALB's name."
  value       = local.public_host
}

output "internal_host" {
  description = "The internal ALB's name, resolvable only inside the VPC."
  value       = local.internal_host
}

output "certificate_arn" {
  description = "The issued certificate. The load balancer controller finds it by the Ingress's tls host, so nothing needs to pass this on; it is here to look at."
  value       = aws_acm_certificate_validation.dev.certificate_arn
}

output "internal_zone_id" {
  value = aws_route53_zone.internal.zone_id
}
