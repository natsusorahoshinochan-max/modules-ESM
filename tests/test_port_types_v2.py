"""Public contract tests for canonical nominal Port Types."""

from __future__ import annotations

from core.catalog.builder import build_frozen_catalog
from core.catalog.declarations import ModulePackageRegistration

from protein_workbench_public.bootstrap import module_registrations

from dataclasses import FrozenInstanceError, fields

from fastapi.testclient import TestClient
import pytest

from core.catalog.errors import (
    CatalogBuildError,
    UnknownPortTypeError,
    PortValueError,
)
from core.catalog.canonical import (
    canonical_json_bytes,
    canonical_sha256,
)
from core.catalog.port_contract import (
    BehaviorReference,
    PortTypeDefinition,
)
from core.catalog.builtins import (
    builtin_frozen_catalog,
)
from tests.support.application import create_application
from datatypes.candidate import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
)
from datatypes.exact_reference import ExactContractReference
from datatypes.observation import (
    IntrinsicObservationContext,
    PairwiseCandidateMapping,
    PairwiseCandidateMatch,
    ScoreCollection,
    ScoreObservation,
)
from datatypes.prompt import (
    FunctionAnnotations,
    FunctionAnnotation,
    ProteinPrompt,
)
from datatypes.residue import (
    ModifiedResidueAtomMapping,
    ModifiedResidueNormalization,
    ModifiedResidueNormalizationCollection,
    ResidueLayout,
    ResidueMap,
    ResidueTrack,
)
from datatypes.sequence import ProteinSequence
from datatypes.structure import ProteinStructure
from modules.proteinmpnn.domain import ProteinMPNNConstraints
from datatypes.residue import validate_residue_map as validate_canonical_residue_map
from tests.support.protocol import validate_response


EXPECTED_PORT_TYPE_IDS = {
    "candidate.collection",
    "candidate.pairing",
    "function.annotations",
    "protein.prompt",
    "protein.sequence",
    "protein.structure",
    "residue.layout",
    "residue.map",
    "residue.track",
    "residue.track.sasa",
    "residue.track.secondary_structure",
    "score.collection",
    "text",
}
EXPECTED_BUILTIN_PORT_TYPE_IDS = EXPECTED_PORT_TYPE_IDS - {
    "function.annotations",
    "protein.prompt",
}
def _port_type_package(
    *port_types: PortTypeDefinition,
) -> ModulePackageRegistration:
    return ModulePackageRegistration(
        package_id="test.port-types",
        package_module=__name__,
        port_types=port_types,
    )


def test_superseded_structure_alignment_port_type_is_not_active() -> None:
    for catalog in (
        builtin_frozen_catalog(),
        build_frozen_catalog(module_registrations()),
    ):
        with pytest.raises(UnknownPortTypeError):
            catalog.require_port_type(
                "structure.alignment",)


def _typed_observation(value: object) -> ScoreObservation:
    return ScoreObservation(
        subject=CandidateDataReference(
            "candidate-1",
            "protein.sequence",
            "sha256:" + ("3" * 64),
        ),
        metric=ExactContractReference(
            "metric",
            "metric.plddt",),
        method=ExactContractReference(
            "method",
            "method.fixture",),
        context=IntrinsicObservationContext(),
        source_partition="default",
        value=value,
)


PROTEINMPNN_TEST_LAYOUT = ResidueLayout(
    "A",
    3,
    ["A:1", "A:2", "A:3"],
)


