"""Exact, subprocess-isolated adapter for the external SoluProt dependency."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import signal
import stat
import subprocess
from typing import Any, Literal

from core import ReadinessResult


SoluProtMode = Literal["full", "no_tm"]
SOLUPROT_VERSION = "1.1.0"
SOLUPROT_PYTHON_VERSION = "3.12.13"
SOLUPROT_PYTHON_SHA256 = (
    "31b9c9a8d50289f3a13f014b3efd8ea3534fc3eea7ca7d9809e166139910b805"
)
SOLUPROT_SOURCE_SHA256 = (
    "71566eb9a5e78099cf82e0da55bf7f4f173c06a0c22395ba7a18324d9234db96"
)
SOLUPROT_FEATURES_SHA256 = (
    "4dd9252e10efcd033aa8f43d555c05615cf2e6bfa004f77e25277b89219c6281"
)
SOLUPROT_DATABASE_SHA256 = (
    "3b5b2475d3f4ef7cdfd8d0e9d32a31804de8a2ccacc2fac3f4d0506319669bd6"
)
SOLUPROT_USEARCH_SHA256 = (
    "de3c4206a92754ba8762237b4c436ed4b72bb7bcfe287891365b47cdda0f5095"
)
SOLUPROT_MODEL_SHA256 = {
    "full": "20ec7d95ee71b31e1ad8e1ff66ad3b966d675bfcf877196dba1db6a3cbbf7e2b",
    "no_tm": "df7f7b8af235981290b77fab7d2be113a81a3e55f14e81b91837e6d96d8d9e60",
}
SOLUPROT_MODEL_TREES_SHA256 = {
    "full": "f8b9fcd813a1fcf55d7fa75a34f7c2a157d35d8f90fdb6189f86833c8c578097",
    "no_tm": "a6e952856f284b35d6524335eae1042cde585a55460308aa0fcf8b9f505277a8",
}
_SOLUPROT_CODE_SHA256 = {
    "soluprot_core/cli.py": (
        "f22b6d7687c3a10b30e5f622add1acf7b28950aae05c3311cdd680ff9e6e4a8d"
    ),
    "soluprot_core/features.py": SOLUPROT_FEATURES_SHA256,
    "soluprot_core/model.py": (
        "c15b914967f32a679fd5d99c93c5af8f110410f2a88624a0b28b8bb633d821e1"
    ),
}
SOLUPROT_TMHMM_SHA256 = {
    "bin/decodeanhmm.Darwin_arm64": (
        "15d6c29dfced4c58b6e56860edb098aa2dce9b7456b9d2969a21b780334d9a6c"
    ),
    "bin/tmhmm": (
        "dfbcf6a8a2d7eb604d83e61b158d652d20e94353f7e1f8a1601d14d9f09a371e"
    ),
    "bin/tmhmmformat.pl": (
        "80b561f6c8035cd93f4653dea0183f765f9b08928057a938e98a872389f8a166"
    ),
    "lib/TMHMM2.0.model": (
        "aa57306b2f6000ee305185d8c58603c7f6463ecb41c98d16d1dfd80302ffa9be"
    ),
    "lib/TMHMM2.0.options": (
        "90d0db4ca8f5dc33deac2e945a1cf904f31a97f7982a1c64214c91d49827983c"
    ),
}
_CANONICAL_AMINO_ACIDS = frozenset("ACDEFGHIKLMNPQRSTVWY")
_MAX_PROVIDER_OUTPUT_BYTES = 1024 * 1024


class SoluProtInvocationError(RuntimeError):
    """A path-free provider failure safe for durable public diagnostics."""


def _regular_file_sha256(path: object, *, executable: bool = False) -> str:
    if not isinstance(path, Path) or path.is_symlink():
        raise FileNotFoundError("configured SoluProt asset is unavailable")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise FileNotFoundError("configured SoluProt asset is unavailable")
        if executable and not metadata.st_mode & 0o111:
            raise FileNotFoundError("configured SoluProt executable is unavailable")
        digest = hashlib.sha256()
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def _require_digest(
    path: object,
    expected: str,
    *,
    executable: bool = False,
) -> Path:
    if _regular_file_sha256(path, executable=executable) != expected:
        raise RuntimeError("configured SoluProt asset identity changed")
    assert isinstance(path, Path)
    return path


def _validate_python_runtime(
    path: object,
    *,
    site_packages_root: Path,
) -> Path:
    if (
        not isinstance(path, Path)
        or not path.is_file()
        or not os.access(path, os.X_OK)
    ):
        raise FileNotFoundError("configured SoluProt Python is unavailable")
    if _regular_file_sha256(path.resolve(), executable=True) != (
        SOLUPROT_PYTHON_SHA256
    ):
        raise RuntimeError("configured SoluProt Python identity changed")
    probe = (
        "import importlib.metadata as m,json,pathlib,platform,soluprot_core;"
        "print(json.dumps({'python':platform.python_version(),"
        "'soluprot':m.version('soluprot'),"
        "'site':str(pathlib.Path(soluprot_core.__file__).resolve().parent.parent)}))"
    )
    try:
        completed = subprocess.run(
            [str(path), "-I", "-c", probe],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
            env={
                "HOME": os.devnull,
                "LANG": "C",
                "LC_ALL": "C",
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            },
        )
        identity = json.loads(completed.stdout)
    except (
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
    ) as error:
        raise RuntimeError(
            "configured SoluProt Python identity is unavailable"
        ) from error
    if (
        not isinstance(identity, dict)
        or set(identity) != {"python", "soluprot", "site"}
        or identity["python"] != SOLUPROT_PYTHON_VERSION
        or identity["soluprot"] != SOLUPROT_VERSION
        or Path(identity["site"]).resolve() != site_packages_root.resolve()
    ):
        raise RuntimeError("configured SoluProt Python identity changed")
    return path


def _site_asset_paths(
    site_packages_root: Path,
    mode: SoluProtMode,
) -> dict[str, Path]:
    model_dir = (
        "grad_clf_v1_tc"
        if mode == "full"
        else "grad_clf_v1_tc_notmhmm"
    )
    return {
        "model_json": site_packages_root / "data" / "models" / model_dir / "model.json",
        "model_arrays": site_packages_root / "data" / "models" / model_dir / "trees.npz",
        "reference_database": (
            site_packages_root / "data" / "Ecoli_xray_nmr_pdb_no_nesg.fa"
        ),
    }


def configured_runtime_fingerprint(mode: SoluProtMode) -> str:
    """Return one path-free identity for all result-affecting assets."""
    payload: dict[str, Any] = {
        "schema_namespace": "protein-workbench-soluprot-runtime/v2",
        "mode": mode,
        "python_version": SOLUPROT_PYTHON_VERSION,
        "python_sha256": SOLUPROT_PYTHON_SHA256,
        "provider_version": SOLUPROT_VERSION,
        "source_sha256": SOLUPROT_SOURCE_SHA256,
        "code_sha256": _SOLUPROT_CODE_SHA256,
        "model_json_sha256": SOLUPROT_MODEL_SHA256[mode],
        "model_arrays_sha256": SOLUPROT_MODEL_TREES_SHA256[mode],
        "reference_database_sha256": SOLUPROT_DATABASE_SHA256,
        "usearch_sha256": SOLUPROT_USEARCH_SHA256,
    }
    if mode == "full":
        payload["tmhmm_sha256"] = SOLUPROT_TMHMM_SHA256
    return "sha256:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def validate_soluprot_environment(
    environment: Mapping[str, Any],
    *,
    mode: SoluProtMode,
) -> dict[str, Any]:
    """Validate one Binding's exact assets without importing/loading a model."""
    if mode not in {"full", "no_tm"}:
        raise ValueError("unknown SoluProt mode")
    if (
        environment.get("resolved_runtime_fingerprint")
        != configured_runtime_fingerprint(mode)
    ):
        raise RuntimeError("configured SoluProt runtime identity changed")
    python_executable = environment.get("python_executable")
    wheel_path = environment.get("wheel_path")
    site_packages_root = environment.get("site_packages_root")
    usearch_executable = environment.get("usearch_executable")
    if (
        not isinstance(site_packages_root, Path)
        or site_packages_root.is_symlink()
        or not site_packages_root.is_dir()
    ):
        raise FileNotFoundError("configured SoluProt package root is unavailable")
    python_path = _validate_python_runtime(
        python_executable,
        site_packages_root=site_packages_root,
    )
    _require_digest(wheel_path, SOLUPROT_SOURCE_SHA256)
    for relative, expected in _SOLUPROT_CODE_SHA256.items():
        _require_digest(site_packages_root / relative, expected)
    assets = _site_asset_paths(site_packages_root, mode)
    _require_digest(assets["model_json"], SOLUPROT_MODEL_SHA256[mode])
    _require_digest(assets["model_arrays"], SOLUPROT_MODEL_TREES_SHA256[mode])
    _require_digest(assets["reference_database"], SOLUPROT_DATABASE_SHA256)
    usearch = _require_digest(
        usearch_executable,
        SOLUPROT_USEARCH_SHA256,
        executable=True,
    )
    tmhmm_executable: Path | None = None
    if mode == "full":
        tmhmm_root = environment.get("tmhmm_root")
        if (
            not isinstance(tmhmm_root, Path)
            or tmhmm_root.is_symlink()
            or not tmhmm_root.is_dir()
        ):
            raise FileNotFoundError("configured SoluProt TMHMM root is unavailable")
        for relative, expected in SOLUPROT_TMHMM_SHA256.items():
            _require_digest(
                tmhmm_root / relative,
                expected,
                executable=relative in {
                    "bin/decodeanhmm.Darwin_arm64",
                    "bin/tmhmm",
                    "bin/tmhmmformat.pl",
                },
            )
        tmhmm_executable = tmhmm_root / "bin" / "tmhmm"
    return {
        "python_executable": python_path,
        "site_packages_root": site_packages_root,
        "model_json": assets["model_json"],
        "reference_database": assets["reference_database"],
        "usearch_executable": usearch,
        "tmhmm_executable": tmhmm_executable,
        "resolved_runtime_fingerprint": configured_runtime_fingerprint(mode),
    }


