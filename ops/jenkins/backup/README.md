# Jenkins home backup

`backup-jenkins-home.ps1` stops the single Jenkins controller briefly, archives
the `jenkins` home PVC to `jenkins-home-backup`, verifies that the archive can be
listed, writes a SHA-256 sidecar, and restarts the controller even if backup
creation fails.

Run it from a Windows workstation whose `kubectl` context targets the intended
cluster:

```powershell
.\ops\jenkins\backup\backup-jenkins-home.ps1
```

The manifest intentionally contains no node name, address, domain, or
credential. Because both volumes use `local-path`, Kubernetes schedules the Job
on the source volume's node and the backup remains in the same node failure
domain. This is suitable as a pre-change rollback point, not as the final
disaster-recovery copy. Export the archive to encrypted off-node storage before
claiming node-loss recovery.

The archive contains Jenkins credentials and cryptographic keys. Never copy it
into Git, logs, build artifacts, or an unencrypted shared location.

## Encrypted Windows off-node export

The Windows export streams the newest verified archive directly from a
short-lived, tokenless Pod that mounts only the backup PVC read-only. Plaintext
is hashed while streaming and is never written to the workstation. The output
uses AES-256-CBC with encrypt-then-MAC HMAC-SHA256 and PBKDF2-HMAC-SHA256. A
wrong passphrase or any changed byte is rejected before restore.

Choose a destination outside the repository, preferably on a BitLocker-backed
volume that is itself backed up:

```powershell
.\ops\jenkins\backup\export-encrypted-backup.ps1 `
  -OutputDirectory 'D:\Backups\Faang\Jenkins'
```

Store the passphrase in a password manager separately from the backup. Retain
both the `.faangbak` file and its non-secret `.metadata.json` sidecar. Test
authentication and decryption into a temporary directory before considering
the export recoverable:

```powershell
.\ops\jenkins\backup\restore-encrypted-backup.ps1 `
  -EncryptedBackup 'D:\Backups\Faang\Jenkins\jenkins-home-<timestamp>.tar.gz.faangbak' `
  -OutputArchive 'D:\Backups\Faang\Restore-Test\jenkins-home.tar.gz'

$restoreArchive = 'D:\Backups\Faang\Restore-Test\jenkins-home.tar.gz'
$entries = @(tar -tzf $restoreArchive)
if ($LASTEXITCODE -ne 0) { throw 'The restored archive cannot be listed.' }

$requiredEntries = @(
  './config.xml',
  './credentials.xml',
  './secrets/master.key',
  './secrets/hudson.util.Secret'
)
$missingEntries = @($requiredEntries | Where-Object { $_ -notin $entries })
if ($missingEntries) {
  throw "The restored archive is missing required Jenkins data: $($missingEntries -join ', ')"
}

"Archive entries: $($entries.Count)"
$entries | Select-Object -First 20
```

Delete the plaintext restore-test archive after validation. The encrypted
export is an off-node copy when the Windows workstation is physically separate
from the k3s storage node. Add a second copy later on an unprivileged Proxmox
LXC with a dedicated ZFS dataset, snapshots, and a restricted restic/SFTP
account; a full VM is not required for this role.
