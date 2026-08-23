"""Exact local Adapter for the SoluProt provider."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import csv
from dataclasses import dataclass, field
import io
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Literal, cast

from core.operation import OperationResources, ReadinessResult
from datatypes.candidate import CandidateDataReference

from ._local_support import (
    SolubilityReadinessUnavailable,
    _provider_sequence_id,
    _require_digest,
    _run_local_process,
    _write_fasta,
)
from .domain import SequenceSolubilitySubject


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


@dataclass(frozen=True, slots=True)
class SoluProtPrediction:
    """One SoluProt value associated with its exact admitted subject."""

    subject: CandidateDataReference
    soluble_probability: float


class SoluProtProviderNonzeroExit(RuntimeError):
    """The provider returned a nonzero status without retaining raw output."""


def _validate_python_runtime(
    path: Path,
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
        raise SolubilityReadinessUnavailable(
            "configured SoluProt Python identity is unavailable"
        ) from error
    if (
        identity["python"] != SOLUPROT_PYTHON_VERSION
        or Path(identity["site"]).resolve() != site_packages_root.resolve()
        or identity["distributions"] != SOLUPROT_RUNTIME_VERSIONS
    ):
        raise SolubilityReadinessUnavailable(
            "configured SoluProt Python identity changed"
        )
    return python_path


def _validate_perl_runtime(path: Path) -> Path:
    """Attest the exact interpreter selected by TMHMM's env shebang."""
    if (
        path.resolve() != Path("/usr/bin/perl").resolve()
    ):
        raise SolubilityReadinessUnavailable(
            "configured SoluProt Perl is unavailable"
        )
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
        raise SolubilityReadinessUnavailable(
            "configured SoluProt Perl identity is unavailable"
        ) from error
    if completed.stdout != SOLUPROT_PERL_VERSION:
        raise SolubilityReadinessUnavailable(
            "configured SoluProt Perl identity changed"
        )
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


def _admit_soluprot_environment(
    environment: Mapping[str, Any],
    *,
    mode: SoluProtMode,
) -> None:
    """Validate one Binding's exact assets without importing/loading a model."""
    python_executable = cast(Path, environment["python_executable"])
    wheel_path = cast(Path, environment["wheel_path"])
    site_packages_root = cast(Path, environment["site_packages_root"])
    usearch_executable = cast(Path, environment["usearch_executable"])
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
        tmhmm_root = cast(Path, environment["tmhmm_root"])
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
        _validate_perl_runtime(cast(Path, environment["perl_executable"]))


def soluprot_readiness(
    environment: Mapping[str, Any],
    *,
    mode: SoluProtMode,
) -> ReadinessResult:
    """Independently attest one mode without loading either model."""
    try:
        _admit_soluprot_environment(environment, mode=mode)
    except SolubilityReadinessUnavailable:
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


def parse_soluprot_output(
    payload: bytes,
    *,
    staged_subjects: Mapping[str, CandidateDataReference],
) -> tuple[SoluProtPrediction, ...]:
    """Translate documented SoluProt identities to exact input subjects."""
    reader = csv.DictReader(
        io.StringIO(payload.decode("utf-8"), newline="")
    )
    return tuple(
        SoluProtPrediction(
            subject=staged_subjects[row["fa_id"]],
            soluble_probability=float(row["soluble"]),
        )
        for row in reader
    )


@dataclass(frozen=True, slots=True, eq=False)
class LocalSoluProtAdapter:
    """Translate canonical sequences through one immutable SoluProt mode."""

    mode: SoluProtMode
    environment: Mapping[str, Any] = field(repr=False, compare=False)
    resources: OperationResources = field(repr=False, compare=False)

    def predict(
        self,
        subjects: Sequence[SequenceSolubilitySubject],
    ) -> tuple[SoluProtPrediction, ...]:
        """Run one exact mode and retain exact subject association."""
        provider_sequences = tuple(
            subject.sequence.sequence for subject in subjects
        )
        staged_subjects = {
            _provider_sequence_id(index): subject.subject
            for index, subject in enumerate(subjects)
        }
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
                return_code = _run_local_process(
                    command=command,
                    staging_directory=staging_directory,
                    resources=self.resources,
                )
                if return_code != 0:
                    raise SoluProtProviderNonzeroExit(
                        "SoluProt provider invocation failed safely "
                        f"(exit status {return_code})"
                    )
            raw_output = output_path.read_bytes()
            values = parse_soluprot_output(
                raw_output,
                staged_subjects=staged_subjects,
            )
        return values
