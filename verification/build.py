#!/usr/bin/env python3
"""Build deterministic Protein Workbench wheel and sdist artifacts."""

from __future__ import annotations

import argparse
import gzip
import os
import subprocess
import sys
import tarfile
import tempfile
from importlib.metadata import version
from io import BytesIO
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DATE_EPOCH = 1727740800
BUILD_TOOLCHAIN = {
    "build": "1.5.0",
    "setuptools": "83.0.0",
}


def _verify_build_toolchain() -> None:
    installed = {package: version(package) for package in BUILD_TOOLCHAIN}
    if installed != BUILD_TOOLCHAIN:
        raise RuntimeError(
            "Build toolchain does not match the frozen contract: "
            f"expected {BUILD_TOOLCHAIN}, got {installed}"
        )


def _normalize_sdist(path: Path) -> None:
    with tarfile.open(path, "r:gz") as source:
        entries = [
            (member, source.extractfile(member).read() if member.isfile() else None)
            for member in source.getmembers()
        ]

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "wb") as raw_output:
            with gzip.GzipFile(
                filename="",
                mode="wb",
                fileobj=raw_output,
                mtime=SOURCE_DATE_EPOCH,
            ) as compressed:
                with tarfile.open(
                    fileobj=compressed,
                    mode="w",
                    format=tarfile.PAX_FORMAT,
                ) as output:
                    for member, payload in entries:
                        if not (member.isdir() or member.isfile()):
                            raise RuntimeError(
                                f"Unsupported sdist entry: {member.name}"
                            )
                        member.mtime = SOURCE_DATE_EPOCH
                        member.uid = 0
                        member.gid = 0
                        member.uname = "root"
                        member.gname = "root"
                        member.mode = 0o755 if member.isdir() else 0o644
                        member.pax_headers = {}
                        if payload is None:
                            output.addfile(member)
                        else:
                            output.addfile(member, BytesIO(payload))
        os.replace(temporary_name, path)
        path.chmod(0o644)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    _verify_build_toolchain()
    env = os.environ.copy()
    env["SOURCE_DATE_EPOCH"] = str(SOURCE_DATE_EPOCH)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--no-isolation",
            "--outdir",
            str(output_dir),
            str(PROJECT_ROOT),
        ],
        cwd=output_dir,
        env=env,
        check=True,
    )
    sdists = list(output_dir.glob("protein_workbench-*.tar.gz"))
    if len(sdists) != 1:
        raise RuntimeError(f"Expected one sdist, found {len(sdists)}")
    _normalize_sdist(sdists[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
