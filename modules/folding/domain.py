"""Provider-independent ESMFold2 results and confidence normalization."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import math
from typing import Protocol, TYPE_CHECKING

from datatypes.sequence import ProteinSequence
from datatypes.structure import ProteinStructure

if TYPE_CHECKING:
    import torch


@dataclass(frozen=True, slots=True)
class NormalizedConfidence:
    """Canonical confidence values for one complete structure Candidate."""

    per_residue_plddt: tuple[float | None, ...]
    ptm: float
    pae: tuple[tuple[float, ...], ...]


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


class _RenderedProtein(Protocol):
    def infer_oxygen(self) -> _RenderedProtein: ...

    def to_pdb_string(self) -> str: ...


def _vector_values(value: torch.Tensor) -> tuple[float, ...]:
    return tuple(float(item) for item in value.detach().cpu().tolist())


def _matrix_values(value: torch.Tensor) -> tuple[tuple[float, ...], ...]:
    return tuple(
        tuple(float(item) for item in row)
        for row in value.detach().cpu().tolist()
    )


def _provider_pdb_string(protein: _RenderedProtein) -> str:
    rendered = protein.infer_oxygen().to_pdb_string()
    if not rendered.endswith("\n"):
        rendered = f"{rendered}\n"
    if rendered.splitlines()[-1][:6].strip() != "END":
        rendered = f"{rendered}END\n"
    return rendered


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
    selected_indices: list[int] = []
    canonical: list[float | None] = []
    for index, (value, valid) in enumerate(zip(native, mask, strict=True)):
        if project_to_valid_residues and not valid:
            continue
        selected_indices.append(index)
        if not valid:
            canonical.append(None)
            continue
        canonical.append(float(value) * (100.0 / native_maximum))
    finite_plddt = [value for value in canonical if value is not None]
    return (
        tuple(canonical),
        math.fsum(finite_plddt) / len(finite_plddt),
        tuple(selected_indices),
    )


def normalize_native_confidence(
    *,
    native_plddt: Iterable[object],
    valid_protein_residues: Iterable[object],
    ptm: float,
    pae: Iterable[Iterable[float]],
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

    ptm_value = float(ptm)
    pae_rows = tuple(tuple(row) for row in pae)
    normalized_pae: list[tuple[float, ...]] = []
    for row_index in selected_indices:
        row: list[float] = []
        for column_index in selected_indices:
            row.append(float(pae_rows[row_index][column_index]))
        normalized_pae.append(tuple(row))

    return NormalizedConfidence(
        per_residue_plddt=tuple(canonical),
        ptm=ptm_value,
        pae=tuple(normalized_pae),
    )
