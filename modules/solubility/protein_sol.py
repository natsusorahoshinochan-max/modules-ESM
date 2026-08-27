"""Local Adapter for the Protein-Sol provider."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import csv
from dataclasses import dataclass, field
import io
from pathlib import Path
import shutil
from typing import Any, cast

from core.operation import OperationResources, ReadinessResult
from datatypes.candidate import CandidateDataReference

from ._local_support import (
    SolubilityReadinessUnavailable,
    _provider_sequence_id,
    _require_executable,
    _require_file,
    _run_local_process,
    _write_fasta,
)
from .domain import SequenceSolubilitySubject


PROTEIN_SOL_RELEASE = "2017-10"
PROTEIN_SOL_POPULATION_SCALED = 0.446
PROTEIN_SOL_PROCESS_TIMEOUT_SECONDS: float = 300.0
PROTEIN_SOL_CALIBRATION_CONTEXT = {
    "kind": "calibration",
    "calibration_metric": "population_scaled_solubility",
    "calibration_value": PROTEIN_SOL_POPULATION_SCALED,
    "calibration_unit": "dimensionless",
    "population_id": "niwa_non_membrane_2396",
}
PROTEIN_SOL_SOURCE_FILES = (
    "fasta_seq_reformat_export.pl",
    "multiple_prediction_wrapper_export.sh",
    "profiles_gather_export.pl",
    "seq_compositions_perc_pipeline_export.pl",
    "seq_props_ALL_export.pl",
    "seq_reference_data.txt",
    "server_prediction_seq_export.pl",
    "ss_propensities.txt",
)


@dataclass(frozen=True, slots=True)
class ProteinSolPrediction:
    """One Provider result associated without owning Observation Context."""

    subject: CandidateDataReference
    percent_soluble_fraction: float
    scaled_soluble_fraction: float
    isoelectric_point: float


class ProteinSolProviderNonzeroExit(RuntimeError):
    """The exact upstream invocation returned a nonzero exit status."""


def _admit_protein_sol_environment(
    environment: Mapping[str, Any],
) -> None:
    """Check configured source and interpreter paths without executing them."""
    source_root = cast(Path, environment["source_root"])
    for relative in PROTEIN_SOL_SOURCE_FILES:
        _require_file(
            source_root / relative,
            provider_name="Protein-Sol",
        )
    _require_executable(
        cast(Path, environment["bash_executable"]),
        provider_name="Protein-Sol Bash",
    )
    _require_executable(
        cast(Path, environment["perl_executable"]),
        provider_name="Protein-Sol Perl",
    )


def protein_sol_readiness(
    environment: Mapping[str, Any],
) -> ReadinessResult:
    """Observe configured source and interpreter prerequisites for one Run."""
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
            for relative in PROTEIN_SOL_SOURCE_FILES
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
    for relative in PROTEIN_SOL_SOURCE_FILES:
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
                    path_entries=(resolved.perl_executable.parent,),
                    timeout_seconds=PROTEIN_SOL_PROCESS_TIMEOUT_SECONDS,
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
