# FAANG monitoring deployment profiles

The initial profile runs one Prometheus, Alertmanager, and Grafana stack in a
dedicated Proxmox LXC. The optional Kubernetes profile is staged separately and
must not be enabled merely because its manifests render.

Both placements consume the same application contract: every deployed Java
service exposes `/actuator/prometheus` on a separate internal management port
named `metrics`. Application ingress continues to target the `http` port, so
Actuator metrics are not intentionally published through ingress.

## Current profile support

| Profile | State | Purpose |
|---|---|---|
| External LXC | installable, pending live acceptance | Central Prometheus/Alertmanager/Grafana plus private file discovery for exporters on external Proxmox VMs/LXCs |
| Kubernetes | staged, not registered | Optional self-contained Prometheus/Alertmanager/Grafana using retained Longhorn PVCs |
| Kubernetes collector to LXC | planned | Secure remote-write bridge; requires an authenticated TLS receiver before it can be enabled |

PostgreSQL, Redis, Kafka, and Elasticsearch currently run externally. Install
their supported exporters beside those services and add the exporter targets
to the ignored `prometheus/file_sd/*.local.json` inventory. SeaweedFS and
Kubernetes components are Kubernetes-native targets. Raw database or broker
ports are not Prometheus endpoints and must never be listed as scrape targets.

## External LXC installation

1. Copy `../config/monitoring.example.json` to the ignored
   `../config/monitoring.local.json`.
2. Create a separately protected file containing a strong Grafana administrator
   password and set `grafanaAdminPasswordFile` to its path. The installer never
   prints the file or its contents.
3. Keep `bindAddress` on loopback for local-only access, or set it to the
   LXC's private address and enforce the approved Proxmox/firewall policy.
   Wildcard and public binds are rejected.
4. Copy `prometheus/file_sd/targets.example.json` to an ignored `.local.json`
   file and replace documentation addresses with the private exporter targets.
5. Validate without mutation:

   ```powershell
   ./install-monitoring-lxc.ps1
   ./install-monitoring-lxc.ps1 -ValidateContainers
   ```

   ```sh
   ./install-monitoring-lxc.sh
   ./install-monitoring-lxc.sh --validate-containers
   ```

6. After owner approval, install or update only this stack:

   ```powershell
   ./install-monitoring-lxc.ps1 `
     -Apply `
     -ConfirmInstall FAANG-MONITORING-INSTALL
   ```

   ```sh
   ./install-monitoring-lxc.sh \
     --apply \
     --confirm-install FAANG-MONITORING-INSTALL
   ```

The installer validates private input, renders the Compose model, pulls the
digest-pinned images, runs `promtool` and `amtool`, then starts the three
services. It performs no uninstall, volume deletion, firewall modification,
DNS change, or credential creation.

Alertmanager initially routes to a null receiver deliberately. Configure and
test real receivers from the private operations source; never commit webhook
URLs, SMTP credentials, or tokens here. Likewise, secure remote write is not
enabled until its private TLS/authentication boundary exists.

## External exporter inventory

Use one file-discovery group per role and keep labels bounded:

- `dependency`: `postgresql`, `redis`, `kafka`, `elasticsearch`, or `s3`;
- `placement`: `external` or `internal`;
- `role`: a small reviewed set such as `primary`, `replica`, or `broker`;
- `job`: the exporter type.

Do not use hostnames, addresses, database names, usernames, bucket names,
topics, index names, or customer identifiers as arbitrary labels. Private
addresses remain only in ignored `.local.json` files or the private operations
repository.

## Optional Kubernetes profile

The staged manifests are under `../k8s/components/monitoring/base`. They use
digest-pinned images, the non-default retained Longhorn StorageClass, a
runtime-only `grafana-admin` Secret supplied by the private secret boundary,
and a least-privilege monitoring AppProject.

Each monitoring Deployment has one replica and mounts a ReadWriteOnce
Longhorn PVC. Its rolling-update strategy therefore uses `maxSurge: 0` and
`maxUnavailable: 1`, stopping the existing pod before its replacement starts.
Expect a brief component outage during an image or pod-template rollout; this
prevents old and new pods from competing for the same volume.

Before registering either monitoring Application, deliver the encrypted
`grafana-admin` Secret through the separate
`../ops/argocd/monitoring-secrets-project.yaml` and
`monitoring-secrets-application.yaml` boundary. That Application is manual,
private-repository-only, and restricted to core Secrets in `monitoring`.
Review and merge both the private Secret PR and this public boundary PR before
registering it. Create the namespace from the reviewed public
`../k8s/components/monitoring/base/namespace.yaml` manifest first; the Secret
AppProject intentionally has no cluster-resource permission and its
Application uses `CreateNamespace=false`. Synchronize it manually without
prune, force, or replace, and verify only the expected Secret key names without
decoding their values.

Only after the Secret Application is healthy, register
`../ops/argocd/monitoring-project.yaml` and `monitoring-application.yaml`:

1. complete capacity and recovery review;
2. stage the encrypted `grafana-admin` Secret privately;
3. render and validate the exact protected revision;
4. inspect AppProject scope and the Application diff;
5. manually sync with prune, force, replace, and automated sync disabled;
6. verify PVCs, targets, dashboards, alerts, backup, and restore;
7. retain the LXC stack until a representative release-cycle comparison and
   rollback rehearsal pass.

For rollback, do not use Argo prune and do not delete the `monitoring`
namespace, monitoring PVCs, or retained Longhorn PVs. Stop the trial by
scaling the monitoring Deployments to zero in an approved maintenance window;
keep both Applications manual.

The Argo resources are intentionally not registered in the current root
Kustomization. Moving the monitoring control plane does not move PostgreSQL,
Redis, Kafka, or Elasticsearch into Kubernetes.

## Verification

Run from `faang-infra`:

```powershell
python -m unittest discover -s ops/validation -p "test_*.py"
kubectl kustomize k8s/components/monitoring/base
python ops/validation/validate_deployment.py `
  --schema-overlay k8s/components/monitoring/base `
  --policy-overlay k8s/overlays/homelab/boundaries/runtime-foundation `
  --policy-overlay k8s/overlays/homelab/boundaries/selected-dependencies `
  --policy-overlay k8s/overlays/homelab/boundaries/bootstrap `
  --policy-overlay k8s/overlays/homelab/boundaries/workloads `
  --strict
```

Live completion additionally requires authenticated target checks, a reboot,
backup/restore rehearsal, a test alert that fires and resolves once, and a
documented rollback. Rendering alone is not completion evidence.
