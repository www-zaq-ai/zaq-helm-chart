# Configurable values

Defaults are in [`values.yaml`](../charts/zaq/values.yaml), validated by
[`values.schema.json`](../charts/zaq/values.schema.json). Unknown top-level and
configuration keys are rejected. Kubernetes security contexts, affinity,
tolerations, and resources remain extensible maps with native Kubernetes shapes.
Do not put credentials in any value.

## Names and image

- `nameOverride`: `""`; replace chart-name portion of resource names.
- `fullnameOverride`: `""`; replace the full resource name.
- `replicaCount`: `1`; automatic provisioning requires exactly one replica.
- `strategy.type`: `Recreate`; also supports `RollingUpdate` only when
  provisioning is disabled.
- `strategy.rollingUpdate`: optional native `maxSurge`/`maxUnavailable` settings;
  omit with `Recreate`.
- `image.repository`: `ghcr.io/www-zaq-ai/zaq`.
- `image.tag`: `v0.18.0`; preserved exactly for image pulling.
- `image.digest`: `""`; optional `sha256:…`, takes precedence over tag.
- `image.pullPolicy`: `IfNotPresent`; also `Always` or `Never`.
- `image.appVersion`: `""`; required full semantic version for digests or
  non-semantic tags. An optional leading `v` is accepted. Minimum `0.18.0`.
- `imagePullSecrets`: `[]`; native list of `{name: existing-secret}` references.

## Existing Secrets

- `secrets.existingSecret`: `zaq-runtime`; one existing Secret per deployment.
- `secrets.keys.ownerPassword`: `owner-password`.
- `secrets.keys.readerPassword`: `reader-password`; required with provisioning.
- `secrets.keys.secretKeyBase`: `secret-key-base`.
- `secrets.keys.encryptionKey`: `encryption-key`.