def test_catalog_snapshot_publishes_exact_port_type_contracts() -> None:
    catalog = build_frozen_catalog(module_registrations())
    with TestClient(
        create_application(
            frozen_catalog_override=catalog,
        )
    ) as client:
        response = client.get("/api/v2/catalog")

    assert response.status_code == 200
    payload = response.json()
    validate_response("catalog_snapshot", 200, payload)
    assert payload["schema_namespace"] == "protein-workbench-public/v2"
    observed_availability = {
        (
            snapshot["binding"]["contract_id"],
            snapshot["available"],
        )
        for snapshot in payload["availability"]
    }
    expected_availability = {
        (
            snapshot.binding.contract_id,
            snapshot.result.is_available,
        )
        for snapshot in catalog.availability
    }
    assert observed_availability == expected_availability

    contracts = [
        item
        for item in payload["contracts"]
        if item["reference"]["contract_kind"] == "port_type"
        and item["reference"]["contract_id"] in EXPECTED_PORT_TYPE_IDS
    ]
    assert {item["reference"]["contract_id"] for item in contracts} == (
        EXPECTED_PORT_TYPE_IDS
    )
    for contract in contracts:
        reference = contract["reference"]
        descriptor = contract["descriptor"]
        assert reference == {
            "contract_kind": "port_type",
            "contract_id": descriptor["contract_id"],
        }
        assert descriptor["schema_namespace"] == (
            "protein-workbench-contract/v2"
        )
        assert descriptor["contract_kind"] == "port_type"
        expected_descriptor_fields = {
            "schema_namespace",
            "contract_kind",
            "contract_id",
            "validator",
            "codec",
            "content_identity",
        }
        if descriptor["contract_id"] in {
            "candidate.collection",
            "candidate.pairing",
            "score.collection",
        }:
            expected_descriptor_fields.add("candidate_data_projection")
        assert set(descriptor) == expected_descriptor_fields
        for behavior_name in (
            "validator",
            "codec",
            "content_identity",
            *(
                ("candidate_data_projection",)
                if "candidate_data_projection" in descriptor
                else ()
            ),
        ):
            behavior = descriptor[behavior_name]
            assert set(behavior) == {
                "behavior_id",
                "parameters",
            }


def test_port_type_codec_round_trips_a_complete_valid_value() -> None:
    port_type = builtin_frozen_catalog().require_port_type(
        "protein.sequence",)
    value = ProteinSequence(
        sequence="META",
        residue_ids=["A:1", "A:2", "A:3", "A:4"],
    )

    encoded = port_type.encode(value)

    assert encoded == (
        b'{"port_type_id":"protein.sequence",'
        b'"schema_namespace":"protein-workbench-port-value/v2","value":'
        b'{"$dataclass":"protein_sequence","fields":{"residue_ids":'
        b'["A:1","A:2","A:3","A:4"],"sequence":"META"}}}'
    )
    assert port_type.decode(encoded) == value
    assert port_type.content_digest(value) == (
        "sha256:e5641249514e5ff9993506a8fb9638a52465ded8fe49f002548859052db1e57d"
    )


def test_protein_sequence_cuts_caller_aliases_without_changing_wire_bytes() -> None:
    residue_ids = ["A:1", "A:2"]
    value = ProteinSequence("MA", residue_ids)
    residue_ids.append("A:3")

    assert value.residue_ids == ("A:1", "A:2")
    with pytest.raises(FrozenInstanceError):
        value.sequence = "AA"

    port_type = builtin_frozen_catalog().require_port_type(
        "protein.sequence",)
    encoded = port_type.encode(value)

    assert b'"$tuple"' not in encoded
    assert b'"residue_ids":["A:1","A:2"]' in encoded
    assert port_type.decode(encoded) == value


@pytest.mark.parametrize("sequence", ("ma", "MÉTA", "MA*"))
def test_protein_sequence_admission_requires_the_exact_uppercase_alphabet(
    sequence: str,
) -> None:
    port_type = builtin_frozen_catalog().require_port_type(
        "protein.sequence",)

    with pytest.raises(PortValueError, match="uppercase amino-acid alphabet"):
        port_type.encode(ProteinSequence(sequence))


@pytest.mark.parametrize(
    "residue_ids",
    (
        ("A1", "A:2"),
        ("A:1", "A:1"),
    ),
)
def test_protein_sequence_admission_requires_canonical_unique_residue_identities(
    residue_ids: tuple[str, str],
) -> None:
    port_type = builtin_frozen_catalog().require_port_type(
        "protein.sequence",)

    with pytest.raises(PortValueError, match="residue identit"):
        port_type.encode(ProteinSequence("MA", residue_ids))


