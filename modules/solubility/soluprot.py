"""Exact local Adapter for the SoluProt provider."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import csv
from dataclasses import dataclass, field
import io
import json
import os
from pathlib import Path
import platform
import re
import subprocess
from typing import Any, Literal, cast

from core.operation import OperationResources, ReadinessResult
from datatypes.candidate import CandidateDataReference

from ._local_support import (
    SolubilityReadinessUnavailable,
    _provider_sequence_id,
    _require_digest,
    _require_executable,
    _run_local_process,
    _write_fasta,
)
from .domain import SequenceSolubilitySubject


SoluProtMode = Literal["full", "no_tm"]
SOLUPROT_PORT_VERSION = "1.1.0"
SOLUPROT_MINIMUM_PYTHON_VERSION = "3.12"
SOLUPROT_FEATURES_SHA256 = (
    "4dd9252e10efcd033aa8f43d555c05615cf2e6bfa004f77e25277b89219c6281"
)
SOLUPROT_DATABASE_SHA256 = (
    "3b5b2475d3f4ef7cdfd8d0e9d32a31804de8a2ccacc2fac3f4d0506319669bd6"
)
SOLUPROT_USEARCH_VERSION = "12.0"
SOLUPROT_PERL_MINIMUM_MAJOR_VERSION = 5
SOLUPROT_TMHMM_RELATIVE_ROOT = Path("soluprot_assets/tmhmm-2.0d")
SOLUPROT_TMHMM_INCLUDED_DECODERS = (
    "decodeanhmm.Darwin_arm64",
    "decodeanhmm.Linux_x86_64",
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
    "feature_scripts/KMerF.py": (
        "cc039e9b84159a04b121e1fe544adc42976f5bb813f6c1f6e6be5b5919b76c54"
    ),
    "feature_scripts/__init__.py": (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    ),
    "feature_scripts/blast6_to_max_id_csv.py": (
        "d4443fd14a5d10ef2fad68c51eea7a5b76081626368c00d7afd351a6c69162d7"
    ),
    "feature_scripts/common/FastaChunk.py": (
        "4876f7703d617ead4770355408ce6fa8cc077126d193ffb1ed38bf765f2acca9"
    ),
    "feature_scripts/common/__init__.py": (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    ),
    "feature_scripts/common/clear_dir.py": (
        "e3dec4d3237f2e9ae31747b7d6d659e7ec2aa187a99bc8824b7eac35b8be7f0c"
    ),
    "feature_scripts/common/get_abs_path.py": (
        "bd4a770b32ab72841f20af94d6791adabc559a972adccafe85f2b79f9f698e4b"
    ),
    "feature_scripts/common/prefix.py": (
        "38815f505c928263e92e2f08bb7a0fffb908fdf814de43c13f6b2ed3c149883b"
    ),
    "feature_scripts/common/seq_count_fa.py": (
        "f1e01f0579edfb74d1c9cc1279fa2ace0cafd71be3ea4ed49b1201d52591b870"
    ),
    "feature_scripts/dimers_comb.py": (
        "c2ad6c1ff3c1d739d2ec7318d6b0852e95162185be037ae0d15da2e387ecd686"
    ),
    "feature_scripts/physico_chemical.py": (
        "14a5250cd4d557173c81a1447805be9d7327719bcf334794494f727db37562dc"
    ),
    "soluprot_core/__init__.py": (
        "a389af42dbfb872edc074c1f4bfbca95067b3f382aca9d1352c55940d61462c7"
    ),
    "soluprot_core/cli.py": (
        "dbc94f9fc512f1b4cca000520896d49e5bab38b307312fbe2da0fb1f4159dbf5"
    ),
    "soluprot_core/features.py": SOLUPROT_FEATURES_SHA256,
    "soluprot_core/exceptions.py": (
        "d862709150f9e8c123527b07f0f2642bd6739db72397392baf11db3e881ab346"
    ),
    "soluprot_core/model.py": (
        "c15b914967f32a679fd5d99c93c5af8f110410f2a88624a0b28b8bb633d821e1"
    ),
    "soluprot_core/parsers.py": (
        "6899491a5093243443b48920520e2b21ba74e7a02d25f37cf7da7777f54df68c"
    ),
    "soluprot_core/paths.py": (
        "3c9ab062dba9f439c0a5c276aa2670596cb33ac9ee65b8d4e585d23f477f13b2"
    ),
}
SOLUPROT_TMHMM_SHA256 = {
    "bin/tmhmm": (
        "b28ed8ae92966ab1ee76fbe63ce4498abbb17f2cb9c07af01325b8f0388a33c8"
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
    python_path = _require_executable(
        path,
        provider_name="SoluProt Python",
    )
    probe = """
