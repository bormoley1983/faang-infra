# Private DNS and TLS registration runbook

Type: operator runbook

Use this runbook for a private, organization-controlled DNS zone and a private
CA trusted by managed clients. It is deliberately topology-neutral: replace
the placeholders only in the separate private environment repository, never in
the public `faang-infra` source.

## Scope and hostname design

Prefer a dedicated application subtree:

| Purpose | Recommended hostname | Certificate coverage |
| --- | --- | --- |
| FAANG workloads | `<service>.faang.<internal-zone>` | `*.faang.<internal-zone>` |
| Argo CD | `argo.<internal-zone>` | exact SAN on a management certificate |
| Jenkins | `jenkins.<internal-zone>` | exact SAN on a management certificate |
| Other management UIs | one exact hostname each | exact SANs on a management certificate |

A wildcard matches exactly one DNS label. Therefore:

- `*.faang.<internal-zone>` covers `account.faang.<internal-zone>` and
  `user.faang.<internal-zone>`.
- It **does not** cover `argo.<internal-zone>`, `jenkins.<internal-zone>`, or
  `api.account.faang.<internal-zone>`.
- `*.<internal-zone>` would cover direct one-label
  subdomains such as Argo and Jenkins, but it is unnecessarily broad and still
  does not cover the two-label FAANG names. Use separate application and
  management certificates unless a documented PKI policy requires otherwise.

Do not use `.local` for new names: it conflicts with multicast DNS. Do not use
`.home.arpa` when a managed AD/private DNS zone is the intended client resolver.

## Preconditions

1. The private DNS owner approves the `<internal-zone>` and the record set.
2. Managed clients trust the private CA root and any issuing intermediate. For
   Windows/AD clients, distribute these through the approved Group Policy trust
   store; define an equivalent managed trust process for Linux, browsers, and
   mobile/other clients.
3. The private CA can issue server certificates with the required DNS SANs and
   appropriate server-authentication key usage.
4. The Traefik LoadBalancer address is known only to the private DNS owner.
   Do not add it to public Git or shared evidence.
5. The private environment repository is Argo-readable and encrypts TLS private
   keys with the approved SOPS/age process.

## DNS record registration

Create private-zone A and, where applicable, AAAA records for every approved
name. Point them to the existing Traefik LoadBalancer address. Use individual
records for the initial rollout; a wildcard record is acceptable only after the
DNS owner confirms that it cannot capture unrelated names.

Before any Argo sync, validate from an authorized domain workstation:

```powershell
Resolve-DnsName account.faang.<internal-zone> -Type A
Resolve-DnsName argo.<internal-zone> -Type A
Resolve-DnsName jenkins.<internal-zone> -Type A
```

Record only pass/fail and the hostname class in shared evidence, not addresses.

## Certificate issuance and custody

### Recommended current model: issue outside Kubernetes, store encrypted

This is the preferred model while there is no approved cert-manager issuer.

1. Generate the private key and CSR in the approved private-CA workflow. Never
   paste keys into chat, public Git, ConfigMaps, Jenkins, or shell history.
2. Request an application certificate with SAN `*.faang.<internal-zone>`.
3. Request a separate management certificate with exact SANs for approved
   management UIs (for example Argo and Jenkins). Do not add unrelated services.
4. Verify the returned chain, SANs, expiry, key usage, and issuer with the CA
   owner before registration.
5. Put the PEM certificate chain and key into namespace-scoped
   `kubernetes.io/tls` Secret manifests in the private environment repository.
   Encrypt the `tls.crt` and `tls.key` values with SOPS/age. Keep structure and
   Secret names reviewable, but never commit plaintext material.
6. Retain the CA issuance record, serial number, owner, renewal date, and
   revocation process in the private operations record—not public Git.

Application Ingress Secret shape, stored only encrypted in the private source:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: faang-ingress-tls
  namespace: faang
type: kubernetes.io/tls
stringData:
  tls.crt: <SOPS-encrypted PEM chain>
  tls.key: <SOPS-encrypted private key>
