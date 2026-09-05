# External dependency preflights

These opt-in Jobs perform read-only checks through the same stable Services the
applications use. The runner creates Jobs only for dependencies whose ignored
local topology entry selects `external`. It never prints or embeds physical
addresses or credential values.

The checks prove PostgreSQL 18 and `uuidv7()` plus the seven bootstrapped
schemas, Redis `PING`, the thirteen Kafka topics, the Elasticsearch version and
`hashtags_index`, and both required S3 buckets. They do not create or alter
databases, schemas, topics, indices, buckets, or application resources.

Each Job uses a pinned client image, a tokenless ServiceAccount, restricted
container security with an explicit numeric non-root UID/GID, bounded
CPU/memory/scratch space, no host mount, no
privilege, a bounded deadline, no retry, and automatic TTL cleanup. Network
clients have shorter connection/request limits, and the runner observes one
dependency at a time so failures retain their logs before the Job deadline. The
PowerShell runner also removes its exact Jobs, ConfigMap, and ServiceAccount in
a `finally` block unless `-KeepResources` is explicitly requested for bounded
diagnosis. Repository attributes enforce LF endings for shell scripts because
the files are mounted verbatim from ConfigMap data. Runs must be serialized.

After a reviewed revision is merged, validate the ignored topology and run:

```powershell
./run-external-preflights.ps1
```

Do not add this directory to the Argo application. These are explicit operator
checks, not continuously reconciled desired state. A failed check is a hard
stop: preserve its sanitized log, correct connectivity/TLS/credentials or run
the existing idempotent bootstrap contract, then rerun the preflight. Never
work around failure by editing application endpoint names.

Keep the following operational record privately for every selected external
dependency: observed version and capacity, service owner, backup mechanism,
backup location owner, RPO, RTO, last successful restore exercise, monitoring
owner, and failure-escalation path. PostgreSQL additionally requires recorded
major-version migration and rollback evidence. Do not place real hosts, people,
contact paths, backup locations, or topology in this public repository.

DEP-041 cannot be resolved until every selected external check passes from the
application namespace, the existing bootstrap contract and service startup are
proven through the stable aliases, the private operational records are
complete, and the temporary Elasticsearch insecure-TLS exception is replaced
with verified trust and a certificate valid for the private endpoint.