@pytest.mark.parametrize(
    ("old", "new", "message"),
    (
        (b'"A:1"', b'"A-1"', "residue identity"),
        (b'"A:2"', b'"A:1"', "duplicate residue identities"),
    ),
)
def test_protein_sequence_codec_rejects_noncanonical_residue_identities(
    old: bytes,
    new: bytes,
    message: str,
) -> None:
    port_type = builtin_frozen_catalog().require_port_type(
        "protein.sequence",)
    canonical = port_type.encode(
        ProteinSequence("MA", ("A:1", "A:2"))
    )

    with pytest.raises(PortValueError, match=message):
        port_type.decode(canonical.replace(old, new))


def test_protein_sequence_does_not_claim_residue_layout_chain_contiguity() -> None:
    port_type = builtin_frozen_catalog().require_port_type(
        "protein.sequence",)
    sequence = ProteinSequence(
        "MAG",
        ("A:1", "B:1", "A:2"),
    )

    assert port_type.decode(port_type.encode(sequence)) == sequence


def test_builtin_sequence_and_candidate_descriptors_declare_identity_invariants(
) -> None:
    catalog = builtin_frozen_catalog()

    assert catalog.require_port_type(
        "protein.sequence",).validator.parameters["sequence_invariants"] == {
        "alphabet": "ACDEFGHIKLMNPQRSTVWYBXZJUO",
        "nonempty": True,
        "residue_ids": {
            "cardinality": "absent-or-sequence-length",
            "chain_boundary_constraint": "none",
            "item_contract": "canonical-residue-identity",
            "unique": True,
        },
    }
    assert catalog.require_port_type(
        "candidate.collection",).validator.parameters["candidate_invariants"] == {
        "candidate_id": "canonical-identifier",
        "internal_lineage": {
            "acyclic": True,
            "external_parents": "allowed",
            "self_parent": "rejected",
        },
        "parent_ids": {
            "item_contract": "canonical-identifier",
            "ordered": True,
            "unique": True,
        },
    }


def test_immutable_residue_map_preserves_list_and_tuple_wire_semantics() -> None:
    layout = ResidueLayout("A", 1, ["A:1"])
    value = ResidueMap(layout, layout, [(0, 0, "match")])
    port_type = builtin_frozen_catalog().require_port_type(
        "residue.map",)

    encoded = port_type.encode(value)

    assert b'"mappings":[{"$tuple":[0,0,"match"]}]' in encoded
    assert port_type.decode(encoded) == value


def test_canonical_scientific_values_are_deeply_immutable() -> None:
    residue_ids = ["A:1", "A:2"]
    mappings = [(0, 0, "match"), (1, 1, "match")]
    track_values = [{"atom": [1.0, 2.0, 3.0]}, None]
    annotations = [
        FunctionAnnotation(
            label="site",
            start=1,
            end=1,
            chain_id="A",
            start_residue_id="A:1",
            end_residue_id="A:1",
            overlap_policy="allow",
        )
    ]
    parent_ids = ["parent-1"]
    metadata_samples = [1]
    score_values = [0.25, None]
    normalization_entries = [
        ModifiedResidueNormalization(
            component_id="CSH",
            observed_residue_id="A:1",
            parent_residue_ids=["A:1", "A:2"],
            parent_sequence="CS",
            atom_mappings=[
                ModifiedResidueAtomMapping("CA", "A:1", "CA")
            ],
        )
    ]

    layout = ResidueLayout("A", 2, residue_ids)
    track = ResidueTrack(track_values, None)
    function_annotations = FunctionAnnotations(annotations)
    prompt = ProteinPrompt(
        target_layout=layout,
        structure_track=track,
        function_annotations=function_annotations,
    )
    candidate = Candidate(
        "candidate-1",
        ProteinSequence("MA", residue_ids),
        parent_ids,
        {"samples": metadata_samples},
    )
    collection = CandidateCollection(
        "candidates",
        "protein.sequence",
        [candidate],
    )
    observation = _typed_observation({"values": score_values})
    scores = ScoreCollection("scores", [observation])
    residue_map = ResidueMap(layout, layout, mappings)
    pairing = PairwiseCandidateMapping([
        PairwiseCandidateMatch(
            CandidateDataReference(
                "candidate-1",
                "protein.sequence",
                "sha256:" + "1" * 64,
            ),
            CandidateDataReference(
                "candidate-2",
                "protein.sequence",
                "sha256:" + "2" * 64,
            ),
        )
    ])
    normalizations = ModifiedResidueNormalizationCollection(
        normalization_entries
    )

    residue_ids.append("A:3")
    mappings.append((2, 2, "match"))
    track_values[0]["atom"].append(4.0)
    annotations.clear()
    parent_ids.append("parent-2")
    metadata_samples.append(2)
    score_values.append(0.5)
    normalization_entries.clear()

    assert layout.residue_ids == ("A:1", "A:2")
    assert residue_map.mappings == (
        (0, 0, "match"),
        (1, 1, "match"),
    )
    assert track.values[0]["atom"] == (1.0, 2.0, 3.0)
    assert function_annotations.annotations == (
        prompt.function_annotations.annotations[0],
    )
    assert candidate.parent_ids == ("parent-1",)
    assert candidate.metadata["samples"] == (1,)
    assert collection.items == (candidate,)
    assert observation.value["values"] == (0.25, None)
    assert scores.entries == (observation,)
    assert pairing.entries[0].subject.candidate_id == "candidate-1"
    assert len(normalizations.entries) == 1

    with pytest.raises(FrozenInstanceError):
        layout.length = 3
    with pytest.raises(TypeError):
        candidate.metadata["samples"] = ()


