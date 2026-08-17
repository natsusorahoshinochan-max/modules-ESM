"""Controlled provider seams for the exact canonical v2 3GB1 Workflow."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import math
from typing import Any

import torch

from core import (
    AvailabilityResult,
    ModulePackageRegistration,
    ReadinessCheckInput,
    ReadinessResult,
    build_frozen_catalog,
    discover_module_packages,
)
from datatypes import ProteinSequence


VERSION = "2.1.0"
REMOTE_BINDING_VERSION = "7.0.0"
PROTEINMPNN_BINDING_VERSION = "10.0.0"
CANONICAL_PROVIDER_PROMPT_CONTENT_DIGEST = (
    "sha256:af6fb4017077a24d67882151d39beb7790b118b02c155a986a48907e1a569ab8"
)
PROVIDER_BINDINGS = frozenset({
    "esm3.generate_paired.biohub_medium",
    "folding.fold.esmfold2_remote",
    "proteinmpnn.design.local",
})
_AA3 = dict(
    zip(
        "ACDEFGHIKLMNPQRSTVWY",
        (
            "ALA",
            "CYS",
            "ASP",
            "GLU",
            "PHE",
            "GLY",
            "HIS",
            "ILE",
            "LYS",
            "LEU",
            "MET",
            "ASN",
            "PRO",
            "GLN",
            "ARG",
            "SER",
            "THR",
            "VAL",
            "TRP",
            "TYR",
        ),
        strict=True,
    )
)
_AA1 = {value: key for key, value in _AA3.items()}
_ALPHABET = "ACDEFGHIKLMNPQRSTVWY"


def pdb_for_sequence(
    sequence: str,
    *,
    bend: float = 0.0,
    z_offset: float = 0.0,
) -> str:
    """Render a deterministic complete single-chain backbone."""
    lines = ["HEADER    CONTROLLED CANONICAL V2 PROVIDER"]
    serial = 1
    for index, amino_acid in enumerate(sequence, start=1):
        center_x = (index - 1) * 3.8
        center_y = bend * math.sin(index * 0.37)
        center_z = z_offset + bend * math.cos(index * 0.23)
        center_y = 0.0 if abs(center_y) < 0.0005 else center_y
        center_z = 0.0 if abs(center_z) < 0.0005 else center_z
        for atom_name, atom_offset in (
            ("N", -1.2),
            ("CA", 0.0),
            ("C", 1.2),
            ("O", 1.8),
        ):
            lines.append(
                f"ATOM  {serial:5d} {atom_name:^4s} "
                f"{_AA3[amino_acid]:>3s} A{index:4d}    "
                f"{center_x + atom_offset:8.3f}"
                f"{center_y:8.3f}{center_z:8.3f}"
                f"{1.0:6.2f}{20.0:6.2f}"
                f"{'':10}{atom_name[0]:>2s}  "
            )
            serial += 1
    lines.extend(("TER", "END"))
    return "\n".join(lines) + "\n"


@dataclass
class ControlledESMResponse:
    sequence: str
    coordinates: Any = None
    ptm: Any = None
    plddt: Any = None
    pae: Any = None
    pdb_string: str | None = None

    def to_pdb_string(self) -> str:
        if self.pdb_string is None:
            raise AssertionError("sequence-only response has no PDB")
        return self.pdb_string


class ControlledESM3Client:
    """Return ten exact sequence/structure pairs and retain Prompt evidence."""

    def __init__(self) -> None:
        self.sequence_prompts: list[Any] = []
        self.structure_prompts: list[Any] = []

    @staticmethod
    def _completed(masked: str, sample_index: int) -> str:
        replacement = _ALPHABET[sample_index % len(_ALPHABET)]
        return "".join(
            replacement if symbol == "_" else symbol
            for symbol in masked
        )

    def generate(self, protein: Any, config: Any) -> ControlledESMResponse:
        if config.track == "sequence":
            sample_index = len(self.sequence_prompts) % 10
            self.sequence_prompts.append(protein)
            return ControlledESMResponse(
                sequence=self._completed(protein.sequence, sample_index),
            )
        if config.track != "structure":
            raise AssertionError(f"unexpected ESM-3 track {config.track!r}")
        sample_index = len(self.structure_prompts) % 10
        self.structure_prompts.append(protein)
        residue_count = len(protein.sequence)
        bend = sample_index * 0.12
        coordinates = torch.zeros((residue_count, 37, 3))
        coordinates[:, 0, 0] = torch.arange(residue_count) * 3.8 - 1.2
        coordinates[:, 1, 0] = torch.arange(residue_count) * 3.8
        coordinates[:, 2, 0] = torch.arange(residue_count) * 3.8 + 1.2
        return ControlledESMResponse(
            sequence=protein.sequence,
            coordinates=coordinates,
            ptm=torch.tensor(0.80 + sample_index * 0.01),
            plddt=torch.tensor([0.90] * residue_count),
            pae=torch.zeros((residue_count, residue_count)),
            pdb_string=pdb_for_sequence(
                protein.sequence,
                bend=bend,
            ),
        )


@dataclass
class ControlledFoldResponse:
    sequence: str
    pdb_string: str
    ptm: torch.Tensor
    plddt: torch.Tensor
    pae: torch.Tensor

    def to_protein_chain(self) -> "ControlledFoldResponse":
        return self

    def infer_oxygen(self) -> "ControlledFoldResponse":
        return self

    def to_pdb_string(self) -> str:
        return self.pdb_string


class ControlledFoldingClient:
    """Return ten ranking folds followed by fifteen final folds."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def fold(
        self,
        *,
        sequence: str,
        model_name: str,
        config: Any,
    ) -> ControlledFoldResponse:
        del model_name, config
        call_index = len(self.calls) % 25
        self.calls.append(sequence)
        bend = (
            call_index * 0.12
            if call_index < 10
            else 2.0 + (call_index - 10) * 0.03
        )
        residue_count = len(sequence)
        return ControlledFoldResponse(
            sequence=sequence,
            pdb_string=pdb_for_sequence(
                sequence,
                bend=bend,
                z_offset=(call_index - 10) * 0.001,
            ),
            ptm=torch.tensor(0.95 - call_index * 0.001),
            plddt=torch.tensor(
                [0.90 - call_index * 0.001] * residue_count
            ),
            pae=torch.tensor([
                [
                    min(float(abs(left - right)), 31.75)
                    for right in range(residue_count)
                ]
                for left in range(residue_count)
            ]),
        )


