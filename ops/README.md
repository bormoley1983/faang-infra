# FAANG Operations Setup (Jenkins & ArgoCD)

This directory contains the necessary manifests to set up a full CI/CD pipeline for the FAANG project.

## 1. Local Image Registry
Before building, deploy the local registry where Jenkins will push images:
```bash
kubectl apply -f ops/docker-registry.yaml
```

## 2. ArgoCD Application
To enable GitOps sync for the whole system:
1. Ensure your local `k8s/overlays/homelab/kustomization.yaml` is correct.
2. If the `faang-infra` repository becomes private, configure its read-only repository credential in Argo CD. Do not commit that credential.
3. Apply the restricted project first, then the application:
```bash
kubectl apply -f ops/argocd/project.yaml
kubectl apply -f ops/argocd/application.yaml
```

The application watches `https://github.com/bormoley1983/faang-infra.git` directly on the explicit `dev-local` branch and renders `k8s/overlays/homelab`. Jenkins pushes desired-image updates to that same repository and branch. `faang-main` retains `faang-infra` as a convenience submodule for reproducible local integration snapshots; its gitlink is updated deliberately during an integration snapshot, not after every service delivery, and is not the deployment revision consumed by Argo CD.

Automated sync is intentionally disabled during the deployment-remediation phases. Argo CD may compare and report desired state, but an operator must not sync until placeholder image references, runtime configuration, bootstrap, and secret delivery blockers are resolved. Automated prune/self-heal is enabled only by the later Argo delivery task after its safety acceptance checks pass.

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

## 4. Ingress Access
After services are deployed, apply the Ingress rules:
```bash
# Locally (uses variable substitution)
.\deploy.ps1 
```
Or via ArgoCD if you choose to track the overlay in Git.
