"""Exact existing-structure SimpleFold confidence engine boundary."""

from __future__ import annotations

import gc
import importlib
import importlib.util
import json
import os
import pickle
import sys
from argparse import Namespace
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from functools import partial
from pathlib import Path
from typing import Any, cast, Protocol, TypedDict

from core.operation import (
    OperationResources,
    ReadinessResult,
)
from core.local_torch_device import (
    expected_local_torch_device,
    local_torch_device_is_available,
)
from datatypes.structure import (
    ResolvedStructureResidueAxis,
    StructureAxisSegment,
)

from . import simplefold_contract
from .domain import normalize_residue_plddt
from .simplefold_asset_closure import (
    BoundSimpleFoldProviderAssetClosure,
    SimpleFoldAssetClosureAdmissionError,
    admit_simplefold_provider_asset_closure,
    bind_simplefold_provider_asset_closure,
)
from .simplefold_runtime import (
    _load_reviewed_plddt_models,
    _restore_process_cwd,
    _setup_simplefold_imports,
)


class _SimpleFoldConfidenceNativeResult(TypedDict):
    native_plddt: list[float]
    valid_protein_residues: list[bool]


@dataclass(frozen=True, slots=True)
class SimpleFoldConfidenceAdapterResult:
    """Canonical pLDDT values admitted from one provider invocation."""

    per_residue_plddt: tuple[float | None, ...]


class SimpleFoldConfidenceAdapter(Protocol):
    """Resolved-axis existing-structure confidence Operation boundary."""

    def evaluate(
        self,
        *,
        residue_axis: ResolvedStructureResidueAxis,
        engine_role: str,
    ) -> SimpleFoldConfidenceAdapterResult: ...


def simplefold_confidence_runtime_structurally_available() -> bool:
    """Probe package structure without probing or loading any model asset."""
    return not (
        importlib.util.find_spec("simplefold") is None
        or importlib.util.find_spec("torch") is None
    )


def simplefold_confidence_readiness(
    environment: Mapping[str, Any],
) -> ReadinessResult:
    if not simplefold_confidence_runtime_structurally_available():
        return ReadinessResult(
            False,
            proof_source="direct-observation",
            reason_code="simplefold_confidence_runtime_unavailable",
        )
    expected_device = expected_local_torch_device()
    import torch

    if not local_torch_device_is_available(torch, expected_device):
        return ReadinessResult(
            False,
            proof_source="direct-observation",
            reason_code="simplefold_confidence_runtime_unavailable",
        )
    try:
        admit_simplefold_provider_asset_closure(
            simplefold_contract.SIMPLEFOLD_CONFIDENCE_ASSET_CLOSURE,
            environment,
        )
    except SimpleFoldAssetClosureAdmissionError:
        return ReadinessResult(
            False,
            proof_source="direct-observation",
            reason_code="simplefold_confidence_runtime_unavailable",
        )
    return ReadinessResult(True, proof_source="direct-observation")


def _load_representation_only_esm2(
    source_root: Path,
    model_path: Path,
) -> tuple[Any, Any]:
    """Load ESM2 representations without opening contact-regression weights."""
    import torch

    prior_esm_modules = {
        module_name: module
        for module_name, module in tuple(sys.modules.items())
        if module_name == "esm" or module_name.startswith("esm.")
    }
    for module_name in prior_esm_modules:
        sys.modules.pop(module_name, None)
    source_entry = str(source_root)
    sys.path.insert(0, source_entry)
    importlib.invalidate_caches()
    try:
        pretrained = importlib.import_module("esm.pretrained")
        with torch.serialization.safe_globals([Namespace]):
            model_data = torch.load(
                str(model_path),
                map_location="cpu",
                weights_only=True,
            )
        return pretrained.load_model_and_alphabet_core(
            model_path.stem,
            model_data,
            None,
        )[:2]
    finally:
        if source_entry in sys.path:
            sys.path.remove(source_entry)
        for module_name in tuple(sys.modules):
            if module_name == "esm" or module_name.startswith("esm."):
                sys.modules.pop(module_name, None)
        sys.modules.update(prior_esm_modules)


