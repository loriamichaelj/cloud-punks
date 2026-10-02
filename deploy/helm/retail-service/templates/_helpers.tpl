{{- define "retail.name" -}}
{{- default .Release.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "retail.labels" -}}
app.kubernetes.io/name: {{ include "retail.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/part-of: retail-platform
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{- define "retail.selectorLabels" -}}
app.kubernetes.io/name: {{ include "retail.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/* repo@digest when image.digest is set (promotion pins what was tested), otherwise repo:tag. */}}
{{- define "retail.image" -}}
{{- if .Values.image.digest -}}
{{- required "image.repository is required" .Values.image.repository -}}@{{- .Values.image.digest -}}
{{- else -}}
{{- required "image.repository is required" .Values.image.repository -}}:{{- required "image.tag is required (the deploy target sets it)" .Values.image.tag -}}
{{- end -}}
{{- end -}}

{{/* Hardened container settings, shared by the Deployment and the migration Job. */}}
{{- define "retail.podSecurityContext" -}}
runAsNonRoot: true
runAsUser: {{ .Values.securityContext.runAsUser }}
runAsGroup: {{ .Values.securityContext.runAsGroup }}
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{- define "retail.containerSecurityContext" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: ["ALL"]
{{- end -}}

{{- define "retail.secretEnv" -}}
{{- range . }}
- name: {{ .name }}
  valueFrom:
    secretKeyRef:
      name: {{ .secret }}
      key: {{ .key }}
{{- end }}
{{- end -}}
