"""Exact local Adapter for the Protein-Sol provider."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import csv
from dataclasses import dataclass, field
import io
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, cast

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
PROTEIN_SOL_PERL_SHA256 = (
    "626702a74f85d2664872f6a7aa9b639306a2035211d442a24ea32ef0d48c8afd"
)
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
class ProteinSolPrediction:
    """One Provider result associated without owning Observation Context."""

    subject: CandidateDataReference
    percent_soluble_fraction: float
    scaled_soluble_fraction: float
    isoelectric_point: float


class ProteinSolProviderNonzeroExit(RuntimeError):
    """The exact upstream invocation returned a nonzero exit status."""


def _validate_executable_runtime(
    path: Path,
    *,
    expected_path: Path,
    expected_sha256: str,
    version_command: Sequence[str],
    expected_version: str,
    runtime_name: str,
) -> Path:
    if (
        path.resolve() != expected_path.resolve()
    ):
        raise SolubilityReadinessUnavailable(
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
        raise SolubilityReadinessUnavailable(
            f"configured Protein-Sol {runtime_name} identity is unavailable"
        ) from error
    observed = completed.stdout.splitlines()[0] if completed.stdout else ""
    if observed != expected_version:
        raise SolubilityReadinessUnavailable(
            f"configured Protein-Sol {runtime_name} identity changed"
        )
    return runtime_path


def _admit_protein_sol_environment(
    environment: Mapping[str, Any],
) -> None:
    """Attest the exact upstream dependency tree without executing it."""
    source_root = cast(Path, environment["source_root"])
    for relative, expected in PROTEIN_SOL_SOURCE_SHA256.items():
        _require_digest(
            source_root / relative,
            expected,
            provider_name="Protein-Sol",
        )
    _validate_executable_runtime(
        cast(Path, environment["bash_executable"]),
        expected_path=Path("/bin/bash"),
        expected_sha256=PROTEIN_SOL_BASH_SHA256,
        version_command=("--version",),
        expected_version=PROTEIN_SOL_BASH_VERSION,
        runtime_name="Bash",
    )
    _validate_executable_runtime(
        cast(Path, environment["perl_executable"]),
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
        _admit_protein_sol_environment(environment)
    except SolubilityReadinessUnavailable:
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


def _prepare_protein_sol_invocation(
    *,
    sequences: Sequence[str],
    staging_directory: Path,
    resolved_environment: _TrustedProteinSolEnvironment,
) -> tuple[tuple[str, ...], Path]:
    """Stage one exact Protein-Sol request before its Engine Invocation."""
    for relative in PROTEIN_SOL_SOURCE_SHA256:
        shutil.copyfile(
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


def parse_protein_sol_output(
    payload: bytes,
    *,
    staged_subjects: Mapping[str, CandidateDataReference],
) -> tuple[ProteinSolPrediction, ...]:
    """Translate documented Protein-Sol identities to exact input subjects."""
    rows = csv.reader(io.StringIO(payload.decode("utf-8"), newline=""))
    predictions: list[ProteinSolPrediction] = []
    for row in rows:
        if not row or row[0] != "SEQUENCE PREDICTIONS":
            continue
        _, _candidate_label, percent, scaled, _population, pi = row
        provider_id = _candidate_label[1:]
        predictions.append(
            ProteinSolPrediction(
                subject=staged_subjects[provider_id],
                percent_soluble_fraction=float(percent),
                scaled_soluble_fraction=float(scaled),
                isoelectric_point=float(pi),
            )
        )
    return tuple(predictions)


@dataclass(frozen=True, slots=True, eq=False)
class LocalProteinSolAdapter:
    """Translate canonical sequences through the pinned Protein-Sol runtime."""

    environment: Mapping[str, Any] = field(repr=False, compare=False)
    resources: OperationResources = field(repr=False, compare=False)

    def predict(
        self,
        subjects: Sequence[SequenceSolubilitySubject],
    ) -> tuple[ProteinSolPrediction, ...]:
        """Run and translate values with exact subject association."""
        with self.resources.local_provider("protein-sol"):
            return self._predict(subjects)

    def _predict(
        self,
        subjects: Sequence[SequenceSolubilitySubject],
    ) -> tuple[ProteinSolPrediction, ...]:
        provider_sequences = tuple(
            subject.sequence.sequence for subject in subjects
        )
        staged_subjects = {
            _provider_sequence_id(index): subject.subject
            for index, subject in enumerate(subjects)
        }
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
                return_code = _run_local_process(
                    command=command,
                    staging_directory=staging_directory,
                    resources=self.resources,
                )
                if return_code != 0:
                    raise ProteinSolProviderNonzeroExit(
                        "Protein-Sol provider invocation failed safely"
                    )
            raw_output = output_path.read_bytes()
            results = parse_protein_sol_output(
                raw_output,
                staged_subjects=staged_subjects,
            )
        return results
