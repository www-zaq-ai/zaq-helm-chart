# Storage

See the [storage values](values.md#storage) for configurable fields. PostgreSQL
persistence belongs to the external database deployment, not this chart.

## Volume and permissions

The application mounts `/zaq/volumes`; it runs with UID `1000`. The default
supplemental filesystem group is `1000`, without assuming the image's primary
GID. Your CSI/NFS driver must honor the chosen access modes and permissions.
No application PVC is mounted into the provisioning init container.

A mount does not register a ZAQ Disk data source. Configure that in Back Office
after [first login](deployment.md#first-login).

## Select a StorageClass or existing PVC

- `persistence.storageClass: null`: omit the field and use cluster defaults.
- `persistence.storageClass: longhorn`: select an existing named class.
- `persistence.storageClass: ""`: explicitly request no class, typically for a
  matching pre-provisioned PV.
- `persistence.existingClaim: customer-a-data`: reuse a PVC in the namespace;
  leave `storageClass` unset. The existing PVC's size, class, annotations, and
  access modes remain externally managed, not changed by this chart.
- `persistence.enabled: false`: use ephemeral `emptyDir`; Pod deletion loses
  application files.

The chart does not create StorageClasses. Ensure sufficient capacity and a
compatible access mode. The default one-replica, Recreate deployment avoids
overlapping RWO attachment; see [replica safety](deployment.md#identity-and-replica-safety)
before scaling.

## Retention and reuse

Chart-created PVCs default to `helm.sh/resource-policy: keep`. After uninstall,
set `existingClaim` to the retained PVC name when reinstalling. Helm no longer
manages a retained PVC after uninstall. To allow intentional deletion, set
`persistence.retain: false` **before** uninstalling; the PV reclaim policy still
determines what happens to backing storage.

Existing PVCs are always externally managed. See
[uninstallation](operations.md#uninstall) for other retained resources.

## Expansion and backups

Expansion requires a StorageClass/CSI driver with expansion support. Increase
the requested size and follow the driver's filesystem expansion procedure; do
not decrease it. StorageClass/access-mode changes usually require a new PVC
and an explicit data migration.

Back up application files and PostgreSQL separately, retaining the encryption
keys needed to read protected configuration. Neither Helm nor this chart
provides backups or restores data during a rollback.
