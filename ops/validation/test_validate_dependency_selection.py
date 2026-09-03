import copy
import importlib.util
import json
import subprocess
import sys
import unittest
from unittest import mock
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("validate_dependency_selection.py")
SPEC = importlib.util.spec_from_file_location("validate_dependency_selection", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load module spec for {MODULE_PATH}")
VALIDATOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VALIDATOR
SPEC.loader.exec_module(VALIDATOR)
ROOT = MODULE_PATH.parents[2]
CONTRACT_PATH = MODULE_PATH.with_name("dependency-contracts.json")
CONTRACTS = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))["dependencies"]
EXAMPLE_PATH = ROOT / "config" / "homelab.example.json"
CONFIGMAP_PATH = ROOT / "k8s" / "overlays" / "homelab" / "configmap.yaml"
DEPENDENCIES = {"postgresql", "redis", "elasticsearch", "kafka", "minio"}


def render(path: Path) -> str:
    result = subprocess.run(
        ["kubectl", "kustomize", str(path)],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return result.stdout


def documents(rendered: str) -> dict[tuple[str, str], str]:
    import re

    result: dict[tuple[str, str], str] = {}
    for document in re.split(r"(?m)^---\s*$", rendered):
        kind = re.search(r"(?m)^kind:\s*([^\s#]+)", document)
        metadata = re.search(r"(?ms)^metadata:\s*\n(?P<body>(?:^[ \t]+.*\n?)*)", document)
        name = re.search(r"(?m)^\s+name:\s*([^\s#]+)", metadata.group("body")) if metadata else None
        if kind and name:
            result[(kind.group(1), name.group(1))] = document.strip()
    return result


def topology_for(modes: dict[str, str]) -> dict:
    topology = copy.deepcopy(json.loads(EXAMPLE_PATH.read_text(encoding="utf-8")))
    for index, name in enumerate(sorted(DEPENDENCIES), start=31):
        entry = topology["dependencies"][name]
        entry["mode"] = modes[name]
        if modes[name] == "external":
            entry["address"] = f"192.0.2.{index}"
            entry["port"] = CONTRACTS[name]["servicePort"]
        else:
            entry.pop("address", None)
            entry.pop("port", None)
    return topology


class DependencySelectionTests(unittest.TestCase):
    def assert_selection_error(self, function, *arguments):
        with self.assertRaises(VALIDATOR.SelectionError):
            function(*arguments)

    def test_all_profiles_render_one_stable_service_and_mode_marker(self):
        for dependency, contract in CONTRACTS.items():
            for mode in ("external", "internal"):
                profile = ROOT / "k8s" / "components" / "dependencies" / dependency / mode
                rendered = render(profile)
                resources = documents(rendered)
                service = resources[("Service", contract["serviceName"])]
                marker = resources[("ConfigMap", f"faang-dependency-{dependency}-selection")]
                self.assertIn(f"port: {contract['servicePort']}", service)
                self.assertIn(f"mode: {mode}", marker)
                if mode == "external":
                    self.assertNotIn("\n  selector:", service)
                else:
                    self.assertIn("\n  selector:", service)

    def test_homelab_selection_matches_the_explicit_example_contract(self):
        with self.assertRaises(VALIDATOR.SelectionError):
            VALIDATOR.validate(
                ROOT / "k8s" / "overlays" / "homelab" / "kustomization.yaml",
                EXAMPLE_PATH,
                CONFIGMAP_PATH,
                CONTRACT_PATH,
            )
        selected = VALIDATOR.validate(
            ROOT / "k8s" / "overlays" / "homelab" / "kustomization.yaml",
            EXAMPLE_PATH,
            CONFIGMAP_PATH,
            CONTRACT_PATH,
            allow_documentation_addresses=True,
        )
        self.assertEqual(
            {name: value["mode"] for name, value in topology_for(selected)["dependencies"].items()},
            selected,
        )

    def test_all_external_all_internal_and_mixed_examples_validate(self):
        cases = {
            "all-external": {name: "external" for name in DEPENDENCIES},
            "all-internal": {name: "internal" for name in DEPENDENCIES},
            "mixed": {
                "postgresql": "external",
                "redis": "external",
                "elasticsearch": "external",
                "kafka": "external",
                "minio": "internal",
            },
        }
        for example, modes in cases.items():
            kustomization = ROOT / "k8s" / "environments" / "examples" / example / "kustomization.yaml"
            self.assertEqual(modes, VALIDATOR.selected_profiles(kustomization, DEPENDENCIES))
            VALIDATOR.validate_topology(
                modes,
                topology_for(modes),
                CONTRACTS,
                allow_documentation_addresses=True,
            )
            VALIDATOR.validate_configmap(CONFIGMAP_PATH, CONTRACTS)

    def test_zero_and_double_selection_are_rejected(self):
        kustomization = ROOT / "k8s" / "overlays" / "homelab" / "kustomization.yaml"
        with mock.patch.object(VALIDATOR, "section_items", return_value=[]):
            self.assert_selection_error(VALIDATOR.selected_profiles, kustomization, DEPENDENCIES)
        resources = [
            f"../../components/dependencies/{name}/external"
            for name in sorted(DEPENDENCIES)
        ]
        resources.append("../../components/dependencies/redis/internal")
        with mock.patch.object(VALIDATOR, "section_items", return_value=resources):
            self.assert_selection_error(VALIDATOR.selected_profiles, kustomization, DEPENDENCIES)

    def test_missing_or_inconsistent_policy_data_is_rejected(self):
        modes = {name: "external" for name in DEPENDENCIES}
        valid = topology_for(modes)
        mutations = []
        missing_address = copy.deepcopy(valid)
        missing_address["dependencies"]["postgresql"].pop("address")
        mutations.append(missing_address)
        missing_tls = copy.deepcopy(valid)
        missing_tls["dependencies"]["redis"].pop("tls")
        mutations.append(missing_tls)
        missing_credentials = copy.deepcopy(valid)
        missing_credentials["dependencies"]["kafka"].pop("credentials")
        mutations.append(missing_credentials)
        wrong_mode = copy.deepcopy(valid)
        wrong_mode["dependencies"]["minio"]["mode"] = "internal"
        mutations.append(wrong_mode)
        for topology in mutations:
            with self.subTest(topology=topology):
                with self.assertRaises(VALIDATOR.SelectionError):
                    VALIDATOR.validate_topology(
                        modes,
                        topology,
                        CONTRACTS,
                        allow_documentation_addresses=True,
                    )

    def test_switching_minio_changes_only_its_connection_and_workload_resources(self):
        external = documents(render(ROOT / "k8s" / "environments" / "examples" / "all-external"))
        mixed = documents(render(ROOT / "k8s" / "environments" / "examples" / "mixed"))
        deployment_keys = {key for key in external | mixed if key[0] == "Deployment"}
        self.assertTrue(deployment_keys)
        for key in deployment_keys:
            self.assertEqual(external[key], mixed[key], key)
        changed = {
            key
            for key in external.keys() & mixed.keys()
            if external[key] != mixed[key]
        } | (external.keys() ^ mixed.keys())
        self.assertEqual(
            {
                ("ConfigMap", "faang-dependency-minio-selection"),
                ("Service", "minio-main"),
                ("StatefulSet", "minio-main"),
            },
            changed,
        )

    def test_profiles_never_track_physical_addresses(self):
        profile_root = ROOT / "k8s" / "components" / "dependencies"
        for path in profile_root.rglob("*.yaml"):
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"(?m)^\s*-?\s*addresses?:\s*")


if __name__ == "__main__":
    unittest.main()
