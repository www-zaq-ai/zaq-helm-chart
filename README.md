# ZAQ OS Helm Chart

Helm packaging for isolated [ZAQ OS](https://github.com/www-zaq-ai/zaq)
instances on Kubernetes, including Rancher-managed clusters.

This repository owns the deployment chart, chart documentation, tests, and
release automation. ZAQ application code and database bootstrap logic belong
to the upstream ZAQ repository.

## Project status

The chart is being prepared. This repository currently documents its deployment
contract and prerequisites; an installable chart and CI workflows are not yet
available.

The initial chart version is planned as `0.1.0`, targeting the verified ZAQ
release `v0.18.0`. Chart versions are independent of application versions.
The intended OCI chart reference is
`oci://ghcr.io/www-zaq-ai/charts/zaq`; this is not a publication announcement.

## Deployment model

Each installation will deploy ZAQ into a selected namespace, using an existing
PostgreSQL server and pre-existing Kubernetes Secrets.

1. An optional, terminating init container runs the ZAQ image's
   `provision-db --automatic` command with separate DBA credentials.
2. It creates or validates the instance database, application-owner login,
   read-only login, required extensions, and permissions.
3. The application starts with owner credentials, runs its migrations, and then
   serves HTTP on port `4000`.
4. Probes gate readiness; a Service and optional Ingress expose the instance.

The provisioning container uses the same image as the application. Bootstrap
state is recorded in PostgreSQL, not on an application volume. Subsequent Pod
starts validate existing provisioning rather than rotate passwords.

The chart will not provision the PostgreSQL server, create credentials, or
integrate billing or the Customer Portal. Secret creation is an external
responsibility, such as a Kubernetes API integration, Rancher, or a secret
management system.

## Prerequisites

### Cluster and tooling

- An existing Kubernetes cluster and a namespace for the installation.
- Helm v3 and cluster access sufficient to manage the chart's resources, or an
  equivalent Rancher installation workflow.
- Kubernetes Secrets created in the installation namespace before deployment.
- Access from cluster nodes to `ghcr.io/www-zaq-ai/zaq`, or an approved mirror.
- Linux AMD64 or ARM64 nodes, supported by the verified `v0.18.0` image.

The tested Kubernetes version range will be published with the chart and its CI
matrix. No cluster-version compatibility claim is made at this stage.

### PostgreSQL

- A reachable PostgreSQL server with the extension packages required by the
  selected ZAQ release, including `vector`.
- For automatic provisioning, a DBA account satisfying ZAQ's bootstrap
  requirements, including PostgreSQL superuser privileges. A provider-managed
  account with restricted administrative rights may not be sufficient.
- Distinct database, application-owner, and reader identities for each instance.
  PostgreSQL role names are cluster-wide and must not be shared across instances.
- Network access from the ZAQ Pod to PostgreSQL.

Provisioning can be disabled for a database already prepared by a DBA. The
application-owner login must have the rights ZAQ requires for migrations and
runtime operations; a read-only login cannot run the application.

Extension installation uses packages already present on the PostgreSQL server;
the init container cannot install server-side operating-system packages.

Existing migrated databases may require explicit adoption or repair before
automatic validation can be used. Follow the upstream
[database setup guide](https://github.com/www-zaq-ai/zaq/blob/v0.18.0/docs/database-setup.md).
Changing a Kubernetes Secret alone does not rotate PostgreSQL credentials.

### Pre-existing Secrets

The chart will select two existing Secrets by name, with configurable key
mappings. The following are logical contents; final values and key names will
be documented alongside the chart implementation.

**DBA Secret**, required when automatic provisioning is enabled:

- DBA username.
- DBA password.

Only the provisioning init container receives these credentials. This Secret
may be reused by installations in the same namespace.

**Per-deployment Secret**, dedicated to one ZAQ installation:

- Application-owner password.
- Reader password, required when provisioning is enabled.
- `SECRET_KEY_BASE` for Phoenix cookie signing and encryption.
- `SYSTEM_CONFIG_ENCRYPTION_KEY` for encrypted application configuration.

The init container receives the owner and reader passwords. The application
receives only its owner password and application keys. Individual
`secretKeyRef` entries will restrict which keys are injected into each container.

The configuration encryption key must represent exactly 32 bytes, using a
format accepted by ZAQ; Base64 is recommended. Keep application keys stable
across upgrades. Previously encrypted configuration requires its original key.

Both Secrets must exist in the release namespace. Cross-namespace references
are not supported. External automation must create or synchronize Secrets into
each target namespace before installation.

Only Secret names and key references belong in Helm values. Do not supply
passwords or application keys through values files, `--set`, or `--set-file`:
Helm retains supplied values in release records. The chart will not create
Secret resources, and uninstalling it will not delete these external Secrets.

### Persistent storage

- An existing StorageClass suitable for the workload, a cluster default class,
  or an existing compatible PVC in the installation namespace.
- Sufficient capacity and an access mode appropriate for the deployment.
- Volume permissions allowing the non-root application to write its data.

The chart will mount application storage at `/zaq/volumes` and allow selection
of an existing StorageClass by name. It will not create a StorageClass.
Existing PVC reuse will also be supported.

ZAQ `v0.18.0` runs with UID `1000`. Storage permissions must accommodate that
identity. Storage expansion depends on the selected class and CSI driver.
Application storage is separate from PostgreSQL persistence and backups.

A mounted directory does not automatically register a ZAQ Disk data source;
configure that in the application's Back Office after installation.

### Ingress and health checks

For external HTTPS access, provide an Ingress controller, hostname/DNS, and
TLS certificate Secret or certificate-management integration.

ZAQ listens for HTTP on port `4000`; TLS normally terminates at the ingress.
The proxy must correctly set forwarded headers and support WebSocket traffic.
Backend access should be restricted to the intended cluster paths.

Startup, readiness, and liveness probes will use `/channels/health` with
`X-Forwarded-Proto: https` to avoid production HTTPS redirects. The probes still
connect over HTTP. This endpoint reports HTTP availability, not database or
AI-provider health.

## Application compatibility

The minimum planned application version is `0.18.0`, which contains the verified
database-provisioning entrypoint. No maximum version is planned.

Image tags such as `v0.18.0` remain unchanged when pulling images. Validation
will normalize the optional leading `v` for semantic-version comparisons.
Custom non-semantic tags and digest-only references will require an explicit
semantic application-version declaration.

A minimum version check is not a guarantee that every future release has been
integration-tested. Tested versions will be recorded with chart releases.

## Development

See [AGENTS.md](AGENTS.md) for repository boundaries, implementation standards,
and checks required before committing. Installation examples and the complete
values reference will be added when the chart is implemented.
