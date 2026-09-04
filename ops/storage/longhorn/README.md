# DEP-042A Longhorn storage foundation

This directory defines the public, non-secret Longhorn 1.12.1 policy. It does
not authorize installation. The owner must complete every gate below before an
exact-revision, manual, no-prune Argo CD sync.

## Fixed decisions

- Longhorn Helm chart and application version: `1.12.1`.
- V1 data engine enabled; V2 disabled.
- Four explicitly configured storage workers; the constrained control-plane
  node is excluded from replicas and stateful workloads.
- The chart's `longhorn` StorageClass is suppressed. The only class introduced
  here is `longhorn-production-retain`, which is non-default, retained,
  expandable, ext4, three-replica, strict node anti-affinity, and restricted by
  stable `longhorn-storage` node and `longhorn-primary` disk-pool tags.
- The existing `local-path` StorageClass is outside this Application and must
  remain unchanged.
- The UI and manager services remain cluster-internal.

The official chart repository index records SHA-256
`c8cf4b35a9d872cd5f7e44fd26d8e6ac7c2abaee42f4e2f2a0b0ebbc6e3a6116`
for the 1.12.1 chart artifact. Re-check this digest before each fresh download.

## Read-only host gate

Download `longhornctl` only from the Longhorn 1.12.1 release, verify its
published checksum, and run it from a temporary directory before installing
prerequisites or Longhorn. Run from a cluster-reachable Linux administrator
terminal with shell tracing disabled:

```bash
set -eu
set +x
case "$(uname -m)" in
  x86_64)
    asset=longhornctl-linux-amd64
    expected=c4845f9713f3cabf55c98ce09ec1f1667216fecfbe7cd9eb032affe918724db0
    ;;
  aarch64|arm64)
    asset=longhornctl-linux-arm64
    expected=d647f3ee543fd659b3eaca781d6fbf0f96360636ae34e0e36c4cb7d6c615f908
    ;;
  *) echo "Unsupported administrator architecture" >&2; exit 1 ;;
esac
work_dir="$(mktemp -d)"
trap 'rm -rf -- "$work_dir"' EXIT
curl -sSfL -o "$work_dir/longhornctl" \
  "https://github.com/longhorn/cli/releases/download/v1.12.1/$asset"
printf '%s  %s\n' "$expected" "$work_dir/longhornctl" | sha256sum -c -
chmod 0700 "$work_dir/longhornctl"
"$work_dir/longhornctl" check preflight
```

Return only aggregate evidence. Four selected workers must pass CPU, memory,
filesystem/free-capacity, stable connectivity, mount propagation, persistent
mount, iSCSI, and NFSv4 checks. Report system-disk-backed storage as reduced
isolation. Stop if fewer than three workers pass, connectivity is unstable,
capacity reservation is unsafe, existing data ownership is unclear, or a disk
operation would be destructive.

If packages are missing, show the missing aggregate first and obtain explicit
owner approval before running `longhornctl install preflight` or equivalent
host commands. Reboot at most one worker at a time and repeat the pinned check.

### Debian-family prerequisite remediation

The selected workers currently use Debian trixie or a Debian-trixie-based
Armbian release. After explicit owner approval, remediate exactly the four
eligible workers, one at a time. Never target the constrained control plane.

First confirm the worker is Ready from the administrator terminal. On the
worker, inspect whether `multipathd.service` or `multipathd.socket` is active.
If either is active, stop for that worker and review Longhorn's multipath
compatibility guidance; do not disable or rewrite multipath automatically.

Load the required modules before package installation so `iscsi_tcp` precedes
any package-triggered `iscsid` startup:

```bash
sudo modprobe iscsi_tcp
sudo modprobe nfs
sudo modprobe dm_crypt
test -d /sys/module/iscsi_tcp
test -d /sys/module/nfs
test -d /sys/module/dm_crypt
```

Persist those exact modules:

```bash
printf '%s\n' iscsi_tcp nfs dm_crypt |
  sudo tee /etc/modules-load.d/longhorn-v1.conf >/dev/null
```

Install only the reviewed Debian packages:

```bash
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  open-iscsi \
  nfs-common \
  cryptsetup \
  bash \
  curl \
  util-linux \
  grep \
  gawk
```

Confirm `iscsi_tcp` remains loaded before enabling the service, then verify the
service and tools:

```bash
test -d /sys/module/iscsi_tcp
sudo systemctl enable --now iscsid.service
systemctl is-enabled iscsid.service
systemctl is-active iscsid.service
command -v bash curl findmnt grep awk blkid lsblk iscsiadm
grep -qw nfs4 /proc/filesystems
findmnt -no PROPAGATION /
```