def soluprot_readiness(
    environment: Mapping[str, Any],
    *,
    mode: SoluProtMode,
) -> ReadinessResult:
    """Independently attest one mode without loading either model."""
    try:
        validate_soluprot_environment(environment, mode=mode)
    except (FileNotFoundError, OSError, RuntimeError, ValueError):
        return ReadinessResult(
            False,
            proof_source="direct-observation",
            reason_code=f"soluprot_{mode}_runtime_unavailable",
        )
    return ReadinessResult(True, proof_source="direct-observation")


def validate_sequences(sequences: Sequence[str]) -> None:
    """Fail closed on every provider-invalid sequence before invocation."""
    if not sequences:
        raise ValueError("SoluProt requires at least one sequence")
    for sequence in sequences:
        if (
            not isinstance(sequence, str)
            or len(sequence) < 20
            or not set(sequence) <= _CANONICAL_AMINO_ACIDS
        ):
            raise ValueError(
                "SoluProt requires canonical protein sequences of at least 20 residues"
            )


def _write_fasta(path: Path, sequences: Sequence[str]) -> None:
    with path.open("x", encoding="ascii", newline="\n") as handle:
        for index, sequence in enumerate(sequences):
            handle.write(f">candidate_{index}\n{sequence}\n")


def _read_provider_output(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size > _MAX_PROVIDER_OUTPUT_BYTES
        ):
            raise SoluProtInvocationError(
                "SoluProt provider output violated the byte contract"
            )
        chunks: list[bytes] = []
        remaining = metadata.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                raise SoluProtInvocationError(
                    "SoluProt provider output was truncated"
                )
            chunks.append(chunk)
            remaining -= len(chunk)
        final = os.fstat(descriptor)
        if (
            final.st_dev,
            final.st_ino,
            final.st_size,
            final.st_mtime_ns,
        ) != (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
        ):
            raise SoluProtInvocationError(
                "SoluProt provider output changed during validation"
            )
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def invoke_soluprot(
    *,
    sequences: Sequence[str],
    mode: SoluProtMode,
    staging_directory: Path,
    environment: Mapping[str, Any],
    run_resources: Any,
    resolved_environment: Mapping[str, Any] | None = None,
) -> bytes:
    """Cross exactly one provider CLI seam and return its unparsed output."""
    validate_sequences(sequences)
    resolved = (
        dict(resolved_environment)
        if resolved_environment is not None
        else validate_soluprot_environment(environment, mode=mode)
    )
    input_path = staging_directory / "input.fasta"
    output_path = staging_directory / "output.csv"
    scratch_path = staging_directory / "provider-work"
    scratch_path.mkdir(mode=0o700)
    _write_fasta(input_path, sequences)
    command = [
        str(resolved["python_executable"]),
        "-I",
        "-m",
        "soluprot_core.cli",
        "--i_fa",
        str(input_path),
        "--o_csv",
        str(output_path),
        "--tmp_dir",
        str(scratch_path),
        "--model",
        str(resolved["model_json"]),
        "--usearch",
        str(resolved["usearch_executable"]),
        "--pdb",
        str(resolved["reference_database"]),
        "--check_unknown",
        "--no_proc",
        "1",
    ]
    if mode == "full":
        command.extend(["--tmhmm", str(resolved["tmhmm_executable"])])
    else:
        command.append("--no_tmhmm")
    process = subprocess.Popen(
        command,
        cwd=staging_directory,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={
            "HOME": str(staging_directory),
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        },
        start_new_session=True,
    )
    try:
        with run_resources.cancellable_process_group(
            process.pid,
            fallback=process.kill,
        ):
            process.communicate(timeout=300)
    except subprocess.TimeoutExpired as error:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        raise SoluProtInvocationError(
            "SoluProt provider invocation timed out safely"
        ) from error
    if process.returncode != 0:
        raise SoluProtInvocationError(
            f"SoluProt provider invocation failed safely "
            f"(exit status {process.returncode})"
        )
    try:
        return _read_provider_output(output_path)
    except OSError as error:
        raise SoluProtInvocationError(
            "SoluProt provider produced no readable output"
        ) from error


