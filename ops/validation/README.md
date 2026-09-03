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
  --topology config/homelab.example.json `
  --configmap k8s/overlays/homelab/configmap.yaml `
  --allow-documentation-addresses
```

Never use `--allow-documentation-addresses` for a real environment mapping.
The local installer invokes the same validator without that flag.

Run from the `faang-infra` repository root:

```powershell
python ops/validation/validate_deployment.py
python -m unittest discover -s ops/validation -p "test_*.py"
```

Linux Jenkins agents use `python3` with the same arguments.

The validator:

- renders the homelab overlay with the installed `kubectl` Kustomize version;
- downloads the pinned kubeconform binary into ignored `.cache/tools`, verifies its official SHA-256 checksum, and validates against the pinned Kubernetes schema version;
- rejects unresolved `${...}` tokens, mutable/placeholder workload images, selected persistent workloads using `emptyDir`, and tracked plaintext Secret manifests;
- checks ConfigMap/Secret references and the per-service environment/port/probe contract;
- compares findings with `baseline.json`, failing on new findings or stale baseline entries.

The unit suite also renders all ten dependency profiles plus the all-internal,
all-external, and mixed examples; rejects zero/double selection and incomplete
topology, TLS, or credential policy; and proves that switching one dependency
does not modify application Deployments.

Normal CI mode allows only the exact known debt listed in `baseline.json`:

```powershell
python ops/validation/validate_deployment.py
```

Strict mode ignores the baseline and must pass before final delivery:

```powershell
python ops/validation/validate_deployment.py --strict `
  --schema-overlay k8s/preflight/external
```

`--schema-overlay` renders and schema-checks an additional opt-in resource set
without treating references to environment-owned ConfigMaps or Secrets as part
of the homelab desired-state policy. Jenkins uses it for the external
dependency preflight Jobs, which are deliberately excluded from Argo desired
state.

Do not add a baseline entry merely to make CI green. Each entry must map to an existing DEVPLAN defect and must be removed in the change that resolves that defect.
