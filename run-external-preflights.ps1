[CmdletBinding()]
param(
    [string]$ConfigPath = "",
    [string]$Namespace = "faang",
    [ValidateRange(30, 600)][int]$TimeoutSeconds = 300,
    [switch]$KeepResources
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Join-Path $PSScriptRoot "config/homelab.local.json"
}
if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
    throw "Missing ignored local topology mapping."
}

$validatorPath = Join-Path $PSScriptRoot "ops/validation/validate_dependency_selection.py"
$selectionPath = Join-Path $PSScriptRoot "k8s/overlays/homelab/kustomization.yaml"
$configMapPath = Join-Path $PSScriptRoot "k8s/overlays/homelab/configmap.yaml"
& python $validatorPath --kustomization $selectionPath --topology (Resolve-Path -LiteralPath $ConfigPath).Path --configmap $configMapPath
if ($LASTEXITCODE -ne 0) { throw "Dependency selection contract validation failed." }

$topology = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$contracts = @{
    postgresql = @{ Service = "postgres-main"; Job = "faang-external-preflight-postgresql"; File = "postgresql-job.yaml" }
    redis = @{ Service = "redis-main"; Job = "faang-external-preflight-redis"; File = "redis-job.yaml" }
    elasticsearch = @{ Service = "elasticsearch-main"; Job = "faang-external-preflight-elasticsearch"; File = "elasticsearch-job.yaml" }
    kafka = @{ Service = "kafka-main"; Job = "faang-external-preflight-kafka"; File = "kafka-job.yaml" }
    minio = @{ Service = "minio-main"; Job = "faang-external-preflight-minio"; File = "minio-job.yaml" }
}
$selected = @($contracts.Keys | Where-Object { $topology.dependencies.$_.mode -eq "external" } | Sort-Object)
if ($selected.Count -eq 0) { throw "No external dependency profile is selected." }

kubectl get namespace $Namespace -o name | Out-Null
if ($LASTEXITCODE -ne 0) { throw "The target namespace does not exist." }

$root = Join-Path $PSScriptRoot "k8s/preflight/external"
$createdJobs = [System.Collections.Generic.List[string]]::new()
function Wait-PreflightJob {
    param([Parameter(Mandatory)][string]$JobName)

    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTimeOffset]::UtcNow -lt $deadline) {
        $jobJson = kubectl -n $Namespace get job $JobName -o json
        if ($LASTEXITCODE -ne 0) { throw "Unable to inspect preflight Job status." }
        $jobState = $jobJson | ConvertFrom-Json
        $trueConditions = @($jobState.status.conditions | Where-Object { $_.status -eq "True" } | ForEach-Object { $_.type })
        if ($trueConditions -contains "Complete") { return $true }
        if ($trueConditions -contains "Failed") { return $false }
        Start-Sleep -Seconds 2
    }
    return $false
}

foreach ($name in $selected) {
    $contract = $contracts[$name]
    $active = kubectl -n $Namespace get job $contract.Job -o "jsonpath={.status.active}" --ignore-not-found
    if ($LASTEXITCODE -ne 0) { throw "Unable to inspect the existing $name preflight Job." }
    if (-not [string]::IsNullOrWhiteSpace($active)) {
        throw "The $name preflight Job is already active; concurrent runs are not allowed."
    }
}

try {
    kubectl apply -n $Namespace -k (Join-Path $root "common") | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Unable to install the tokenless preflight identity and scripts." }

    foreach ($name in $selected) {
        $contract = $contracts[$name]
        kubectl -n $Namespace delete job $contract.Job --ignore-not-found --wait=true | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Unable to remove the previous $name preflight Job." }
        kubectl apply -n $Namespace -f (Join-Path $root $contract.File) | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Unable to create the $name preflight Job." }
        $createdJobs.Add($contract.Job)
        $job = $contract.Job
        $completed = Wait-PreflightJob -JobName $job
        kubectl -n $Namespace logs "job/$job" --all-containers=true
        if (-not $completed) {
            kubectl -n $Namespace describe "job/$job"
            throw "$name external dependency preflight failed."
        }
    }
    Write-Output "External dependency preflights passed for: $($selected -join ', ')."
}
finally {
    if (-not $KeepResources) {
        foreach ($job in $createdJobs) {
            kubectl -n $Namespace delete job $job --ignore-not-found --wait=true | Out-Null
        }
        kubectl -n $Namespace delete configmap faang-external-preflight-scripts --ignore-not-found | Out-Null
        kubectl -n $Namespace delete serviceaccount faang-external-preflight --ignore-not-found | Out-Null
    }
}