def test_canonical_scientific_values_reject_ambiguous_or_mutable_inputs() -> None:
    with pytest.raises(TypeError, match="ordered list or tuple"):
        ProteinSequence("MA", {"A:1", "A:2"})
    with pytest.raises(TypeError, match="ordered list or tuple"):
        Candidate(
            "candidate-1",
            ProteinSequence("MA"),
            "parent-1",
        )
    with pytest.raises(ValueError, match="I-JSON"):
        Candidate(
            "candidate-1",
            ProteinSequence("MA"),
            metadata={"payload": bytearray(b"mutable")},
        )
    with pytest.raises(ValueError, match="string object key"):
        _typed_observation({("A:1", "A:2"): 0.5})
    with pytest.raises(ValueError, match="sentinel must be null"):
        ResidueTrack([1, []], [])


def test_every_builtin_port_type_round_trips_its_runtime_value() -> None:
    sequence = ProteinSequence("MA", ["A:1", "A:2"])
    structure = ProteinStructure(
        "ATOM      1  CA  ALA A   1       1.000   2.000   3.000"
        "  1.00 20.00           C  \nEND\n"
    )
    layout = ResidueLayout("A", 2, ["A:1", "A:2"])
    track = ResidueTrack(["M", None], None)
    samples = {
        "candidate.collection": CandidateCollection(
            "candidates",
            "protein.sequence",
            [
                Candidate(
                    "candidate-1",
                    sequence,
                    ["parent-1"],
                    {"rank": 1},
                )
            ],
        ),
        "protein.sequence": sequence,
        "protein.structure": structure,
        "residue.layout": layout,
        "residue.map": ResidueMap(
            layout,
            layout,
            [(0, 0, "match"), (1, 1, "match")],
        ),
        "residue.track": track,
        "residue.track.sasa": ResidueTrack([0.25, None], None),
        "residue.track.secondary_structure": ResidueTrack(
            ["H", "E"],
            None,
        ),
        "score.collection": ScoreCollection(
            "scores",
            [_typed_observation(83.5)],
        ),
        "candidate.pairing": PairwiseCandidateMapping(
            entries=[
                PairwiseCandidateMatch(
                    subject=CandidateDataReference(
                        "candidate-1",
                        "protein.sequence",
                        "sha256:" + "1" * 64,
                    ),
                    reference=CandidateDataReference(
                        "reference-1",
                        "protein.sequence",
                        "sha256:" + "2" * 64,
                    ),
                )
            ]
        ),
        "text": "α-helix",
    }
    catalog = builtin_frozen_catalog()

    assert set(samples) == EXPECTED_BUILTIN_PORT_TYPE_IDS
    for type_id, value in samples.items():
        definition = catalog.require_port_type(
            type_id,)
        definition.validate(value)
        assert definition.decode(definition.encode(value)) == value


