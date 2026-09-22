[CmdletBinding()]
param(
    [string]$ConfigPath = "",
    [switch]$Apply,
    [string]$ConfirmInstall = "",
    [switch]$ValidateContainers
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Join-Path $PSScriptRoot "config/monitoring.local.json"
}

$arguments = @((Join-Path $PSScriptRoot "monitoring/install.py"), "--config", $ConfigPath)
if ($Apply) { $arguments += "--apply" }
if ($ValidateContainers) { $arguments += "--validate-containers" }
if (-not [string]::IsNullOrWhiteSpace($ConfirmInstall)) {
    $arguments += @("--confirm-install", $ConfirmInstall)
}

& python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Monitoring installation validation failed."
}
