"""Locked provider identities shared by adapters and real verification gates."""

from __future__ import annotations

import base64
import hashlib
import importlib.metadata
import json
import os
import stat
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


ESM_SDK_REVISION = "917af90b624535eed1e072d343c717e3ec11fef4"
LOCAL_ESM3_SNAPSHOT_REVISION = "47f0545b2b6daf26a93439a3cd610f4f7f3d5478"
LOCAL_ESM3_WEIGHT_SHA256 = {
    "data/weights/esm3_sm_open_v1.pth": (
        "5ead5a135c658068db6a4f1b933e72d6110992c4668822e1c0e2dcc53e38acd9"
    ),
    "data/weights/esm3_structure_encoder_v0.pth": (
        "467acbaee703ba3ccde6e75241a912a316952e5ff071355f85c1d33c68704f40"
    ),
    "data/weights/esm3_structure_decoder_v0.pth": (
        "3b726258a44274792b40ce7ea307e10c5da09936368a4ffa2970264d909da65b"
    ),
    "data/weights/esm3_function_decoder_v0.pth": (
        "f76d074efcaccfe21365a4fa96f212dadd66798e1e49d809ab7ffbe025d227c9"
    ),
}
BIOHUB_ESM3_MODEL = "esm3-medium-2024-08"
BIOHUB_ESM3_OPEN_MODEL = "esm3-open-2024-03"
BIOHUB_ESMFOLD2_MODEL = "esmfold2-fast-2026-05"
PROTEINMPNN_REVISION = "8907e6671bfbfc92303b5f79c4b5e6ce47cdef57"
SIMPLEFOLD_REVISION = "c7a5570a6be9f5c695126e27c804e77567209934"
SIMPLEFOLD_ESM2_REVISION = "2b369911bb5b4b0dda914521b9475cad1656b2ac"
SIMPLEFOLD_ESM2_SOURCE_TREE_SHA256 = (
    "da1fd5e94771906950ccc9b4e789d50b0e8f8c4594608898dbcb14f14e3c50ba"
)
SIMPLEFOLD_ESM2_ARTIFACT_IDENTITIES = {
    "esm2_t36_3B_UR50D.pt": {"bytes": 5678116398},
    "esm2_t36_3B_UR50D-contact-regression.pt": {"bytes": 6759},
}
SIMPLEFOLD_ESM2_ARTIFACT_SHA256 = {
    "esm2_t36_3B_UR50D.pt": (
        "7de8b4082ba15891959ab368b77ce3886697af1efb16d3c9e9e7b0c5d3f07500"
    ),
    "esm2_t36_3B_UR50D-contact-regression.pt": (
        "4da500eab246481dc9c8c95bc7b1d02f2803d761c380b0e95186d4a07d0fc84e"
    ),
}

SIMPLEFOLD_ARTIFACT_IDENTITIES = {
    "simplefold_100M.ckpt": {
        "object": "simplefold_100M.ckpt",
        "bytes": 386772550,
        "etag": "d3f36328118ca08f0aac3a0e910b6829-23",
    },
    "simplefold_360M.ckpt": {
        "object": "simplefold_360M.ckpt",
        "bytes": 1454881694,
        "etag": "7c0603668846e72a0bd8a2c8b43b1151-85",
    },
    "simplefold_1.6B.ckpt": {
        "object": "simplefold_1.6B.ckpt",
        "bytes": 6354525226,
        "etag": "8547a616a08162144b9591b3e9479b8e-370",
    },
    "plddt.ckpt": {
        "object": "plddt_module_1.6B.ckpt",
        "bytes": 462812900,
        "etag": "1ed78d3cf12e8558ec45c596b1197ba9-27",
    },
}

