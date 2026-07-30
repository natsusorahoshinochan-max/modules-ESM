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
import re
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
SOLUPROT_RUNTIME_DISTRIBUTIONS = {
    "soluprot": {
        "version": SOLUPROT_VERSION,
        "tree_sha256": (
            "4545de75323fc7bee9e680acc4cf53fbc72526884f343e9d8b516b3182f3eaf9"
        ),
    },
    "numpy": {
        "version": "2.5.1",
        "tree_sha256": (
            "0b0d04a80c0cf06abe5fbab7ddcb6c2e9fe9635a3cdecd4c9b8258ef6d4519c3"
        ),
    },
    "pandas": {
        "version": "3.0.3",
        "tree_sha256": (
            "8a46f6df5d74225edc2d1a22e7464e008c5513e4bb0b53a1df51a350e1af5bbd"
        ),
    },
    "biopython": {
        "version": "1.87",
        "tree_sha256": (
            "e3ebf1d5f5c4f12bb09ead365faa9142308256bf5ed2351a2e1f7b24805704ad"
        ),
    },
    "tqdm": {
        "version": "4.68.4",
        "tree_sha256": (
            "1d73b88d9a23473b8f99e1e0d6e3bd0006e91674098baa94364bb1df7435e51c"
        ),
    },
    "python-dateutil": {
        "version": "2.9.0.post0",
        "tree_sha256": (
            "e59e1256976e4c5aa01c60b90584bab7de15f99a1f6a84e071f58e0a3a1ac458"
        ),
    },
    "six": {
        "version": "1.17.0",
        "tree_sha256": (
            "4306b73cf46c7ca2e8fc881901fb3a2215efbcaa8a520d1964c0650d27a47ec9"
        ),
    },
}
SOLUPROT_PERL_VERSION = "v5.34.1"
SOLUPROT_PERL_SHA256 = (
    "abda2bfd23a6c9a8e57adf2291f0aea4abd8faf440558ee49fe4ced55e8d9ad0"
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
PROTEIN_SOL_RELEASE = "2017-10"
PROTEIN_SOL_POPULATION_SCALED = 0.446
PROTEIN_SOL_CALIBRATION_CONTEXT = {
    "kind": "calibration",
    "calibration_metric": "population_scaled_solubility",
    "calibration_value": PROTEIN_SOL_POPULATION_SCALED,
    "calibration_unit": "dimensionless",
    "population_id": "niwa_non_membrane_2396",
}
PROTEIN_SOL_PERL_VERSION = "v5.34.1"
PROTEIN_SOL_PERL_SHA256 = SOLUPROT_PERL_SHA256
PROTEIN_SOL_BASH_VERSION = (
    "GNU bash, version 3.2.57(1)-release (arm64-apple-darwin25)"
)
PROTEIN_SOL_BASH_SHA256 = (
    "fde343ee184953c1fa1185abddeaa8be61c6acbebae4eb54db5d6b55b09a5755"
)
PROTEIN_SOL_SOURCE_SHA256 = {
    "fasta_seq_reformat_export.pl": (
        "ee671b4121e343e0dd660377a8204c2e5058fcf9185e8ea629b2c3c64562a8e9"
    ),
    "multiple_prediction_wrapper_export.sh": (
        "a7e7d0137508f34734584a6b37157e980bed769f400032f8ecb36949d17dc232"
    ),
    "profiles_gather_export.pl": (
        "ad1aadee73db9b828ed4e87b27bb75191cf48b4934cf8ab3855c80740b674eac"
    ),
    "seq_compositions_perc_pipeline_export.pl": (
        "8e8888220984b77c472333fa57750585d33e7aff93d44cb6b090fccd728d87cb"
    ),
    "seq_props_ALL_export.pl": (
        "f20eac44b526f9b694c6371b06a3a4a9c080d14da1241cb785d77230783efa15"
    ),
    "seq_reference_data.txt": (
        "6943cd600741d5d22b7518b8be40f2850bfa5586e96d637de3db688c7337d1f0"
    ),
    "server_prediction_seq_export.pl": (
        "80f8554e43d605c10a6feea983c222099869119b0a9d73411c5a1b2dd68c4b4d"
    ),
    "ss_propensities.txt": (
        "3c634b252ed83ffd363e6b0936e95813584facddb399f0fcc6769710755fa33f"
    ),
}


class SoluProtInvocationError(RuntimeError):
    """A path-free provider failure safe for durable public diagnostics."""


class SoluProtProviderTimeout(SoluProtInvocationError):
    """The provider exceeded its closed execution budget."""


class SoluProtProviderNonzeroExit(SoluProtInvocationError):
    """The provider returned a nonzero status without retaining raw output."""


class SoluProtProviderOutputUnavailable(SoluProtInvocationError):
    """The provider did not leave one readable output file."""


class SoluProtProviderOutputContractViolation(SoluProtInvocationError):
    """The provider output file violated its bounded file contract."""


class SoluProtProviderOutputTruncated(SoluProtInvocationError):
    """The provider output became shorter while it was read."""


class SoluProtProviderOutputChanged(SoluProtInvocationError):
    """The provider output changed while it was validated."""


class ProteinSolInvocationError(RuntimeError):
    """A path-free Protein-Sol failure safe for durable diagnostics."""


class ProteinSolProviderTimeout(ProteinSolInvocationError):
    """The exact upstream invocation exceeded its closed time budget."""


class ProteinSolProviderNonzeroExit(ProteinSolInvocationError):
    """The exact upstream invocation returned a nonzero exit status."""


class ProteinSolProviderOutputUnavailable(ProteinSolInvocationError):
    """The exact upstream invocation produced no readable result."""


class ProteinSolProviderOutputContractViolation(ProteinSolInvocationError):
    """The exact upstream result violated its bounded file contract."""


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
    distribution_names = tuple(SOLUPROT_RUNTIME_DISTRIBUTIONS)
    probe = f"""
import base64
import hashlib
import importlib.metadata as metadata
import json
import os
import platform
import stat

distributions = {{}}
site = None
for name in {distribution_names!r}:
    distribution = metadata.distribution(name)
    records = []
    for item in sorted(distribution.files or (), key=str):
        recorded_hash = item.hash
        if recorded_hash is None:
            continue
        if recorded_hash.mode != "sha256":
            raise RuntimeError("unsupported installed-record digest")
        descriptor = os.open(
            item.locate(),
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            file_metadata = os.fstat(descriptor)
            if not stat.S_ISREG(file_metadata.st_mode):
                raise RuntimeError("installed runtime file is not regular")
            digest = hashlib.sha256()
            while chunk := os.read(descriptor, 1024 * 1024):
                digest.update(chunk)
        finally:
            os.close(descriptor)
        observed_hash = base64.urlsafe_b64encode(
            digest.digest()
        ).rstrip(b"=").decode()
        if (
            observed_hash != recorded_hash.value
            or (
                item.size is not None
                and file_metadata.st_size != item.size
            )
        ):
            raise RuntimeError("installed runtime file identity changed")
        records.append(
            [str(item), observed_hash, file_metadata.st_size]
        )
    distributions[name] = {{
        "version": distribution.version,
        "tree_sha256": hashlib.sha256(
            json.dumps(
                records,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
    }}
    if name == "soluprot":
        site = str(distribution.locate_file("").resolve())
print(json.dumps({{
    "python": platform.python_version(),
    "site": site,
    "distributions": distributions,
}}))
"""
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
        or set(identity) != {"python", "site", "distributions"}
        or identity["python"] != SOLUPROT_PYTHON_VERSION
        or not isinstance(identity["site"], str)
        or Path(identity["site"]).resolve() != site_packages_root.resolve()
        or not isinstance(identity["distributions"], dict)
        or identity["distributions"] != SOLUPROT_RUNTIME_DISTRIBUTIONS
    ):
        raise RuntimeError("configured SoluProt Python identity changed")
    return path


