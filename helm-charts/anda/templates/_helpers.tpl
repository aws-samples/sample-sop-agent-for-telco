{{- define "anda.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "anda.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "anda.labels" -}}
app.kubernetes.io/part-of: anra-platform
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
app.kubernetes.io/name: {{ include "anda.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: deployment
{{- end }}

{{- define "anda.selectorLabels" -}}
app.kubernetes.io/name: {{ include "anda.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "anda.secretName" -}}
{{- .Values.credentials.existingSecret | default (printf "%s-secrets" (include "anda.fullname" .)) -}}
{{- end }}