SIMPLEFOLD_AUXILIARY_ARTIFACTS = (
    "ccd.pkl",
    "boltz1_conf.ckpt",
)
# Maintainer-reviewed immutable digests for the exact runtime artifacts.  The
# adapter verifies and stages every file before importing or invoking SimpleFold.
SIMPLEFOLD_ARTIFACT_SHA256 = {
    "simplefold_100M.ckpt": (
        "4cd0b8a0b317a6ab8634444fffd78ce84cfd49c20fe927b83c76c36fda5f54bd"
    ),
    "simplefold_360M.ckpt": (
        "517338ec36b10ecc774f36b592ffe0fee6a24fa5c7d2fcfa3e3009282d48a49b"
    ),
    "simplefold_1.6B.ckpt": (
        "aaac2d73dcc59c61153c58a1d56e74a8ada9d6057d67000f7836f3c87325312b"
    ),
    "plddt.ckpt": (
        "cb32fa9cdc9e80406b793a8c09a929077534d9991a1d08f4c159d2e4ed81315f"
    ),
    "ccd.pkl": (
        "2d3b2f03a3c5665944adba51e33263511e51b21c9cd05d902f9c4b7c1e58d2f4"
    ),
    "boltz1_conf.ckpt": (
        "219a73ac67535ad0535b9d3fb11fc7dbbcb7a0b71e4b4bb28f0c50cc2ac7f4ee"
    ),
}
SIMPLEFOLD_EXECUTION_ENABLED = True
PROVIDER_PACKAGE_TREE_SHA256 = {
    "esm": "4d50a2977825a046d8e6045189b1d8d75082ba3b9bfd69db8939f2063745b621",
    "simplefold": (
        "7eff5379ff65ca1c56bd784c5a2fb1091bafb76dd26b1a4afaf776fc656bcc07"
    ),
}

PROTEINMPNN_V_48_020_SHA256 = (
    "c9cb4a671d79604111231f8dbfc7c590e06f1197453b7a6854ac6661a642f5bd"
)


def esm_provider_identity(*, local: bool = False) -> dict[str, Any]:
    identity: dict[str, Any] = {
        "sdk": "esm",
        "sdk_source_revision": ESM_SDK_REVISION,
        "service": "local_open" if local else "Biohub",
    }
    if local:
        identity.update({
            "snapshot_revision": LOCAL_ESM3_SNAPSHOT_REVISION,
            "weight_sha256": LOCAL_ESM3_WEIGHT_SHA256,
        })
    return identity


def proteinmpnn_provider_identity() -> dict[str, str]:
    return {
        "source": "ProteinMPNN",
        "source_revision": PROTEINMPNN_REVISION,
        "checkpoint_sha256": PROTEINMPNN_V_48_020_SHA256,
    }


def simplefold_provider_identity(
    artifact_sha256: dict[str, str],
) -> dict[str, Any]:
    return {
        "source": "ml-simplefold",
        "source_revision": SIMPLEFOLD_REVISION,
        "esm2_source_revision": SIMPLEFOLD_ESM2_REVISION,
        "esm2_source_tree_sha256": SIMPLEFOLD_ESM2_SOURCE_TREE_SHA256,
        "esm2_artifact_sha256": SIMPLEFOLD_ESM2_ARTIFACT_SHA256,
        "artifact_sha256": dict(sorted(artifact_sha256.items())),
    }


