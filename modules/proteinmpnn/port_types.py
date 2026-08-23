"""Nominal ProteinMPNN constraint Port owned by the package."""

from __future__ import annotations

from core.catalog.port_contract import BehaviorReference, PortTypeDefinition
from datatypes.i_json import thaw_i_json
from datatypes.residue import ResidueLayout

from .domain import (
    ProteinMPNNConstraints,
    validate_proteinmpnn_constraints,
)


_VERSION = "4.0.0"
_BEHAVIOR_PREFIX = "protein-workbench.port-type/proteinmpnn.constraints"


def _validate_constraints(value: object) -> None:
    if type(value) is not ProteinMPNNConstraints:
        raise ValueError("constraints must use the exact ProteinMPNN contract")
    validate_proteinmpnn_constraints(value)


def _to_wire(value: ProteinMPNNConstraints) -> dict[str, object]:
    return thaw_i_json({
        "layout": {
            "chain_id": value.layout.chain_id,
            "length": value.layout.length,
            "residue_ids": value.layout.residue_ids,
        },
        "designable_residue_ids": value.designable_residue_ids,
        "fixed_residue_ids": value.fixed_residue_ids,
        "designed_chains": value.designed_chains,
        "fixed_chains": value.fixed_chains,
        "omit_amino_acids": value.omit_amino_acids,
        "tied_residue_groups": value.tied_residue_groups,
        "bias_by_residue": (
            None
            if value.bias_by_residue is None
            else [
                [residue_id, dict(sorted(biases.items()))]
                for residue_id, biases in sorted(
                    value.bias_by_residue.items()
                )
            ]
        ),
    })


def _from_wire(value: object) -> ProteinMPNNConstraints:
    if not isinstance(value, dict) or set(value) != {
        "layout",
        "designable_residue_ids",
        "fixed_residue_ids",
        "designed_chains",
        "fixed_chains",
        "omit_amino_acids",
        "tied_residue_groups",
        "bias_by_residue",
    }:
        raise ValueError("ProteinMPNN constraints wire value is not closed")
    raw_biases = value["bias_by_residue"]
    if raw_biases is None:
        biases = None
    elif isinstance(raw_biases, list):
        biases = {}
        previous_residue_id: str | None = None
        for entry in raw_biases:
            if (
                not isinstance(entry, list)
                or len(entry) != 2
                or type(entry[0]) is not str
                or not isinstance(entry[1], dict)
            ):
                raise ValueError(
                    "ProteinMPNN constraint biases are malformed"
                )
            if (
                previous_residue_id is not None
                and entry[0] <= previous_residue_id
            ):
                raise ValueError(
                    "ProteinMPNN constraint biases require canonical key order"
                )
            biases[entry[0]] = entry[1]
            previous_residue_id = entry[0]
    else:
        raise ValueError("ProteinMPNN constraint biases are malformed")
    raw_layout = value["layout"]
    if (
        not isinstance(raw_layout, dict)
        or set(raw_layout) != {"chain_id", "length", "residue_ids"}
    ):
        raise ValueError("ProteinMPNN constraint layout is malformed")

    return ProteinMPNNConstraints(
        layout=ResidueLayout(
            chain_id=raw_layout["chain_id"],
            length=raw_layout["length"],
            residue_ids=raw_layout["residue_ids"],
        ),
        designable_residue_ids=value["designable_residue_ids"],
        fixed_residue_ids=value["fixed_residue_ids"],
        designed_chains=value["designed_chains"],
        fixed_chains=value["fixed_chains"],
        omit_amino_acids=value["omit_amino_acids"],
        tied_residue_groups=value["tied_residue_groups"],
        bias_by_residue=biases,
    )


PROTEINMPNN_CONSTRAINTS_PORT_TYPE = PortTypeDefinition(
    type_id="proteinmpnn.constraints",
    version=_VERSION,
    validator=BehaviorReference(
        behavior_id=f"{_BEHAVIOR_PREFIX}/validate",
        behavior_version=_VERSION,
        parameters={
            "accepted_value_kind": "proteinmpnn_constraints",
            "complete_values_only": True,
        },
    ),
    codec=BehaviorReference(
        behavior_id=f"{_BEHAVIOR_PREFIX}/canonical-json-codec",
        behavior_version=_VERSION,
        parameters={
            "canonicalization": "RFC 8785",
            "character_encoding": "UTF-8",
            "envelope_namespace": "protein-workbench-port-value/v2",
            "value_kind": "proteinmpnn_constraints",
            "embedded_layout_contract": "residue.layout@3.0.0",
        },
    ),
    content_identity=BehaviorReference(
        behavior_id=f"{_BEHAVIOR_PREFIX}/content-sha256",
        behavior_version=_VERSION,
        parameters={
            "digest_algorithm": "SHA-256",
            "digest_input": "canonical_codec_bytes",
            "digest_representation": (
                "sha256:<64 lowercase hexadecimal digits>"
            ),
        },
    ),
    runtime_validator=_validate_constraints,
    runtime_to_wire=_to_wire,
    runtime_from_wire=_from_wire,
)
