{{- define "anra.fullname" -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end }}

{{- define "anra.labels" -}}
app.kubernetes.io/name: anra
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "anra.selectorLabels" -}}
app.kubernetes.io/name: anra
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "anra.influxdbUrl" -}}
{{- .Values.monitoring.influxdbUrl | default "" -}}
{{- end }}

{{- define "anra.alertmanagerUrl" -}}
{{- .Values.monitoring.alertmanagerUrl | default "" -}}
{{- end }}

{{- define "anra.secretName" -}}
{{- .Values.credentials.existingSecret | default (printf "%s-secrets" (include "anra.fullname" .)) -}}
{{- end }}
