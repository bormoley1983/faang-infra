#!/usr/bin/env python3
"""Create or reuse the single open GitOps promotion pull request."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Sequence


class PullRequestError(RuntimeError):
    """The pull-request request was invalid or failed safely."""


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
            "User-Agent": "faang-gitops-proposal",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise PullRequestError(f"Git provider returned HTTP {error.code}") from error
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise PullRequestError(f"Git provider request failed: {type(error).__name__}") from error


def create_or_reuse_pull_request(
    repository: str,
    owner: str,
    token: str,
    head: str = "gitops/promotions",
    base: str = "dev-local",
    api_url: str = "https://api.github.com",
) -> tuple[str, bool]:
    if repository.count("/") != 1 or repository.startswith("/") or repository.endswith("/"):
        raise PullRequestError("Repository must use owner/name form")
    if not owner or any(character.isspace() for character in owner):
        raise PullRequestError("Repository owner is invalid")
    if not token:
        raise PullRequestError("Git provider token is missing")

    query = urllib.parse.urlencode(
        {"state": "open", "head": f"{owner}:{head}", "base": base}
    )
    endpoint = f"{api_url.rstrip('/')}/repos/{repository}/pulls"
    existing = _request_json(f"{endpoint}?{query}", token)
    if not isinstance(existing, list):
        raise PullRequestError("Git provider returned an invalid pull-request list")
    if len(existing) > 1:
        raise PullRequestError("More than one open GitOps promotion pull request exists")
    if existing:
        html_url = existing[0].get("html_url")
        if not isinstance(html_url, str) or not html_url.startswith("https://"):
            raise PullRequestError("Existing pull request has no valid URL")
        return html_url, False

    created = _request_json(
        endpoint,
        token,
        method="POST",
        payload={
            "title": "chore(gitops): promote verified service digests",
            "head": head,
            "base": base,
            "body": (
                "Automated proposal containing immutable service digests from completed "
                "trusted delivery jobs. Review every commit and desired-state diff before merge."
            ),
        },
    )
    if not isinstance(created, dict):
        raise PullRequestError("Git provider returned an invalid pull-request response")
    html_url = created.get("html_url")
    if not isinstance(html_url, str) or not html_url.startswith("https://"):
        raise PullRequestError("Created pull request has no valid URL")
    return html_url, True


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--head", default="gitops/promotions")
    parser.add_argument("--base", default="dev-local")
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    options = _build_parser().parse_args(arguments)
    try:
        url, created = create_or_reuse_pull_request(
            repository=options.repository,
            owner=options.owner,
            token=os.environ.get("GITOPS_TOKEN", ""),
            head=options.head,
            base=options.base,
        )
    except PullRequestError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(f"{'created' if created else 'reused'}: {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
