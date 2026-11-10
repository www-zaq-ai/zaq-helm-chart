# Deploying ZAQ

This guide covers prerequisites, database initialization, Secrets, installation,
and initial application setup. For Rancher-specific steps, see
[Rancher installation](rancher.md). For all settings, see the
[values reference](values.md).

## Prerequisites

### Cluster and tooling

- Helm **3.18.6** is the validation baseline; Helm v3 is required.
- Kubernetes **1.31 or newer**. Manifest schemas are checked against 1.31–1.34;
  CI performs real installation tests on Kind/Kubernetes 1.34.0. This is not a
  guarantee of compatibility with every future Kubernetes version.
- A namespace and permission to create Deployments, Services, ServiceAccounts,
  PVCs, and optionally Ingresses there. Enabling preflight also requires the
  Helm/Rancher installer to manage Jobs in that namespace.
- Linux AMD64 or ARM64 nodes and access to `ghcr.io/www-zaq-ai/zaq` or a mirror.
- An existing StorageClass, cluster default, or compatible existing PVC; see
  [storage requirements](storage.md).
- The applicable credential Secrets below, created **before installation**.
- For external access: an Ingress controller, DNS, and a TLS certificate Secret
  or certificate-management integration. See [networking](operations.md#networking).

### PostgreSQL

- PostgreSQL **16+** with **pgvector >= 0.7.0**, including `halfvec`, installed
  on the server. CI uses PostgreSQL 17 with pgvector 0.8.1.
- ParadeDB is optional; its `pg_search` capability is selected by the upstream
  bootstrap implementation.
- Network access from the ZAQ Pod to PostgreSQL, using a direct primary endpoint.
- Distinct database, application-owner, and reader identities per instance.

Automatic provisioning requires a **PostgreSQL superuser DBA**. Many managed
database providers cannot grant the necessary rights: use DBA/provider-managed
provisioning and set `database.provisioning.enabled: false` instead. Extension
packages must already be installed on the server; the init container cannot
install server-side operating-system packages.

Read the upstream
[deployment](https://github.com/www-zaq-ai/zaq/blob/v0.18.0/docs/operations/deployment.md)
and [database bootstrap](https://github.com/www-zaq-ai/zaq/blob/v0.18.0/docs/database-setup.md)
contracts. This chart does not deploy a PostgreSQL server, create credentials,
create StorageClasses, or implement billing or Customer Portal integration.

## Database provisioning and startup

The optional `provision-db` **terminating init container** uses the same image as
ZAQ and runs its existing `provision-db --automatic` command. It creates or
validates the database, owner login, reader login, extensions, and permissions.
The chart does not duplicate ZAQ's SQL.

After initialization succeeds, the application constructs its database URL
using the supplied owner password, runs migrations, then starts on HTTP port
`4000`. Credentials containing URI punctuation are encoded by ZAQ's entrypoint.
The owner needs DDL privileges for migrations and runtime operations. The reader
has read-only privileges, including default grants for future owner-created
tables; it is not the application's runtime account.

A PostgreSQL bootstrap receipt makes subsequent Pod creation validation-only;
it does not reset passwords. The init container is stateless and does not mount
application storage. Application-container restarts in the same Pod do not
normally rerun an already completed init container.

An existing migrated database without a matching receipt requires the upstream
explicit adoption/repair procedure or provisioning-disabled deployment. Do not
delete receipts or migration ledgers to force bootstrap.

### Identity and replica safety

Empty `database.name`, `database.owner`, and `database.reader` derive stable
identities from namespace/release plus a hash, avoiding truncation collisions.
Set explicit identities in production (see
[`examples/production.yaml`](../examples/production.yaml)) and keep them stable.
PostgreSQL roles are cluster-wide: never reuse role names for different instances.

Default: one replica, `Recreate` strategy. Automatic provisioning requires both.
To scale, provision externally, coordinate migrations separately, and use RWX
storage or disable persistence. The chart cannot coordinate application-level
multi-node behavior; validate it with ZAQ before scaling. Recreate causes upgrade
downtime but avoids overlapping first-run provisioning and RWO volume attachment.

### Database transport limitation

**The released v0.18.0 configuration does not enable TLS for ZAQ's Ecto database
connection.** Its generated owner URL does not configure certificate validation.
`database.provisioning.sslMode` affects only the init container's libpq client
and does not secure the application connection.

Use an appropriately isolated/trusted database network. Do not deploy across an
untrusted network or claim end-to-end database TLS with this image. A deployment
requiring verified database TLS needs an upstream-compatible image/configuration
change; the chart deliberately does not pretend that `PGSSLMODE` configures Ecto.
Use a direct primary endpoint: poolers/load-balanced replicas can violate ZAQ's
bootstrap server identity checks.

## Pre-existing Secrets

All Secrets must be in the release namespace. Names and key mappings are
configurable; only references go into Helm values and release records.
Do not pass credentials through `--set`, `--set-file`, or values files.

### DBA Secret

Default name: `zaq-dba`. Required only when provisioning is enabled.

- `username`: DBA login.
- `password`: DBA password.

Only the init container receives these keys. The same DBA Secret can be selected
by multiple releases in one namespace. External automation must synchronize it
into each namespace if needed; Kubernetes cannot reference it cross-namespace.

### Deployment Secret

Default name: `zaq-runtime`. Use a **dedicated Secret per deployment**.

- `owner-password`: raw application-owner password, supplied to both containers.
- `reader-password`: raw reader password, supplied only to the init container;
  unnecessary when provisioning is disabled.
- `secret-key-base`: Phoenix key, supplied only to the application; use a strong
  value of at least 64 bytes/characters as accepted by Phoenix.
- `encryption-key`: configuration encryption key, supplied only to the
  application; must represent exactly **32 bytes**. Base64 is recommended.

Use stable, independently managed values. Never regenerate the encryption key
on an existing installation: encrypted configuration requires its original key.
Secret selection does not grant application code Kubernetes API access; token
automounting is disabled. Nevertheless, users able to edit Pods or Secrets can
access credentials, including a completed init container's configured references.
Enforce RBAC and Kubernetes Secret encryption at rest.

### Creation example

Prefer a secret-management system or external Kubernetes API automation. For
manual creation, read values from protected files, not command-line literals:

```sh
kubectl create namespace customer-a
kubectl -n customer-a create secret generic postgres-dba \
  --from-file=username=/secure/dba-username \
  --from-file=password=/secure/dba-password
kubectl -n customer-a create secret generic customer-a-runtime \
  --from-file=owner-password=/secure/owner-password \
  --from-file=reader-password=/secure/reader-password \
  --from-file=secret-key-base=/secure/secret-key-base \
  --from-file=encryption-key=/secure/encryption-key
```

Files must contain exact values, without unintended trailing newlines. Do not
commit them, print Secret objects, or enable shell tracing while preparing them.
Missing Secrets/keys block startup; offline rendering does not query the cluster.
No Secret resources or installation helper are included in the chart.

## Install from a checkout

An optional [prerequisite preflight](operations.md#optional-prerequisite-preflight)
can check required Secret references and read-only PostgreSQL authentication
before install/upgrade. It is bounded and off by default, and never replaces
bootstrap, migrations, or application-key validation.

Run these commands from the repository root. Review the [values reference](values.md)
and adapt [`examples/production.yaml`](../examples/production.yaml).
The example selects the existing `longhorn` StorageClass, `postgres-dba` Secret,
and `customer-a-runtime` Secret; replace these names with your resources.

```sh
helm lint --strict charts/zaq
helm upgrade --install customer-a ./charts/zaq \
  --namespace customer-a \
  --values your-values.yaml \
  --wait --timeout 20m
```

For a prepared database and existing PVC, see
[`examples/existing-database-pvc.yaml`](../examples/existing-database-pvc.yaml).
Supply the existing owner credentials and disable provisioning; no DBA/reader
credentials or bootstrap receipt are required by the application itself.

## Install from GHCR

After chart 0.1.0 has been published:

```sh
helm upgrade --install customer-a oci://ghcr.io/www-zaq-ai/charts/zaq \
  --version 0.1.0 --namespace customer-a \
  --values your-values.yaml \
  --wait --timeout 20m
```

If package access requires authentication, use `helm registry login ghcr.io`
with your normal protected credential flow. The chart does not require a registry
token when the package is publicly readable. See [release availability](releases.md)
and [temporary test releases](releases.md#manual-test-releases-from-main).

### Waiting for startup

**Always use `--wait` and an adequate timeout.** Helm rendering/API submission
alone is not proof of successful initialization or migration. No migration hook
is needed because ZAQ runs migrations before serving. Startup failures prevent
readiness; Helm waiting reports failure rather than a successful installation.
Do not assume `--atomic` can undo a database schema change.

## First login

ZAQ's migrations seed an `admin` Back Office account with initial password
`admin` and force a password/email change. This is upstream behavior, not a
chart-generated credential. **Restrict ingress to trusted operators until first
login is completed.** Existing accounts are not overwritten.

Configure AI providers/model settings, an enabled conversational agent, and Disk
data sources in Back Office. A mounted PVC does not automatically expose its root
or create a `documents` data source. See the upstream deployment guide.

## Application compatibility

Minimum ZAQ version: **0.18.0**, annotated in `Chart.yaml`. No maximum is imposed.
`v0.18.0` and `0.18.0` compare identically, but the actual tag is not rewritten.
Prereleases below the stable minimum are rejected; later semantic prereleases
are permitted but not claimed tested. Build metadata does not change ordering.

For a non-semantic tag or digest, supply `image.appVersion` as an explicit full
semantic version. Digest selection takes precedence over tag selection. This is
an operator assertion, not inspection of the image's contents. Prefer immutable
digests in production. The chart rejects a conflicting version declaration when
a semantic tag is used without a digest. Chart and application versions remain
independent; see [chart releases](releases.md).
