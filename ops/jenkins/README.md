# Jenkins CI contract

FAANG uses two separate Jenkins trust zones:

- `faang-untrusted` contains multibranch validation jobs for pull requests and
  `dev-local`. These jobs must not have registry, signing, or Git write
  credentials. They run `Jenkinsfile` from the service revision being tested.
- `faang-trusted` contains owner-controlled delivery jobs. Only these jobs may
  read the registry publisher and signing credentials, and they publish only
  from the committed `dev-local` revision.

The `faang-ci` Shared Library is versioned in this repository. Write access to
this repository is therefore equivalent to Jenkins Pipeline trust and must stay
restricted to infrastructure maintainers. Service repositories contain only a
minimal wrapper selecting their existing integration-test tasks.

The untrusted library pipeline:

1. checks out the exact multibranch revision with `checkout scm`;
2. validates and executes the repository Gradle Wrapper;
3. runs `clean build`, which includes unit tests and the repository's JaCoCo
   verification policy;
4. runs `integrationTest` only for services that define that task;
5. runs pinned SpotBugs/FindSecBugs source analysis and a pinned Grype scan of
   the built dependency archive;
6. archives XML test results and security/build reports even when a gate fails.

Untrusted builds use an `emptyDir` Gradle home. They do not share the trusted
delivery cache, mount registry configuration, or bind Jenkins credentials.
Publication remains a later trusted job and cannot run when validation fails.

## DEP-031 acceptance status

The reviewed plugin lock, controller restart, Shared Library, and nine
multibranch jobs are live. Each SCM source uses the dedicated
`github-app-faang-ci` GitHub App credential with inferred-repository/read-only
contents access. All nine current `dev-local` revisions pass the common Jenkins
build, integration, source-analysis, and dependency-vulnerability baseline at
exact infrastructure revision `7bbde68edb973ba7d0dc4d4c1951956e31af8c48`
and archive their reports. The final runs are Account build 6, Achievement
build 7, Analytics build 7, Notification build 4, Payment build 4, Post build
4, Project build 3, URL Shortener build 3, and User build 3. The untrusted
folder has no credentials, and its job definitions reference no registry,
signing, or publication identity.

Deferred follow-up:

- Optional repository webhook automation is tracked separately as DEP-033 and
  remains deferred while Jenkins is private. Authenticated manual or periodic
  indexing is the accepted DEP-031 trigger model. The existing trusted delivery
  image scan remains mandatory and unchanged.

## DEP-040 infrastructure validation

The infrastructure job's existing unit-test discovery now covers the paired
internal/external dependency selection contract. It renders all ten profiles
and the all-internal, all-external, and mixed examples; rejects zero/double
selection, topology-mode disagreement, invalid connectivity, and missing
TLS/credential policy; and proves a one-dependency placement change leaves all
application Deployments unchanged. The normal desired-state stage continues to
run the pinned Kubernetes schema and strict policy checks over the selected
homelab overlay.

The infrastructure Jenkinsfile runs on a short-lived amd64 Kubernetes Pod with
a digest-pinned Python image, no service-account token, no privilege, a
read-only root filesystem, bounded resources/lifetime, and size-limited scratch
space. It downloads kubectl 1.36.0 only from the official release endpoint and
verifies the pinned SHA-256 before execution. It archives the exact checkout
revision, unit-test log, and strict deployment-validation log. It binds no
Jenkins credential and contains no publication, signing, Git-write, Argo, or
cluster-apply step.

Do not add the `timestamps()` Pipeline option: the deliberately locked plugin
set does not include its optional provider. GitHub commit-status update failures
are also expected from the read-only discovery App and are not a reason to
broaden that App; retained Jenkins build evidence is the acceptance record.

The installed GitHub Branch Source version is affected by open upstream issue
JENKINS-76287 when repository-inferred App permissions cross the
controller/agent remoting boundary. Keep the App's inferred-repository and
read-only strategies unchanged. Since this repository is intentionally public
and contains no private topology, the infrastructure pipeline uses that App
only for controller-side discovery and performs a shallow anonymous checkout
of exactly `refs/heads/dev-local` inside the disposable agent. It validates and
archives the resulting 40-character revision. If this repository becomes
private, replace this workaround only with a reviewed upstream fix or an
equally repository-scoped read-only checkout mechanism.

