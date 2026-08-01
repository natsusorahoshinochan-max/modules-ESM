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
    canonical_json_bytes,
    canonical_sha256,
)
from core import builtin_frozen_catalog
from core.server import create_app
from datatypes import (
    Candidate,
    CandidateCollection,
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
    StructureAlignment,
)
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
    "structure.alignment",
    "text",
}
EXPECTED_PORT_TYPE_VERSIONS = {
    type_id: "3.0.0" if type_id == "protein.structure" else "2.1.0"
    for type_id in EXPECTED_PORT_TYPE_IDS
}
EXPECTED_PORT_TYPE_DIGESTS = {
    "candidate.collection": (
        "sha256:6425b44763bd03b2987d9c78e3675e11733416af7dafd01714f9ac121568685c"
    ),
    "candidate.pairing": (
        "sha256:87f96a0b1047dc84683c7f6692ae085470fe68ee45cec2fbf697ac4d76b91c30"
    ),
    "function.annotations": (
        "sha256:eb7d7dd6dbe6fc62569d5f8fadcc52793e2cf4f5bb43387b892c8161671cfded"
    ),
    "protein.prompt": (
        "sha256:87227c64305f9ac6b10203be5c72b3dd22bb96ba2aeb96d20ae750f2226e9607"
    ),
    "protein.sequence": (
        "sha256:36ce4a625ff63ce0f90cebba84b4d72285054bebc74cc05119d241428ec9e533"
    ),
    "protein.structure": (
        "sha256:cd09d43e3229ca3dedfb5d57c2b154f65629e3da6038d8459b74282015bb60e0"
    ),
    "residue.layout": (
        "sha256:ff3f084e99dab615dcab848d4dd8af3b36622c53e1cf095cbc4d53b873eefb33"
    ),
    "residue.map": (
        "sha256:45889114e3e917fdb42f40bec014fbb94abcdbf050ce9e7e92866e0595142a9c"
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
        "sha256:f8575371f045e3405e2633ac2fbcd02a3df214a654b7570a021324e44387bb4d"
    ),
    "structure.alignment": (
        "sha256:b107487cbcb85b90552bc7750e1b115662beebe64a3e4abc744cf0b9abea0746"
    ),
    "text": (
        "sha256:deccc91ef2b9b94ad5d14637690c6de2f7b8ea7ff75c401faca95510cf3381c3"
    ),
}
EXPECTED_BUILTIN_PORT_TYPE_IDS = EXPECTED_PORT_TYPE_IDS - {
    "function.annotations",
    "protein.prompt",
}


