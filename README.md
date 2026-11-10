# ZAQ OS Helm Chart

Deploy isolated [ZAQ OS](https://github.com/www-zaq-ai/zaq) instances on
Kubernetes, including Rancher-managed clusters, using external PostgreSQL,
pre-existing Secrets, and your cluster's storage.

Chart **0.1.0** targets ZAQ **v0.18.0**. Chart and application versions are
independent. The intended OCI reference is
`oci://ghcr.io/www-zaq-ai/charts/zaq`; availability depends on an explicit chart
release, not a commit to `main`.

## Prerequisites

- Helm **3.18.6** is the validation baseline; Helm v3 is required.
- Kubernetes **1.31 or newer**. Manifest schemas are checked against 1.31–1.34;
  CI performs real installation tests on Kind/Kubernetes 1.34.0. This is not a
  guarantee of compatibility with every future Kubernetes version.
- A namespace and permission to create Deployments, Services, ServiceAccounts,
  PVCs, and optionally Ingresses there.
- Linux AMD64 or ARM64 nodes and access to `ghcr.io/www-zaq-ai/zaq` or a mirror.
- PostgreSQL **16+** with **pgvector >= 0.7.0**, including `halfvec`, installed
  on the server. CI uses PostgreSQL 17 with pgvector 0.8.1. ParadeDB is optional;
  its `pg_search` capability is selected by the upstream bootstrap implementation.
- An existing StorageClass (or cluster default) or a compatible existing PVC.
- Both credential Secrets described below, created **before installation**.
- For external access: an Ingress controller, DNS, and a TLS certificate Secret
  or certificate-management integration.

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

Automatic provisioning requires a **PostgreSQL superuser DBA**. Many managed
database providers cannot grant the necessary rights: use DBA/provider-managed
provisioning and set `database.provisioning.enabled: false` instead. Extension
packages must already be installed on the server.

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
Set explicit identities in production (see `examples/production.yaml`) and keep
them stable. PostgreSQL roles are cluster-wide: never reuse role names for
different instances.

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

## Install

Review [all values](docs/values.md) and adapt `examples/production.yaml`.
The example selects the existing `longhorn` StorageClass, `postgres-dba` Secret,
and `customer-a-runtime` Secret; replace these names with your resources.

From this repository:

```sh
helm lint --strict charts/zaq
helm upgrade --install customer-a ./charts/zaq \
  --namespace customer-a \
  --values examples/production.yaml \
  --wait --timeout 20m
```

From GHCR, after chart 0.1.0 has been published:

```sh
helm upgrade --install customer-a oci://ghcr.io/www-zaq-ai/charts/zaq \
  --version 0.1.0 --namespace customer-a \
  --values examples/production.yaml \
  --wait --timeout 20m
```

If package access requires authentication, use `helm registry login ghcr.io`
with your normal protected credential flow. The chart does not require a registry
token when the package is publicly readable.

**Always use `--wait` and an adequate timeout.** Helm rendering/API submission
alone is not proof of successful initialization or migration. No migration hook
is needed because ZAQ runs migrations before serving. Startup failures prevent
readiness; Helm waiting reports failure rather than a successful installation.
Do not assume `--atomic` can undo a database schema change.

### Rancher

1. Select the cluster/project and create the target namespace.
2. Create/import the DBA and deployment Secrets in that namespace using Rancher
   or your external API automation. Also prepare the Ingress TLS Secret.
3. Use Rancher's supported OCI chart installation workflow, if available in your
   version; otherwise run the Helm commands above with a downloaded kubeconfig.
4. Supply non-sensitive values: database endpoint/identities, existing Secret
   names, hostname, Ingress class/TLS, and existing StorageClass or PVC.
5. Wait for the Deployment to become available and verify Back Office access.

There is no chart-managed PostgreSQL, credential-generation form, or dependency
on a Rancher-specific resource API.

### First login

ZAQ's migrations seed an `admin` Back Office account with initial password
`admin` and force a password/email change. This is upstream behavior, not a
chart-generated credential. **Restrict ingress to trusted operators until first
login is completed.** Existing accounts are not overwritten.

Configure AI providers/model settings, an enabled conversational agent, and Disk
data sources in Back Office. A mounted PVC does not automatically expose its root
or create a `documents` data source. See the upstream deployment guide.

## Storage

The application mounts `/zaq/volumes`; it runs with UID `1000`. The default
supplemental filesystem group is `1000`, without assuming the image's primary
GID. Your CSI/NFS driver must honor the chosen access modes and permissions.

- `persistence.storageClass: null`: omit the field and use cluster defaults.
- `persistence.storageClass: longhorn`: select an existing named class.
- `persistence.storageClass: ""`: explicitly request no class, typically for a
  matching pre-provisioned PV.
- `persistence.existingClaim: customer-a-data`: reuse a PVC in the namespace;
  leave `storageClass` unset. The existing PVC's size, class, annotations, and
  access modes remain externally managed, not changed by this chart.
- `persistence.enabled: false`: use ephemeral `emptyDir`; Pod deletion loses
  application files.

Chart-created PVCs default to `helm.sh/resource-policy: keep`. After uninstall,
set `existingClaim` to the retained PVC name when reinstalling. Helm no longer
manages a retained PVC after uninstall. To allow intentional deletion, set
`persistence.retain: false` **before** uninstalling; the PV reclaim policy still
determines what happens to backing storage.

Expansion requires a StorageClass/CSI driver with expansion support. Increase
the requested size and follow the driver's filesystem expansion procedure; do
not decrease it. StorageClass/access-mode changes usually require a new PVC
and an explicit data migration. Back up application files and PostgreSQL
separately; neither Helm nor this chart provides backups.

## Networking and health

Service: ClusterIP, default port `4000`, targeting container port `4000`.
Ingress is optional and terminates TLS outside ZAQ. Its hostname must match
`app.host`. Configure your proxy to overwrite `X-Forwarded-Proto`, preserve the
public hostname, support WebSockets, and restrict direct backend access.
Cluster-specific network policies remain an operator responsibility.

All probes request `/channels/health` over HTTP with
`X-Forwarded-Proto: https`. This avoids production HTTPS redirection without
changing the application's HTTPS enforcement. Integration tests assert status
**200**, not a redirect. The startup probe allows 15 minutes by default; tune it
and the Helm timeout for large migrations. Liveness is delayed until startup
succeeds. The endpoint reports HTTP availability, not database/provider health.

For temporary local access without Ingress:

```sh
kubectl -n customer-a port-forward service/customer-a-zaq 4000:4000
```

Then visit `http://localhost:4000/bo/login`. Do not expose this port-forward on
external interfaces.

## Upgrade, rotation, rollback, and uninstall

1. Back up PostgreSQL, application files, and key-management records.
2. Review ZAQ release notes and migration compatibility. Keep database/role
   identities and application encryption keys stable.
3. Upgrade with explicit chart/image versions and `--wait --timeout 20m`.
4. Check Deployment readiness, login, data access, and application behavior.

The init container validates passwords on each new Pod; editing a Secret is
**not** database password rotation. Coordinate DBA changes and Secret updates
with downtime as required. Secret content changes do not automatically trigger
a Deployment rollout; restart it explicitly after a coordinated change.

Helm rollback restores Kubernetes configuration only. It does not reverse
migrations or restore PostgreSQL or files. Use an older image only if its schema
compatibility is confirmed; otherwise use a reviewed forward fix or coordinated
backup restoration. Never delete receipts or migration ledgers as recovery.

```sh
helm uninstall customer-a --namespace customer-a --wait
```

This removes chart workloads, Service, Ingress, and created ServiceAccount.
External Secrets and PostgreSQL data/roles remain. Existing PVCs are untouched;
chart-created PVCs follow the retention setting above. No database cleanup or
credential revocation occurs automatically.

## Version policy

Minimum ZAQ version: **0.18.0**, annotated in `Chart.yaml`. No maximum is imposed.
`v0.18.0` and `0.18.0` compare identically, but the actual tag is not rewritten.
Prereleases below the stable minimum are rejected; later semantic prereleases
are permitted but not claimed tested. Build metadata does not change ordering.

For a non-semantic tag or digest, supply `image.appVersion` as an explicit full
semantic version. Digest selection takes precedence over tag selection. This is
an operator assertion, not inspection of the image's contents. Prefer immutable
digests in production. The chart rejects a conflicting version declaration when
a semantic tag is used without a digest.

## Development and release

See [AGENTS.md](AGENTS.md) for boundaries and pre-commit checks.

```sh
INSTALL_DIR="$HOME/.local/zaq-chart-tools" bash tests/install-tools.sh
export PATH="$HOME/.local/zaq-chart-tools:$PATH"
python3 -m venv .venv
.venv/bin/pip install -r tests/requirements.txt
.venv/bin/python tests/validate.py
npx --yes markdownlint-cli2@0.18.1 README.md AGENTS.md docs/*.md
.venv/bin/python -u tests/integration.py
helm package charts/zaq --destination .artifacts
```

The installer downloads checksum-verified, pinned Helm, Kind, kubectl,
kubeconform, and actionlint binaries. Offline tests need no cluster or real
Secrets (kubeconform fetches public schemas). Integration requires Docker and
creates/deletes its **own Kind cluster and kubeconfig**, never using your current
cluster. Allow adequate memory, disk, image-download access, and time.

Unit tests cover rendering, schema failures, identity isolation, Secret wiring,
probes, storage, security, versions, and release tags. The schema matrix covers
default, TLS Ingress, custom, and existing-database/PVC configurations.
Integration separately tests a mock deployment and real ZAQ with disposable
PostgreSQL, ephemeral Secrets, ACLs/default grants, restart validation, credential
and migration failures, upgrades, PVC reuse, and uninstall retention.

CI runs on PRs and pushes to `main`. Publication is independent: a maintainer
creates an explicit `chart-v0.1.0` tag matching `Chart.yaml`. The release workflow
reruns validation/integration, packages the chart, and publishes to GHCR with
minimal `GITHUB_TOKEN` permissions. It refuses existing versions and ambiguous
registry errors. No release is published on ordinary `main` commits.

See the [initial implementation report](docs/implementation-report.md) for
checks actually performed and remaining production constraints.

## Troubleshooting and deployment risks

- Missing Secret/key: inspect Pod events and reference names; never print Secret
  data or container environments.
- Initialization failure: inspect `kubectl logs <pod> -c provision-db`, treating
  diagnostic output as sensitive. Verify DBA rights, extensions, identities,
  supplied passwords, and receipt/adoption status.
- Migration failure: ZAQ never becomes ready. Inspect application diagnostics
  securely and request DBA/application review; do not assume rollback is safe.
- Pending PVC: verify StorageClass name, provisioner, access modes, capacity,
  and any wait-for-consumer scheduling constraints.
- Redirect loops: check public hostname, TLS termination, and overwritten
  forwarded headers. Health probes must carry the documented header.
- Remote database TLS, safe bootstrap Back Office exposure, backups, node-level
  storage permissions, and multi-replica operation need explicit production
  review. This chart does not remove those upstream/operator constraints.
