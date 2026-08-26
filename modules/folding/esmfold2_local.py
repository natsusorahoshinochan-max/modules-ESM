"""Local ESMFold2 provider translation and lifecycle."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import importlib.util
from pathlib import Path
from typing import Any, cast, Protocol, TYPE_CHECKING

from core.operation import (
    EngineInvocationProvenance,
    InvocationRandomness,
    OperationResources,
    ReadinessResult,
)
from core.local_torch_device import (
    expected_local_torch_device,
    local_torch_device_is_available,
)
from datatypes.sequence import ProteinSequence
from datatypes.structure import ProteinStructure

from .domain import (
    ESMFold2AdapterResult,
    _RenderedProtein,
    _matrix_values,
    _provider_pdb_string,
    _vector_values,
    normalize_native_confidence,
)
from .esmfold2_contract import (
    LOCAL_ESMC_PRECISION,
)

if TYPE_CHECKING:
    import torch


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


class LocalESMFold2RuntimeUnavailable(RuntimeError):
    """The local ESMFold2 runtime is unavailable."""


@dataclass(frozen=True, slots=True)
class LocalESMFold2Runtime:
    """Local model paths admitted by the ESMFold2 Binding."""

    model_snapshot_path: Path
    language_model_snapshot_path: Path
    device: str


class _LocalComplex(Protocol):
    sequence: Iterable[str]

    def to_protein_complex(self) -> _RenderedProtein: ...


class _LocalFoldResult(Protocol):
    complex: _LocalComplex
    plddt: torch.Tensor
    ptm: float
    pae: torch.Tensor


@dataclass(slots=True)
class _LocalEngine:
    model: Any
    builder: Any
    protein_input_type: Any
    structure_prediction_input_type: Any

    def fold(
        self,
        *,
        sequence: str,
        effective_seed: int,
    ) -> object:
        provider_input = self.structure_prediction_input_type(
            sequences=[self.protein_input_type(id="A", sequence=sequence)]
        )
        return self.builder.fold(
            self.model,
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


def local_runtime_structurally_available() -> bool:
    return not (
        importlib.util.find_spec("esm") is None
        or importlib.util.find_spec("esm.models.esmfold2") is None
        or importlib.util.find_spec("torch") is None
        or importlib.util.find_spec("transformers") is None
        or importlib.util.find_spec(
            "transformers.models.esmfold2.modeling_esmfold2"
        )
        is None
    )


def resolve_local_runtime(
    environment: Mapping[str, object],
) -> LocalESMFold2Runtime:
    """Resolve configured model roots before local model invocation."""
    if not local_runtime_structurally_available():
        raise LocalESMFold2RuntimeUnavailable(
            "local ESMFold2 runtime is unavailable"
        )
    import torch

    expected_device = expected_local_torch_device()
    if not local_torch_device_is_available(torch, expected_device):
        raise LocalESMFold2RuntimeUnavailable(
            "local ESMFold2 policy-selected Torch device is unavailable"
        )
    model_path = cast(Path, environment["model_snapshot_path"])
    language_path = cast(Path, environment["language_model_snapshot_path"])
    required_files = (
        model_path / "ccd.pkl",
        model_path / "config.json",
        model_path / "model.safetensors",
        language_path / "config.json",
        language_path / "model.safetensors.index.json",
        language_path / "model-00001-of-00006.safetensors",
        language_path / "model-00002-of-00006.safetensors",
        language_path / "model-00003-of-00006.safetensors",
        language_path / "model-00004-of-00006.safetensors",
        language_path / "model-00005-of-00006.safetensors",
        language_path / "model-00006-of-00006.safetensors",
    )
    if (
        not model_path.is_dir()
        or not language_path.is_dir()
        or any(not path.is_file() for path in required_files)
    ):
        raise LocalESMFold2RuntimeUnavailable(
            "local ESMFold2 model roots are unavailable"
        )
    return LocalESMFold2Runtime(
        model_snapshot_path=model_path,
        language_model_snapshot_path=language_path,
        device=expected_device,
    )


def _trusted_local_runtime(
    environment: Mapping[str, object],
) -> LocalESMFold2Runtime:
    """Read the runtime values already admitted by Binding readiness."""
    return LocalESMFold2Runtime(
        model_snapshot_path=cast(Path, environment["model_snapshot_path"]),
        language_model_snapshot_path=cast(
            Path,
            environment["language_model_snapshot_path"],
        ),
        device=expected_local_torch_device(),
    )


def local_readiness(environment: Mapping[str, Any]) -> ReadinessResult:
    """Return a bounded conclusion for exactly one selected local Binding."""
    try:
        resolve_local_runtime(environment)
    except LocalESMFold2RuntimeUnavailable:
        return ReadinessResult(
            False,
            proof_source="direct-observation",
            reason_code="local_runtime_unavailable",
        )
    return ReadinessResult(True, proof_source="direct-observation")


def decode_local_fold_result(
    result: _LocalFoldResult,
    *,
    effective_call_seed: int,
) -> ESMFold2AdapterResult:
    """Decode one provider-native local MolecularComplexResult."""
    mask = tuple(
        token.upper() in _PDB_RESIDUE_TO_ONE
        for token in result.complex.sequence
    )
    pdb_string = _provider_pdb_string(result.complex.to_protein_complex())
    confidence = normalize_native_confidence(
        native_plddt=_vector_values(result.plddt),
        valid_protein_residues=mask,
        ptm=result.ptm,
        pae=_matrix_values(result.pae),
    )
    return ESMFold2AdapterResult(
        ProteinStructure(pdb_string),
        confidence,
        effective_call_seed,
    )


def load_local_engine(runtime: LocalESMFold2Runtime) -> _LocalEngine:
    """Load the configured local snapshots."""
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
        esmc_precision=LOCAL_ESMC_PRECISION,
    ).to(runtime.device).eval()
    builder = ESMFold2InputBuilder(ccd_cache=runtime.model_snapshot_path)
    return _LocalEngine(
        model=model,
        builder=builder,
        protein_input_type=ProteinInput,
        structure_prediction_input_type=StructurePredictionInput,
    )


class LocalESMFold2Adapter:
    """Translate one canonical sequence through the exact local route."""

    def __init__(
        self,
        *,
        environment: Mapping[str, Any],
        resources: OperationResources,
    ) -> None:
        self._environment = environment
        self._resources = resources

    def _provider_engine(self, state: dict[object, object]) -> _LocalEngine:
        runtime = _trusted_local_runtime(self._environment)
        engine = state.get(runtime)
        if engine is None:
            state.clear()
            engine = load_local_engine(runtime)
            state[runtime] = engine
        return cast(_LocalEngine, engine)

    def fold(
        self,
        *,
        sequence: ProteinSequence,
        derived_call_seed: int,
        engine_role: str,
    ) -> ESMFold2AdapterResult:
        """Invoke the local model once, then admit its raw result."""
        with (
            self._resources.local_provider("local-esmfold2") as state,
            self._resources.engine_invocation(
                engine_role=engine_role,
                invocation_provenance=EngineInvocationProvenance(
                    effective_randomness=InvocationRandomness(
                        control="exact_seed",
                        effective_seed=derived_call_seed,
                    )
                ),
            ),
        ):
            raw_result = self._provider_engine(state).fold(
                sequence=sequence.sequence,
                effective_seed=derived_call_seed,
            )
        return decode_local_fold_result(
            cast(_LocalFoldResult, raw_result),
            effective_call_seed=derived_call_seed,
        )
