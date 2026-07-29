"""Direct implementations for structure-annotation Nodes."""

from __future__ import annotations

from collections import defaultdict
from io import StringIO
import math
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Mapping

from Bio.PDB.MMCIF2Dict import MMCIF2Dict

from datatypes import (
    CandidateCollection,
    ExactContractReference,
    IntrinsicObservationContext,
    ProteinStructure,
    ResidueLayout,
    ScoreCollection,
    ScoreObservation,
)

from .domain import DSSPAnnotation, StructureAnnotationTrack


_SS8 = frozenset("GHITEBSC")
_PDB_RESIDUE_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def _structure_layout(structure: ProteinStructure) -> ResidueLayout:
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
        if (
            len(chain) != 1
            or not chain.isalnum()
            or not sequence_label
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
        if identity == previous:
            continue
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
        seen.add(identity)
        previous = identity
    if not residues:
        raise ValueError("structure contains no protein ATOM residues")
    return ResidueLayout(
        chain_id=",".join(chain_order),
        length=len(residues),
        residue_ids=[
            f"{chain}:{residue_label}"
            for chain, residue_label in residues
        ],
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


def _parse_dssp_output(
    text: str,
    *,
    layout: ResidueLayout,
) -> DSSPAnnotation:
    """Parse DSSP mmCIF and fail closed while reconciling by chain ordinal."""
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
    secondary_values = _column(
        parsed,
        "_dssp_struct_summary.secondary_structure",
    )
    accessibility_values = _column(
        parsed,
        "_dssp_struct_summary.accessibility",
    )
    lengths = {
        len(chain_values),
        len(sequence_values),
        len(secondary_values),
        len(accessibility_values),
    }
    if len(lengths) != 1:
        raise ValueError("DSSP output columns have inconsistent lengths")

    residue_ids = layout.residue_ids or []
    layout_indices_by_chain: dict[str, list[int]] = defaultdict(list)
    for index, residue_id in enumerate(residue_ids):
        chain, _ = residue_id.split(":", 1)
        layout_indices_by_chain[chain].append(index)
    secondary = ["_"] * layout.length
    sasa: list[float | None] = [None] * layout.length
    mapped: set[int] = set()
    for row_index, (
        chain,
        sequence_number,
        raw_secondary,
        raw_accessibility,
    ) in enumerate(
        zip(
            chain_values,
            sequence_values,
            secondary_values,
            accessibility_values,
            strict=True,
        )
    ):
        try:
            ordinal = int(sequence_number)
        except ValueError as error:
            raise ValueError(
                f"DSSP row {row_index} has an invalid residue ordinal"
            ) from error
        chain_indices = layout_indices_by_chain.get(chain)
        if (
            chain_indices is None
            or ordinal < 1
            or ordinal > len(chain_indices)
        ):
            raise ValueError(
                f"DSSP row {row_index} cannot be reconciled to the structure"
            )
        layout_index = chain_indices[ordinal - 1]
        if layout_index in mapped:
            raise ValueError(
                f"DSSP row {row_index} duplicates one structure residue"
            )
        mapped.add(layout_index)

        if raw_secondary in {".", "-"}:
            normalized_secondary = "C"
        elif raw_secondary in {"_", "?"}:
            normalized_secondary = "_"
        elif raw_secondary in _SS8:
            normalized_secondary = raw_secondary
        else:
            raise ValueError(
                f"DSSP row {row_index} contains an unsupported SS8 symbol"
            )
        secondary[layout_index] = normalized_secondary

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
        layout = _structure_layout(structure)
        configured = self._environment.get("dssp_binary")
        binary = (
            configured
            if isinstance(configured, str) and configured
            else shutil.which("mkdssp")
        )
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
                        [binary, str(input_path)],
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
            annotation = _parse_dssp_output(output, layout=layout)
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
                "2.0.0"
            ),
        ):
            track = StructureAnnotationTrack(
                layout=annotation.layout,
                values=annotation.secondary_structure,
            )
        return {"secondary_structure_track": track}

    def _extract_sasa(
        self,
        inputs: Mapping[str, Any],
    ) -> dict[str, Any]:
        annotation = self._annotation_input(inputs)
        with self._run_resources.engine_invocation(
            engine_identity="structure_annotation.sasa_compute.method/2.0.0",
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
            "2.0.0",
        )
        return ExactContractReference(**contract.reference())

    def _observe_agreement(
        self,
        inputs: Mapping[str, Any],
    ) -> dict[str, Any]:
        if set(inputs) != {"subjects", "expected", "observed"}:
            raise ValueError(
                "secondary-structure agreement requires subjects, expected, "
                "and observed"
            )
        subjects = inputs["subjects"]
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
                "2.0.0"
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
                context=IntrinsicObservationContext(),
                value=agreement,
            )
        return {
            "scores": ScoreCollection(
                collection_id="structure-annotation-agreement",
                entries=[observation],
            )
        }
