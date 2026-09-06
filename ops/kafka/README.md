# DEP-042D Phase 1 — Strimzi Kafka operator boundary

This directory contains the Argo CD boundary for the Strimzi Kafka operator and
its canary cluster. It intentionally does **not** create a production Kafka
cluster, application topics, credentials, or routing changes.

## Components

| Path | Purpose |
|------|---------|
| `operator-values.yaml` | Pinned Strimzi operator image and scheduling constraints |
| `manifests/namespace.yaml` | Declares the `faang-kafka-system` operator namespace |
| `canary/namespace.yaml` | Declares the `faang-kafka-canary` canary namespace |
| `canary/cluster.yaml` | Single-broker KRaft Kafka CR (10 GiB Longhorn PVC) |

## Argo applications

- `faang-kafka-canary` — one multi-source Application: the pinned Strimzi
  chart, operator namespace manifest, and canary directory. It deploys the
  operator into `faang-kafka-system` and the Kafka CR into
  `faang-kafka-canary`. Manual sync, no prune. The Kafka CR is sync wave 1, so
  Argo waits for the wave-0 operator resources to be healthy first.

## Cutover boundary

The external `kafka-main` Service in the `faang` namespace remains unchanged
until Phase 5 (approved cutover). At that point, only the Service routing is
switched to the Strimzi internal listener; the application contract
(`KAFKA_BOOTSTRAP_SERVERS=kafka-main:9092`) does not change.

## Backup and restore

The canary uses Kafka-native replication (RF=1) for fault tolerance within the
single broker. Volume-level recovery is via Longhorn snapshot or PVC copy.
Production will use RF=3 with MirrorMaker 2 for cross-cluster DR. No external
backup target is required for the canary phase.
