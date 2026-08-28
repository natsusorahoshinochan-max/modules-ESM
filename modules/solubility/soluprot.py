"""Local Adapter for the SoluProt provider."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import csv
from dataclasses import dataclass, field
import io
from pathlib import Path
import platform
from typing import Any, Literal, cast

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


SoluProtMode = Literal["full", "no_tm"]
SOLUPROT_PROCESS_TIMEOUT_SECONDS: float = 300.0
SOLUPROT_TMHMM_RELATIVE_ROOT = Path("soluprot_assets/tmhmm-2.0d")
SOLUPROT_TMHMM_DECODER_FILE = (
    f"bin/decodeanhmm.{platform.system()}_{platform.machine()}"
)
SOLUPROT_TMHMM_FILES = (
    "bin/tmhmm",
    "bin/tmhmmformat.pl",
    SOLUPROT_TMHMM_DECODER_FILE,
    "lib/TMHMM2.0.model",
    "lib/TMHMM2.0.options",
)
SOLUPROT_PROVIDER_SOURCE_FILES = (
    "soluprot_core/__init__.py",
    "soluprot_core/cli.py",
    "soluprot_core/exceptions.py",
    "soluprot_core/features.py",
    "soluprot_core/model.py",
    "soluprot_core/parsers.py",
    "soluprot_core/paths.py",
    "feature_scripts/__init__.py",
    "feature_scripts/blast6_to_max_id_csv.py",
)
_SOLUPROT_MODULE_DRIVER = (
    "import sys;"
    "sys.path.insert(0,sys.argv.pop(1));"
    "from soluprot_core.cli import main;"
    "raise SystemExit(main())"
)


@dataclass(frozen=True, slots=True)
class SoluProtPrediction:
    """One SoluProt value associated with its exact admitted subject."""

    subject: CandidateDataReference
    soluble_probability: float


class SoluProtProviderNonzeroExit(RuntimeError):
    """The provider returned a nonzero status without retaining raw output."""


def _validate_tmhmm_runtime(root: Path) -> None:
    for relative in SOLUPROT_TMHMM_FILES:
        _require_file(root / relative)
    _require_executable(
        root / "bin" / "tmhmm",
        provider_name="SoluProt TMHMM",
    )
    _require_executable(
        root / "bin" / "tmhmmformat.pl",
        provider_name="SoluProt TMHMM formatter",
    )
    decoder = root / SOLUPROT_TMHMM_DECODER_FILE
    _require_executable(decoder, provider_name="SoluProt TMHMM decoder")


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
    """Check one Binding's configured paths without loading a model."""
    python_executable = cast(Path, environment["python_executable"])
    site_packages_root = cast(Path, environment["site_packages_root"])
    usearch_executable = cast(Path, environment["usearch_executable"])
    _require_executable(python_executable, provider_name="SoluProt Python")
    if not site_packages_root.is_dir():
        raise SolubilityReadinessUnavailable(
            "configured SoluProt package root is unavailable"
        )
    for relative in SOLUPROT_PROVIDER_SOURCE_FILES:
        _require_file(
            site_packages_root / relative,
            provider_name="SoluProt source",
        )
    assets = _site_asset_paths(site_packages_root, mode)
    for path in assets.values():
        _require_file(path)
    _require_executable(usearch_executable, provider_name="SoluProt USEARCH")
    if mode == "full":
        tmhmm_root = site_packages_root / SOLUPROT_TMHMM_RELATIVE_ROOT
        _validate_tmhmm_runtime(tmhmm_root)
        perl_executable = cast(Path, environment["perl_executable"])
        _require_executable(
            perl_executable,
            provider_name="SoluProt Perl",
        )


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
    site_packages_root: Path
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
        site_packages_root / SOLUPROT_TMHMM_RELATIVE_ROOT
        if mode == "full"
        else None
    )
    return _TrustedSoluProtEnvironment(
        python_executable=cast(Path, environment["python_executable"]),
        site_packages_root=site_packages_root,
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
    if mode == "full":
        (staging_directory / "perl").symlink_to(
            cast(Path, resolved_environment.perl_executable)
        )
    _write_fasta(input_path, sequences)
    command = [
        str(resolved_environment.python_executable),
        "-I",
        "-X",
        f"pycache_prefix={bytecode_path}",
        "-c",
        _SOLUPROT_MODULE_DRIVER,
        str(resolved_environment.site_packages_root),
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
        with (
            self.resources.local_provider("soluprot"),
            self.resources.temporary_directory(
                prefix=f"soluprot-{self.mode}-"
            ) as staging_directory,
        ):
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
                    path_entries=(
                        (staging_directory,)
                        if resolved.perl_executable is not None
                        else ()
                    ),
                    timeout_seconds=SOLUPROT_PROCESS_TIMEOUT_SECONDS,
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
