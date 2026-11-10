# Operations

For initial setup and application-version policy, see [deployment](deployment.md).
Storage lifecycle details are in [storage](storage.md).

## Networking

Service: ClusterIP, default port `4000`, targeting container port `4000`.
Ingress is optional and terminates TLS outside ZAQ. Its hostname must match
`app.host`. Configure your proxy to overwrite `X-Forwarded-Proto`, preserve the
public hostname, support WebSockets, and restrict direct backend access.
Cluster-specific network policies remain an operator responsibility.

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
