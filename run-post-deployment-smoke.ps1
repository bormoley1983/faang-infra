[CmdletBinding()]
param(
    [Parameter(Mandatory)][switch]$ConfirmActiveProbe,
    [string]$Context = "",
    [string]$Namespace = "faang",
    [ValidateRange(30, 300)][int]$TimeoutSeconds = 210,
    [switch]$KeepEvidence
)

# DEP-052's sole active probe. Do not add this directory to Argo desired state.
$ErrorActionPreference = "Stop"
$kubectl = @("--request-timeout=20s")
if (-not [string]::IsNullOrWhiteSpace($Context)) { $kubectl += @("--context", $Context) }
$manifest = Join-Path $PSScriptRoot "k8s/preflight/post-deployment/smoke-job.yaml"
$jobName = "faang-post-deployment-smoke"
$createdJobUid = ""

if (-not $ConfirmActiveProbe) { throw "Explicit -ConfirmActiveProbe is required." }
if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) { throw "Missing post-deployment smoke manifest." }
& kubectl @kubectl get namespace $Namespace -o name | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Target namespace is unavailable." }

try {
    & kubectl @kubectl -n $Namespace delete job $jobName --ignore-not-found --wait=true | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Unable to remove a previous smoke Job." }
    & kubectl @kubectl -n $Namespace apply -f $manifest | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Unable to create the post-deployment smoke Job." }
    $createdJobUid = (& kubectl @kubectl -n $Namespace get job $jobName -o "jsonpath={.metadata.uid}").Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($createdJobUid)) { throw "Unable to identify the created post-deployment smoke Job." }
    & kubectl @kubectl -n $Namespace wait --for=condition=complete "job/$jobName" "--timeout=$($TimeoutSeconds)s"
    if ($LASTEXITCODE -ne 0) { throw "Post-deployment smoke Job did not complete successfully." }
    & kubectl @kubectl -n $Namespace logs "job/$jobName" --all-containers=true
    if ($LASTEXITCODE -ne 0) { throw "Unable to collect sanitized smoke evidence." }
}
finally {
    if (-not $KeepEvidence) {
        $currentJobUid = (& kubectl @kubectl -n $Namespace get job $jobName -o "jsonpath={.metadata.uid}" --ignore-not-found).Trim()
        if ($LASTEXITCODE -eq 0 -and $currentJobUid -eq $createdJobUid) {
            & kubectl @kubectl -n $Namespace delete job $jobName --ignore-not-found --wait=true | Out-Null
        }
    }
}
