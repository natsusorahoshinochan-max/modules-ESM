"""Provider-free prompt-authoring implementations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import re
from typing import Any

from datatypes import (
    FunctionAnnotations,
    ProteinPrompt,
    ProteinStructure,
    ResidueLayout,
    ResidueTrack,
)

from .annotations import add_function_annotation
from .domain import (
    build_layout,
    build_residue_map,
    map_track,
    override_track,
    TrackKind,
)
from .prompts import (
    assemble_protein_prompt,
    override_protein_prompt_track,
    update_prompt_sequence,
)
from .stochastic import random_insert_masked, random_mask_prompt


_TRACK_PORTS = {
    "sequence_track": TrackKind.SEQUENCE,
    "structure_track": TrackKind.STRUCTURE,
    "visibility_track": TrackKind.VISIBILITY,
    "secondary_structure_track": TrackKind.SECONDARY_STRUCTURE,
    "sasa_track": TrackKind.SASA,
}


class _Implementation:
    def __init__(self, run_resources: Any, operation: str) -> None:
        self._run_resources = run_resources
        self._operation = operation

    def _invocation(self):
        return self._run_resources.engine_invocation(
            engine_identity=(
                f"prompt_authoring.{self._operation}.method/2.0.0"
            ),
        )


class BuildResidueLayoutImplementation(_Implementation):
    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        if inputs or binding_parameters or set(node_parameters) != {"chains"}:
            raise ValueError("layout construction requires only chains")
        with self._invocation():
            layout = build_layout(node_parameters["chains"])
        return {"layout": layout}


class EditResidueLayoutImplementation(_Implementation):
    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        if (
            set(inputs) != {"source_layout", "target_layout"}
            or set(node_parameters) != {"edits"}
            or binding_parameters
        ):
            raise ValueError(
                "residue editing requires source_layout, target_layout, and edits"
            )
        with self._invocation():
            residue_map = build_residue_map(
                inputs["source_layout"],
                inputs["target_layout"],
                node_parameters["edits"],
            )
        return {"residue_map": residue_map}


def _selected_track(
    inputs: Mapping[str, Any],
) -> tuple[str, TrackKind, object]:
    selected = [
        (port, kind, inputs[port])
        for port, kind in _TRACK_PORTS.items()
        if port in inputs
    ]
    if len(selected) != 1:
        raise ValueError("exactly one nominal per-residue track is required")
    return selected[0]


class MapResidueTrackImplementation(_Implementation):
    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        port, kind, track = _selected_track(inputs)
        if (
            set(inputs) != {"residue_map", port}
            or node_parameters
            or binding_parameters
        ):
            raise ValueError(
                "track mapping requires one track and one residue_map"
            )
        with self._invocation():
            converted = map_track(
                track,
                inputs["residue_map"],
                kind=kind,
            )
        return {port: converted}


class OverrideResidueTrackImplementation(_Implementation):
    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        port, kind, track = _selected_track(inputs)
        if (
            set(inputs) != {"target_layout", port}
            or set(node_parameters) != {"overrides"}
            or binding_parameters
        ):
            raise ValueError(
                "track override requires target_layout, one track, and overrides"
            )
        with self._invocation():
            result = override_track(
                track,
                inputs["target_layout"],
                node_parameters["overrides"],
                kind=kind,
            )
        return {port: result}


_AA3_TO_1 = {
    "ALA": "A",
    "CYS": "C",
    "ASP": "D",
    "GLU": "E",
    "PHE": "F",
    "GLY": "G",
    "HIS": "H",
    "ILE": "I",
    "LYS": "K",
    "LEU": "L",
    "MET": "M",
    "ASN": "N",
    "PRO": "P",
    "GLN": "Q",
    "ARG": "R",
    "SER": "S",
    "THR": "T",
    "VAL": "V",
    "TRP": "W",
    "TYR": "Y",
}
_PDB_ATOM_NAME = re.compile(r"^[A-Z0-9][A-Z0-9']{0,3}$")
_PROMPT_ATOMS = frozenset({
    "N",
    "CA",
    "C",
    "CB",
    "O",
    "CG",
    "CG1",
    "CG2",
    "OG",
    "OG1",
    "SG",
    "CD",
    "CD1",
    "CD2",
    "ND1",
    "ND2",
    "OD1",
    "OD2",
    "SD",
    "CE",
    "CE1",
    "CE2",
    "CE3",
    "NE",
    "NE1",
    "NE2",
    "OE1",
    "OE2",
    "CH2",
    "NH1",
    "NH2",
    "OH",
    "CZ",
    "CZ2",
    "CZ3",
    "NZ",
    "OXT",
})


@dataclass
class _StructureResidue:
    residue_id: str
    amino_acid: str
    atoms: dict[str, tuple[float, float, float]] = field(
        default_factory=dict
    )


def _prompt_from_structure(
    structure: object,
) -> tuple[ResidueLayout, ProteinPrompt]:
    if type(structure) is not ProteinStructure:
        raise ValueError("structure must be one complete ProteinStructure")
    residues: list[_StructureResidue] = []
    by_identity: dict[tuple[str, str], _StructureResidue] = {}
    chain_order: list[str] = []
    closed_chains: set[str] = set()
    previous_chain: str | None = None
    for line in structure.pdb_string.splitlines():
        if not line.startswith("ATOM  "):
            continue
        if len(line) < 54:
            raise ValueError("structure contains a truncated PDB atom record")
        alternate = line[16:17].strip()
        if alternate not in {"", "A"}:
            continue
        atom_name = line[12:16].strip()
        if atom_name not in _PROMPT_ATOMS:
            continue
        chain_id = line[21:22].strip()
        residue_number = line[22:26].strip()
        insertion_code = line[26:27].strip()
        residue_name = line[17:20].strip().upper()
        if (
            _PDB_ATOM_NAME.fullmatch(atom_name) is None
            or not chain_id.isalnum()
            or len(chain_id) != 1
            or not residue_number
            or residue_name not in _AA3_TO_1
        ):
            raise ValueError(
                "structure contains an unsupported canonical residue record"
            )
        if chain_id != previous_chain:
            if chain_id in closed_chains:
                raise ValueError("structure chains are not contiguous")
            if previous_chain is not None:
                closed_chains.add(previous_chain)
            chain_order.append(chain_id)
            previous_chain = chain_id
        residue_label = residue_number + insertion_code
        key = (chain_id, residue_label)
        residue = by_identity.get(key)
        if residue is None:
            residue = _StructureResidue(
                residue_id=f"{chain_id}:{residue_label}",
                amino_acid=_AA3_TO_1[residue_name],
            )
            by_identity[key] = residue
            residues.append(residue)
        elif residue.amino_acid != _AA3_TO_1[residue_name]:
            raise ValueError("structure residue identity has conflicting names")
        if atom_name in residue.atoms:
            continue
        try:
            residue.atoms[atom_name] = (
                float(line[30:38]),
                float(line[38:46]),
                float(line[46:54]),
            )
        except ValueError as error:
            raise ValueError(
                "structure contains non-numeric atom coordinates"
            ) from error
    if not residues or any(not residue.atoms for residue in residues):
        raise ValueError("structure contains no complete canonical residues")
    layout = ResidueLayout(
        chain_id=",".join(chain_order),
        length=len(residues),
        residue_ids=[residue.residue_id for residue in residues],
    )
    prompt = ProteinPrompt(
        target_layout=layout,
        sequence_track=ResidueTrack(
            [residue.amino_acid for residue in residues],
            None,
        ),
        structure_track=ResidueTrack(
            [dict(residue.atoms) for residue in residues],
            None,
        ),
        structure_visibility_track=ResidueTrack(
            [True for _ in residues],
            None,
        ),
        secondary_structure_track=ResidueTrack(
            [None for _ in residues],
            None,
        ),
        sasa_track=None,
        function_annotations=FunctionAnnotations(),
    )
    return layout, prompt


class PromptFromStructureImplementation(_Implementation):
    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        if (
            set(inputs) != {"structure"}
            or node_parameters
            or binding_parameters
        ):
            raise ValueError(
                "prompt construction requires one structure and no parameters"
            )
        with self._invocation():
            layout, prompt = _prompt_from_structure(inputs["structure"])
        return {"layout": layout, "protein_prompt": prompt}


class OverrideProteinPromptTrackImplementation(_Implementation):
    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        if (
            set(inputs) != {"protein_prompt"}
            or set(node_parameters) != {"track", "overrides"}
            or binding_parameters
        ):
            raise ValueError(
                "prompt track override requires one Prompt and exact overrides"
            )
        with self._invocation():
            prompt = override_protein_prompt_track(
                inputs["protein_prompt"],
                track=node_parameters["track"],
                overrides=node_parameters["overrides"],
            )
        return {"protein_prompt": prompt}


class AssembleProteinPromptImplementation(_Implementation):
    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        allowed_inputs = {"layout", "function_annotations", *_TRACK_PORTS}
        if (
            "layout" not in inputs
            or not set(inputs) <= allowed_inputs
            or node_parameters
            or binding_parameters
        ):
            raise ValueError(
                "prompt assembly accepts only layout and declared optional tracks"
            )
        tracks = {
            name: inputs[name]
            for name in _TRACK_PORTS
            if name in inputs
        }
        with self._invocation():
            prompt = assemble_protein_prompt(
                inputs["layout"],
                tracks,
                inputs.get("function_annotations"),
            )
        return {"protein_prompt": prompt}


class AddFunctionAnnotationImplementation(_Implementation):
    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        if (
            set(inputs) not in (
                {"layout"},
                {"layout", "existing_annotations"},
            )
            or set(node_parameters) != {"annotation", "overlap_policy"}
            or binding_parameters
        ):
            raise ValueError(
                "function annotation requires layout, annotation, overlap_policy, "
                "and optional existing_annotations"
            )
        with self._invocation():
            annotations = add_function_annotation(
                inputs["layout"],
                inputs.get("existing_annotations"),
                node_parameters["annotation"],
                overlap_policy=node_parameters["overlap_policy"],
            )
        return {"function_annotations": annotations}


class UpdatePromptSequenceImplementation(_Implementation):
    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        if (
            set(inputs) != {"protein_prompt", "sequence"}
            or node_parameters
            or binding_parameters
        ):
            raise ValueError(
                "sequence update requires only protein_prompt and sequence"
            )
        with self._invocation():
            prompt = update_prompt_sequence(
                inputs["protein_prompt"],
                inputs["sequence"],
            )
        return {"protein_prompt": prompt}


class RandomMaskImplementation(_Implementation):
    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        if (
            set(inputs) != {"protein_prompt"}
            or set(node_parameters)
            != {
                "effective_seed",
                "count",
                "track",
                "eligible_residue_ids",
            }
            or binding_parameters
        ):
            raise ValueError(
                "random masking requires one ProteinPrompt and resolved randomness"
            )
        with self._invocation():
            prompt = random_mask_prompt(
                inputs["protein_prompt"],
                effective_seed=node_parameters["effective_seed"],
                count=node_parameters["count"],
                track=node_parameters["track"],
                eligible_residue_ids=node_parameters["eligible_residue_ids"],
            )
        return {"protein_prompt": prompt}


class RandomInsertMaskedImplementation(_Implementation):
    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        if (
            set(inputs) != {"protein_prompt"}
            or set(node_parameters)
            != {
                "effective_seed",
                "count",
                "eligible_chain_ids",
            }
            or binding_parameters
        ):
            raise ValueError(
                "masked insertion requires one ProteinPrompt and resolved randomness"
            )
        with self._invocation():
            prompt, residue_map = random_insert_masked(
                inputs["protein_prompt"],
                effective_seed=node_parameters["effective_seed"],
                count=node_parameters["count"],
                eligible_chain_ids=node_parameters["eligible_chain_ids"],
            )
        return {
            "protein_prompt": prompt,
            "residue_map": residue_map,
        }
