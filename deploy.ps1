# FAANG Deployment Script
$envFile = Join-Path $PSScriptRoot ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | Where-Object { $_ -match '=' -and $_ -notmatch '^#' } | ForEach-Object {
        $name, $value = $_.Split('=', 2).Trim()
        if ($name -eq "USE_EXISTING_INFRA") {
            $USE_EXISTING_INFRA = [System.Convert]::ToBoolean($value)
        }
    }
}

# Defaults
if ($null -eq $USE_EXISTING_INFRA) { $USE_EXISTING_INFRA = $true }

Write-Host "Starting FAANG System Deployment..." -ForegroundColor Green
Write-Host "Mode: $(if ($USE_EXISTING_INFRA) { 'Using Existing Network Infra' } else { 'Deploying New Infra in K8s' })" -ForegroundColor Yellow

# 1. Build Initialization Image
Write-Host "Building Initialization Utility Image..." -ForegroundColor Cyan
docker build -f Dockerfile.init -t faang-init-utils:latest .

# 2. Infrastructure Logic
if (-not $USE_EXISTING_INFRA) {
    Write-Host "Deploying New Infrastructure..." -ForegroundColor Cyan
    kubectl apply -k k8s/infra/  # Assuming infra also uses kustomize or standard apply
}

# 3. Run Configuration/Initialization Job
Write-Host "Running Initialization Job..." -ForegroundColor Cyan
kubectl delete job faang-init-job --ignore-not-found
# Secrets and ConfigMaps are part of the Kustomize base, but for the job we apply them directly or via base
kubectl apply -f k8s/base/secret.yaml
kubectl apply -f k8s/base/configmap.yaml
kubectl apply -f k8s/init-job.yaml

Write-Host "Waiting for initialization to complete..." -ForegroundColor Cyan
kubectl wait --for=condition=complete job/faang-init-job --timeout=300s

# 4. Deploy the exact same committed overlay rendered by Argo CD
Write-Host "Deploying FAANG System via Kustomize..." -ForegroundColor Cyan
kubectl apply -k k8s/overlays/homelab

Write-Host "Deployment Complete!" -ForegroundColor Green
Write-Host "Check status with: kubectl get pods" -ForegroundColor Green
