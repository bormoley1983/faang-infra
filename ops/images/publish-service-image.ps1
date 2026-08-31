[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ServiceDirectory,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z0-9]+(?:[._-][a-z0-9]+)*$')]
    [string]$ImageName,

    [Parameter(Mandatory = $true)]
    [string]$RegistryEndpoint,

    [Parameter(Mandatory = $true)]
    [string]$RegistryCaFile,

    [string]$ImageTag = "",
    [string]$ArtifactsDirectory = ""
)

$ErrorActionPreference = "Stop"
$requiredPlatforms = @("linux/amd64", "linux/arm64")
$runtimeDigest = "sha256:3137541deb3cac6626b5d9a4a2187bc0d6a34312f858bd2c67dd01e732e6b682"
$sbomGenerator = "docker/buildkit-syft-scanner:stable-1@sha256:ae4f3b554449e7e25548e7d8ccc029d17357348e30c6e3df01b92bc93654d6a9"
$orasImage = "ghcr.io/oras-project/oras:v1.3.3@sha256:a4c54befd87d0366e0ba3ac3a9536a5288c8a3735acd3b635cdace59a2c559c8"

if ([string]::IsNullOrWhiteSpace($env:REGISTRY_USERNAME) -or [string]::IsNullOrWhiteSpace($env:REGISTRY_PASSWORD)) {
    throw "REGISTRY_USERNAME and REGISTRY_PASSWORD must be supplied by the caller's credential store"
}

$servicePath = (Resolve-Path -LiteralPath $ServiceDirectory).Path
$caPath = (Resolve-Path -LiteralPath $RegistryCaFile).Path
$jarPath = Join-Path $servicePath "build/libs/service.jar"
if (-not (Test-Path -LiteralPath $jarPath -PathType Leaf)) {
    throw "Missing $jarPath; build and test the service before publishing"
}

$revision = (& git -C $servicePath rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $revision -notmatch '^[0-9a-f]{40}$') {
    throw "Unable to resolve the service Git revision"
}
$worktreeStatus = @(& git -C $servicePath status --porcelain --untracked-files=all)
if ($LASTEXITCODE -ne 0) { throw "Unable to inspect the service worktree" }
if ($worktreeStatus.Count -gt 0) {
    throw "Refusing to publish from a dirty service worktree. Commit the reviewed service-owned Dockerfile/.dockerignore changes first so OCI revision metadata is truthful."
}
if ([string]::IsNullOrWhiteSpace($ImageTag)) {
    $ImageTag = $revision.Substring(0, 12)
}
if ($ImageTag -notmatch '^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$') {
    throw "ImageTag is not a valid OCI tag"
}

$source = (& git -C $servicePath remote get-url origin).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($source)) {
    throw "Unable to resolve the service source URL"
}
$created = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
$target = "$RegistryEndpoint/$ImageName`:$ImageTag"

if ([string]::IsNullOrWhiteSpace($ArtifactsDirectory)) {
    $ArtifactsDirectory = Join-Path $PSScriptRoot "../../artifacts/images/$ImageName/$ImageTag"
}
$artifactPath = [IO.Path]::GetFullPath($ArtifactsDirectory)
New-Item -ItemType Directory -Path $artifactPath -Force | Out-Null

$tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$tempDirectory = [IO.Path]::GetFullPath((Join-Path $tempRoot "faang-image-$([guid]::NewGuid().ToString('N'))"))
if (-not $tempDirectory.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Unsafe temporary path"
}
New-Item -ItemType Directory -Path $tempDirectory | Out-Null
$layoutPath = Join-Path $tempDirectory "layout"

