# Bitnami Redis profile

This profile defines a manual Bitnami Redis chart `27.0.17` canary in standalone
mode. It has one retained 10 GiB Longhorn PVC, bounded resources, a non-root
security context, and worker-only scheduling. Its chart artifact and Redis
multi-architecture image index are pinned.

The canary deliberately has no application routing or credential in Git. It is
unauthenticated only because it is isolated in `faang-redis-canary` and not a
production endpoint. A production Redis profile must use a separately supplied
existing Secret and an approved cutover.
