[CmdletBinding()]
param(
    [string]$Namespace = "jenkins",
    [string]$StatefulSet = "jenkins",
    [string]$Manifest = (Join-Path $PSScriptRoot "jenkins-home-backup.yaml")
)

$ErrorActionPreference = "Stop"

function Invoke-Kubectl {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)

    & kubectl @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "kubectl failed: $($Arguments -join ' ')"
    }
}

$replicas = (& kubectl -n $Namespace get statefulset $StatefulSet -o jsonpath="{.spec.replicas}")
if ($LASTEXITCODE -ne 0 -or $replicas -ne "1") {
    throw "Expected StatefulSet $Namespace/$StatefulSet to have exactly one replica; found '$replicas'."
}

$restartRequired = $false
try {
    Invoke-Kubectl -n $Namespace delete job jenkins-home-backup --ignore-not-found=true
    Invoke-Kubectl apply -f $Manifest

    Invoke-Kubectl -n $Namespace scale statefulset $StatefulSet --replicas=0
    $restartRequired = $true
    Invoke-Kubectl -n $Namespace wait --for=delete pod/$StatefulSet-0 --timeout=180s

    Invoke-Kubectl -n $Namespace patch job jenkins-home-backup --type=merge --patch '{"spec":{"suspend":false}}'
    Invoke-Kubectl -n $Namespace wait --for=condition=complete job/jenkins-home-backup --timeout=600s
    Invoke-Kubectl -n $Namespace logs job/jenkins-home-backup
} finally {
    if ($restartRequired) {
        Invoke-Kubectl -n $Namespace scale statefulset $StatefulSet --replicas=1
        Invoke-Kubectl -n $Namespace rollout status statefulset/$StatefulSet --timeout=600s
    }
}
