# Service follow-ups after private ingress verification

Type: application follow-up log

Status: deferred application work; no infrastructure change is authorized by
this record.

## Verified infrastructure boundary

Private DNS, trusted private-CA TLS, Traefik HTTPS routing, service selection,
and the application ingress Secret are working. Seven application services
returned successful readiness responses through trusted external HTTPS.

The findings below are application routing/observability gaps. They are not
DNS, certificate, Argo CD, Kubernetes Service, or Traefik failures.

## USER-001 — User service has no external readiness endpoint

Observed behavior:

- The User workload pod and Service endpoint were ready.
- HTTPS reached the User application successfully.
- Requests to `/actuator/health/readiness` and `/` received application JSON
  error responses reporting no matching static resource.
- The application maps an unmapped request to HTTP 500 instead of HTTP 404.

Required service work:

1. Expose bounded, unauthenticated liveness and readiness endpoints, preferably
   Spring Boot Actuator `/actuator/health/liveness` and
   `/actuator/health/readiness`.
2. Configure Kubernetes liveness/readiness probes only after those endpoints
   return HTTP 200 under normal dependency conditions.
3. Correct exception handling so an unmapped route returns HTTP 404 rather
   than HTTP 500.
4. Add a service-level test for the published health contract and one external
   ingress acceptance check using that contract.

Until resolved, external User verification is limited to trusted TLS and
request routing; it is not a functional readiness assertion.

## PROJECT-001 — Project service Swagger UI is not exposed at the tested path

Observed behavior:

- HTTPS reached the Project application successfully.
- The tested Swagger UI route returned the application’s Spring Boot fallback
  404 page.

Required service decision:

1. If interactive API documentation is a supported deliverable, enable and
   test the chosen OpenAPI/Swagger UI route, and document its stable path.
2. If it is intentionally not exposed, document that decision and use the
   service’s readiness endpoint or another approved read-only endpoint for
   operational verification.

Do not add an ingress rewrite, wildcard route, or Traefik middleware solely to
make an undocumented Swagger path appear to work.

## Closure evidence

Close an item only with the owning service revision, a passing service test,
and a trusted external HTTPS result. Do not include credentials, private
addresses, certificate material, or full request logs in this document.
