[CmdletBinding()]
param(
    [string]$ConfigPath = "config/longhorn-backup.local.json"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Stop-Safely([string]$Message) {
    throw "Longhorn backup configuration rejected: $Message"
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
if ([string]$configuration.provider -ne "seaweedfs") {
    Stop-Safely "provider must be the owner-approved SeaweedFS target"
}
if ([string]$configuration.version -ne "4.45") {
    Stop-Safely "SeaweedFS must be pinned to version 4.45"
}
if ([string]$configuration.artifact.name -ne "linux_amd64.tar.gz") {
    Stop-Safely "the reviewed Linux amd64 artifact is required"
}
$expectedDigest = "c408894668aeaa74d4f251e20b350fd72195cbe596ddc3f48658709714f7be36"
if ([string]$configuration.artifact.sha256 -ne $expectedDigest) {
    Stop-Safely "the reviewed artifact digest is required"
}

$endpoint = $null
if (-not [Uri]::TryCreate([string]$configuration.endpoint, [UriKind]::Absolute, [ref]$endpoint) -or
    $endpoint.Scheme -ne "https" -or
    -not [string]::IsNullOrEmpty($endpoint.UserInfo) -or
    $endpoint.AbsolutePath -ne "/") {
    Stop-Safely "endpoint must be an HTTPS origin without credentials or a path"
}

$bucket = [string]$configuration.bucket
if ($bucket -notmatch "^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$" -or $bucket.Contains("..")) {
    Stop-Safely "bucket must use a valid private S3 bucket name"
}
if ([string]::IsNullOrWhiteSpace([string]$configuration.region)) {
    Stop-Safely "region is required"
}

foreach ($property in @("caFile", "accessKeyFile", "secretKeyFile")) {
    $path = [string]$configuration.$property
    if ([string]::IsNullOrWhiteSpace($path) -or
        -not [System.IO.Path]::IsPathRooted($path) -or
        -not (Test-Path -LiteralPath $path -PathType Leaf) -or
        (Get-Item -LiteralPath $path).Length -eq 0) {
        Stop-Safely "$property must reference a non-empty private absolute file"
    }
}

Write-Output "Backup provider: SeaweedFS 4.45"
Write-Output "Artifact digest: verified configuration pin"
Write-Output "TLS endpoint, bucket, CA, and credential files: validated"
Write-Output "Private endpoint and credential material: suppressed"
Write-Output "Mutation: none (validation only)"
