# Deployment validation

The service dependency and environment-variable mapping is documented in `runtime-contracts.md`; its machine-readable required-input subset is `service-contracts.json`.

Dependency placement is a separate one-of-two contract. Its policy is defined
in `dependency-contracts.json` and enforced by
`validate_dependency_selection.py`. The public topology example deliberately
uses documentation-only addresses, so validating that example requires the
explicit test-only allowance:

```powershell
python ops/validation/validate_dependency_selection.py `
  --kustomization k8s/overlays/homelab/kustomization.yaml `
  --selection-overlay k8s/overlays/homelab/boundaries/selected-dependencies `
  --topology config/homelab.example.json `
  --configmap k8s/overlays/homelab/boundaries/runtime-foundation/configmap.yaml `
  --allow-documentation-addresses
```

Never use `--allow-documentation-addresses` for a real environment mapping.
The local installer invokes the same validator without that flag.

Run from the `faang-infra` repository root:

```powershell
python ops/validation/validate_deployment.py `
  --policy-overlay k8s/overlays/homelab/boundaries/runtime-foundation `
  --policy-overlay k8s/overlays/homelab/boundaries/selected-dependencies `
  --policy-overlay k8s/overlays/homelab/boundaries/bootstrap `
  --policy-overlay k8s/overlays/homelab/boundaries/workloads
python -m unittest discover -s ops/validation -p "test_*.py"
```

Linux Jenkins agents use `python3` with the same arguments.

## DEP-052 post-deployment evidence

Application follow-ups found after trusted ingress verification are recorded in
[service-followups.md](service-followups.md). They are deliberately separate
from infrastructure acceptance evidence and do not authorize infrastructure
changes.

`collect-post-deployment-verification.ps1` is the default read-only release
collector. It emits sanitized JSON only: Argo sync/health and safe revision
identifiers, workload readiness and image digests, Service endpoint counts,
Ingress presence/rule count, and bootstrap Job completion. It does not output
addresses, hosts, certificate details, or Secret data, and it cannot create,
apply, delete, sync, restart, retry, scale, or port-forward resources.

Run from an authorized operator shell after a manual `faang-workloads` sync:

```powershell
./ops/validation/collect-post-deployment-verification.ps1 -Context <reviewed-context> |
  Set-Content -Encoding utf8 .\dep-052-sanitized-baseline.json
```

To evaluate one externally trusted ingress route, pass a reviewed URI with
`-IngressUri`. The output records only DNS outcome, status code, TLS outcome,
and redirect presence. To perform an external readiness
acceptance check, additionally pass the reviewed, exact HTTPS endpoint:

```powershell
./ops/validation/collect-post-deployment-verification.ps1 `
  -Context <reviewed-context> `
  -ReadinessUri https://<reviewed-service-host>/actuator/health/readiness `
  -RequireReadiness
```

That check accepts only the exact readiness path, validates TLS without bypasses,
and passes only when the endpoint returns HTTP 200 with JSON status `UP`; the
`-RequireReadiness` switch fails the command for any other outcome. Use this
generic check with the User Service hostname for its required external readiness
acceptance.
Dependency entries deliberately remain `not-probed`: a separately approved,
scoped, read-only in-cluster diagnostic context is required. The existing
external-preflight runner is excluded because it creates short-lived Jobs.

For an observation-only Jenkins result, pass a reviewed **HTTPS** Jenkins base URI and
job path, and supply a narrowly scoped read-only API identity through
`FAANG_JENKINS_API_USER` and `FAANG_JENKINS_API_TOKEN`. The collector records
only collection status, result, building state, and duration; it never records
the URI, job name, credentials, console output, or build parameters. It makes
one bounded HTTPS request and has no Argo credential, CLI, or mutation path.

For the owner-approved in-cluster service smoke gate, use the separate,
explicitly mutation-capable runner below. It creates one tokenless disposable
Job, checks Actuator liveness/readiness for all nine application services,
including User Service, then deletes that exact Job by default.
It has no dependency credentials and performs no dependency, migration, Kafka,
or S3 operation. Do not add its manifest to Argo.

```powershell
./run-post-deployment-smoke.ps1 -ConfirmActiveProbe -Context <reviewed-context>
```

The validator:

- renders the homelab overlay with the installed `kubectl` Kustomize version;
- downloads the pinned kubeconform binary into ignored `.cache/tools`, verifies its official SHA-256 checksum, and validates against the pinned Kubernetes schema version;
- rejects unresolved `${...}` tokens, mutable/placeholder workload images, selected persistent workloads using `emptyDir`, and tracked plaintext Secret manifests;
- permits only credential-free Argo CD Helm-OCI repository Secrets under `ops/argocd` (all other tracked plaintext Secrets remain prohibited);
- checks ConfigMap/Secret references and the per-service environment/port/probe contract;
- compares findings with `baseline.json`, failing on new findings or stale baseline entries.

The unit suite also renders all ten dependency profiles plus the all-internal,
all-external, and mixed examples; rejects zero/double selection and incomplete
topology, TLS, or credential policy; and proves that switching one dependency
does not modify application Deployments.

Normal CI mode allows only the exact known debt listed in `baseline.json`:

```powershell
python ops/validation/validate_deployment.py `
  --policy-overlay k8s/overlays/homelab/boundaries/runtime-foundation `
  --policy-overlay k8s/overlays/homelab/boundaries/selected-dependencies `
  --policy-overlay k8s/overlays/homelab/boundaries/bootstrap `
  --policy-overlay k8s/overlays/homelab/boundaries/workloads
```

Strict mode ignores the baseline and must pass before final delivery:

```powershell
python ops/validation/validate_deployment.py --strict `
  --policy-overlay k8s/overlays/homelab/boundaries/runtime-foundation `
  --policy-overlay k8s/overlays/homelab/boundaries/selected-dependencies `
  --policy-overlay k8s/overlays/homelab/boundaries/bootstrap `
  --policy-overlay k8s/overlays/homelab/boundaries/workloads `
  --schema-overlay k8s/preflight/external
```

`--schema-overlay` renders and schema-checks an additional opt-in resource set
without treating references to environment-owned ConfigMaps or Secrets as part
of the homelab desired-state policy. Jenkins uses it for the external
dependency preflight Jobs, which are deliberately excluded from Argo desired
state.

Do not add a baseline entry merely to make CI green. Each entry must map to an existing DEVPLAN defect and must be removed in the change that resolves that defect.
