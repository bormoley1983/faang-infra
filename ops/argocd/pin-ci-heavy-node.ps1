param(
    [string]$LabelKey = "workload.faang.io/ci-heavy",
    [string]$LabelValue = "true"
)

$ErrorActionPreference = "Stop"

function Invoke-KubectlStrict {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & kubectl @Arguments | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "kubectl $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

$nodeSelector = @{
    $LabelKey = $LabelValue
    "kubernetes.io/arch" = "amd64"
}
$nodeSelectorJson = $nodeSelector | ConvertTo-Json -Depth 20 -Compress
$selectorPatch = '[{"op":"replace","path":"/spec/template/spec/nodeSelector","value":' + $nodeSelectorJson + '}]'

$patchFile = Join-Path $env:TEMP "argocd-ci-heavy-patch.json"
[System.IO.File]::WriteAllText($patchFile, $selectorPatch, (New-Object System.Text.UTF8Encoding($false)))

Invoke-KubectlStrict -Arguments @("-n", "argocd", "patch", "deployment", "argocd-repo-server", "--type", "json", "--patch-file", $patchFile)
Invoke-KubectlStrict -Arguments @("-n", "argocd", "patch", "statefulset", "argocd-application-controller", "--type", "json", "--patch-file", $patchFile)

Invoke-KubectlStrict -Arguments @("-n", "argocd", "rollout", "status", "deployment/argocd-repo-server", "--timeout=180s")
Invoke-KubectlStrict -Arguments @("-n", "argocd", "rollout", "status", "statefulset/argocd-application-controller", "--timeout=180s")

Write-Host "Argo CD repo-server and application-controller pinned to $LabelKey=$LabelValue on amd64." -ForegroundColor Green
