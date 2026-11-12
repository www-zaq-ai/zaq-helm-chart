# Operations

For initial setup and application-version policy, see [deployment](deployment.md).
Storage lifecycle details are in [storage](storage.md).

## Networking

Service: ClusterIP, default port `4000`, targeting container port `4000`.
Ingress is optional and terminates TLS outside ZAQ. Its hostname must match
`app.host`. Configure your proxy to overwrite `X-Forwarded-Proto`, preserve the
public hostname, support WebSockets, and restrict direct backend access.
Cluster-specific network policies remain an operator responsibility.

Enabled Ingresses default to `50M` request-body limits via
`nginx.ingress.kubernetes.io/proxy-body-size` and
`nginx.org/client-max-body-size`, plus `"3600"`-second ingress-nginx
`proxy-read-timeout` and `proxy-send-timeout`. These are controller settings,
not application upload limits or a guaranteed request lifetime. Each controller
applies its supported annotations. Edit/override these defaults or add further
annotations in Rancher's form or `ingress.annotations`.

Rancher's form supports Ingress annotations and a single-host TLS checkbox plus
Secret-name field (`ingress.tlsEnabled`/`ingress.tlsSecretName`). Advanced users
can instead configure `ingress.tls` in Values YAML; the two modes are mutually
exclusive. See [configuration examples](rancher.md#ingress-annotations-and-tls).

The chart does **not** generate TLS certificates or install an issuer. Reference
an externally supplied TLS Secret in the release namespace, or configure
cert-manager externally and supply its issuer annotation; cert-manager then
creates/renews the named Secret. DNS must point to the Ingress controller and
the certificate issuer's challenge must succeed. Helm application readiness
does not establish certificate issuance or end-to-end HTTPS availability.

For temporary local access without Ingress:

```sh
kubectl -n customer-a port-forward service/customer-a-zaq 4000:4000
```

Then visit `http://localhost:4000/bo/login`. Do not expose this port-forward on
external interfaces. HTTP ingress TLS is separate from the
[application database TLS limitation](deployment.md#database-transport-limitation).

## Health checks

All probes request `/channels/health` over HTTP with
`X-Forwarded-Proto: https`. This avoids production HTTPS redirection without
changing the application's HTTPS enforcement. Integration tests assert status
**200**, not a redirect. The startup probe allows 15 minutes by default; tune it
and the Helm timeout for large migrations. Liveness is delayed until startup
succeeds. The endpoint reports HTTP availability, not database/provider health.
See [probe settings](values.md#health-probes).

## Optional prerequisite preflight

Set `preflight.enabled: true` to run a **pre-install/pre-upgrade Helm hook Job**.
It is off by default and reuses the ZAQ image without loading the application.
It executes only `BEGIN READ ONLY; SELECT 1; ROLLBACK;` through libpq/psql:

- Provisioning enabled: authenticate the DBA against the maintenance database.
  The target database and owner/reader roles may not exist yet.
- Provisioning disabled: authenticate the existing owner against the target DB.

The check accepts external/cross-namespace PostgreSQL endpoints. It does not look
for a PostgreSQL Pod/Service in the release namespace and makes no Kubernetes API
calls. Only its Secret references are namespace-local. It uses the namespace's
default ServiceAccount without an API token because the chart-created account
does not exist yet at pre-install; no additional RBAC is created.
The Helm/Rancher installer still needs permission to create/watch/delete Jobs;
this is separate from the Job container's lack of API access.

```yaml
preflight:
  enabled: true
  activeDeadlineSeconds: 120
  connectTimeoutSeconds: 10
  ttlSecondsAfterFinished: 3600
```

All required runtime keys (plus DBA/reader keys when provisioning) are referenced
individually with `secretKeyRef`. A missing Secret/key prevents container startup;
**it cannot produce a custom container message**. In Rancher inspect the Job's
Pod events for missing Secret/key errors. The Job's active deadline bounds even
this pending-start state, eventually reporting Job failure/`DeadlineExceeded` to
the Helm hook. Helm waits for hooks even without `--wait`; use `--wait` as well
to detect later application/migration failures.

The Job deadline is limited to 15–600 seconds; its connection/query timeout must
be shorter (1–30 seconds). Image pulls and scheduling consume this deadline;
allow enough for cold nodes. The Helm/Rancher timeout must cover the hook,
termination allowance, and subsequent application startup. A failed
pre-upgrade hook stops that upgrade before ordinary workload changes; it does
not turn existing application readiness into a database health guarantee.

Successful hooks are deleted immediately. Failed Jobs remain for inspection,
then expire after their configured TTL (default one hour, 60–86400 seconds), or
are deleted before the next hook attempt. Hooks are not ordinary release-owned
resources and may remain after uninstall until that cleanup occurs.

Once a container starts, its logs contain only a generic connectivity result;
connection URLs, credentials, SQL output, and database-client errors are not
printed. Inspect endpoint/Secret mappings and use protected DBA diagnostics for
details. Fix configuration and retry; never delete migration ledgers or receipts.

This is not a provisioning/migration dry run or full readiness test. It does not
check role/extension eligibility, bootstrap receipts, storage, ingress, or key
contents. The original terminating init container and migrations-before-server
entrypoint remain authoritative. ZAQ boot validates application keys; malformed
values can pass preflight presence checks and still correctly fail application
startup. Preflight success cannot prevent a later connectivity failure.

`preflight.sslMode` configures only this libpq client, separately from the init
container setting. **Neither enables Ecto/application database TLS**; see the
[released-image limitation](deployment.md#database-transport-limitation).

## Upgrade

1. Back up PostgreSQL, application files, and key-management records.
2. Review ZAQ release notes and [migration/version compatibility](deployment.md#application-compatibility).
   Keep database/role identities and application encryption keys stable.
3. Upgrade with explicit chart/image versions and `--wait --timeout 20m`, using
   the same installation command and reviewed values.
4. Check Deployment readiness, login, data access, and application behavior.

Default Recreate rollouts cause downtime. An init container gates only its own
Pod; coordinate provisioning and migrations separately before scaling.

## Credential rotation

The init container validates passwords on each new Pod; editing a Secret is
**not** database password rotation. Coordinate DBA changes and Secret updates
with downtime as required. Secret content changes do not automatically trigger
a Deployment rollout; restart it explicitly after a coordinated change.

Keep application encryption keys stable. Existing encrypted configuration
requires the original key; `app.encryptionKeyId` is rotation metadata, not a
replacement key. See [Secret requirements](deployment.md#pre-existing-secrets).

## Rollback and recovery

Helm rollback restores Kubernetes configuration only. It does not reverse
migrations or restore PostgreSQL or files. Use an older image only if its schema
compatibility is confirmed; otherwise use a reviewed forward fix or coordinated
backup restoration. Never delete receipts or migration ledgers as recovery.
Do not assume `--atomic` can undo a database schema change.

## Uninstall

```sh
helm uninstall customer-a --namespace customer-a --wait
```

This removes chart workloads, Service, Ingress, and created ServiceAccount.
External Secrets and PostgreSQL data/roles remain. Existing PVCs are untouched;
chart-created PVCs follow the [retention setting](storage.md#retention-and-reuse).
No database cleanup or credential revocation occurs automatically.
An enabled preflight's failed hook Job can remain until its TTL, as described
[above](#optional-prerequisite-preflight).

## Troubleshooting

- Missing Secret/key: inspect Pod events and reference names; never print Secret
  data or container environments.
- Initialization failure: inspect `kubectl logs <pod> -c provision-db`, treating
  diagnostic output as sensitive. Verify DBA rights, extensions, identities,
  supplied passwords, and [receipt/adoption status](deployment.md#database-provisioning-and-startup).
- Migration failure: ZAQ never becomes ready. Inspect application diagnostics
  securely and request DBA/application review; do not assume rollback is safe.
- Pending PVC: verify StorageClass name, provisioner, access modes, capacity,
  and any wait-for-consumer scheduling constraints. See [storage](storage.md).
- Redirect loops: check public hostname, TLS termination, and overwritten
  forwarded headers. Health probes must carry the documented header.

## Production review

Remote database TLS, safe bootstrap Back Office exposure, backups, node-level
storage permissions, and multi-replica operation need explicit production
review. This chart does not remove those upstream/operator constraints. Start
with the [deployment prerequisites](deployment.md#prerequisites) and
[first-login warning](deployment.md#first-login).