def test_protein_structure_scientific_identity_excludes_source_provenance() -> None:
    port_type = builtin_frozen_catalog().require_port_type(
        "protein.structure",)
    pdb_string = (
        "ATOM      1  CA  ALA A   1       1.000   2.000   3.000"
        "  1.00 20.00           C  \nEND\n"
    )
    structure = ProteinStructure(pdb_string)

    assert tuple(item.name for item in fields(ProteinStructure)) == (
        "pdb_string",
    )
    with pytest.raises(TypeError, match="source"):
        ProteinStructure(pdb_string, source="provider")
    assert b'"source"' not in port_type.encode(structure)
    assert port_type.content_digest(structure) == (
        "sha256:ae194f58596034c7222ab19926da34079f5b95b4e97e38605e1cab8cc63e33cf"
    )
    legacy_wire = canonical_json_bytes({
        "schema_namespace": "protein-workbench-port-value/v2",
        "port_type_id": "protein.structure",
        "value": {
            "$dataclass": "protein_structure",
            "fields": {
                "pdb_string": pdb_string,
                "source": "provider",
            },
        },
    })
    with pytest.raises(PortValueError, match="complete protein_structure"):
        port_type.decode(legacy_wire)


@pytest.mark.parametrize(
    "pdb_string",
    (
        (
            "ATOM      1  N   ALA A   1       0.000   0.000   0.000"
            "  1.00 20.00           N  \r\nEND\r\n"
        ),
        (
            "ATOM      1  N   ALA A   1       0.000   0.000   0.000"
            "  1.00 20.00           N  \nEND"
        ),
        "ATOM      X malformed coordinate record\nEND\n",
        (
            "MODEL garbage\n"
            "ATOM      1  N   ALA A   1       0.000   0.000   0.000"
            "  1.00 20.00           N  \nENDMDL\nEND\n"
        ),
        (
            "ATOM      1  N   ALA A   1       0.000   0.000   0.000"
            "  1.00 20.00           N  \n"
        ),
    ),
)
def test_protein_structure_admission_rejects_noncanonical_pdb_text(
    pdb_string: str,
) -> None:
    port_type = builtin_frozen_catalog().require_port_type(
        "protein.structure",)

    with pytest.raises(PortValueError, match="canonical PDB"):
        port_type.encode(ProteinStructure(pdb_string))


def test_protein_structure_admission_does_not_impose_single_model_or_ca() -> None:
    port_type = builtin_frozen_catalog().require_port_type(
        "protein.structure",)
    structure = ProteinStructure(
        "MODEL        1\n"
        "ATOM      1  N   ALA A   1       0.000   0.000   0.000"
        "  1.00 20.00           N  \n"
        "ENDMDL\n"
        "MODEL        2\n"
        "ATOM      2  N   ALA A   1       1.000   0.000   0.000"
        "  1.00 20.00           N  \n"
        "ENDMDL\n"
        "END\n"
    )

    assert port_type.decode(port_type.encode(structure)) == structure


@pytest.mark.parametrize("record_name", ("HETNAM", "HETSYN", "SPRSDE"))
def test_protein_structure_accepts_supported_uninterpreted_metadata_record_names(
    record_name: str,
) -> None:
    port_type = builtin_frozen_catalog().require_port_type(
        "protein.structure",)
    structure = ProteinStructure(
        f"{record_name:<6} canonical metadata\n"
        "ATOM      1  N   ALA A   1       0.000   0.000   0.000"
        "  1.00 20.00           N  \n"
        "END\n"
    )

    assert port_type.decode(port_type.encode(structure)) == structure


def test_protein_structure_admission_preserves_pdb_residue_number_zero() -> None:
    port_type = builtin_frozen_catalog().require_port_type(
        "protein.structure",)
    structure = ProteinStructure(
        "ATOM      1  N   ALA A   0       0.000   0.000   0.000"
        "  1.00 20.00           N  \nEND\n"
    )

    assert port_type.decode(port_type.encode(structure)) == structure


def test_protein_structure_admission_accepts_standard_padded_end_record() -> None:
    port_type = builtin_frozen_catalog().require_port_type(
        "protein.structure",)
    structure = ProteinStructure(
        "ATOM      1  N   ALA A   1       0.000   0.000   0.000"
        "  1.00 20.00           N  \nEND   \n"
    )

    assert port_type.decode(port_type.encode(structure)) == structure


