output "records" {
  description = "The names that now point at an ALB."
  value = concat(
    aws_route53_record.public[*].fqdn,
    aws_route53_record.internal[*].fqdn,
  )
}
