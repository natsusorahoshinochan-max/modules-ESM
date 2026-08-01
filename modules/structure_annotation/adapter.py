"""Exact local Adapter for the PDB-REDO mkdssp provider."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from io import StringIO
import math
import os
from pathlib import Path
import re
import subprocess
from typing import Any

from Bio.PDB.MMCIF2Dict import MMCIF2Dict

from core import ReadinessResult, RunResources
from datatypes import ProteinStructure, ResidueLayout

from .domain import DSSPAnnotation


MKDSSP_BINARY = "mkdssp"
MKDSSP_VERSION = "4.6.1"
MKDSSP_SOURCE_REPOSITORY = "PDB-REDO/dssp"
MKDSSP_SOURCE_REVISION = "v4.6.1"
MKDSSP_SOURCE_ARCHIVE_SHA256 = (
    "5ddb8274f03ac0338adffcd661989f515fffb95d40afca404cf2677024256ae3"
)
_DSSP_SECONDARY = frozenset("GHITEBSP")
_DSSP_CA_COORDINATE_TOLERANCE = 0.0500001
_PDB_RESIDUE_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def mkdssp_provider_identity() -> dict[str, str]:
    """Return the exact source and binary identity declared by the Adapter."""
    return {
        "repository": MKDSSP_SOURCE_REPOSITORY,
        "source_revision": MKDSSP_SOURCE_REVISION,
        "source_archive_sha256": MKDSSP_SOURCE_ARCHIVE_SHA256,
        "binary": MKDSSP_BINARY,
        "binary_version": MKDSSP_VERSION,
    }


def mkdssp_readiness(environment: Mapping[str, Any]) -> ReadinessResult:
    """Attest the configured executable without performing annotation work."""
    path = environment.get("dssp_binary")
    if (
        not isinstance(path, str)
        or not path
        or not os.path.isfile(path)
        or not os.access(path, os.X_OK)
    ):
        return ReadinessResult(
            False,
            proof_source="direct-observation",
            reason_code="dssp_binary_unavailable",
        )
    try:
        result = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ReadinessResult(
            False,
            proof_source="direct-observation",
            reason_code="dssp_binary_unavailable",
        )
    version_text = f"{result.stdout}\n{result.stderr}"
    match = re.search(
        r"(?m)^mkdssp version (?P<version>\S+)\s*$",
        version_text,
    )
    if (
        result.returncode != 0
        or match is None
        or match.group("version") != MKDSSP_VERSION
    ):
        return ReadinessResult(
            False,
            proof_source="direct-observation",
            reason_code="dssp_version_mismatch",
        )
    return ReadinessResult(True, proof_source="direct-observation")


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
    """Project one canonical structure onto the exact mkdssp request layout."""
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
    """Parse the closed mkdssp 4.6.1 mmCIF row contract."""
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
    """Admit mkdssp mmCIF while reconciling exact canonical residues."""
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
            if not math.isfinite(accessibility) or accessibility < 0:
                raise ValueError(
                    f"DSSP row {row_index} has invalid accessibility"
                )
        sasa[layout_index] = accessibility
    return DSSPAnnotation(
        layout=layout,
        secondary_structure=tuple(secondary),
        sasa=tuple(sasa),
    )


class MkdsspAdapter:
    """Translate canonical structures through one pinned local provider."""

    def __init__(
        self,
        *,
        environment: Mapping[str, Any],
        resources: RunResources,
    ) -> None:
        self._environment = environment
        self._resources = resources

    def _binary(self) -> str:
        binary = self._environment.get("dssp_binary")
        if not isinstance(binary, str) or not binary:
            raise RuntimeError("the ready mkdssp binary is unavailable")
        return binary

    def _timeout(self) -> int:
        timeout = self._environment.get("dssp_timeout_seconds", 30)
        if type(timeout) is not int or not 1 <= timeout <= 300:
            raise ValueError(
                "trusted DSSP timeout must be an integer from 1 to 300"
            )
        return timeout

    def annotate(self, structure: ProteinStructure) -> DSSPAnnotation:
        """Run mkdssp and return only its admitted canonical annotation."""
        parsed_structure = _structure_layout(structure)
        binary = self._binary()
        timeout = self._timeout()
        with self._resources.temporary_directory(
            prefix="structure-annotation-dssp-"
        ) as workspace:
            input_path = Path(workspace) / "input.pdb"
            input_path.write_text(structure.pdb_string, encoding="ascii")
            with self._resources.engine_invocation():
                try:
                    result = subprocess.run(
                        [
                            binary,
                            "--calculate-accessibility",
                            str(input_path),
                        ],
                        capture_output=True,
                        timeout=timeout,
                        check=False,
                    )
                except subprocess.TimeoutExpired as error:
                    raise RuntimeError(
                        "mkdssp execution exceeded its trusted timeout"
                    ) from error
                except OSError as error:
                    raise RuntimeError(
                        "mkdssp execution could not start"
                    ) from error
                if result.returncode != 0:
                    raise RuntimeError(
                        "mkdssp execution failed with exit code "
                        f"{result.returncode}"
                    )
            try:
                output = result.stdout.decode("utf-8")
            except UnicodeDecodeError as error:
                raise ValueError(
                    "mkdssp output is not UTF-8 mmCIF"
                ) from error
            return _parse_dssp_output(
                output,
                structure=parsed_structure,
            )
