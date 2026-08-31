# Multi-platform image contract

Each deployable service builds its Spring Boot JAR and publishes independently. The container step never rebuilds Java bytecode and therefore uses the same tested JAR for `linux/amd64` and `linux/arm64`.

`publish-service-image.ps1` performs this ordered gate:

1. Resolve the owning service's full Git revision and source URL.
   Publication fails if that service worktree is dirty, preventing a Git tag or provenance claim from describing uncommitted image inputs.
2. Build an OCI layout for amd64 and arm64 from the pinned Temurin 25 JRE image.
3. Generate pinned BuildKit SPDX SBOM and maximum-mode provenance attestations.
4. Export an SPDX SBOM and Docker Scout SARIF report for each architecture.
5. Stop before publication if either architecture has any Critical vulnerability.
6. Copy the exact scanned OCI layout to the registry through pinned ORAS.
7. Verify both platforms and both attestation manifests, then write ignored publication evidence.

The caller supplies `REGISTRY_USERNAME` and `REGISTRY_PASSWORD` from its credential store. The script never reads a committed credential file. Local topology, CA paths, reports, and publication metadata are ignored.

Example after the service build/test succeeds:

```powershell
$env:REGISTRY_USERNAME = '<from credential store>'
$env:REGISTRY_PASSWORD = '<from credential store>'
./ops/images/publish-service-image.ps1 `
  -ServiceDirectory ../faang-account_service `
  -ImageName faang-account-service `
  -RegistryEndpoint '<private-registry-endpoint>' `
  -RegistryCaFile ../faang-registry-ca.crt
```

Do not put real endpoints or credentials into this README, service Dockerfiles, Jenkinsfiles, or `service-images.json`. DEP-030 binds the registry credential in Jenkins. Signing is intentionally not performed with an ad-hoc workstation key: DEP-030 must create the protected Jenkins signing identity, after which this task resumes for Cosign signing/verification evidence.

Verify a published digest natively on both cluster architectures without starting the application or its dependencies:

```powershell
./ops/images/verify-published-image.ps1 `
  -ImageName account `
  -ImageReference '<private-registry>/faang-account-service@sha256:<digest>'
```

The smoke containers run as UID/GID 10001, drop all capabilities, mount no service-account token, and execute only `java -XshowSettings:properties -version`. Successful logs must report the expected `os.arch` on each node.
