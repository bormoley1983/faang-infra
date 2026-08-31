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

# Infrastructure selection is implemented by DEP-040/DEP-042 profiles.
if (-not $USE_EXISTING_INFRA) {
    throw "Internal infrastructure delivery is not available until DEP-040 and DEP-042 are resolved."
}

# Bootstrap Jobs are part of this overlay. Argo CD honors their negative sync waves;
# kubectl does not, so this path is emergency-only after prerequisites are ready.
Write-Host "Deploying FAANG System via Kustomize..." -ForegroundColor Cyan
kubectl apply -k k8s/overlays/homelab

Write-Host "Deployment Complete!" -ForegroundColor Green
Write-Host "Check status with: kubectl get pods" -ForegroundColor Green
