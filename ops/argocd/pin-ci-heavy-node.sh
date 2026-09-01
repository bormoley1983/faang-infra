#!/usr/bin/env bash
set -euo pipefail

LABEL_KEY="${1:-workload.faang.io/ci-heavy}"
LABEL_VALUE="${2:-true}"

PATCH=$(cat <<JSON
{"spec":{"template":{"spec":{"nodeSelector":{"${LABEL_KEY}":"${LABEL_VALUE}","kubernetes.io/arch":"amd64"}}}}}
JSON
)

kubectl -n argocd patch deployment argocd-repo-server --type merge -p "${PATCH}"
kubectl -n argocd patch statefulset argocd-application-controller --type merge -p "${PATCH}"

kubectl -n argocd rollout status deployment/argocd-repo-server --timeout=180s
kubectl -n argocd rollout status statefulset/argocd-application-controller --timeout=180s

echo "Argo CD repo-server and application-controller pinned to ${LABEL_KEY}=${LABEL_VALUE} on amd64."
