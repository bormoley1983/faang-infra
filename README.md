# FAANG System Infrastructure & Deployment

This repository manages the deployment and configuration of the FAANG microservices system on a Kubernetes cluster.

## Architecture
- **Infrastructure**: Existing homelab services (Postgres, Kafka, etc.) or K8s-deployed instances.
- **Deployment**: Managed via **Kustomize** (located in `k8s/`).
- **CI/CD**: Jenkins for builds, ArgoCD for GitOps deployment.
- **Ingress**: Traefik-based subdomain routing.

## Project Structure
- `k8s/base/`: Standard Kubernetes manifests (Generic).
- `k8s/overlays/homelab/`: Environment-specific patches (Private domain settings).
- `ops/`: Jenkins and ArgoCD configuration.
- `scripts/`: Initialization scripts for DB, Kafka, and Elastic.

## Deployment Workflows

### 1. Manual Deployment (Local)
Use this for initial setup or local testing.
```powershell
# From the faang-infra folder
.\deploy.ps1
```
*Note: This script uses your local `.env` and applies the Kustomize overlay.*

### 2. Infrastructure Setup
Run this once to create the `faang` database, schemas, and Kafka topics on your existing servers.
```powershell
.\setup-infra.ps1
```

### 3. GitOps Deployment (ArgoCD)
ArgoCD monitors this repo. To deploy, simply push changes to the `main` branch.
- Manifests are located in `k8s/overlays/homelab`.
- Ensure ArgoCD is configured to point to your Git repo.

## Security & Privacy
- Sensitive credentials are in `k8s/base/secret.yaml` (Base64 encoded). **Update these before production!**
- Domain names are managed via Kustomize overlays. The `kustomization.yaml` file is excluded from Git to keep your homelab domain private.
