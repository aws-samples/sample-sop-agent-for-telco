{{/*
Common labels for all ANRA platform components.
*/}}
{{- define "anra-common.labels" -}}
app.kubernetes.io/part-of: anra-platform
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end }}

{{/*
Selector labels — use in sub-chart deployments.
Usage: {{ include "anra-common.selectorLabels" (dict "name" "anpa" "instance" .Release.Name) }}
*/}}
{{- define "anra-common.selectorLabels" -}}
app.kubernetes.io/name: {{ .name }}
app.kubernetes.io/instance: {{ .instance }}
{{- end }}

{{/*
Namespace helper — resolves to override or default.
*/}}
{{- define "anra-common.namespace" -}}
{{- default "anra-system" .Values.namespace.name -}}
{{- end }}
