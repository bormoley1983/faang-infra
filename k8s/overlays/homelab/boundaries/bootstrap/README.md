# Bootstrap contract

The homelab overlay includes four independent, versioned Kubernetes Jobs:

| Job | Wave | Contract |
|---|---:|---|
| `faang-bootstrap-postgres-v1` | -40 | Creates the `faang` database when absent and the seven schemas used by database-backed services. |
| `faang-bootstrap-kafka-v1` | -39 | Creates the version-1 topic set with Kafka 4.3.1. |
| `faang-bootstrap-elasticsearch-v1` | -38 | Creates `hashtags_index` with curl 8.21.0. |
| `faang-bootstrap-s3-v1` | -37 | Creates the application and user-avatar buckets with `--ignore-existing`. |

The namespace is wave -60; the application ConfigMap, script ConfigMap, and dedicated token-free ServiceAccount are wave -50. Application Deployments remain at wave 0. Argo CD therefore waits for each bootstrap Job before advancing. The Jobs are ordinary versioned resources, not hooks: a completed Job remains completed and is not recreated by normal reconciliation.

## Images and architecture

Jobs use official PostgreSQL, Apache Kafka 4.3.1, curl 8.21.0, and the S3 client (`mc`) image pinned to an immutable multi-platform manifest digest. The selected manifests were verified to contain both `linux/amd64` and `linux/arm64`. The curl image is only the Elasticsearch HTTP bootstrap client; Elasticsearch itself is 9.5.2. No workstation-local bootstrap image is built or required.

## Reconciliation and versioning

All operations are idempotent and bounded to 60 readiness attempts. A second execution is expected to succeed without duplicating schemas, topics, indexes, or buckets.

Do not edit a completed Job's pod template. To introduce a new bootstrap contract:

1. update the script and its tests;
2. increment the script ConfigMap and affected Job name from `v1` to `v2`;
3. update `faang.io/bootstrap-contract`;
4. review the stateful migration and rollback implications;
5. let Argo create the new Job in its declared wave.

Routine application reconciliation must not bump this version. Database schema migrations remain owned by each service's Liquibase changelog; PostgreSQL major-version migration is a separate stateful operation.

## Observation and failure handling

```powershell
kubectl -n faang get jobs -l app.kubernetes.io/component=bootstrap
kubectl -n faang logs job/faang-bootstrap-postgres-v1
kubectl -n faang logs job/faang-bootstrap-kafka-v1
kubectl -n faang logs job/faang-bootstrap-elasticsearch-v1
kubectl -n faang logs job/faang-bootstrap-s3-v1
```

A failed negative-wave Job blocks later Argo waves. Correct the endpoint, protected credential, dependency health, or script contract; then explicitly delete only the failed versioned Job and request a reviewed Argo sync. Do not delete completed Jobs merely to force routine reruns.

The Jobs do not call the Kubernetes API. They use the dedicated `faang-bootstrap` ServiceAccount with token automount disabled, so no Role or RoleBinding is required.

`kubectl apply -k` does not implement Argo sync-wave ordering. Workstation scripts therefore remain emergency-only and must not be used for the first rollout. Normal bootstrap execution belongs to the existing Argo CD application after secrets and dependency endpoints are ready.
