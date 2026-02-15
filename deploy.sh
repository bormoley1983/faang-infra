#!/bin/bash
# Load Configuration from .env
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Default if not set
USE_EXISTING_INFRA=${USE_EXISTING_INFRA:-true}
BASE_DOMAIN=${BASE_DOMAIN:-example.com}

echo "Starting FAANG System Deployment..."
echo "Mode: $( [ "$USE_EXISTING_INFRA" = "true" ] && echo 'Using Existing Network Infra' || echo 'Deploying New Infra in K8s' )"
echo "Domain: $BASE_DOMAIN"

# 1. Build Initialization Image
docker build -f Dockerfile.init -t faang-init-utils:latest .

# 2. Apply Secrets and Configs
kubectl apply -f k8s/secret.yaml
kubectl apply -f k8s/configmap.yaml

# 3. Infrastructure Logic
if [ "$USE_EXISTING_INFRA" = false ]; then
    echo "Deploying New Infrastructure..."
    kubectl apply -f k8s/infra/
fi

# 4. Run Initialization Job
kubectl delete job faang-init-job --ignore-not-found
kubectl apply -f k8s/init-job.yaml
kubectl wait --for=condition=complete job/faang-init-job --timeout=300s

# 5. Deploy Microservices
kubectl apply -f k8s/services/

# Apply Ingress with substitution
sed "s/\${BASE_DOMAIN}/$BASE_DOMAIN/g" k8s/ingress.yaml | kubectl apply -f -

echo "Deployment Complete!"
