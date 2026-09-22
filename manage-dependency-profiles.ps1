[CmdletBinding()]
param(
    [Parameter(Mandatory, Position = 0)]
    [ValidateSet("status", "validate", "plan")]
    [string]$Command,
    [string]$ConfigPath = "",
    [ValidateSet("postgresql", "redis", "elasticsearch", "kafka", "s3")]
    [string]$Dependency = "",
    [ValidateSet("internal", "external")]
    [string]$Mode = "",
    [switch]$Json
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Join-Path $PSScriptRoot "config/homelab.local.json"
}
$arguments = @(
    (Join-Path $PSScriptRoot "ops/dependencies/profilectl.py"),
    "--config", $ConfigPath
)
if ($Json) { $arguments += "--json" }
$arguments += $Command
if ($Command -eq "plan") {
    if ([string]::IsNullOrWhiteSpace($Dependency) -or [string]::IsNullOrWhiteSpace($Mode)) {
        throw "plan requires -Dependency and -Mode"
    }
    $arguments += @("--dependency", $Dependency, "--mode", $Mode)
}

& python @arguments
if ($LASTEXITCODE -notin @(0, 3)) {
    throw "Dependency profile operation failed."
}
if ($LASTEXITCODE -eq 3) {
    throw "The requested profile is not production-ready; inspect the plan output."
}
