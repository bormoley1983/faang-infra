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
2. Update the `repoURL` in `ops/argocd/application.yaml`.
3. Apply the application:
```bash
kubectl apply -f ops/argocd/application.yaml
```

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

## 4. Ingress Access
After services are deployed, apply the Ingress rules:
```bash
# Locally (uses variable substitution)
.\deploy.ps1 
```
Or via ArgoCD if you choose to track the overlay in Git.
