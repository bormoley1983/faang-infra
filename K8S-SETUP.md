# Kubernetes operator access

Use an organization-approved kubeconfig and canonical API hostname. This guide
does not distribute kubeconfigs, private addresses, host-file entries, client
certificates, or TLS-bypass instructions.

## Preconditions

- `kubectl` is installed from a trusted source.
- An authorized least-privilege kubeconfig was supplied through the protected
  access procedure.
- The configured API hostname validates against the kubeconfig CA. Stop on a
  certificate-name or trust error; do not use `--insecure-skip-tls-verify`.

## Connect and verify

In PowerShell, point only the current shell at the approved kubeconfig:

```powershell
$env:KUBECONFIG = '<approved-kubeconfig-path>'
kubectl config current-context
kubectl get nodes
kubectl -n argocd get applications.argoproj.io
```

Do not permanently add a privileged kubeconfig path to a shared profile, edit
API-server values in copied credentials, or commit kubeconfig material.

## Delivery boundary

Kubernetes access is for observation and explicitly approved manual Argo
operations. Normal delivery is Git review → Jenkins validation/proposal →
manual Argo refresh and scoped sync.

Do not run `deploy.ps1`, `deploy.sh`, or `kubectl apply -k
k8s/overlays/homelab` as the normal delivery route. See the repository-level
[deployment guide](../README_DEPLOY.md) and `ops/validation/README.md`.
