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

## 3. Jenkins CI Pipeline
1. Create a Pipeline job in Jenkins.
2. Point it to your Git repository and set the script path to `faang-infra/ops/jenkins/Jenkinsfile`.
3. **Important**: Add a Global Environment Variable in Jenkins named `BASE_DOMAIN` with your domain (e.g., `office.aviv.com.ua`).
4. Ensure Jenkins has the `docker-credentials` and `k3s-kubeconfig` credentials set up.

## 4. Ingress Access
After services are deployed, apply the Ingress rules:
```bash
# Locally (uses variable substitution)
.\deploy.ps1 
```
Or via ArgoCD if you choose to track the overlay in Git.
