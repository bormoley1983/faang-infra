[CmdletBinding()]
param(
    [string]$ConfigPath = "",
    [string]$RegistryUsername = "jenkins"
)

$ErrorActionPreference = "Stop"
$registryNamespace = "registry"
$credentialsSecret = "registry-client-credentials"
$authSecret = "registry-auth"
$htpasswdImage = "httpd:2.4.68-alpine@sha256:1b766f17b84026429b7cb243317b142921b24432336e798bc881c43f45ed9567"

if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Join-Path $PSScriptRoot "config/homelab.local.json"
}
if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
    throw "Missing local topology mapping '$ConfigPath'. Copy config/homelab.example.json to config/homelab.local.json and set local values."
}

$localConfig = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$registryAddress = [string]$localConfig.registry.address
$registryPort = [int]$localConfig.registry.port
$registryDnsName = [string]$localConfig.registry.dnsName
$registryStorageNode = [string]$localConfig.registry.storageNode
$parsedAddress = $null

if (-not [Net.IPAddress]::TryParse($registryAddress, [ref]$parsedAddress)) {
    throw "registry.address must be a valid IP address for the MetalLB allocation"
}
if ($registryPort -lt 1 -or $registryPort -gt 65535) {
    throw "registry.port must be between 1 and 65535"
}
if ([string]::IsNullOrWhiteSpace($registryStorageNode)) {
    throw "registry.storageNode is required"
}

$RegistryEndpoint = "${registryAddress}:$registryPort"

function New-RandomSecret {
    param([int]$ByteCount = 32)

    $bytes = [byte[]]::new($ByteCount)
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function ConvertTo-Base64 {
    param([string]$Value)
    return [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Value))
}

kubectl apply -f "$PSScriptRoot/k8s/registry/namespace.yaml"
if ($LASTEXITCODE -ne 0) {
    throw "Unable to create or update the registry namespace"
}

kubectl get node $registryStorageNode -o name | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Registry storage node '$registryStorageNode' does not exist" }
kubectl label node $registryStorageNode faang.io/registry-storage=true --overwrite
if ($LASTEXITCODE -ne 0) { throw "Unable to label the registry storage node" }

$existingCredentials = & kubectl -n $registryNamespace get secret $credentialsSecret -o json 2>$null
if ($LASTEXITCODE -eq 0) {
    $credentialData = $existingCredentials | ConvertFrom-Json
    $RegistryUsername = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($credentialData.data.username))
    $registryPassword = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($credentialData.data.password))
} else {
    $registryPassword = New-RandomSecret
}

$htpasswd = $registryPassword | docker run --rm -i --entrypoint htpasswd $htpasswdImage -Bin $RegistryUsername
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($htpasswd)) {
    throw "Unable to generate the bcrypt htpasswd entry"
}
$htpasswd = $htpasswd.Trim()

$existingAuth = & kubectl -n $registryNamespace get secret $authSecret -o json 2>$null
if ($LASTEXITCODE -eq 0) {
    $authData = $existingAuth | ConvertFrom-Json
    $httpSecret = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($authData.data.'http-secret'))
} else {
    $httpSecret = New-RandomSecret
}

$credentialsManifest = @{
    apiVersion = "v1"
    kind = "Secret"
    metadata = @{ name = $credentialsSecret; namespace = $registryNamespace }
    type = "Opaque"
    data = @{
        username = ConvertTo-Base64 $RegistryUsername
        password = ConvertTo-Base64 $registryPassword
    }
} | ConvertTo-Json -Depth 6
$credentialsManifest | kubectl apply -f -
if ($LASTEXITCODE -ne 0) { throw "Unable to apply registry client credentials" }

$authManifest = @{
    apiVersion = "v1"
    kind = "Secret"
    metadata = @{ name = $authSecret; namespace = $registryNamespace }
    type = "Opaque"
    data = @{
        htpasswd = ConvertTo-Base64 $htpasswd
        'http-secret' = ConvertTo-Base64 $httpSecret
    }
} | ConvertTo-Json -Depth 6
$authManifest | kubectl apply -f -
if ($LASTEXITCODE -ne 0) { throw "Unable to apply registry server credentials" }