@pytest.mark.parametrize(
    "layout",
    (
        ResidueLayout("A", 2),
        ResidueLayout("A", 2, ["A:1", "A:1"]),
        ResidueLayout("A,B,A", 3, ["A:1", "B:1", "A:2"]),
        ResidueLayout("A", 1, ["A1"]),
    ),
)
def test_residue_layout_admission_requires_complete_unique_contiguous_identities(
    layout: ResidueLayout,
) -> None:
    port_type = builtin_frozen_catalog().require_port_type(
        "residue.layout",)

    with pytest.raises(PortValueError, match="identit|contiguous"):
        port_type.encode(layout)


@pytest.mark.parametrize(
    "residue_map",
    (
        ResidueMap(
            ResidueLayout("A", 2, ["A:1", "A:2"]),
            ResidueLayout("A", 2, ["A:1", "A:2"]),
            [(0, 0, "match")],
        ),
        ResidueMap(
            ResidueLayout("A", 1, ["A:1"]),
            ResidueLayout("A", 1, ["A:1"]),
            [(0, 0, "match"), (0, 0, "match")],
        ),
        ResidueMap(
            ResidueLayout("A", 2, ["A:1", "A:2"]),
            ResidueLayout("A", 2, ["A:2", "A:1"]),
            [(0, 0, "match"), (1, 1, "match")],
        ),
        ResidueMap(
            ResidueLayout("A", 1, ["A:1"]),
            ResidueLayout("A", 1, ["A:1"]),
            [(0, -1, "delete"), (-1, 0, "insert")],
        ),
    ),
)
def test_residue_map_admission_requires_complete_one_to_one_identity_mapping(
    residue_map: ResidueMap,
) -> None:
    port_type = builtin_frozen_catalog().require_port_type(
        "residue.map",)

    with pytest.raises(
        PortValueError,
        match="cover|overlap|identit|insert|delete",
    ):
        port_type.encode(residue_map)


def test_canonical_residue_map_owner_rejects_boolean_indices() -> None:
    layout = ResidueLayout("A", 2, ["A:1", "A:2"])
    residue_map = ResidueMap(
        layout,
        layout,
        [(False, False, "match"), (True, True, "match")],
    )

    with pytest.raises(ValueError, match="integer indices"):
        validate_canonical_residue_map(residue_map)


def test_codec_rejects_malformed_and_noncanonical_values() -> None:
    sequence_type = builtin_frozen_catalog().require_port_type(
        "protein.sequence",)
    canonical = sequence_type.encode(ProteinSequence("MA"))

    with pytest.raises(PortValueError, match="requires ProteinSequence"):
        sequence_type.encode({"sequence": "MA"})
    with pytest.raises(PortValueError, match="not canonical RFC 8785"):
        sequence_type.decode(b" " + canonical)
    with pytest.raises(PortValueError, match="duplicate JSON object key"):
        sequence_type.decode(
            canonical.replace(
                b'"sequence":"MA"',
                b'"sequence":"MA","sequence":"MA"',
            )
        )
    with pytest.raises(PortValueError, match="nominal identity"):
        sequence_type.decode(
            canonical.replace(b"protein.sequence", b"protein.structure")
        )

    from modules.proteinmpnn.package import MODULE_PACKAGE as package

    constraints_type = package.port_types[0]
    constraints = constraints_type.encode(
        ProteinMPNNConstraints(
            layout=PROTEINMPNN_TEST_LAYOUT,
            bias_by_residue={
                "A:2": {"A": 0.5},
                "A:3": {"V": -0.5},
            },
        )
    )
    with pytest.raises(PortValueError, match="canonical key order"):
        constraints_type.decode(
            constraints.replace(
                b'[["A:2",{"A":0.5}],["A:3",{"V":-0.5}]]',
                b'[["A:3",{"V":-0.5}],["A:2",{"A":0.5}]]',
            )
        )


