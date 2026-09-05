[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$ConfigPath = "config/postgresql-backup.local.json",
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

& "$PSScriptRoot/validate-postgresql-backup.ps1" -ConfigPath $ConfigPath
if (-not $Apply) { Write-Output "Mutation: none (pass -Apply only after owner approval)"; exit 0 }

$configuration = Get-Content -Raw -LiteralPath $ConfigPath | ConvertFrom-Json
$runtimeAccessKey = (Get-Content -Raw -LiteralPath $configuration.accessKeyFile).Trim()
$runtimeSecretKey = (Get-Content -Raw -LiteralPath $configuration.secretKeyFile).Trim()
$provisioningAccessKey = (Get-Content -Raw -LiteralPath $configuration.provisioningAccessKeyFile).Trim()
$provisioningSecretKey = (Get-Content -Raw -LiteralPath $configuration.provisioningSecretKeyFile).Trim()
$previousAccessKey = $env:AWS_ACCESS_KEY_ID; $previousSecretKey = $env:AWS_SECRET_ACCESS_KEY; $previousRegion = $env:AWS_DEFAULT_REGION
try {
    $env:AWS_ACCESS_KEY_ID = $provisioningAccessKey; $env:AWS_SECRET_ACCESS_KEY = $provisioningSecretKey; $env:AWS_DEFAULT_REGION = [string]$configuration.region
    aws --endpoint-url $configuration.endpoint s3api head-bucket --bucket $configuration.bucket 2>$null
    if ($LASTEXITCODE -ne 0) {
        if ($PSCmdlet.ShouldProcess("external SeaweedFS bucket", "create the dedicated PostgreSQL backup bucket")) {
            aws --endpoint-url $configuration.endpoint s3api create-bucket --bucket $configuration.bucket | Out-Null
        }
    }
    if ($LASTEXITCODE -ne 0) { throw "unable to verify or create the dedicated PostgreSQL backup bucket" }
} finally {
    $env:AWS_ACCESS_KEY_ID = $previousAccessKey; $env:AWS_SECRET_ACCESS_KEY = $previousSecretKey; $env:AWS_DEFAULT_REGION = $previousRegion
}

$temporarySecret = New-TemporaryFile
try {
    kubectl -n faang-postgresql-canary create secret generic faang-postgresql-backup-s3 `
        --from-file=ACCESS_KEY_ID=$configuration.accessKeyFile `
        --from-file=ACCESS_SECRET_KEY=$configuration.secretKeyFile `
        --from-literal=REGION=$configuration.region `
        --from-file=ca.crt=$configuration.caFile `
        --dry-run=client -o yaml | Set-Content -LiteralPath $temporarySecret -NoNewline
    $objectStore = @"
apiVersion: barmancloud.cnpg.io/v1
kind: ObjectStore
metadata:
  name: faang-postgresql-backup
  namespace: faang-postgresql-canary
spec:
  configuration:
    destinationPath: s3://$($configuration.bucket)/$($configuration.prefix)
    endpointURL: $($configuration.endpoint)
    endpointCA: {name: faang-postgresql-backup-s3, key: ca.crt}
    s3Credentials:
      accessKeyId: {name: faang-postgresql-backup-s3, key: ACCESS_KEY_ID}
      secretAccessKey: {name: faang-postgresql-backup-s3, key: ACCESS_SECRET_KEY}
      region: {name: faang-postgresql-backup-s3, key: REGION}
    data: {compression: gzip}
    wal: {compression: gzip}
"@
    if ($PSCmdlet.ShouldProcess("faang-postgresql-canary runtime backup boundary", "create or update the dedicated Secret and ObjectStore")) {
        Get-Content -Raw -LiteralPath $temporarySecret | kubectl apply -f -
        $objectStore | kubectl apply -f -
    }
} finally { Remove-Item -LiteralPath $temporarySecret -Force -ErrorAction SilentlyContinue }

Write-Output "Dedicated external SeaweedFS PostgreSQL backup boundary: configured"
Write-Output "Endpoint, bucket, prefix, and credentials: suppressed"
