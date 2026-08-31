[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z0-9]+(?:[._-][a-z0-9]+)*$')]
    [string]$ImageName,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^.+@sha256:[0-9a-f]{64}$')]
    [string]$ImageReference,

    [string]$Namespace = "faang",
    [string]$PullSecret = "faang-registry-pull",
    [switch]$KeepPods
)

$ErrorActionPreference = "Stop"
$podPrefix = "dep021-$ImageName"
if ($podPrefix.Length -gt 50) {
    throw "ImageName is too long for the smoke Pod naming contract"
}

function New-SmokePod {
    param(
        [string]$Architecture
    )

    return @{
        apiVersion = "v1"
        kind = "Pod"
        metadata = @{
            name = "$podPrefix-$Architecture"
            namespace = $Namespace
            labels = @{
                'app.kubernetes.io/name' = "image-smoke"
                'app.kubernetes.io/component' = $ImageName
            }
        }
        spec = @{
            automountServiceAccountToken = $false
            restartPolicy = "Never"
            imagePullSecrets = @(@{ name = $PullSecret })
            nodeSelector = @{ 'kubernetes.io/arch' = $Architecture }
            securityContext = @{
                runAsNonRoot = $true
                runAsUser = 10001
                runAsGroup = 10001
                seccompProfile = @{ type = "RuntimeDefault" }
            }
            containers = @(
                @{
                    name = "smoke"
                    image = $ImageReference
                    command = @("java")
                    args = @("-XshowSettings:properties", "-version")
                    securityContext = @{
                        allowPrivilegeEscalation = $false
                        capabilities = @{ drop = @("ALL") }
                    }
                }
            )
        }
    }
}

$podNames = @("$podPrefix-amd64", "$podPrefix-arm64")
$qualifiedPodNames = @($podNames | ForEach-Object { "pod/$_" })
try {
    kubectl -n $Namespace delete pod @podNames --ignore-not-found=true --wait=true | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Unable to clear previous smoke Pods" }

    foreach ($architecture in @("amd64", "arm64")) {
        $manifest = New-SmokePod -Architecture $architecture | ConvertTo-Json -Depth 10
        $manifest | kubectl apply -f - | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Unable to create $architecture smoke Pod" }
    }

    kubectl -n $Namespace wait --for=jsonpath='{.status.phase}'=Succeeded @qualifiedPodNames --timeout=180s
    if ($LASTEXITCODE -ne 0) {
        kubectl -n $Namespace get pod @podNames -o wide
        foreach ($podName in $podNames) { kubectl -n $Namespace describe pod $podName }
        throw "One or more architecture smoke Pods failed"
    }

    kubectl -n $Namespace get pod @podNames -o wide
    foreach ($podName in $podNames) {
        Write-Output "--- $podName"
        kubectl -n $Namespace logs $podName
        if ($LASTEXITCODE -ne 0) { throw "Unable to read $podName logs" }
    }
} finally {
    if (-not $KeepPods) {
        kubectl -n $Namespace delete pod @podNames --ignore-not-found=true --wait=true | Out-Null
    }
}
