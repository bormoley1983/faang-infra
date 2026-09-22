#!/usr/bin/env python3
"""Guard the public-workload revision and private environment promotion PR.

The update command changes exactly one pinned remote Kustomize reference. The
validate-render command checks only bounded workload facts and never emits the
rendered private manifest. The ensure-pr command creates or reuses the single
private environment promotion pull request.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Sequence


PUBLIC_REPOSITORY = "https://github.com/bormoley1983/faang-infra.git"
PUBLIC_WORKLOAD_PATH = "k8s/overlays/homelab/boundaries/workloads"
PRIVATE_REPOSITORY = "bormoley1983/faang-infra-env-homelab"
PRIVATE_OWNER = "bormoley1983"
PROPOSAL_BRANCH = "env/promotions"
PRIVATE_BASE_BRANCH = "main"
REVISION_PATTERN = re.compile(r"[0-9a-f]{40}")
SERVICE_NAMES = (
    "faang-account-service",
    "faang-achievement-service",
    "faang-analytics-service",
    "faang-notification-service",
    "faang-payment-service",
    "faang-post-service",
    "faang-project-service",
    "faang-url-shortener-service",
    "faang-user-service",
)
REMOTE_LINE_PATTERN = re.compile(
    r"^(?P<prefix>\s*-\s+)"
    + re.escape(PUBLIC_REPOSITORY)
    + r"//"
    + re.escape(PUBLIC_WORKLOAD_PATH)
    + r"\?ref=(?P<revision>dev-local|[0-9a-f]{40})"
    + r"(?P<suffix>\s*(?:#.*)?)(?P<newline>\r?\n|$)$"
)


class EnvironmentPromotionError(RuntimeError):
    """The requested environment promotion is ambiguous or unsafe."""


@dataclass(frozen=True)
class RevisionUpdateResult:
    previous_revision: str
    requested_revision: str
    changed: bool


def _validate_revision(revision: str) -> None:
    if not REVISION_PATTERN.fullmatch(revision):
        raise EnvironmentPromotionError(
            "revision must be exactly 40 lowercase hexadecimal characters"
        )


def _atomic_write(path: Path, content: str) -> None:
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_path, stat.S_IMODE(path.stat().st_mode))
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def update_environment_revision(
    kustomization: Path,
    public_repository: str,
    revision: str,
) -> RevisionUpdateResult:
    if public_repository != PUBLIC_REPOSITORY:
        raise EnvironmentPromotionError("public repository is not allowlisted")
    _validate_revision(revision)
    if not kustomization.is_file():
        raise EnvironmentPromotionError("private workload kustomization does not exist")

    try:
        original = kustomization.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise EnvironmentPromotionError("cannot read private workload kustomization") from error

    lines = original.splitlines(keepends=True)
    matches = [
        (index, match)
        for index, line in enumerate(lines)
        if (match := REMOTE_LINE_PATTERN.fullmatch(line)) is not None
    ]
    if len(matches) != 1:
        raise EnvironmentPromotionError(
            "expected exactly one allowlisted public workload reference, "
            f"found {len(matches)}"
        )

    index, match = matches[0]
    previous = match.group("revision")
    if previous == revision:
        return RevisionUpdateResult(previous, revision, False)

    lines[index] = (
        f"{match.group('prefix')}{PUBLIC_REPOSITORY}//{PUBLIC_WORKLOAD_PATH}"
        f"?ref={revision}{match.group('suffix')}{match.group('newline')}"
    )
    try:
        _atomic_write(kustomization, "".join(lines))
    except OSError as error:
        raise EnvironmentPromotionError("cannot update private workload kustomization") from error
    return RevisionUpdateResult(previous, revision, True)


def _documents(rendered: str) -> list[str]:
    return [
        document.strip() + "\n"
        for document in re.split(r"(?m)^---\s*$", rendered)
        if document.strip()
    ]


def _identity(document: str) -> tuple[str, str]:
    kind = re.search(r"(?m)^kind:\s*([^\s#]+)", document)
    metadata = re.search(
        r"(?ms)^metadata:\s*\n(?P<body>(?:^[ \t]+.*\n?)*)", document
    )
    name = (
        re.search(r"(?m)^\s+name:\s*([^\s#]+)", metadata.group("body"))
        if metadata
        else None
    )
    return (
        kind.group(1) if kind else "Unknown",
        name.group(1) if name else "unknown",
    )


def validate_rendered_workloads(rendered_path: Path) -> None:
    try:
        rendered = rendered_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise EnvironmentPromotionError("cannot read rendered workloads") from error

    resources = {_identity(document): document for document in _documents(rendered)}
    secret_names = sorted(name for kind, name in resources if kind == "Secret")
    if secret_names:
        raise EnvironmentPromotionError("workload render must not contain Secret resources")
    if re.search(r"(?m)^\s*image:\s*\S+:latest\s*$", rendered):
        raise EnvironmentPromotionError("workload render contains a mutable latest image")

    for service in SERVICE_NAMES:
        deployment = resources.get(("Deployment", service))
        if deployment is None:
            raise EnvironmentPromotionError(f"missing Deployment/{service}")
        image_pattern = re.compile(
            rf"(?m)^\s*image:\s*docker-registry:5000/{re.escape(service)}"
            r"@sha256:[0-9a-f]{64}\s*$"
        )
        if not image_pattern.search(deployment):
            raise EnvironmentPromotionError(
                f"Deployment/{service} does not use its immutable allowlisted image"
            )
        if not re.search(
            r"(?m)^\s*- name:\s*MANAGEMENT_SERVER_PORT\s*$\n"
            r"\s+value:\s*[\"']?9090[\"']?\s*$",
            deployment,
        ):
            raise EnvironmentPromotionError(
                f"Deployment/{service} has no management port contract"
            )
        if not re.search(
            r"(?ms)^\s*-\s+containerPort:\s*9090\s*$.*?^\s+name:\s*metrics\s*$"
            r"|^\s*-\s+name:\s*metrics\s*$.*?^\s+containerPort:\s*9090\s*$",
            deployment,
        ):
            raise EnvironmentPromotionError(
                f"Deployment/{service} has no named metrics container port"
            )

        service_document = resources.get(("Service", service))
        if service_document is None:
            raise EnvironmentPromotionError(f"missing Service/{service}")
        if not re.search(
            r"(?m)^\s+metrics\.faang\.io/scrape:\s*[\"']?true[\"']?\s*$",
            service_document,
        ):
            raise EnvironmentPromotionError(
                f"Service/{service} is not explicitly enabled for metrics discovery"
            )
        if not re.search(
            r"(?ms)^\s*-\s+name:\s*http\s*$.*?^\s+port:\s*80\s*$",
            service_document,
        ):
            raise EnvironmentPromotionError(
                f"Service/{service} has no named application service port"
            )
        if not re.search(
            r"(?ms)^\s*-\s+name:\s*metrics\s*$.*?^\s+port:\s*9090\s*$"
            r".*?^\s+targetPort:\s*metrics\s*$",
            service_document,
        ):
            raise EnvironmentPromotionError(
                f"Service/{service} has no named metrics service port"
            )

    policy = resources.get(("NetworkPolicy", "faang-application-metrics"))
    if policy is None:
        raise EnvironmentPromotionError(
            "missing NetworkPolicy/faang-application-metrics"
        )
    if "kubernetes.io/metadata.name: monitoring" not in policy:
        raise EnvironmentPromotionError(
            "metrics NetworkPolicy does not select the monitoring namespace"
        )


def _request_json(
    url: str,
    token: str,
    method: str = "GET",
    payload: dict[str, str] | None = None,
) -> Any:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "faang-environment-promotion",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise EnvironmentPromotionError(
            f"Git provider returned HTTP {error.code}"
        ) from error
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise EnvironmentPromotionError(
            f"Git provider request failed: {type(error).__name__}"
        ) from error


def create_or_reuse_environment_pull_request(
    repository: str,
    owner: str,
    token: str,
    head: str,
    base: str,
    api_url: str = "https://api.github.com",
) -> tuple[str, bool]:
    if repository != PRIVATE_REPOSITORY:
        raise EnvironmentPromotionError("private repository is not allowlisted")
    if owner != PRIVATE_OWNER or head != PROPOSAL_BRANCH or base != PRIVATE_BASE_BRANCH:
        raise EnvironmentPromotionError("private pull-request boundary is not allowlisted")
    if not token:
        raise EnvironmentPromotionError("environment proposer token is missing")

    endpoint = f"{api_url.rstrip('/')}/repos/{repository}/pulls"
    query = urllib.parse.urlencode(
        {"state": "open", "head": f"{owner}:{head}", "base": base}
    )
    existing = _request_json(f"{endpoint}?{query}", token)
    if not isinstance(existing, list):
        raise EnvironmentPromotionError("Git provider returned an invalid PR list")
    if len(existing) > 1:
        raise EnvironmentPromotionError("more than one environment promotion PR exists")
    if existing:
        url = existing[0].get("html_url")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise EnvironmentPromotionError("existing promotion PR has no valid URL")
        return url, False

    created = _request_json(
        endpoint,
        token,
        method="POST",
        payload={
            "title": "chore(gitops): promote public workload revision",
            "head": head,
            "base": base,
            "body": (
                "Automated proposal pinning the reviewed public workload boundary "
                "to an exact faang-infra revision. Review the one-file diff and "
                "rendered evidence before merge; deployment remains a manual Argo sync."
            ),
        },
    )
    if not isinstance(created, dict):
        raise EnvironmentPromotionError("Git provider returned an invalid PR response")
    url = created.get("html_url")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise EnvironmentPromotionError("created promotion PR has no valid URL")
    return url, True


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    update = subparsers.add_parser("update")
    update.add_argument("--kustomization", type=Path, required=True)
    update.add_argument("--public-repository", required=True)
    update.add_argument("--revision", required=True)

    validate = subparsers.add_parser("validate-render")
    validate.add_argument("--rendered", type=Path, required=True)

    ensure_pr = subparsers.add_parser("ensure-pr")
    ensure_pr.add_argument("--repository", required=True)
    ensure_pr.add_argument("--owner", required=True)
    ensure_pr.add_argument("--head", required=True)
    ensure_pr.add_argument("--base", required=True)
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    options = _parser().parse_args(arguments)
    try:
        if options.command == "update":
            result = update_environment_revision(
                options.kustomization,
                options.public_repository,
                options.revision,
            )
            action = "updated" if result.changed else "unchanged"
            print(
                f"{action}: public workload revision "
                f"{result.previous_revision} -> {result.requested_revision}"
            )
        elif options.command == "validate-render":
            validate_rendered_workloads(options.rendered)
            print("validated: 9 workload images, metrics contract, and NetworkPolicy")
        else:
            url, created = create_or_reuse_environment_pull_request(
                repository=options.repository,
                owner=options.owner,
                token=os.environ.get("ENVIRONMENT_TOKEN", ""),
                head=options.head,
                base=options.base,
            )
            print(f"{'created' if created else 'reused'}: {url}")
    except EnvironmentPromotionError as error:
        print(f"ERROR: {error}", file=os.sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
