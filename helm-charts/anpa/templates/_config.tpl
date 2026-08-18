{{/*
Shared agent-config.yaml content — one source of truth for all 3 agents.
Each chart includes this via: {{ include "anra-common.agent-config" . }}
*/}}
{{- define "anra-common.agent-config" -}}
version: "1"
agent_role: {{ .Values.agentRole | default "anpa" | quote }}

cluster:
  name: {{ ((.Values.config).cluster).name | default "" | quote }}
  context: {{ ((.Values.config).cluster).context | default (((.Values.config).cluster).name | default "") | quote }}
  region: {{ ((.Values.config).cluster).region | default "us-west-1" | quote }}

bedrock:
  region: {{ (.Values.bedrock).region | default "us-west-2" | quote }}
  model_tier: {{ (.Values.bedrock).modelTier | default "smart" | quote }}
  {{- if (.Values.bedrock).modelOverride }}
  model_override: {{ .Values.bedrock.modelOverride | quote }}
  {{- end }}

approval:
  mode: {{ (.Values.approval).mode | default "auto" | quote }}

{{- if (.Values.config).guardrails }}
guardrails:
  {{- toYaml .Values.config.guardrails | nindent 2 }}
{{- end }}

{{- if .Values.monitoring }}
monitoring:
  influxdb_url: {{ (.Values.monitoring).influxdbUrl | default "" | quote }}
  alertmanager_url: {{ (.Values.monitoring).alertmanagerUrl | default "" | quote }}
  influxdb_org: {{ (.Values.monitoring).influxdbOrg | default "srs" | quote }}
  influxdb_bucket: {{ (.Values.monitoring).influxdbBucket | default "srsran" | quote }}
  {{- if (.Values.config).anomaly_detection }}
  anomaly_detection:
    {{- toYaml .Values.config.anomaly_detection | nindent 4 }}
  {{- end }}
{{- end }}

{{- if .Values.provisioning }}
provisioning:
  tinkerbell_namespace: {{ (.Values.tinkerbell).namespace | default "tink-system" | quote }}
  workflow_timeout: {{ (.Values.provisioning).workflowTimeout | default 1800 }}
  concurrency: {{ (.Values.provisioning).concurrency | default 3 }}
  redfish_scan_interval: {{ (.Values.inventorySync).redfishScanInterval | default 1800 }}
{{- end }}

{{- if or (.Values.gitops) (.Values.argocd) }}
deployment:
  helm_repo: {{ (.Values.deployment).helmRepo | default "" | quote }}
  gitops_repo: {{ (.Values.gitops).repoUrl | default "" | quote }}
  gitops_branch: {{ (.Values.gitops).branch | default "main" | quote }}
  nf_catalog_path: {{ (.Values.deployment).nfCatalogPath | default "/etc/anda/catalog/catalog.yaml" | quote }}
  argocd_url: {{ (.Values.argocd).serverUrl | default "http://argocd-server.argocd.svc:80" | quote }}
  argocd_namespace: {{ (.Values.argocd).namespace | default "argocd" | quote }}
{{- end }}

topology:
  provider: {{ ((.Values.config).topology).provider | default "yaml" | quote }}
  emit_service_topology: {{ ((.Values.config).topology).emitServiceTopology | default true }}
  {{- if ((.Values.config).topology).endpoint }}
  endpoint: {{ .Values.config.topology.endpoint | quote }}
  {{- end }}

{{- if (.Values.config).nodes }}
nodes:
  {{- toYaml .Values.config.nodes | nindent 2 }}
{{- end }}

{{- if (.Values.config).alarms }}
alarms:
  {{- toYaml .Values.config.alarms | nindent 2 }}
{{- end }}
{{- end }}
