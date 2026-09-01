[CmdletBinding()]
param(
    [string]$ConfigPath = "",
    [string]$Namespace = "faang",
    [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Join-Path $PSScriptRoot "config/homelab.local.json"
}
if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
    throw "Missing local topology mapping '$ConfigPath'. Copy config/homelab.example.json to config/homelab.local.json and set local values."
}

$localConfig = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
if ($null -eq $localConfig.dependencies) {
    throw "The local topology mapping must contain the 'dependencies' object from config/homelab.example.json."
}

$dependencyContract = @(
    @{ ConfigKey = "postgresql"; ServiceName = "postgres-main"; PortName = "postgresql"; DefaultPort = 5432 },
    @{ ConfigKey = "redis"; ServiceName = "redis-main"; PortName = "redis"; DefaultPort = 6379 },
    @{ ConfigKey = "elasticsearch"; ServiceName = "elasticsearch-main"; PortName = "http"; DefaultPort = 9200 },
    @{ ConfigKey = "kafka"; ServiceName = "kafka-main"; PortName = "broker"; DefaultPort = 9092 },
    @{ ConfigKey = "minio"; ServiceName = "minio-main"; PortName = "api"; DefaultPort = 9000 }
)

function Invoke-KubectlApply {
    param([Parameter(Mandatory)][hashtable]$Manifest)

    $Manifest | ConvertTo-Json -Depth 10 | kubectl apply -f -
    if ($LASTEXITCODE -ne 0) {
        throw "kubectl apply failed for $($Manifest.kind)/$($Manifest.metadata.name)"
    }
}

if (-not $ValidateOnly) {
    kubectl get namespace $Namespace -o name | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Namespace '$Namespace' does not exist; create the application namespace before installing dependency aliases."
    }
}

foreach ($contract in $dependencyContract) {
    $entry = $localConfig.dependencies.($contract.ConfigKey)
    if ($null -eq $entry) {
        throw "dependencies.$($contract.ConfigKey) is required"
    }

    $mode = [string]$entry.mode
    if ($mode -notin @("external", "internal")) {
        throw "dependencies.$($contract.ConfigKey).mode must be exactly 'external' or 'internal'"
    }

    if ($mode -eq "internal") {
        if ($contract.ConfigKey -ne "minio") {
            throw "Internal mode is not implemented yet for dependencies.$($contract.ConfigKey)"
        }
        if (-not $ValidateOnly) {
            kubectl -n $Namespace delete endpointslice "$($contract.ServiceName)-external" --ignore-not-found
            if ($LASTEXITCODE -ne 0) { throw "Unable to remove the obsolete external MinIO endpoint" }
            kubectl apply -k "$PSScriptRoot/k8s/components/dependencies/minio/internal"
            if ($LASTEXITCODE -ne 0) { throw "Unable to apply the internal MinIO profile" }
            kubectl -n $Namespace rollout status statefulset/minio-main --timeout=300s
            if ($LASTEXITCODE -ne 0) { throw "Internal MinIO did not become ready" }
        }
        continue
    }

    $address = [string]$entry.address
    $parsedAddress = $null
    if (-not [Net.IPAddress]::TryParse($address, [ref]$parsedAddress)) {
        throw "dependencies.$($contract.ConfigKey).address must be an IPv4 or IPv6 address"
    }
    $isDocumentationAddress = $address.StartsWith("192.0.2.") -or
        $address.StartsWith("198.51.100.") -or
        $address.StartsWith("203.0.113.") -or
        $address.StartsWith("2001:db8", [StringComparison]::OrdinalIgnoreCase)
    if (-not $ValidateOnly -and $isDocumentationAddress) {
        throw "dependencies.$($contract.ConfigKey).address still uses a documentation-only example address"
    }

    $port = if ($null -eq $entry.port) { [int]$contract.DefaultPort } else { [int]$entry.port }
    if ($port -lt 1 -or $port -gt 65535) {
        throw "dependencies.$($contract.ConfigKey).port must be between 1 and 65535"
    }

    $labels = @{
        "app.kubernetes.io/managed-by" = "faang-local-topology"
        "faang.io/dependency" = $contract.ConfigKey
    }
    $annotations = @{
        "argocd.argoproj.io/compare-options" = "IgnoreExtraneous"
        "faang.io/topology-source" = "ignored-local-config"
    }

    $service = @{
        apiVersion = "v1"
        kind = "Service"
        metadata = @{
            name = $contract.ServiceName
            namespace = $Namespace
            labels = $labels
            annotations = $annotations
        }
        spec = @{
            ports = @(
                @{
                    name = $contract.PortName
                    port = $port
                    protocol = "TCP"
                    targetPort = $port
                }
            )
        }
    }

    $endpointSlice = @{
        apiVersion = "discovery.k8s.io/v1"
        kind = "EndpointSlice"
        metadata = @{
            name = "$($contract.ServiceName)-external"
            namespace = $Namespace
            labels = $labels + @{ "kubernetes.io/service-name" = $contract.ServiceName }
            annotations = $annotations
        }
        addressType = if ($parsedAddress.AddressFamily -eq [Net.Sockets.AddressFamily]::InterNetwork) { "IPv4" } else { "IPv6" }
        ports = @(
            @{
                name = $contract.PortName
                port = $port
                protocol = "TCP"
            }
        )
        endpoints = @(
            @{
                addresses = @($address)
                conditions = @{ ready = $true }
            }
        )
    }

    if (-not $ValidateOnly) {
        Invoke-KubectlApply -Manifest $service
        Invoke-KubectlApply -Manifest $endpointSlice
    }
}

if ($ValidateOnly) {
    Write-Output "Dependency mode and mapping configuration is valid."
} else {
    Write-Output "Dependency profiles are configured in namespace '$Namespace'. Physical external addresses remain only in the ignored local mapping."
}
