# FAANG infrastructure

This repository is the public, portable GitOps and operations source for the
FAANG platform. It contains no real topology, credentials, kubeconfig data,
or plaintext runtime Secrets.

## Verified delivery model

- Existing k3s, Rancher, Argo CD, Longhorn, MetalLB, Traefik, cert-manager,
  Jenkins, and Distribution registry installations are reused.
- Jenkins validates and proposes one immutable workload image-digest update.
  It does not apply manifests or sync Argo CD.
- Argo CD watches the protected delivery branch and is operated manually:
  automated sync, prune, self-heal, force, and replace are disabled.
- The private environment repository supplies encrypted runtime Secrets,
  topology, private DNS, and private TLS overlays.

## Repository map

- `k8s/base/`: portable application resource structure.
- `k8s/overlays/homelab/`: public example composition. It is not a place for
  real domains or endpoint mappings.
- `k8s/overlays/homelab/boundaries/`: independently owned runtime foundation,
  selected-dependencies, bootstrap, retained-backup, and workload sources.
- `k8s/components/dependencies/`: reviewed internal/external dependency
  profile components and render-only examples.
- `ops/argocd/`: named AppProjects, Applications, and staged App-of-Apps
  definitions.
- `ops/gitops/`: digest proposal and workload-only rollback tooling.
- `ops/validation/`: render, policy, boundary, and post-deployment evidence
  checks.

## Current runtime selection

PostgreSQL, Redis, Kafka, and Elasticsearch use external aliases.
Application S3 uses the separate internal `faang-object-storage` endpoint.
`s3-main` is retained local backup storage under `faang-system`; it is not the
active application S3 endpoint and must not be pruned through routine delivery.

## Operator path

Start at the root [deployment guide](../README_DEPLOY.md). Before a manual
Argo action, validate the intended Git revision and inspect the exact
Application diff. Sync only the approved Application, with Prune, Force, and
Replace disabled; then collect sanitized read-only evidence.

Do not use `deploy.ps1`, `deploy.sh`, or direct `kubectl apply` as routine
delivery mechanisms. Those legacy emergency paths do not encode the current
Application ownership gates.

## Focused documentation

- [Kubernetes operator access](K8S-SETUP.md)
- [Operations and GitOps](ops/README.md)
- [Validation and post-deployment evidence](ops/validation/README.md)
- [Dependency selection](k8s/components/dependencies/README.md)
- [Bootstrap contract](k8s/bootstrap/README.md)
- [Registry trust](k8s/registry/README.md)
- [Workload rollback](ops/gitops/workload-rollback.md)
