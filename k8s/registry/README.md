# POC registry

CNCF Distribution Registry 3.1.1 is the POC milestone. The committed manifests contain no private hostname, domain, node name, or LAN address. Local topology comes from the ignored `config/homelab.local.json`; copy the tracked `config/homelab.example.json` to create it.

Long-term Argo CD reconciliation must read the real environment overlay from a separate private Git repository. An ignored workstation file is appropriate for bootstrap, but it is not an Argo CD source of truth.

## Endpoint and persistence

- The installer allocates the configured private MetalLB address and issues a certificate for that address plus the optional local DNS name.
- The committed Deployment selects the generic node label `faang.io/registry-storage=true`; the installer applies that label to the locally configured storage node.
- Storage is a 50 GiB `local-path` PVC. It survives Pod replacement and restart of its bound node, but not loss of that node or disk. An external backup remains mandatory before production use.

## Credentials

`install-registry.ps1` creates a random password on first use and stores it only in Kubernetes:

- `registry/registry-client-credentials`: client username/password;
- `registry/registry-auth`: bcrypt htpasswd entry and registry HTTP secret;
- `faang/faang-registry-pull`: namespace-scoped Docker pull configuration.

The default username is `jenkins`. Distribution htpasswd authentication does not provide repository-scoped authorization, so this is a POC credential rather than the final robot-account model. Jenkins Credentials receives it during DEP-030; never copy it into Git or pipeline environment files.

The transient Apache helper used to create the bcrypt entry is versioned and pinned by multi-platform digest; it does not run in the cluster.

Install or reconcile:

```powershell
Copy-Item .\config\homelab.example.json .\config\homelab.local.json
# Edit only the ignored local copy.
.\install-registry.ps1
```

## Trust the private CA

Exporting the public CA is safe; never export `tls.key`:

```powershell
$ca = kubectl -n registry get secret registry-ca -o jsonpath="{.data.tls\.crt}"
[IO.File]::WriteAllBytes("faang-registry-ca.crt", [Convert]::FromBase64String($ca))
$config = Get-Content .\config\homelab.local.json -Raw | ConvertFrom-Json
$endpoint = "$($config.registry.address):$($config.registry.port)"
```

On every k3s server/agent, copy the CA to `/etc/rancher/k3s/registry-certs/faang-registry-ca.crt` and merge this entry into `/etc/rancher/k3s/registries.yaml`, replacing `<registry-endpoint>` with the local `$endpoint` value:

```yaml
mirrors:
  "<registry-endpoint>":
    endpoint:
      - "https://<registry-endpoint>"
configs:
  "<registry-endpoint>":
    tls:
      ca_file: /etc/rancher/k3s/registry-certs/faang-registry-ca.crt
```

Restart `k3s-agent` on agents and `k3s` on the server one node at a time. Authentication is supplied by the namespace pull Secret, not by node files. Install the same CA in Docker Desktop and Jenkins build agents before pushing.

## Verification

An unauthenticated request must return `401`; an authenticated request must return `200`:

```powershell
curl.exe --cacert .\faang-registry-ca.crt --ssl-no-revoke -I "https://$endpoint/v2/"

$credential = kubectl -n registry get secret registry-client-credentials -o json | ConvertFrom-Json
$username = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($credential.data.username))
$password = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($credential.data.password))
$password | docker login $endpoint --username $username --password-stdin
```

The installer generates an ignored smoke manifest from the tracked template:

```powershell
kubectl apply -f .\k8s\registry\tests\pull-smoke.local.yaml
kubectl -n faang get pods dep020-pull-amd64 dep020-pull-arm64 -o wide
kubectl -n faang delete pods dep020-pull-amd64 dep020-pull-arm64
```

## Retention, backup, and recovery

- Promotion references digests; Git-SHA tags are aliases only.
- Deletion is enabled, but garbage collection runs only during a reviewed maintenance window with pushes stopped and a verified backup available.
- Back up `/var/lib/registry` from the PVC to storage outside the selected registry node.
- Recovery recreates the PVC on the intended labeled node, restores the directory with ownership `1000:1000`, reapplies the generic Kustomization and protected Secrets, and verifies known image digests before Jenkins publishing resumes.
- Do not delete the legacy registry until authenticated push/pull, mixed-architecture, and persistence tests all pass.