def _provider_chain_ids(
    segments: tuple[StructureAxisSegment, ...],
) -> tuple[str, ...]:
    reserved = {
        segment.chain_id.strip()
        for segment in segments
        if segment.chain_id.strip()
    }
    assigned: list[str] = []
    used: set[str] = set()
    for segment in segments:
        chain_id = segment.chain_id.strip()
        if not chain_id or chain_id in used:
            chain_id = next(
                (
                    candidate
                    for candidate in (
                        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                        "abcdefghijklmnopqrstuvwxyz"
                        "0123456789"
                    )
                    if candidate not in reserved and candidate not in used
                ),
                "",
            )
            if not chain_id:
                raise ValueError(
                    "SimpleFold confidence cannot assign a blank chain"
                )
            reserved.add(chain_id)
        assigned.append(chain_id)
        used.add(chain_id)
    return tuple(assigned)


def _segment_sequences(
    residue_axis: ResolvedStructureResidueAxis,
) -> tuple[str, ...]:
    residue_ids = cast(tuple[str, ...], residue_axis.layout.residue_ids)
    sequence_by_residue = dict(
        zip(residue_ids, residue_axis.sequence, strict=True)
    )
    return tuple(
        "".join(
            sequence_by_residue[residue_id]
            for residue_id in segment.residue_ids
        )
        for segment in residue_axis.segments
    )


def _coordinates_by_residue(
    residue_axis: ResolvedStructureResidueAxis,
) -> dict[str, dict[str, tuple[float, float, float]]]:
    return {
        residue.residue_id: {
            atom.atom_name: atom.coordinate
            for atom in residue.atom_coordinates
        }
        for residue in residue_axis.residue_coordinates
    }


