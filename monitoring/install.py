#!/usr/bin/env python3
"""Validate or install the external LXC monitoring stack.

The script never creates credentials and never prints private configuration.
Use an ignored local JSON file and a separately protected password file.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT.parent / "config" / "monitoring.local.json"
COMPOSE_FILE = ROOT / "compose.yaml"
CONFIRMATION = "FAANG-MONITORING-INSTALL"
PROMETHEUS_IMAGE = "prom/prometheus:v3.13.3@sha256:6976aa8a60fec930796ce5772b8d12da7a318a5daa8d40d69c5c7819a05eeed7"
ALERTMANAGER_IMAGE = "prom/alertmanager:v0.34.1@sha256:e9733bafb1bdef9b00e25a21f8f99dc26a22224bf16641ad754d1649f4c3357a"
ALLOWED_KEYS = {
    "bindAddress",
    "grafanaAdminUser",
    "grafanaAdminPasswordFile",
    "prometheusRetentionTime",
    "prometheusRetentionSize",
}
DOCUMENTATION_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "2001:db8::/32")
)


class ConfigurationError(ValueError):
    """The private monitoring input is missing or unsafe."""


def _required_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{key} must be a non-empty string")
    return value.strip()


def load_config(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise ConfigurationError(
            "missing private monitoring config; copy config/monitoring.example.json "
            "to config/monitoring.local.json and set private values"
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigurationError("monitoring config is not valid JSON") from error
    if not isinstance(raw, dict):
        raise ConfigurationError("monitoring config must be a JSON object")
    unknown = set(raw) - ALLOWED_KEYS
    if unknown:
        raise ConfigurationError(f"unknown monitoring config keys: {', '.join(sorted(unknown))}")

    bind_text = _required_string(raw, "bindAddress")
    try:
        bind_address = ipaddress.ip_address(bind_text)
    except ValueError as error:
        raise ConfigurationError("bindAddress must be one explicit IPv4 or IPv6 address") from error
    if bind_address.is_unspecified or bind_address.is_multicast:
        raise ConfigurationError("bindAddress must not be wildcard or multicast")
    if any(bind_address in network for network in DOCUMENTATION_NETWORKS):
        raise ConfigurationError("bindAddress still uses a documentation-only address")
    if not (bind_address.is_loopback or bind_address.is_private):
        raise ConfigurationError("bindAddress must be loopback or a private network address")

    admin_user = _required_string(raw, "grafanaAdminUser")
    if not re.fullmatch(r"[A-Za-z0-9_.@-]{1,64}", admin_user):
        raise ConfigurationError("grafanaAdminUser contains unsupported characters")

    password_path_text = _required_string(raw, "grafanaAdminPasswordFile")
    password_path = Path(password_path_text).expanduser()
    if not password_path.is_absolute():
        password_path = (path.parent / password_path).resolve()
    if not password_path.is_file() or password_path.stat().st_size < 16:
        raise ConfigurationError("Grafana password file must exist and contain at least 16 bytes")

    retention_time = _required_string(raw, "prometheusRetentionTime")
    if not re.fullmatch(r"[1-9][0-9]*(?:h|d|w|y)", retention_time):
        raise ConfigurationError("prometheusRetentionTime must be a positive h/d/w/y duration")
    retention_size = _required_string(raw, "prometheusRetentionSize")
    if not re.fullmatch(r"[1-9][0-9]*(?:MB|GB|TB)", retention_size):
        raise ConfigurationError("prometheusRetentionSize must be a positive MB/GB/TB size")

    return {
        "MONITORING_BIND_ADDRESS": str(bind_address),
        "GRAFANA_ADMIN_USER": admin_user,
        "GRAFANA_ADMIN_PASSWORD_FILE": str(password_path),
        "PROMETHEUS_RETENTION_TIME": retention_time,
        "PROMETHEUS_RETENTION_SIZE": retention_size,
    }


def compose_command(*arguments: str) -> list[str]:
    return ["docker", "compose", "-f", str(COMPOSE_FILE), *arguments]


def run_checked(command: list[str], environment: dict[str, str]) -> None:
    result = subprocess.run(command, cwd=ROOT, env=environment, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"command failed with exit code {result.returncode}: {command[0]} {command[1]}")


def operate(config_path: Path, apply: bool, confirmation: str, validate_containers: bool) -> None:
    settings = load_config(config_path.resolve())
    if shutil.which("docker") is None:
        raise RuntimeError("docker is required")
    environment = os.environ.copy()
    environment.update(settings)

    run_checked(compose_command("config", "--quiet"), environment)
    if apply and confirmation != CONFIRMATION:
        raise ConfigurationError(f"installation requires --confirm-install {CONFIRMATION}")

    if apply:
        run_checked(compose_command("pull"), environment)
    if apply or validate_containers:
        run_checked(
            [
                "docker", "run", "--rm", "--read-only", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges:true",
                "--mount", f"type=bind,src={ROOT / 'prometheus/prometheus.yml'},dst=/etc/prometheus/prometheus.yml,readonly",
                "--mount", f"type=bind,src={ROOT / 'prometheus/platform-alerts.yml'},dst=/etc/prometheus/rules/platform-alerts.yml,readonly",
                "--entrypoint", "/bin/promtool", PROMETHEUS_IMAGE,
                "check", "config", "/etc/prometheus/prometheus.yml",
            ],
            environment,
        )
        run_checked(
            [
                "docker", "run", "--rm", "--read-only", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges:true",
                "--mount", f"type=bind,src={ROOT / 'alertmanager/alertmanager.yml'},dst=/etc/alertmanager/alertmanager.yml,readonly",
                "--entrypoint", "/bin/amtool", ALERTMANAGER_IMAGE,
                "check-config", "/etc/alertmanager/alertmanager.yml",
            ],
            environment,
        )
    if apply:
        run_checked(compose_command("up", "-d", "--remove-orphans"), environment)
        run_checked(compose_command("ps"), environment)
        print("Monitoring stack installed. Private values: suppressed.")
    else:
        print("Monitoring configuration is valid. Mutation: none. Private values: suppressed.")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-install", default="")
    parser.add_argument(
        "--validate-containers",
        action="store_true",
        help="run promtool/amtool in pinned containers; may pull missing images",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    options = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        operate(options.config, options.apply, options.confirm_install, options.validate_containers)
    except (ConfigurationError, RuntimeError) as error:
        print(f"monitoring installation refused: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
