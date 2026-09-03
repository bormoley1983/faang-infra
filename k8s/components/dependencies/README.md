# Dependency selection contract

Each dependency exposes the same cluster-local Service name in both modes. An
environment must include exactly one `internal` or `external` profile for each
of PostgreSQL, Redis, Elasticsearch, Kafka, and MinIO.

External profiles own only selectorless Services. Physical addresses and
EndpointSlices are environment-private data and must never be committed here.
Internal profiles own Services with selectors. DEP-042 will add persistent
workloads, backup/restore, placement, and upgrade contracts; the existing MinIO
POC is the only internal profile that currently includes a workload.

Every profile also emits one deterministic selection ConfigMap containing its
mode. These markers make the selected state reviewable and machine-verifiable;
applications continue to consume stable endpoint keys from `faang-config`, so
switching dependency location does not rewrite application Deployments.

The public examples under `k8s/environments/examples` prove all-external,
all-internal, and mixed selection rendering. They are contract examples, not
deployable production environments. Validate a selection and its separate
topology policy with `ops/validation/validate_dependency_selection.py` before
any environment-specific implementation or sync.