import importlib.metadata as metadata
import json
import sys

site = str(metadata.distribution("soluprot").locate_file("").resolve())
print(json.dumps({
    "python": list(sys.version_info[:3]),
    "site": site,
    "soluprot": metadata.version("soluprot"),
}))
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
                "PATH": os.defpath,
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
        tuple(identity["python"][:2]) < (3, 12)
        or Path(identity["site"]).resolve() != site_packages_root.resolve()
        or identity["soluprot"] != SOLUPROT_PORT_VERSION
    ):
        raise SolubilityReadinessUnavailable(
            "configured SoluProt Python identity changed"
        )
    return python_path


def _validate_perl_runtime(path: Path) -> Path:
    """Require a portable Perl 5 runtime selected by TMHMM's env shebang."""
    if path.name != "perl":
        raise SolubilityReadinessUnavailable(
            "configured SoluProt Perl command is unavailable"
        )
    perl_path = _require_executable(
        path,
        provider_name="SoluProt Perl",
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
                "PATH": os.defpath,
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
    match = re.fullmatch(r"v(?P<major>\d+)(?:\.\d+)+", completed.stdout)
    if (
        match is None
        or int(match.group("major")) < SOLUPROT_PERL_MINIMUM_MAJOR_VERSION
    ):
        raise SolubilityReadinessUnavailable(
            "configured SoluProt Perl identity changed"
        )
    return perl_path


def _validate_usearch_runtime(path: Path) -> Path:
    usearch_path = _require_executable(
        path,
        provider_name="SoluProt USEARCH",
    )
    try:
        completed = subprocess.run(
            [str(usearch_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
            env={
                "HOME": os.devnull,
                "LANG": "C",
                "LC_ALL": "C",
                "PATH": os.defpath,
            },
        )
    except (
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as error:
        raise SolubilityReadinessUnavailable(
            "configured SoluProt USEARCH runtime is unavailable"
        ) from error
    banner = f"{completed.stdout}\n{completed.stderr}"
    if re.search(
        rf"(?m)^usearch v{re.escape(SOLUPROT_USEARCH_VERSION)}(?:\s|$)",
        banner,
    ) is None:
        raise SolubilityReadinessUnavailable(
            "configured SoluProt USEARCH version changed"
        )
    return usearch_path


def _validate_tmhmm_runtime(root: Path) -> None:
    for relative, expected in SOLUPROT_TMHMM_SHA256.items():
        _require_digest(
            root / relative,
            expected,
            executable=relative.startswith("bin/"),
        )
    decoder = (
        root
        / "bin"
        / f"decodeanhmm.{platform.system()}_{platform.machine()}"
    )
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
    """Validate one Binding's exact assets without importing/loading a model."""
    python_executable = cast(Path, environment["python_executable"])
    site_packages_root = cast(Path, environment["site_packages_root"])
    usearch_executable = cast(Path, environment["usearch_executable"])
    _validate_python_runtime(
        python_executable,
        site_packages_root=site_packages_root,
    )
    for relative, expected in SOLUPROT_CODE_SHA256.items():
        _require_digest(site_packages_root / relative, expected)
    assets = _site_asset_paths(site_packages_root, mode)
    _require_digest(assets["model_json"], SOLUPROT_MODEL_SHA256[mode])
    _require_digest(assets["model_arrays"], SOLUPROT_MODEL_TREES_SHA256[mode])
    _require_digest(assets["reference_database"], SOLUPROT_DATABASE_SHA256)
    _validate_usearch_runtime(usearch_executable)
    if mode == "full":
        tmhmm_root = site_packages_root / SOLUPROT_TMHMM_RELATIVE_ROOT
        _validate_tmhmm_runtime(tmhmm_root)
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
        site_packages_root / SOLUPROT_TMHMM_RELATIVE_ROOT
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
                        (resolved.perl_executable.parent,)
                        if resolved.perl_executable is not None
                        else ()
                    ),
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
