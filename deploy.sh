#!/bin/bash
# Load Configuration from .env
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Default if not set
USE_EXISTING_INFRA=${USE_EXISTING_INFRA:-true}
echo "Starting FAANG System Deployment..."
echo "Mode: $( [ "$USE_EXISTING_INFRA" = "true" ] && echo 'Using Existing Network Infra' || echo 'Deploying New Infra in K8s' )"

# 1. Build Initialization Image
docker build -f Dockerfile.init -t faang-init-utils:latest .

# 2. Infrastructure Logic
if [ "$USE_EXISTING_INFRA" = "false" ]; then
    echo "Deploying New Infrastructure..."
    kubectl apply -f k8s/infra/
fi

# 3. Run Initialization Job
echo "Running Initialization Job..."
kubectl delete job faang-init-job --ignore-not-found
kubectl apply -f k8s/base/secret.yaml
kubectl apply -f k8s/base/configmap.yaml
kubectl apply -f k8s/init-job.yaml
kubectl wait --for=condition=complete job/faang-init-job --timeout=300s

# 4. Deploy the exact same committed overlay rendered by Argo CD
echo "Deploying FAANG System via Kustomize..."
kubectl apply -k k8s/overlays/homelab

echo "Deployment Complete!"
echo "Check status with: kubectl get pods"