try {
    Push-Location $servicePath
    try {
        docker buildx build `
            --platform ($requiredPlatforms -join ',') `
            --file Dockerfile `
            --tag "$ImageName`:$ImageTag" `
            --build-arg "RUNTIME_IMAGE=eclipse-temurin:25-jre-alpine@$runtimeDigest" `
            --build-arg "OCI_CREATED=$created" `
            --build-arg "OCI_REVISION=$revision" `
            --build-arg "OCI_SOURCE=$source" `
            --build-arg "OCI_VERSION=$ImageTag" `
            --attest "type=sbom,generator=$sbomGenerator" `
            --provenance mode=max `
            --output "type=oci,dest=$layoutPath,tar=false" `
            .
        if ($LASTEXITCODE -ne 0) { throw "Multi-platform OCI build failed" }
    } finally {
        Pop-Location
    }

    foreach ($platform in $requiredPlatforms) {
        $architecture = $platform.Split('/')[1]
        $sbomPath = Join-Path $artifactPath "sbom-$architecture.spdx.json"
        $scanPath = Join-Path $artifactPath "vulnerabilities-$architecture.sarif.json"

        docker scout sbom --platform $platform --format spdx --output $sbomPath "oci-dir://$layoutPath"
        if ($LASTEXITCODE -ne 0) { throw "SBOM export failed for $platform" }

        docker scout cves --platform $platform --only-severity critical --exit-code --format sarif --output $scanPath "oci-dir://$layoutPath"
        if ($LASTEXITCODE -ne 0) { throw "Critical vulnerability gate failed for $platform" }
    }

    Copy-Item -LiteralPath $caPath -Destination (Join-Path $tempDirectory "ca.crt")
    $auth = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("$($env:REGISTRY_USERNAME):$($env:REGISTRY_PASSWORD)"))
    $authConfig = @{ auths = @{ $RegistryEndpoint = @{ auth = $auth } } } | ConvertTo-Json -Compress -Depth 5
    [IO.File]::WriteAllText((Join-Path $tempDirectory "auth.json"), $authConfig, [Text.UTF8Encoding]::new($false))

    $copyOutput = docker run --rm -v "${tempDirectory}:/work" $orasImage copy `
        --from-oci-layout `
        --to-ca-file /work/ca.crt `
        --to-registry-config /work/auth.json `
        "/work/layout:$ImageTag" `
        $target 2>&1
    $copyOutput | Write-Output
    if ($LASTEXITCODE -ne 0) { throw "OCI layout publication failed" }

    $digestLine = ($copyOutput | Select-String '^Digest:\s+sha256:[0-9a-f]{64}$').Line | Select-Object -Last 1
    $digest = ($digestLine -replace '^Digest:\s+', '').Trim()
    if ($digest -notmatch '^sha256:[0-9a-f]{64}$') { throw "Unable to resolve the published index digest" }

    $remoteManifest = docker run --rm -v "${tempDirectory}:/work" $orasImage manifest fetch `
        --ca-file /work/ca.crt `
        --registry-config /work/auth.json `
        "$RegistryEndpoint/$ImageName@$digest"
    if ($LASTEXITCODE -ne 0) { throw "Published manifest verification failed" }
    $index = $remoteManifest | ConvertFrom-Json
    $platforms = @($index.manifests | Where-Object { $_.platform.os -and $_.platform.architecture } | ForEach-Object { "$($_.platform.os)/$($_.platform.architecture)" } | Sort-Object -Unique)
    foreach ($platform in $requiredPlatforms) {
        if ($platform -notin $platforms) { throw "Published index is missing $platform" }
    }

    $attestationCount = @($index.manifests | Where-Object { $_.platform.os -eq 'unknown' -and $_.platform.architecture -eq 'unknown' }).Count
    if ($attestationCount -lt 2) { throw "Published index does not contain both platform attestations" }

    $metadata = @{
        image = $ImageName
        tag = $ImageTag
        digest = $digest
        reference = "$RegistryEndpoint/$ImageName@$digest"
        revision = $revision
        source = $source
        created = $created
        platforms = $requiredPlatforms
        attestationManifestCount = $attestationCount
        scanPolicy = "block any Critical finding on either required platform"
    } | ConvertTo-Json -Depth 6
    $metadataPath = Join-Path $artifactPath "publication.json"
    [IO.File]::WriteAllText($metadataPath, $metadata, [Text.UTF8Encoding]::new($false))

    Write-Output "Published $target"
    Write-Output "Digest $digest"
    Write-Output "Evidence $artifactPath"
} finally {
    if (Test-Path -LiteralPath $tempDirectory) {
        $resolvedTemp = [IO.Path]::GetFullPath($tempDirectory)
        if (-not $resolvedTemp.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing unsafe temporary cleanup"
        }
        Remove-Item -LiteralPath $resolvedTemp -Recurse -Force
    }
}
