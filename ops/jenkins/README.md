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

## DEP-031 remaining acceptance work

- Install the reviewed exact plugin lock and validate Jenkins restart/recovery.
- Create nine multibranch jobs in `faang-untrusted`, with branch and pull-request
  discovery and repository webhooks.
- Add and prove a common source static-analysis/dependency-vulnerability gate.
  The existing trusted delivery image scan remains mandatory but does not by
  itself satisfy this source-validation item.
- Adapt the Account, Achievement, and Analytics integration suites to a
  reviewed disposable-agent dependency path. They currently launch
  Testcontainers and cannot run in the socket-free untrusted Pod. Do not mount
  a host Docker/containerd socket or introduce privileged Docker-in-Docker to
  bypass this gate.
- Run the nine `dev-local` jobs and a credential-isolation negative test, then
  retain the reports as acceptance evidence.

Do not add publication credentials to `faang-untrusted` to make a test pass.
