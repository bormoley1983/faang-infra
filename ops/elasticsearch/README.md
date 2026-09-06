# ECK Elasticsearch operator boundary

This profile installs ECK chart `3.4.1` and defines a one-node Elasticsearch
`9.5.2` canary. Both images are pinned to multi-architecture OCI index digests.
The canary uses a 20 GiB `longhorn-production-retain` PVC, bounded resources,
non-root execution, and worker-only scheduling.

The single Argo Application is manual and has no prune or automated sync. It
intentionally does **not** create `elasticsearch-main`, modify application
routing, create a user credential, or migrate the active external profile.
ECK keeps HTTP TLS and its generated credentials internal to the isolated
canary namespace.
