# SeaweedFS application object storage

This is the DEP-042B in-cluster application object store.
It is a separate SeaweedFS S3 service backed by retained Longhorn volumes; it
is not the external SeaweedFS service used for Longhorn backups.

The initial topology has one master, filer, volume server, and S3 gateway.
Longhorn replicates each persistent volume across three eligible workers. This
is not SeaweedFS protocol-level HA. Scale SeaweedFS components and select a
durable multi-filer metadata store only through a separate reviewed change.

No public ingress, LoadBalancer, NodePort, admin UI, SFTP, COSI, worker, or
chart-created credential is enabled. The S3 gateway accepts traffic only from
the `faang` namespace through the chart NetworkPolicies.

## Runtime S3 identity

Copy `config/seaweedfs-app-s3.example.json` to the ignored
`config/seaweedfs-app-s3.local.json`. Point its credential fields at separate,
non-empty private files and set only the required application buckets. Do not
reuse the Longhorn-backup credential or its bucket.

Validate without mutation:

```powershell
./validate-seaweedfs-app-s3.p
./configure-seaweedfs-app-s3.ps1
```

After explicit owner approval, create the runtime-only identity Secret:

```powershell
./configure-seaweedfs-app-s3.ps1 -Apply
```

The script passes the identity configuration to Kubernetes through a temporary
file and deletes that file afterwards. It never prints credentials, bucket
names, or the rendered Secret. Jenkins must not receive either the local
configuration or the credential files.

## Delivery and rollback

After protected-branch review and a successful exact-revision infrastructure
Jenkins build, create the target namespace under explicit owner approval, then
create the runtime identity Secret, then bootstrap the reviewed Argo
AppProject/Application explicitly. Keep automated sync absent and use only an
exact-revision manual sync with pruning disabled. This order prevents the S3
gateway from ever starting without its required identity configuration.

Do not change the active S3 profile or application endpoint in the same
operation as the first SeaweedFS installation. Verify the SeaweedFS components,
three Longhorn replicas per persistent volume, authenticated required-bucket
access, and unauthorized denial first. A later approved change may redirect
applications and retire the legacy in-cluster object store workload.

For a failed initial installation, do not delete the Argo Application as a
substitute for data cleanup. Confirm no application traffic or bucket data is
present, then use the chart's documented uninstall path and delete retained
PVCs/PVs only through an explicitly approved procedure.

## Restore rehearsal

Treat the Master, Filer, and Volume claims as one consistency group. Stop S3
writers and all SeaweedFS components before taking the three Longhorn
snapshots, then restore all three claims into an isolated namespace.

For the pinned chart, an `existingClaim` Filer claim is not mounted at
`/data` automatically. Apply `restore-values.yaml` with the restore-specific
claim overrides so the Filer receives the restored LevelDB metadata. Restart
the isolated S3 gateway after the Filer is mounted, then retrieve a known
pre-backup sentinel and verify its checksum before declaring recovery passed.