def _typed_observation(value: object) -> ScoreObservation:
    return ScoreObservation(
        candidate_id="candidate-1",
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
    assert {
        (
            snapshot["binding"]["contract_id"],
            snapshot["binding"]["contract_version"],
            snapshot["available"],
        )
        for snapshot in payload["availability"]
    } == {
        (
            "collection_ops.concat_candidates.direct",
            "2.1.0",
            True,
        ),
        ("collection_ops.merge_scores.direct", "2.1.0", True),
            (
                "collection_ops.rebind_candidate_pairing.direct",
                "2.1.0",
                True,
            ),
            (
                "collection_ops.pair_siblings_by_parent.direct",
                "2.1.0",
                True,
            ),
        ("collection_ops.take_candidates.direct", "2.1.0", True),
            ("selection.filter.direct", "2.1.0", True),
            ("selection.sort.direct", "2.1.0", True),
            ("selection.top_k.direct", "2.1.0", True),
            ("selection.weighted_rank.direct", "2.1.0", True),
            ("selection.pareto.direct", "2.1.0", True),
            ("selection.diversity.direct", "2.1.0", True),
            ("esm3.generate_paired.biohub_medium", "3.0.0", True),
        ("esm3.generate_sequence.biohub_medium", "3.0.0", True),
        ("esm3.generate_structure.biohub_medium", "3.0.0", True),
        ("esm3.generate_paired.biohub_open", "3.0.0", True),
        ("esm3.generate_sequence.biohub_open", "3.0.0", True),
        ("esm3.generate_structure.biohub_open", "3.0.0", True),
        ("esm3.generate_paired.local_open", "3.0.0", True),
        ("esm3.generate_sequence.local_open", "3.0.0", True),
        ("esm3.generate_structure.local_open", "3.0.0", True),
        (
            "esm3.represent_sequence.biohub_esmc_600m_2024_12",
            "2.2.0",
            True,
        ),
        ("folding.fold.esmfold2_remote", "3.0.0", True),
            ("folding.fold.esmfold2_local", "3.0.0", True),
            ("folding.fold.simplefold_local", "3.0.0", True),
            (
                "folding.simplefold_confidence.simplefold_local",
                "2.2.0",
                True,
            ),
        ("protein_io.import_sequence.direct", "3.0.0", True),
        ("protein_io.import_structure.direct", "3.0.0", True),
        ("protein_io.export_sequence.direct", "2.1.0", True),
        ("protein_io.export_structure.direct", "3.0.0", True),
        (
            "prompt_authoring.add_function_annotation.direct",
            "2.1.0",
            True,
        ),
        (
            "prompt_authoring.assemble_protein_prompt.direct",
            "2.1.0",
            True,
        ),
        ("prompt_authoring.build_residue_layout.direct", "2.1.0", True),
            ("prompt_authoring.edit_residue_layout.direct", "2.1.0", True),
            (
                "prompt_authoring.insert_masked_residues.direct",
                "2.1.0",
                True,
            ),
        ("prompt_authoring.map_residue_track.direct", "2.1.0", True),
        (
            "prompt_authoring.override_protein_prompt_track.direct",
            "2.1.0",
            True,
        ),
        ("prompt_authoring.override_residue_track.direct", "2.1.0", True),
        ("prompt_authoring.prompt_from_structure.direct", "3.0.0", True),
        (
            "prompt_authoring.random_insert_masked.direct",
            "2.1.0",
            True,
        ),
        ("prompt_authoring.random_mask.direct", "2.1.0", True),
        (
            "prompt_authoring.update_prompt_sequence.direct",
            "2.1.0",
            True,
        ),
        ("proteinmpnn.constraints.local", "3.0.0", True),
        (
            "proteinmpnn.random_fixed_positions.local",
            "3.0.0",
            True,
        ),
        ("proteinmpnn.design.local", "4.0.0", True),
        ("proteinmpnn.score.local", "2.1.0", True),
            ("solubility.soluprot_full.local", "2.1.0", True),
            ("solubility.soluprot_no_tm.local", "2.1.0", True),
            ("solubility.protein_sol.local", "2.1.0", True),
            ("structure_transform.select_chains.direct", "3.0.0", True),
            (
                "structure_transform.select_candidate_chains.direct",
                "2.1.0",
                True,
            ),
            ("structure_transform.extract_backbone.direct", "3.0.0", True),
            ("structure_transform.extract_sequence.direct", "3.0.0", True),
            (
                "structure_transform.extract_sequence_candidates.direct",
                "2.1.0",
                True,
            ),
            (
                "structure_transform.normalize_csh_parent_span.direct",
                "3.0.0",
                True,
            ),
        (
            "structure_transform.backbone_to_structure.direct",
            "3.0.0",
            True,
        ),
        (
            "structure_annotation.dssp_compute.mkdssp_local",
            "3.0.0",
            True,
        ),
        (
            "structure_annotation.secondary_structure_extract.direct",
            "2.2.0",
            True,
        ),
        ("structure_annotation.sasa_compute.direct", "2.2.0", True),
        (
            "structure_annotation.secondary_structure_agreement.direct",
            "2.2.0",
            True,
        ),
        ("structure_comparison.align_single.direct", "2.1.0", True),
        ("structure_comparison.align_pairwise.direct", "2.2.0", True),
        (
            "structure_comparison.align_pairwise.fixed_reference",
            "2.2.0",
            True,
        ),
        (
            "structure_comparison.rmsd.fixed_reference",
            "2.2.0",
            True,
        ),
        (
            "structure_comparison.rmsd.per_subject_counterpart",
            "2.2.0",
            True,
        ),
        (
            "structure_comparison.tm_score.fixed_reference",
            "2.1.0",
            True,
        ),
        (
            "structure_comparison.batch_tm_score.fixed_reference",
            "2.2.0",
            True,
        ),
        (
            "structure_comparison.batch_tm_score.per_subject_counterpart",
            "2.2.0",
            True,
        ),
    }

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
        "2.1.0",
    )
    value = ProteinSequence(
        sequence="MÉTA",
        residue_ids=["A:1", "A:2", "A:3", "A:4"],
    )

    encoded = port_type.encode(value)

    assert encoded == (
        b'{"port_type_id":"protein.sequence","port_type_version":"2.1.0",'
        b'"schema_namespace":"protein-workbench-port-value/v2","value":'
        b'{"$dataclass":"protein_sequence","fields":{"residue_ids":'
        b'["A:1","A:2","A:3","A:4"],"sequence":"M\xc3\x89TA"}}}'
    )
    assert port_type.decode(encoded) == value
    assert port_type.content_digest(value) == (
        "sha256:22263b9aebbd730a1788b93bc59a7c2a5081fe0fa16a3ec9d15eb577b1bcded6"
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
        "2.1.0",
    )
    encoded = port_type.encode(value)

    assert b'"$tuple"' not in encoded
    assert b'"residue_ids":["A:1","A:2"]' in encoded
    assert port_type.decode(encoded) == value