```

`stage-private-tls-secret.ps1` can stage one encrypted Secret from a PFX after
prompting locally for its password. It holds plaintext PEM only in process
memory, writes a short-lived plaintext input file beside the requested output
only while SOPS runs, removes it in `finally`, refuses an absolute/escaping
output path or overwrite, and never contacts Kubernetes or Argo.

### Optional later model: cert-manager issuer

Do not add a self-signed issuer merely to remove a manual step. Add a
cert-manager `Issuer` or `ClusterIssuer` only after the PKI owner approves its
authentication, renewal, revocation, key custody, and audit model. Prefer an
external/private-CA issuer integration. A CA issuer whose signing key is stored
in Kubernetes changes the private-key threat model and needs separate approval.

When an issuer is approved, declare the issuer and `Certificate` resources in
the private environment repository, scoped to the consuming namespace where
possible. Do not rely on a secret from `faang` for Argo or Jenkins: Kubernetes
Secrets are namespace-scoped and each ingress needs a Secret in its own
namespace.

Before staging a management PFX, use
`prepare-private-management-tls-overlays.ps1` to create separate private
`argocd` and `jenkins` overlay skeletons and extend the existing private SOPS
creation rule. It refuses an ambiguous rule or an existing overlay and never
contacts Kubernetes or Argo.

After all three encrypted TLS manifests have been staged, run
`configure-private-tls-ksops-overlays.ps1`. It registers the application
certificate with the existing Homelab KSOPS generator and creates separate
KSOPS generators for the Argo CD and Jenkins namespace overlays. This is the
required bridge between encrypted files in Git and Argo render output; it does
not decrypt a Secret, call SOPS, or contact Kubernetes.

## Private environment overlay changes

The generic public workload source must remain unchanged. In the private
environment overlay:

1. Patch all nine `Ingress/faang-ingress` hosts to
   `<service>.faang.<internal-zone>`.
2. Add `spec.tls` with all nine hosts and `secretName: faang-ingress-tls`.
3. Patch `URL_SHORTENER_BASE_URL` and `URL_SHORTENER_PUBLIC_URL` to the HTTPS
   URL-shortener hostname. Keep service-to-service names unchanged.
4. Add the encrypted `faang-ingress-tls` Secret to the private source that Argo
   decrypts, then register it with the private KSOPS generator. Do not add it
   to the public generic repository.
5. For Argo and Jenkins, update their own private Ingress/Helm values and put
   the management TLS Secret in `argocd` and `jenkins` respectively. Do not
   reuse a cross-namespace Secret.
6. Reconcile the dedicated `faang-private-tls` Argo project and its three
   child Applications (`faang-ingress-tls`, `argocd-management-tls`, and
   `jenkins-management-tls`) through the approved root/source handoff. The
   runtime/workload Applications continue to use the generic source; do not patch their `repoURL` or `targetRevision` live.

## Manual reconciliation sequence

All syncs remain manual. Automated sync, prune, self-heal, force, and replace
remain disabled.

1. Review private-source render output and a resource inventory. Confirm that
   the only workload changes are Ingress hosts/TLS and the two URL-shortener
   values; confirm no dependency, bootstrap, storage, or Secret deletion.
2. Validate DNS resolution and private-CA trust from the domain workstation.
3. Reconcile the approved private-source/root handoff, then manually sync
   `faang-runtime-foundation` and `faang-workloads` with prune disabled.
4. Verify Argo `Synced/Healthy`, nine ready workloads/endpoints, and Ingress
   presence. Never restart services merely to refresh an Ingress certificate.
5. Run the DEP-052 collector with one HTTPS application URI. It must report
   DNS resolved, a meaningful HTTP status, and `tls: validated`.
6. Validate Argo and Jenkins individually against their exact management
   names, using trusted TLS. Their availability is not evidence that application
   wildcard coverage is correct.

## Renewal, revocation, and rollback

- Track certificate expiry and begin renewal before the CA-defined lead time.
  Reissue into the same namespace/Secret name, commit the encrypted private
  change, manually sync the owning Application, and re-run trusted TLS checks.
- For compromise or revocation, obtain a replacement certificate first; then
  update the encrypted Secret and reconcile it. Record serial/revocation facts
  privately. Do not delete the serving Secret before a replacement exists.
- To roll back a DNS/TLS change, revert only the reviewed private overlay
  revision and manually sync the affected Application with prune disabled.
  DNS TTL propagation and client trust caches can delay visible recovery.
- A certificate rollback cannot undo data, dependency, bootstrap, or schema
  changes. Treat those as separate recovery decisions.

## Acceptance evidence

- Every approved hostname resolves in the intended private DNS view.
- Certificate SANs match the exact hostname class; issuer chain is trusted by
  the validation client; certificate is within validity period.
- Each namespace has only its intended TLS Secret; no private key is present in
  public Git, Jenkins, ConfigMaps, or shared logs.
- Argo remains manual/no-prune and reports the affected Applications
  `Synced/Healthy` after reconciliation.
- DEP-052 records DNS/HTTP/TLS/redirect outcomes without host addresses,
  certificate subjects, keys, or tokens.