@pytest.mark.parametrize(
    ("type_id", "malformed"),
    [
        ("protein.sequence", ProteinSequence(123)),
        ("protein.sequence", ProteinSequence("MA", [1, 2])),
        (
            "candidate.collection",
            CandidateCollection(
                "candidates",
                "protein.sequence",
                [Candidate("candidate-1", ProteinStructure("ATOM\n"))],
            ),
        ),
        ("residue.track.sasa", ResidueTrack(["buried"], None)),
    ],
)
def test_runtime_validators_reject_malformed_complete_values(
    type_id: str,
    malformed: object,
) -> None:
    definition = builtin_frozen_catalog().require_port_type(
        type_id,)

    with pytest.raises(
        PortValueError,
        match="requires|must|mismatch|does not match",
    ):
        definition.encode(malformed)


def test_canonical_constructors_close_domain_invariants_before_encoding() -> None:

    catalog = build_frozen_catalog(module_registrations())
    sequence = ProteinSequence("MA", ["A:1", "A:2"])
    layout = ResidueLayout("A", 1, ["A:1"])
    with pytest.raises(FrozenInstanceError):
        sequence.residue_ids = ("A:1",)
    with pytest.raises(FrozenInstanceError):
        layout.length = -1
    with pytest.raises(ValueError, match="residue_ids length"):
        ProteinSequence("MA", ["A:1"])
    with pytest.raises(ValueError, match="length must be"):
        ResidueLayout("A", -1)
    malformed_values = [
        (
            "residue.map",
            ResidueMap(
                ResidueLayout("A", 1),
                ResidueLayout("A", 1),
                [(99, 99, "match")],
            ),
        ),
        (
            "function.annotations",
            FunctionAnnotations(
                [{"label": "site", "start": "zero", "unexpected": True}]
            ),
        ),
        (
            "protein.prompt",
            ProteinPrompt(
                target_layout=ResidueLayout("A", 2),
                sequence_track=ResidueTrack(["A"]),
            ),
        ),
        (
            "residue.track.secondary_structure",
            ResidueTrack(["helix"]),
        ),
    ]

    for type_id, malformed in malformed_values:
        with pytest.raises(PortValueError):
            catalog.require_port_type(
                type_id,).encode(malformed)


@pytest.mark.parametrize(
    "constraints",
    [
        ProteinMPNNConstraints(
            layout=PROTEINMPNN_TEST_LAYOUT,
            tied_residue_groups=[["A:1"]],
        ),
        ProteinMPNNConstraints(
            layout=PROTEINMPNN_TEST_LAYOUT,
            designable_residue_ids=["A:1"],
            fixed_residue_ids=["A:1"],
        ),
        ProteinMPNNConstraints(
            layout=PROTEINMPNN_TEST_LAYOUT,
            omit_amino_acids=["B"],
        ),
        ProteinMPNNConstraints(
            layout=PROTEINMPNN_TEST_LAYOUT,
            bias_by_residue={"A:1": {"B": 1.0}},
        ),
    ],
)
def test_proteinmpnn_port_reuses_the_authoritative_constraint_contract(
    constraints: ProteinMPNNConstraints,
) -> None:

    definition = build_frozen_catalog(module_registrations()).require_port_type(
        "proteinmpnn.constraints",)

    with pytest.raises(PortValueError):
        definition.encode(constraints)


def test_proteinmpnn_constraints_cannot_drift_after_validation() -> None:
    constraints = ProteinMPNNConstraints(
        layout=PROTEINMPNN_TEST_LAYOUT,
        tied_residue_groups=[["A:1", "A:2"]],
    )
    from modules.proteinmpnn.package import MODULE_PACKAGE as package

    definition = package.port_types[0]
    definition.validate(constraints)

    with pytest.raises(AttributeError):
        constraints.tied_residue_groups[0].pop()
    definition.encode(constraints)


@pytest.mark.parametrize("invalid_value", [-0.0, float("nan"), float("inf")])
def test_score_constructor_rejects_non_i_json_numbers(
    invalid_value: float,
) -> None:
    with pytest.raises(ValueError, match="I-JSON"):
        _typed_observation(invalid_value)


