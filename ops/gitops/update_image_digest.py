#!/usr/bin/env python3
"""Safely update one allowlisted service digest in a Kustomize overlay."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_KUSTOMIZATION = REPOSITORY_ROOT / "k8s" / "overlays" / "homelab" / "kustomization.yaml"
DEFAULT_INVENTORY = REPOSITORY_ROOT / "ops" / "images" / "service-images.json"
DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
NAME_LINE_PATTERN = re.compile(r"^(?P<indent>\s*)-\s+name:\s+(?P<name>\S+)\s*$")
DIGEST_LINE_PATTERN = re.compile(
    r"^(?P<indent>\s*)digest:\s*(?P<digest>\S+)(?P<suffix>\s*(?:#.*)?)$"
)
IMAGES_KEY_PATTERN = re.compile(r"^images:\s*(?P<value>.*)$")
TOP_LEVEL_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]+:\s*(?:.*)?$")


class DigestUpdateError(RuntimeError):
    """The requested update is invalid or cannot be applied safely."""


class RetryableDigestUpdateError(DigestUpdateError):
    """A transient condition prevented the update and a clean retry is safe."""


@dataclass(frozen=True)
class DigestUpdateResult:
    service: str
    previous_digest: str
    requested_digest: str
    changed: bool


def _validate_digest(value: str, label: str) -> None:
    if not DIGEST_PATTERN.fullmatch(value):
        raise DigestUpdateError(f"{label} must be lowercase sha256:<64 hexadecimal characters>")


def load_allowed_services(inventory_path: Path) -> set[str]:
    try:
        data = json.loads(inventory_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DigestUpdateError(f"Cannot read service inventory {inventory_path}: {error}") from error

    if not isinstance(data, list):
        raise DigestUpdateError(f"Service inventory {inventory_path} must contain a JSON array")

    services: list[str] = []
    for entry in data:
        if not isinstance(entry, dict) or not isinstance(entry.get("image"), str):
            raise DigestUpdateError(f"Service inventory {inventory_path} contains an invalid image entry")
        services.append(entry["image"])

    if len(services) != len(set(services)):
        raise DigestUpdateError(f"Service inventory {inventory_path} contains duplicate image names")
    if not services:
        raise DigestUpdateError(f"Service inventory {inventory_path} contains no image names")
    return set(services)


def _service_from_reference(reference: str) -> str:
    return reference.rsplit("/", 1)[-1]


def _images_block_bounds(lines: list[str]) -> tuple[int, int]:
    image_keys = [
        (index, match)
        for index, line in enumerate(lines)
        if (match := IMAGES_KEY_PATTERN.fullmatch(line.rstrip("\r\n")))
    ]
    if len(image_keys) != 1:
        raise DigestUpdateError(
            f"Expected exactly one top-level images block, found {len(image_keys)}"
        )

    image_key, image_match = image_keys[0]
    if image_match.group("value") and not image_match.group("value").startswith("#"):
        raise DigestUpdateError("The top-level images block must use block-list form")

    start = image_key + 1
    end = len(lines)
    for index in range(start, len(lines)):
        candidate = lines[index].rstrip("\r\n")
        if TOP_LEVEL_KEY_PATTERN.fullmatch(candidate):
            end = index
            break
    return start, end


def _replace_digest(
    content: str,
    service: str,
    requested_digest: str,
    expected_current_digest: str | None,
) -> tuple[str, DigestUpdateResult]:
    lines = content.splitlines(keepends=True)
    images_start, images_end = _images_block_bounds(lines)
    matches: list[tuple[int, int, re.Match[str]]] = []

    for index in range(images_start, images_end):
        line = lines[index]
        name_match = NAME_LINE_PATTERN.fullmatch(line.rstrip("\r\n"))
        if not name_match or _service_from_reference(name_match.group("name")) != service:
            continue

        name_indent = len(name_match.group("indent"))
        digest_matches: list[tuple[int, re.Match[str]]] = []
        for candidate_index in range(index + 1, images_end):
            candidate = lines[candidate_index].rstrip("\r\n")
            next_name = NAME_LINE_PATTERN.fullmatch(candidate)
            if next_name and len(next_name.group("indent")) == name_indent:
                break
            digest_match = DIGEST_LINE_PATTERN.fullmatch(candidate)
            if digest_match:
                digest_matches.append((candidate_index, digest_match))

        if len(digest_matches) != 1:
            raise DigestUpdateError(
                f"Image mapping for '{service}' must contain exactly one digest field"
            )
        digest_index, digest_match = digest_matches[0]
        matches.append((index, digest_index, digest_match))

    if len(matches) != 1:
        raise DigestUpdateError(
            f"Expected exactly one image mapping for '{service}', found {len(matches)}"
        )

    _, digest_index, digest_match = matches[0]
    previous_digest = digest_match.group("digest")
    _validate_digest(previous_digest, f"Current digest for '{service}'")
    if expected_current_digest is not None and previous_digest != expected_current_digest:
        raise RetryableDigestUpdateError(
            f"Current digest for '{service}' changed from the expected value; retry from latest Git state"
        )

    if previous_digest == requested_digest:
        return content, DigestUpdateResult(service, previous_digest, requested_digest, False)

    original_line = lines[digest_index]
    newline = "\r\n" if original_line.endswith("\r\n") else "\n" if original_line.endswith("\n") else ""
    lines[digest_index] = (
        f"{digest_match.group('indent')}digest: {requested_digest}"
        f"{digest_match.group('suffix')}{newline}"
    )
    return "".join(lines), DigestUpdateResult(service, previous_digest, requested_digest, True)


class _WorkspaceLock:
    def __init__(self, target_path: Path) -> None:
        self.path = target_path.with_name(f"{target_path.name}.digest-update.lock")
        self._acquired = False

    def __enter__(self) -> None:
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as error:
            raise RetryableDigestUpdateError(
                f"Another digest update owns {self.path}; retry after it completes"
            ) from error
        try:
            os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
        finally:
            os.close(descriptor)
        self._acquired = True

    def __exit__(self, _error_type: object, _error: object, _traceback: object) -> None:
        if self._acquired:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass


def _atomic_write(path: Path, content: str) -> None:
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
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
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def update_image_digest(
    kustomization_path: Path,
    inventory_path: Path,
    service: str,
    requested_digest: str,
    expected_current_digest: str | None = None,
) -> DigestUpdateResult:
    _validate_digest(requested_digest, "Requested digest")
    if expected_current_digest is not None:
        _validate_digest(expected_current_digest, "Expected current digest")

    allowed_services = load_allowed_services(inventory_path)
    if service not in allowed_services:
        raise DigestUpdateError(f"Service '{service}' is not present in {inventory_path}")

    with _WorkspaceLock(kustomization_path):
        try:
            original_content = kustomization_path.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise DigestUpdateError(f"Cannot read {kustomization_path}: {error}") from error

        updated_content, result = _replace_digest(
            original_content,
            service,
            requested_digest,
            expected_current_digest,
        )
        if result.changed:
            try:
                _atomic_write(kustomization_path, updated_content)
            except OSError as error:
                raise RetryableDigestUpdateError(
                    f"Cannot atomically update {kustomization_path}: {error}"
                ) from error
        return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Update exactly one allowlisted service digest in the homelab Kustomize overlay."
    )
    parser.add_argument("service", help="Allowlisted image name, for example faang-account-service")
    parser.add_argument("digest", help="Published immutable digest in sha256:<64 lowercase hex> form")
    parser.add_argument("--kustomization", type=Path, default=DEFAULT_KUSTOMIZATION)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument(
        "--expected-current-digest",
        help="Fail retryably if the service no longer has this digest",
    )
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    options = _build_parser().parse_args(arguments)
    try:
        result = update_image_digest(
            options.kustomization,
            options.inventory,
            options.service,
            options.digest,
            options.expected_current_digest,
        )
    except RetryableDigestUpdateError as error:
        print(f"RETRYABLE: {error}", file=sys.stderr)
        return 75
    except DigestUpdateError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    action = "updated" if result.changed else "unchanged"
    print(
        f"{action}: {result.service} {result.previous_digest} -> {result.requested_digest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