def test_immutable_residue_map_preserves_2_1_list_and_tuple_wire_semantics() -> None:
    layout = ResidueLayout("A", 1, ["A:1"])
    value = ResidueMap(layout, layout, [(0, 0, "match")])
    port_type = builtin_frozen_catalog().require_port_type(
        "residue.map",
        "2.1.0",
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
    alignment_rotation = [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ]
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
    alignment = StructureAlignment(
        residue_map=[("A:1", "A:1")],
        chain_map={"A": "A"},
        rotation=alignment_rotation,
        translation=[0.0, 0.0, 0.0],
        reference_sequence="A",
        mobile_sequence="A",
        reference_length=1,
        mobile_length=1,
        aligned_reference_indices=[0],
        aligned_mobile_indices=[0],
        aligned_reference_coordinates=[[0.0, 0.0, 0.0]],
        aligned_mobile_coordinates=[[0.0, 0.0, 0.0]],
        aligned_distances=[0.0],
    )
    residue_map = ResidueMap(layout, layout, mappings)
    pairing = PairwiseCandidateMapping([
        PairwiseCandidateMatch(
            "candidate-1",
            "sha256:" + "1" * 64,
            "candidate-2",
            "sha256:" + "2" * 64,
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
    alignment_rotation[0][0] = 0.0
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
    assert alignment.rotation[0] == (1.0, 0.0, 0.0)
    assert pairing.entries[0].subject_candidate_id == "candidate-1"
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
    structure = ProteinStructure("ATOM\nEND\n")
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
        "structure.alignment": StructureAlignment(
            residue_map=[("A:1", "A:1")],
            chain_map={"A": "A"},
            rotation=[
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [0.0, 0.0, 1.0],
            ],
                translation=[0.0, 0.0, 0.0],
                reference_sequence="A",
                mobile_sequence="A",
                reference_length=1,
                mobile_length=1,
                aligned_reference_indices=[0],
                aligned_mobile_indices=[0],
                aligned_reference_coordinates=[[0.0, 0.0, 0.0]],
                aligned_mobile_coordinates=[[0.0, 0.0, 0.0]],
                aligned_distances=[0.0],
            ),
        "candidate.pairing": PairwiseCandidateMapping(
            entries=[
                PairwiseCandidateMatch(
                    subject_candidate_id="candidate-1",
                    subject_content_digest="sha256:" + "1" * 64,
                    reference_candidate_id="reference-1",
                    reference_content_digest="sha256:" + "2" * 64,
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
        "3.0.0",
    )
    pdb_string = "ATOM\nEND\n"
    structure = ProteinStructure(pdb_string)

    assert tuple(item.name for item in fields(ProteinStructure)) == (
        "pdb_string",
    )
    with pytest.raises(TypeError, match="source"):
        ProteinStructure(pdb_string, source="provider")
    assert b'"source"' not in port_type.encode(structure)
    assert port_type.content_digest(structure) == (
        "sha256:d69a23684db136581195d9fe89ff37cdb9ea10701ca873321de7425093fd1700"
    )
    legacy_wire = canonical_json_bytes({
        "schema_namespace": "protein-workbench-port-value/v2",
        "port_type_id": "protein.structure",
        "port_type_version": "3.0.0",
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


def test_codec_rejects_malformed_and_noncanonical_values() -> None:
    sequence_type = builtin_frozen_catalog().require_port_type(
        "protein.sequence",
        "2.1.0",
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
    definition = builtin_frozen_catalog().require_port_type(type_id, "2.1.0")

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
            "structure.alignment",
            StructureAlignment(
                rotation=[[1.0]],
                translation=[0.0],
                coverage=2.0,
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
            catalog.require_port_type(type_id, "2.1.0").encode(malformed)


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
        "3.0.0",
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
        "2.1.0",
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
        "2.1.0",
        "protein.sequence",
        "2.1.0",
    )
    assert not catalog.directly_compatible(
        "residue.track",
        "2.1.0",
        "residue.track.secondary_structure",
        "2.1.0",
    )
    assert not catalog.directly_compatible(
        "protein.sequence",
        "2.1.0",
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
                "2.1.0",
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
        "sha256:e106d275deae5a31ea9e77b3007b4c86566655104864ae2f77aeee64c667de77"
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
    sequence_type = catalog.require_port_type("protein.sequence", "2.1.0")
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
