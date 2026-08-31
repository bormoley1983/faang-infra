# FAANG System Infrastructure & Deployment

This repository manages the deployment and configuration of the FAANG microservices system on a Kubernetes cluster.

## Ideal Architecture (The Homelab "All-in-Cluster" Setup)
The system is designed for an optimized homelab environment where the entire CI/CD stack runs as internal workloads within the **K3s cluster**:

- **CI (Jenkins)**: Running in the `jenkins` namespace. Builds Jars and Docker images.
- **CD (ArgoCD)**: Running in the `argocd` namespace. Syncs Git manifests to the cluster.
- **Registry (Distribution)**: A TLS/authenticated POC registry in namespace `registry`, with persistent storage and topology supplied by an ignored local mapping.
- **Management (Rancher)**: Running in-cluster to provide a unified GUI for all workloads.
- **Ingress (Traefik)**: Handles private subdomain routing (`faang-account.home.arpa` in the public example).

## Project Structure
- `k8s/base/`: Standard Kubernetes manifests (Generic, tracked in Git).
- `k8s/bootstrap/`: Versioned, idempotent PostgreSQL, Kafka, Elasticsearch, and MinIO bootstrap Jobs.
- `k8s/overlays/homelab/`: Kustomize patches for your specific domain and environment.
- `ops/`: Configuration for Jenkins and ArgoCD.

## Deployment Workflows

### 1. Internal Registry Setup
Copy the safe mapping example, edit only the ignored local copy, and install the registry:
```powershell
Copy-Item .\config\homelab.example.json .\config\homelab.local.json
.\install-registry.ps1
```

See `k8s/registry/README.md` for CA trust and verification. The obsolete unauthenticated `default/docker-registry` resource has been removed.

### 2. Infrastructure Setup Validation

Validate the committed bootstrap resources without changing the cluster:

```powershell
.\setup-infra.ps1
```

Argo CD executes the four versioned bootstrap Jobs in ordered sync waves after the protected Secret and dependency endpoints are ready. See `k8s/bootstrap/README.md`. No local `latest` utility image or direct Secret manifest is used.

### 3. Automated CI/CD (The GitOps Loop)
1. **Service CI**: Each service repository runs its Gradle build and tests for pull requests and pushes to `dev-local`.
2. **Jenkins**: The delivery pipeline builds an immutable image, pushes it to the endpoint configured in Jenkins Credentials/environment configuration, and commits only that service's image digest to the environment overlay.
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
- `k8s/overlays/homelab` is now a generic `home.arpa` example and must not contain real domains, LAN addresses, node names, or external-node mappings.
- Real topology belongs in a separate private environment repository before Argo CD workload sync. Ignored workstation mappings are bootstrap-only.
- Credentials remain outside ConfigMaps and plaintext Git. Runtime secret delivery is implemented separately under DEP-043.
