"""Direct implementations for structure-annotation Nodes."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from io import StringIO
import math
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping

from Bio.PDB.MMCIF2Dict import MMCIF2Dict

from datatypes import (
    CandidateCollection,
    ExactContractReference,
    PairwiseObservationContext,
    PairwiseParticipant,
    ProteinStructure,
    ResidueLayout,
    ScoreCollection,
    ScoreObservation,
)

from .domain import DSSPAnnotation, StructureAnnotationTrack


_DSSP_SECONDARY = frozenset("GHITEBSP")
_DSSP_CA_COORDINATE_TOLERANCE = 0.0500001
_PDB_RESIDUE_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


@dataclass(frozen=True, slots=True)
class _ParsedStructure:
    layout: ResidueLayout
    residue_names: tuple[str, ...]
    ca_coordinates: tuple[tuple[float, float, float] | None, ...]


@dataclass(frozen=True, slots=True)
class _DSSPRow:
    chain_id: str
    label_seq_id: str
    residue_name: str
    secondary_structure: str
    accessibility: str
    ca_coordinate: tuple[float, float, float]


def _structure_layout(structure: ProteinStructure) -> _ParsedStructure:
    """Derive exact ordered residue identities from one PDB model."""
    if type(structure) is not ProteinStructure:
        raise ValueError("DSSP computation requires one ProteinStructure")
    model_count = sum(
        line.startswith("MODEL ")
        for line in structure.pdb_string.splitlines()
    )
    if model_count > 1:
        raise ValueError("DSSP computation requires a single-model structure")

    residues: list[tuple[str, str]] = []
    residue_names: list[str] = []
    ca_coordinates: list[tuple[float, float, float] | None] = []
    ca_altlocs: list[str | None] = []
    seen: set[tuple[str, str]] = set()
    previous: tuple[str, str] | None = None
    closed_chains: set[str] = set()
    previous_chain: str | None = None
    chain_order: list[str] = []
    for line in structure.pdb_string.splitlines():
        if not line.startswith("ATOM  "):
            continue
        if len(line) < 27:
            raise ValueError("structure contains a truncated ATOM record")
        chain = line[21].strip()
        sequence_label = line[22:26].strip()
        insertion_code = line[26].strip()
        residue_name = line[17:20].strip()
        if (
            len(chain) != 1
            or not chain.isalnum()
            or not sequence_label
            or not residue_name
            or not residue_name.isalpha()
        ):
            raise ValueError(
                "structure residue identity cannot be represented exactly"
            )
        residue_label = f"{sequence_label}{insertion_code}"
        if _PDB_RESIDUE_LABEL.fullmatch(residue_label) is None:
            raise ValueError(
                "structure residue label cannot be represented exactly"
            )
        identity = (chain, residue_label)
        if identity != previous:
            if identity in seen:
                raise ValueError(
                    "structure contains a non-contiguous duplicate residue"
                )
            if chain != previous_chain:
                if chain in closed_chains:
                    raise ValueError(
                        "structure chain boundaries are not contiguous"
                    )
                if previous_chain is not None:
                    closed_chains.add(previous_chain)
                chain_order.append(chain)
                previous_chain = chain
            residues.append(identity)
            residue_names.append(residue_name.upper())
            ca_coordinates.append(None)
            ca_altlocs.append(None)
            seen.add(identity)
            previous = identity
        elif residue_names[-1] != residue_name.upper():
            raise ValueError(
                "structure residue identity has conflicting names"
            )

        if line[12:16].strip() != "CA":
            continue
        altloc = line[16:17].strip()
        if altloc not in {"", "A"}:
            continue
        try:
            coordinate = (
                float(line[30:38]),
                float(line[38:46]),
                float(line[46:54]),
            )
        except ValueError as error:
            raise ValueError(
                "structure contains malformed CA coordinates"
            ) from error
        if not all(math.isfinite(value) for value in coordinate):
            raise ValueError("structure contains non-finite CA coordinates")
        selected_altloc = ca_altlocs[-1]
        if selected_altloc == "" or (
            selected_altloc == "A" and altloc == "A"
        ):
            if ca_coordinates[-1] != coordinate:
                raise ValueError(
                    "structure contains duplicate selected CA coordinates"
                )
            continue
        ca_coordinates[-1] = coordinate
        ca_altlocs[-1] = altloc
    if not residues:
        raise ValueError("structure contains no protein ATOM residues")
    return _ParsedStructure(
        layout=ResidueLayout(
            chain_id=",".join(chain_order),
            length=len(residues),
            residue_ids=[
                f"{chain}:{residue_label}"
                for chain, residue_label in residues
            ],
        ),
        residue_names=tuple(residue_names),
        ca_coordinates=tuple(ca_coordinates),
    )


def _column(
    parsed: Mapping[str, Any],
    name: str,
) -> list[str]:
    value = parsed.get(name)
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list) and all(
        isinstance(item, str) for item in value
    ):
        values = value
    else:
        raise ValueError(f"DSSP output is missing required column {name}")
    if not values:
        raise ValueError(f"DSSP output column {name} is empty")
    return values


def _parse_dssp_rows(text: str) -> tuple[_DSSPRow, ...]:
    """Parse the one shared closed DSSP mmCIF row contract."""
    if not text.lstrip().startswith("data_"):
        text = f"data_structure_annotation\n{text}"
    try:
        parsed = MMCIF2Dict(StringIO(text))
    except Exception as error:
        raise ValueError("DSSP output is malformed mmCIF") from error
    chain_values = _column(
        parsed,
        "_dssp_struct_summary.label_asym_id",
    )
    sequence_values = _column(
        parsed,
        "_dssp_struct_summary.label_seq_id",
    )
    residue_names = _column(
        parsed,
        "_dssp_struct_summary.label_comp_id",
    )
    secondary_values = _column(
        parsed,
        "_dssp_struct_summary.secondary_structure",
    )
    accessibility_values = _column(
        parsed,
        "_dssp_struct_summary.accessibility",
    )
    x_ca_values = _column(parsed, "_dssp_struct_summary.x_ca")
    y_ca_values = _column(parsed, "_dssp_struct_summary.y_ca")
    z_ca_values = _column(parsed, "_dssp_struct_summary.z_ca")
    lengths = {
        len(chain_values),
        len(sequence_values),
        len(residue_names),
        len(secondary_values),
        len(accessibility_values),
        len(x_ca_values),
        len(y_ca_values),
        len(z_ca_values),
    }
    if len(lengths) != 1:
        raise ValueError("DSSP output columns have inconsistent lengths")
    rows: list[_DSSPRow] = []
    for row_index, (
        chain,
        sequence_number,
        residue_name,
        raw_secondary,
        raw_accessibility,
        raw_x_ca,
        raw_y_ca,
        raw_z_ca,
    ) in enumerate(
        zip(
            chain_values,
            sequence_values,
            residue_names,
            secondary_values,
            accessibility_values,
            x_ca_values,
            y_ca_values,
            z_ca_values,
            strict=True,
        )
    ):
        try:
            ca_coordinate = (
                float(raw_x_ca),
                float(raw_y_ca),
                float(raw_z_ca),
            )
        except ValueError as error:
            raise ValueError(
                f"DSSP row {row_index} has malformed CA coordinates"
            ) from error
        if (
            len(chain) != 1
            or not chain.isalnum()
            or not sequence_number
            or not residue_name
            or not residue_name.isalpha()
            or not all(math.isfinite(value) for value in ca_coordinate)
        ):
            raise ValueError(f"DSSP row {row_index} has invalid residue identity")
        rows.append(
            _DSSPRow(
                chain_id=chain,
                label_seq_id=sequence_number,
                residue_name=residue_name.upper(),
                secondary_structure=raw_secondary,
                accessibility=raw_accessibility,
                ca_coordinate=ca_coordinate,
            )
        )
    return tuple(rows)


def _parse_dssp_output(
    text: str,
    *,
    structure: _ParsedStructure,
) -> DSSPAnnotation:
    """Parse DSSP mmCIF and fail closed while reconciling exact residues."""
    layout = structure.layout
    rows = _parse_dssp_rows(text)

    residue_ids = layout.residue_ids or []
    layout_indices_by_identity: dict[tuple[str, str], list[int]] = defaultdict(
        list
    )
    for index, residue_id in enumerate(residue_ids):
        chain, _ = residue_id.split(":", 1)
        coordinate = structure.ca_coordinates[index]
        if coordinate is None:
            continue
        layout_indices_by_identity[
            (chain, structure.residue_names[index])
        ].append(index)
    secondary = ["_"] * layout.length
    sasa: list[float | None] = [None] * layout.length
    mapped: set[int] = set()
    for row_index, row in enumerate(rows):
        candidates = [
            index
            for index in layout_indices_by_identity.get(
                (row.chain_id, row.residue_name),
                (),
            )
            if structure.ca_coordinates[index] is not None
            and all(
                abs(source - observed) <= _DSSP_CA_COORDINATE_TOLERANCE
                for source, observed in zip(
                    structure.ca_coordinates[index] or (),
                    row.ca_coordinate,
                    strict=True,
                )
            )
        ]
        if len(candidates) != 1:
            raise ValueError(
                f"DSSP row {row_index} cannot be reconciled to the structure"
            )
        layout_index = candidates[0]
        if layout_index in mapped:
            raise ValueError(
                f"DSSP row {row_index} duplicates one structure residue"
            )
        mapped.add(layout_index)
        raw_secondary = row.secondary_structure
        if raw_secondary == ".":
            normalized_secondary = "C"
        elif raw_secondary == "?":
            normalized_secondary = "_"
        elif raw_secondary in _DSSP_SECONDARY:
            normalized_secondary = raw_secondary
        else:
            raise ValueError(
                f"DSSP row {row_index} contains an unsupported SS8 symbol"
            )
        secondary[layout_index] = normalized_secondary

        raw_accessibility = row.accessibility
        if raw_accessibility in {".", "?", "_"}:
            accessibility = None
        else:
            try:
                accessibility = float(raw_accessibility)
            except ValueError as error:
                raise ValueError(
                    f"DSSP row {row_index} has malformed accessibility"
                ) from error
            if (
                not math.isfinite(accessibility)
                or accessibility < 0
            ):
                raise ValueError(
                    f"DSSP row {row_index} has invalid accessibility"
                )
        sasa[layout_index] = accessibility
    return DSSPAnnotation(
        layout=layout,
        secondary_structure=tuple(secondary),
        sasa=tuple(sasa),
    )


class StructureAnnotationImplementation:
    """Dispatch one registered operation through the shared implementation."""

    def __init__(
        self,
        run_resources: Any,
        operation: str,
        environment: Mapping[str, Any],
        catalog: Any,
    ) -> None:
        self._run_resources = run_resources
        self._operation = operation
        self._environment = environment
        self._catalog = catalog

    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        if node_parameters or binding_parameters:
            raise ValueError(
                "structure annotation Nodes do not accept parameters"
            )
        if self._operation == "dssp_compute":
            return self._compute_dssp(inputs)
        if self._operation == "secondary_structure_extract":
            return self._extract_secondary_structure(inputs)
        if self._operation == "sasa_compute":
            return self._extract_sasa(inputs)
        if self._operation == "secondary_structure_agreement":
            return self._observe_agreement(inputs)
        raise RuntimeError("unknown structure annotation operation")

    def _compute_dssp(
        self,
        inputs: Mapping[str, Any],
    ) -> dict[str, Any]:
        if set(inputs) != {"structure"}:
            raise ValueError(
                "DSSP computation requires exactly one structure input"
            )
        structure = inputs["structure"]
        parsed_structure = _structure_layout(structure)
        binary = self._environment.get("dssp_binary")
        if not isinstance(binary, str) or not binary:
            raise RuntimeError("the ready mkdssp binary is unavailable")
        timeout = self._environment.get("dssp_timeout_seconds", 30)
        if type(timeout) is not int or not 1 <= timeout <= 300:
            raise ValueError(
                "trusted DSSP timeout must be an integer from 1 to 300"
            )
        with self._run_resources.temporary_directory(
            prefix="structure-annotation-dssp-"
        ) as workspace:
            input_path = Path(workspace) / "input.pdb"
            input_path.write_text(structure.pdb_string, encoding="ascii")
            with self._run_resources.engine_invocation(
                engine_identity="structure_annotation.mkdssp/4.6.1",
            ):
                try:
                    result = subprocess.run(
                        [binary, "--calculate-accessibility", str(input_path)],
                        capture_output=True,
                        timeout=timeout,
                        check=False,
                    )
                except subprocess.TimeoutExpired as error:
                    raise RuntimeError(
                        "mkdssp execution exceeded its trusted timeout"
                    ) from error
                except OSError as error:
                    raise RuntimeError("mkdssp execution could not start") from error
                if result.returncode != 0:
                    raise RuntimeError(
                        f"mkdssp execution failed with exit code "
                        f"{result.returncode}"
                    )
                try:
                    output = result.stdout.decode("utf-8")
                except UnicodeDecodeError as error:
                    raise ValueError(
                        "mkdssp output is not UTF-8 mmCIF"
                    ) from error
            annotation = _parse_dssp_output(
                output,
                structure=parsed_structure,
            )
        return {"annotations": annotation}

    def _annotation_input(
        self,
        inputs: Mapping[str, Any],
    ) -> DSSPAnnotation:
        if set(inputs) != {"annotations"}:
            raise ValueError(
                "annotation extraction requires exactly one annotation input"
            )
        annotation = inputs["annotations"]
        if type(annotation) is not DSSPAnnotation:
            raise ValueError("annotations must be a DSSPAnnotation")
        return annotation

    def _extract_secondary_structure(
        self,
        inputs: Mapping[str, Any],
    ) -> dict[str, Any]:
        annotation = self._annotation_input(inputs)
        with self._run_resources.engine_invocation(
            engine_identity=(
                "structure_annotation.secondary_structure_extract.method/"
                "2.1.0"
            ),
        ):
            track = StructureAnnotationTrack(
                layout=annotation.layout,
                values=tuple(
                    "C" if value == "P" else value
                    for value in annotation.secondary_structure
                ),
            )
        return {"secondary_structure_track": track}

    def _extract_sasa(
        self,
        inputs: Mapping[str, Any],
    ) -> dict[str, Any]:
        annotation = self._annotation_input(inputs)
        with self._run_resources.engine_invocation(
            engine_identity="structure_annotation.sasa_compute.method/2.1.0",
        ):
            track = StructureAnnotationTrack(
                layout=annotation.layout,
                values=annotation.sasa,
            )
        return {"sasa_track": track}

    def _contract_reference(
        self,
        kind: str,
        contract_id: str,
    ) -> ExactContractReference:
        contract = self._catalog.require_contract(
            kind,
            contract_id,
            "2.1.0",
        )
        return ExactContractReference(**contract.reference())

    def _observe_agreement(
        self,
        inputs: Mapping[str, Any],
    ) -> dict[str, Any]:
        if set(inputs) != {
            "subjects",
            "references",
            "expected",
            "observed",
        }:
            raise ValueError(
                "secondary-structure agreement requires subjects, references, "
                "expected, and observed"
            )
        subjects = inputs["subjects"]
        references = inputs["references"]
        expected = inputs["expected"]
        observed = inputs["observed"]
        if (
            type(subjects) is not CandidateCollection
            or len(subjects.items) != 1
            or not subjects.items[0].candidate_id
        ):
            raise ValueError(
                "secondary-structure agreement requires exactly one "
                "identified Candidate"
            )
        if (
            type(references) is not CandidateCollection
            or len(references.items) != 1
            or not references.items[0].candidate_id
        ):
            raise ValueError(
                "secondary-structure agreement requires exactly one "
                "identified reference Candidate"
            )
        if (
            type(expected) is not StructureAnnotationTrack
            or type(observed) is not StructureAnnotationTrack
        ):
            raise ValueError(
                "agreement inputs must be exact structure-annotation tracks"
            )
        if expected.layout != observed.layout:
            raise ValueError(
                "agreement tracks must carry one identical exact layout"
            )
        if (
            len(expected.values) != expected.layout.length
            or len(observed.values) != observed.layout.length
        ):
            raise ValueError("agreement track length contradicts its layout")
        with self._run_resources.engine_invocation(
            engine_identity=(
                "structure_annotation.secondary_structure_agreement.method/"
                "2.1.0"
            ),
        ):
            compared = [
                (expected_value, observed_value)
                for expected_value, observed_value in zip(
                    expected.values,
                    observed.values,
                    strict=True,
                )
                if expected_value != "_" and observed_value != "_"
            ]
            if not compared:
                raise ValueError(
                    "agreement requires at least one present residue pair"
                )
            agreement = sum(
                expected_value == observed_value
                for expected_value, observed_value in compared
            ) / len(compared)
            subject = subjects.items[0]
            reference = references.items[0]
            subject_digest = self._catalog.require_port_type(
                subjects.item_type,
                "2.1.0",
            ).content_digest(subject.data)
            reference_digest = self._catalog.require_port_type(
                references.item_type,
                "2.1.0",
            ).content_digest(reference.data)
            observation = ScoreObservation(
                candidate_id=subject.candidate_id,
                metric=self._contract_reference(
                    "metric",
                    "structure_annotation.secondary_structure_agreement",
                ),
                method=self._contract_reference(
                    "method",
                    (
                        "structure_annotation."
                        "secondary_structure_agreement.method"
                    ),
                ),
                context=PairwiseObservationContext(
                    subject=PairwiseParticipant(
                        role="subject",
                        candidate_id=subject.candidate_id,
                        content_digest=subject_digest,
                    ),
                    reference=PairwiseParticipant(
                        role="reference",
                        candidate_id=reference.candidate_id,
                        content_digest=reference_digest,
                    ),
                    pairing_mode="fixed_reference",
                    normalization="exact-SS8-present-residue",
                ),
                value=agreement,
            )
        return {
            "scores": ScoreCollection(
                collection_id="structure-annotation-agreement",
                entries=[observation],
            )
        }