def _validate_perl_runtime(path: object) -> Path:
    """Attest the exact interpreter selected by TMHMM's env shebang."""
    if (
        not isinstance(path, Path)
        or path.resolve() != Path("/usr/bin/perl").resolve()
        or not path.is_file()
        or not os.access(path, os.X_OK)
    ):
        raise FileNotFoundError("configured SoluProt Perl is unavailable")
    if _regular_file_sha256(path.resolve(), executable=True) != (
        SOLUPROT_PERL_SHA256
    ):
        raise RuntimeError("configured SoluProt Perl identity changed")
    try:
        completed = subprocess.run(
            [str(path), "-e", "print $^V"],
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
    except (
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as error:
        raise RuntimeError(
            "configured SoluProt Perl identity is unavailable"
        ) from error
    if completed.stdout != SOLUPROT_PERL_VERSION:
        raise RuntimeError("configured SoluProt Perl identity changed")
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
        "runtime_distributions": SOLUPROT_RUNTIME_DISTRIBUTIONS,
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
        payload["perl_version"] = SOLUPROT_PERL_VERSION
        payload["perl_sha256"] = SOLUPROT_PERL_SHA256
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
    perl_executable: Path | None = None
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
        perl_executable = _validate_perl_runtime(
            environment.get("perl_executable")
        )
    return {
        "python_executable": python_path,
        "site_packages_root": site_packages_root,
        "model_json": assets["model_json"],
        "reference_database": assets["reference_database"],
        "usearch_executable": usearch,
        "tmhmm_executable": tmhmm_executable,
        "perl_executable": perl_executable,
        "runtime_distributions": SOLUPROT_RUNTIME_DISTRIBUTIONS,
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
            raise SoluProtProviderOutputContractViolation(
                "SoluProt provider output violated the byte contract"
            )
        chunks: list[bytes] = []
        remaining = metadata.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                raise SoluProtProviderOutputTruncated(
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
            raise SoluProtProviderOutputChanged(
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
    bytecode_path = staging_directory / "bytecode-cache"
    bytecode_path.mkdir(mode=0o700)
    _write_fasta(input_path, sequences)
    command = [
        str(resolved["python_executable"]),
        "-I",
        "-X",
        f"pycache_prefix={bytecode_path}",
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
        raise SoluProtProviderTimeout(
            "SoluProt provider invocation timed out safely"
        ) from error
    if process.returncode != 0:
        raise SoluProtProviderNonzeroExit(
            f"SoluProt provider invocation failed safely "
            f"(exit status {process.returncode})"
        )
    try:
        return _read_provider_output(output_path)
    except OSError as error:
        raise SoluProtProviderOutputUnavailable(
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
            if re.fullmatch(
                r"(?:0(?:\.\d{1,4})?|1(?:\.0{1,4})?)",
                row["soluble"],
            ) is None:
                raise ValueError(
                    "SoluProt output precision does not match the exact contract"
                )
            values.append(value)
    except (csv.Error, TypeError, ValueError) as error:
        if isinstance(error, ValueError) and str(error).startswith("SoluProt"):
            raise
        raise ValueError("SoluProt output contains an invalid value") from error
    if len(values) != expected_count:
        raise ValueError("SoluProt output row count is incomplete")
    return values


def configured_protein_sol_runtime_fingerprint() -> str:
    """Return one path-free identity for Protein-Sol source and runtimes."""
    payload = {
        "schema_namespace": "protein-workbench-protein-sol-runtime/v2",
        "release": PROTEIN_SOL_RELEASE,
        "source_sha256": PROTEIN_SOL_SOURCE_SHA256,
        "bash_version": PROTEIN_SOL_BASH_VERSION,
        "bash_sha256": PROTEIN_SOL_BASH_SHA256,
        "perl_version": PROTEIN_SOL_PERL_VERSION,
        "perl_sha256": PROTEIN_SOL_PERL_SHA256,
    }
    return "sha256:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _validate_executable_runtime(
    path: object,
    *,
    expected_path: Path,
    expected_sha256: str,
    version_command: Sequence[str],
    expected_version: str,
    runtime_name: str,
) -> Path:
    if (
        not isinstance(path, Path)
        or path.resolve() != expected_path.resolve()
        or not path.is_file()
        or not os.access(path, os.X_OK)
    ):
        raise FileNotFoundError(
            f"configured Protein-Sol {runtime_name} is unavailable"
        )
    _require_digest(path.resolve(), expected_sha256, executable=True)
    try:
        completed = subprocess.run(
            [str(path), *version_command],
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
    except (
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as error:
        raise RuntimeError(
            f"configured Protein-Sol {runtime_name} identity is unavailable"
        ) from error
    observed = completed.stdout.splitlines()[0] if completed.stdout else ""
    if observed != expected_version:
        raise RuntimeError(
            f"configured Protein-Sol {runtime_name} identity changed"
        )
    return path


def validate_protein_sol_environment(
    environment: Mapping[str, Any],
) -> dict[str, Any]:
    """Attest the exact upstream dependency tree without executing it."""
    if (
        environment.get("resolved_runtime_fingerprint")
        != configured_protein_sol_runtime_fingerprint()
    ):
        raise RuntimeError("configured Protein-Sol runtime identity changed")
    source_root = environment.get("source_root")
    if (
        not isinstance(source_root, Path)
        or source_root.is_symlink()
        or not source_root.is_dir()
    ):
        raise FileNotFoundError(
            "configured Protein-Sol source root is unavailable"
        )
    sources: dict[str, Path] = {}
    for relative, expected in PROTEIN_SOL_SOURCE_SHA256.items():
        sources[relative] = _require_digest(source_root / relative, expected)
    bash = _validate_executable_runtime(
        environment.get("bash_executable"),
        expected_path=Path("/bin/bash"),
        expected_sha256=PROTEIN_SOL_BASH_SHA256,
        version_command=("--version",),
        expected_version=PROTEIN_SOL_BASH_VERSION,
        runtime_name="Bash",
    )
    perl = _validate_executable_runtime(
        environment.get("perl_executable"),
        expected_path=Path("/usr/bin/perl"),
        expected_sha256=PROTEIN_SOL_PERL_SHA256,
        version_command=("-e", "print $^V"),
        expected_version=PROTEIN_SOL_PERL_VERSION,
        runtime_name="Perl",
    )
    return {
        "source_files": sources,
        "bash_executable": bash,
        "perl_executable": perl,
        "resolved_runtime_fingerprint": (
            configured_protein_sol_runtime_fingerprint()
        ),
    }


def protein_sol_readiness(
    environment: Mapping[str, Any],
) -> ReadinessResult:
    """Observe exact source and interpreter prerequisites for one Run."""
    try:
        validate_protein_sol_environment(environment)
    except (FileNotFoundError, OSError, RuntimeError, ValueError):
        return ReadinessResult(
            False,
            proof_source="direct-observation",
            reason_code="protein_sol_runtime_unavailable",
        )
    return ReadinessResult(True, proof_source="direct-observation")


def validate_protein_sol_sequences(sequences: Sequence[str]) -> None:
    """Reject non-canonical input before crossing the upstream seam."""
    if not sequences:
        raise ValueError("Protein-Sol requires at least one sequence")
    for sequence in sequences:
        if (
            not isinstance(sequence, str)
            or not sequence
            or not set(sequence) <= _CANONICAL_AMINO_ACIDS
        ):
            raise ValueError(
                "Protein-Sol requires non-empty canonical protein sequences"
            )


def _copy_exact_protein_sol_source(
    source: Path,
    destination: Path,
    expected_sha256: str,
) -> None:
    """Copy one verified regular source without following a replacement link."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(source, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ProteinSolProviderOutputContractViolation(
                "Protein-Sol source is not a regular file"
            )
        digest = hashlib.sha256()
        with (
            os.fdopen(descriptor, "rb", closefd=False) as source_handle,
            destination.open("xb") as destination_handle,
        ):
            while chunk := source_handle.read(1024 * 1024):
                digest.update(chunk)
                destination_handle.write(chunk)
        if digest.hexdigest() != expected_sha256:
            raise ProteinSolProviderOutputContractViolation(
                "Protein-Sol source identity changed before invocation"
            )
    finally:
        os.close(descriptor)


def _read_protein_sol_output(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size > 16 * 1024 * 1024
        ):
            raise ProteinSolProviderOutputContractViolation(
                "Protein-Sol output violated the bounded byte contract"
            )
        chunks: list[bytes] = []
        remaining = metadata.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                raise ProteinSolProviderOutputContractViolation(
                    "Protein-Sol output was truncated"
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
            raise ProteinSolProviderOutputContractViolation(
                "Protein-Sol output changed during validation"
            )
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def invoke_protein_sol(
    *,
    sequences: Sequence[str],
    staging_directory: Path,
    environment: Mapping[str, Any],
    run_resources: Any,
    resolved_environment: Mapping[str, Any] | None = None,
) -> bytes:
    """Stage and run only the exact external Protein-Sol dependency."""
    validate_protein_sol_sequences(sequences)
    resolved = (
        dict(resolved_environment)
        if resolved_environment is not None
        else validate_protein_sol_environment(environment)
    )
    source_files = resolved.get("source_files")
    if not isinstance(source_files, Mapping):
        raise RuntimeError("Protein-Sol resolved source identity is incomplete")
    for relative, expected in PROTEIN_SOL_SOURCE_SHA256.items():
        source = source_files.get(relative)
        if not isinstance(source, Path):
            raise RuntimeError(
                "Protein-Sol resolved source identity is incomplete"
            )
        _copy_exact_protein_sol_source(
            source,
            staging_directory / relative,
            expected,
        )
    input_path = staging_directory / "input.fasta"
    _write_fasta(input_path, sequences)
    process = subprocess.Popen(
        [
            str(resolved["bash_executable"]),
            "multiple_prediction_wrapper_export.sh",
            input_path.name,
        ],
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
        raise ProteinSolProviderTimeout(
            "Protein-Sol provider invocation timed out safely"
        ) from error
    if process.returncode != 0:
        raise ProteinSolProviderNonzeroExit(
            "Protein-Sol provider invocation failed safely"
        )
    try:
        return _read_protein_sol_output(
            staging_directory / "seq_prediction.txt"
        )
    except OSError as error:
        raise ProteinSolProviderOutputUnavailable(
            "Protein-Sol provider produced no readable output"
        ) from error


def parse_protein_sol_output(
    payload: bytes,
    *,
    expected_count: int,
) -> list[dict[str, float]]:
    """Decode upstream prediction records without scale inference or clamping."""
    expected_header = (
        "HEADERS PREDICTIONS LINE,ID,percent-sol,scaled-sol,"
        "population-sol,pI"
    )
    try:
        lines = payload.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise ValueError("Protein-Sol output is not valid UTF-8") from error
    prediction_headers = [
        line for line in lines if line.startswith("HEADERS PREDICTIONS")
    ]
    if prediction_headers != [expected_header]:
        raise ValueError(
            "Protein-Sol output prediction header does not match"
        )
    rows = [
        line.split(",")
        for line in lines
        if line.startswith("SEQUENCE PREDICTIONS,")
    ]
    if len(rows) != expected_count:
        raise ValueError("Protein-Sol output row count is incomplete")
    parsed: list[dict[str, float]] = []
    decimal = re.compile(r"\s*-?\d+\.\d{3}\s*")
    ranges = (
        ("percent_sol", 5.208, 113.241),
        ("scaled_sol", 0.0, 1.0),
        ("population_sol", 0.0, 1.0),
        ("pi", 1.0, 14.0),
    )
    for expected_index, row in enumerate(rows):
        if len(row) != 6 or row[0] != "SEQUENCE PREDICTIONS":
            raise ValueError("Protein-Sol output fields do not match")
        if row[1] != f">candidate_{expected_index}":
            raise ValueError(
                "Protein-Sol output identity or ordering is invalid"
            )
        if any(decimal.fullmatch(raw) is None for raw in row[2:]):
            raise ValueError(
                "Protein-Sol values must use finite three-decimal output"
            )
        values = [float(raw) for raw in row[2:]]
        for (_, minimum, maximum), value in zip(
            ranges,
            values,
            strict=True,
        ):
            if not math.isfinite(value) or not minimum <= value <= maximum:
                raise ValueError(
                    "Protein-Sol output is outside its declared range"
                )
        if values[2] != PROTEIN_SOL_POPULATION_SCALED:
            raise ValueError(
                "Protein-Sol population calibration identity changed"
            )
        expected_scaled = (values[0] - 5.208) / (113.241 - 5.208)
        if abs(values[1] - expected_scaled) > 0.00051:
            raise ValueError(
                "Protein-Sol percent and scaled outputs conflict"
            )
        parsed.append(
            {
                name: value
                for (name, _, _), value in zip(
                    ranges,
                    values,
                    strict=True,
                )
            }
        )
    return parsed
