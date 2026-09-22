"""Static and unit contracts for external and staged in-cluster monitoring."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
MONITORING = ROOT / "monitoring"
INSTALLER_PATH = MONITORING / "install.py"
SPEC = importlib.util.spec_from_file_location("monitoring_install", INSTALLER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load module spec for {INSTALLER_PATH}")
INSTALLER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = INSTALLER
SPEC.loader.exec_module(INSTALLER)


class MonitoringProfileTests(unittest.TestCase):
    def test_lxc_compose_is_pinned_private_and_secret_file_backed(self):
        text = (MONITORING / "compose.yaml").read_text(encoding="utf-8")
        for image in (
            "prom/prometheus:v3.13.3@sha256:6976aa8a60fec930796ce5772b8d12da7a318a5daa8d40d69c5c7819a05eeed7",
            "prom/alertmanager:v0.34.1@sha256:e9733bafb1bdef9b00e25a21f8f99dc26a22224bf16641ad754d1649f4c3357a",
            "grafana/grafana:13.2.2@sha256:ac461fb352abc50da10a51c7d02462e9c05488f11f53f14b3ad79a8145f638a0",
        ):
            self.assertIn(image, text)
        self.assertEqual(3, text.count("@sha256:"))
        self.assertIn("${MONITORING_BIND_ADDRESS:-127.0.0.1}", text)
        self.assertIn("GF_SECURITY_ADMIN_PASSWORD__FILE", text)
        self.assertIn("GRAFANA_ADMIN_PASSWORD_FILE", text)
        self.assertNotIn("CHANGE_ME", text)
        self.assertNotIn(":latest", text)

    def test_external_config_uses_private_file_discovery_not_raw_dependency_ports(self):
        text = (MONITORING / "prometheus/prometheus.yml").read_text(encoding="utf-8")
        self.assertIn("/etc/prometheus/file_sd/*.local.json", text)
        self.assertNotIn("postgres:5432", text)
        self.assertNotIn("redis:6379", text)
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("/monitoring/prometheus/file_sd/*.local.json", gitignore)
        example = json.loads((MONITORING / "prometheus/file_sd/targets.example.json").read_text(encoding="utf-8"))
        self.assertEqual({"external"}, {group["labels"]["placement"] for group in example})

    def test_installer_validates_private_input_and_requires_exact_apply_token(self):
        source = INSTALLER_PATH.read_text(encoding="utf-8")
        self.assertIn('CONFIRMATION = "FAANG-MONITORING-INSTALL"', source)
        self.assertIn("Mutation: none", source)
        self.assertIn("Private values: suppressed", source)
        self.assertNotIn("down -v", source)
        self.assertNotIn("volume rm", source)

        temporary = ROOT / ".cache" / "validation-tests" / f"monitoring-{os.getpid()}"
        if temporary.exists():
            shutil.rmtree(temporary)
        temporary.mkdir(parents=True)
        try:
            password = temporary / "grafana-password"
            password.write_text("a-strong-private-password\n", encoding="utf-8")
            config = temporary / "monitoring.json"
            config.write_text(
                json.dumps(
                    {
                        "bindAddress": "127.0.0.1",
                        "grafanaAdminUser": "admin",
                        "grafanaAdminPasswordFile": str(password),
                        "prometheusRetentionTime": "15d",
                        "prometheusRetentionSize": "20GB",
                    }
                ),
                encoding="utf-8",
            )
            values = INSTALLER.load_config(config)
            self.assertEqual("127.0.0.1", values["MONITORING_BIND_ADDRESS"])
            self.assertEqual(str(password), values["GRAFANA_ADMIN_PASSWORD_FILE"])

            unsafe = json.loads(config.read_text(encoding="utf-8"))
            unsafe["bindAddress"] = "0.0.0.0"
            config.write_text(json.dumps(unsafe), encoding="utf-8")
            with self.assertRaises(INSTALLER.ConfigurationError):
                INSTALLER.load_config(config)
        finally:
            shutil.rmtree(temporary, ignore_errors=True)

    def test_kubernetes_profile_renders_without_plaintext_secrets(self):
        profile = ROOT / "k8s/components/monitoring/base"
        result = subprocess.run(
            ["kubectl", "kustomize", str(profile)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn("kind: Secret\n", result.stdout)
        self.assertNotIn("CHANGE_ME", result.stdout)
        self.assertNotIn(":latest", result.stdout)
        self.assertEqual(3, result.stdout.count("storageClassName: longhorn-production-retain"))
        self.assertEqual(3, result.stdout.count("@sha256:"))
        self.assertIn("__meta_kubernetes_endpoint_port_name", result.stdout)
        self.assertIn("regex: metrics", result.stdout)

    def test_monitoring_argo_boundary_is_manual_scoped_and_unregistered(self):
        application = (ROOT / "ops/argocd/monitoring-application.yaml").read_text(encoding="utf-8")
        project = (ROOT / "ops/argocd/monitoring-project.yaml").read_text(encoding="utf-8")
        secret_application = (ROOT / "ops/argocd/monitoring-secrets-application.yaml").read_text(encoding="utf-8")
        secret_project = (ROOT / "ops/argocd/monitoring-secrets-project.yaml").read_text(encoding="utf-8")
        registered = (ROOT / "ops/argocd/kustomization.yaml").read_text(encoding="utf-8")
        staged_registered = (
            ROOT / "ops/argocd/staged-boundaries/kustomization.yaml"
        ).read_text(encoding="utf-8")
        self.assertIn("project: faang-monitoring", application)
        self.assertIn("namespace: monitoring", application)
        self.assertNotIn("automated:", application)
        self.assertNotIn("prune:", application)
        self.assertIn("name: faang-monitoring", project)
        self.assertEqual(1, project.count("namespace: monitoring"))
        self.assertNotIn("monitoring-application.yaml", registered)
        self.assertNotIn("monitoring-project.yaml", registered)
        self.assertNotIn("monitoring-secrets-application.yaml", registered)
        self.assertNotIn("monitoring-secrets-project.yaml", registered)
        self.assertNotIn("monitoring-application.yaml", staged_registered)
        self.assertNotIn("monitoring-project.yaml", staged_registered)
        self.assertNotIn("monitoring-secrets-application.yaml", staged_registered)
        self.assertNotIn("monitoring-secrets-project.yaml", staged_registered)

        self.assertIn("name: faang-monitoring-secrets", secret_project)
        self.assertIn("https://github.com/bormoley1983/faang-infra-env-homelab.git", secret_project)
        self.assertEqual(1, secret_project.count("https://github.com/bormoley1983/faang-infra-env-homelab.git"))
        self.assertEqual(1, secret_project.count("namespace: monitoring"))
        self.assertIn("clusterResourceWhitelist: []", secret_project)
        self.assertIn("group: ''", secret_project)
        self.assertEqual(1, secret_project.count("kind: Secret"))
        self.assertNotIn("kind: '*'", secret_project)

        self.assertIn("project: faang-monitoring-secrets", secret_application)
        self.assertIn("repoURL: 'https://github.com/bormoley1983/faang-infra-env-homelab.git'", secret_application)
        self.assertIn("targetRevision: main", secret_application)
        self.assertIn("path: overlays/monitoring", secret_application)
        self.assertIn("name: ksops-v1", secret_application)
        self.assertIn("namespace: monitoring", secret_application)
        self.assertIn("CreateNamespace=true", secret_application)
        for prohibited in ("automated:", "prune:", "force:", "replace:"):
            self.assertNotIn(prohibited, secret_application)

    def test_workloads_expose_separate_internal_metrics_port(self):
        profile = ROOT / "k8s/overlays/homelab/boundaries/workloads"
        result = subprocess.run(
            ["kubectl", "kustomize", str(profile)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(18, result.stdout.count("name: metrics"))
        self.assertEqual(9, result.stdout.count("metrics.faang.io/scrape: \"true\""))
        self.assertEqual(28, result.stdout.count("port: metrics"))
        self.assertEqual(9, result.stdout.count("name: MANAGEMENT_SERVER_PORT"))
        self.assertIn("kind: NetworkPolicy", result.stdout)
        self.assertIn("kubernetes.io/metadata.name: monitoring", result.stdout)

    def test_dashboard_and_datasource_are_consistent(self):
        dashboard = json.loads(
            (MONITORING / "grafana/provisioning/dashboards/faang-jvm-micrometer.json").read_text(encoding="utf-8")
        )
        self.assertEqual("faang-jvm-micrometer", dashboard["uid"])
        datasource = (MONITORING / "grafana/provisioning/datasources/prometheus.yml").read_text(encoding="utf-8")
        self.assertIn("uid: prometheus", datasource)


if __name__ == "__main__":
    unittest.main()
