# Repository guidance

## Purpose and boundaries

This repository owns the ZAQ OS Helm chart, its documentation, chart tests, and
GitHub Actions validation and release workflows. Read `README.md` first.

- Implement only the scope requested in the active task. A documented roadmap
  is not authorization to implement additional features.
- Treat the upstream ZAQ release as the application source of truth. Verify
  entrypoints, environment variables, migrations, permissions, and health
  behavior before encoding them in templates.
- Do not modify ZAQ application code here or duplicate its bootstrap SQL.
- Do not provision PostgreSQL servers, StorageClasses, billing, or Customer
  Portal integrations.
- Do not create installation helpers or chart-managed credential Secrets.
- Preserve unfamiliar local changes. Do not commit unrelated or generated
  agent state, including `.serena/`.
- Do not create commits, tags, or publish artifacts unless requested.

## Deployment contract

- Use an ordinary terminating init container, not a long-running sidecar, for
  optional database provisioning. Preserve the ZAQ image entrypoint and reuse
  `provision-db --automatic`.
- Use the same image version/digest for provisioning and the application.
- Keep DBA credentials confined to the provisioning container. The application
  uses its dedicated PostgreSQL owner login; the reader is a separate login.
- Reference a selectable existing DBA Secret and a selectable per-deployment
  Secret, both in the release namespace. Support configurable key mappings.
- Inject individual Secret keys with `secretKeyRef`, not wholesale `envFrom`.
- Never generate, embed, log, or commit production credentials. Keep sensitive
  values out of Helm values, command arguments, rendered examples, and release
  records. Do not use Helm `lookup` to read Secret contents.
- Keep credential creation and rotation external. Do not reset passwords or
  bypass ZAQ receipt, ownership, or migration-ledger checks on restart.
- Preserve migrations-before-server startup. Installation and upgrade checks
  must wait for readiness and fail on provisioning or migration failure.
- Do not imply that Helm rollback reverses database schema changes.
- Select existing storage classes or reuse PVCs. Mount data at `/zaq/volumes`.
- Use `/channels/health` with `X-Forwarded-Proto: https` for HTTP probes on port
  `4000`; verify HTTP 200 rather than redirect success.
- Enforce minimum application version `0.18.0`, with no maximum. Normalize an
  optional leading `v` only for comparisons, never for changing the image tag.
- Keep chart and application versions independent.

## Code quality

- Prefer small, conventional Helm templates and minimal dependencies.
- Centralize naming and labels in helpers. Avoid unnecessary abstraction and
  duplicated environment or security configuration.
- Document all public values and validate types and conditional requirements
  through `values.schema.json` and targeted template checks.
- Keep renders deterministic and usable offline. Cluster-dependent existence
  checks must not be required for `helm template`.
- Quote string values correctly and preserve Kubernetes field types. Use
  semantic-version comparison, not lexical comparison.
- Default to non-root execution, least privilege, and no automatic service
  account token mounting. Verify writable-path and volume requirements against
  the released image before tightening filesystem defaults.
- Make resource ownership and retention behavior explicit. Do not introduce
  automatic destructive database or storage cleanup.
- Add meaningful tests for configuration contracts, failure paths, credential
  isolation, version validation, and resource lifecycle behavior.
- Separate mocked chart tests from real ZAQ integration tests. A mock becoming
  ready does not prove the application deploys successfully.
- Pin CI actions to immutable revisions and tools/images to reproducible
  versions or digests. Release Please manages chart versions and changelogs;
  merging its release PR is the publication approval. Publish the exact release
  SHA only after validation, and reject an existing chart version. Never bump
  the ZAQ application version as part of automatic chart versioning.
- Document assumptions and unsupported behavior instead of inventing defaults.

## Checks before committing

Run checks appropriate to the files changed and report their actual results.
Do not claim checks passed when tooling or implementation is unavailable.

### Every change

1. Inspect `git status --short` and the complete intended diff.
2. Run `git diff --check` for tracked changes; also inspect new files before
   staging, since ordinary `git diff` does not include untracked files.
3. Check for credentials, unrelated changes, generated artifacts, and broken
   documentation references.
4. After staging, inspect `git diff --cached` and run
   `git diff --cached --check` before committing.

### Documentation changes

Run the pinned Markdown linter against changed Markdown files:

```sh
npx --yes markdownlint-cli2@0.18.1 README.md AGENTS.md docs/*.md
```

Check that examples match the current implementation and distinguish planned
functionality from shipped functionality. Documentation-only work does not
require an application build or a Kubernetes installation.

### Chart changes

- Run `helm lint --strict charts/zaq`.
- Validate values against the JSON schema, including invalid-value fixtures.
- Render defaults and representative configurations with `helm template`.
- Validate rendered resources with the CI-pinned kubeconform version against
  the documented Kubernetes version matrix.
- Run chart unit and negative tests, including Secret isolation and unsupported
  application-version rejection.
- For provisioning, startup, migrations, networking, security, or storage
  changes, run the relevant Kind integration tests with disposable dependencies
  and ephemeral test credentials. Verify readiness and cleanup/retention.
- Verify `helm package charts/zaq` for packaging or release-related changes.

Canonical checks: install `tests/requirements.txt`, then run
`python tests/validate.py` and, for integration-sensitive changes,
`python -u tests/integration.py`. Install pinned tools with
`INSTALL_DIR=/your/tools/path bash tests/install-tools.sh`; add that path to
`PATH`. Keep this guidance synchronized with CI. Do not substitute mock-only
checks for required integration checks. Broaden testing when failures or changed
behavior justify it, rather than repeating successful unrelated suites.

### Workflow changes

Validate GitHub Actions syntax with a pinned workflow linter. Review trigger
scope, token permissions, immutable dependency pins, credential handling, and
release-version matching. Do not publish a release merely to test a workflow.

## Completion report

Summarize changed files, checks run, and any remaining blockers. Clearly
distinguish implemented behavior from planned work, and stop at the user's
requested boundary.
