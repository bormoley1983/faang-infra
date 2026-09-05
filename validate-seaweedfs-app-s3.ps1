[CmdletBinding()]
param(
    [string]$ConfigPath = "config/seaweedfs-app-s3.local.json"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Stop-Safely([string]$Message) {
    throw "SeaweedFS application S3 configuration rejected: $Message"
}

if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
    Stop-Safely "ignored private configuration is missing"
}

try {
    $configuration = Get-Content -Raw -LiteralPath $ConfigPath | ConvertFrom-Json
} catch {
    Stop-Safely "ignored private configuration is not valid JSON"
}

if ($configuration.schemaVersion -ne 1) {
    Stop-Safely "schemaVersion must be 1"
}
if ([string]$configuration.provider -ne "seaweedfs" -or [string]$configuration.chartVersion -ne "4.45.0") {
    Stop-Safely "the reviewed SeaweedFS provider and chart version are required"
}

foreach ($property in @("accessKeyFile", "secretKeyFile")) {
    $path = [string]$configuration.$property
    if ([string]::IsNullOrWhiteSpace($path) -or
        -not [System.IO.Path]::IsPathRooted($path) -or
        -not (Test-Path -LiteralPath $path -PathType Leaf) -or
        (Get-Item -LiteralPath $path).Length -eq 0) {
        Stop-Safely "$property must reference a non-empty private absolute file"
    }
}

$buckets = @($configuration.buckets)
if ($buckets.Count -lt 1 -or $buckets.Count -ne @($buckets | Select-Object -Unique).Count) {
    Stop-Safely "buckets must be a non-empty unique list"
}
foreach ($bucket in $buckets) {
    if ([string]$bucket -notmatch "^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$" -or [string]$bucket -match "\\.\\.") {
        Stop-Safely "each bucket must be a valid S3 bucket name"
    }
}

Write-Output "Provider/chart: SeaweedFS 4.45.0"
Write-Output "Private credential files and bucket policy: validated"
Write-Output "Credential and bucket values: suppressed"
Write-Output "Mutation: none (validation only)"
