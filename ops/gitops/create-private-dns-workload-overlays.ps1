[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PrivateEnvironmentRoot,
    [Parameter(Mandatory)][string]$InternalZone,
    [switch]$ReplaceExisting
)

# Creates private DNS/TLS patches over the reviewed generic workload sources.
# It writes only private Git files and never invokes Git, Argo, Kubernetes, or SOPS.
$ErrorActionPreference = 'Stop'
if ($InternalZone -notmatch '^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$') {
    throw 'InternalZone must be a lowercase DNS suffix with at least two labels.'
}
$root = (Resolve-Path -LiteralPath $PrivateEnvironmentRoot -ErrorAction Stop).Path
$overlays = @('overlays/runtime-foundation', 'overlays/workloads')
foreach ($relativePath in $overlays) {
    if ((Test-Path -LiteralPath (Join-Path $root $relativePath)) -and -not $ReplaceExisting) {
        throw "Refusing to alter existing private overlay: $relativePath"
    }
}

$services = @('account', 'achievement', 'analytics', 'notification', 'payment', 'post', 'project', 'url-shortener', 'user')
$rules = foreach ($service in $services) {
@"
    - host: faang-$service.faang.$InternalZone
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: faang-$service-service
                port:
                  number: 80
"@
}
$hostList = ($services | ForEach-Object { "      - faang-$_.faang.$InternalZone" }) -join "`n"
$workloadsKustomization = @"
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - https://github.com/bormoley1983/faang-infra.git//k8s/overlays/homelab/boundaries/workloads?ref=dev-local
patches:
  - path: ingress-private-dns-tls.yaml
    target:
      kind: Ingress
      name: faang-ingress
  - path: url-shortener-public-url-rollout.yaml
    target:
      group: apps
      version: v1
      kind: Deployment
      name: faang-url-shortener-service
"@
$workloadsPatch = @"
- op: replace
  path: /spec/rules
  value:
$($rules -join "`n")
- op: add
  path: /spec/tls
  value:
    - hosts:
$hostList
      secretName: faang-ingress-tls
"@
$runtimeKustomization = @"
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - https://github.com/bormoley1983/faang-infra.git//k8s/overlays/homelab/boundaries/runtime-foundation?ref=dev-local
patches:
  - path: url-shortener-public-url.yaml
    target:
      version: v1
      kind: ConfigMap
      name: faang-config
"@
$runtimePatch = @"
apiVersion: v1
kind: ConfigMap
metadata:
  name: faang-config
data:
  URL_SHORTENER_BASE_URL: https://faang-url-shortener.faang.$InternalZone
  URL_SHORTENER_PUBLIC_URL: https://faang-url-shortener.faang.$InternalZone/url
"@
$urlShortenerRolloutPatch = @"
apiVersion: apps/v1
kind: Deployment
metadata:
  name: faang-url-shortener-service
spec:
  template:
    metadata:
      annotations:
        faang.io/public-url: https://faang-url-shortener.faang.$InternalZone
"@

$createdOverlayPaths = @()
try {
    foreach ($relativePath in $overlays) {
        $overlayPath = Join-Path $root $relativePath
        if (-not (Test-Path -LiteralPath $overlayPath)) {
            New-Item -ItemType Directory -Path $overlayPath -Force | Out-Null
            $createdOverlayPaths += $overlayPath
        }
    }
    [IO.File]::WriteAllText((Join-Path $root 'overlays/workloads/kustomization.yaml'), $workloadsKustomization, [Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllText((Join-Path $root 'overlays/workloads/ingress-private-dns-tls.yaml'), $workloadsPatch, [Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllText((Join-Path $root 'overlays/workloads/url-shortener-public-url-rollout.yaml'), $urlShortenerRolloutPatch, [Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllText((Join-Path $root 'overlays/runtime-foundation/kustomization.yaml'), $runtimeKustomization, [Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllText((Join-Path $root 'overlays/runtime-foundation/url-shortener-public-url.yaml'), $runtimePatch, [Text.UTF8Encoding]::new($false))
} catch {
    foreach ($overlayPath in $createdOverlayPaths) {
        Remove-Item -LiteralPath $overlayPath -Recurse -Force -ErrorAction SilentlyContinue
    }
    throw
}
Write-Output 'private_dns_workload_overlays_created=runtime-foundation,workloads'
