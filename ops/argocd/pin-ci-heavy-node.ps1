param(
    [string]$LabelKey = "workload.faang.io/ci-heavy",
    [string]$LabelValue = "true"
)

$ErrorActionPreference = "Stop"

$selectorPatch = @{
    spec = @{
        template = @{
            spec = @{
                nodeSelector = @{
                    $LabelKey = $LabelValue
                    "kubernetes.io/arch" = "amd64"
                }
            }
        }
    }
} | ConvertTo-Json -Depth 20 -Compress

kubectl -n argocd patch deployment argocd-repo-server --type merge -p $selectorPatch | Out-Host
kubectl -n argocd patch statefulset argocd-application-controller --type merge -p $selectorPatch | Out-Host

kubectl -n argocd rollout status deployment/argocd-repo-server --timeout=180s | Out-Host
kubectl -n argocd rollout status statefulset/argocd-application-controller --timeout=180s | Out-Host

Write-Host "Argo CD repo-server and application-controller pinned to $LabelKey=$LabelValue on amd64." -ForegroundColor Green