@dataclass(slots=True)
class ActivatedSimpleFoldConfidence:
    """The two serial scientific engines of one confidence call."""

    provider_directory: Path
    model_directory: Path
    residue_axis: ResolvedStructureResidueAxis
    structure_file: Path
    record_file: Path
    const_module: Any
    tokenizer: Any
    featurizer: Any
    processor: Any
    process_one_inference_structure: Any
    esm_model: Any
    esm_dict: Any
    af2_to_esm: Any
    torch_device: Any
    torch_module: Any
    numpy_module: Any
    batch: Any = field(init=False)
    provider_structure: Any = field(init=False)
    latent_module: Any = field(init=False)
    output_module: Any = field(init=False)

    @_restore_process_cwd
    def prepare_inputs(self) -> None:
        """Run the ESM2 feature engine and release its resident model."""
        os.chdir(self.provider_directory)
        try:
            self.batch, self.provider_structure, _ = (
                self.process_one_inference_structure(
                    self.structure_file,
                    self.record_file,
                    self.tokenizer,
                    self.featurizer,
                    self.processor,
                    self.esm_model,
                    self.esm_dict,
                    self.af2_to_esm,
                )
            )
        finally:
            self.esm_model = None
            self.esm_dict = None
            self.af2_to_esm = None
            gc.collect()

    @_restore_process_cwd
    def activate_final_models(self) -> None:
        """Load the confidence models after ESM2 is released."""
        os.chdir(self.provider_directory)
        plddt_models = _load_reviewed_plddt_models(
            self.model_directory,
            self.torch_device,
        )
        self.latent_module = plddt_models["plddt_latent_module"]
        self.output_module = plddt_models["plddt_out_module"]

    @_restore_process_cwd
    def invoke(self) -> _SimpleFoldConfidenceNativeResult:
        """Enter the already-activated confidence engine once."""
        os.chdir(self.provider_directory)
        residue_ids = cast(
            tuple[str, ...],
            self.residue_axis.layout.residue_ids,
        )
        input_coordinates = _coordinates_by_residue(self.residue_axis)
        batch = self.batch
        provider_structure = self.provider_structure
        raw_coordinates = self.torch_module.zeros_like(batch["coords"])
        atom_mask = self.torch_module.zeros_like(
            batch["atom_resolved_mask"],
            dtype=self.torch_module.bool,
        )
        valid_residue_mask = list(self.residue_axis.ca_coordinate_mask)
        for residue_index, residue in enumerate(provider_structure.residues):
            atom_start = int(residue["atom_idx"])
            atom_count = int(residue["atom_num"])
            supplied = input_coordinates[residue_ids[residue_index]]
            for atom_index in range(atom_start, atom_start + atom_count):
                encoded_name = provider_structure.atoms[atom_index]["name"]
                atom_name = "".join(
                    chr(int(value) + 32)
                    for value in encoded_name
                    if int(value) != 0
                )
                coordinate = supplied.get(atom_name)
                if coordinate is None:
                    continue
                raw_coordinates[0, atom_index] = self.torch_module.tensor(
                    coordinate,
                    device=raw_coordinates.device,
                    dtype=raw_coordinates.dtype,
                )
                atom_mask[0, atom_index] = True
        center = raw_coordinates[0, atom_mask[0]].mean(dim=0)
        raw_coordinates[0, atom_mask[0]] -= center
        batch["coords"] = raw_coordinates / 16.0
        batch["atom_resolved_mask"] = atom_mask.to(
            batch["atom_resolved_mask"].dtype
        )
        token_valid = (
            batch["token_pad_mask"].bool()
            & batch["token_resolved_mask"].bool()
            & (
                batch["mol_type"]
                == self.const_module.chain_type_ids["PROTEIN"]
            )
        )
        supplied_valid = self.torch_module.zeros_like(token_valid)
        supplied_valid[0, : len(valid_residue_mask)] = (
            self.torch_module.tensor(
                valid_residue_mask,
                device=supplied_valid.device,
            )
        )
        token_valid &= supplied_valid
        with self.torch_module.inference_mode():
            t = self.torch_module.ones(
                batch["coords"].shape[0],
                device=batch["coords"].device,
            )
            latent = self.latent_module(batch["coords"], t, batch)
            direct = self.output_module(
                latent["latent"].detach(),
                batch,
            )["plddt"]
        native = direct.detach().cpu().numpy().reshape(-1)
        valid = token_valid.detach().cpu().numpy().reshape(-1)
        return {
            "native_plddt": [
                float(value)
                for value in self.numpy_module.asarray(native).tolist()
            ],
            "valid_protein_residues": [
                bool(value)
                for value in self.numpy_module.asarray(valid).tolist()
            ],
        }


