# Setup Existing Infrastructure for FAANG (PowerShell)
Write-Host "Starting Infrastructure Configuration..." -ForegroundColor Green

# 1. Build Initialization Image
Write-Host "Building Configuration Utility Image..." -ForegroundColor Cyan
docker build -f Dockerfile.init -t faang-init-utils:latest .

# 2. Apply Secrets and Configs
Write-Host "Applying Secrets and ConfigMaps..." -ForegroundColor Cyan
kubectl apply -f k8s/secret.yaml
kubectl apply -f k8s/configmap.yaml

# 3. Run Initialization Job
Write-Host "Running Configuration Job (Schemas, Topics, Indices)..." -ForegroundColor Cyan
kubectl delete job faang-init-job --ignore-not-found
kubectl apply -f k8s/init-job.yaml

Write-Host "Waiting for configuration to complete..." -ForegroundColor Cyan
kubectl wait --for=condition=complete job/faang-init-job --timeout=300s

if ($LASTEXITCODE -ne 0) {
    Write-Host "Initialization failed. Checking logs..." -ForegroundColor Red
    kubectl logs -l job-name=faang-init-job --all-containers=true
} else {
    Write-Host "Infrastructure configuration successful!" -ForegroundColor Green
}
