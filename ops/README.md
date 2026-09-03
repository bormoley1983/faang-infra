# FAANG Operations Setup (Jenkins & ArgoCD)

This directory contains the necessary manifests to set up a full CI/CD pipeline for the FAANG project.

## 1. Local Image Registry

The authenticated persistent POC registry is installed from the repository root with `install-registry.ps1`. Its real endpoint and storage-node mapping are held only in ignored `config/homelab.local.json`. See `k8s/registry/README.md`; the old unauthenticated `emptyDir` registry has been removed.

## 2. ArgoCD Application

Before the temporary public-overlay POC is synced, select exactly one
`internal` or `external` profile for every dependency in
`k8s/overlays/homelab/kustomization.yaml`, then configure the corresponding
private topology:

```powershell
Copy-Item config/homelab.example.json config/homelab.local.json # first use only
# Edit the ignored local file with the real registry and dependency mappings.
.\install-external-dependencies.ps1 -ValidateOnly
.\install-external-dependencies.ps1
```

Git owns the stable Service and selection marker for each chosen profile.
External profiles use selectorless Services; the installer creates their
physical EndpointSlices from the ignored mapping and marks only those private
objects as locally managed. It applies a profile-compatible Service during
bootstrap so Argo CD can adopt it without changing the endpoint contract. The
installer rejects a missing or doubled selection, a mode mismatch, an invalid
external address, or omitted TLS/credential policy before touching the
cluster.

The currently selected mixed profile keeps PostgreSQL, Redis, Elasticsearch,
and Kafka external and deploys MinIO internally as a restricted, digest-pinned
StatefulSet with a 20 GiB `local-path` PVC and credentials from
`faang-secrets`. Other internal profiles currently establish the stable
Service contract only; their persistent workloads are intentionally deferred
to DEP-042 and must not be selected for a live environment yet.

The local-path MinIO profile survives Pod and same-node restarts, but it is not resilient to loss of the PVC's node or disk. Treat it as the POC profile until DEP-042 adds backup/restore and reviewed failure-domain storage. The final delivery path moves environment selection and physical topology into a separate private environment repository and protects credentials with SOPS/age (DEP-041 through DEP-043).

Runtime credentials belong to `faang/faang-secrets`. Copy `k8s/overlays/homelab/secret.example.yaml` to the ignored `faang-secrets.yaml`, set real values, and apply it with `kubectl -n faang apply -f k8s/overlays/homelab/faang-secrets.yaml`. The manifest also declares `metadata.namespace: faang` so an omitted CLI namespace cannot silently update `default/faang-secrets`.

To enable GitOps sync for the whole system:
1. Ensure your local `k8s/overlays/homelab/kustomization.yaml` is correct.
2. If the `faang-infra` repository becomes private, configure its read-only repository credential in Argo CD. Do not commit that credential.
3. Apply the restricted project first, then the application:
```bash
kubectl apply -f ops/argocd/project.yaml
kubectl apply -f ops/argocd/application.yaml
```

The application watches the infrastructure repository directly on explicit `refs/heads/dev-local` and renders `k8s/overlays/homelab`. DEP-032 stages Jenkins-generated digest changes on a separate review branch and requires a pull request; Jenkins does not push directly to protected `dev-local`. `faang-main` retains `faang-infra` as a convenience submodule for reproducible local integration snapshots; its gitlink is updated deliberately during an integration snapshot, not after every service delivery, and is not the deployment revision consumed by Argo CD.

Automated sync is intentionally disabled during the deployment-remediation phases. Argo CD may compare and report desired state, but an operator must not sync until placeholder image references and secret delivery blockers are resolved. Bootstrap is represented by versioned negative-wave Jobs under `k8s/bootstrap`; automated prune/self-heal is enabled only by the later Argo delivery task after its safety acceptance checks pass.

## 3. Jenkins Pipelines

The root `Jenkinsfile` owns delivery for the account service. On trusted `dev-local` builds it:

1. builds and tests the service
2. pushes an image tagged with the service commit SHA
3. updates only the account-service tag in the homelab overlay
4. pushes the resulting GitOps commit for ArgoCD to sync

Configure these Jenkins credentials before enabling delivery:

- `docker-credentials`: username and password for the configured registry
- `github-credentials`: username/token credential with push access to the infrastructure repository

The `ops/jenkins/Jenkinsfile` is a separate infrastructure validation job. Point it at the main or infrastructure repository; it renders the homelab Kustomize overlay and never calls `kubectl apply`.

Its deployment gate runs `ops/validation/validate_deployment.py` and the negative policy tests. The validator uses pinned Kustomize/Kubernetes schema expectations, a checksum-verified kubeconform binary, service runtime contracts, and an explicit known-debt baseline. See `ops/validation/README.md` for local Windows and Linux commands. New findings and stale baseline entries fail CI.

### CI-heavy placement and caches

For homelab performance tuning, pin heavy CI/CD control workloads to the fastest amd64 worker using a private logical label.

1. Label the node once (replace `<node-name>`):

```bash
kubectl label node <node-name> workload.faang.io/ci-heavy=true --overwrite
```

2. Provision persistent Jenkins caches:

```bash
kubectl apply -f ops/jenkins/agents/cache-persistent-volumes.yaml
kubectl apply -f ops/jenkins/agents/grype-db-refresh-cronjob.yaml
```

3. Pin Argo CD repo generation and control loops:

```powershell
.\ops\argocd\pin-ci-heavy-node.ps1
```

The service-delivery Jenkins pod template now uses `workload.faang.io/ci-heavy=true` and `kubernetes.io/arch=amd64`, keeps native amd64/arm64 runtime verification stages, mounts persistent Gradle and Grype DB caches, and enforces one concurrent heavy build (`disableConcurrentBuilds()`).

## 4. Ingress Access

Ingress is part of the committed homelab overlay. For an authorized emergency/manual reconciliation, render and apply the exact same path watched by Argo CD:

```bash
kubectl apply -k k8s/overlays/homelab
```

Normal delivery is performed by Argo CD. Do not apply `k8s/base` directly; its hosts and external endpoints are deliberately non-routable portable defaults.
