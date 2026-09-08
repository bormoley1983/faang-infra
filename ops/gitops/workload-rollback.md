# Workload-only rollback runbook

Type: operator runbook

This is a DEP-052 proposal and execution record. It does not authorize a
rollback by itself. It applies only to `faang-workloads`; never use it for
dependencies, bootstrap, secrets, storage, `s3-main`, cluster configuration,
or an Argo Application/AppProject change.

## Eligibility gate

All conditions must be true before requesting approval:

1. The incident affects a Deployment, Service, or Ingress owned by
   `faang-workloads`, and current and known-good full Git revisions are recorded.
2. The proposal changes only `k8s/overlays/homelab/boundaries/workloads/`; it
   has no schema migration, bootstrap, dependency-profile, Secret,
   persistent-data, or external-endpoint implication.
3. `faang-workloads` remains the owner and the five DEP-051 Applications have
   no unexpected ownership/tracking warning.
4. A read-only comparison shows no deletion or change outside the declared
   workload set.

Capture only sanitized revision IDs, resource identities, health states, and
the decision. Do not record addresses, Secret values, credentials, certificate
details, or raw application logs.

```sh
argocd app get faang-workloads --refresh
argocd app diff faang-workloads --revision <known-good-full-git-sha>
git diff --name-only <known-good-full-git-sha>..<current-full-git-sha> -- \
  k8s/overlays/homelab/boundaries/workloads
```

## Mandatory stops

Stop and obtain a separate forward-fix or restore plan if any of the following
occurs: a prune/deletion proposal; a shared-resource or tracking-owner warning;
a change outside `faang-workloads`; an unready dependency; a degraded
non-affected workload; a schema/data/bootstrap effect; a secret, profile,
storage, external endpoint, or `s3-main` change; or an unavailable prior
revision.

Git revert cannot undo an executed migration, a Kafka/S3/data write, or a
stateful configuration change. Those are never workload rollbacks.

## Approved execution only

After the incident owner explicitly approves the recorded proposal, revert only
the reviewed workload source to the known-good revision, merge it through the
normal protected Git review path, then manually sync only `faang-workloads`.
Keep automated sync, self-heal, force, replace, and prune disabled. The manual
sync must use `--prune=false`; do not retry or bulk-sync other Applications.

```sh
argocd app sync faang-workloads --revision <approved-revert-full-git-sha> --prune=false
argocd app wait faang-workloads --sync --health --timeout 300
```

Immediately run the read-only DEP-052 collector and separately approved smoke
gate. Record recovery time from approved sync start to all declared workloads
healthy. If the gate fails, stop: do not oscillate revisions; open a forward-fix
or restore decision with the captured evidence.
