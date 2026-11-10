# Initial chart implementation report

This is the original implementation snapshot. The manual-tag release policy
has since been replaced by the Release Please flow described in the
[README](../README.md#development-and-release).

## Delivered

- Helm application chart `charts/zaq`, version `0.1.0`, targeting ZAQ `v0.18.0`.
- Existing DBA Secret selection and a grouped, per-deployment runtime Secret,
  with configurable key mappings and per-container credential isolation.
- Optional terminating database-provisioning init container using ZAQ's own
  entrypoint, followed by application migrations-before-server startup.
- PVC creation/retention, existing StorageClass selection, existing PVC reuse,
  ClusterIP Service, optional TLS Ingress, security/resource controls, probes,
  scheduling, and semantic minimum-version validation without an upper bound.
- Offline tests, a disposable Kind integration suite, pinned validation tools,
  PR/main CI, and separately tagged, guarded OCI chart publication.
- Installation/Rancher instructions, Secret prerequisites, production examples,
  complete values reference, and lifecycle/recovery documentation.

## Validation performed

Validated locally on 2026-11-06 using Docker on Linux ARM64 containers:

- Helm **3.18.6** strict lint: passed.
- JSON Schema validation and **20 unit/negative tests**: passed.
- **16 renders / 64 resource validations** using kubeconform **0.7.0** against
  Kubernetes **1.31.0, 1.32.0, 1.33.0, and 1.34.0** schemas: passed.
- Workflow syntax with actionlint **1.7.7**: passed.
- Markdown lint with markdownlint-cli2 **0.18.1**: passed.
- Chart packaging as `zaq-0.1.0.tgz`: passed.
- Local documentation references, whitespace checks, and shell syntax: passed.
- Kind **0.30.0**, Kubernetes **1.34.0**, real ZAQ **v0.18.0**, and PostgreSQL
  **17** with pgvector **0.8.1**: passed.

The Kind suite separately installed a mock chart workload and real ZAQ. It
verified database creation, migrations, restricted role flags, reader SELECT,
denied writes, default grants on new tables, and HTTP **200** responses using
`X-Forwarded-Proto: https`.

It also verified replacement-Pod receipt validation without password rotation,
credential-mismatch and migration-failure readiness gates, app-only upgrade,
uninstall retention, external Secret preservation, and reinstallation using the
existing database/PVC. The disposable cluster was deleted after testing.

GitHub-hosted CI and real GHCR publication have **not** been executed. Publication
is intentionally not part of local validation; registry absence/overwrite guards
are unit-tested. Nothing has been committed, tagged, or published by this task.

## Remaining deployment constraints

1. **Application database TLS:** ZAQ v0.18.0 does not configure Ecto database TLS.
   Init-container `sslMode` does not secure that separate connection. A verified
   TLS requirement needs an upstream-compatible image/configuration change;
   otherwise use an appropriately isolated, trusted database network.
2. **DBA rights:** automatic provisioning requires PostgreSQL superuser rights
   and preinstalled extension packages. Restricted managed providers require
   externally prepared databases and provisioning-disabled deployment.
3. **First login:** upstream migrations seed an `admin` account with initial
   password `admin` and mandatory password change. Restrict exposure until setup.
4. **Rollout and recovery:** the default is one replica with Recreate downtime.
   Scaling requires external provisioning/migration coordination and ZAQ-level
   review. Helm rollback does not reverse schema changes or restore data.
5. **Operator responsibilities:** create Secrets before installation, coordinate
   credential rotation, configure ingress trust/network restrictions, verify CSI
   permissions and expansion, and back up PostgreSQL/files/encryption keys.
6. **Coverage boundary:** real installation was tested on Kubernetes 1.34/ARM64
   and PostgreSQL 17, not every Rancher/Kubernetes/CSI/provider combination.
   AMD64 CI is configured but not claimed executed here. Future application
   versions passing the minimum check are not automatically integration-tested.
