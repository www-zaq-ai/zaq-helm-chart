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
- `image.tag`: `v0.19.1`; preserved exactly for image pulling.
- `image.digest`: `""`; optional `sha256:…`, takes precedence over tag.
- `image.pullPolicy`: `IfNotPresent`; also `Always` or `Never`.
- `image.appVersion`: `""`; required full semantic version for digests or
  non-semantic tags. An optional leading `v` is accepted. Minimum `0.19.1`.
- `imagePullSecrets`: `[]`; native list of `{name: existing-secret}` references.

Database TLS uses one `database.tls.enabled` switch; the minimum v0.19.1 official
image supports it. Custom images must implement their declared version.
The former `image.databaseTlsSupported` setting was removed: delete it from
saved values before upgrading, because the strict image schema rejects it.

## Rancher metadata

`global` is an optional object for Rancher/Helm-injected metadata such as
`global.cattle`. Its children are unrestricted and ignored by the templates.
It does not relax validation of other root fields or application settings;
never put credentials in it. See [Rancher injection](rancher.md#rancher-injected-global-values).

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
- `database.owner`: `""`; release/namespace-derived owner login. ZAQ v0.19.1
  requires cluster-wide `CREATEROLE`; it is not a schema-confined identity. See
  [the privilege/upgrade contract](deployment.md#owner-privilege-scope).
- `database.reader`: `""`; release/namespace-derived reader login.
- `database.poolSize`: `10`; application Ecto connection pool size.
- `database.ipv6`: `false`; set `ECTO_IPV6` for application DNS connections.
- `database.tls.enabled`: `false`; one switch for application, provisioning and
  preflight. Off means plaintext for all clients; on means verified application
  TLS and the shared libpq mode below. No image-support confirmation is needed.
- `database.tls.libpqMode`: `verify-full`; shared provisioning/preflight mode,
  used only when TLS is enabled. Accepts `require` (encryption), `verify-ca`
  (certificate chain), or `verify-full` (chain and hostname, recommended).
  Application TLS always verifies chain and hostname regardless of this mode.
  Without a CA Secret, `verify-ca` uses `/etc/ssl/certs/ca-certificates.crt`
  (also required in custom images); `verify-full` uses libpq's `system` shortcut.
- `database.tls.ca.existingSecret`: `""`; optional namespace-local Secret with a
  PEM CA bundle; may reuse the DBA Secret. Empty uses system trust.
- `database.tls.ca.key`: `ca.crt`; only this key is projected read-only, never
  the other keys in that Secret. Shared by all clients when TLS is enabled;
  ignored and not mounted otherwise. See [TLS rules](database-tls.md).
- `database.provisioning.enabled`: `true`; add terminating provisioning init.
- `database.provisioning.existingSecret`: `zaq-dba`; existing DBA Secret.
- `database.provisioning.keys.username`: `username`; DBA login key.
- `database.provisioning.keys.password`: `password`; DBA password key.
- `database.provisioning.maintenanceDatabase`: `postgres`; DBA connection DB.
- `database.provisioning.engine`: `auto`; also `postgres` or `paradedb`.
- `database.provisioning.resources.requests`: CPU `100m`, memory `256Mi`.
- `database.provisioning.resources.limits`: CPU `1`, memory `512Mi`.
- `database.provisioning.securityContext`: `allowPrivilegeEscalation: false`,
  drop capability `ALL`, `readOnlyRootFilesystem: false`; configurable native map.

Remove the old `database.provisioning.sslMode` and `preflight.sslMode` keys from
saved values; both are rejected by the strict schema. Their earlier `prefer`
defaults could negotiate TLS, whereas the shared switch now defaults to explicit
plaintext. See [TLS migration](database-tls.md#upgrading-saved-values).

Explicit database/role names use lowercase letters, digits and underscores,
start with a letter/underscore, and are at most 63 characters. Reserved names
are rejected. Empty defaults include a hash of the exact namespace/release;
renaming a release/namespace changes those defaults. Pin identities explicitly
before migrating or renaming an existing installation.

## Application and security

- `app.host`: `zaq.example.com`; public hostname, must match enabled Ingress.
- `app.encryptionKeyId`: `v1`; encryption-key rotation metadata, not key material.
- `app.workflowsEnabled`: `true`.
- `app.extraEnv`: `{}`; non-sensitive environment variable name → string map,
  editable in Rancher's form. Values such as numbers/booleans must be quoted.
- `app.extraEnvSecrets`: `[]`; list of
  `{name: MY_API_TOKEN, secretKeyRef: {name: integration-secrets, key: api-token}}`.
  Names/keys only; Secrets must exist in the release namespace. Configure this
  structured list in Values YAML, not the plain-text form map.
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

## Custom environment variables

Custom variables reach **only the application container**, never the provisioning
init container or preflight. They do not change the image entrypoint. For
portability, custom names must match `[A-Za-z_][A-Za-z0-9_]*`; values in `extraEnv`
must be strings. Rendering uses no Helm `tpl` evaluation; Kubernetes' normal
`$(VAR_NAME)` environment expansion still applies. Map order is deterministic.

Use `extraEnv` only for non-sensitive settings. Its values are visible in Helm
release records and rendered Deployment manifests. Sensitive values must use
individual existing `secretKeyRef` entries via `extraEnvSecrets`; no `envFrom`,
Secret generation, optional keys, or cross-namespace references are supported.
A missing custom Secret/key blocks application startup (Pod events explain the
missing reference); preflight intentionally does not check custom references.
ZAQ boot remains authoritative for supported variable names and valid contents.

Duplicate names within the Secret list or between the two sources are rejected.
The following names are reserved in **both** sources:

- Prefixes `PG`, `ZAQ_`, `RELEASE_`, `ERL_`, `ELIXIR_`, and `LD_`.
- `DATABASE_URL`, `PHX_SERVER`, `PHX_HOST`, `PORT`, `POOL_SIZE`, `ECTO_IPV6`,
  `SECRET_KEY_BASE`, `SYSTEM_CONFIG_ENCRYPTION_KEY`,
  `SYSTEM_CONFIG_ENCRYPTION_KEY_ID`, and `WORKFLOWS_ENABLED`.
- `STORAGE_VOLUMES`, `STORAGE_VOLUMES_BASE`, `INGESTION_VOLUMES`, and
  `INGESTION_VOLUMES_BASE`.
- `MIX_ENV`, `PATH`, `HOME`, `ENV`, `BASH_ENV`, `PYTHONPATH`, and `PYTHONHOME`.

Use the dedicated chart settings/managed Secret mappings for these instead.
Custom references to the configured DBA Secret or the configured runtime
reader-password key are also rejected, even under an alias and with provisioning
disabled. The chart cannot inspect Secret contents or detect copied DBA
credentials in another Secret; operators must keep those out of custom inputs.
This configuration interface is not a security boundary against release admins.

Changing either custom environment configuration changes the Pod template and
causes a rollout. Rotating the data of an externally referenced Secret alone does
not update existing container environment variables: restart the application
Pods after external rotation. This does not rotate database logins.

## Prerequisite preflight

- `preflight.enabled`: `false`; optional pre-install/pre-upgrade Job.
- `preflight.activeDeadlineSeconds`: `120`; overall Job deadline, 15–600 seconds.
- `preflight.connectTimeoutSeconds`: `10`; bounded libpq/query process timeout,
  1–30 seconds, strictly less than the Job deadline.
- `preflight.ttlSecondsAfterFinished`: `3600`; failed Job retention, 60–86400
  seconds. Successful hooks are deleted immediately; previous hooks are removed
  before a retry.
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
  The Service targets numeric port `4000`; the Ingress references the configured
  Service port numerically. The container's `http` name remains used by probes.
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
