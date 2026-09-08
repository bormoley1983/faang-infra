# FAANG operations

This directory contains narrowly scoped operational tooling and runbooks. The
normal delivery path is reviewed Git → Jenkins validation/proposal → manual,
scoped Argo CD reconciliation. It is not direct `kubectl apply`.

## Safety rules

- Keep Argo automated sync, prune, self-heal, force, and replace disabled.
- Do not create plaintext runtime Secrets or physical dependency mappings from
  public repository files. The private SOPS/age environment source owns them.
- Do not use `kubectl apply -k k8s/overlays/homelab` for routine delivery.
- Stop on an unexpected prune, shared-resource warning, owner mismatch, or
  diff outside the approved resource set.

## Runbooks

| Topic | Reference |
| --- | --- |
| GitOps image proposal and rollback | [`gitops/README.md`](gitops/README.md), [`gitops/workload-rollback.md`](gitops/workload-rollback.md) |
| Argo applications and projects | [`argocd/`](argocd/) manifests; inspect the affected Application before a manual sync |
| Jenkins pipelines and recovery | [`jenkins/README.md`](jenkins/README.md), [`jenkins/backup/README.md`](jenkins/backup/README.md) |
| Deployment and post-release evidence | [`validation/README.md`](validation/README.md) |
| Dependency profiles | [`../k8s/components/dependencies/README.md`](../k8s/components/dependencies/README.md) |
| Bootstrap jobs | [`../k8s/bootstrap/README.md`](../k8s/bootstrap/README.md) |
| Registry trust | [`../k8s/registry/README.md`](../k8s/registry/README.md) |
| Private ingress and TLS | [`gitops/private-ingress-tls.md`](gitops/private-ingress-tls.md) |

## Ownership summary

`faang-runtime-foundation` owns namespace/configuration;
`faang-selected-dependencies` owns selected aliases and markers;
`faang-bootstrap` owns completed initialization resources; and
`faang-workloads` owns the application Deployments, Services, and Ingress.
`faang-system` retains only local-backup `s3-main`. Stateful, storage,
object-storage, and Secrets Applications remain independently scoped.

Never infer that an internal endpoint is a backup guarantee, or that Git
rollback reverses migrations, external dependency changes, Secret changes, or
persistent data. Those require their dedicated approved runbooks.