def _git(*args: str, cwd: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(cwd), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Provider package is not from a verifiable Git checkout") from exc
    return completed.stdout.strip()


def _package_tree_sha256(
    files: list[tuple[str, Path]],
) -> str:
    digest = hashlib.sha256()
    for relative, path in sorted(files):
        digest.update(relative.encode() + b"\0")
        file_digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                file_digest.update(chunk)
        digest.update(file_digest.digest())
    return digest.hexdigest()


def validate_installed_provider_checkout(
    package_name: str,
    expected_revision: str,
) -> Path:
    """Verify installed VCS provenance or an editable checkout's live Git state."""
    distribution = importlib.metadata.distribution(package_name)
    direct_url_text = distribution.read_text("direct_url.json")
    if not direct_url_text:
        raise RuntimeError("Provider package has no PEP 610 VCS provenance")
    try:
        direct_url = json.loads(direct_url_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Provider package has invalid PEP 610 provenance") from exc
    vcs_info = direct_url.get("vcs_info")
    if isinstance(vcs_info, dict):
        if (
            vcs_info.get("vcs") != "git"
            or vcs_info.get("commit_id") != expected_revision
            or vcs_info.get("requested_revision") != expected_revision
        ):
            raise RuntimeError(
                "Provider package VCS provenance does not match locked revision"
            )
        recorded_hashes: dict[str, Any] = {}
        for package_file in distribution.files or ():
            parts = Path(str(package_file)).parts
            if (
                not parts
                or parts[0] != package_name
                or "__pycache__" in parts
                or str(package_file).endswith(".pyc")
            ):
                continue
            if (
                package_file.hash is None
                or package_file.hash.mode != "sha256"
            ):
                raise RuntimeError(
                    "Installed provider runtime file lacks a SHA-256 entry"
                )
            relative = Path(*parts[1:]).as_posix()
            recorded_hashes[relative] = package_file.hash
        package_root_path = Path(distribution.locate_file(package_name))
        if package_root_path.is_symlink() or not package_root_path.is_dir():
            raise RuntimeError("Installed provider package root is not regular")
        package_root = package_root_path.resolve()
        runtime_files: list[tuple[str, Path]] = []
        for installed_file in package_root.rglob("*"):
            if installed_file.is_symlink():
                raise RuntimeError("Installed provider contains a symlink")
            if (
                not installed_file.is_file()
                or "__pycache__" in installed_file.parts
                or installed_file.suffix == ".pyc"
            ):
                continue
            relative = installed_file.relative_to(package_root).as_posix()
            package_hash = recorded_hashes.get(relative)
            if package_hash is None:
                raise RuntimeError(
                    "Installed provider runtime file is absent from RECORD"
                )
            digest = hashlib.new(package_hash.mode)
            with installed_file.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)
            encoded = base64.urlsafe_b64encode(digest.digest()).decode().rstrip("=")
            if encoded != package_hash.value:
                raise RuntimeError("Installed provider file hash mismatch")
            runtime_files.append((
                relative,
                installed_file,
            ))
        if not runtime_files or {
            relative for relative, _ in runtime_files
        } != set(recorded_hashes):
            raise RuntimeError("Installed provider RECORD inventory mismatch")
        if (
            _package_tree_sha256(runtime_files)
            != PROVIDER_PACKAGE_TREE_SHA256[package_name]
        ):
            raise RuntimeError(
                "Installed provider package tree does not match reviewed source"
            )
        return package_root
    if direct_url.get("dir_info", {}).get("editable") is not True:
        raise RuntimeError("Provider package is not from a locked VCS install")
    parsed_url = urlparse(str(direct_url.get("url", "")))
    if parsed_url.scheme != "file":
        raise RuntimeError("Editable provider provenance is not a local file URL")
    editable_root = Path(unquote(parsed_url.path)).resolve()
    checkout = Path(
        _git("rev-parse", "--show-toplevel", cwd=editable_root)
    ).resolve()
    package_roots = (
        checkout / package_name,
        checkout / "src" / package_name,
    )
    package_root = next((
        root
        for root in package_roots
        if not root.is_symlink() and (root / "__init__.py").is_file()
    ), None)
    if package_root is None:
        raise RuntimeError("Editable provider checkout lacks the expected package")
    runtime_files = [
        (path.relative_to(package_root).as_posix(), path)
        for path in package_root.rglob("*")
        if (
            path.is_file()
            and not path.is_symlink()
            and "__pycache__" not in path.parts
            and path.suffix != ".pyc"
        )
    ]
    if (
        _package_tree_sha256(runtime_files)
        != PROVIDER_PACKAGE_TREE_SHA256[package_name]
    ):
        raise RuntimeError(
            "Editable provider package tree does not match reviewed source"
        )
    if _git("rev-parse", "HEAD", cwd=checkout) != expected_revision:
        raise RuntimeError("Provider package checkout does not match locked revision")
    if _git("status", "--porcelain", "--untracked-files=all", cwd=checkout):
        raise RuntimeError("Provider package checkout is not clean")
    return checkout


def _open_biohub_token(path: Path) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    file_stat = os.fstat(descriptor)
    if (
        not stat.S_ISREG(file_stat.st_mode)
        or file_stat.st_uid != os.getuid()
        or file_stat.st_nlink != 1
        or stat.S_IMODE(file_stat.st_mode) & 0o077
        or not 0 < file_stat.st_size <= 16 * 1024
    ):
        os.close(descriptor)
        raise PermissionError("Biohub token file is not a private regular file")
    return descriptor


def validate_biohub_token_file(path: str | Path) -> Path:
    """Validate token metadata through one no-follow descriptor."""
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        raise FileNotFoundError("Biohub token file path must be absolute")
    try:
        descriptor = _open_biohub_token(candidate)
    except OSError as error:
        raise FileNotFoundError(
            "Configured Biohub token file is unavailable"
        ) from error
    os.close(descriptor)
    return candidate


def read_biohub_token(project_dir: str | None = None) -> str:
    """Read a token from a configured file without retaining its value."""
    configured = os.environ.get("PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE")
    if configured:
        candidates = [Path(configured).expanduser()]
    else:
        if (
            os.environ.get("PROTEIN_WORKBENCH_VERIFICATION_TIER")
            == "fresh-remote-3gb1"
        ):
            raise FileNotFoundError(
                "Fresh remote gate requires an explicit Biohub token file"
            )
        candidates = [Path("keys/esmkey.txt")]
        if project_dir:
            candidates.append(
                Path(project_dir) / ".." / ".." / "keys" / "esmkey.txt"
            )
    for candidate in candidates:
        try:
            descriptor = _open_biohub_token(candidate)
        except OSError:
            continue
        try:
            before = os.fstat(descriptor)
            payload = os.read(descriptor, 16 * 1024 + 1)
            after = os.fstat(descriptor)
            stable_fields = (
                "st_dev",
                "st_ino",
                "st_size",
                "st_mtime_ns",
                "st_ctime_ns",
                "st_nlink",
            )
            if any(
                getattr(before, field_name) != getattr(after, field_name)
                for field_name in stable_fields
            ):
                continue
            if len(payload) > 16 * 1024:
                continue
            token = payload.decode().strip()
            if token:
                return token
        finally:
            os.close(descriptor)
    raise FileNotFoundError(
        "Biohub API key not found. Configure "
        "PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE."
    )


def local_esm3_snapshot_root() -> Path:
    """Resolve the exact offline Hugging Face snapshot required by the gate."""
    configured_cache = os.environ.get("HF_HUB_CACHE")
    if configured_cache:
        hub_cache = Path(configured_cache).expanduser()
    else:
        hf_home = Path(
            os.environ.get(
                "HF_HOME",
                str(Path.home() / ".cache" / "huggingface"),
            )
        ).expanduser()
        hub_cache = hf_home / "hub"
    snapshot = (
        hub_cache
        / "models--biohub--esm3-sm-open-v1"
        / "snapshots"
        / LOCAL_ESM3_SNAPSHOT_REVISION
    )
    if not snapshot.is_dir():
        raise FileNotFoundError(
            "Locked local ESM3 snapshot is not installed"
        )
    return snapshot


@lru_cache(maxsize=1)
def validate_local_esm3_snapshot() -> Path:
    """Verify every locked local ESM3 weight before inference."""
    snapshot = local_esm3_snapshot_root()
    repository_root = snapshot.parents[1].resolve()
    for relative_path, expected_sha256 in LOCAL_ESM3_WEIGHT_SHA256.items():
        weight = snapshot / relative_path
        resolved = weight.resolve()
        if (
            not weight.exists()
            or not resolved.is_file()
            or not resolved.is_relative_to(repository_root)
        ):
            raise FileNotFoundError(
                f"Locked local ESM3 weight is unavailable: {relative_path}"
            )
        digest = hashlib.sha256()
        with resolved.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest() != expected_sha256:
            raise RuntimeError(
                f"Locked local ESM3 weight digest mismatch: {relative_path}"
            )
    return snapshot
