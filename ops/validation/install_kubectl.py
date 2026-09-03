#!/usr/bin/env python3
"""Install the pinned kubectl binary after verifying its official checksum."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import urllib.request
from pathlib import Path
from typing import Sequence


KUBECTL_VERSION = "1.36.0"
KUBECTL_SHA256 = "123d8c8844f46b1244c547fffb3c17180c0c26dac9890589fe7e67763298748e"
KUBECTL_URL = f"https://dl.k8s.io/v{KUBECTL_VERSION}/bin/linux/amd64/kubectl"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def install(output: Path) -> None:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and sha256(output) == KUBECTL_SHA256:
        output.chmod(0o755)
        return

    temporary = output.with_name(f".{output.name}.download")
    temporary.unlink(missing_ok=True)
    request = urllib.request.Request(KUBECTL_URL, headers={"User-Agent": "faang-infra-validator"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as destination:
            shutil.copyfileobj(response, destination)
        actual = sha256(temporary)
        if actual != KUBECTL_SHA256:
            raise RuntimeError("Downloaded kubectl checksum does not match the pinned checksum")
        temporary.chmod(0o755)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def parse_arguments(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    options = parse_arguments(arguments)
    try:
        install(options.output)
    except (OSError, RuntimeError) as error:
        print(f"Unable to install pinned kubectl: {error}", file=sys.stderr)
        return 1
    print(f"Pinned kubectl {KUBECTL_VERSION} is ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
