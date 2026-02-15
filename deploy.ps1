# FAANG Deployment Script (Kustomize version)
$envFile = Join-Path $PSScriptRoot ".env"
# ... (loading env variables logic same as before)

# Load Domain from env
if ($null -eq $BASE_DOMAIN) { $BASE_DOMAIN = "office.aviv.com.ua" }

Write-Host "Deploying FAANG System using Kustomize..." -ForegroundColor Green

# Use kubectl kustomize to apply the overlay
# This automatically handles the domain patching
kubectl apply -k k8s/overlays/homelab

Write-Host "Deployment Complete!" -ForegroundColor Green
