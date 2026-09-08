[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PrivateEnvironmentRoot
)

# Gives the application TLS Secret one Argo/KSOPS owner. It does not decrypt,
# move, or modify the encrypted manifest, and never contacts cluster tooling.
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $PrivateEnvironmentRoot -ErrorAction Stop).Path
$sourceSecret = Join-Path $root 'overlays/homelab/secrets/faang-ingress-tls.sops.yaml'
if (-not (Test-Path -LiteralPath $sourceSecret -PathType Leaf)) { throw 'Encrypted application TLS manifest was not found.' }

$homeGeneratorPath = Join-Path $root 'overlays/homelab/secrets/ksops-generator.yaml'
if (-not (Test-Path -LiteralPath $homeGeneratorPath -PathType Leaf)) { throw 'Homelab KSOPS generator was not found.' }
$homeGenerator = [IO.File]::ReadAllText($homeGeneratorPath)
$entry = '  - ./secrets/faang-ingress-tls.sops.yaml'
$entryCount = [regex]::Matches($homeGenerator, [regex]::Escape($entry)).Count
if ($entryCount -ne 1) { throw 'Expected exactly one application TLS entry in the Homelab KSOPS generator.' }
$updatedHomeGenerator = $homeGenerator.Replace("$entry`r`n", '').Replace("$entry`n", '')

$overlayPath = Join-Path $root 'overlays/faang-tls'
if (Test-Path -LiteralPath $overlayPath) { throw 'Refusing to alter an existing private faang-tls overlay.' }
$kustomization = @"
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: faang
generators:
  - secrets/ksops-generator.yaml
"@
$generator = @"
apiVersion: viaduct.ai/v1
kind: ksops
metadata:
  name: faang-ingress-tls-generator
  annotations:
    config.kubernetes.io/function: |
      exec:
        path: ksops
files:
  - ../homelab/secrets/faang-ingress-tls.sops.yaml
"@

try {
    New-Item -ItemType Directory -Path (Join-Path $overlayPath 'secrets') -Force | Out-Null
    [IO.File]::WriteAllText((Join-Path $overlayPath 'kustomization.yaml'), $kustomization, [Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllText((Join-Path $overlayPath 'secrets/ksops-generator.yaml'), $generator, [Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllText($homeGeneratorPath, $updatedHomeGenerator, [Text.UTF8Encoding]::new($false))
} catch {
    Remove-Item -LiteralPath $overlayPath -Recurse -Force -ErrorAction SilentlyContinue
    throw
}
Write-Output 'private_application_tls_overlay_isolated=faang-tls'
