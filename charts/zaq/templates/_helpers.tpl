{{- define "zaq.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "zaq.fullname" -}}
{{- default (printf "%s-%s" .Release.Name (include "zaq.name" .)) .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "zaq.selectorLabels" -}}
app.kubernetes.io/name: {{ include "zaq.name" . | quote }}
app.kubernetes.io/instance: {{ .Release.Name | quote }}
{{- end -}}

{{- define "zaq.labels" -}}
{{ include "zaq.selectorLabels" . }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | quote }}
app.kubernetes.io/version: {{ include "zaq.appVersion" . | replace "+" "_" | trunc 63 | trimSuffix "-" | trimSuffix "." | trimSuffix "_" | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "zaq.appVersion" -}}
{{- $pattern := `^v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-(0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)(\.(0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?(\+[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?$` -}}
{{- $tagIsVersion := regexMatch $pattern .Values.image.tag -}}
{{- $version := trimPrefix "v" .Values.image.tag -}}
{{- if or .Values.image.digest (not $tagIsVersion) -}}
  {{- $version = trimPrefix "v" (required "image.appVersion is required for digest or non-semantic tags" .Values.image.appVersion) -}}
{{- else if .Values.image.appVersion -}}
  {{- if ne (trimPrefix "v" .Values.image.appVersion) $version -}}
    {{- fail "image.appVersion conflicts with image.tag" -}}
  {{- end -}}
{{- end -}}
{{- if not (regexMatch $pattern $version) -}}{{- fail "image version must be a full semantic version" -}}{{- end -}}
{{- $minimum := index .Chart.Annotations "zaq.ai/min-app-version" -}}
{{- if not (semverCompare (printf ">=%s-0" $minimum) $version) -}}
  {{- fail (printf "ZAQ image version %s is below minimum %s" $version $minimum) -}}
{{- end -}}
{{/* Prereleases of the minimum release must not bypass the stable minimum. */}}
{{- if and (eq (printf "%d.%d.%d" (semver $version).Major (semver $version).Minor (semver $version).Patch) $minimum) (ne (semver $version).Prerelease "") -}}
  {{- fail (printf "ZAQ image version %s is below stable minimum %s" $version $minimum) -}}
{{- end -}}
{{- $version -}}
{{- end -}}

{{- define "zaq.image" -}}
{{- if .Values.image.digest -}}
{{ printf "%s@%s" .Values.image.repository .Values.image.digest }}
{{- else -}}
{{ printf "%s:%s" .Values.image.repository .Values.image.tag }}
{{- end -}}
{{- end -}}

{{- define "zaq.databaseIdentity" -}}
{{- $root := .root -}}
{{- $base := regexReplaceAll "[^a-z0-9_]" (lower (printf "%s_%s" $root.Release.Namespace $root.Release.Name)) "_" | trunc 36 -}}
{{- $hash := printf "%s/%s" $root.Release.Namespace $root.Release.Name | sha256sum | trunc 10 -}}
{{- $suffix := .kind -}}
{{- default (printf "zaq_%s_%s_%s" $base $hash $suffix) (index $root.Values.database .kind) -}}
{{- end -}}

{{- define "zaq.serviceAccount" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "zaq.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- required "serviceAccount.name is required when create=false" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "zaq.preflightName" -}}
{{- $name := include "zaq.fullname" . -}}
{{- if gt (len $name) 53 -}}
{{- printf "%s-%s-preflight" ($name | trunc 44 | trimSuffix "-") ($name | sha256sum | trunc 8) -}}
{{- else -}}
{{- printf "%s-preflight" $name -}}
{{- end -}}
{{- end -}}

{{- define "zaq.validate" -}}
{{- $_ := include "zaq.appVersion" . -}}
{{- if and .Values.preflight.enabled (le (int .Values.preflight.activeDeadlineSeconds) (int .Values.preflight.connectTimeoutSeconds)) -}}
  {{- fail "preflight.activeDeadlineSeconds must exceed preflight.connectTimeoutSeconds" -}}
{{- end -}}
{{- if .Values.database.provisioning.enabled -}}
  {{- $_ := required "database.provisioning.existingSecret is required" .Values.database.provisioning.existingSecret -}}
  {{- $_ := required "secrets.keys.readerPassword is required for provisioning" .Values.secrets.keys.readerPassword -}}
  {{- if ne (int .Values.replicaCount) 1 -}}{{- fail "automatic provisioning requires replicaCount=1; provision externally before scaling" -}}{{- end -}}
  {{- if ne .Values.strategy.type "Recreate" -}}{{- fail "automatic provisioning requires strategy.type=Recreate" -}}{{- end -}}
{{- end -}}
{{- if eq (include "zaq.databaseIdentity" (dict "root" . "kind" "owner")) (include "zaq.databaseIdentity" (dict "root" . "kind" "reader")) -}}
  {{- fail "database.owner and database.reader must be distinct" -}}
{{- end -}}
{{- range $kind := list "name" "owner" "reader" -}}
  {{- $identity := include "zaq.databaseIdentity" (dict "root" $ "kind" $kind) -}}
  {{- if or (hasPrefix "pg_" $identity) (has $identity (list "postgres" "template0" "template1" "public")) -}}
    {{- fail (printf "database.%s uses a reserved identity" $kind) -}}
  {{- end -}}
{{- end -}}
{{- if and (eq .Values.strategy.type "Recreate") .Values.strategy.rollingUpdate -}}
  {{- fail "strategy.rollingUpdate is only valid with RollingUpdate" -}}
{{- end -}}
{{- if and .Values.persistence.existingClaim (not .Values.persistence.enabled) -}}{{- fail "existingClaim requires persistence.enabled=true" -}}{{- end -}}
{{- if and .Values.persistence.existingClaim (ne .Values.persistence.storageClass nil) -}}{{- fail "existingClaim cannot be combined with storageClass; configure the existing PVC externally" -}}{{- end -}}
{{- if and (gt (int .Values.replicaCount) 1) .Values.persistence.enabled (not (has "ReadWriteMany" .Values.persistence.accessModes)) -}}
  {{- fail "multiple replicas with persistence require ReadWriteMany and externally coordinated migrations" -}}
{{- end -}}
{{- if and .Values.ingress.enabled (ne .Values.ingress.host .Values.app.host) -}}{{- fail "ingress.host must match app.host" -}}{{- end -}}
{{- if .Values.ingress.tlsEnabled -}}
  {{- if not .Values.ingress.tlsSecretName -}}{{- fail "ingress.tlsSecretName is required when ingress.tlsEnabled=true" -}}{{- end -}}
  {{- if .Values.ingress.tls -}}{{- fail "ingress.tls cannot be combined with ingress.tlsEnabled=true; choose simple TLS or the advanced list" -}}{{- end -}}
{{- end -}}
{{- if hasKey .Values.persistence.annotations "helm.sh/resource-policy" -}}{{- fail "use persistence.retain instead of the resource-policy annotation" -}}{{- end -}}
{{- end -}}

{{- define "zaq.databaseEnv" -}}
- name: PGHOST
  value: {{ .Values.database.host | quote }}
- name: PGPORT
  value: {{ .Values.database.port | quote }}
- name: ZAQ_DATABASE
  value: {{ include "zaq.databaseIdentity" (dict "root" . "kind" "name") | quote }}
- name: ZAQ_OWNER
  value: {{ include "zaq.databaseIdentity" (dict "root" . "kind" "owner") | quote }}
- name: ZAQ_OWNER_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secrets.existingSecret | quote }}
      key: {{ .Values.secrets.keys.ownerPassword | quote }}
{{- end -}}

{{- define "zaq.applicationSecretEnv" -}}
{{- range $env, $key := dict "SECRET_KEY_BASE" "secretKeyBase" "SYSTEM_CONFIG_ENCRYPTION_KEY" "encryptionKey" }}
- name: {{ $env }}
  valueFrom:
    secretKeyRef:
      name: {{ $.Values.secrets.existingSecret | quote }}
      key: {{ index $.Values.secrets.keys $key | quote }}
{{- end -}}
{{- end -}}

{{- define "zaq.provisioningSecretEnv" -}}
- name: PGUSER
  valueFrom:
    secretKeyRef:
      name: {{ .Values.database.provisioning.existingSecret | quote }}
      key: {{ .Values.database.provisioning.keys.username | quote }}
- name: PGPASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ .Values.database.provisioning.existingSecret | quote }}
      key: {{ .Values.database.provisioning.keys.password | quote }}
- name: ZAQ_READER_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secrets.existingSecret | quote }}
      key: {{ .Values.secrets.keys.readerPassword | quote }}
{{- end -}}
