[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PrivateEnvironmentRoot
)

# Registers already SOPS-encrypted TLS manifests with private KSOPS overlays.
# It does not read decrypted data or invoke Kubernetes, Argo, Git, or SOPS.
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $PrivateEnvironmentRoot -ErrorAction Stop).Path
$expectedFiles = @(
    'overlays/homelab/secrets/faang-ingress-tls.sops.yaml',
    'overlays/argocd/secrets/argocd-management-tls.sops.yaml',
    'overlays/jenkins/secrets/jenkins-management-tls.sops.yaml'
)
foreach ($relativePath in $expectedFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $root $relativePath) -PathType Leaf)) {
        throw "Required encrypted TLS manifest was not found: $relativePath"
    }
}

$homeGeneratorPath = Join-Path $root 'overlays/homelab/secrets/ksops-generator.yaml'
if (-not (Test-Path -LiteralPath $homeGeneratorPath -PathType Leaf)) { throw 'Homelab KSOPS generator was not found.' }
$homeGenerator = [IO.File]::ReadAllText($homeGeneratorPath)
$applicationTlsEntry = '  - ./secrets/faang-ingress-tls.sops.yaml'
if (-not $homeGenerator.Contains($applicationTlsEntry)) {
    $anchor = '  - ./secrets/faang-secrets.enc.yaml'
    if ($homeGenerator.IndexOf($anchor) -lt 0) { throw 'Homelab KSOPS generator did not contain its expected encrypted-secret entry.' }
    $homeGenerator = $homeGenerator.Replace($anchor, "$anchor`n$applicationTlsEntry")
}

$managementOverlays = @(
    @{ Name = 'argocd'; Namespace = 'argocd'; Secret = 'argocd-management-tls' },
    @{ Name = 'jenkins'; Namespace = 'jenkins'; Secret = 'jenkins-management-tls' }
)
$writes = @(@{ Path = $homeGeneratorPath; Content = $homeGenerator })
foreach ($overlay in $managementOverlays) {
    $overlayPath = Join-Path $root ('overlays/' + $overlay.Name)
    $kustomizationPath = Join-Path $overlayPath 'kustomization.yaml'
    $generatorPath = Join-Path $overlayPath 'secrets/ksops-generator.yaml'
    if (-not (Test-Path -LiteralPath $kustomizationPath -PathType Leaf)) { throw "Management overlay kustomization was not found: $($overlay.Name)" }
    $kustomization = @"
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: $($overlay.Namespace)
generators:
  - secrets/ksops-generator.yaml
"@
    $generator = @"
apiVersion: viaduct.ai/v1
kind: ksops
metadata:
  name: $($overlay.Secret)-generator
  annotations:
    config.kubernetes.io/function: |
      exec:
        path: ksops
files:
  - ./secrets/$($overlay.Secret).sops.yaml
"@
    $writes += @{ Path = $kustomizationPath; Content = $kustomization }
    $writes += @{ Path = $generatorPath; Content = $generator }
}

foreach ($write in $writes) {
    [IO.File]::WriteAllText($write.Path, $write.Content, [Text.UTF8Encoding]::new($false))
}
Write-Output 'private_tls_ksops_overlays_configured=faang,argocd,jenkins'
