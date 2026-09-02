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
gate and archive reports. The untrusted folder has no credentials, and its job
definitions reference no registry, signing, or publication identity.

Remaining acceptance work:

- Enable and prove repository webhooks when Jenkins has an approved inbound
  endpoint. Until then, use authenticated manual or periodic indexing.
- Correct and prove the common source-security gate across all nine untrusted
  jobs. Achievement canary build 5 reached the gate but failed before analysis:
  the init script attempted plugin-ID resolution outside its plugin classpath,
  and the read-only vulnerability cache mount prevented database traversal.
  Neither failure is accepted as a security finding or a passing gate. The
  existing trusted delivery image scan remains mandatory and unchanged.

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

The canary corrections apply SpotBugs by its class loaded from the init-script
classpath. The cache remains read-only inside the untrusted container, while
the Pod-level claim is mounted so Kubernetes always applies the configured
supplemental-group ownership before exposing that read-only mount. These
corrections require a committed/pushed infrastructure revision and a fresh
canary before they are accepted.

Do not add publication credentials to `faang-untrusted` to make a test pass.