The root mount must support shared propagation. Inspect the approved Longhorn
filesystem locally with `findmnt` and `df`; it must be ext4 or XFS, writable,
have a valid persistent `fstab` entry, and retain the approved capacity
reservation. Never record the path/device in Git, and never run `mkfs`, `fdisk`,
`parted`, `wipefs`, resize, or mount-changing commands under this procedure.

A reboot is not routine. A read-only inventory for this canary found existing
`local-path` volumes on three storage-eligible workers, so never drain or reboot
a selected worker without first identifying and protecting its privately mapped
local workloads. If an approved reboot is required, use a workload-aware
one-worker-at-a-time procedure: cordon, safely stop or relocate only workloads
whose recovery procedure permits it, reboot, wait for Ready, repeat the
module/service/mount checks, restore workload health, and uncordon before moving
to the next worker. Finally rerun the checksum-verified V1 preflight. Apply no
storage labels or disk annotations until all four selected workers pass.

### Built-in NFS kernel exception boundary

Longhorn CLI 1.12.1 checks Debian-family kernel modules by searching
`/proc/modules`. A kernel may instead compile NFS directly into the kernel; in
that case `modprobe nfs` succeeds, `/sys/module/nfs` exists, and NFSv4 is
available, but no dynamic `nfs` module can appear in `/proc/modules`.

Do not change or replace a kernel solely to satisfy that implementation detail.
A proposed exception requires all of this local evidence:

- `modinfo -F filename nfs` reports `(builtin)`;
- `CONFIG_NFS_FS=y` and the required NFSv4 options are `y` in the running
  kernel configuration;
- `nfs4` is present in `/proc/filesystems`;
- the pinned checker independently reports NFSv4 supported;
- `nfs-common` is installed and all other selected-worker checks pass.

The literal pinned-preflight acceptance condition remains open until the owner
explicitly approves this bounded checker exception. Record only the aggregate
exception count, never the affected node identity or kernel topology.

Owner approval was recorded on 2026-09-04 for exactly one selected worker and
only this Longhorn CLI 1.12.1 `/proc/modules` false negative. The approval is
supported by built-in NFS/NFSv4 kernel configuration, registered NFSv4
filesystem capability, installed NFS client tooling, and the checker's own
successful NFSv4 result. It does not waive any other prerequisite or acceptance
condition. Treat the four selected workers' NFS prerequisite as accepted with
one documented checker exception; do not describe the raw checker result as a
literal clean pass.

## Private node and disk bootstrap

Keep the real node names and disk paths outside Git in ignored
`config/longhorn-storage.local.json`. For each of exactly four approved nodes,
apply these reviewed concepts only after preflight passes:

- Kubernetes label `storage.faang.io/longhorn-node=true`;
- Longhorn label `node.longhorn.io/create-default-disk=config`;
- annotation `node.longhorn.io/default-node-tags` containing
  `longhorn-storage`;
- annotation `node.longhorn.io/default-disks-config` containing the approved
  persistent filesystem path, a non-zero byte reservation, scheduling enabled,
  and disk tag `longhorn-primary`.

Do not label the constrained control plane. The configuration annotation is
consumed only when the node has no existing Longhorn disk or tag configuration;
therefore validate all four mappings before the first install.

Create the ignored file from `config/longhorn-storage.example.json`. Add exactly
four private entries using this shape, replacing every placeholder only in the
ignored copy:

```json
{
  "name": "REPLACE_PRIVATE_NODE",
  "nodeTags": ["longhorn-storage"],
  "disks": [{
    "name": "longhorn-primary",
    "path": "REPLACE_PRIVATE_ABSOLUTE_PATH",
    "allowScheduling": true,
    "storageReserved": 1073741824,
    "tags": ["longhorn-primary"]
  }]
}
```

Replace the sample reservation with the privately calculated byte value. The
tracked example deliberately contains no topology. Validate without mutation:

```powershell
Copy-Item config/longhorn-storage.example.json config/longhorn-storage.local.json
# Edit only the ignored local file.
.\configure-longhorn-storage.ps1
```

The validator requires exactly four unique Ready nodes meeting the resource
floor, exactly one absolute filesystem path and non-trivial reservation per
node, and only the reviewed node/disk tag. It prints counts only. Applying the
labels and annotations is a separate mutation requiring explicit approval and
the exact guard phrase:

```powershell
.\configure-longhorn-storage.ps1 -Apply `
  -Approval DEP-042A-NODE-MAPPING-APPROVED
