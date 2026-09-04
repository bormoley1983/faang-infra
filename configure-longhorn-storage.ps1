[CmdletBinding()]
param(
    [string]$ConfigPath = "config/longhorn-storage.local.json",
    [switch]$Apply,
    [string]$Approval = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RequiredNodeTag = "longhorn-storage"
$RequiredDiskTag = "longhorn-primary"
$RequiredNodeCount = 4
$MinimumReservationBytes = 1GB
$ApprovalPhrase = "DEP-042A-NODE-MAPPING-APPROVED"

function Stop-Safely([string]$Message) {
    throw "Longhorn storage bootstrap rejected: $Message"
}

if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
    Stop-Safely "ignored private configuration is missing"
}

try {
    $configuration = Get-Content -Raw -LiteralPath $ConfigPath | ConvertFrom-Json
} catch {
    Stop-Safely "ignored private configuration is not valid JSON"
}

if ($configuration.schemaVersion -ne 1) {
    Stop-Safely "schemaVersion must be 1"
}

$nodes = @($configuration.nodes)
if ($nodes.Count -ne $RequiredNodeCount) {
    Stop-Safely "exactly four private node mappings are required"
}

$seenNodes = @{}
foreach ($node in $nodes) {
    $nodeName = [string]$node.name
    if ([string]::IsNullOrWhiteSpace($nodeName) -or $nodeName -match "REPLACE|<|>") {
        Stop-Safely "every node requires a real private name"
    }
    if ($seenNodes.ContainsKey($nodeName)) {
        Stop-Safely "node mappings must be unique"
    }
    $seenNodes[$nodeName] = $true

    $nodeTags = @($node.nodeTags)
    if ($nodeTags.Count -ne 1 -or [string]$nodeTags[0] -ne $RequiredNodeTag) {
        Stop-Safely "every node must use only the reviewed Longhorn node tag"
    }

    $disks = @($node.disks)
    if ($disks.Count -ne 1) {
        Stop-Safely "exactly one approved filesystem disk is required per node"
    }
    $disk = $disks[0]
    $diskName = [string]$disk.name
    $diskPath = [string]$disk.path
    if ($diskName -notmatch "^[a-z0-9][a-z0-9-]{0,31}$") {
        Stop-Safely "disk names must be generic DNS-style identifiers"
    }
    if (-not $diskPath.StartsWith("/") -or $diskPath -eq "/" -or $diskPath -match "REPLACE|<|>") {
        Stop-Safely "every disk requires a private absolute path below the filesystem root"
    }
    if ($disk.allowScheduling -ne $true) {
        Stop-Safely "every selected disk must explicitly allow scheduling"
    }
    $reservation = [int64]$disk.storageReserved
    if ($reservation -lt $MinimumReservationBytes) {
        Stop-Safely "every disk requires a non-trivial byte reservation"
    }
    $diskTags = @($disk.tags)
    if ($diskTags.Count -ne 1 -or [string]$diskTags[0] -ne $RequiredDiskTag) {
        Stop-Safely "every disk must use only the reviewed Longhorn disk tag"
    }

    $rawNode = & kubectl get node $nodeName -o json --request-timeout=10s 2>$null
    if ($LASTEXITCODE -ne 0) {
        Stop-Safely "a private node mapping does not resolve"
    }
    $liveNode = $rawNode | ConvertFrom-Json
    $ready = @($liveNode.status.conditions | Where-Object {
        $_.type -eq "Ready" -and $_.status -eq "True"
    }).Count -eq 1
    $memoryKi = [int64](([string]$liveNode.status.capacity.memory) -replace "Ki$", "")
    if (-not $ready -or [int]$liveNode.status.capacity.cpu -lt 4 -or $memoryKi -lt 4194304) {
        Stop-Safely "a private node mapping is not Ready or misses the storage resource floor"
    }
}

Write-Output "Validated storage nodes: 4"
Write-Output "Validated filesystem disks: 4"
Write-Output "Private identities and mappings: suppressed"

if (-not $Apply) {
    Write-Output "Mutation: none (validation only)"
    exit 0
}

if ($Approval -ne $ApprovalPhrase) {
    Stop-Safely "-Apply requires the exact reviewed approval phrase"
}

foreach ($node in $nodes) {
    $nodeName = [string]$node.name
    $nodeTagsJson = ConvertTo-Json @($node.nodeTags) -Compress
    $disksJson = ConvertTo-Json @($node.disks) -Compress -Depth 8

    & kubectl label node $nodeName `
        "storage.faang.io/longhorn-node=true" `
        "node.longhorn.io/create-default-disk=config" `
        --overwrite *> $null
    if ($LASTEXITCODE -ne 0) {
        Stop-Safely "failed to apply reviewed labels to a private node"
    }

    & kubectl annotate node $nodeName `
        "node.longhorn.io/default-node-tags=$nodeTagsJson" `
        "node.longhorn.io/default-disks-config=$disksJson" `
        --overwrite *> $null
    if ($LASTEXITCODE -ne 0) {
        Stop-Safely "failed to apply reviewed annotations to a private node"
    }
}

Write-Output "Mutated storage nodes: 4"
Write-Output "Applied reviewed labels and disk configuration annotations"
Write-Output "Private identities and mappings: suppressed"
