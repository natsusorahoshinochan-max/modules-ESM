"""Canonical ResidueIdentity coverage for signed PDB residue numbers."""

from __future__ import annotations

import pytest

from core.catalog.errors import PortValueError
from datatypes.residue import ResidueLayout
from datatypes.residue import residue_identity_chain


@pytest.mark.parametrize(
    "residue_id",
    (
        "A:-3",
        "A:-3A",
        "A:-999",
        "A:+3",
        "A:+3B",
        "A:authored.v1-label",
    ),
)
def test_residue_identity_admits_signed_pdb_and_existing_authored_labels(
    residue_id: str,
) -> None:
    assert residue_identity_chain(residue_id) == "A"


@pytest.mark.parametrize(
    "residue_id",
    (
        "A:-",
        "A:+",
        "A:--3",
        "A:+-3",
        "A:-1234",
        "A:-3.extra",
    ),
)
def test_signed_pdb_residue_identity_form_is_closed(residue_id: str) -> None:
    with pytest.raises(ValueError, match="'<chain>:<label>'"):
        residue_identity_chain(residue_id)


def test_signed_residue_id_round_trips_layout_codec() -> None:
    from core.catalog.port_contract import (
        PORT_VALUE_NAMESPACE,
        BehaviorReference,
        PortTypeDefinition,
    )

    layout_type = PortTypeDefinition(
        type_id="residue_layout",
        validator=BehaviorReference(
            behavior_id="protein-workbench.port-type/residue_layout/validate",
            parameters={"accepted_value_kind": "residue_layout"},
        ),
        codec=BehaviorReference(
            behavior_id=(
                "protein-workbench.port-type/residue_layout/"
                "canonical-json-codec"
            ),
            parameters={
                "canonicalization": "RFC 8785",
                "character_encoding": "UTF-8",
                "envelope_namespace": PORT_VALUE_NAMESPACE,
                "value_kind": "residue_layout",
            },
        ),
        content_identity=BehaviorReference(
            behavior_id=(
                "protein-workbench.port-type/residue_layout/content-sha256"
            ),
            parameters={
                "digest_algorithm": "SHA-256",
                "digest_input": "canonical_codec_bytes",
                "digest_representation": "sha256:<64 lowercase hexadecimal digits>",
            },
        ),
    )
    source = ResidueLayout(("A:-3", "A:-3A"))

    assert layout_type.decode(layout_type.encode(source)) == source

    invalid = ResidueLayout(("A:-1234",))
    with pytest.raises(PortValueError, match="residue identity"):
        layout_type.encode(invalid)
