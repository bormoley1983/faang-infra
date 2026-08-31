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
