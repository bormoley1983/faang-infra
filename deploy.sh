#!/bin/bash
# Load Configuration from .env
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Default if not set
USE_EXISTING_INFRA=${USE_EXISTING_INFRA:-true}
echo "Starting FAANG System Deployment..."
echo "Mode: $( [ "$USE_EXISTING_INFRA" = "true" ] && echo 'Using Existing Network Infra' || echo 'Deploying New Infra in K8s' )"

# Infrastructure selection is implemented by DEP-040/DEP-042 profiles.
if [ "$USE_EXISTING_INFRA" = "false" ]; then
    echo "Internal infrastructure delivery is not available until DEP-040 and DEP-042 are resolved." >&2
    exit 2
fi

# Bootstrap Jobs are part of this overlay. Argo CD honors their negative sync waves;
# kubectl does not, so this path is emergency-only after prerequisites are ready.
echo "Deploying FAANG System via Kustomize..."
kubectl apply -k k8s/overlays/homelab

echo "Deployment Complete!"
echo "Check status with: kubectl get pods"
