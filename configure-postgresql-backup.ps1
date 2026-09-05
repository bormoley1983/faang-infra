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
$provisioningAccessKey = (Get-Content -Raw -LiteralPath $configuration.provisioningAccessKeyFile).Trim()
$provisioningSecretKey = (Get-Content -Raw -LiteralPath $configuration.provisioningSecretKeyFile).Trim()
$previousAccessKey = $env:AWS_ACCESS_KEY_ID; $previousSecretKey = $env:AWS_SECRET_ACCESS_KEY; $previousRegion = $env:AWS_DEFAULT_REGION; $previousCaBundle = $env:AWS_CA_BUNDLE
try {
    $env:AWS_ACCESS_KEY_ID = $provisioningAccessKey; $env:AWS_SECRET_ACCESS_KEY = $provisioningSecretKey; $env:AWS_DEFAULT_REGION = [string]$configuration.region; $env:AWS_CA_BUNDLE = [string]$configuration.caFile
    $headBucketOutput = @(aws --endpoint-url $configuration.endpoint s3api head-bucket --bucket $configuration.bucket 2>&1)
    $headBucketExitCode = $LASTEXITCODE
    if ($headBucketExitCode -ne 0) {
        if (($headBucketOutput -join "`n") -match "(?i)(accessdenied|forbidden|\b403\b)") {
            throw "the provisioning identity cannot verify the dedicated PostgreSQL backup bucket; refusing to attempt bucket creation"
        }
        if ($PSCmdlet.ShouldProcess("external SeaweedFS bucket", "create the dedicated PostgreSQL backup bucket")) {
            $createBucketOutput = @(aws --endpoint-url $configuration.endpoint s3api create-bucket --bucket $configuration.bucket 2>&1)
            $createBucketExitCode = $LASTEXITCODE
            if ($createBucketExitCode -ne 0) { throw "unable to create the dedicated PostgreSQL backup bucket" }
        }
    }
} finally {
    $env:AWS_ACCESS_KEY_ID = $previousAccessKey; $env:AWS_SECRET_ACCESS_KEY = $previousSecretKey; $env:AWS_DEFAULT_REGION = $previousRegion; $env:AWS_CA_BUNDLE = $previousCaBundle
}

$canaryNamespace = @"
apiVersion: v1
kind: Namespace
metadata:
  name: faang-postgresql-canary
  labels:
    app.kubernetes.io/part-of: faang-postgresql
    faang.io/environment: canary
"@
$secretManifest = @(kubectl -n faang-postgresql-canary create secret generic faang-postgresql-backup-s3 `
    "--from-file=ACCESS_KEY_ID=$($configuration.accessKeyFile)" `
    "--from-file=ACCESS_SECRET_KEY=$($configuration.secretKeyFile)" `
    "--from-literal=REGION=$($configuration.region)" `
    "--from-file=ca.crt=$($configuration.caFile)" `
    --dry-run=client -o yaml)
if ($LASTEXITCODE -ne 0) { throw "unable to render the PostgreSQL backup runtime Secret" }

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
if ($PSCmdlet.ShouldProcess("faang-postgresql-canary runtime backup boundary", "create or label the namespace, then create or update the dedicated Secret and ObjectStore")) {
    $canaryNamespace | kubectl apply -f -
    if ($LASTEXITCODE -ne 0) { throw "unable to apply the PostgreSQL canary namespace" }
    $secretManifest | kubectl apply -f -
    if ($LASTEXITCODE -ne 0) { throw "unable to apply the PostgreSQL backup runtime Secret" }
    $objectStore | kubectl apply -f -
    if ($LASTEXITCODE -ne 0) { throw "unable to apply the PostgreSQL backup ObjectStore" }
}

Write-Output "Dedicated external SeaweedFS PostgreSQL backup boundary: configured"
Write-Output "Endpoint, bucket, prefix, and credentials: suppressed"
