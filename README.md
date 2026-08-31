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
- `k8s/bootstrap/`: Versioned, idempotent PostgreSQL, Kafka, Elasticsearch, and MinIO bootstrap Jobs.
- `k8s/overlays/homelab/`: Kustomize patches for your specific domain and environment.
- `ops/`: Configuration for Jenkins, ArgoCD, and the internal Docker Registry.

## Deployment Workflows

### 1. Internal Registry Setup
Before any builds can happen, the internal storage must be available:
```powershell
kubectl apply -f ops/docker-registry.yaml
```

### 2. Infrastructure Setup Validation

Validate the committed bootstrap resources without changing the cluster:

```powershell
.\setup-infra.ps1
```

Argo CD executes the four versioned bootstrap Jobs in ordered sync waves after the protected Secret and dependency endpoints are ready. See `k8s/bootstrap/README.md`. No local `latest` utility image or direct Secret manifest is used.

### 3. Automated CI/CD (The GitOps Loop)
1. **Service CI**: Each service repository runs its Gradle build and tests for pull requests and pushes to `dev-local`.
2. **Jenkins**: The delivery pipeline builds an immutable image, pushes it to `docker-registry:5000`, and commits only that service's image tag to the homelab overlay.
3. **Infrastructure CI**: `ops/jenkins/Jenkinsfile` renders the overlay to catch invalid Kustomize configuration; it does not deploy directly.
4. **ArgoCD**: Watches the `faang-infra` `dev-local` branch and `k8s/overlays/homelab` directly, then performs the cluster sync. The `faang-main` submodule pointer is updated only for deliberate integration snapshots and is not used as the deployment revision. Apply the restricted project and app once to start the sync:
   ```powershell
   kubectl apply -f ops/argocd/project.yaml
   kubectl apply -f ops/argocd/application.yaml
   ```

   Automated sync remains disabled while the initial deployment blockers are being closed. Applying the Application registers and compares the desired state but does not authorize rollout.

Hashtag Service has no Kubernetes resource by design. Add one only after the repository contains a deployable application, Dockerfile, configuration contract, and health endpoints.

### 4. Manual/Emergency Deployment
If you need to bypass CI/CD and deploy from your workstation:
```powershell
.\deploy.ps1
```

## Configuration ownership

- `k8s/base` contains portable resource structure and deliberately non-routable dependency/ingress defaults.
- `k8s/overlays/homelab` owns the committed homelab dependency endpoints and complete ingress hostnames.
- Argo CD and emergency `kubectl apply -k` deployment render the same overlay; there is no shell-time substitution.
- Credentials remain outside ConfigMaps and plaintext Git. Runtime secret delivery is implemented separately under DEP-043.
