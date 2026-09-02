# GitOps digest promotion helper

`update_image_digest.py` is the mutation boundary for DEP-032. It updates one
allowlisted service in `k8s/overlays/homelab/kustomization.yaml` and never
performs Git, Jenkins, Argo CD, Kubernetes, registry, or credential operations.

Run it from the `faang-infra` repository root with the exact digest archived by
the completed trusted publication job:

```bash
python3 ops/gitops/update_image_digest.py \
  faang-account-service \
  sha256:<64-lowercase-hexadecimal-characters>
```

For a retry based on an observed current value, use
`--expected-current-digest sha256:<current-digest>`. A mismatch or workspace
lock returns exit code 75 and must be retried from the latest Git state. Invalid
input or an ambiguous mapping returns exit code 1. Repeating an already-applied
update succeeds without changing the file.

The adjacent lock serializes mutations in one workspace. Cross-workspace and
cross-build concurrency remains the responsibility of the promotion workflow:
start from the latest protected `dev-local`, validate the resulting diff, and
refresh or recreate a conflicted promotion branch rather than forcing it.

## Jenkins proposal boundary

`../jenkins/tests/Jenkinsfile.gitops-proposal` defines a separate trusted job.
It serializes all service proposals into `gitops/promotions`, fast-forwards that
branch without force-pushing, and creates or reuses one pull request targeting
protected `dev-local`. The job accepts only one of the nine inventory images, a
40-character lowercase service revision, and an immutable lowercase digest.

The proposal job deliberately has no registry, signing, Argo CD, Kubernetes,
runtime, or service-checkout credential. Its only credential must be stored in
the trusted folder as `faang-gitops-proposer` and owned by a dedicated identity
restricted to this infrastructure repository. The minimum repository
permissions are metadata read, contents read/write, and pull requests
read/write. Do not store this identity globally or expose it to service PR jobs.

Before switching to the mutable proposal branch, the job stashes its updater,
inventory, and pull-request client from protected `dev-local`. Only those
protected copies execute while the credential is bound. The credential is
scoped to fetch/push and pull-request API calls and is absent during the digest
mutation itself.

The rolling job plus `disableConcurrentBuilds()` serializes proposals from all
nine delivery jobs. A second service update starts from the existing proposal,
merges the latest protected base, and preserves the first service change. A
concurrent external branch update causes a normal non-fast-forward push failure;
the job never force-pushes and can be retried with the same published evidence.
The pull request remains a human review boundary, and Jenkins never merges it
or asks Argo CD to sync.

The Jenkinsfile contains installation placeholders for the fixed repository
URL/slug/owner and bot commit name/email. Substitute them only in the trusted
job definition after this revision is pushed. Do not put local mappings,
credentials, or private topology into this repository.

Run the focused tests with:

```bash
python3 -m unittest discover -s ops/gitops -p "test_*.py"
```

The legacy `ops/jenkins/update-image-tag.sh` edits `newTag` and is retained only
for the obsolete root proof-of-concept pipeline. DEP-032 must not call it.
