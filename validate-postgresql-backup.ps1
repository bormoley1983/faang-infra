[CmdletBinding()]
param(
    [string]$ConfigPath = "config/postgresql-backup.local.json"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Stop-Safely([string]$Message) { throw "PostgreSQL backup configuration rejected: $Message" }

if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) { Stop-Safely "ignored private configuration is missing" }
try { $configuration = Get-Content -Raw -LiteralPath $ConfigPath | ConvertFrom-Json } catch { Stop-Safely "configuration is not valid JSON" }
if ($configuration.schemaVersion -ne 1 -or [string]$configuration.provider -ne "seaweedfs") { Stop-Safely "schemaVersion 1 and provider seaweedfs are required" }

$endpoint = $null
if (-not [Uri]::TryCreate([string]$configuration.endpoint, [UriKind]::Absolute, [ref]$endpoint) -or $endpoint.Scheme -ne "https" -or -not [string]::IsNullOrEmpty($endpoint.UserInfo) -or $endpoint.AbsolutePath -ne "/") { Stop-Safely "endpoint must be an HTTPS origin without credentials or a path" }
$bucket = [string]$configuration.bucket
if ($bucket -notmatch "^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$" -or $bucket.Contains("..")) { Stop-Safely "bucket must be a valid S3 bucket name" }
$prefix = [string]$configuration.prefix
if ($prefix -notmatch "^[a-z0-9][a-z0-9._/-]{0,126}[a-z0-9]$" -or $prefix.Contains("..") -or $prefix.StartsWith("/") -or $prefix.EndsWith("/")) { Stop-Safely "prefix must be a relative, traversal-free S3 path" }
if ([string]::IsNullOrWhiteSpace([string]$configuration.region)) { Stop-Safely "region is required" }

foreach ($property in @("caFile", "accessKeyFile", "secretKeyFile", "provisioningAccessKeyFile", "provisioningSecretKeyFile")) {
    $path = [string]$configuration.$property
    if ([string]::IsNullOrWhiteSpace($path) -or -not [System.IO.Path]::IsPathRooted($path) -or -not (Test-Path -LiteralPath $path -PathType Leaf) -or (Get-Item -LiteralPath $path).Length -eq 0) { Stop-Safely "$property must reference a non-empty private absolute file" }
}
if ([string]$configuration.accessKeyFile -eq [string]$configuration.provisioningAccessKeyFile -or [string]$configuration.secretKeyFile -eq [string]$configuration.provisioningSecretKeyFile) { Stop-Safely "runtime and provisioning identity files must be distinct" }

$longhornPath = Join-Path $PSScriptRoot "config/longhorn-backup.local.json"
if (Test-Path -LiteralPath $longhornPath -PathType Leaf) {
    try { $longhorn = Get-Content -Raw -LiteralPath $longhornPath | ConvertFrom-Json } catch { Stop-Safely "existing Longhorn backup configuration is not valid JSON" }
    if ([string]$longhorn.bucket -eq $bucket) { Stop-Safely "PostgreSQL must not reuse Longhorn's backup bucket" }
    if ([string]$longhorn.accessKeyFile -eq [string]$configuration.accessKeyFile -or [string]$longhorn.secretKeyFile -eq [string]$configuration.secretKeyFile) { Stop-Safely "PostgreSQL must not reuse Longhorn's backup identity files" }
}
$applicationPath = Join-Path $PSScriptRoot "config/seaweedfs-app-s3.local.json"
if (Test-Path -LiteralPath $applicationPath -PathType Leaf) {
    try { $application = Get-Content -Raw -LiteralPath $applicationPath | ConvertFrom-Json } catch { Stop-Safely "existing application S3 configuration is not valid JSON" }
    if (@($application.buckets) -contains $bucket) { Stop-Safely "PostgreSQL must not reuse an application S3 bucket" }
    if ([string]$application.accessKeyFile -eq [string]$configuration.accessKeyFile -or [string]$application.secretKeyFile -eq [string]$configuration.secretKeyFile) { Stop-Safely "PostgreSQL must not reuse the application S3 identity files" }
}

Write-Output "Backup provider: external SeaweedFS"
Write-Output "Dedicated bucket, prefix, runtime identity, and provisioning identity: validated"
Write-Output "Private endpoint, bucket, and credentials: suppressed"
Write-Output "Mutation: none (validation only)"
