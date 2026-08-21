"""Canonical ResidueIdentity coverage for signed PDB residue numbers."""

from __future__ import annotations

import pytest

from core.catalog.builtins import (
    builtin_frozen_catalog,
)
from core.catalog.port_contract import (
    PortValueError,
)
from datatypes.residue import (
    ResidueLayout,
    ResidueMap,
)
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


def test_signed_residue_id_round_trips_layout_and_map_codecs() -> None:
    catalog = builtin_frozen_catalog()
    layout_type = catalog.require_port_type("residue.layout", "3.0.0")
    map_type = catalog.require_port_type("residue.map", "3.0.0")
    source = ResidueLayout("A", 2, ("A:-3", "A:-3A"))
    residue_map = ResidueMap(
        source,
        source,
        ((0, 0, "match"), (1, 1, "match")),
    )

    assert layout_type.decode(layout_type.encode(source)) == source
    assert map_type.decode(map_type.encode(residue_map)) == residue_map

    invalid = ResidueLayout("A", 1, ("A:-1234",))
    with pytest.raises(PortValueError, match="residue identity"):
        layout_type.encode(invalid)
