"""Shared exact-checkout admission and private credential-file hygiene."""

from __future__ import annotations

import importlib.metadata
import json
import os
from pathlib import Path
import stat
import subprocess
from urllib.parse import unquote, urlparse


class ProviderInstallationUnavailable(RuntimeError):
    """An exact installed Provider source cannot be admitted."""


def _git(*args: str, cwd: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(cwd), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise ProviderInstallationUnavailable(
            "Provider package is not from a verifiable Git checkout"
        ) from error
    return completed.stdout.strip()


def validate_provider_checkout(
    root: str | Path,
    expected_revision: str,
) -> Path:
    """Admit one configured Provider checkout root at its exact Git revision."""
    candidate = Path(root).expanduser().resolve()
    checkout = Path(
        _git("rev-parse", "--show-toplevel", cwd=candidate)
    ).resolve()
    if checkout != candidate:
        raise ProviderInstallationUnavailable(
            "Configured Provider path is not the Git checkout root"
        )
    if _git("rev-parse", "HEAD", cwd=checkout) != expected_revision:
        raise ProviderInstallationUnavailable(
            "Provider checkout does not match locked revision"
        )
    return checkout


def validate_installed_provider_checkout(
    package_name: str,
    expected_revision: str,
) -> Path:
    """Resolve one installed Provider package from its exact source revision."""
    try:
        distribution = importlib.metadata.distribution(package_name)
    except importlib.metadata.PackageNotFoundError as error:
        raise ProviderInstallationUnavailable(
            "Provider package is not installed"
        ) from error
    direct_url_text = distribution.read_text("direct_url.json")
    if not direct_url_text:
        raise ProviderInstallationUnavailable(
            "Provider package has no PEP 610 VCS provenance"
        )
    try:
        direct_url = json.loads(direct_url_text)
    except json.JSONDecodeError as error:
        raise ProviderInstallationUnavailable(
            "Provider package has invalid PEP 610 provenance"
        ) from error
    vcs_info = direct_url.get("vcs_info")
    if isinstance(vcs_info, dict):
        if (
            vcs_info.get("vcs") != "git"
            or vcs_info.get("commit_id") != expected_revision
            or vcs_info.get("requested_revision") != expected_revision
        ):
            raise ProviderInstallationUnavailable(
                "Provider package VCS provenance does not match locked revision"
            )
        package_root = Path(distribution.locate_file(package_name))
        if not package_root.is_dir():
            raise ProviderInstallationUnavailable(
                "Installed provider package is unavailable"
            )
        return package_root.resolve()
    if direct_url.get("dir_info", {}).get("editable") is not True:
        raise ProviderInstallationUnavailable(
            "Provider package is not from a locked VCS install"
        )
    parsed_url = urlparse(str(direct_url.get("url", "")))
    if parsed_url.scheme != "file":
        raise ProviderInstallationUnavailable(
            "Editable provider provenance is not a local file URL"
        )
    editable_root = Path(unquote(parsed_url.path)).resolve()
    checkout = validate_provider_checkout(editable_root, expected_revision)
    package_roots = (
        checkout / package_name,
        checkout / "src" / package_name,
    )
    package_root = next(
        (
            root
            for root in package_roots
            if (root / "__init__.py").is_file()
        ),
        None,
    )
    if package_root is None:
        raise ProviderInstallationUnavailable(
            "Editable provider checkout lacks the expected package"
        )
    return checkout


_MAX_PRIVATE_CREDENTIAL_BYTES = 16 * 1024
_STABLE_CREDENTIAL_STAT_FIELDS = (
    "st_dev",
    "st_ino",
    "st_size",
    "st_mtime_ns",
    "st_ctime_ns",
    "st_nlink",
)


def _open_private_credential_file(path: Path) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise FileNotFoundError("credential file is unavailable") from error
    file_stat = os.fstat(descriptor)
    if (
        not stat.S_ISREG(file_stat.st_mode)
        or file_stat.st_uid != os.getuid()
        or file_stat.st_nlink != 1
        or stat.S_IMODE(file_stat.st_mode) & 0o077
        or not 0 < file_stat.st_size <= _MAX_PRIVATE_CREDENTIAL_BYTES
    ):
        os.close(descriptor)
        raise PermissionError("credential file is not private")
    return descriptor


def read_private_credential_file(path: str | Path) -> str:
    """Read one private credential through a single stable descriptor."""
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        raise FileNotFoundError("credential file path must be absolute")
    descriptor = _open_private_credential_file(candidate)
    try:
        before = os.fstat(descriptor)
        payload = os.read(descriptor, _MAX_PRIVATE_CREDENTIAL_BYTES + 1)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if any(
        getattr(before, field_name) != getattr(after, field_name)
        for field_name in _STABLE_CREDENTIAL_STAT_FIELDS
    ) or len(payload) > _MAX_PRIVATE_CREDENTIAL_BYTES:
        raise PermissionError("credential file is not private")
    token = payload.decode().strip()
    if not token:
        raise ValueError("credential file is empty")
    return token
