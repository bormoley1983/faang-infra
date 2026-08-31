param(
    [switch]$ShowClusterStatus
)

$ErrorActionPreference = "Stop"
$repoRoot = $PSScriptRoot

Write-Host "Validating the committed bootstrap contract..." -ForegroundColor Cyan
Push-Location $repoRoot
try {
    python ops/validation/validate_deployment.py
    if ($LASTEXITCODE -ne 0) {
        throw "Deployment validation failed."
    }
    kubectl kustomize k8s/overlays/homelab > $null
    if ($LASTEXITCODE -ne 0) {
        throw "Homelab overlay rendering failed."
    }
} finally {
    Pop-Location
}

Write-Host "Bootstrap configuration is valid." -ForegroundColor Green
Write-Host "Argo CD owns execution and honors the committed sync waves." -ForegroundColor Yellow

if ($ShowClusterStatus) {
    kubectl -n faang get jobs -l app.kubernetes.io/component=bootstrap
    kubectl -n faang get pods -l app.kubernetes.io/component=bootstrap
}