@_restore_process_cwd
def activate_existing_structure_confidence(
    *,
    residue_axis: ResolvedStructureResidueAxis,
    staging_directory: Path,
    bound_closure: BoundSimpleFoldProviderAssetClosure,
    device: str,
) -> ActivatedSimpleFoldConfidence:
    """Import SimpleFold, load ESM2, and prepare its fixed request."""
    import numpy as np
    import torch

    model_dir = bound_closure.group_root("simplefold_models")
    esm2_model_dir = bound_closure.group_root("esm2_models")
    esm2_source_root = bound_closure.group_root("esm2_source")
    _setup_simplefold_imports()
    provider_directory = Path.cwd()
    from simplefold.boltz_data_pipeline import const
    from simplefold.boltz_data_pipeline.feature.featurizer import (
        BoltzFeaturizer,
    )
    from simplefold.boltz_data_pipeline.parse.fasta import parse_fasta
    from simplefold.boltz_data_pipeline.tokenize.boltz_protein import (
        BoltzTokenizer,
    )
    from simplefold.processor.protein_processor import ProteinDataProcessor
    from simplefold.utils.datamodule_utils import (
        process_one_inference_structure,
    )
    from simplefold.utils.esm_utils import _af2_to_esm, esm_registry

    esm_registry["esm2_3B"] = partial(
        _load_representation_only_esm2,
        esm2_source_root,
        esm2_model_dir / "esm2_t36_3B_UR50D.pt",
    )
    cache = staging_directory / "confidence-input"
    output_dir = staging_directory / "confidence-features"
    cache.mkdir(mode=0o700)
    output_dir.mkdir(mode=0o700)
    torch_device = torch.device(device)
    esm_model, esm_dict = esm_registry["esm2_3B"]()
    esm_model = esm_model.to(torch_device).eval()
    af2_to_esm = _af2_to_esm(esm_dict).to(torch_device)
    fasta_path = cache / "existing.fasta"
    fasta_path.write_text(
        "".join(
            f">{chain_id}|Protein\n{sequence}\n"
            for chain_id, sequence in zip(
                _provider_chain_ids(residue_axis.segments),
                _segment_sequences(residue_axis),
                strict=True,
            )
        )
    )
    with (model_dir / "ccd.pkl").open("rb") as handle:
        ccd = pickle.load(handle)
    target = parse_fasta(fasta_path, ccd)
    for chain in target.record.chains:
        chain.msa_id = -1
    structure_dir = output_dir / "structures"
    record_dir = output_dir / "records"
    structure_dir.mkdir()
    record_dir.mkdir()
    structure_file = structure_dir / f"{target.record.id}.npz"
    record_file = record_dir / f"{target.record.id}.json"
    target.structure.dump(structure_file)
    record_file.write_text(
        json.dumps(asdict(target.record), sort_keys=True)
    )
    return ActivatedSimpleFoldConfidence(
        provider_directory=provider_directory,
        model_directory=model_dir,
        residue_axis=residue_axis,
        structure_file=structure_file,
        record_file=record_file,
        const_module=const,
        tokenizer=BoltzTokenizer(),
        featurizer=BoltzFeaturizer(),
        processor=ProteinDataProcessor(
            device=torch_device,
            scale=16.0,
            ref_scale=5.0,
            multiplicity=1,
            inference_multiplicity=1,
            backend="torch",
        ),
        process_one_inference_structure=process_one_inference_structure,
        esm_model=esm_model,
        esm_dict=esm_dict,
        af2_to_esm=af2_to_esm,
        torch_device=torch_device,
        torch_module=torch,
        numpy_module=np,
    )


class LocalSimpleFoldConfidenceAdapter:
    """Translate one resolved structure axis through the confidence head."""

    def __init__(
        self,
        *,
        environment: Mapping[str, Any],
        resources: OperationResources,
    ) -> None:
        self._environment = environment
        self._resources = resources

    def evaluate(
        self,
        *,
        residue_axis: ResolvedStructureResidueAxis,
        engine_role: str,
    ) -> SimpleFoldConfidenceAdapterResult:
        """Invoke ESM2 then confidence and normalize outside Invocation."""
        with (
            self._resources.local_provider("simplefold-confidence"),
            self._resources.temporary_directory(
                prefix="simplefold-confidence-"
            ) as staging_directory,
        ):
            bound_closure = bind_simplefold_provider_asset_closure(
                simplefold_contract.SIMPLEFOLD_CONFIDENCE_ASSET_CLOSURE,
                self._environment,
            )
            activated = activate_existing_structure_confidence(
                residue_axis=residue_axis,
                staging_directory=staging_directory,
                bound_closure=bound_closure,
                device=expected_local_torch_device(),
            )
            with self._resources.engine_invocation(
                engine_role=f"{engine_role}_esm2_features",
            ):
                activated.prepare_inputs()
            activated.activate_final_models()
            with self._resources.engine_invocation(
                engine_role=engine_role,
            ):
                raw_result = activated.invoke()
            values, _, _ = normalize_residue_plddt(
                native_plddt=raw_result["native_plddt"],
                valid_residues=raw_result[
                    "valid_protein_residues"
                ],
                native_maximum=1.0,
                project_to_valid_residues=False,
            )
        return SimpleFoldConfidenceAdapterResult(
            per_residue_plddt=values,
        )
