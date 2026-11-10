# Development

Run commands from the repository root. Read [AGENTS.md](../AGENTS.md) for
repository boundaries, security contracts, and pre-commit checks.

## Tooling and local checks

```sh
INSTALL_DIR="$HOME/.local/zaq-chart-tools" bash tests/install-tools.sh
export PATH="$HOME/.local/zaq-chart-tools:$PATH"
python3 -m venv .venv
.venv/bin/pip install -r tests/requirements.txt
.venv/bin/python tests/validate.py
npx --yes markdownlint-cli2@0.18.1 README.md AGENTS.md \
  docs/*.md charts/zaq/README.md
.venv/bin/python -u tests/integration.py
helm package charts/zaq --destination .artifacts
```

The installer downloads checksum-verified, pinned Helm, Kind, kubectl,
kubeconform, and actionlint binaries. Offline tests need no cluster or real
Secrets (kubeconform fetches public schemas). Integration requires Docker and
creates/deletes its **own Kind cluster and kubeconfig**, never using your current
cluster. Allow adequate memory, disk, image-download access, and time.

To validate an already packaged chart with integration tests, set
`ZAQ_CHART_PATH` to its absolute archive path. The default is `charts/zaq`.
The test-release workflow uses this to test its packaged prerelease.

## Test coverage

Unit tests cover rendering, schema failures, identity isolation, Secret wiring,
probes, storage, security, versions, and release tags. The schema matrix covers
default, TLS Ingress, custom, and existing-database/PVC configurations across
Kubernetes 1.31–1.34.

Integration separately tests a mock deployment and real ZAQ with disposable
PostgreSQL, ephemeral Secrets, ACLs/default grants, restart validation, credential
and migration failures, upgrades, PVC reuse, and uninstall retention. Mock
readiness alone is not proof that ZAQ deploys successfully.

Release-automation tests cover source-SHA pinning, test namespace isolation,
retention boundaries, pagination, dry runs, and deletion guards without
publishing or deleting live GitHub/GHCR artifacts. Never use live publication
or deletion merely to validate workflow changes.

## Choosing checks

- Every change: inspect the intended diff, check for credentials/unrelated
  changes, and run `git diff --check`. Include new files in the review.
- Documentation-only: run Markdown lint and check local links/anchors. No
  application build or Kubernetes installation is required.
- Chart changes: run `tests/validate.py`; also run integration for provisioning,
  startup, migration, networking, security, or storage changes.
- Workflow/release changes: run workflow lint and relevant automation tests;
  verify permissions, pinned actions/tools, trigger scope, and packaging.

Keep docs consistent with implemented behavior. Avoid duplicating detailed
guidance in the [README](../README.md); it is the overview and quick start.
CI already lints `docs/*.md` and `charts/zaq/README.md`, so new guides and the
packaged chart details are covered. Chart tests also verify packaged README/form
inclusion and question defaults/types against values/schema. Preflight changes
require real Kind coverage, including cross-namespace PostgreSQL, bounded
missing-Secret/key failures, read-only behavior, and credential-safe diagnostics.

See [release maintenance](releases.md) for versioning and publishing, and the
[initial implementation report](implementation-report.md) for the original
validation snapshot and production constraints.
