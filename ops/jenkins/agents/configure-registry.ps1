[CmdletBinding()]
param(
    [string]$MappingFile = (Join-Path $PSScriptRoot "../../../config/homelab.local.json"),
    [string]$JenkinsNamespace = "jenkins",
    [string]$RegistryNamespace = "registry",
    [string]$KubeSystemNamespace = "kube-system"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $MappingFile)) {
    throw "Missing ignored homelab mapping: $MappingFile"
}

$mapping = Get-Content -LiteralPath $MappingFile -Raw | ConvertFrom-Json
$registryAddress = [string]$mapping.registry.address
$registryHost = [string]$mapping.registry.dnsName
$registryPort = [int]$mapping.registry.port
$parsedAddress = $null
if (-not [Net.IPAddress]::TryParse($registryAddress, [ref]$parsedAddress) -or
    [string]::IsNullOrWhiteSpace($registryHost) -or
    $registryPort -lt 1 -or
    $registryPort -gt 65535) {
    throw "The mapping must define registry.address, registry.dnsName, and a valid registry.port."
}
$endpoint = "${registryHost}:${registryPort}"

$caSecret = & kubectl -n $RegistryNamespace get secret registry-ca -o json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or -not $caSecret.data.'ca.crt') {
    throw "Unable to read registry CA from $RegistryNamespace/registry-ca."
}

$caConfigMap = [ordered]@{
    apiVersion = "v1"
    kind = "ConfigMap"
    metadata = [ordered]@{
        name = "faang-registry-ca"
        namespace = $JenkinsNamespace
        labels = [ordered]@{ "app.kubernetes.io/name" = "faang-build-agent" }
    }
    binaryData = [ordered]@{ "ca.crt" = $caSecret.data.'ca.crt' }
}

$endpointConfigMap = [ordered]@{
    apiVersion = "v1"
    kind = "ConfigMap"
    metadata = [ordered]@{
        name = "faang-registry-client"
        namespace = $JenkinsNamespace
        labels = [ordered]@{ "app.kubernetes.io/name" = "faang-build-agent" }
    }
    data = [ordered]@{ endpoint = $endpoint }
}

$buildkitConfigMap = [ordered]@{
    apiVersion = "v1"
    kind = "ConfigMap"
    metadata = [ordered]@{
        name = "faang-buildkit-config"
        namespace = $JenkinsNamespace
        labels = [ordered]@{ "app.kubernetes.io/name" = "faang-build-agent" }
    }
    data = [ordered]@{
        "buildkitd.toml" = @"
[registry."$endpoint"]
  ca = ["/etc/buildkit/certs/ca.crt"]
"@
    }
}

@($caConfigMap, $endpointConfigMap, $buildkitConfigMap) |
    ForEach-Object { $_ | ConvertTo-Json -Depth 20 -Compress } |
    ForEach-Object {
        $_ | & kubectl apply -f - | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to configure the Jenkins registry client resources."
        }
    }

$coreDns = & kubectl -n $KubeSystemNamespace get configmap coredns -o json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or -not $coreDns.data.NodeHosts) {
    throw "Unable to read the existing k3s CoreDNS NodeHosts data."
}
$nodeHostLines = @(
    [string]$coreDns.data.NodeHosts -split "`r?`n" |
        Where-Object {
            $_ -and $_ -notmatch "\s$([regex]::Escape($registryHost))(\s|$)"
        }
)
$nodeHostLines += "$registryAddress $registryHost"
$coreDns.data.NodeHosts = ($nodeHostLines -join "`n") + "`n"
$coreDns | ConvertTo-Json -Depth 40 -Compress | & kubectl replace -f - | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Failed to add the private registry mapping to the existing CoreDNS hosts data."
}

Write-Output "Jenkins registry CA, endpoint, BuildKit, and private CoreDNS configuration are applied."
