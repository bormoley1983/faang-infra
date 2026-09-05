# DEP-042C PostgreSQL operator boundary

This directory configures the operator layer only. It installs CloudNativePG
chart `0.29.0` (application `1.30.0`) and Barman Cloud CNPG-I chart `0.8.0`
(application `v0.15.0`) through a manual Argo CD application in `cnpg-system`.
All operator, plugin, and plugin-sidecar images are pinned to multi-architecture
OCI index digests in the adjacent values files.

The Application declares `cnpg-system` itself and uses server-side apply. CNPG
CRD schemas are too large for Kubernetes' client-side apply annotation limit;
do not remove that sync option.

It intentionally does **not** create a CloudNativePG `Cluster`, an `ObjectStore`,
a database PVC, a backup bucket, a credential, a `postgres-main` selector, or a
cutover. The active external PostgreSQL profile stays authoritative until a
separate migration rehearsal and owner-approved maintenance window.

The plugin depends on cert-manager, which must be Ready before the manual,
no-prune operator sync. It provides PostgreSQL-native physical base backups and
continuous WAL archive; an eventual recovery must bootstrap a newly named
isolated cluster and verify application data. Do not use a Longhorn volume
attachment or PVC copy as a substitute for that proof.

The live cluster has no `VolumeSnapshotClass`, so CSI snapshot recovery is not
part of this first delivery. A future database Cluster must use only
`longhorn-production-retain`, a dedicated least-privilege SeaweedFS S3 backup
identity/prefix, explicit capacity/anti-affinity, and a separately rendered
recovery manifest.

## Disposable canary order

1. Register the two manual canary Applications after CI; do not sync the
   Cluster Application yet.
2. Manually no-prune sync `faang-postgresql-canary-foundation` to create only
   its namespace.
3. Copy the example configuration to the ignored local path, supply a new
   external SeaweedFS bucket/prefix plus distinct runtime and provisioning
   identities, then validate it. Run `configure-postgresql-backup.ps1 -Apply`
   only with owner approval; it creates the bucket if necessary and applies
   only the canary runtime Secret/ObjectStore.
4. Manually no-prune sync `faang-postgresql-canary`. It creates the one-instance
   CNPG cluster only after the ObjectStore reports Ready.

The foundation and Cluster Applications intentionally remain separate so a
missing backup boundary can never be bypassed by a combined first sync.