class ControlledProteinMPNNProvider:
    """Return exactly five deterministic children for every selected parent."""

    provider_identity = "controlled-proteinmpnn-v2"

    def __init__(self) -> None:
        self.requests: list[Any] = []

    def parse_structure(self, pdb_string: str) -> list[dict[str, object]]:
        sequence = "".join(
            _AA1[line[17:20].strip()]
            for line in pdb_string.splitlines()
            if line.startswith("ATOM  ")
            and line[12:16].strip() == "CA"
        )
        return [{
            "name": "controlled-canonical-v2",
            "seq": sequence,
            "seq_chain_A": sequence,
        }]

    def design(
        self,
        request: Any,
    ) -> list[ProteinSequence]:
        seed_offset = request.seed % len(_ALPHABET)
        self.requests.append(request)
        sequences = [
            ProteinSequence(
                "".join(
                    _ALPHABET[
                        (
                            position
                            + seed_offset
                            + sample_index
                        )
                        % len(_ALPHABET)
                    ]
                    for position in range(request.target_length)
                )
            )
            for sample_index in range(request.num_sequences)
        ]
        return sequences


def controlled_catalog() -> Any:
    """Preserve every public contract byte while opening provider test seams."""

    def available() -> AvailabilityResult:
        return AvailabilityResult.available()

    def ready(check_input: ReadinessCheckInput) -> ReadinessResult:
        return ReadinessResult(isinstance(check_input.values, Mapping))

    registrations: list[ModulePackageRegistration] = []
    for registration in discover_module_packages():
        bindings = []
        for binding in registration.bindings:
            if binding.binding_id not in PROVIDER_BINDINGS:
                bindings.append(binding)
                continue
            bindings.append(
                replace(
                    binding,
                    availability=replace(
                        binding.availability,
                        check=available,
                    ),
                    readiness=replace(
                        binding.readiness,
                        check=ready,
                    ),
                )
            )
        registrations.append(
            replace(registration, bindings=tuple(bindings))
        )
    return build_frozen_catalog(tuple(registrations))


def controlled_environment(
    esm3: ControlledESM3Client,
    folding: ControlledFoldingClient,
) -> dict[tuple[str, str], dict[str, object]]:
    """Build trusted run-scoped configuration without Workflow-owned values."""
    return {
        (
            "esm3.generate_paired.biohub_medium",
            REMOTE_BINDING_VERSION,
        ): {
            "values": {
                "endpoint_id": "biohub",
                "credential_handle": object(),
                "provider_client": esm3,
            },
            "safe_fingerprint": "controlled-esm3-canonical-v2",
            "invalidation_token": "controlled-esm3-canonical-v2",
        },
        ("folding.fold.esmfold2_remote", REMOTE_BINDING_VERSION): {
            "values": {
                "endpoint_id": "biohub",
                "credential_handle": object(),
                "provider_client": folding,
            },
            "safe_fingerprint": "controlled-folding-canonical-v2",
            "invalidation_token": "controlled-folding-canonical-v2",
        },
        ("proteinmpnn.design.local", PROTEINMPNN_BINDING_VERSION): {
            "values": {},
            "safe_fingerprint": "controlled-proteinmpnn-canonical-v2",
            "invalidation_token": "controlled-proteinmpnn-canonical-v2",
        },
    }
