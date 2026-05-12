{{/*
Common labels for all resources.
*/}}
{{- define "anra.labels" -}}
app.kubernetes.io/name: anra
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels (subset of common labels).
*/}}
{{- define "anra.selectorLabels" -}}
app.kubernetes.io/name: anra
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Resolve InfluxDB URL from monitoring config.
*/}}
{{- define "anra.influxdbUrl" -}}
{{- .Values.monitoring.influxdbUrl | default "" -}}
{{- end }}

{{/*
Resolve Alertmanager URL from monitoring config.
*/}}
{{- define "anra.alertmanagerUrl" -}}
{{- .Values.monitoring.alertmanagerUrl | default "" -}}
{{- end }}
