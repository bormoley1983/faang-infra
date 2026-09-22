#!/usr/bin/env python3
"""Read-only status, validation, and planning for dependency profiles.

Stateful deployment and cutover commands are intentionally absent until their
production manifests, migration, recovery, and rollback contracts are accepted.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = ROOT / "ops/validation/validate_dependency_selection.py"
SPEC = importlib.util.spec_from_file_location("dependency_selection_validator", VALIDATOR_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load validator {VALIDATOR_PATH}")
VALIDATOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VALIDATOR
SPEC.loader.exec_module(VALIDATOR)

DEFAULT_TOPOLOGY = ROOT / "config/homelab.local.json"
KUSTOMIZATION = ROOT / "k8s/overlays/homelab/kustomization.yaml"
SELECTION_OVERLAY = ROOT / "k8s/overlays/homelab/boundaries/selected-dependencies"
CONFIGMAP = ROOT / "k8s/overlays/homelab/boundaries/runtime-foundation/configmap.yaml"
READINESS_PATH = Path(__file__).with_name("profile-readiness.json")


class ProfileError(ValueError):
    """The requested profile operation is invalid or not ready."""


def load_readiness() -> dict[str, dict[str, dict[str, Any]]]:
    document = json.loads(READINESS_PATH.read_text(encoding="utf-8"))
    contracts = VALIDATOR.load_json(VALIDATOR.DEFAULT_CONTRACT)["dependencies"]
    if set(document) != set(contracts):
        raise ProfileError("profile readiness inventory does not match dependency contracts")
    for dependency, modes in document.items():
        if set(modes) != {"internal", "external"}:
            raise ProfileError(f"readiness for {dependency} must define internal and external")
        for mode, value in modes.items():
            if not isinstance(value, dict) or not isinstance(value.get("ready"), bool):
                raise ProfileError(f"readiness for {dependency}/{mode} is invalid")
            if not isinstance(value.get("state"), str) or not value["state"]:
                raise ProfileError(f"state for {dependency}/{mode} is invalid")
    return document


def validate_current(topology: Path, allow_documentation_addresses: bool = False) -> dict[str, str]:
    return VALIDATOR.validate(
        KUSTOMIZATION,
        topology,
        CONFIGMAP,
        selection_overlays=(SELECTION_OVERLAY,),
        allow_documentation_addresses=allow_documentation_addresses,
    )


def status_data(topology: Path, allow_documentation_addresses: bool = False) -> dict[str, Any]:
    selected = validate_current(topology, allow_documentation_addresses)
    readiness = load_readiness()
    return {
        "mutation": "none",
        "dependencies": {
            name: {
                "selectedMode": mode,
                "ready": readiness[name][mode]["ready"],
                "state": readiness[name][mode]["state"],
            }
            for name, mode in sorted(selected.items())
        },
    }


def plan_data(
    topology: Path,
    dependency: str,
    mode: str,
    allow_documentation_addresses: bool = False,
) -> dict[str, Any]:
    status = status_data(topology, allow_documentation_addresses)
    dependencies = status["dependencies"]
    if dependency not in dependencies:
        raise ProfileError(f"unknown dependency {dependency}")
    if mode not in {"internal", "external"}:
        raise ProfileError("mode must be internal or external")
    readiness = load_readiness()[dependency][mode]
    current = dependencies[dependency]["selectedMode"]
    return {
        "mutation": "none",
        "dependency": dependency,
        "currentMode": current,
        "requestedMode": mode,
        "changeRequired": current != mode,
        "deployable": readiness["ready"],
        "state": readiness["state"],
        "nextAction": (
            "no-change"
            if current == mode
            else "prepare-reviewed-profile-change"
            if readiness["ready"]
            else "complete-production-profile-acceptance"
        ),
    }


def print_document(document: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(document, indent=2, sort_keys=True))
        return
    if "dependencies" in document:
        for name, value in document["dependencies"].items():
            print(f"{name}: mode={value['selectedMode']} ready={str(value['ready']).lower()} state={value['state']}")
    else:
        for key in ("dependency", "currentMode", "requestedMode", "changeRequired", "deployable", "state", "nextAction"):
            print(f"{key}: {document[key]}")
    print("Mutation: none. Private topology and credentials: suppressed.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_TOPOLOGY)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--allow-documentation-addresses", action="store_true", help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    subparsers.add_parser("validate")
    plan = subparsers.add_parser("plan")
    plan.add_argument("--dependency", required=True)
    plan.add_argument("--mode", required=True, choices=("internal", "external"))
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    options = build_parser().parse_args(arguments)
    try:
        if options.command in {"status", "validate"}:
            document = status_data(options.config.resolve(), options.allow_documentation_addresses)
        else:
            document = plan_data(
                options.config.resolve(),
                options.dependency,
                options.mode,
                options.allow_documentation_addresses,
            )
    except (ProfileError, VALIDATOR.SelectionError, OSError, json.JSONDecodeError) as error:
        print(f"profile operation refused: {error}", file=sys.stderr)
        return 2
    print_document(document, options.json)
    if options.command == "plan" and not document["deployable"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