The lightweight validation image intentionally contains neither Git nor a
package manager mutation step. The checkout container produces a newline-only
inventory with `git ls-files` after the exact checkout; the Python validator
accepts that inventory through `--tracked-source-list`, rejects absolute,
parent-traversal, and non-YAML entries, and applies the same tracked-manifest
policy used by local Git-backed validation. The inventory is archived with the
revision and validation logs.

Acceptance completed in `faang-infra-ci` build 5 from protected revision
`09c35f9db79df73d2a5d2b977dc8817da27a0757`: all 31 tests passed, all 38
rendered resources passed schema validation, and strict policy/contract
validation reported no findings. Jenkins archived `revision.txt`,
`tracked-manifests.txt`, `tests.log`, and `deployment-validation.log` with
fingerprints. The expected read-only commit-status denial was non-fatal and the
pipeline finished successfully without publication, deployment, or Argo action.

DEP-041 adds five opt-in external-dependency preflight Jobs. The untrusted
infrastructure pipeline renders and schema-checks them with
`--schema-overlay k8s/preflight/external`; it does not run them or receive
runtime credentials. Their live, read-only execution remains an explicit
post-merge operator action from the application namespace.

Sanitized DEP-041 live evidence at the protected diagnostic contract passed
all four dependencies selected as external: Elasticsearch version/index,
Kafka's 13 required topics, PostgreSQL 18 with `uuidv7()` and seven schemas,
and authenticated Redis version/PING. Internal MinIO was correctly excluded.
Redis credential propagation into the six consuming Deployments remains a
reviewed tracked change and must pass exact-revision Jenkins validation plus an
explicit manual no-prune deployment before runtime acceptance is complete.

Do not refresh or sync Argo CD from a feature revision. For future contract
changes, merge through protected `dev-local`, run the independent
infrastructure job against that exact protected revision, and retain its
archived result. This contract change required no Jenkins controller
configuration mutation.

The pending implementation keeps dependencies inside the affected short-lived
agent Pod. Only the three wrappers opt in to digest-pinned PostgreSQL, Redis,
or Kafka sidecars. They use bounded CPU/memory and size-limited `emptyDir`
storage, and Pod termination is the cleanup boundary. The Pod mounts no host
runtime socket or host path, uses no privileged container, disables service
account token mounting, and binds no runtime or publication credential.
Developer execution retains Testcontainers; Jenkins selects explicit same-Pod
endpoints through a CI-only flag and fails if a required endpoint is missing.

The reviewed readiness correction runs bounded localhost port checks from the
JDK container. Account build 4 passed 42 integration tests, Achievement build 4
passed three, and Analytics build 5 passed 12. All corresponding XML suites are
archived, and none of those tasks was `NO-SOURCE`, skipped, or up-to-date.

The common security gate applies SpotBugs 4.10.4 through the pinned
6.5.11 Gradle plugin plus FindSecBugs 1.14.0. Maximum-effort analysis fails on
medium-or-higher confidence findings. Grype 0.116.1 is checksum-verified before
execution, consumes the existing read-only vulnerability database cache, scans
the built application archive, and fails on High or Critical dependencies.
Both reports are archived. The vulnerability cache contains no credentials and
is refreshed independently every six hours.

SpotBugs exclusions are an exact, reviewed resource in the non-overridable
Shared Library. An untrusted service revision cannot supply or broaden the
filter. Current exclusions cover only identified Spring-managed shared
collaborators, Hibernate-managed collections, generated jsonschema2pojo
classes, and one constant-name/auto-escaped Freemarker template call.

The accepted canary applies SpotBugs by its class loaded from the init-script
classpath. The cache remains read-only inside the untrusted container, while
the Pod-level claim lets Kubernetes always apply the configured
supplemental-group ownership before exposing that read-only mount. Achievement
build 6 executed, rather than suppressed, both `integrationTest` and
`spotbugsMain`; passed all three integration tests; archived SpotBugs XML/HTML
with zero findings and a valid Grype SARIF with zero findings; exposed no
publication stage; and left no agent Pod. Jenkins still has one global
read-only SCM credential and zero credentials in the untrusted folder.

The first all-service security run passed Achievement and URL Shortener. The
other seven jobs failed on archived SpotBugs findings while every Grype
High/Critical threshold passed. The reviewed remediation uses defensive copies
for response/event collections and multipart bytes, explicit null handling,
fixed-string logging at tainted boundaries, static constants, private entity
state, and exceptions instead of process termination. No finding threshold or
trusted image policy is weakened.