```

Do not run `-Apply` until all four filesystem/mount checks, network validation,
and the preflight gate (including any approved bounded exception) are complete.

The owner accepted network stability on 2026-09-04 from representative tests
covering both selected-worker link classes. Sustained aggregate throughput was
approximately 0.936 Gbit/s and 2.35 Gbit/s respectively, without interruption.
One faster-link sample reported retransmissions while retaining full throughput;
monitor retransmissions and volume recovery time during the canary. Do not put
endpoint or pair mappings in this repository.

The additional machine must be a k3s agent, never a server. If this ever needs
to be repeated, enter the server URL and join token interactively on the new
machine, keep shell tracing disabled, and run the pinned k3s installer with
`K3S_URL` and `K3S_TOKEN` supplied only to that process. Never paste or log the
token. Acceptance is five Ready nodes, aggregate architecture counts, four
nodes meeting the storage floor, and four selected nodes; do not record names.

## External backup gate

The backup target must be an independently hosted, TLS-only S3-compatible
service with a dedicated bucket and least-privilege credential. The current
MinIO community repository is archived, so MinIO is not selected automatically.
The owner must approve either a maintained distribution with acceptable
license/support/upgrade terms or the documented NFSv4 fallback before service
deployment. Do not use the in-cluster application MinIO or an NFS filesystem
under an object-store process.

The owner selected SeaweedFS under Apache-2.0 on 2026-09-04. Pin release `4.45`
and the standard `linux_amd64.tar.gz` artifact at SHA-256
`c408894668aeaa74d4f251e20b350fd72195cbe596ddc3f48658709714f7be36`.
Do not use `latest` or the large-disk build. The official artifact was downloaded
to ignored cache and independently matched this published digest. SeaweedFS is
still a single-node/single-disk backup target here, not highly available object
storage and not an off-site copy.

### Host boundary decision

The approved default is a dedicated Debian 13 amd64 VM outside k3s. On
2026-09-04 the owner explicitly approved an LXC system-container exception in
place of the dedicated VM, confirming the container is outside k3s. The weaker
host-kernel isolation relative to a dedicated VM is recorded as an accepted
residual risk for this POC. This exception does not waive any other backup
acceptance condition: pinned 4.45 digest verification, TLS-only S3, disabled
or firewalled unused catalog/admin listeners, least-privilege bucket
credential, unauthorized-access denial, persistent mount, automatic startup
after reboot, and controlled-restart recovery all remain required before the
target is accepted as Longhorn's backup destination.

### Backup host read-only gate

Use a dedicated Debian 13 amd64 host outside k3s (dedicated VM by default, or
the owner-approved LXC system container). Before installing anything,
select the existing directly attached backup filesystem interactively and run:

```bash
. /etc/os-release
printf 'OS family/version: %s %s\n' "$ID" "$VERSION_ID"
uname -m
read -r -p 'Existing backup filesystem mount: ' backup_mount
findmnt -T "$backup_mount" -o TARGET,SOURCE,FSTYPE,OPTIONS
df -hT "$backup_mount"
sudo findmnt --verify --verbose
sudo find "$backup_mount" -mindepth 1 -maxdepth 1 -printf . | wc -c
sudo stat -c 'Owner/mode: %U:%G %a' "$backup_mount"
```

Report only OS/version, architecture, filesystem type, rounded free capacity,
persistent-mount validation, top-level entry count, and whether ownership is
understood. Never paste the mount, device, UUID, address, or existing filenames.
Stop if the filesystem is NFS, is not persistent, lacks adequate capacity, or
contains data whose ownership is unclear. Do not format, repartition, resize,
move, delete, or change a mount under this gate.

After that evidence and separate host-install approval, install the binary
side-by-side under `/usr/local/lib/seaweedfs/4.45/`, using the exact release URL
and digest above. Use a dedicated unprivileged service account and persistent
data/config directories. Configure `weed mini` with native S3 TLS on its primary
S3 port, static S3 configuration, telemetry disabled, WebDAV disabled, Admin UI
disabled, and Iceberg/Lance ports disabled. Bind to the reviewed private
interface and firewall every master, filer, volume, admin, gRPC, HTTP, and
metrics listener; allow only the TLS S3 listener from the selected cluster
network and reviewed monitoring source. Do not expose it to the Internet.

Create the bucket internally before installing the Longhorn identity. The
Longhorn identity receives only `Read:<bucket>`, `Write:<bucket>`, and
`List:<bucket>`; it receives no global or bucket-admin action. Any pre-existing
administrative identity (for example a `homelab-admin` with `Admin` actions)
must not be used by Longhorn and must not be recorded in any tracked file,
Secret, or journal entry. Store its static configuration, TLS private key, and
service environment as root-owned mode `0600`; the service account receives
only the minimum read access it needs. The private CA and server certificate
must validate the exact private endpoint.

### Existing-install hardening gate

If a SeaweedFS instance is already running (for example in the approved LXC
container), do not treat its current state as accepted. Before any Longhorn
configuration, prove each of the following on the existing installation:

1. **Version and digest**: the running binary is release `4.45` and matches
   the pinned artifact SHA-256 above (compare the installed file's hash).
2. **TLS-only S3**: the S3 listener serves HTTPS with a certificate that
   validates the exact private endpoint; plaintext HTTP S3 access fails.
3. **Listener restriction**: the Iceberg catalog, Lance namespace, Admin UI,
   WebDAV, and all non-S3 management listeners are disabled in configuration
   or firewalled so they are not reachable from any network other than the
   reviewed monitoring source. Only the TLS S3 listener is reachable from the
   selected cluster network.
4. **Least-privilege credential**: a dedicated Longhorn identity exists with
   only `Read:<bucket>`, `Write:<bucket>`, and `List:<bucket>` on the backup
   bucket; no admin or global actions are granted to it.
5. **Unauthorized denial**: an anonymous request and a request with a
   non-Longhorn credential both fail against the bucket.
6. **Persistent mount**: the data directory is on a directly attached,
   persistent filesystem (not NFS) with a valid `fstab` entry; `findmnt
   --verify` reports no errors for it.
7. **Automatic startup and restart recovery**: the service is enabled to start
   after host/container reboot; perform one controlled restart and confirm the
   S3 endpoint, bucket, and an existing object all recover.

Record only sanitized aggregate results (pass/fail per gate, rounded capacity,
version string). Never record the endpoint, host identity, mount path, device,
or credential values in Git, the journal, or responses.

Create ignored client configuration from
`config/longhorn-backup.example.json`, store the CA, access key, and secret key
in separate private files, and validate without mutation:

```powershell
Copy-Item config/longhorn-backup.example.json config/longhorn-backup.local.json
# Fill only the ignored file and private referenced files.
.\validate-longhorn-backup.ps1
```

Until DEP-043 provides a private configuration owner, the external VM's root
configuration and this ignored local file are the temporary sources of truth.
Neither Jenkins nor the public repository may receive them.

Before configuring Longhorn, prove authorized TLS bucket access, rejected
anonymous/unauthorized access, persistent capacity, automatic service startup,
and recovery after a controlled VM restart. Record the single-VM/disk and
missing off-site-copy limitations.

Keep the endpoint, CA, bucket mapping, and credential outside Git. Create a
Secret only in `longhorn-system` with the Longhorn-defined keys
`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_ENDPOINTS`, and (for a private
CA) `AWS_CERT`; then update the `default` Longhorn BackupTarget with the private
S3 URL and Secret name. Ensure Jenkins service accounts cannot read that Secret.

## Protected delivery

After owner review, commit and push this feature branch and merge it by pull
request. Fetch `dev-local`, confirm its exact revision and reviewed tree, then
run the independent infrastructure Jenkins job. Its archived `revision.txt`
must equal that protected revision and all policy/schema gates must pass.

Apply the storage AppProject and Application definitions only after those
checks. Confirm automated sync is absent. The only authorized deployment is an
exact-revision manual sync of `faang-storage` with pruning disabled. Verify the
operation succeeded, all components are healthy, no unexpected resource was
removed, and `local-path` is unchanged.

## Canary, recovery, and rollback

Do not migrate MinIO or any application dependency in DEP-042A. Use only
explicitly named disposable canary resources. Record deterministic original
and restored checksums, three healthy replicas on three distinct eligible
workers, pod-replacement persistence, controlled one-worker recovery time,
backup success, restore success, backup readability after backup-service
restart, and final cleanup. Never record node names or the private backup URL.

Before persistent workloads use Longhorn, rollback may revert the reviewed Git
commit through a pull request and remove only named canary resources. Deleting
the Argo Application is not an uninstall. Argo CD lacks the required PreDelete
hook: first confirm that no Longhorn-backed workload remains, explicitly set
the deletion-confirmation safety control, run the Longhorn 1.12.1 uninstall
job to completion, and only then remove remaining resources. Preserve the
external backup bucket unless its deletion receives separate approval. Once
persistent workloads use Longhorn, uninstall is prohibited until independently
verified migration or restore elsewhere.
