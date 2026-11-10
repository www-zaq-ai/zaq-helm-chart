# ZAQ OS Helm Chart

Deploy isolated [ZAQ OS](https://github.com/www-zaq-ai/zaq) instances on
Kubernetes, including Rancher-managed clusters.

This repository provides the Helm chart, deployment documentation, tests, and
GitHub Actions workflows. It uses an existing PostgreSQL server and Kubernetes
Secrets; it does not deploy PostgreSQL or generate credentials.

Chart **0.1.0** targets ZAQ **v0.18.0**. Chart and application versions are
independent.

## Prerequisites

- Kubernetes **1.31+**, Helm v3, and access to the target cluster.
- PostgreSQL **16+** with **pgvector >= 0.7.0**. Automatic database provisioning
  requires a PostgreSQL superuser; externally prepared databases are supported.
- A namespace with the required pre-existing database/application Secrets.
- An existing StorageClass, cluster default, or compatible PVC.
- For external HTTPS access: an Ingress controller, DNS, and TLS certificate.

Review the [deployment prerequisites and security constraints](docs/deployment.md)
before installing, especially database TLS and initial administrator access.

## Quick start

1. Prepare PostgreSQL, the namespace, and
   [required Secrets](docs/deployment.md#pre-existing-secrets).
2. Copy [`examples/production.yaml`](examples/production.yaml) to your own
   values file. Set the database endpoint/identities, existing Secret names,
   StorageClass, hostname, and Ingress/TLS configuration for your cluster.
   **Do not put credentials in Helm values.**
3. Install from this checkout:

   ```sh
   helm upgrade --install customer-a ./charts/zaq \
     --namespace customer-a --values your-values.yaml \
     --wait --timeout 20m
   ```

Open your configured hostname at `/bo/login` and complete
[first-login setup](docs/deployment.md#first-login) before public exposure.

For a published release, use `oci://ghcr.io/www-zaq-ai/charts/zaq` with an explicit
chart version. See [GHCR installation](docs/deployment.md#install-from-ghcr) or
the [Rancher guide](docs/rancher.md). OCI availability depends on a successful
chart release; a source commit alone does not publish a chart.

## Documentation

- [Deployment](docs/deployment.md) — prerequisites, database bootstrap, Secrets,
  installation, first login, and application compatibility.
- [Rancher](docs/rancher.md) — prepare and install in a Rancher-managed cluster.
- [Storage](docs/storage.md) — StorageClasses, existing PVCs, permissions,
  expansion, backups, and retention.
- [Operations](docs/operations.md) — networking, health checks, upgrades,
  credential rotation, rollback, uninstall, and troubleshooting.
- [Values reference](docs/values.md) — complete chart configuration.
- [Releases](docs/releases.md) — Release Please, GitHub setup, manual test
  releases, and automatic cleanup.
- [Development](docs/development.md) — tooling, local tests, and contribution
  checks. Agent-specific boundaries are in [AGENTS.md](AGENTS.md).
