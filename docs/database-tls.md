# PostgreSQL TLS

Application, provisioning and preflight use separate database clients, controlled
by one `database.tls.enabled` switch and one shared provisioning/preflight mode.

## Image support and defaults

The default and minimum supported application version is **v0.19.1**. Its
[published release](https://github.com/www-zaq-ai/zaq/releases/tag/v0.19.1) includes
verified database TLS and the Docker packaging fix for its Python URL helper.
Older application versions are rejected, including v0.19.0 which lacked TLS.

Database TLS stays opt-in: set `database.tls.enabled: true` to enable it for all
clients. Set `database.tls.libpqMode` only to change provisioning/preflight's
verification policy; the recommended default is `verify-full`.
The v0.19.1 minimum already requires TLS support in official images, so no
separate image-support confirmation is needed. A custom tag or digest relies
on the existing `image.appVersion` declaration; operators must supply an image
that implements that version, including its TLS helper and libpq 17+.

When upgrading an earlier test chart, remove `image.databaseTlsSupported` from
saved values. The setting no longer exists and is rejected by the strict image
schema, regardless of its former true/false value.

For the supported image, the recommended application setting is **enabled**, meaning
certificate-chain and hostname verification with no plaintext fallback. Without
a CA Secret, ZAQ uses system trust. Private PostgreSQL CAs need the issuing CA
bundle, not an Ingress certificate, server private key, or password.

## Example: CA in the existing DBA Secret

Add a PEM CA bundle under `ca.crt` in the existing namespace-local DBA Secret,
alongside its externally managed `username`/`password` keys. No contents go in
Helm values. The default official image supports this configuration:

```yaml
image:
  tag: v0.19.1
database:
  host: database.example.org
  tls:
    enabled: true
    libpqMode: verify-full
    ca:
      existingSecret: zaq-dba
      key: ca.crt
  provisioning:
    existingSecret: zaq-dba
preflight:
  enabled: true
```

Prefer an immutable digest in production. The database hostname must match its
certificate's DNS identity, not an unrelated Service alias or IP address.
For system trust, leave `database.tls.ca.existingSecret: ""`. The CA key mapping
defaults to `ca.crt` and is used only with a selected Secret. With provisioning
disabled, a CA Secret can still be selected independently, including a DBA
Secret used only for its CA key; no DBA credential references are then injected.

## Shared switch and verification modes

With `database.tls.enabled: false` (the default), the application uses plaintext
and provisioning/preflight receive `PGSSLMODE=disable`. The selected libpq mode
and CA reference are unused: no CA is mounted and no CA-file environment
variables are emitted. This is explicit plaintext, not opportunistic TLS.

With TLS enabled, application connections always verify the certificate chain
and hostname, with no plaintext fallback. Both provisioning and preflight use
`database.tls.libpqMode`:

- `verify-full` (default): require TLS, validate the chain and hostname.
- `verify-ca`: require TLS and validate the chain, but not the hostname.
- `require`: require encryption, without guaranteeing hostname verification.
  Without a CA reference, do not rely on this mode for certificate validation;
  libpq additionally validates the chain when a CA bundle is supplied.

There is no `disable`, `allow`, or `prefer` choice in the mode selector. The
shared switch controls plaintext, and enabled TLS must never fall back to it.
Rancher shows the mode and CA fields only when the switch is enabled. The mode
does not weaken application TLS; a weaker preflight can succeed while the
application correctly rejects a hostname mismatch.

### Client wiring

- **Application and migrations:** `database.tls.enabled` supplies exactly
  `ZAQ_DATABASE_SSL=true` or `false`. When enabled with a custom CA, it also sets
  `ZAQ_DATABASE_SSL_CA_CERT_FILE=/etc/zaq/database-ca/ca.crt`.
- **Init container's application-owner URL check:** gets those same application
  settings. ZAQ constructs the owner URL and converts its TLS options to libpq
  for that check, preserving receipt/identity validation.
- **Provisioning DBA and separate owner/reader psql checks:** receive the shared
  libpq mode when enabled, otherwise `disable`.
- **Optional preflight:** uses that same mode for its read-only libpq check and
  forwards `PGSSLROOTCERT` into its sanitized subprocess environment. Success is
  not an Ecto TLS guarantee if the selected libpq mode is weaker than `verify-full`.

With TLS enabled, a selected CA supplies the mounted path as `PGSSLROOTCERT`.
Without one, `verify-full` uses libpq 17+'s `system` shortcut. That shortcut
rejects `verify-ca`, so this mode instead uses the published image's system CA
bundle at `/etc/ssl/certs/ca-certificates.crt`. Custom images must preserve that
bundle path when using `verify-ca` without a CA Secret. Application TLS uses
the selected CA bundle, or system trust when none is selected.

### Upgrading saved values

Remove `database.provisioning.sslMode` and `preflight.sslMode` from saved values;
the strict schema rejects both old keys, even if provisioning/preflight is off.
Move the desired libpq policy to `database.tls.libpqMode` and explicitly enable
TLS when required. Earlier defaults used libpq `prefer`, which could negotiate
TLS or fall back to plaintext. The new default switch-off behavior is plaintext
only; a TLS-required server needs `database.tls.enabled: true`.

The chart keeps `DATABASE_URL` generated by ZAQ's image entrypoint. It exposes
no credential-bearing URL override and duplicates no URL translation or SQL.
TLS names stay reserved from custom environment overrides. TLS does not change
the v0.19.1 owner `CREATEROLE` requirement or automate
[DBA upgrade maintenance](deployment.md#upgrading-the-v0180-owner-contract).

## Secret projection and lifecycle

The volume projects **only the selected CA key**, mapped to `ca.crt`, read-only
with mode `0444`. Reusing the DBA Secret does not mount its username/password
keys into the application. Init/preflight credentials retain individual
`secretKeyRef` mappings. Known DBA/runtime credential keys are rejected as CA
selections. The chart cannot inspect Secret contents: operators must select a
PEM CA bundle, not copied credentials. No Secret creation, lookup, or RBAC is
introduced.

With TLS enabled, missing CA Secrets/keys block volume setup; inspect Pod events.
A container that cannot start has no custom TLS log. Preflight retains its bounded
Job deadline
and cleanup policy. Otherwise Helm `--wait`/timeout and readiness surface startup
failures. Wrong, expired, malformed, or untrusted certificates and hostname
mismatches fail instead of downgrading verified application TLS.

CA rotation remains external. Projected files may refresh, but the chart does
not promise live pool reload or trigger a rollout on Secret-data changes.
Restart application Pods after coordinated CA rotation; subsequent init/hook
runs use the current bundle. Helm rollback does not reverse database migrations.

## Validation

Offline tests cover schema failures, image gating, CA-only DBA-Secret projection,
credential-key rejection, shared modes and switch-off behavior, form mappings,
and preflight CA forwarding. See [development checks](development.md). The opt-in
real Kind suite
uses the pinned published v0.19.1 image and an SSL-required disposable PostgreSQL,
never an existing database. `ZAQ_TLS_TEST_IMAGE` optionally selects a local
TLS-capable image implementing at least v0.19.1. It checks real migrations,
SSL sessions, readiness, provisioning, receipt restart, app-only upgrade, rejected
CA/hostname/plaintext/expired certificates, missing keys, and system trust.
It also exercises `require`/`verify-ca` provisioning/preflight and proves that
weaker libpq modes do not disable the application's hostname verification.

The recovered v0.19.1 release fixes the earlier PR build-context omission of
`scripts/database_url.py`. No local packaging workaround is needed for the
published image. Tests pin the release's multi-architecture digest rather than
relying on a mutable alias.
