[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PrivateEnvironmentRoot
)

# Prepares private-only TLS overlay directories. It never reads Secret values,
# invokes Kubernetes/Argo, or creates a TLS Secret.
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $PrivateEnvironmentRoot -ErrorAction Stop).Path
$sopsPath = Join-Path $root '.sops.yaml'
if (-not (Test-Path -LiteralPath $sopsPath -PathType Leaf)) { throw 'Private environment SOPS configuration was not found.' }

$sopsText = [IO.File]::ReadAllText($sopsPath)
$pathRuleVariants = @(
    @{ Old = 'overlays/homelab/secrets'; New = 'overlays/(homelab|argocd|jenkins)/secrets' },
    @{ Old = 'overlays[\\/]homelab[\\/]secrets'; New = 'overlays[\\/](homelab|argocd|jenkins)[\\/]secrets' }
)
$selectedVariant = $null
foreach ($variant in $pathRuleVariants) {
    $oldCount = [regex]::Matches($sopsText, [regex]::Escape($variant.Old)).Count
    $newCount = [regex]::Matches($sopsText, [regex]::Escape($variant.New)).Count
    if ($oldCount -eq 1 -and $newCount -eq 0) {
        $selectedVariant = $variant
        break
    }
}
if ($null -eq $selectedVariant) {
    throw 'Expected exactly one homelab secrets path in an unexpanded SOPS creation rule.'
}
$updatedSopsText = $sopsText.Replace($selectedVariant.Old, $selectedVariant.New)

$overlays = @(
    @{ Name = 'argocd'; Namespace = 'argocd'; Secret = 'argocd-management-tls' },
    @{ Name = 'jenkins'; Namespace = 'jenkins'; Secret = 'jenkins-management-tls' }
)
foreach ($overlay in $overlays) {
    $overlayPath = Join-Path $root ('overlays/' + $overlay.Name)
    if (Test-Path -LiteralPath $overlayPath) { throw "Refusing to alter existing private overlay $($overlay.Name)." }
}

$createdOverlays = @()
try {
    [IO.File]::WriteAllText($sopsPath, $updatedSopsText, [Text.UTF8Encoding]::new($false))
    foreach ($overlay in $overlays) {
        $overlayPath = Join-Path $root ('overlays/' + $overlay.Name)
        $secretPath = Join-Path $overlayPath 'secrets'
        New-Item -ItemType Directory -Path $secretPath -Force | Out-Null
        $createdOverlays += $overlayPath
        $kustomizationPath = Join-Path $overlayPath 'kustomization.yaml'
        $kustomization = @"
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: $($overlay.Namespace)
resources:
  - secrets/$($overlay.Secret).sops.yaml
"@
        [IO.File]::WriteAllText($kustomizationPath, $kustomization, [Text.UTF8Encoding]::new($false))
    }
} catch {
    [IO.File]::WriteAllText($sopsPath, $sopsText, [Text.UTF8Encoding]::new($false))
    foreach ($overlayPath in $createdOverlays) {
        Remove-Item -LiteralPath $overlayPath -Recurse -Force -ErrorAction SilentlyContinue
    }
    throw
}
Write-Output 'private_management_tls_overlays_prepared=argocd,jenkins'
