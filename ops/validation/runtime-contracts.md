# Runtime configuration contract

This matrix is the human-readable companion to `service-contracts.json`. Kubernetes environment names must match each service's `application.yaml`; `*_HOST` values are hostnames without a scheme, and Feign clients add `http://` explicitly. ConfigMaps contain only non-secret values. All credentials and credential-bearing URLs come from `faang-secrets` until DEP-043 replaces the example contract with SOPS/age delivery.

| Service | Port | Stateful dependencies | Internal clients | Required secret inputs | External/optional behavior |
|---|---:|---|---|---|---|
| Account | 8090 | PostgreSQL | None | PostgreSQL user/password | None |
| Achievement | 8085 | PostgreSQL | User | PostgreSQL user/password | None |
| Analytics | 8086 | PostgreSQL, Redis, Kafka | Project | PostgreSQL user/password | None |
| Notification | 8083 | Kafka | User | SMTP user/password, Telegram token, Vonage key/secret | SMTP, Telegram, and Vonage are configured through the injected delivery contract. |
| Payment | 8082 | Redis | None | Currency-exchange access key | Currency API URL is non-secret; the access key is Secret-backed. |
| Post | 8081 | PostgreSQL, Redis, Kafka, S3/MinIO | Project, User, Payment | PostgreSQL, S3/MinIO, moderation credential-bearing URL | Spellchecker URL is non-secret. Moderation no longer has a source-code API key default. |
| Project | 8082 | PostgreSQL, Redis, S3/MinIO | Payment, User | PostgreSQL and S3/MinIO | Jira and Google Calendar default to explicitly disabled; enabling them requires their protected credentials. |
| URL Shortener | 18080 | PostgreSQL, Redis | None | PostgreSQL user/password | Base and public redirect URLs are environment-specific ConfigMap values. |
| User | 8080 | PostgreSQL, Redis, Kafka, S3/MinIO | Payment; Project endpoint reserved by configuration | PostgreSQL and S3/MinIO | DiceBear API URL and the dedicated avatar bucket are configurable. No default S3 credentials remain in source. |

## Shared naming rules

- `DATABASE_URL`, `DATABASE_USERNAME`, `DATABASE_PASSWORD`, and `DATABASE_SCHEMA` are the application-facing PostgreSQL contract. Kubernetes assembles these from `POSTGRES_*` configuration and Secret keys.
- `REDIS_URL` currently means a hostname for Spring Redis clients; `REDIS_PORT` is separate. DEP-040 may introduce a better logical endpoint name while preserving service compatibility.
- `KAFKA_SERVERS` is a comma-separated bootstrap-server list.
- `PROJECT_SERVICE_HOST`, `PAYMENT_SERVICE_HOST`, and `USER_SERVICE_HOST` are hostname-only values. Their ports are separate.
- Post Service consumes `MINIO_*`; Project and User consume `S3_*`. Kubernetes maps both conventions to the same `MINIO_ACCESS_KEY` and `MINIO_SECRET_KEY` Secret keys, so credentials are not duplicated.
- `S3_BUCKET_NAME` is the shared application bucket; `S3_AVATAR_BUCKET_NAME` is the User avatar bucket. The MinIO bootstrap Job creates both idempotently.
- `APP_ENV` selects the User Service Spring profile and is `production` in homelab.
- `URL_SHORTENER_BASE_URL` and `URL_SHORTENER_PUBLIC_URL` must be externally reachable URLs for the selected environment.
- External Elasticsearch uses `ELASTICSEARCH_USERNAME` and `ELASTICSEARCH_PASSWORD` from `faang-secrets`. The homelab POC currently sets `ELASTICSEARCH_TLS_INSECURE=true` because the external certificate does not cover the cluster-local Service alias; production must use a trusted CA and a SAN-correct private endpoint.

## Optional integration policy

- Google Calendar: `GOOGLE_CALENDAR_ENABLED=false` by default. Enabling it also requires `GOOGLE_CALENDAR_CREDENTIALS_JSON` from a Secret.
- Jira: `JIRA_ENABLED=false` by default. A disabled invocation fails clearly; enabling it requires an HTTPS base URL, allowed-host list, username, and password.
- Notification transports are part of the current homelab contract and therefore receive their credential references. A later feature-level change may make each transport independently conditional.
- Currency exchange and Post moderation are treated as required by the current application code and therefore fail configuration when their protected input is absent.

## Validation boundary

Run from `faang-infra`:

```powershell
python -m unittest discover -s ops/validation -p "test_*.py"
python ops/validation/validate_deployment.py
```

The validator checks required environment variables, ports, probes, ConfigMap/Secret references, schemas, and known deployment debt. Service compilation/tests remain owned by the individual service repository pipelines.
