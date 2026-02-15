# FAANG System Infrastructure & Deployment

This repository manages the deployment and configuration of the FAANG microservices system on a Kubernetes cluster.

## Ideal Architecture (The Homelab "All-in-Cluster" Setup)
The system is designed for an optimized homelab environment where the entire CI/CD stack runs as internal workloads within the **K3s cluster**:

- **CI (Jenkins)**: Running in the `jenkins` namespace. Builds Jars and Docker images.
- **CD (ArgoCD)**: Running in the `argocd` namespace. Syncs Git manifests to the cluster.
- **Registry (Docker Registry)**: Running in the `default` namespace at `docker-registry:5000`. Stores all FAANG images.
- **Management (Rancher)**: Running in-cluster to provide a unified GUI for all workloads.
- **Ingress (Traefik)**: Handles subdomain routing (`faang-account.office.aviv.com.ua`).

## Project Structure
- `k8s/base/`: Standard Kubernetes manifests (Generic, tracked in Git).
- `k8s/overlays/homelab/`: Kustomize patches for your specific domain and environment.
- `ops/`: Configuration for Jenkins, ArgoCD, and the internal Docker Registry.
- `scripts/`: Initialization scripts for DB, Kafka, and Elastic.

## Deployment Workflows

### 1. Internal Registry Setup
Before any builds can happen, the internal storage must be available:
```powershell
kubectl apply -f ops/docker-registry.yaml
```

### 2. Infrastructure Setup (Configuration)
Run this once to create the `faang` database, schemas, and Kafka topics on your existing servers.
```powershell
.\setup-infra.ps1
```

### 3. Automated CI/CD (The GitOps Loop)
1. **Jenkins**: Listens for pushes to GitHub. It uses the `ops/jenkins/Jenkinsfile` to build and push images to `docker-registry:5000`.
2. **ArgoCD**: Listens for manifest changes. Apply the app once to start the sync:
   ```powershell
   kubectl apply -f ops/argocd/application.yaml
   ```

### 4. Manual/Emergency Deployment
If you need to bypass CI/CD and deploy from your workstation:
```powershell
.\deploy.ps1
```

## Security & Privacy
- **Domain Privacy**: Domain names are managed via Kustomize placeholders `${BASE_DOMAIN}`.
- **Local Config**: Your actual domain is stored in a private `.env` file and applied on-the-fly during deployment, ensuring `office.aviv.com.ua` never leaks to GitHub.