def test_i_json_array_admission_normalizes_list_and_tuple_wire_identity() -> None:
    score_type = builtin_frozen_catalog().require_port_type(
        "score.collection",)
    list_observation = _typed_observation({"samples": [1, 2]})
    tuple_observation = _typed_observation({"samples": (1, 2)})
    list_scores = ScoreCollection("scores", [list_observation])
    tuple_scores = ScoreCollection("scores", [tuple_observation])

    list_encoded = score_type.encode(list_scores)
    tuple_encoded = score_type.encode(tuple_scores)

    assert list_observation == tuple_observation
    assert tuple_encoded == list_encoded
    assert score_type.content_digest(tuple_scores) == (
        score_type.content_digest(list_scores)
    )
    assert score_type.encode(
        ScoreCollection("scores", [list_observation, tuple_observation])
    ) == list_encoded
    assert b'"$tuple"' not in list_encoded


def test_behavior_declarations_require_stable_ids_and_i_json() -> None:
    with pytest.raises(CatalogBuildError, match="canonical identifier"):
        BehaviorReference("Example Validate", {})
    with pytest.raises(CatalogBuildError, match="negative zero"):
        BehaviorReference("example.validate", {"threshold": -0.0})
    with pytest.raises(CatalogBuildError, match="NaN|Infinity"):
        BehaviorReference(
            "example.validate",
            {"threshold": float("nan")},
        )


def test_behavior_declaration_parameters_are_deeply_immutable() -> None:
    supplied = {"schema": {"required": ["sequence"]}}
    behavior = BehaviorReference(
        "example.validate",
        supplied,
    )

    supplied["schema"]["required"].append("residue_ids")

    assert behavior.descriptor()["parameters"] == {
        "schema": {"required": ["sequence"]}
    }
    with pytest.raises(TypeError):
        behavior.parameters["schema"]["new_field"] = True


def test_rfc8785_and_sha256_match_the_published_golden_vector() -> None:
    vector = {
        "literals": [None, True, False],
        "numbers": [333333333.33333329, 1e30, 4.50, 2e-3, 1e-27],
        "string": "€$\x0f\nA'B\"\\\"/",
    }

    assert canonical_json_bytes(vector) == (
        b'{"literals":[null,true,false],"numbers":[333333333.3333333,'
        b'1e+30,4.5,0.002,1e-27],"string":"\xe2\x82\xac$\\u000f\\n'
        b'A\'B\\"\\\\\\"/"}'
    )
    assert canonical_sha256(vector) == (
        "sha256:6d77565c0fe51d7346bd5debb08f2eebbe9bde01eade30b34e2011f360f91b0e"
    )


def test_codec_differentials_materialize_defaults_and_preserve_semantic_order() -> None:
    catalog = builtin_frozen_catalog()
    sequence_type = catalog.require_port_type("protein.sequence",)
    from modules.proteinmpnn.package import MODULE_PACKAGE as package

    constraints_type = package.port_types[0]
    first_map_order = ProteinMPNNConstraints(
        layout=PROTEINMPNN_TEST_LAYOUT,
        bias_by_residue={
            "A:3": {"V": -0.5},
            "A:2": {"A": 0.5},
        },
    )
    second_map_order = ProteinMPNNConstraints(
        layout=PROTEINMPNN_TEST_LAYOUT,
        bias_by_residue={
            "A:2": {"A": 0.5},
            "A:3": {"V": -0.5},
        },
    )

    assert sequence_type.encode(ProteinSequence("MA")) == (
        sequence_type.encode(ProteinSequence("MA", residue_ids=None))
    )
    assert constraints_type.encode(first_map_order) == (
        constraints_type.encode(second_map_order)
    )
    assert sequence_type.content_digest(
        ProteinSequence("MA", ["A:1", "A:2"])
    ) != sequence_type.content_digest(
        ProteinSequence("MA", ["A:2", "A:1"])
    )


def test_port_type_catalog_build_is_atomic_on_duplicate_identity() -> None:
    published = builtin_frozen_catalog()
    duplicate = published.require_port_type("text",)

    with pytest.raises(CatalogBuildError, match="duplicate contract identity"):
        build_frozen_catalog(
            (_port_type_package(duplicate),)
        )

    assert published.require_port_type("text") is duplicate
