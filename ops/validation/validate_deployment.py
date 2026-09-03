#!/usr/bin/env python3
"""Render and validate FAANG Kubernetes desired state without cluster access."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OVERLAY = ROOT / "k8s" / "overlays" / "homelab"
DEFAULT_BASELINE = Path(__file__).with_name("baseline.json")
DEFAULT_CONTRACTS = Path(__file__).with_name("service-contracts.json")
KUBERNETES_SCHEMA_VERSION = "1.36.0"
KUBECONFORM_VERSION = "0.8.0"
KUBECONFORM_ASSETS = {
    ("darwin", "amd64"): ("kubeconform-darwin-amd64.tar.gz", "71dbc87ac9f24099a62b93570e65aa06312ba6ac8aea63b7f86e9d999edf5a92"),
    ("darwin", "arm64"): ("kubeconform-darwin-arm64.tar.gz", "f84f4dfbebf4a6b0b230385fa065a39ea35e02608c2b50d025dcf64775a69d67"),
    ("linux", "amd64"): ("kubeconform-linux-amd64.tar.gz", "9bc2bffbf71f261128533edaf912153948b7ff238f9a531ae6d34466ec287883"),
    ("linux", "arm64"): ("kubeconform-linux-arm64.tar.gz", "1f53fc8e81258197a35e8603054162a5af1de8c5af13746c71ab680d9534ed87"),
    ("windows", "amd64"): ("kubeconform-windows-amd64.zip", "e3f56102bcf4f50b034a567e2482a1c5330799983ddd655952310211aef73d93"),
    ("windows", "arm64"): ("kubeconform-windows-arm64.zip", "4f3c9889f5f3a1e4aba84f9212f599ad3164d1fb32175fba3a53b505b0fffd0f"),
}
STATEFUL_NAME_PATTERN = re.compile(r"(postgres|redis|kafka|elastic|elasticsearch|minio|registry)", re.IGNORECASE)


@dataclass(frozen=True, order=True)
class Issue:
    code: str
    location: str
    detail: str

    @property
    def fingerprint(self) -> str:
        return f"{self.code}|{self.location}|{self.detail}"


def run(command: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, input=input_text, text=True, capture_output=True, check=False)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Required command was not found: {command[0]}") from exc


def split_documents(text: str) -> list[str]:
    return [document.strip() + "\n" for document in re.split(r"(?m)^---\s*$", text) if document.strip()]


def resource_identity(document: str) -> tuple[str, str]:
    kind_match = re.search(r"(?m)^kind:\s*([^\s#]+)", document)
    metadata_match = re.search(r"(?ms)^metadata:\s*\n(?P<body>(?:^[ \t]+.*\n?)*)", document)
    name_match = re.search(r"(?m)^\s+name:\s*([^\s#]+)", metadata_match.group("body")) if metadata_match else None
    return (kind_match.group(1) if kind_match else "Unknown", name_match.group(1) if name_match else "unknown")


def top_level_keys(document: str, section_names: tuple[str, ...]) -> set[str]:
    lines = document.splitlines()
    keys: set[str] = set()
    for index, line in enumerate(lines):
        if line.strip() not in {f"{name}:" for name in section_names} or line[:1].isspace():
            continue
        for child in lines[index + 1 :]:
            if child and not child[:1].isspace():
                break
            match = re.match(r"^\s{2}([A-Za-z0-9_.-]+):", child)
            if match:
                keys.add(match.group(1))
    return keys


def references(document: str) -> list[tuple[str, str, str]]:
    lines = document.splitlines()
    found: list[tuple[str, str, str]] = []
    for index, line in enumerate(lines):
        match = re.match(r"^(\s*)(configMapKeyRef|secretKeyRef):\s*$", line)
        if not match:
            continue
        indentation = len(match.group(1))
        values: dict[str, str] = {}
        for child in lines[index + 1 :]:
            child_indent = len(child) - len(child.lstrip())
            if child.strip() and child_indent <= indentation:
                break
            value_match = re.match(r"^\s+(name|key):\s*([^\s#]+)", child)
            if value_match:
                values[value_match.group(1)] = value_match.group(2).strip('"\'')
        if "name" in values and "key" in values:
            found.append((match.group(2), values["name"], values["key"]))
    return found


def deployment_environment(document: str) -> set[str]:
    return set(re.findall(r"(?m)^\s+- name:\s*([A-Z][A-Z0-9_]*)\s*$", document))


def validate_rendered(rendered: str, contracts: dict[str, object]) -> list[Issue]:
    documents = split_documents(rendered)
    resources: dict[tuple[str, str], str] = {resource_identity(document): document for document in documents}
    issues: set[Issue] = set()

    config_keys: dict[tuple[str, str], set[str]] = {}
    for (kind, name), document in resources.items():
        if kind == "ConfigMap":
            config_keys[(kind, name)] = top_level_keys(document, ("data", "binaryData"))
        elif kind == "Secret":
            config_keys[(kind, name)] = top_level_keys(document, ("data", "stringData"))

    secret_example = ROOT / "k8s" / "overlays" / "homelab" / "secret.example.yaml"
    if secret_example.exists():
        example_text = secret_example.read_text(encoding="utf-8")
        _, example_name = resource_identity(example_text)
        config_keys[("Secret", example_name)] = top_level_keys(example_text, ("data", "stringData"))

    for (kind, name), document in resources.items():
        location = f"{kind}/{name}"
        # The generated bootstrap ConfigMap contains executable shell scripts,
        # where ${...} is intentional runtime expansion rather than a missed
        # manifest substitution.
        tokens = [] if (kind, name) == ("ConfigMap", "faang-bootstrap-scripts-v1") else sorted(
            set(re.findall(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}", document))
        )
        for token in tokens:
            issues.add(Issue("POL001", location, f"unresolved token {token}"))

        if kind in {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"}:
            for image in sorted(set(re.findall(r"(?m)^\s*image:\s*([^\s#]+)", document))):
                if image.endswith(":latest") or image.endswith(":bootstrap") or ":latest@" in image:
                    issues.add(Issue("POL002", location, f"mutable or placeholder image {image}"))

        if kind in {"Deployment", "StatefulSet"} and STATEFUL_NAME_PATTERN.search(name):
            has_empty_dir = re.search(r"(?m)^\s*emptyDir:\s*", document)
            has_persistent_storage = re.search(
                r"(?m)^\s*(?:persistentVolumeClaim|volumeClaimTemplates):\s*", document
            )
            if has_empty_dir and not has_persistent_storage:
                issues.add(Issue("POL003", location, "persistent service uses emptyDir without persistent storage"))

        for reference_type, referenced_name, key in references(document):
            referenced_kind = "ConfigMap" if reference_type == "configMapKeyRef" else "Secret"
            available = config_keys.get((referenced_kind, referenced_name))
            if available is None:
                issues.add(Issue("REF001", location, f"missing {referenced_kind} contract {referenced_name}"))
            elif key not in available:
                issues.add(Issue("REF002", location, f"missing key {referenced_kind}/{referenced_name}:{key}"))

    raw_service_contracts = contracts.get("services") if contracts else None
    service_contracts = raw_service_contracts if isinstance(raw_service_contracts, dict) else {}
    for deployment_name_raw, contract_value in service_contracts.items():
        deployment_name = str(deployment_name_raw)
        contract = contract_value if isinstance(contract_value, dict) else {}
        location = f"Deployment/{deployment_name}"
        document = resources.get(("Deployment", deployment_name))
        if document is None:
            issues.add(Issue("CON001", location, "deployment is missing"))
            continue
        expected_port = int(contract.get("containerPort", 0))
        ports = {int(value) for value in re.findall(r"(?m)^\s*- containerPort:\s*(\d+)\s*$", document)}
        if expected_port and expected_port not in ports:
            issues.add(Issue("CON002", location, f"missing container port {expected_port}"))
        missing_env = sorted(set(contract.get("requiredEnv", [])) - deployment_environment(document))
        if missing_env:
            issues.add(Issue("CON003", location, f"missing env {','.join(missing_env)}"))
        for probe in ("livenessProbe", "readinessProbe"):
            if not re.search(rf"(?m)^\s*{probe}:\s*$", document):
                issues.add(Issue("CON004", location, f"missing {probe}"))

    return sorted(issues)


def validate_source_text(relative_path: Path, text: str) -> list[Issue]:
    issues: list[Issue] = []
    for token in sorted(set(re.findall(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}", text))):
        issues.append(Issue("POL001", relative_path.as_posix(), f"unresolved token {token}"))
    if re.search(r"(?m)^kind:\s*Secret\s*$", text) and not re.search(r"(?m)^sops:\s*$", text):
        issues.append(Issue("SEC001", relative_path.as_posix(), "tracked plaintext Secret manifest"))
    return issues


def validate_tracked_sources(relative_names: list[str] | None = None) -> list[Issue]:
    if relative_names is None:
        result = run(["git", "-C", str(ROOT), "ls-files", "*.yaml", "*.yml"])
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Unable to list tracked manifests")
        relative_names = result.stdout.splitlines()
    issues: list[Issue] = []
    for relative_name in relative_names:
        relative_path = Path(relative_name)
        if (
            relative_path.is_absolute()
            or ".." in relative_path.parts
            or relative_path.suffix.lower() not in {".yaml", ".yml"}
        ):
            raise RuntimeError("Tracked source list contains an invalid manifest path")
        if ".example." in relative_path.name or relative_path.parts[:3] == ("ops", "validation", "fixtures"):
            continue
        path = ROOT / relative_path
        if not path.exists():
            # A valid working-tree validation may include tracked files staged
            # for deletion before the corresponding commit is created.
            continue
        text = path.read_text(encoding="utf-8")
        issues.extend(validate_source_text(relative_path, text))
    return issues


def normalized_platform() -> tuple[str, str]:
    system = platform.system().lower()
    machine = platform.machine().lower()
    architecture = "arm64" if machine in {"arm64", "aarch64"} else "amd64" if machine in {"amd64", "x86_64"} else machine
    return system, architecture


def install_kubeconform() -> Path:
    system, architecture = normalized_platform()
    asset = KUBECONFORM_ASSETS.get((system, architecture))
    if not asset:
        raise RuntimeError(f"No pinned kubeconform build for {system}/{architecture}")
    asset_name, expected_hash = asset
    executable_name = "kubeconform.exe" if system == "windows" else "kubeconform"
    install_dir = ROOT / ".cache" / "tools" / f"kubeconform-{KUBECONFORM_VERSION}-{system}-{architecture}"
    executable = install_dir / executable_name
    if executable.exists():
        return executable

    install_dir.mkdir(parents=True, exist_ok=True)
    archive = install_dir / asset_name
    url = f"https://github.com/yannh/kubeconform/releases/download/v{KUBECONFORM_VERSION}/{asset_name}"
    request = urllib.request.Request(url, headers={"User-Agent": "faang-deployment-validator"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, archive.open("wb") as destination:
            shutil.copyfileobj(response, destination)
    except OSError as exc:
        raise RuntimeError(f"Unable to download pinned kubeconform from {url}: {exc}") from exc

    actual_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
    if actual_hash != expected_hash:
        archive.unlink(missing_ok=True)
        raise RuntimeError(f"Checksum mismatch for {asset_name}: expected {expected_hash}, received {actual_hash}")

    if asset_name.endswith(".zip"):
        with zipfile.ZipFile(archive) as package:
            package.extract(executable_name, install_dir)
    else:
        with tarfile.open(archive, "r:gz") as package:
            member = next((item for item in package.getmembers() if Path(item.name).name == executable_name), None)
            if member is None:
                raise RuntimeError(f"{executable_name} was not found in {asset_name}")
            source = package.extractfile(member)
            if source is None:
                raise RuntimeError(f"Unable to read {executable_name} from {asset_name}")
            with source, executable.open("wb") as destination:
                shutil.copyfileobj(source, destination)
    executable.chmod(executable.stat().st_mode | stat.S_IEXEC)
    archive.unlink(missing_ok=True)
    return executable


def validate_schema(rendered: str) -> None:
    executable = install_kubeconform()
    schema_cache = ROOT / ".cache" / "kubeconform" / f"kubernetes-{KUBERNETES_SCHEMA_VERSION}"
    schema_cache.mkdir(parents=True, exist_ok=True)
    result = run([
        str(executable),
        "-cache",
        str(schema_cache),
        "-strict",
        "-summary",
        "-kubernetes-version",
        KUBERNETES_SCHEMA_VERSION,
        "-ignore-missing-schemas",
        "-",
    ], input_text=rendered)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "kubeconform schema validation failed")


def load_json(path: Path) -> dict[str, object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unable to load {path}: {exc}") from exc


def evaluate_baseline(issues: list[Issue], baseline_path: Path, strict: bool) -> bool:
    current = {issue.fingerprint for issue in issues}
    baseline_data = load_json(baseline_path)
    known_issues = baseline_data.get("knownIssues", [])
    baseline = {issue for issue in known_issues if isinstance(issue, str)} if isinstance(known_issues, list) else set()
    defect_owners = baseline_data.get("defectOwners", {})
    owned = {
        fingerprint
        for fingerprints in defect_owners.values()
        if isinstance(fingerprints, list)
        for fingerprint in fingerprints
        if isinstance(fingerprint, str)
    } if isinstance(defect_owners, dict) else set()
    if baseline != owned:
        unowned = sorted(baseline - owned)
        unknown = sorted(owned - baseline)
        raise RuntimeError(f"Baseline ownership mismatch; unowned={unowned}, unknown={unknown}")
    new_issues = current if strict else current - baseline
    stale_issues = set() if strict else baseline - current

    if issues:
        print("Policy and contract findings:")
        for issue in issues:
            state = "NEW" if issue.fingerprint in new_issues else "KNOWN"
            print(f"  [{state}] {issue.fingerprint}")
    else:
        print("Policy and contract findings: none")

    if stale_issues:
        print("Stale baseline entries must be removed:")
        for fingerprint in sorted(stale_issues):
            print(f"  [STALE] {fingerprint}")
    if new_issues:
        print("Validation failed because new or strict-mode findings exist.", file=sys.stderr)
    if stale_issues:
        print("Validation failed because resolved findings remain in the baseline.", file=sys.stderr)
    return not new_issues and not stale_issues


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overlay", type=Path, default=DEFAULT_OVERLAY)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS)
    parser.add_argument(
        "--tracked-source-list",
        type=Path,
        help="Newline-delimited git-tracked YAML paths supplied by the checkout environment",
    )
    parser.add_argument("--strict", action="store_true", help="Reject all findings instead of honoring the known-debt baseline")
    parser.add_argument("--skip-schema", action="store_true", help="Skip kubeconform; intended only for unit tests or offline diagnosis")
    parser.add_argument("--print-fingerprints", action="store_true", help="Print current finding fingerprints as JSON")
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    overlay = arguments.overlay.resolve()
    render = run(["kubectl", "kustomize", str(overlay)])
    if render.returncode != 0:
        print(render.stderr.strip() or "Kustomize rendering failed", file=sys.stderr)
        return 1

    contracts = load_json(arguments.contracts)
    try:
        tracked_names = (
            arguments.tracked_source_list.read_text(encoding="utf-8").splitlines()
            if arguments.tracked_source_list
            else None
        )
        issues = validate_rendered(render.stdout, contracts) + validate_tracked_sources(tracked_names)
        issues = sorted(set(issues))
    except (OSError, RuntimeError) as exc:
        print(f"Validation error: {exc}", file=sys.stderr)
        return 1
    if arguments.print_fingerprints:
        print(json.dumps([issue.fingerprint for issue in issues], indent=2))
        return 0

    try:
        if not arguments.skip_schema:
            validate_schema(render.stdout)
        valid = evaluate_baseline(issues, arguments.baseline, arguments.strict)
    except RuntimeError as exc:
        print(f"Validation error: {exc}", file=sys.stderr)
        return 1
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
