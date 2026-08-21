"""Concrete local Adapters for the exact sequence-solubility providers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import csv
from dataclasses import dataclass, field
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
from typing import Any, Literal, cast

from core import ReadinessResult, RunResources
from datatypes import ProteinSequence


SoluProtMode = Literal["full", "no_tm"]
SOLUPROT_PORT_VERSION = "1.1.0"
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
SOLUPROT_RUNTIME_VERSIONS = {
    "soluprot": SOLUPROT_PORT_VERSION,
    "numpy": "2.5.1",
    "pandas": "3.0.3",
    "biopython": "1.87",
    "tqdm": "4.68.4",
    "python-dateutil": "2.9.0.post0",
    "six": "1.17.0",
}
SOLUPROT_PERL_VERSION = "v5.34.1"
SOLUPROT_PERL_SHA256 = (
    "626702a74f85d2664872f6a7aa9b639306a2035211d442a24ea32ef0d48c8afd"
)
SOLUPROT_MODEL_SHA256 = {
    "full": "20ec7d95ee71b31e1ad8e1ff66ad3b966d675bfcf877196dba1db6a3cbbf7e2b",
    "no_tm": "df7f7b8af235981290b77fab7d2be113a81a3e55f14e81b91837e6d96d8d9e60",
}
SOLUPROT_MODEL_TREES_SHA256 = {
    "full": "f8b9fcd813a1fcf55d7fa75a34f7c2a157d35d8f90fdb6189f86833c8c578097",
    "no_tm": "a6e952856f284b35d6524335eae1042cde585a55460308aa0fcf8b9f505277a8",
}
SOLUPROT_CODE_SHA256 = {
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
PROTEIN_SOL_RELEASE = "2017-10"
PROTEIN_SOL_OFFICIAL_DOWNLOAD_URL = (
    "https://protein-sol.manchester.ac.uk/cgi-bin/utilities/"
    "download_sequence_code.php"
)
PROTEIN_SOL_ARCHIVE_SHA256 = (
    "4df32c61fca53adcb2394a528babd1ad85cb5c551bf7bd1c56d134097fb2b1b8"
)
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
    "a4c638ae036d92d55661de7d50896ec630145acaa3afeb1818ef4fc4e0ee45a7"
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


@dataclass(frozen=True, slots=True)
class SoluProtPrediction:
    """One SoluProt value aligned to its admitted input subject."""

    soluble_probability: float


@dataclass(frozen=True, slots=True)
class ProteinSolPrediction:
    """One aligned Provider result without owning Observation Context."""

    percent_soluble_fraction: float
    scaled_soluble_fraction: float
    isoelectric_point: float


class SoluProtInvocationError(RuntimeError):
    """A path-free provider failure safe for durable public diagnostics."""


class SoluProtProviderTimeout(SoluProtInvocationError):
    """The provider exceeded its closed execution budget."""


class SoluProtProviderNonzeroExit(SoluProtInvocationError):
    """The provider returned a nonzero status without retaining raw output."""


class SoluProtProviderOutputUnavailable(SoluProtInvocationError):
    """The provider did not leave one readable output file."""


class ProteinSolInvocationError(RuntimeError):
    """A path-free Protein-Sol failure safe for durable diagnostics."""


class ProteinSolProviderTimeout(ProteinSolInvocationError):
    """The exact upstream invocation exceeded its closed time budget."""


class ProteinSolProviderNonzeroExit(ProteinSolInvocationError):
    """The exact upstream invocation returned a nonzero exit status."""


class ProteinSolProviderOutputUnavailable(ProteinSolInvocationError):
    """The exact upstream invocation produced no readable result."""


def _regular_file_sha256(
    path: object,
    *,
    executable: bool = False,
    provider_name: str = "SoluProt",
) -> str:
    if not isinstance(path, Path) or not path.is_file():
        raise FileNotFoundError(
            f"configured {provider_name} asset is unavailable"
        )
    if executable and not os.access(path, os.X_OK):
        raise FileNotFoundError(
            f"configured {provider_name} executable is unavailable"
        )
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _require_digest(
    path: object,
    expected: str,
    *,
    executable: bool = False,
    provider_name: str = "SoluProt",
) -> Path:
    if (
        _regular_file_sha256(
            path,
            executable=executable,
            provider_name=provider_name,
        )
        != expected
    ):
        raise RuntimeError(
            f"configured {provider_name} asset identity changed"
        )
    return cast(Path, path)


def _validate_python_runtime(
    path: object,
    *,
    site_packages_root: Path,
) -> Path:
    python_path = _require_digest(
        path,
        SOLUPROT_PYTHON_SHA256,
        executable=True,
    )
    distribution_names = tuple(SOLUPROT_RUNTIME_VERSIONS)
    probe = f"""
