# ZAQ OS

[ZAQ OS](https://github.com/www-zaq-ai/zaq) is a collaborative agentic operating
system for people, AI agents, and organizational knowledge. This chart deploys
an isolated instance with persistent storage and optional HTTPS ingress, using
an **external PostgreSQL server** and **pre-existing Kubernetes Secrets**.

## Before installing

- Kubernetes 1.31+, Helm v3, Linux AMD64/ARM64 nodes, and image-pull access.
- PostgreSQL 16+ with pgvector >= 0.7.0 (`halfvec`) installed on the server.
  The server may be outside Kubernetes or in another namespace.
- For automatic bootstrap, a superuser DBA account. Otherwise prepare the
  database/owner externally and disable provisioning.
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
  tls:
    - secretName: customer-a-tls
      hosts: [zaq.example.org]
```

Replace `longhorn` and `nginx` with your cluster's actual classes. For PVC reuse,
set `persistence.existingClaim` and leave `storageClass` null/unset. Files mount
at `/zaq/volumes`; UID 1000 needs write access. PVCs are retained by default.

Rancher 2.10.3 users can enable **Avatar → Preferences → Helm Charts → Include
Prerelease Versions** to see test charts. The packaged `questions.yaml` provides
common configuration fields; use Values YAML for advanced settings and review
it before installation. Secret selectors select **names**, never secret values.

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

- **ZAQ v0.18.0 does not enable TLS for its Ecto/application DB connection.**
  Preflight/init-container libpq TLS settings do not secure that connection.
  Use a trusted network; verified application DB TLS needs an upstream change.
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
