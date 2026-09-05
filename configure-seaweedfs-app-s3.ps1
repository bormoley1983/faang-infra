[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$ConfigPath = "config/seaweedfs-app-s3.local.json",
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

& "$PSScriptRoot/validate-seaweedfs-app-s3.ps1" -ConfigPath $ConfigPath
if (-not $Apply) {
    Write-Output "Mutation: none (pass -Apply only after owner approval)"
    exit 0
}

$configuration = Get-Content -Raw -LiteralPath $ConfigPath | ConvertFrom-Json
$accessKey = (Get-Content -Raw -LiteralPath $configuration.accessKeyFile).Trim()
$secretKey = (Get-Content -Raw -LiteralPath $configuration.secretKeyFile).Trim()
$actions = foreach ($bucket in @($configuration.buckets)) {
    "Read:$bucket"
    "Write:$bucket"
    "List:$bucket"
}
$identity = @{
    identities = @(@{
        name = "faang-application"
        credentials = @(@{ accessKey = $accessKey; secretKey = $secretKey })
        actions = @($actions)
    })
} | ConvertTo-Json -Compress -Depth 8

$temporaryFile = New-TemporaryFile
try {
    [System.IO.File]::WriteAllText($temporaryFile, $identity, [System.Text.UTF8Encoding]::new($false))
    if ($PSCmdlet.ShouldProcess("faang-object-storage/seaweedfs-app-s3-identity", "create or update runtime-only S3 identity Secret")) {
        kubectl -n faang-object-storage create secret generic seaweedfs-app-s3-identity `
            --from-file="seaweedfs_s3_config=$temporaryFile" `
            --dry-run=client -o yaml | kubectl apply -f -
    }
} finally {
    Remove-Item -LiteralPath $temporaryFile -Force -ErrorAction SilentlyContinue
}

Write-Output "Runtime-only SeaweedFS S3 identity Secret: configured"
Write-Output "Credential and bucket values: suppressed"
