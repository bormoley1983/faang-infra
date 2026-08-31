# Deployment validation

The service dependency and environment-variable mapping is documented in `runtime-contracts.md`; its machine-readable required-input subset is `service-contracts.json`.

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

Normal CI mode allows only the exact known debt listed in `baseline.json`:

```powershell
python ops/validation/validate_deployment.py
```

Strict mode ignores the baseline and must pass before final delivery:

```powershell
python ops/validation/validate_deployment.py --strict
```

Do not add a baseline entry merely to make CI green. Each entry must map to an existing DEVPLAN defect and must be removed in the change that resolves that defect.