$dockerAuth = ConvertTo-Base64 "$RegistryUsername`:$registryPassword"
$dockerConfig = @{ auths = @{ $RegistryEndpoint = @{ username = $RegistryUsername; password = $registryPassword; auth = $dockerAuth } } } | ConvertTo-Json -Compress -Depth 6
$pullSecretManifest = @{
    apiVersion = "v1"
    kind = "Secret"
    metadata = @{ name = "faang-registry-pull"; namespace = "faang" }
    type = "kubernetes.io/dockerconfigjson"
    data = @{ '.dockerconfigjson' = ConvertTo-Base64 $dockerConfig }
} | ConvertTo-Json -Depth 6
$pullSecretManifest | kubectl apply -f -
if ($LASTEXITCODE -ne 0) { throw "Unable to apply the faang image-pull Secret" }

kubectl apply -k "$PSScriptRoot/k8s/registry"
if ($LASTEXITCODE -ne 0) { throw "Unable to apply the registry resources" }

$servicePatch = @{
    metadata = @{
        annotations = @{ 'metallb.io/loadBalancerIPs' = $registryAddress }
    }
} | ConvertTo-Json -Compress -Depth 5
kubectl -n $registryNamespace patch service registry --type=merge --patch $servicePatch
if ($LASTEXITCODE -ne 0) { throw "Unable to set the private MetalLB registry address" }

kubectl -n $registryNamespace wait --for=condition=Ready certificate/registry-ca --timeout=120s
if ($LASTEXITCODE -ne 0) { throw "Registry CA was not issued" }
kubectl -n $registryNamespace wait --for=condition=Ready issuer/registry-ca --timeout=120s
if ($LASTEXITCODE -ne 0) { throw "Registry CA issuer is not ready" }

$certificateSpec = @{
    secretName = "registry-tls"
    ipAddresses = @($registryAddress)
    duration = "8760h"
    renewBefore = "720h"
    privateKey = @{ algorithm = "ECDSA"; size = 256 }
    issuerRef = @{ name = "registry-ca"; kind = "Issuer" }
}
if (-not [string]::IsNullOrWhiteSpace($registryDnsName)) {
    $certificateSpec.dnsNames = @($registryDnsName)
}
$certificateManifest = @{
    apiVersion = "cert-manager.io/v1"
    kind = "Certificate"
    metadata = @{ name = "registry-tls"; namespace = $registryNamespace }
    spec = $certificateSpec
} | ConvertTo-Json -Depth 8
$certificateManifest | kubectl apply -f -
if ($LASTEXITCODE -ne 0) { throw "Unable to apply the topology-specific registry certificate" }

kubectl -n $registryNamespace wait --for=condition=Ready certificate/registry-tls --timeout=120s
if ($LASTEXITCODE -ne 0) { throw "Registry TLS certificate was not issued" }
kubectl -n $registryNamespace rollout status deployment/registry --timeout=180s
if ($LASTEXITCODE -ne 0) { throw "Registry Deployment did not become ready" }

$smokeTemplate = Join-Path $PSScriptRoot "k8s/registry/tests/pull-smoke.template.yaml"
$smokeLocal = Join-Path $PSScriptRoot "k8s/registry/tests/pull-smoke.local.yaml"
$smokeManifest = (Get-Content -LiteralPath $smokeTemplate -Raw).Replace("__REGISTRY_ENDPOINT__", $RegistryEndpoint)
[IO.File]::WriteAllText($smokeLocal, $smokeManifest, [Text.UTF8Encoding]::new($false))

Write-Output "Registry is ready at $RegistryEndpoint. Credentials remain in Secret $registryNamespace/$credentialsSecret."
Write-Output "Local smoke manifest: $smokeLocal"
Write-Output "Install the registry CA on Docker and every k3s node before login or image pulls; see k8s/registry/README.md."
