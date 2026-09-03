#!/usr/bin/env python3
"""Validate one-of-two dependency selections and separate topology policy."""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = Path(__file__).with_name("dependency-contracts.json")
PROFILE_PATTERN = re.compile(
    r"(?:^|/)components/dependencies/([^/]+)/(internal|external)/?$"
)
DOCUMENTATION_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "2001:db8::/32")
)


class SelectionError(ValueError):
    """The selected profiles or their topology contract are invalid."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SelectionError(f"Unable to read JSON contract {path.name}") from error
    if not isinstance(value, dict):
        raise SelectionError(f"JSON contract {path.name} must contain an object")
    return value


def section_items(path: Path, section: str) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise SelectionError(f"Unable to read {path.name}") from error

    items: list[str] = []
    inside = False
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[:1].isspace():
            inside = line.strip() == f"{section}:"
            continue
        if inside:
            match = re.match(r"^\s+-\s+([^#]+?)\s*$", line)
            if match:
                items.append(match.group(1).strip("'\""))
    return items


def selected_profiles(kustomization: Path, expected: set[str]) -> dict[str, str]:
    selected: dict[str, list[str]] = {name: [] for name in expected}
    for item in section_items(kustomization, "resources"):
        resolved = (kustomization.parent / item).resolve()
        try:
            relative = resolved.relative_to(ROOT.resolve()).as_posix()
        except (TypeError, ValueError) as error:
            raise SelectionError("Selection resource escapes the repository") from error
        match = PROFILE_PATTERN.search(relative)
        if not match:
            continue
        dependency, mode = match.groups()
        if dependency not in expected:
            raise SelectionError(f"Unknown dependency profile {dependency}")
        selected[dependency].append(mode)

    invalid = {
        name: modes for name, modes in selected.items() if len(modes) != 1
    }
    if invalid:
        details = ", ".join(
            f"{name}={modes or ['missing']}" for name, modes in sorted(invalid.items())
        )
        raise SelectionError(f"Each dependency requires exactly one profile: {details}")
    return {name: modes[0] for name, modes in selected.items()}


def configmap_data(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    inside = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line[:1].isspace():
            inside = line.strip() == "data:"
            continue
        if inside:
            match = re.match(r"^\s{2}([A-Z][A-Z0-9_]*):\s*[\"']?(.+?)[\"']?\s*$", line)
            if match:
                values[match.group(1)] = match.group(2).strip("'\"")
    return values


def validate_topology(
    selected: dict[str, str],
    topology: dict[str, Any],
    contracts: dict[str, Any],
    *,
    allow_documentation_addresses: bool = False,
) -> None:
    entries = topology.get("dependencies")
    if not isinstance(entries, dict) or set(entries) != set(contracts):
        raise SelectionError("Topology must define exactly the contracted dependencies")

    for name, contract_value in contracts.items():
        contract = contract_value if isinstance(contract_value, dict) else {}
        entry = entries.get(name)
        if not isinstance(entry, dict):
            raise SelectionError(f"dependencies.{name} must be an object")
        mode = entry.get("mode")
        if mode != selected[name]:
            raise SelectionError(f"dependencies.{name}.mode does not match the selected profile")

        tls = entry.get("tls")
        tls_mode = tls.get("mode") if isinstance(tls, dict) else None
        if tls_mode not in contract.get("tlsModes", []):
            raise SelectionError(f"dependencies.{name}.tls.mode is missing or unsupported")

        credentials = entry.get("credentials")
        credential_mode = credentials.get("mode") if isinstance(credentials, dict) else None
        if credential_mode not in contract.get("credentialModes", []):
            raise SelectionError(f"dependencies.{name}.credentials.mode is missing or unsupported")
        if credential_mode == "secret":
            if credentials.get("secretName") != "faang-secrets":
                raise SelectionError(f"dependencies.{name}.credentials.secretName is invalid")
            keys = credentials.get("keys")
            if not isinstance(keys, list) or set(keys) != set(contract.get("requiredSecretKeys", [])):
                raise SelectionError(f"dependencies.{name}.credentials.keys do not match the contract")
        elif set(credentials) != {"mode"}:
            raise SelectionError(f"dependencies.{name}.credentials none mode has unexpected fields")

        if mode == "internal":
            if "address" in entry or "port" in entry:
                raise SelectionError(f"dependencies.{name} internal mode must not contain physical topology")
            continue

        address = entry.get("address")
        port = entry.get("port")
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError as error:
            raise SelectionError(f"dependencies.{name}.address must be an IP address") from error
        if parsed.is_unspecified or parsed.is_loopback or parsed.is_multicast:
            raise SelectionError(f"dependencies.{name}.address is not an external endpoint")
        is_documentation_address = any(parsed in network for network in DOCUMENTATION_NETWORKS)
        if is_documentation_address and not allow_documentation_addresses:
            raise SelectionError(f"dependencies.{name}.address is documentation-only")
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise SelectionError(f"dependencies.{name}.port must be between 1 and 65535")


def validate_configmap(path: Path, contracts: dict[str, Any]) -> None:
    actual = configmap_data(path)
    for name, contract_value in contracts.items():
        contract = contract_value if isinstance(contract_value, dict) else {}
        expected = contract.get("config", {})
        for key, value in expected.items():
            if actual.get(key) != str(value):
                raise SelectionError(f"{path.name} does not map {name} endpoint key {key}")


def validate(
    kustomization: Path,
    topology_path: Path,
    configmap_path: Path,
    contract_path: Path = DEFAULT_CONTRACT,
    *,
    allow_documentation_addresses: bool = False,
) -> dict[str, str]:
    contract_document = load_json(contract_path)
    contracts = contract_document.get("dependencies")
    if not isinstance(contracts, dict) or not contracts:
        raise SelectionError("Dependency contract has no dependencies")
    selected = selected_profiles(kustomization, set(contracts))
    validate_topology(
        selected,
        load_json(topology_path),
        contracts,
        allow_documentation_addresses=allow_documentation_addresses,
    )
    validate_configmap(configmap_path, contracts)
    return selected


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kustomization", type=Path, required=True)
    parser.add_argument("--topology", type=Path, required=True)
    parser.add_argument("--configmap", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--allow-documentation-addresses", action="store_true")
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    options = build_parser().parse_args(arguments)
    try:
        selected = validate(
            options.kustomization,
            options.topology,
            options.configmap,
            options.contract,
            allow_documentation_addresses=options.allow_documentation_addresses,
        )
    except SelectionError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    summary = ", ".join(f"{name}={mode}" for name, mode in sorted(selected.items()))
    print(f"Dependency selection is valid: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
