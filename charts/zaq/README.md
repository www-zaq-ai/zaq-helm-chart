# ZAQ OS

[ZAQ OS](https://github.com/www-zaq-ai/zaq) is a collaborative agentic operating
system for people, AI agents, and organizational knowledge. This chart deploys
an isolated instance with persistent storage and optional HTTPS ingress, using
an **external PostgreSQL server** and **pre-existing Kubernetes Secrets**.
The default and minimum supported image version is **ZAQ v0.19.1**.
Chart and application versions are independent.

## Before installing

- Kubernetes 1.31+, Helm v3, Linux AMD64/ARM64 nodes, and image-pull access.
- PostgreSQL 16+ with pgvector >= 0.7.0 (`halfvec`) installed on the server.
  The server may be outside Kubernetes or in another namespace.
- For automatic bootstrap, a superuser DBA account. Otherwise prepare the
  database/owner externally and disable provisioning.
- **ZAQ v0.19.1 requires cluster-wide `CREATEROLE` for the application owner.**
  This is role-administration capability, not schema isolation. Review shared
  PostgreSQL trust boundaries with the DBA before deploying.
- Create a deployment Secret in the release namespace with `owner-password`,
  `secret-key-base`, and `encryption-key`; add `reader-password` for provisioning.
  The encryption key must represent exactly 32 bytes; Base64 is recommended.
- With provisioning enabled, also create/select a DBA Secret with `username`
  and `password`. Names/key mappings are configurable. **Never put credential
  values in Helm values or the Rancher form.** Secret creation stays external.
- An existing StorageClass or compatible PVC, and for ingress, an Ingress
  controller, DNS, and TLS certificate Secret/integration.

## Example configuration

Adapt these non-sensitive settings to your resources:

```yaml
secrets:
  existingSecret: customer-a-runtime
database:
  host: postgres.database.svc.cluster.local
  name: customer_a
  owner: customer_a_owner
  reader: customer_a_reader
  provisioning:
    existingSecret: postgres-dba
preflight:
  enabled: true
persistence:
  storageClass: longhorn
  size: 20Gi
app:
  host: zaq.example.org
ingress:
  enabled: true
  className: nginx
  host: zaq.example.org
  tlsEnabled: true
  tlsSecretName: customer-a-tls
```

Replace `longhorn` and `nginx` with your cluster's actual classes. For PVC reuse,
set `persistence.existingClaim` and leave `storageClass` null/unset. Files mount
at `/zaq/volumes`; UID 1000 needs write access. PVCs are retained by default.

Rancher 2.10.3 users can enable **Avatar → Preferences → Helm Charts → Include
Prerelease Versions** to see test charts. The packaged `questions.yaml` provides
common configuration fields; use Values YAML for advanced settings and review
it before installation. Secret selectors select **names**, never secret values.

The form prefills editable NGINX annotations for `50M` body-size limits and
`"3600"`-second ingress-nginx read/send timeouts. Override individual defaults
or add other annotations; each controller applies the annotations it supports.
The form also includes an **Enable TLS** checkbox
with a **TLS Secret name** field. TLS uses the Ingress hostname automatically.
Reference an existing namespace-local TLS Secret, or use an installed,
configured cert-manager with an issuer annotation (for example,
`cert-manager.io/cluster-issuer: letsencrypt-prod`) to issue and renew it.
The chart does not generate certificates or install cert-manager; configure
DNS/challenges externally. HTTPS terminates at the Ingress controller, with
HTTP to ZAQ's ClusterIP Service. Helm readiness does not verify HTTPS/issuance.

For advanced TLS lists, use `ingress.tls` in Values YAML and keep
`ingress.tlsEnabled: false`; enabling the checkbox with a nonempty list is
rejected. Unchecking it leaves advanced-list TLS active if configured. The TLS
Secret name alone is ignored with the checkbox off.

## Database TLS

The default v0.19.1 image includes verified application TLS. It remains opt-in:
enable `database.tls.enabled` for application, provisioning and preflight without
a separate image-support confirmation.
This uses verified TLS with no plaintext fallback. With no CA Secret, it uses system
trust; private CAs need `database.tls.ca.existingSecret` and `key` (default
`ca.crt`). These fields are in Rancher's **Database TLS** group.

The CA can live in the **existing DBA Secret**. Only that CA key is projected
read-only; DBA username/password keys are never mounted into the application.
Provisioning-disabled deployments can select the CA independently. Application
TLS settings also reach the init container's application-owner URL check.
Provisioning DBA/reader and preflight share `database.tls.libpqMode`, default
`verify-full` (chain and hostname verification). The selector appears only with
TLS enabled and also supports `verify-ca` (chain only) and `require` (encryption,
without guaranteed hostname verification). These modes never weaken application
TLS. All clients share the CA bundle, or system trust for verification. With TLS
off, every client uses plaintext and no CA is mounted; the mode is ignored.

Custom images must preserve v0.19.1's TLS implementation and helper. See the
[full TLS guide](https://github.com/www-zaq-ai/zaq-helm-chart/blob/main/docs/database-tls.md)
for version requirements and Secret/CA rotation behavior.

When upgrading an earlier test chart, remove `image.databaseTlsSupported` from
saved values. That redundant setting was removed and the strict schema rejects
it. Custom images remain responsible for implementing their declared version.

Also remove `database.provisioning.sslMode` and `preflight.sslMode` from saved
values. Unlike their earlier `prefer` defaults, TLS off now means plaintext
only. Enable the switch explicitly for a TLS-required server.

Rancher may inject `global.cattle` metadata after its Edit YAML view. The chart
accepts an optional `global` object with arbitrary children without using it to
configure ZAQ. Other root fields and application settings remain strictly
validated. No credential values belong in `global` or other Helm values.

## Additional application environment variables

Rancher's **Application** group includes a non-sensitive key/value editor for
`app.extraEnv`. For example, set `REQ_LLM_POOL_SIZE` to the string `"8"`.
Only settings supported by your selected ZAQ image affect its behavior.
Never enter credentials here: literal values are stored in Helm release records.
For sensitive settings, use **Values YAML** with `app.extraEnvSecrets`:

```yaml
app:
  extraEnvSecrets:
    - name: MY_API_TOKEN
      secretKeyRef:
        name: integration-secrets
        key: api-token
```

Secrets must already exist in the release namespace. Variables reach only ZAQ,
not provisioning/preflight. Reserved chart/bootstrap names, duplicate variables,
and references to the configured DBA Secret or runtime reader-password key are
rejected. A missing custom Secret/key blocks application startup; preflight does
not inspect these custom references. Configuration edits trigger a Pod rollout;
Secret data changes alone need a restart. See the
[full rules](https://github.com/www-zaq-ai/zaq-helm-chart/blob/main/docs/values.md#custom-environment-variables).

## Prerequisite preflight (optional, off by default)

The `preflight.enabled` hook runs before install/upgrade. It references required
Secret keys and executes a bounded, read-only connectivity/authentication query:
DBA → maintenance DB when provisioning is enabled; owner → target DB otherwise.
The target database/owner/reader need not exist before automatic bootstrap.

The default Job deadline is 120 seconds, including image pulls and scheduling.
Missing Secrets/keys prevent container
startup: inspect Pod events in Rancher; no custom container log can exist yet.
The deadline eventually fails the Job and Helm hook. Successful hooks are removed;
failed hooks remain until their one-hour TTL or the next attempt. Set the Helm
timeout longer than the Job deadline plus scheduling/termination allowance.

Preflight does not provision, run migrations, inspect external DB workloads,
validate key contents, or grant Kubernetes API access. Actual startup remains
authoritative. Secrets alone must be in the release namespace, not PostgreSQL.
The installer needs permission to manage Jobs; the Job container needs no API
token/RBAC.

## Important deployment constraints

- When upgrading from v0.18.0, stop ZAQ/migrators and arrange the
  [upstream DBA maintenance](https://github.com/www-zaq-ai/zaq/blob/v0.19.1/docs/database-setup.md#enable-owner-managed-logins-on-an-existing-deployment)
  before normal v0.19.1 startup: approve/grant owner `CREATEROLE` and, when
  `pg_search` is installed, `pdb` USAGE with grant option. Existing receipts
  reject the old privilege contract; Helm never repairs it or bypasses ledgers.
- **Application TLS is separate from preflight/init-container libpq modes.**
  Configure both explicitly as needed. TLS is opt-in even though v0.19.1
  supports it; use a trusted database network while application TLS is disabled.
- ZAQ seeds an initial `admin`/`admin` Back Office account with mandatory password
  change. Restrict public access until setup at `/bo/login` is complete.
- Keep encryption keys stable. Changing a Secret does not rotate DB passwords.
- The terminating provisioning init container and PostgreSQL receipts remain
  authoritative, followed by migrations-before-server startup. Do not bypass
  receipt, ownership, or migration-ledger guards. Default: one replica/Recreate.
- Use Helm `--wait --timeout 20m`; health is HTTP `/channels/health` with
  `X-Forwarded-Proto: https`, not a database/provider check. Rollback does not
  undo schema changes; back up PostgreSQL, files, and key-management records.

## Detailed guides

- [Deployment and Secrets](https://github.com/www-zaq-ai/zaq-helm-chart/blob/main/docs/deployment.md)
- [Rancher](https://github.com/www-zaq-ai/zaq-helm-chart/blob/main/docs/rancher.md)
- [Storage](https://github.com/www-zaq-ai/zaq-helm-chart/blob/main/docs/storage.md)
- [Operations and preflight](https://github.com/www-zaq-ai/zaq-helm-chart/blob/main/docs/operations.md)
- [Values reference](https://github.com/www-zaq-ai/zaq-helm-chart/blob/main/docs/values.md)
- [Production/test releases](https://github.com/www-zaq-ai/zaq-helm-chart/blob/main/docs/releases.md)

## Branding

The icon links to the unmodified PNG used by ZAQ's own login and Back Office,
pinned to the v0.18.0 source commit; it is not copied into this package.
Upstream copyright belongs to ZAQ / www-zaq-ai. See its
[NOTICE](https://github.com/www-zaq-ai/zaq/blob/eb5e422eee3d96268bf8cd968750baa54a529f97/NOTICE)
and [AGPLv3 license](https://github.com/www-zaq-ai/zaq/blob/eb5e422eee3d96268bf8cd968750baa54a529f97/LICENSE).
This reference identifies the application; it does not grant trademark rights
or imply a separate commercial license.
