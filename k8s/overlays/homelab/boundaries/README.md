# DEP-051 homelab boundary sources

These Kustomizations are self-contained so each can later become an Argo CD
Application source under default Kustomize load restrictions. The top-level
homelab overlay consumes all five boundaries today, so `faang-system` remains
the only live owner.

| Boundary | Intended role | Registration state |
| --- | --- | --- |
| `runtime-foundation` | Namespace and runtime ConfigMap | Staged only |
| `selected-dependencies` | Internal/external selection metadata and external aliases | Staged only |
| `retained-s3-main` | Legacy local backup store | No separate Application planned |
| `bootstrap` | Idempotent bootstrap Jobs | Staged only |
| `workloads` | FAANG Deployments, Services, and Ingress | Staged only |

The copied workload, bootstrap, and dependency inputs are intentionally kept
beside their original reusable sources. Do not edit only one copy: the
`ops/validation/test_boundary_source_equivalence.py` contract requires their
contents to remain equal. The boundary-local Kustomizations add only boundary
composition such as namespace, patch, or image-promotion ownership.

No file here registers an Argo Application. The staged AppProject/Application
definitions remain in `ops/argocd/staged-boundaries/` and are intentionally
omitted from the live Argo Kustomization until an approved manual/no-prune
handoff.
