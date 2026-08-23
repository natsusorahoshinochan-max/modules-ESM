"""Exact local Adapter for the PDB-REDO mkdssp provider."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from io import StringIO
import os
from pathlib import Path
import re
import subprocess
from typing import Any, cast

from Bio.PDB.MMCIF2Dict import MMCIF2Dict

from core.operation import (
    OperationResources,
    ReadinessResult,
)
from datatypes.candidate import CandidateDataReference
from datatypes.structure import ResolvedStructureResidueAxis

from .domain import DSSPAnnotation


MKDSSP_BINARY = "mkdssp"
MKDSSP_VERSION = "4.6.1"
MKDSSP_SOURCE_REPOSITORY = "PDB-REDO/dssp"
MKDSSP_SOURCE_REVISION = "v4.6.1"
MKDSSP_SOURCE_ARCHIVE_SHA256 = (
    "5ddb8274f03ac0338adffcd661989f515fffb95d40afca404cf2677024256ae3"
)
_DSSP_SECONDARY = frozenset("GHITEBSP")


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
    path = cast(Path, environment["dssp_binary"])
    if (
        not os.path.isfile(path)
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
            check=False,
        )
    except OSError:
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
class _DSSPRow:
    label_asym_id: str
    label_seq_id: str
    secondary_structure: str
    accessibility: str


def _column(
    parsed: Mapping[str, Any],
    name: str,
) -> list[str]:
    value = parsed[name]
    if isinstance(value, str):
        return [value]
    return value


def _parse_dssp_rows(
    parsed: Mapping[str, Any],
) -> tuple[_DSSPRow, ...]:
    """Read trusted mkdssp summary rows in their label namespace."""
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
    rows: list[_DSSPRow] = []
    for (
        chain,
        residue_label,
        raw_secondary,
        raw_accessibility,
    ) in zip(
        chain_values,
        sequence_values,
        secondary_values,
        accessibility_values,
        strict=True,
    ):
        rows.append(
            _DSSPRow(
                label_asym_id=chain,
                label_seq_id=residue_label,
                secondary_structure=raw_secondary,
                accessibility=raw_accessibility,
            )
        )
    return tuple(rows)


def _authored_residue_ids(
    parsed: Mapping[str, Any],
    rows: tuple[_DSSPRow, ...],
) -> dict[tuple[str, str], str]:
    """Join DSSP label identifiers to exact authored PDB identities."""
    summary_keys = {
        (row.label_asym_id, row.label_seq_id)
        for row in rows
    }
    authored_by_label: dict[tuple[str, str], str] = {}
    for (
        label_asym_id,
        label_seq_id,
        auth_asym_id,
        auth_seq_id,
        insertion_code,
    ) in zip(
        _column(parsed, "_atom_site.label_asym_id"),
        _column(parsed, "_atom_site.label_seq_id"),
        _column(parsed, "_atom_site.auth_asym_id"),
        _column(parsed, "_atom_site.auth_seq_id"),
        _column(parsed, "_atom_site.pdbx_PDB_ins_code"),
        strict=True,
    ):
        label_identity = (label_asym_id, label_seq_id)
        if label_identity not in summary_keys:
            continue
        authored_identity = (
            f"{auth_asym_id}:{auth_seq_id}"
            f"{'' if insertion_code in {'.', '?'} else insertion_code}"
        )
        previous = authored_by_label.setdefault(
            label_identity,
            authored_identity,
        )
        if previous != authored_identity:
            raise ValueError(
                "mkdssp atom_site label identity maps to conflicting "
                "authored residue identities"
            )
    return authored_by_label


def _parse_dssp_output(
    text: str,
    *,
    residue_axis: ResolvedStructureResidueAxis,
    subject: CandidateDataReference,
) -> DSSPAnnotation:
    """Admit mkdssp mmCIF while reconciling exact canonical residues."""
    parsed = MMCIF2Dict(StringIO(text))
    layout = residue_axis.layout
    rows = _parse_dssp_rows(parsed)
    authored_by_label = _authored_residue_ids(parsed, rows)
    residue_ids = cast(tuple[str, ...], layout.residue_ids)
    layout_index_by_residue_id = {
        residue_id: index
        for index, residue_id in enumerate(residue_ids)
    }
    secondary = ["_"] * layout.length
    sasa: list[float | None] = [None] * layout.length
    mapped: set[int] = set()
    for row_index, row in enumerate(rows):
        label_identity = (row.label_asym_id, row.label_seq_id)
        residue_id = authored_by_label.get(label_identity)
        if residue_id is None:
            raise ValueError(
                f"DSSP row {row_index} has no atom_site authored residue "
                "identity"
            )
        layout_index = layout_index_by_residue_id.get(residue_id)
        if layout_index is None:
            raise ValueError(
                f"DSSP row {row_index} residue identity is absent from the "
                "authoritative axis"
            )
        if layout_index in mapped:
            raise ValueError(
                f"DSSP row {row_index} duplicates one structure residue"
            )
        mapped.add(layout_index)
        raw_secondary = row.secondary_structure
        normalized_secondary = {
            ".": "C",
            "?": "_",
            **{symbol: symbol for symbol in _DSSP_SECONDARY},
        }[raw_secondary]
        secondary[layout_index] = normalized_secondary

        raw_accessibility = row.accessibility
        if raw_accessibility in {".", "?"}:
            accessibility = None
        else:
            accessibility = float(raw_accessibility)
        sasa[layout_index] = accessibility
    if mapped != set(range(layout.length)):
        raise ValueError(
            "DSSP authored residue identities are not exactly equal to the "
            "authoritative axis layout"
        )
    return DSSPAnnotation(
        subject=subject,
        layout=layout,
        secondary_structure=tuple(secondary),
        sasa=tuple(sasa),
    )


class MkdsspAdapter:
    """Translate authoritative resolved axes through one pinned provider."""

    def __init__(
        self,
        *,
        environment: Mapping[str, Any],
        resources: OperationResources,
    ) -> None:
        self._environment = environment
        self._resources = resources

    def annotate(
        self,
        residue_axis: ResolvedStructureResidueAxis,
        *,
        subject: CandidateDataReference,
    ) -> DSSPAnnotation:
        """Run mkdssp and return only its admitted canonical annotation."""
        binary = self._environment["dssp_binary"]
        with self._resources.temporary_directory(
            prefix="structure-annotation-dssp-"
        ) as workspace:
            input_path = Path(workspace) / "input.pdb"
            input_path.write_text(
                residue_axis.structure.pdb_string,
                encoding="ascii",
            )
            with self._resources.engine_invocation():
                try:
                    result = subprocess.run(
                        [
                            binary,
                            "--calculate-accessibility",
                            str(input_path),
                        ],
                        capture_output=True,
                        check=False,
                    )
                except OSError as error:
                    raise RuntimeError(
                        "mkdssp execution could not start"
                    ) from error
                if result.returncode != 0:
                    raise RuntimeError(
                        "mkdssp execution failed with exit code "
                        f"{result.returncode}"
                    )
            output = result.stdout.decode("utf-8")
            return _parse_dssp_output(
                output,
                residue_axis=residue_axis,
                subject=subject,
            )