import importlib.metadata as metadata
import json
import platform

distributions = {{
    name: metadata.version(name)
    for name in {distribution_names!r}
}}
site = str(metadata.distribution("soluprot").locate_file("").resolve())
print(json.dumps({{
    "python": platform.python_version(),
    "site": site,
    "distributions": distributions,
}}))
"""
    try:
        completed = subprocess.run(
            [str(python_path), "-I", "-c", probe],
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
        or identity["distributions"] != SOLUPROT_RUNTIME_VERSIONS
    ):
        raise RuntimeError("configured SoluProt Python identity changed")
    return python_path


def _validate_perl_runtime(path: object) -> Path:
    """Attest the exact interpreter selected by TMHMM's env shebang."""
    if (
        not isinstance(path, Path)
        or path.resolve() != Path("/usr/bin/perl").resolve()
    ):
        raise FileNotFoundError("configured SoluProt Perl is unavailable")
    perl_path = _require_digest(
        path,
        SOLUPROT_PERL_SHA256,
        executable=True,
    )
    try:
        completed = subprocess.run(
            [str(perl_path), "-e", "print $^V"],
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
    return perl_path


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


def validate_soluprot_environment(
    environment: Mapping[str, Any],
    *,
    mode: SoluProtMode,
) -> None:
    """Validate one Binding's exact assets without importing/loading a model."""
    python_executable = environment.get("python_executable")
    wheel_path = environment.get("wheel_path")
    site_packages_root = environment.get("site_packages_root")
    usearch_executable = environment.get("usearch_executable")
    if (
        not isinstance(site_packages_root, Path)
        or not site_packages_root.is_dir()
    ):
        raise FileNotFoundError("configured SoluProt package root is unavailable")
    _validate_python_runtime(
        python_executable,
        site_packages_root=site_packages_root,
    )
    _require_digest(wheel_path, SOLUPROT_SOURCE_SHA256)
    for relative, expected in SOLUPROT_CODE_SHA256.items():
        _require_digest(site_packages_root / relative, expected)
    assets = _site_asset_paths(site_packages_root, mode)
    _require_digest(assets["model_json"], SOLUPROT_MODEL_SHA256[mode])
    _require_digest(assets["model_arrays"], SOLUPROT_MODEL_TREES_SHA256[mode])
    _require_digest(assets["reference_database"], SOLUPROT_DATABASE_SHA256)
    _require_digest(
        usearch_executable,
        SOLUPROT_USEARCH_SHA256,
        executable=True,
    )
    if mode == "full":
        tmhmm_root = environment.get("tmhmm_root")
        if (
            not isinstance(tmhmm_root, Path)
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
        _validate_perl_runtime(environment.get("perl_executable"))


def soluprot_readiness(
    environment: Mapping[str, Any],
    *,
    mode: SoluProtMode,
) -> ReadinessResult:
    """Independently attest one mode without loading either model."""
    try:
        validate_soluprot_environment(environment, mode=mode)
    except (FileNotFoundError, OSError, RuntimeError):
        return ReadinessResult(
            False,
            proof_source="direct-observation",
            reason_code=f"soluprot_{mode}_runtime_unavailable",
        )
    return ReadinessResult(True, proof_source="direct-observation")


@dataclass(frozen=True, slots=True)
class _TrustedSoluProtEnvironment:
    """Runtime paths already admitted by per-run Binding readiness."""

    python_executable: Path
    model_json: Path
    reference_database: Path
    usearch_executable: Path
    tmhmm_executable: Path | None
    perl_executable: Path | None


def _trusted_soluprot_environment(
    environment: Mapping[str, Any],
    *,
    mode: SoluProtMode,
) -> _TrustedSoluProtEnvironment:
    """Project already-admitted environment values without probing again."""
    site_packages_root = cast(Path, environment["site_packages_root"])
    assets = _site_asset_paths(site_packages_root, mode)
    tmhmm_root = (
        cast(Path, environment["tmhmm_root"])
        if mode == "full"
        else None
    )
    return _TrustedSoluProtEnvironment(
        python_executable=cast(Path, environment["python_executable"]),
        model_json=assets["model_json"],
        reference_database=assets["reference_database"],
        usearch_executable=cast(Path, environment["usearch_executable"]),
        tmhmm_executable=(
            tmhmm_root / "bin" / "tmhmm"
            if tmhmm_root is not None
            else None
        ),
        perl_executable=(
            cast(Path, environment["perl_executable"])
            if mode == "full"
            else None
        ),
    )


def _provider_sequence_id(index: int) -> str:
    """Return the exact staged FASTA identity shared with Provider output."""
    return f"candidate_{index}"


def _write_fasta(path: Path, sequences: Sequence[str]) -> None:
    with path.open("x", encoding="ascii", newline="\n") as handle:
        for index, sequence in enumerate(sequences):
            handle.write(f">{_provider_sequence_id(index)}\n{sequence}\n")


def _read_provider_output(path: Path) -> bytes:
    return path.read_bytes()


def _prepare_soluprot_invocation(
    *,
    sequences: Sequence[str],
    mode: SoluProtMode,
    staging_directory: Path,
    resolved_environment: _TrustedSoluProtEnvironment,
) -> tuple[tuple[str, ...], Path]:
    """Stage one exact provider request before its Engine Invocation."""
    input_path = staging_directory / "input.fasta"
    output_path = staging_directory / "output.csv"
    scratch_path = staging_directory / "provider-work"
    scratch_path.mkdir(mode=0o700)
    bytecode_path = staging_directory / "bytecode-cache"
    bytecode_path.mkdir(mode=0o700)
    _write_fasta(input_path, sequences)
    command = [
        str(resolved_environment.python_executable),
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
        str(resolved_environment.model_json),
        "--usearch",
        str(resolved_environment.usearch_executable),
        "--pdb",
        str(resolved_environment.reference_database),
        "--check_unknown",
        "--no_proc",
        "1",
    ]
    if mode == "full":
        command.extend(
            ["--tmhmm", str(resolved_environment.tmhmm_executable)]
        )
    else:
        command.append("--no_tmhmm")
    return tuple(command), output_path


def invoke_soluprot(
    *,
    command: Sequence[str],
    staging_directory: Path,
    run_resources: Any,
) -> None:
    """Run exactly one already-staged SoluProt provider process."""
    process = subprocess.Popen(
        list(command),
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


def parse_soluprot_output(
    payload: bytes,
    *,
    sequence_count: int,
) -> tuple[SoluProtPrediction, ...]:
    """Admit documented SoluProt rows in staged input-subject order."""
    reader = csv.DictReader(
        io.StringIO(payload.decode("utf-8"), newline="")
    )
    probabilities_by_provider_id = {
        row["fa_id"]: float(row["soluble"])
        for row in reader
    }
    return tuple(
        SoluProtPrediction(
            soluble_probability=probabilities_by_provider_id[
                _provider_sequence_id(index)
            ],
        )
        for index in range(sequence_count)
    )


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
    ):
        raise FileNotFoundError(
            f"configured Protein-Sol {runtime_name} is unavailable"
        )
    runtime_path = _require_digest(
        path,
        expected_sha256,
        executable=True,
        provider_name="Protein-Sol",
    )
    try:
        completed = subprocess.run(
            [str(runtime_path), *version_command],
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
    return runtime_path


def validate_protein_sol_environment(
    environment: Mapping[str, Any],
) -> None:
    """Attest the exact upstream dependency tree without executing it."""
    source_root = environment.get("source_root")
    if (
        not isinstance(source_root, Path)
        or not source_root.is_dir()
    ):
        raise FileNotFoundError(
            "configured Protein-Sol source root is unavailable"
        )
    for relative, expected in PROTEIN_SOL_SOURCE_SHA256.items():
        _require_digest(
            source_root / relative,
            expected,
            provider_name="Protein-Sol",
        )
    _validate_executable_runtime(
        environment.get("bash_executable"),
        expected_path=Path("/bin/bash"),
        expected_sha256=PROTEIN_SOL_BASH_SHA256,
        version_command=("--version",),
        expected_version=PROTEIN_SOL_BASH_VERSION,
        runtime_name="Bash",
    )
    _validate_executable_runtime(
        environment.get("perl_executable"),
        expected_path=Path("/usr/bin/perl"),
        expected_sha256=PROTEIN_SOL_PERL_SHA256,
        version_command=("-e", "print $^V"),
        expected_version=PROTEIN_SOL_PERL_VERSION,
        runtime_name="Perl",
    )


def protein_sol_readiness(
    environment: Mapping[str, Any],
) -> ReadinessResult:
    """Observe exact source and interpreter prerequisites for one Run."""
    try:
        validate_protein_sol_environment(environment)
    except (FileNotFoundError, OSError, RuntimeError):
        return ReadinessResult(
            False,
            proof_source="direct-observation",
            reason_code="protein_sol_runtime_unavailable",
        )
    return ReadinessResult(True, proof_source="direct-observation")


@dataclass(frozen=True, slots=True)
class _TrustedProteinSolEnvironment:
    """Runtime paths already admitted by per-run Binding readiness."""

    source_files: Mapping[str, Path]
    bash_executable: Path
    perl_executable: Path


def _trusted_protein_sol_environment(
    environment: Mapping[str, Any],
) -> _TrustedProteinSolEnvironment:
    """Project already-admitted environment values without probing again."""
    source_root = cast(Path, environment["source_root"])
    return _TrustedProteinSolEnvironment(
        source_files={
            relative: source_root / relative
            for relative in PROTEIN_SOL_SOURCE_SHA256
        },
        bash_executable=cast(Path, environment["bash_executable"]),
        perl_executable=cast(Path, environment["perl_executable"]),
    )


def _copy_exact_protein_sol_source(
    source: Path,
    destination: Path,
) -> None:
    """Stage one source already attested by the Adapter boundary."""
    shutil.copyfile(source, destination)


def _read_protein_sol_output(path: Path) -> bytes:
    return path.read_bytes()


def _prepare_protein_sol_invocation(
    *,
    sequences: Sequence[str],
    staging_directory: Path,
    resolved_environment: _TrustedProteinSolEnvironment,
) -> tuple[tuple[str, ...], Path]:
    """Stage one exact Protein-Sol request before its Engine Invocation."""
    for relative in PROTEIN_SOL_SOURCE_SHA256:
        _copy_exact_protein_sol_source(
            resolved_environment.source_files[relative],
            staging_directory / relative,
        )
    input_path = staging_directory / "input.fasta"
    _write_fasta(input_path, sequences)
    return (
        (
            str(resolved_environment.bash_executable),
            "multiple_prediction_wrapper_export.sh",
            input_path.name,
        ),
        staging_directory / "seq_prediction.txt",
    )


def invoke_protein_sol(
    *,
    command: Sequence[str],
    staging_directory: Path,
    run_resources: Any,
) -> None:
    """Run exactly one already-staged Protein-Sol provider process."""
    process = subprocess.Popen(
        list(command),
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


def parse_protein_sol_output(
    payload: bytes,
    *,
    sequence_count: int,
) -> tuple[ProteinSolPrediction, ...]:
    """Admit documented Protein-Sol rows in staged input-subject order."""
    rows = csv.reader(io.StringIO(payload.decode("utf-8"), newline=""))
    values_by_provider_id: dict[str, tuple[float, float, float]] = {}
    for row in rows:
        if not row or row[0] != "SEQUENCE PREDICTIONS":
            continue
        _, _candidate_label, percent, scaled, _population, pi = row
        provider_id = _candidate_label.removeprefix(">")
        values_by_provider_id[provider_id] = (
            float(percent),
            float(scaled),
            float(pi),
        )
    return tuple(
        ProteinSolPrediction(
            *values_by_provider_id[_provider_sequence_id(index)]
        )
        for index in range(sequence_count)
    )


@dataclass(frozen=True, slots=True, eq=False)
class LocalSoluProtAdapter:
    """Translate canonical sequences through one immutable SoluProt mode."""

    mode: SoluProtMode
    environment: Mapping[str, Any] = field(repr=False, compare=False)
    resources: RunResources = field(repr=False, compare=False)

    def predict(
        self,
        sequences: Sequence[ProteinSequence],
    ) -> tuple[SoluProtPrediction, ...]:
        """Run one exact mode and admit ordered scientific predictions."""
        provider_sequences = tuple(sequence.sequence for sequence in sequences)
        resolved = _trusted_soluprot_environment(
            self.environment,
            mode=self.mode,
        )
        with self.resources.temporary_directory(
            prefix=f"soluprot-{self.mode}-"
        ) as staging_directory:
            command, output_path = _prepare_soluprot_invocation(
                sequences=provider_sequences,
                mode=self.mode,
                staging_directory=staging_directory,
                resolved_environment=resolved,
            )
            with self.resources.engine_invocation(
                engine_role=f"soluprot_{self.mode}",
            ):
                invoke_soluprot(
                    command=command,
                    staging_directory=staging_directory,
                    run_resources=self.resources,
                )
            try:
                raw_output = _read_provider_output(output_path)
            except OSError as error:
                raise SoluProtProviderOutputUnavailable(
                    "SoluProt provider produced no readable output"
                ) from error
            values = parse_soluprot_output(
                raw_output,
                sequence_count=len(provider_sequences),
            )
        return values


@dataclass(frozen=True, slots=True, eq=False)
class LocalProteinSolAdapter:
    """Translate canonical sequences through the pinned Protein-Sol runtime."""

    environment: Mapping[str, Any] = field(repr=False, compare=False)
    resources: RunResources = field(repr=False, compare=False)

    def predict(
        self,
        sequences: Sequence[ProteinSequence],
    ) -> tuple[ProteinSolPrediction, ...]:
        """Run and translate ordered Protein-Sol prediction values."""
        provider_sequences = tuple(sequence.sequence for sequence in sequences)
        resolved = _trusted_protein_sol_environment(self.environment)
        with self.resources.temporary_directory(
            prefix="protein-sol-"
        ) as staging_directory:
            command, output_path = _prepare_protein_sol_invocation(
                sequences=provider_sequences,
                staging_directory=staging_directory,
                resolved_environment=resolved,
            )
            with self.resources.engine_invocation(
                engine_role="protein_sol_sequence_prediction",
            ):
                invoke_protein_sol(
                    command=command,
                    staging_directory=staging_directory,
                    run_resources=self.resources,
                )
            try:
                raw_output = _read_protein_sol_output(output_path)
            except OSError as error:
                raise ProteinSolProviderOutputUnavailable(
                    "Protein-Sol provider produced no readable output"
                ) from error
            results = parse_protein_sol_output(
                raw_output,
                sequence_count=len(provider_sequences),
            )
        return results
