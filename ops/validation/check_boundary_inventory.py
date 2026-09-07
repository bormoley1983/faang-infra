#!/usr/bin/env python3
"""Prove proposed DEP-051 child Kustomizations partition the homelab render."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from validate_deployment import ROOT, split_documents


MONOLITH = ROOT / "k8s" / "overlays" / "homelab"
BOUNDARIES = (
    "runtime-foundation",
    "selected-dependencies",
    "retained-s3-main",
    "bootstrap",
    "workloads",
)


def render(path: Path) -> list[str]:
    result = subprocess.run(
        ["kubectl", "kustomize", str(path)], text=True, capture_output=True, check=False
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"Kustomize failed for {path}")
    return split_documents(result.stdout)


def identity(document: str) -> tuple[str, str, str, str]:
    def required(pattern: str, field: str) -> str:
        match = re.search(pattern, document, re.MULTILINE)
        if not match:
            raise RuntimeError(f"Rendered resource has no {field}")
        return match.group(1)

    api_version = required(r"^apiVersion:\s*([^\s#]+)", "apiVersion")
    kind = required(r"^kind:\s*([^\s#]+)", "kind")
    metadata = required(r"(?ms)^metadata:\s*\n((?:^[ \t]+.*\n?)*)", "metadata")
    name = required(r"(?m)^\s+name:\s*([^\s#]+)", "metadata.name")
    namespace_match = re.search(r"(?m)^\s+namespace:\s*([^\s#]+)", metadata)
    namespace = namespace_match.group(1) if namespace_match else "<cluster>"
    return api_version, kind, namespace, name


def inventory(path: Path) -> dict[tuple[str, str, str, str], str]:
    resources: dict[tuple[str, str, str, str], str] = {}
    for document in render(path):
        resource = identity(document)
        if resource in resources:
            raise RuntimeError(f"Duplicate resource within {path}: {'/'.join(resource)}")
        resources[resource] = document
    return resources


def check() -> tuple[int, dict[str, int]]:
    monolith = inventory(MONOLITH)
    children: dict[tuple[str, str, str, str], str] = {}
    counts: dict[str, int] = {}
    for name in BOUNDARIES:
        child = inventory(MONOLITH / "boundaries" / name)
        counts[name] = len(child)
        duplicate = sorted(set(children) & set(child))
        if duplicate:
            raise RuntimeError(f"Boundary overlap in {name}: {duplicate}")
        children.update(child)

    missing = sorted(set(monolith) - set(children))
    extra = sorted(set(children) - set(monolith))
    changed = sorted(resource for resource in monolith.keys() & children.keys() if monolith[resource] != children[resource])
    if missing or extra or changed:
        raise RuntimeError(
            f"Boundary inventory mismatch; missing={missing}, extra={extra}, changed={changed}"
        )
    return len(monolith), counts


def main() -> int:
    try:
        total, counts = check()
    except RuntimeError as exc:
        print(f"DEP-051 boundary gate failed: {exc}", file=sys.stderr)
        return 1
    print(f"DEP-051 boundary gate passed: {total} resources; " + ", ".join(f"{name}={count}" for name, count in counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
