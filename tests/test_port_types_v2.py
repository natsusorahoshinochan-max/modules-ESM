"""Public contract tests for canonical nominal Port Types."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace
import re

from fastapi.testclient import TestClient
import pytest

from core import (
    BehaviorReference,
    CatalogBuildError,
    FrozenCatalog,
    PortTypeDefinition,
    PortValueError,
    UnknownPortTypeError,
    build_discovered_frozen_catalog,
    canonical_json_bytes,
    canonical_sha256,
)
from core import builtin_frozen_catalog
from core.server import create_app
from datatypes import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
    ExactContractReference,
    FunctionAnnotations,
    FunctionAnnotation,
    IntrinsicObservationContext,
    ModifiedResidueAtomMapping,
    ModifiedResidueNormalization,
    ModifiedResidueNormalizationCollection,
    PairwiseCandidateMapping,
    PairwiseCandidateMatch,
    ProteinPrompt,
    ProteinMPNNConstraints,
    ProteinSequence,
    ProteinStructure,
    ResidueLayout,
    ResidueMap,
    ResidueTrack,
    ScoreCollection,
    ScoreObservation,
)
from datatypes.protein import validate_residue_map as validate_canonical_residue_map
from protein_workbench_public import validate_response


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
EXPECTED_PORT_TYPE_VERSIONS = {
    type_id: {
        "candidate.collection": "3.0.0",
        "candidate.pairing": "3.0.0",
        "function.annotations": "3.0.0",
        "protein.prompt": "3.0.0",
        "protein.sequence": "3.0.0",
        "protein.structure": "4.0.0",
        "residue.layout": "3.0.0",
        "residue.map": "3.0.0",
        "score.collection": "4.0.0",
    }.get(type_id, "2.1.0")
    for type_id in EXPECTED_PORT_TYPE_IDS
}
EXPECTED_PORT_TYPE_DIGESTS = {
    "candidate.collection": (
        "sha256:e900457e8e059f4f15469e7673fa3156d0f51e060fc8235daf07fc3ce5954812"
    ),
    "candidate.pairing": (
        "sha256:20a3e7771705d5d160342a7b3b5c5a311ed224a002c441bd5c2d4eae4d3ee5cf"
    ),
    "function.annotations": (
        "sha256:588a10bc34079eb599d5dba191be126fa067675400427d6b9191d348c32d98a4"
    ),
    "protein.prompt": (
        "sha256:6e95a89810d7cba459009d6b798b9d9290180af0c020d868ad8bd3bc72ef7b44"
    ),
    "protein.sequence": (
        "sha256:914c2c5b605073080b29dbaf8c83decbd7f98cc2d2455311f5865f2fcee9c3a0"
    ),
    "protein.structure": (
        "sha256:329ebc4c4f2c3323afa7577999882ef51a7588e5803be4d2b0da5d6e07fe8e0b"
    ),
    "residue.layout": (
        "sha256:c0b66618ee52d36bda8f857cb422f195152ecfebfc4ed48a45e3924edacb08fd"
    ),
    "residue.map": (
        "sha256:49fb91759842c064b47b337dc1c6568b1e3035b6965286dcd29a95bcf6525b52"
    ),
    "residue.track": (
        "sha256:db5a52f8c6920365a31bacf221e5e9eb23c4b5aea4de696f69c01bd084738707"
    ),
    "residue.track.sasa": (
        "sha256:3bb4d6175604f3bfe346cf078ea78014a5cf2a44196603ee7d28f6b4d299942f"
    ),
    "residue.track.secondary_structure": (
        "sha256:9203923af8490d9f3947cdd3b0dd9fc48727aa3aaa61cfea8ede2087046c4890"
    ),
    "score.collection": (
        "sha256:369193274cf356a6814a81a15d9261467c6eac8768888cfe2643fe5f605d385e"
    ),
    "text": (
        "sha256:deccc91ef2b9b94ad5d14637690c6de2f7b8ea7ff75c401faca95510cf3381c3"
    ),
}
EXPECTED_BUILTIN_PORT_TYPE_IDS = EXPECTED_PORT_TYPE_IDS - {
    "function.annotations",
    "protein.prompt",
}


def test_superseded_structure_alignment_port_type_is_not_active() -> None:
    for catalog in (
        builtin_frozen_catalog(),
        build_discovered_frozen_catalog(),
    ):
        with pytest.raises(UnknownPortTypeError):
            catalog.require_port_type(
                "structure.alignment",
                "2.1.0",
            )


def _typed_observation(value: object) -> ScoreObservation:
    return ScoreObservation(
        subject=CandidateDataReference(
            "candidate-1",
            "protein.sequence",
            "sha256:" + ("3" * 64),
        ),
        metric=ExactContractReference(
            "metric",
            "metric.plddt",
            "2.1.0",
            "sha256:" + ("1" * 64),
        ),
        method=ExactContractReference(
            "method",
            "method.fixture",
            "2.1.0",
            "sha256:" + ("2" * 64),
        ),
        context=IntrinsicObservationContext(),
        value=value,
)


PROTEINMPNN_TEST_LAYOUT = ResidueLayout(
    "A",
    3,
    ["A:1", "A:2", "A:3"],
)


def test_catalog_snapshot_publishes_exact_port_type_contracts() -> None:
    catalog = build_discovered_frozen_catalog()
    with TestClient(create_app()) as client:
        response = client.get("/api/v2/catalog")

    assert response.status_code == 200
    payload = response.json()
    validate_response("catalog_snapshot", 200, payload)
    assert payload["schema_namespace"] == "protein-workbench-public/v2"
    assert re.fullmatch(
        r"sha256:[0-9a-f]{64}",
        payload["catalog_contract_digest"],
    )
    observed_availability = {
        (
            snapshot["binding"]["contract_id"],
            snapshot["binding"]["contract_version"],
            snapshot["available"],
        )
        for snapshot in payload["availability"]
    }
    expected_availability = {
        (
            snapshot["binding"]["contract_id"],
            snapshot["binding"]["contract_version"],
            snapshot["available"],
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
            "contract_version": descriptor["contract_version"],
            "contract_digest": EXPECTED_PORT_TYPE_DIGESTS[
                descriptor["contract_id"]
            ],
        }
        assert reference["contract_digest"] == canonical_sha256(descriptor)
        assert descriptor["schema_namespace"] == (
            "protein-workbench-contract/v2"
        )
        assert descriptor["contract_kind"] == "port_type"
        assert descriptor["contract_version"] == EXPECTED_PORT_TYPE_VERSIONS[
            descriptor["contract_id"]
        ]
        assert set(descriptor) == {
            "schema_namespace",
            "contract_kind",
            "contract_id",
            "contract_version",
            "validator",
            "codec",
            "content_identity",
        }
        assert re.fullmatch(
            r"sha256:[0-9a-f]{64}",
            reference["contract_digest"],
        )
        for behavior_name in ("validator", "codec", "content_identity"):
            behavior = descriptor[behavior_name]
            assert set(behavior) == {
                "behavior_id",
                "behavior_version",
                "parameters",
            }
            assert behavior["behavior_version"] == (
                EXPECTED_PORT_TYPE_VERSIONS[descriptor["contract_id"]]
            )


def test_port_type_codec_round_trips_a_complete_valid_value() -> None:
    port_type = builtin_frozen_catalog().require_port_type(
        "protein.sequence",
        "3.0.0",
    )
    value = ProteinSequence(
        sequence="META",
        residue_ids=["A:1", "A:2", "A:3", "A:4"],
    )

    encoded = port_type.encode(value)

    assert encoded == (
        b'{"port_type_id":"protein.sequence","port_type_version":"3.0.0",'
        b'"schema_namespace":"protein-workbench-port-value/v2","value":'
        b'{"$dataclass":"protein_sequence","fields":{"residue_ids":'
        b'["A:1","A:2","A:3","A:4"],"sequence":"META"}}}'
    )
    assert port_type.decode(encoded) == value
    assert port_type.content_digest(value) == (
        "sha256:ddb925c1ae9cd8b03ff8803c5b578c2fdaa82bc5edb435fb5b8b25857f4497e3"
    )


def test_protein_sequence_cuts_caller_aliases_without_changing_wire_bytes() -> None:
    residue_ids = ["A:1", "A:2"]
    value = ProteinSequence("MA", residue_ids)
    residue_ids.append("A:3")

    assert value.residue_ids == ("A:1", "A:2")
    with pytest.raises(FrozenInstanceError):
        value.sequence = "AA"

    port_type = builtin_frozen_catalog().require_port_type(
        "protein.sequence",
        "3.0.0",
    )
    encoded = port_type.encode(value)

    assert b'"$tuple"' not in encoded
    assert b'"residue_ids":["A:1","A:2"]' in encoded
    assert port_type.decode(encoded) == value


@pytest.mark.parametrize("sequence", ("ma", "MÉTA", "MA*"))
def test_protein_sequence_admission_requires_the_exact_uppercase_alphabet(
    sequence: str,
) -> None:
    port_type = builtin_frozen_catalog().require_port_type(
        "protein.sequence",
        "3.0.0",
    )

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
        "protein.sequence",
        "3.0.0",
    )

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
        "protein.sequence",
        "3.0.0",
    )
    canonical = port_type.encode(
        ProteinSequence("MA", ("A:1", "A:2"))
    )

    with pytest.raises(PortValueError, match=message):
        port_type.decode(canonical.replace(old, new))


def test_protein_sequence_does_not_claim_residue_layout_chain_contiguity() -> None:
    port_type = builtin_frozen_catalog().require_port_type(
        "protein.sequence",
        "3.0.0",
    )
    sequence = ProteinSequence(
        "MAG",
        ("A:1", "B:1", "A:2"),
    )

    assert port_type.decode(port_type.encode(sequence)) == sequence


def test_builtin_sequence_and_candidate_descriptors_declare_identity_invariants(
) -> None:
    catalog = builtin_frozen_catalog()

    assert catalog.require_port_type(
        "protein.sequence",
        "3.0.0",
    ).validator.parameters["sequence_invariants"] == {
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
        "candidate.collection",
        "3.0.0",
    ).validator.parameters["candidate_invariants"] == {
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
        "residue.map",
        "3.0.0",
    )

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
            type_id,
            EXPECTED_PORT_TYPE_VERSIONS[type_id],
        )
        definition.validate(value)
        assert definition.decode(definition.encode(value)) == value


def test_protein_structure_scientific_identity_excludes_source_provenance() -> None:
    port_type = builtin_frozen_catalog().require_port_type(
        "protein.structure",
        "4.0.0",
    )
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
        "sha256:b59a5d5b5422e4473900b689291474ccfc9ec525b3663f4b5c35c53c8edcff0f"
    )
    legacy_wire = canonical_json_bytes({
        "schema_namespace": "protein-workbench-port-value/v2",
        "port_type_id": "protein.structure",
        "port_type_version": "4.0.0",
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
        "protein.structure",
        "4.0.0",
    )

    with pytest.raises(PortValueError, match="canonical PDB"):
        port_type.encode(ProteinStructure(pdb_string))


def test_protein_structure_admission_does_not_impose_single_model_or_ca() -> None:
    port_type = builtin_frozen_catalog().require_port_type(
        "protein.structure",
        "4.0.0",
    )
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
        "protein.structure",
        "4.0.0",
    )
    structure = ProteinStructure(
        f"{record_name:<6} canonical metadata\n"
        "ATOM      1  N   ALA A   1       0.000   0.000   0.000"
        "  1.00 20.00           N  \n"
        "END\n"
    )

    assert port_type.decode(port_type.encode(structure)) == structure


def test_protein_structure_admission_preserves_pdb_residue_number_zero() -> None:
    port_type = builtin_frozen_catalog().require_port_type(
        "protein.structure",
        "4.0.0",
    )
    structure = ProteinStructure(
        "ATOM      1  N   ALA A   0       0.000   0.000   0.000"
        "  1.00 20.00           N  \nEND\n"
    )

    assert port_type.decode(port_type.encode(structure)) == structure


def test_protein_structure_admission_accepts_standard_padded_end_record() -> None:
    port_type = builtin_frozen_catalog().require_port_type(
        "protein.structure",
        "4.0.0",
    )
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
        "residue.layout",
        "3.0.0",
    )

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
        "residue.map",
        "3.0.0",
    )

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
        "protein.sequence",
        "3.0.0",
    )
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
        type_id,
        EXPECTED_PORT_TYPE_VERSIONS[type_id],
    )

    with pytest.raises(
        PortValueError,
        match="requires|must|mismatch|does not match",
    ):
        definition.encode(malformed)


def test_canonical_constructors_close_domain_invariants_before_encoding() -> None:
    from core import build_discovered_frozen_catalog

    catalog = build_discovered_frozen_catalog()
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
                type_id,
                EXPECTED_PORT_TYPE_VERSIONS[type_id],
            ).encode(malformed)


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
    from core import build_discovered_frozen_catalog

    definition = build_discovered_frozen_catalog().require_port_type(
        "proteinmpnn.constraints",
        "4.0.0",
    )

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
        "score.collection",
        "4.0.0",
    )
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


def test_behavior_declarations_require_exact_versions_and_i_json() -> None:
    with pytest.raises(CatalogBuildError, match="exact semantic version"):
        BehaviorReference("example.validate", "", {})
    with pytest.raises(CatalogBuildError, match="negative zero"):
        BehaviorReference("example.validate", "2.1.0", {"threshold": -0.0})
    with pytest.raises(CatalogBuildError, match="NaN|Infinity"):
        BehaviorReference(
            "example.validate",
            "2.1.0",
            {"threshold": float("nan")},
        )
    with pytest.raises(CatalogBuildError, match="exact semantic version"):
        BehaviorReference("example.validate", "2.1.0+local", {})


def test_behavior_declaration_parameters_are_deeply_immutable() -> None:
    supplied = {"schema": {"required": ["sequence"]}}
    behavior = BehaviorReference(
        "example.validate",
        "2.1.0",
        supplied,
    )

    supplied["schema"]["required"].append("residue_ids")

    assert behavior.descriptor()["parameters"] == {
        "schema": {"required": ["sequence"]}
    }
    with pytest.raises(TypeError):
        behavior.parameters["schema"]["new_field"] = True


def test_direct_connections_require_exact_known_nominal_identity() -> None:
    catalog = builtin_frozen_catalog()

    assert catalog.directly_compatible(
        "protein.sequence",
        "3.0.0",
        "protein.sequence",
        "3.0.0",
    )
    assert not catalog.directly_compatible(
        "residue.track",
        "2.1.0",
        "residue.track.secondary_structure",
        "2.1.0",
    )
    assert not catalog.directly_compatible(
        "protein.sequence",
        "3.0.0",
        "text",
        "2.1.0",
    ), "scientific conversion must be represented by an explicit Node Type"

    for unknown_id, unknown_version in (
        ("unknown.type", "2.1.0"),
        ("protein.sequence", "1.0.0"),
        ("protein.sequence", ">=2"),
    ):
        with pytest.raises(UnknownPortTypeError):
            catalog.directly_compatible(
                unknown_id,
                unknown_version,
                "protein.sequence",
                "3.0.0",
            )


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


def test_builtin_port_type_contract_digests_match_golden_vectors() -> None:
    catalog = builtin_frozen_catalog()

    assert {
        definition.type_id: definition.contract_digest
        for definition in catalog.port_types
    } == {
        type_id: EXPECTED_PORT_TYPE_DIGESTS[type_id]
        for type_id in EXPECTED_BUILTIN_PORT_TYPE_IDS
    }
    assert catalog.contract_digest == (
        "sha256:e1fb6c90341d4c09fef7fad7e030057c1500cf24edb4293cc14f18719da299b3"
    )


def _example_port_type(
    *,
    validator_parameters: dict[str, object] | None = None,
    validator_version: str = "2.1.0",
) -> PortTypeDefinition:
    return PortTypeDefinition(
        type_id="example.text",
        version="2.1.0",
        validator=BehaviorReference(
            "example.text/validate",
            validator_version,
            (
                {"accepted_value_kind": "text", "complete_values_only": True}
                if validator_parameters is None
                else validator_parameters
            ),
        ),
        codec=BehaviorReference(
            "example.text/codec",
            "2.1.0",
            {},
        ),
        content_identity=BehaviorReference(
            "example.text/content",
            "2.1.0",
            {},
        ),
    )


def test_port_type_descriptor_differentials_are_semantic_and_path_free() -> None:
    first = _example_port_type(
        validator_parameters={
            "accepted_value_kind": "text",
            "complete_values_only": True,
            "label": "é",
        }
    )
    reordered = _example_port_type(
        validator_parameters={
            "label": "é",
            "complete_values_only": True,
            "accepted_value_kind": "text",
        }
    )
    decomposed_unicode = _example_port_type(
        validator_parameters={
            "accepted_value_kind": "text",
            "complete_values_only": True,
            "label": "e\u0301",
        }
    )
    changed_behavior = _example_port_type(validator_version="2.0.1")
    explicit_defaults = _example_port_type()

    assert first.descriptor_bytes == reordered.descriptor_bytes
    assert first.contract_digest == reordered.contract_digest
    assert first.contract_digest != decomposed_unicode.contract_digest
    assert explicit_defaults.descriptor()["codec"]["parameters"] == {}
    assert explicit_defaults.contract_digest != changed_behavior.contract_digest
    assert b"/Users/" not in first.descriptor_bytes
    assert b"0x" not in first.descriptor_bytes

    with pytest.raises(CatalogBuildError, match="cannot be represented"):
        BehaviorReference(
            "example.text/validate",
            "2.1.0",
            {"callable": object()},
        )


def test_runtime_callables_never_enter_stable_contract_identity() -> None:
    declaration = {
        "accepted_value_kind": "extension.sequence",
        "complete_values_only": True,
    }

    def build_definition() -> PortTypeDefinition:
        return PortTypeDefinition(
            type_id="extension.sequence",
            version="2.1.0",
            validator=BehaviorReference(
                "extension.sequence/validate",
                "2.1.0",
                declaration,
            ),
            codec=BehaviorReference(
                "extension.sequence/codec",
                "2.1.0",
                {},
            ),
            content_identity=BehaviorReference(
                "extension.sequence/content",
                "2.1.0",
                {},
            ),
            runtime_validator=lambda value: (
                None
                if isinstance(value, str) and value.isalpha()
                else (_ for _ in ()).throw(ValueError("invalid sequence"))
            ),
            runtime_to_wire=lambda value: value,
            runtime_from_wire=lambda value: value,
        )

    source_definition = build_definition()
    installed_definition = build_definition()
    source_catalog = FrozenCatalog((source_definition,))
    installed_catalog = FrozenCatalog((installed_definition,))

    assert source_definition.descriptor_bytes == (
        installed_definition.descriptor_bytes
    )
    assert source_definition.contract_digest == (
        installed_definition.contract_digest
    )
    assert source_catalog.catalog_descriptor_bytes == (
        installed_catalog.catalog_descriptor_bytes
    )
    assert source_definition.decode(source_definition.encode("MÉTA")) == "MÉTA"
    assert b"<lambda>" not in source_definition.descriptor_bytes
    assert b"0x" not in source_definition.descriptor_bytes


def test_codec_differentials_materialize_defaults_and_preserve_semantic_order() -> None:
    catalog = builtin_frozen_catalog()
    sequence_type = catalog.require_port_type("protein.sequence", "3.0.0")
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
    original_digest = published.contract_digest
    duplicate = published.require_port_type("text", "2.1.0")

    with pytest.raises(CatalogBuildError, match="duplicate Port Type identity"):
        FrozenCatalog((*published.port_types, duplicate))

    assert published.contract_digest == original_digest


def test_direct_catalog_construction_rejects_multiple_active_port_versions() -> None:
    published = builtin_frozen_catalog()
    current = published.require_port_type("text", "2.1.0")
    incompatible = replace(current, version="3.0.0")

    with pytest.raises(
        CatalogBuildError,
        match="multiple active versions for contract port_type:text",
    ):
        FrozenCatalog((current, incompatible))
