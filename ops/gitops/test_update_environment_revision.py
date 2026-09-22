import json
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

from update_environment_revision import (
    EnvironmentPromotionError,
    PUBLIC_REPOSITORY,
    SERVICE_NAMES,
    create_or_reuse_environment_pull_request,
    update_environment_revision,
    validate_rendered_workloads,
)


OLD_REVISION = "1" * 40
NEW_REVISION = "2" * 40


class _Response:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class EnvironmentRevisionUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parent
        self.path = self.root / f".test-environment-{uuid.uuid4().hex}.yaml"
        self.addCleanup(self._remove_test_files)

    def _remove_test_files(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        for path in self.root.glob(f".{self.path.name}.*.tmp"):
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def write(self, revision: str = OLD_REVISION) -> None:
        self.path.write_text(
            "apiVersion: kustomize.config.k8s.io/v1beta1\n"
            "kind: Kustomization\n"
            "resources:\n"
            f"  - {PUBLIC_REPOSITORY}//k8s/overlays/homelab/"
            f"boundaries/workloads?ref={revision}\n"
            "patches:\n"
            "  - path: ingress-private-dns-tls.yaml\n",
            encoding="utf-8",
        )

    def test_updates_exactly_one_old_revision(self) -> None:
        self.write()
        result = update_environment_revision(self.path, PUBLIC_REPOSITORY, NEW_REVISION)
        self.assertTrue(result.changed)
        self.assertEqual(OLD_REVISION, result.previous_revision)
        self.assertIn(f"?ref={NEW_REVISION}", self.path.read_text(encoding="utf-8"))
        self.assertIn("ingress-private-dns-tls.yaml", self.path.read_text(encoding="utf-8"))

    def test_updates_initial_dev_local_reference(self) -> None:
        self.write("dev-local")
        result = update_environment_revision(self.path, PUBLIC_REPOSITORY, NEW_REVISION)
        self.assertTrue(result.changed)
        self.assertEqual("dev-local", result.previous_revision)

    def test_same_revision_is_idempotent(self) -> None:
        self.write(NEW_REVISION)
        before = self.path.read_bytes()
        result = update_environment_revision(self.path, PUBLIC_REPOSITORY, NEW_REVISION)
        self.assertFalse(result.changed)
        self.assertEqual(before, self.path.read_bytes())

    def test_rejects_invalid_revision(self) -> None:
        self.write()
        with self.assertRaisesRegex(EnvironmentPromotionError, "40 lowercase"):
            update_environment_revision(self.path, PUBLIC_REPOSITORY, "main")

    def test_rejects_different_repository(self) -> None:
        self.write()
        with self.assertRaisesRegex(EnvironmentPromotionError, "not allowlisted"):
            update_environment_revision(
                self.path,
                "https://github.com/example/other.git",
                NEW_REVISION,
            )

    def test_rejects_missing_or_ambiguous_reference(self) -> None:
        self.path.write_text("resources: []\n", encoding="utf-8")
        with self.assertRaisesRegex(EnvironmentPromotionError, "found 0"):
            update_environment_revision(self.path, PUBLIC_REPOSITORY, NEW_REVISION)

        line = (
            f"  - {PUBLIC_REPOSITORY}//k8s/overlays/homelab/"
            f"boundaries/workloads?ref={OLD_REVISION}\n"
        )
        self.path.write_text(f"resources:\n{line}{line}", encoding="utf-8")
        with self.assertRaisesRegex(EnvironmentPromotionError, "found 2"):
            update_environment_revision(self.path, PUBLIC_REPOSITORY, NEW_REVISION)

    def test_rejects_different_public_path(self) -> None:
        self.path.write_text(
            f"resources:\n  - {PUBLIC_REPOSITORY}//k8s/base?ref={OLD_REVISION}\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(EnvironmentPromotionError, "found 0"):
            update_environment_revision(self.path, PUBLIC_REPOSITORY, NEW_REVISION)


class EnvironmentPullRequestTests(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_reuses_existing_pull_request(self, urlopen) -> None:
        urlopen.return_value = _Response([{"html_url": "https://github.com/example/pr/1"}])
        url, created = create_or_reuse_environment_pull_request(
            "bormoley1983/faang-infra-env-homelab",
            "bormoley1983",
            "token",
            "env/promotions",
            "main",
        )
        self.assertFalse(created)
        self.assertEqual("https://github.com/example/pr/1", url)
        request = urlopen.call_args.args[0]
        self.assertIn("head=bormoley1983%3Aenv%2Fpromotions", request.full_url)

    @patch("urllib.request.urlopen")
    def test_creates_environment_pull_request_with_specific_title(self, urlopen) -> None:
        urlopen.side_effect = [
            _Response([]),
            _Response({"html_url": "https://github.com/example/pr/2"}),
        ]
        url, created = create_or_reuse_environment_pull_request(
            "bormoley1983/faang-infra-env-homelab",
            "bormoley1983",
            "token",
            "env/promotions",
            "main",
        )
        self.assertTrue(created)
        self.assertEqual("https://github.com/example/pr/2", url)
        request = urlopen.call_args_list[1].args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(
            "chore(gitops): promote public workload revision", payload["title"]
        )
        self.assertEqual("env/promotions", payload["head"])
        self.assertEqual("main", payload["base"])

    def test_rejects_non_allowlisted_pull_request_boundary(self) -> None:
        with self.assertRaisesRegex(EnvironmentPromotionError, "not allowlisted"):
            create_or_reuse_environment_pull_request(
                "bormoley1983/other",
                "bormoley1983",
                "token",
                "env/promotions",
                "main",
            )
        with self.assertRaisesRegex(EnvironmentPromotionError, "boundary"):
            create_or_reuse_environment_pull_request(
                "bormoley1983/faang-infra-env-homelab",
                "bormoley1983",
                "token",
                "main",
                "main",
            )


class RenderedWorkloadValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parent
        self.path = self.root / f".test-rendered-{uuid.uuid4().hex}.yaml"
        self.addCleanup(self.path.unlink, missing_ok=True)

    def valid_render(self) -> str:
        documents: list[str] = []
        for service in SERVICE_NAMES:
            documents.append(
                f"""apiVersion: apps/v1
kind: Deployment
metadata:
  name: {service}
spec:
  template:
    spec:
      containers:
        - name: application
          image: docker-registry:5000/{service}@sha256:{'1' * 64}
          ports:
            - containerPort: 9090
              name: metrics
          env:
            - name: MANAGEMENT_SERVER_PORT
              value: \"9090\"
"""
            )
            documents.append(
                f"""apiVersion: v1
kind: Service
metadata:
  name: {service}
  labels:
    metrics.faang.io/scrape: \"true\"
spec:
  ports:
    - name: metrics
      port: 9090
      targetPort: metrics
"""
            )
        documents.append(
            """apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: faang-application-metrics
spec:
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: monitoring
"""
        )
        return "---\n".join(documents)

    def test_accepts_bounded_observability_contract(self) -> None:
        self.path.write_text(self.valid_render(), encoding="utf-8")
        validate_rendered_workloads(self.path)

    def test_rejects_secret_or_mutable_image(self) -> None:
        self.path.write_text(
            self.valid_render()
            + "---\napiVersion: v1\nkind: Secret\nmetadata:\n  name: forbidden\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(EnvironmentPromotionError, "Secret"):
            validate_rendered_workloads(self.path)

        mutable = self.valid_render().replace(
            f"docker-registry:5000/{SERVICE_NAMES[0]}@sha256:{'1' * 64}",
            f"docker-registry:5000/{SERVICE_NAMES[0]}:latest",
        )
        self.path.write_text(mutable, encoding="utf-8")
        with self.assertRaisesRegex(EnvironmentPromotionError, "mutable latest"):
            validate_rendered_workloads(self.path)


if __name__ == "__main__":
    unittest.main()