All names/keys refer to the release namespace. The chart never reads their
contents or creates Secret resources. See
[Secret requirements](deployment.md#pre-existing-secrets) for their contents.

## PostgreSQL

- `database.host`: `postgresql`; DNS name or IPv4 address. Use DNS for IPv6
  servers; IPv6 literals are not supported by the upstream URL constructor.
- `database.port`: `5432`.
- `database.name`: `""`; release/namespace-derived database identity.
- `database.owner`: `""`; release/namespace-derived owner login.
- `database.reader`: `""`; release/namespace-derived reader login.
- `database.poolSize`: `10`; application Ecto connection pool size.
- `database.ipv6`: `false`; set `ECTO_IPV6` for application DNS connections.
- `database.provisioning.enabled`: `true`; add terminating provisioning init.
- `database.provisioning.existingSecret`: `zaq-dba`; existing DBA Secret.
- `database.provisioning.keys.username`: `username`; DBA login key.
- `database.provisioning.keys.password`: `password`; DBA password key.
- `database.provisioning.maintenanceDatabase`: `postgres`; DBA connection DB.
- `database.provisioning.engine`: `auto`; also `postgres` or `paradedb`.
- `database.provisioning.sslMode`: `prefer`; libpq **init-only** TLS mode;
  also `disable`, `allow`, or `require`. This does not enable application TLS
  or offer verified certificate validation.
- `database.provisioning.resources.requests`: CPU `100m`, memory `256Mi`.
- `database.provisioning.resources.limits`: CPU `1`, memory `512Mi`.
- `database.provisioning.securityContext`: `allowPrivilegeEscalation: false`,
  drop capability `ALL`, `readOnlyRootFilesystem: false`; configurable native map.

Explicit database/role names use lowercase letters, digits and underscores,
start with a letter/underscore, and are at most 63 characters. Reserved names
are rejected. Empty defaults include a hash of the exact namespace/release;
renaming a release/namespace changes those defaults. Pin identities explicitly
before migrating or renaming an existing installation.

## Application and security

- `app.host`: `zaq.example.com`; public hostname, must match enabled Ingress.
- `app.encryptionKeyId`: `v1`; encryption-key rotation metadata, not key material.
- `app.workflowsEnabled`: `true`.
- `serviceAccount.create`: `true`; create a dedicated account.
- `serviceAccount.name`: `""`; generated when creating; required when reusing.
- `serviceAccount.annotations`: `{}`.
- `podAnnotations`: `{}`; for example an operator-controlled restart marker.
- `podSecurityContext.runAsNonRoot`: `true`.
- `podSecurityContext.runAsUser`: `1000`.
- `podSecurityContext.fsGroup`: `1000`; supplemental storage group.
- `podSecurityContext.fsGroupChangePolicy`: `OnRootMismatch`.
- `podSecurityContext.seccompProfile.type`: `RuntimeDefault`.
- `securityContext.allowPrivilegeEscalation`: `false`.
- `securityContext.capabilities.drop`: `[ALL]`.
- `securityContext.readOnlyRootFilesystem`: `false`; the image writes under
  `/app`, including browser tooling. Do not enable without compatible mounts/image.
- `resources.requests`: CPU `250m`, memory `1Gi`.
- `resources.limits`: CPU `2`, memory `2Gi`.
- `terminationGracePeriodSeconds`: `60`.
- `nodeSelector`: `{}`; native node-label map.
- `tolerations`: `[]`; native toleration objects.
- `affinity`: `{}`; native affinity configuration.

Pod security context, container security contexts, and resource maps support
native Kubernetes fields. Empty maps remove optional defaults through Helm
merging only when their entries are explicitly cleared as appropriate. Token
automounting is always disabled on the Pod and any chart-created ServiceAccount.

## Prerequisite preflight

- `preflight.enabled`: `false`; optional pre-install/pre-upgrade Job.
- `preflight.activeDeadlineSeconds`: `120`; overall Job deadline, 15–600 seconds.
- `preflight.connectTimeoutSeconds`: `10`; bounded libpq/query process timeout,
  1–30 seconds, strictly less than the Job deadline.
- `preflight.ttlSecondsAfterFinished`: `3600`; failed Job retention, 60–86400
  seconds. Successful hooks are deleted immediately; previous hooks are removed
  before a retry.
- `preflight.sslMode`: `prefer`; libpq-only, also `disable`, `allow`, `require`.
  This does not secure the application's separate Ecto connection.
- `preflight.resources.requests`: CPU `100m`, memory `128Mi`.
- `preflight.resources.limits`: CPU `500m`, memory `256Mi`.
- `preflight.securityContext`: privilege escalation disabled, capabilities
  dropped, `readOnlyRootFilesystem: true`; configurable native map.

Reuses image/pull Secrets, Pod security context, node selector, tolerations and
affinity settings. Required Secrets stay externally managed and namespace-local.
See [behavior, missing-key errors, and cleanup](operations.md#optional-prerequisite-preflight).

## Storage

- `persistence.enabled`: `true`; false uses ephemeral `emptyDir`.
- `persistence.existingClaim`: `""`; existing PVC name, no PVC is created.
- `persistence.storageClass`: `null`; omitted for cluster default, `""` for no
  class, or an existing class name. Must be omitted/null with existingClaim.
- `persistence.accessModes`: `[ReadWriteOnce]`; native PVC access modes.
- `persistence.size`: `10Gi`; positive integer with binary unit, for new PVCs.
- `persistence.retain`: `true`; add Helm keep annotation to new PVCs.
- `persistence.annotations`: `{}`; annotations on new PVCs. Use `retain` rather
  than manually setting `helm.sh/resource-policy`.

Size, access modes and annotations are not applied to externally managed PVCs.
For multiple replicas, the operator must set accessModes to ReadWriteMany and
verify the actual existing claim supports it. No volume is shared with the init.

## Service and Ingress

- `service.port`: `4000`; ClusterIP Service port; container always uses `4000`.
- `ingress.enabled`: `false`.
- `ingress.className`: `""`; omit to use controller defaults.
- `ingress.annotations`: editable string key/value settings in Rancher's form.
  Defaults (additional annotations are merged; individual defaults can be
  overridden):
  - `nginx.ingress.kubernetes.io/proxy-body-size`: `"50M"`.
  - `nginx.org/client-max-body-size`: `"50M"`.
  - `nginx.ingress.kubernetes.io/proxy-read-timeout`: `"3600"` seconds.
  - `nginx.ingress.kubernetes.io/proxy-send-timeout`: `"3600"` seconds.
- `ingress.host`: `zaq.example.com`; must match `app.host` when enabled.
- `ingress.path`: `/`.
- `ingress.pathType`: `Prefix`; also `Exact` or `ImplementationSpecific`.
- `ingress.tlsEnabled`: `false`; simple TLS checkbox. When true, renders one TLS
  entry using `ingress.host` and requires `ingress.tlsSecretName`.
- `ingress.tlsSecretName`: `""`; namespace-local TLS Secret name, either existing
  or created externally by cert-manager. Ignored when the checkbox is off.
- `ingress.tls`: `[]`; advanced list of
  `{secretName: existing-tls, hosts: [hostname]}`. Keep `tlsEnabled: false` to
  use this list; a nonempty list conflicts with `tlsEnabled: true`.

TLS settings never create Secrets/certificates. Issuance/renewal stays external;
see [Rancher configuration](rancher.md#ingress-annotations-and-tls). With Ingress
disabled, no Ingress is rendered even if TLS settings are retained. A true
`tlsEnabled` still requires a valid Secret name and empty advanced list.

## Health probes

All enabled probes use HTTP `/channels/health`, named port `http`, and the
`X-Forwarded-Proto: https` header. The endpoint is not a database health check.

- `probes.startup.enabled`: `true`.
- `probes.startup.periodSeconds`: `10`.
- `probes.startup.timeoutSeconds`: `5`.
- `probes.startup.failureThreshold`: `90`.
- `probes.readiness.enabled`: `true`.
- `probes.readiness.periodSeconds`: `10`.
- `probes.readiness.timeoutSeconds`: `5`.
- `probes.readiness.failureThreshold`: `3`.
- `probes.liveness.enabled`: `true`.
- `probes.liveness.periodSeconds`: `20`.
- `probes.liveness.timeoutSeconds`: `5`.
- `probes.liveness.failureThreshold`: `3`.
