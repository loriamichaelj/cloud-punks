output "namespace" {
  value = kubernetes_namespace_v1.retail.metadata[0].name
}

output "lbc_role_arn" {
  value = module.lbc_role.role_arn
}

output "eso_role_arn" {
  value = module.eso_role.role_arn
}

output "helm_releases" {
  value = {
    lbc = "${helm_release.lbc.chart} ${helm_release.lbc.version}"
    eso = "${helm_release.eso.chart} ${helm_release.eso.version}"
  }
}