The final exact-revision rerun passed all nine jobs. Every `spotbugsMain` task
executed rather than being `NO-SOURCE`, skipped, or up-to-date and archived zero
findings. Every Grype High/Critical threshold passed; lower-severity advisories
remain visible in the affected SARIF reports. Account build 6 passed 42 tagged
integration tests across seven suites, Achievement build 7 passed three in one
suite, and Analytics build 7 passed 12 across two suites, all with zero
failures/errors/skips and archived XML. A repeated live negative test found the
read-only SCM identity as the sole global credential, zero credentials in the
untrusted folder, exactly that identity in all 9/9 definitions, no publication
stage, and zero remaining agent Pods.

DEP-031 is accepted without inbound webhook exposure: authenticated manual and
periodic indexing provide change discovery for the private Jenkins deployment.
Optional webhook automation remains undelivered and is tracked as deferred
DEP-033; it must not expose the Jenkins UI/controller surface when revisited.

Do not add publication credentials to `faang-untrusted` to make a test pass.

## DEP-032 GitOps proposal boundary

The staged `tests/Jenkinsfile.gitops-proposal` is a separate trusted job for
reviewable desired-state proposals. It serializes all nine services onto one
rolling `gitops/promotions` branch, updates exactly one immutable digest, and
creates or reuses one pull request to protected `dev-local`. It never merges the
pull request and never invokes Kubernetes or Argo CD.

The job must receive a dedicated `faang-gitops-proposer` credential stored only
in `faang-trusted`. Scope its identity to the infrastructure repository with
metadata read, contents read/write, and pull requests read/write. Do not reuse
the service checkout, registry publisher, signing, or untrusted GitHub App
identities. The job's Pod has no service-account token or deploy capability.

The job runs the updater, inventory, and pull-request client stashed from the
protected base revision, not code from the mutable proposal branch. Git and
Python run in separate digest-pinned, non-privileged containers. A
non-fast-forward update fails visibly and is retried normally; no force push is
used. Every commit records the exact service revision and published digest, and
the job archives proposal evidence even when a post-publication Git step fails.

Do not install or run this job from a local-only revision. First review, commit,
push, and merge the infrastructure changes. Substitute the fixed repository and
bot-identity placeholders only in the trusted Jenkins job definition; never
write credentials or private environment mappings into this repository.

The standalone proposal acceptance used only successful archived publications.
Proposal build 5 created the first one-service change and review request. Builds
6 and 7 were submitted back-to-back, executed serially, preserved the Account
and Achievement changes in one rolling branch, and reused exactly one review
request. The merged protected revision was then applied by one exact-revision
manual no-prune Argo CD sync; the application reported `Synced/Healthy` and both
affected Deployments became Ready at their intended digests. Automated sync
remained disabled.

`tests/Jenkinsfile.service-delivery` now hands the archived image name, exact
service revision, and immutable publication digest to `gitops-proposal` only
after both native architecture checks pass. It waits for the proposal result
without transferring any credential. A failed proposal turns the delivery run
red with an explicit retry instruction while retaining the already archived
publication evidence. Install this handoff into the nine trusted delivery jobs
only from its reviewed protected infrastructure revision.

Protected revision `41d7006f3c13b0c01a86d00bec974f9334f229d6`
supplied the reviewed handoff installed in all nine trusted delivery jobs.
Account delivery build 9 proved the complete runtime path: Gradle, both
architecture vulnerability gates, publication/signing, and native amd64/arm64
execution passed before GitOps proposal build 8 was invoked. The downstream
build preserved the exact archived revision/digest pair and created a
one-service review request. Its protected merge revision
`c639d7836162911508f97f9d3ce9a4a11242f53b` completed an exact-revision manual
no-prune sync; Argo CD reported `Synced/Healthy`, Account became Ready at the
intended digest with zero restarts, and automated sync remained disabled. The
merged proposal head was deleted, preventing linear-history commits from
accumulating into the next promotion cycle.

## Plugin and JCasC update policy

`values/controller-hardening.yaml` is an exact 74-plugin lock. An update-center
notification is not authorization to change individual pins: review Jenkins
core compatibility, transitive dependency changes, backup/rollback, and the
full CI acceptance suite in a separate upgrade change.

The Shared Library retriever uses the current `gitSource` JCasC symbol. The old
`git` alias is obsolete and must not be reintroduced. A focused regression test
checks both this schema field and the unchanged 74-entry lock.
