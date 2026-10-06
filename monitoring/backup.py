#!/usr/bin/env python3
"""Create and verify guarded backups of the external monitoring data volumes."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import uuid

import install


BACKUP_CONFIRMATION = "FAANG-MONITORING-BACKUP"
VERIFY_CONFIRMATION = "FAANG-MONITORING-RESTORE-VERIFY"
VOLUMES = {
    "prometheus": "monitoring_prometheus_data",
    "alertmanager": "monitoring_alertmanager_data",
    "grafana": "monitoring_grafana_data",
}


class BackupError(RuntimeError):
    """The requested backup operation is unsafe or invalid."""


def run(command: list[str], *, environment: dict[str, str] | None = None,
        stdout: object | None = None, capture: bool = False) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=install.ROOT,
        env=environment,
        check=False,
        text=stdout is None,
        stdout=subprocess.PIPE if capture else stdout,
        stderr=subprocess.PIPE if capture else None,
    )
    if result.returncode != 0:
        raise BackupError(f"command failed with exit code {result.returncode}: {command[0]} {command[1]}")
    return result


def docker_environment(config: Path) -> dict[str, str]:
    settings = install.load_config(config.resolve())
    environment = os.environ.copy()
    environment.update(settings)
    return environment


def compose(*arguments: str) -> list[str]:
    return ["docker", "compose", "-f", str(install.COMPOSE_FILE), *arguments]


def helper_command(mounts: list[str], script: str) -> list[str]:
    command = [
        "docker", "run", "--rm", "--network", "none", "--read-only",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
        "--user", "0:0",
    ]
    command.extend(mounts)
    command.extend(["--entrypoint", "/bin/sh", install.GRAFANA_IMAGE, "-ec", script])
    return command


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_archive_members(path: Path) -> None:
    required = {f"{name}/" for name in VOLUMES}
    observed: set[str] = set()
    try:
        with tarfile.open(path, "r:gz") as archive:
            for member in archive.getmembers():
                candidate = PurePosixPath(member.name)
                if candidate.is_absolute() or ".." in candidate.parts:
                    raise BackupError("backup contains an unsafe archive path")
                for prefix in required:
                    if member.name == prefix.rstrip("/") or member.name.startswith(prefix):
                        observed.add(prefix)
    except (OSError, tarfile.TarError) as error:
        raise BackupError("backup is not a readable gzip tar archive") from error
    missing = required - observed
    if missing:
        raise BackupError(f"backup is missing volume trees: {', '.join(sorted(missing))}")


def create_backup(config: Path, output_directory: Path, confirmation: str) -> Path:
    if confirmation != BACKUP_CONFIRMATION:
        raise BackupError(f"backup requires --confirm {BACKUP_CONFIRMATION}")
    environment = docker_environment(config)
    output_directory = output_directory.expanduser().resolve()
    output_directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    running = run(compose("ps", "--status", "running", "-q"), environment=environment, capture=True)
    if len([line for line in running.stdout.splitlines() if line.strip()]) != 3:
        raise BackupError("all three monitoring services must be running before a consistent backup")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive_path = output_directory / f"faang-monitoring-{timestamp}.tar.gz"
    if archive_path.exists():
        raise BackupError("refusing to overwrite an existing backup")

    stopped = False
    try:
        run(compose("stop"), environment=environment)
        stopped = True
        mounts = sum(([
                "--mount", f"type=volume,src={volume},dst=/source/{name},readonly"
            ] for name, volume in VOLUMES.items()), [])
        command = helper_command(
            mounts,
            "tar -czf - -C /source prometheus alertmanager grafana",
        )
        descriptor = os.open(archive_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as output:
                run(command, stdout=output)
        except Exception:
            archive_path.unlink(missing_ok=True)
            raise
    finally:
        if stopped:
            run(compose("up", "-d"), environment=environment)

    validate_archive_members(archive_path)
    digest = sha256(archive_path)
    checksum_path = archive_path.with_suffix(archive_path.suffix + ".sha256")
    checksum_path.write_text(f"{digest}  {archive_path.name}\n", encoding="ascii")
    metadata = {
        "archive": archive_path.name,
        "createdUtc": timestamp,
        "sha256": digest,
        "volumeTrees": sorted(VOLUMES),
    }
    archive_path.with_suffix(archive_path.suffix + ".json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Monitoring backup created: {archive_path}")
    print("The archive contains sensitive operational data; store it encrypted off-host.")
    return archive_path


def verify_backup(archive: Path, confirmation: str) -> None:
    if confirmation != VERIFY_CONFIRMATION:
        raise BackupError(f"restore verification requires --confirm {VERIFY_CONFIRMATION}")
    archive = archive.expanduser().resolve()
    if not archive.is_file():
        raise BackupError("backup archive does not exist")
    validate_archive_members(archive)
    checksum_path = archive.with_suffix(archive.suffix + ".sha256")
    if not checksum_path.is_file():
        raise BackupError("backup checksum sidecar does not exist")
    expected = checksum_path.read_text(encoding="ascii").split()[0].lower()
    if expected != sha256(archive):
        raise BackupError("backup checksum verification failed")

    suffix = uuid.uuid4().hex[:12]
    temporary = {name: f"monitoring_restore_verify_{name}_{suffix}" for name in VOLUMES}
    created: list[str] = []
    try:
        for volume in temporary.values():
            run(["docker", "volume", "create", "--label", "faang.io/restore-verification=true", volume])
            created.append(volume)
        mounts = ["--mount", f"type=bind,src={archive},dst=/backup/archive.tar.gz,readonly"]
        for name, volume in temporary.items():
            mounts.extend(["--mount", f"type=volume,src={volume},dst=/restore/{name}"])
        run(helper_command(
            mounts,
            "tar -xzf /backup/archive.tar.gz -C /restore "
            "prometheus alertmanager grafana; "
            "test -d /restore/prometheus/wal; test -f /restore/grafana/grafana.db",
        ))
    finally:
        for volume in reversed(created):
            run(["docker", "volume", "rm", volume])
    print("Monitoring backup checksum and isolated restore verification passed.")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    backup = subparsers.add_parser("backup")
    backup.add_argument("--config", type=Path, default=install.DEFAULT_CONFIG)
    backup.add_argument("--output-directory", type=Path, required=True)
    backup.add_argument("--confirm", default="")
    verify = subparsers.add_parser("verify")
    verify.add_argument("--archive", type=Path, required=True)
    verify.add_argument("--confirm", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    options = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if options.action == "backup":
            create_backup(options.config, options.output_directory, options.confirm)
        else:
            verify_backup(options.archive, options.confirm)
    except (BackupError, install.ConfigurationError) as error:
        print(f"monitoring backup refused: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
