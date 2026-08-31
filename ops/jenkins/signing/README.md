# Jenkins Cosign identity

`cosign-keygen-pod.yaml` is a short-lived bootstrap Pod for generating the POC
Cosign key pair inside the cluster. Its key volume is memory-backed, it mounts no
service-account token, and its password comes from the temporary
`jenkins/faang-cosign-bootstrap` Secret.

After generation, import the encrypted private key and password as the
folder-scoped Jenkins credentials `faang-cosign-key` and
`faang-cosign-password` under `faang-trusted`, update `cosign.pub`, and delete
both the Pod and bootstrap Secret. Never store the private key or password in
Git, a Jenkins build log, or an untrusted job.

Trusted publication pipelines verify signatures with this repository's public
key:

```bash
cosign verify --key faang-infra/ops/jenkins/signing/cosign.pub \
  REGISTRY/REPOSITORY@sha256:DIGEST
```

Key rotation requires publishing a newly generated public key together with a
documented overlap or re-signing policy. Existing signatures remain verifiable
only while their corresponding public key is retained.
