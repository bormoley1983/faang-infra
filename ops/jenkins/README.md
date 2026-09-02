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
5. archives XML test results and build reports even when the gate fails.

Untrusted builds use an `emptyDir` Gradle home. They do not share the trusted
delivery cache, mount registry configuration, or bind Jenkins credentials.
Publication remains a later trusted job and cannot run when validation fails.

## DEP-031 acceptance status

The reviewed plugin lock, controller restart, Shared Library, and nine
multibranch jobs are live. Each SCM source uses the dedicated
`github-app-faang-ci` GitHub App credential with inferred-repository/read-only
contents access. All nine current `dev-local` revisions pass the common Jenkins
gate and archive reports. The untrusted folder has no credentials, and its job
definitions reference no registry, signing, or publication identity.

Remaining acceptance work:

- Enable and prove repository webhooks when Jenkins has an approved inbound
  endpoint. Until then, use authenticated manual or periodic indexing.
- Add and prove a common source static-analysis/dependency-vulnerability gate.
  The existing trusted delivery image scan remains mandatory but does not by
  itself satisfy this source-validation item.
- Commit, push, and independently prove the pending Account, Achievement, and
  Analytics `integrationTest` task wiring and disposable dependency path.
  Until Jenkins executes the tagged suites and archives their XML reports, the
  last pushed `NO-SOURCE` results remain the acceptance record.

The pending implementation keeps dependencies inside the affected short-lived
agent Pod. Only the three wrappers opt in to digest-pinned PostgreSQL, Redis,
or Kafka sidecars. They use bounded CPU/memory and size-limited `emptyDir`
storage, and Pod termination is the cleanup boundary. The Pod mounts no host
runtime socket or host path, uses no privileged container, disables service
account token mounting, and binds no runtime or publication credential.
Developer execution retains Testcontainers; Jenkins selects explicit same-Pod
endpoints through a CI-only flag and fails if a required endpoint is missing.

The first exact-revision run proved all dependency containers healthy but also
found that Jenkins durable shell steps cannot start inside those service
containers. Account build 3 failed before Gradle; Achievement and Analytics
build 3 were stopped after confirming the same condition. No integration report
was claimed, and all agent Pods were removed. The pending correction keeps the
sidecars unchanged and runs bounded localhost port checks from the JDK container,
whose pinned image includes the required probe utility.

Do not add publication credentials to `faang-untrusted` to make a test pass.
