# FAANG Social Network - Infrastructure

This repository manages the core infrastructure, initialization scripts, and Kubernetes deployment configurations for the FAANG microservices ecosystem.

> **Note:** For local development using Docker Compose and CI/CD pipelines, please refer to the [faang-main (Root)](../) repository.

---

## 1. Infrastructure Initialization

The ecosystem requires specific schemas, Kafka topics, and Elasticsearch indices to be created before services start.

### Initialization Utility Image
A custom Docker image (`Dockerfile.init`) packages all necessary CLI tools (`psql`, `kafka-topics`, `curl`) and scripts.
```bash
docker build -t your-registry/faang-init-utils:latest -f Dockerfile.init .
```

### Initialization Scripts
*   **`init-postgres.sh`**: Creates schemas for all microservices in the target database.
*   **`init-kafka.sh`**: Pre-creates required topics with defined partitions and replication factors.
*   **`init-elastic.sh`**: Configures Elasticsearch indices and mappings.

All scripts are configurable via environment variables (`POSTGRES_HOST`, `KAFKA_BOOTSTRAP_SERVERS`, etc.).

---

## 2. Kubernetes Deployment (Production/Homelab)

The `k8s/` directory contains manifests for deploying to a Kubernetes cluster (managed via Rancher/ArgoCD).

### Configuration & Secrets
1.  **`configmap.yaml`**: Update with your external server URLs (Postgres host, Kafka brokers, etc.).
2.  **`secret.yaml`**: Update with your credentials (passwords, access keys).

### Deployment Steps
1.  **Apply Configuration**:
    ```bash
    kubectl apply -f k8s/configmap.yaml
    kubectl apply -f k8s/secret.yaml
    ```
2.  **Run Initialization Job**:
    Executes the init scripts against your external servers.
    ```bash
    kubectl apply -f k8s/init-job.yaml
    ```
3.  **Deploy Services**:
    Each service manifest in `k8s/services/` (e.g., `account-service.yaml`) defines its own Deployment and ClusterIP Service, injecting environment variables from the shared ConfigMap/Secret.
    ```bash
    kubectl apply -f k8s/services/
    ```

