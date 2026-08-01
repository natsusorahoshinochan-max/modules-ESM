"""Provider-native ESMFold2 decoding and static scientific normalization."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import stat
import threading
from typing import Any, Iterable, Protocol

from core import ReadinessResult, RunResources, canonical_sha256
from modules.provider_contract import validate_installed_provider_checkout
from datatypes import ProteinSequence, ProteinStructure


ESM_SDK_REVISION = "917af90b624535eed1e072d343c717e3ec11fef4"
TRANSFORMERS_REVISION = "ef32577f55da19a4989cd7b22e004dc43a4998cb"
TRANSFORMERS_ESMFOLD2_SOURCE_SHA256 = {
    "models/esmfold2/configuration_esmfold2.py": (
        "417d7419d501e7706f715dbfd9b30b61d099c2a16db4bbd15bd322b4bbd52471"
    ),
    "models/esmfold2/modeling_esmfold2.py": (
        "3c36128a70a063aab1278ea2ed1bafbe97787e4c8f5e69639dfb399c96c3f38c"
    ),
}
REMOTE_ESMFOLD2_MODEL = "esmfold2-fast-2026-05"
LOCAL_ESMFOLD2_MODEL = "biohub/ESMFold2"
LOCAL_ESMFOLD2_REVISION = "1ebf0e3481a5184eb6171d40615c79e384b48796"
LOCAL_ESMC_MODEL = "biohub/ESMC-6B"
LOCAL_ESMC_REVISION = "45b0fa5d7fb06faefbd5e3b89bdcef35d564e79a"
LOCAL_DEVICE = "cpu"
LOCAL_TORCH_VERSION = "2.13.0"
LOCAL_ESMFOLD2_ARTIFACT_SHA256 = {
    "ccd.pkl": "9ff44b1927c6b9198e38ffe0928706827a09a350c15530beeeabebfa88038fc5",
    "config.json": "e9ec2496ec433a1dce18627ed4bf3785b4ce0c1d69e4bb4663dad1ab895da012",
    "model.safetensors": (
        "138fd4350d6892b81ce6be7ff9bf5a93ae9d4d3751f46a27438a3f9f0dcefa0e"
    ),
}
LOCAL_ESMC_ARTIFACT_SHA256 = {
    "config.json": "c5566fab6a17fd674141331fe75de917b7904d99fb7a410d2b1593c21e576913",
    "model.safetensors.index.json": (
        "6846456e20e6ee2c37461f7bfc21d316d69bdaf165b925691afcb39e583244da"
    ),
    "model-00001-of-00006.safetensors": (
        "bd90149ff223e6ac1a0cac6147a5ae0df20d3a21df4f65356a1f19cd14f4aa8a"
    ),
    "model-00002-of-00006.safetensors": (
        "f75e2144d8269fe2eb4b3e0823fb089b94f176d8024153e85b8fb573a42294fa"
    ),
    "model-00003-of-00006.safetensors": (
        "f699f01ecc9691d9c6470492765fe54b8b5d2e9f277c139e89427433ffdfe0b2"
    ),
    "model-00004-of-00006.safetensors": (
        "46add1b7be098bbfdc3073884851ba3057f1b33ea23a158b650a37007dabd13d"
    ),
    "model-00005-of-00006.safetensors": (
        "1e1cb62f060a34e18f54a31a76683ef888b8cec59e73315f5b31d25d45a1f88c"
    ),
    "model-00006-of-00006.safetensors": (
        "56c73e13ae96e777ce65eee99364056069ef93b646470f352f83c5f1037b1b18"
    ),
    "special_tokens_map.json": (
        "0b7245ec86c8c3aeaf61523ba70dfa79be137e6283f127bd651adc30b4f15c74"
    ),
    "tokenizer.json": (
        "8d3447b278176e65fb3ef0224472927bf5fee3be46ea2bd77fad0111423cee1f"
    ),
    "tokenizer_config.json": (
        "e8d8e40c9f92b334f0272e80bb65ed4043cb9836523cbae899e9859e8cbb8833"
    ),
}
_PROTEIN_ALPHABET = frozenset("ACDEFGHIKLMNPQRSTVWY")
_LOCAL_CCD_LOCK = threading.Lock()
_LOCAL_CCD_DIGEST: str | None = None
_LOCAL_CCD_OBJECT: object | None = None
_PDB_RESIDUE_TO_ONE = {
    "ALA": "A",
    "ARG": "R",
    "ASN": "N",
    "ASP": "D",
    "CYS": "C",
    "GLN": "Q",
    "GLU": "E",
    "GLY": "G",
    "HIS": "H",
    "ILE": "I",
    "LEU": "L",
    "LYS": "K",
    "MET": "M",
    "PHE": "F",
    "PRO": "P",
    "SER": "S",
    "THR": "T",
    "TRP": "W",
    "TYR": "Y",
    "VAL": "V",
}


def remote_runtime_structurally_available() -> bool:
    if (
        importlib.util.find_spec("esm") is None
        or importlib.util.find_spec("torch") is None
    ):
        return False
    try:
        validate_installed_provider_checkout("esm", ESM_SDK_REVISION)
    except (
        ImportError,
        importlib.metadata.PackageNotFoundError,
        OSError,
        RuntimeError,
        ValueError,
    ):
        return False
    return True


def transformers_esmfold2_runtime_is_exact() -> bool:
    """Verify the installed ESMFold2 source files against one reviewed commit."""
    try:
        distribution = importlib.metadata.distribution("transformers")
        direct_url_text = distribution.read_text("direct_url.json")
        if not direct_url_text:
            return False
        direct_url = json.loads(direct_url_text)
        vcs_info = direct_url.get("vcs_info")
        if (
            direct_url.get("url")
            != "https://github.com/Biohub/transformers.git"
            or not isinstance(vcs_info, dict)
            or vcs_info.get("vcs") != "git"
            or vcs_info.get("commit_id") != TRANSFORMERS_REVISION
        ):
            return False
        package_root_entry = Path(
            distribution.locate_file("transformers")
        )
        if (
            package_root_entry.is_symlink()
            or not package_root_entry.is_dir()
        ):
            return False
        package_root = package_root_entry.resolve(strict=True)
        for relative_path, expected_digest in (
            TRANSFORMERS_ESMFOLD2_SOURCE_SHA256.items()
        ):
            source = package_root / relative_path
            if (
                source.is_symlink()
                or not source.is_file()
                or source.resolve(strict=True).parent
                != (package_root / relative_path).parent.resolve(strict=True)
                or _regular_file_sha256(source) != expected_digest
            ):
                return False
    except (
        ImportError,
        importlib.metadata.PackageNotFoundError,
        json.JSONDecodeError,
        OSError,
        RuntimeError,
        ValueError,
    ):
        return False
    return True


def local_runtime_structurally_available() -> bool:
    if (
        not remote_runtime_structurally_available()
        or importlib.util.find_spec("transformers") is None
        or importlib.util.find_spec(
            "transformers.models.esmfold2.modeling_esmfold2"
        )
        is None
        or not transformers_esmfold2_runtime_is_exact()
    ):
        return False
    try:
        import torch
    except ImportError:
        return False
    return str(torch.__version__) == LOCAL_TORCH_VERSION


def remote_readiness(environment: object) -> bool:
    if not isinstance(environment, Mapping):
        return False
    client = environment.get("provider_client")
    factory = environment.get("client_factory")
    return (
        environment.get("endpoint_id") == "biohub"
        and environment.get("credential_handle") is not None
        and (
            callable(getattr(client, "fold", None))
            or callable(factory)
        )
        and remote_runtime_structurally_available()
    )


@dataclass(frozen=True, slots=True)
class LocalESMFold2Runtime:
    """Readiness-validated local model paths and safe public identity."""

    model_snapshot_path: Path
    language_model_snapshot_path: Path
    runtime_directory: Path
    device: str
    safe_fingerprint: str


def _local_input_builder(
    builder_type: type,
    runtime: LocalESMFold2Runtime,
) -> object:
    """Initialize the ESMFold2 CCD once from the validated local snapshot."""
    from esm.models.esmfold2 import conformers

    return _initialize_local_ccd(conformers, builder_type, runtime)


def _initialize_local_ccd(
    conformers: object,
    builder_type: type,
    runtime: LocalESMFold2Runtime,
) -> object:
    """Reject pre-existing CCD state not initialized by this adapter."""
    expected_digest = LOCAL_ESMFOLD2_ARTIFACT_SHA256["ccd.pkl"]
    global _LOCAL_CCD_DIGEST, _LOCAL_CCD_OBJECT
    with _LOCAL_CCD_LOCK:
        loaded = getattr(conformers, "_CCD_MOLECULES", None)
        if _LOCAL_CCD_DIGEST is None:
            if loaded is not None:
                raise RuntimeError(
                    "ESMFold2 CCD was initialized outside this adapter"
                )
            builder = builder_type(ccd_cache=runtime.model_snapshot_path)
            if getattr(conformers, "_CCD_MOLECULES", None) is None:
                raise RuntimeError("ESMFold2 CCD initialization did not complete")
            _LOCAL_CCD_DIGEST = expected_digest
            _LOCAL_CCD_OBJECT = getattr(conformers, "_CCD_MOLECULES")
            return builder
        if (
            _LOCAL_CCD_DIGEST != expected_digest
            or loaded is None
            or loaded is not _LOCAL_CCD_OBJECT
        ):
            raise RuntimeError("ESMFold2 CCD global identity changed")
        builder = builder_type(ccd_cache=runtime.model_snapshot_path)
        if getattr(conformers, "_CCD_MOLECULES", None) is not _LOCAL_CCD_OBJECT:
            raise RuntimeError("ESMFold2 CCD global identity changed")
        return builder


def configured_local_runtime_fingerprint() -> str:
    """Return the path-free identity required from trusted configuration."""
    return canonical_sha256(
        {
            "schema_namespace": (
                "protein-workbench-local-esmfold2-runtime/v2"
            ),
            "model": LOCAL_ESMFOLD2_MODEL,
            "model_snapshot_revision": LOCAL_ESMFOLD2_REVISION,
            "model_artifact_sha256": dict(
                sorted(LOCAL_ESMFOLD2_ARTIFACT_SHA256.items())
            ),
            "language_model": LOCAL_ESMC_MODEL,
            "language_model_snapshot_revision": LOCAL_ESMC_REVISION,
            "language_model_artifact_sha256": dict(
                sorted(LOCAL_ESMC_ARTIFACT_SHA256.items())
            ),
            "esm_sdk_source_revision": ESM_SDK_REVISION,
            "transformers_source_revision": TRANSFORMERS_REVISION,
            "device": LOCAL_DEVICE,
            "torch_version": LOCAL_TORCH_VERSION,
            "runtime_directory_policy": "binding-scoped-private",
        }
    )


def _configured_directory(
    environment: Mapping[str, object],
    key: str,
) -> Path:
    raw = environment.get(key)
    if not isinstance(raw, (str, os.PathLike)):
        raise RuntimeError(f"local ESMFold2 {key} is not configured")
    path = Path(raw)
    try:
        metadata = path.lstat()
    except OSError as error:
        raise RuntimeError(
            f"local ESMFold2 {key} is unavailable"
        ) from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeError(
            f"local ESMFold2 {key} is not a regular directory"
        )
    return path.resolve(strict=True)


def _regular_file_sha256(path: Path) -> str:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise RuntimeError(
                "required local ESMFold2 artifact is not regular"
            )
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        after = os.fstat(descriptor)
        if (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ) != (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
        ):
            raise RuntimeError(
                "local ESMFold2 artifact changed during validation"
            )
        return digest.hexdigest()
    except OSError as error:
        raise RuntimeError(
            "local ESMFold2 artifact could not be validated"
        ) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _artifact_source(
    snapshot_path: Path,
    relative_path: str,
    expected_digest: str,
) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise RuntimeError("local ESMFold2 artifact path is invalid")
    try:
        parent = snapshot_path
        for component in relative.parts[:-1]:
            parent = parent / component
            metadata = parent.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(
                metadata.st_mode
            ):
                raise RuntimeError(
                    "local ESMFold2 snapshot directory is not regular"
                )
        entry = parent / relative.parts[-1]
        metadata = entry.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            target_value = os.readlink(entry)
            if Path(target_value).is_absolute():
                raise RuntimeError(
                    "local ESMFold2 snapshot link is not repository-contained"
                )
            target = (entry.parent / target_value).resolve(strict=True)
            repository_root = snapshot_path.parent.parent.resolve(strict=True)
            if (
                target.parent != repository_root / "blobs"
                or target.name != expected_digest
            ):
                raise RuntimeError(
                    "local ESMFold2 snapshot link is not repository-contained"
                )
        elif stat.S_ISREG(metadata.st_mode):
            target = entry
        else:
            raise RuntimeError(
                "required local ESMFold2 artifact is not regular"
            )
    except OSError as error:
        raise RuntimeError(
            "local ESMFold2 artifact could not be validated"
        ) from error
    if _regular_file_sha256(target) != expected_digest:
        raise RuntimeError("local ESMFold2 artifact identity mismatch")
    return target


def resolve_local_runtime(
    environment: Mapping[str, object],
) -> LocalESMFold2Runtime:
    """Resolve both immutable snapshots before any local model invocation."""
    if not local_runtime_structurally_available():
        raise RuntimeError("exact local ESMFold2 runtime is unavailable")
    if (
        environment.get("model_snapshot_revision")
        != LOCAL_ESMFOLD2_REVISION
        or environment.get("language_model_snapshot_revision")
        != LOCAL_ESMC_REVISION
    ):
        raise RuntimeError("local ESMFold2 snapshot revision is not exact")
    if environment.get("device") != LOCAL_DEVICE:
        raise RuntimeError("local ESMFold2 device does not match the Binding")
    model_path = _configured_directory(environment, "model_snapshot_path")
    language_path = _configured_directory(
        environment,
        "language_model_snapshot_path",
    )
    runtime_directory = _configured_directory(
        environment,
        "runtime_directory",
    )
    for relative_path, digest in LOCAL_ESMFOLD2_ARTIFACT_SHA256.items():
        _artifact_source(model_path, relative_path, digest)
    for relative_path, digest in LOCAL_ESMC_ARTIFACT_SHA256.items():
        _artifact_source(language_path, relative_path, digest)
    safe_fingerprint = configured_local_runtime_fingerprint()
    if environment.get("resolved_runtime_fingerprint") != safe_fingerprint:
        raise RuntimeError("local ESMFold2 runtime fingerprint is stale")
    return LocalESMFold2Runtime(
        model_snapshot_path=model_path,
        language_model_snapshot_path=language_path,
        runtime_directory=runtime_directory,
        device=LOCAL_DEVICE,
        safe_fingerprint=safe_fingerprint,
    )


def local_readiness(environment: object) -> ReadinessResult:
    """Return a bounded conclusion for exactly one selected local Binding."""
    if not isinstance(environment, Mapping):
        return ReadinessResult(
            False,
            proof_source="direct-observation",
            reason_code="local_runtime_unavailable",
        )
    try:
        resolve_local_runtime(environment)
    except (ImportError, OSError, RuntimeError, ValueError):
        return ReadinessResult(
            False,
            proof_source="direct-observation",
            reason_code="local_runtime_unavailable",
        )
    return ReadinessResult(True, proof_source="direct-observation")


@dataclass(frozen=True, slots=True)
class NormalizedConfidence:
    """Canonical confidence values for one complete structure Candidate."""

    per_residue_plddt: tuple[float | None, ...]
    ptm: float
    pae: tuple[tuple[float, ...], ...]


@dataclass(frozen=True, slots=True)
class DecodedFoldResult:
    """Complete provider result ready for Candidate publication."""

    structure: ProteinStructure
    confidence: NormalizedConfidence


@dataclass(frozen=True, slots=True)
class ESMFold2AdapterResult:
    """Provider-independent result and actual effective call randomness."""

    structure: ProteinStructure
    confidence: NormalizedConfidence
    effective_call_seed: int | None


class ESMFold2Adapter(Protocol):
    """Canonical folding Operation boundary for one exact provider route."""

    def fold(
        self,
        *,
        sequence: ProteinSequence,
        derived_call_seed: int,
        engine_role: str,
    ) -> ESMFold2AdapterResult: ...


def _flat_values(value: object, field: str) -> tuple[object, ...]:
    if value is None:
        raise ValueError(f"{field} is required")
    if callable(getattr(value, "detach", None)):
        value = value.detach()
    if callable(getattr(value, "cpu", None)):
        value = value.cpu()
    if callable(getattr(value, "flatten", None)):
        value = value.flatten()
    if callable(getattr(value, "tolist", None)):
        value = value.tolist()
    if not isinstance(value, (list, tuple)):
        value = (value,)
    return tuple(value)


def _matrix_values(value: object, field: str) -> tuple[tuple[object, ...], ...]:
    if value is None:
        raise ValueError(f"{field} is required")
    if callable(getattr(value, "detach", None)):
        value = value.detach()
    if callable(getattr(value, "cpu", None)):
        value = value.cpu()
    if callable(getattr(value, "tolist", None)):
        value = value.tolist()
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field} must be a residue matrix")
    rows: list[tuple[object, ...]] = []
    for row in value:
        if not isinstance(row, (list, tuple)):
            raise ValueError(f"{field} must be a residue matrix")
        rows.append(tuple(row))
    return tuple(rows)


def _pdb_sequence(pdb_string: str) -> str:
    seen: set[tuple[str, str, str]] = set()
    residues: list[str] = []
    for line in pdb_string.splitlines():
        if not line.startswith("ATOM  ") or len(line) < 27:
            continue
        residue_name = line[17:20].strip().upper()
        residue = _PDB_RESIDUE_TO_ONE.get(residue_name)
        if residue is None:
            raise ValueError(
                "ESMFold2 PDB contains a non-protein ATOM residue"
            )
        key = (line[21:22], line[22:26], line[26:27])
        if key in seen:
            continue
        seen.add(key)
        residues.append(residue)
    if not residues:
        raise ValueError("ESMFold2 PDB contains no complete protein residues")
    return "".join(residues)


def _validated_input_sequence(sequence: ProteinSequence) -> str:
    if type(sequence) is not ProteinSequence:
        raise ValueError("folding input must be a ProteinSequence")
    value = sequence.sequence
    if (
        not value
        or any(symbol not in _PROTEIN_ALPHABET for symbol in value)
        or (
            sequence.residue_ids is not None
            and len(sequence.residue_ids) != len(value)
        )
    ):
        raise ValueError(
            "ESMFold2 requires one complete canonical protein sequence"
        )
    return value


def _provider_pdb_string(result: object, *, local: bool) -> str:
    if local:
        complex_value = getattr(result, "complex", None)
        if complex_value is None:
            raise ValueError("local ESMFold2 result lacks a structure")
        to_protein = getattr(complex_value, "to_protein_complex", None)
        if not callable(to_protein):
            raise ValueError("local ESMFold2 result cannot render PDB")
        protein = to_protein()
    else:
        to_chain = getattr(result, "to_protein_chain", None)
        if not callable(to_chain):
            raise ValueError("remote ESMFold2 result cannot render PDB")
        protein = to_chain()
    infer_oxygen = getattr(protein, "infer_oxygen", None)
    if not callable(infer_oxygen):
        raise ValueError("ESMFold2 result cannot infer oxygen")
    protein = infer_oxygen()
    render = getattr(protein, "to_pdb_string", None)
    if not callable(render):
        raise ValueError("ESMFold2 result cannot render PDB")
    rendered = render()
    if not isinstance(rendered, str):
        raise ValueError("ESMFold2 PDB rendering returned the wrong type")
    return rendered


def decode_remote_fold_result(
    result: object,
    sequence: ProteinSequence,
) -> DecodedFoldResult:
    """Decode one provider-native Biohub ESMProtein result."""
    expected = _validated_input_sequence(sequence)
    try:
        from esm.sdk.api import ESMProteinError
    except ImportError:
        ESMProteinError = ()  # type: ignore[assignment]
    if isinstance(result, ESMProteinError):
        raise RuntimeError("remote ESMFold2 provider returned an error")
    observed = getattr(result, "sequence", None)
    if observed != expected:
        raise ValueError("remote ESMFold2 result sequence is incomplete")
    pdb_string = _provider_pdb_string(result, local=False)
    if _pdb_sequence(pdb_string) != expected:
        raise ValueError("remote ESMFold2 PDB sequence is incomplete")
    confidence = normalize_native_confidence(
        native_plddt=_flat_values(
            getattr(result, "plddt", None),
            "native pLDDT",
        ),
        valid_protein_residues=(True,) * len(expected),
        ptm=getattr(result, "ptm", None),
        pae=_matrix_values(getattr(result, "pae", None), "native PAE"),
    )
    return DecodedFoldResult(
        ProteinStructure(pdb_string),
        confidence,
    )


def decode_local_fold_result(
    result: object,
    sequence: ProteinSequence,
) -> DecodedFoldResult:
    """Decode one provider-native local MolecularComplexResult."""
    expected = _validated_input_sequence(sequence)
    complex_value = getattr(result, "complex", None)
    tokens = getattr(complex_value, "sequence", None)
    if not isinstance(tokens, (list, tuple)) or not tokens:
        raise ValueError("local ESMFold2 result lacks residue identities")
    mask = tuple(
        isinstance(token, str) and token.upper() in _PDB_RESIDUE_TO_ONE
        for token in tokens
    )
    observed = "".join(
        _PDB_RESIDUE_TO_ONE[token.upper()]
        for token, valid in zip(tokens, mask, strict=True)
        if valid
    )
    if observed != expected:
        raise ValueError("local ESMFold2 result sequence is incomplete")
    pdb_string = _provider_pdb_string(result, local=True)
    if _pdb_sequence(pdb_string) != expected:
        raise ValueError("local ESMFold2 PDB sequence is incomplete")
    confidence = normalize_native_confidence(
        native_plddt=_flat_values(
            getattr(result, "plddt", None),
            "native pLDDT",
        ),
        valid_protein_residues=mask,
        ptm=getattr(result, "ptm", None),
        pae=_matrix_values(getattr(result, "pae", None), "native PAE"),
    )
    return DecodedFoldResult(
        ProteinStructure(pdb_string),
        confidence,
    )


def fixed_folding_config() -> Any:
    """Build the Method-fixed remote configuration with complete confidence."""
    from esm.sdk.api import FoldingConfig

    return FoldingConfig(
        include_pae=True,
        include_embeddings=False,
        num_sampling_steps=100,
        num_loops=20,
        lm_dropout=0.3,
        lm_mask_pct=0.1,
        msa_max_depth=1024,
        msa_column_mask_rate=0.1,
    )


def remote_client(environment: Mapping[str, Any]) -> Any:
    client = environment.get("provider_client")
    if callable(getattr(client, "fold", None)):
        return client
    factory = environment.get("client_factory")
    if callable(factory):
        return factory(
            model_name=REMOTE_ESMFOLD2_MODEL,
            endpoint_id=environment["endpoint_id"],
            credential_handle=environment["credential_handle"],
        )
    raise RuntimeError("remote ESMFold2 client is unavailable")


def load_local_engine(
    environment: Mapping[str, Any],
    runtime: LocalESMFold2Runtime,
) -> Any:
    """Load the exact local snapshots only after Readiness has validated them."""
    client = environment.get("provider_client")
    if callable(getattr(client, "fold", None)):
        return client
    factory = environment.get("client_factory")
    if callable(factory):
        return factory(
            model_snapshot_path=runtime.model_snapshot_path,
            language_model_snapshot_path=(
                runtime.language_model_snapshot_path
            ),
            device=runtime.device,
            runtime_directory=runtime.runtime_directory,
        )

    from esm.models.esmfold2 import (
        ESMFold2InputBuilder,
        ProteinInput,
        StructurePredictionInput,
    )
    from transformers.models.esmfold2.configuration_esmfold2 import (
        ESMFold2Config,
    )
    from transformers.models.esmfold2.modeling_esmfold2 import ESMFold2Model

    configuration = ESMFold2Config.from_pretrained(
        runtime.model_snapshot_path,
        local_files_only=True,
    )
    configuration.esmc_id = str(runtime.language_model_snapshot_path)
    model = ESMFold2Model.from_pretrained(
        runtime.model_snapshot_path,
        config=configuration,
        local_files_only=True,
    ).to(runtime.device).eval()
    builder = _local_input_builder(ESMFold2InputBuilder, runtime)

    class LocalEngine:
        def fold(
            self,
            *,
            sequence: str,
            effective_seed: int,
        ) -> object:
            provider_input = StructurePredictionInput(
                sequences=[ProteinInput(id="A", sequence=sequence)]
            )
            return builder.fold(
                model,
                provider_input,
                num_loops=20,
                num_sampling_steps=100,
                num_diffusion_samples=1,
                seed=effective_seed,
                lm_dropout=0.3,
                lm_mask_pct=0.1,
                msa_max_depth=1024,
                msa_column_mask_rate=0.1,
                complex_id="protein-workbench-fold",
            )

    return LocalEngine()


def _finite_number(value: object, field: str) -> float:
    if callable(getattr(value, "detach", None)):
        value = value.detach()
    if callable(getattr(value, "cpu", None)):
        value = value.cpu()
    if callable(getattr(value, "flatten", None)):
        value = value.flatten()
    if callable(getattr(value, "tolist", None)):
        value = value.tolist()
    if isinstance(value, (list, tuple)):
        if len(value) != 1:
            raise ValueError(f"{field} must be scalar")
        value = value[0]
    if (
        type(value) not in {int, float}
        or not math.isfinite(float(value))
    ):
        raise ValueError(f"{field} must be finite")
    return float(value)


def normalize_residue_plddt(
    *,
    native_plddt: Iterable[object],
    valid_residues: Iterable[object],
    native_maximum: float,
    project_to_valid_residues: bool,
) -> tuple[tuple[float | None, ...], float, tuple[int, ...]]:
    """Normalize pLDDT while preserving the declared subject residue axis."""
    native = tuple(native_plddt)
    mask = tuple(valid_residues)
    if len(native) != len(mask) or not native:
        raise ValueError("native pLDDT and residue validity are inconsistent")
    if any(type(valid) is not bool for valid in mask):
        raise ValueError("protein-residue validity must be boolean")
    if native_maximum <= 0 or not math.isfinite(native_maximum):
        raise ValueError("native pLDDT maximum is invalid")

    selected_indices: list[int] = []
    canonical: list[float | None] = []
    for index, (value, valid) in enumerate(zip(native, mask, strict=True)):
        if project_to_valid_residues and not valid:
            continue
        selected_indices.append(index)
        if (
            not valid
            or type(value) not in {int, float}
            or not math.isfinite(float(value))
        ):
            canonical.append(None)
            continue
        native_value = float(value)
        if native_value < 0.0 or native_value > native_maximum:
            raise ValueError(
                f"native pLDDT must remain in [0,{native_maximum:g}]"
            )
        canonical.append(native_value * (100.0 / native_maximum))
    finite_plddt = [value for value in canonical if value is not None]
    if not finite_plddt:
        raise ValueError("native pLDDT has no valid protein residues")
    return (
        tuple(canonical),
        math.fsum(finite_plddt) / len(finite_plddt),
        tuple(selected_indices),
    )


def normalize_native_confidence(
    *,
    native_plddt: Iterable[object],
    valid_protein_residues: Iterable[object],
    ptm: object,
    pae: Iterable[Iterable[object]],
) -> NormalizedConfidence:
    """Convert exact native `[0,1]` ESMFold2 confidence without range guessing."""
    native = tuple(native_plddt)
    mask = tuple(valid_protein_residues)
    canonical, _, selected_indices = normalize_residue_plddt(
        native_plddt=native,
        valid_residues=mask,
        native_maximum=1.0,
        project_to_valid_residues=True,
    )

    ptm_value = _finite_number(ptm, "native pTM")
    if ptm_value < 0.0 or ptm_value > 1.0:
        raise ValueError("native pTM must remain in [0,1]")

    pae_rows = tuple(tuple(row) for row in pae)
    if (
        len(pae_rows) != len(native)
        or any(len(row) != len(native) for row in pae_rows)
    ):
        raise ValueError("native PAE must be a square residue matrix")
    normalized_pae: list[tuple[float, ...]] = []
    for row_index in selected_indices:
        row: list[float] = []
        for column_index in selected_indices:
            value = _finite_number(
                pae_rows[row_index][column_index],
                "native PAE",
            )
            if value < 0.0:
                raise ValueError("native PAE must remain in angstroms")
            row.append(value)
        normalized_pae.append(tuple(row))

    return NormalizedConfidence(
        per_residue_plddt=tuple(canonical),
        ptm=ptm_value,
        pae=tuple(normalized_pae),
    )


class BiohubESMFold2Adapter:
    """Translate one canonical sequence through the exact Biohub route."""

    def __init__(
        self,
        *,
        environment: Mapping[str, Any],
        resources: RunResources,
    ) -> None:
        self._environment = environment
        self._resources = resources
        self._client: Any | None = None

    def _provider_client(self) -> Any:
        if self._client is None:
            self._client = remote_client(self._environment)
        return self._client

    def fold(
        self,
        *,
        sequence: ProteinSequence,
        derived_call_seed: int,
        engine_role: str,
    ) -> ESMFold2AdapterResult:
        """Invoke Biohub once, then admit its raw result outside Invocation."""
        del derived_call_seed
        provider_sequence = _validated_input_sequence(sequence)
        client = self._provider_client()
        config = fixed_folding_config()
        with self._resources.engine_invocation(
            engine_role=engine_role,
            invocation_provenance={
                "effective_randomness": {
                    "control": "provider_uncontrolled",
                }
            },
        ):
            raw_result = client.fold(
                sequence=provider_sequence,
                model_name=REMOTE_ESMFOLD2_MODEL,
                config=config,
            )
        decoded = decode_remote_fold_result(raw_result, sequence)
        return ESMFold2AdapterResult(
            structure=decoded.structure,
            confidence=decoded.confidence,
            effective_call_seed=None,
        )


class LocalESMFold2Adapter:
    """Translate one canonical sequence through the exact local route."""

    def __init__(
        self,
        *,
        environment: Mapping[str, Any],
        resources: RunResources,
    ) -> None:
        self._environment = environment
        self._resources = resources
        self._runtime: LocalESMFold2Runtime | None = None
        self._engine: Any | None = None

    def _provider_engine(
        self,
    ) -> tuple[LocalESMFold2Runtime, Any]:
        if self._runtime is None:
            self._runtime = resolve_local_runtime(self._environment)
        if self._engine is None:
            self._engine = load_local_engine(
                self._environment,
                self._runtime,
            )
        return self._runtime, self._engine

    def fold(
        self,
        *,
        sequence: ProteinSequence,
        derived_call_seed: int,
        engine_role: str,
    ) -> ESMFold2AdapterResult:
        """Invoke the local model once, then admit its raw result."""
        provider_sequence = _validated_input_sequence(sequence)
        _, engine = self._provider_engine()
        with self._resources.engine_invocation(
            engine_role=engine_role,
            invocation_provenance={
                "effective_randomness": {
                    "control": "exact_seed",
                    "effective_seed": derived_call_seed,
                }
            },
        ):
            raw_result = engine.fold(
                sequence=provider_sequence,
                effective_seed=derived_call_seed,
            )
        decoded = decode_local_fold_result(raw_result, sequence)
        return ESMFold2AdapterResult(
            structure=decoded.structure,
            confidence=decoded.confidence,
            effective_call_seed=derived_call_seed,
        )
