# Chart releases

Chart versions are independent of ZAQ application versions. This repository
publishes Helm OCI artifacts to `oci://ghcr.io/www-zaq-ai/charts/zaq`.
Availability depends on a successful publication; a source commit alone does
not publish a chart. See [installation](deployment.md#install-from-ghcr).

## Production releases with Release Please

CI runs on PRs and pushes to `main`. The release workflow also runs on `main`,
using Release Please's native Helm strategy for `charts/zaq`:

1. Merge chart changes using Conventional Commit messages. Release Please opens
   or updates one release PR, grouping unreleased changes across multiple merges.
2. Review the generated chart version, `charts/zaq/CHANGELOG.md`, and release
   manifest. Merging this PR approves the release; no manual tag or chart-version
   bump is needed.
3. Release Please creates a GitHub Release and `chart-vX.Y.Z` tag. Validation
   and Kind integration run against that exact release SHA in the same workflow.
4. Once both gates pass, the workflow packages and publishes the chart to GHCR
   with `GITHUB_TOKEN`. Existing versions and ambiguous registry errors still
   block publication.

The workflow uses the path-specific `release_created` output instead of relying
on a tag-created workflow event: tags created with `GITHUB_TOKEN` do not trigger
another workflow. Ordinary merges only update the release PR; the GitHub Release
can exist before GHCR publication finishes. If publication or a gate fails, fix
the cause and **rerun failed jobs**, preserving the successful Release Please
job's outputs. Rerunning the entire workflow will not recreate an existing
release, so it will not take the automatic publication path again.

The empty initial manifest and `initial-version: 0.1.0` prepare the first release
without claiming that version is already published. A bootstrap commit bounds
the initial history scan; subsequent releases use the recorded release history.
Release Please changes `Chart.yaml`'s chart `version`, **not** ZAQ's `appVersion`,
image tag, or minimum supported application version.

Chart commits are scoped to `charts/zaq`. Use `fix:` for patches, `feat:` for
minor releases, and `!` or `BREAKING CHANGE:` for major releases. Docs, tests,
and CI-only commits do not normally trigger a release. Squash merging with a
Conventional Commit PR title makes the release intent clear.

## GitHub repository setup

Enable **Allow GitHub Actions to create and approve pull requests** in repository
Settings → Actions → General. Release Please uses job-scoped contents, issues,
and pull-request write permissions; production package write permission is
limited to its publication job. It does not automatically merge its release PR.

By default, Release Please uses `GITHUB_TOKEN`. GitHub suppresses CI events for
bot-created/updated PRs using this token, which can leave required PR checks
pending. If your branch rules require those checks, configure the optional
`RELEASE_PLEASE_TOKEN` Actions secret with a repository-scoped automation token
that can write contents, issues, and pull requests and trigger PR workflows.
Do not bypass branch protection to compensate. GHCR publication continues to
use `GITHUB_TOKEN`, not this optional token.

## Manual test releases from main

Once the test workflows are merged into `main`, open **Actions → Test release →
Run workflow**, select **main**, and run it. Dispatches from other branches are
skipped. The workflow resolves current `main` once; all checks and publication
use that exact commit even if `main` advances while the run is in progress.

It creates a unique chart version such as `0.1.0-test.123456789.1` (base chart
version, workflow run ID, run attempt). The packaged chart is validated and
installed with real ZAQ in Kind before publication. Chart source files,
Release Please's manifest/changelog, and ZAQ's application version are not
modified or committed.

Successful runs publish to the separate test reference
`oci://ghcr.io/www-zaq-ai/charts/test/zaq` and create a GitHub **prerelease** with
a `chart-test-v` tag, source SHA, and installation instructions. These tags do
not match the production `chart-v` release series and are never marked latest.
Create the namespace and [Secrets](deployment.md#pre-existing-secrets) before
installing, then adapt your values:

```sh
helm upgrade --install customer-a oci://ghcr.io/www-zaq-ai/charts/test/zaq \
  --version 0.1.0-test.123456789.1 --namespace customer-a \
  --values your-values.yaml --wait --timeout 20m
```

Use the exact version from the GitHub prerelease. If a test run fails, choose
**Re-run all jobs** (or start another manual run), not just failed jobs: the new
attempt must prepare and validate its own unique version. Existing artifacts
are not overwritten. A failed GitHub prerelease creation after OCI publication
may leave a test package version; cleanup also inventories those orphan versions.

## Test release cleanup

**Clean up test releases** runs daily at **03:23 UTC** and after successful test
publication. It can also be launched manually; its **dry_run** option defaults
to true. Review the Actions log before disabling that option for manual deletion.

Retention is evaluated across matching GitHub prereleases and test OCI versions:

- Always keep the **newest three** test versions, even if older than seven days.
- Keep **all versions within seven days**, so more than three may coexist.
- Delete other versions only when all their recorded artifacts are **older
  than seven days**, using their latest creation/publication timestamp.
- Delete expired test OCI versions, associated test Git tags, and marked GitHub
  prereleases. Production packages/releases are outside the cleanup namespace.

Cleanup paginates inventories and rechecks each candidate before deleting it.
Unknown/shared OCI aliases, unmarked or non-prerelease GitHub records, and moved
or annotated tags are protected rather than deleted. Package deletion happens
first and the GitHub release record last, preserving discovery after partial
failures. Untagged OCI versions and unrelated tags are not automatically removed.

Grant this repository's Actions **admin access** to the test GHCR package
(`charts/test/zaq`) so `GITHUB_TOKEN` can delete its versions. Check the package's
**Manage Actions access** settings and repository linkage; `packages: write`
alone does not guarantee deletion rights. The workflows request package/content
write permissions only for publication/cleanup jobs. Registry/API permission
failures stop cleanup instead of silently claiming success. Public-package
download restrictions imposed by GitHub can also prevent deletion.

GitHub schedules run from the default branch and may be delayed; ensure the
repository's default branch is `main`. Publication and cleanup share a concurrency
lock. A successful publication remains available if subsequent cleanup fails;
fix the permissions/error and rerun cleanup separately.

For local workflow validation and safety checks, see [development](development.md).