def parse_soluprot_output(payload: bytes, *, expected_count: int) -> list[float]:
    """Decode the closed upstream CSV contract without clamping or guessing."""
    try:
        text = payload.decode("utf-8")
        reader = csv.DictReader(io.StringIO(text, newline=""))
    except (UnicodeDecodeError, csv.Error) as error:
        raise ValueError("SoluProt output is not valid UTF-8 CSV") from error
    if reader.fieldnames != ["runtime_id", "fa_id", "soluble"]:
        raise ValueError("SoluProt output columns do not match the exact contract")
    values: list[float] = []
    try:
        for expected_index, row in enumerate(reader):
            if (
                set(row) != {"runtime_id", "fa_id", "soluble"}
                or row["runtime_id"] != str(expected_index)
                or row["fa_id"] != f"candidate_{expected_index}"
            ):
                raise ValueError("SoluProt output identity or ordering is invalid")
            value = float(row["soluble"])
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("SoluProt output is outside its declared range")
            values.append(value)
    except (csv.Error, TypeError, ValueError) as error:
        if isinstance(error, ValueError) and str(error).startswith("SoluProt"):
            raise
        raise ValueError("SoluProt output contains an invalid value") from error
    if len(values) != expected_count:
        raise ValueError("SoluProt output row count is incomplete")
    return values
