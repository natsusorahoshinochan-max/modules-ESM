"""Public contract tests for canonical nominal Port Types."""

from __future__ import annotations

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
    IntrinsicObservationContext,
    ProteinMPNNConstraints,
    ProteinPrompt,
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
    "file.path",
    "file.path.collection",
    "function.annotations",
    "protein.prompt",
    "protein.sequence",
    "protein.structure",
    "proteinmpnn.constraints",
    "residue.layout",
    "residue.map",
    "residue.track",
    "residue.track.sasa",
    "residue.track.secondary_structure",
    "score.collection",
    "structure.alignment",
    "text",
}
EXPECTED_PORT_TYPE_DIGESTS = {
    "candidate.collection": (
        "sha256:9bb806e8f171a89c82e89d47e0e47da4eed2c4977ad09899d4d60dc7e28bda00"
    ),
    "file.path": (
        "sha256:1076b1d3c0159655b5a558dc81dac3069d894720634f743e1a124cca1ac91e91"
    ),
    "file.path.collection": (
        "sha256:9b136ff44781a1e762a481cd9a7dbdbf4381e17475373229af57b856de8a6357"
    ),
    "function.annotations": (
        "sha256:81b9d7d9c345101657abb0f229b08a8db0827336b3b145cb146702f3c44865f9"
    ),
    "protein.prompt": (
        "sha256:1a8c19fdc37c71839d234b7785c35d430fa960939be768710f2a16b1fc30afd9"
    ),
    "protein.sequence": (
        "sha256:5e4ca2f126c449f784b80de3815e717dea84e54205391eff0a68ffefc5527e91"
    ),
    "protein.structure": (
        "sha256:5e15d0d47a0d0f95049e278756366461f0ec80817f72e742a6f023678b6ec90d"
    ),
    "proteinmpnn.constraints": (
        "sha256:36db16305da2a755c0a06481512524ac5a2b9693876aaeae31b71e2bf2a66b98"
    ),
    "residue.layout": (
        "sha256:911e7f11d03a26372aec750751caba34a934fefd64f041d9e8cce7c947f71ab0"
    ),
    "residue.map": (
        "sha256:ef6249643614d5c80f6354ac9d42b6b781bf4149f7cc4cfe8e9b965824e8c6ae"
    ),
    "residue.track": (
        "sha256:657b6729cfb0bcceb2be842b2f81882ed432607e49a93b30f7398a10ac369cc6"
    ),
    "residue.track.sasa": (
        "sha256:544e17a843a8561dd4fbfb56d84f85069595fb7636a3664572ab2687ad5efbdf"
    ),
    "residue.track.secondary_structure": (
        "sha256:7ca6d963ec3c855defc49110b1c0bd0c6e4216fe18573e89b5df27af4af7a56c"
    ),
    "score.collection": (
        "sha256:830dcf99fdd861b0036d2082b3ad1e93a2dd894e7a909608c835a5458c4339e7"
    ),
    "structure.alignment": (
        "sha256:7b93f80914d0b7347eb40b7e2214f737d08bf7b78fda1da7602a009b8e0b927b"
    ),
    "text": (
        "sha256:f5f7a90c1c9c0743fd50abfba417d2e444f680b02bca120be0f7719da31a5ea0"
    ),
}


def _typed_observation(value: object) -> ScoreObservation:
    return ScoreObservation(
        candidate_id="candidate-1",
        metric=ExactContractReference(
            "metric",
            "metric.plddt",
            "2.0.0",
            "sha256:" + ("1" * 64),
        ),
        method=ExactContractReference(
            "method",
            "method.fixture",
            "2.0.0",
            "sha256:" + ("2" * 64),
        ),
        context=IntrinsicObservationContext(),
        value=value,
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
    assert payload["availability"] == []

    contracts = payload["contracts"]
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
        assert descriptor["contract_version"] == "2.0.0"
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
            assert behavior["behavior_version"] == "2.0.0"


def test_port_type_codec_round_trips_a_complete_valid_value() -> None:
    port_type = builtin_frozen_catalog().require_port_type(
        "protein.sequence",
        "2.0.0",
    )
    value = ProteinSequence(
        sequence="MÉTA",
        residue_ids=["A:1", "A:2", "A:3", "A:4"],
    )

    encoded = port_type.encode(value)

    assert encoded == (
        b'{"port_type_id":"protein.sequence","port_type_version":"2.0.0",'
        b'"schema_namespace":"protein-workbench-port-value/v2","value":'
        b'{"$dataclass":"protein_sequence","fields":{"residue_ids":'
        b'["A:1","A:2","A:3","A:4"],"sequence":"M\xc3\x89TA"}}}'
    )
    assert port_type.decode(encoded) == value
    assert port_type.content_digest(value) == (
        "sha256:b5351bf0959b681459946858a424aada77a1c5b921acf482afac5c9d78d56eee"
    )


def test_every_builtin_port_type_round_trips_its_runtime_value() -> None:
    sequence = ProteinSequence("MA", ["A:1", "A:2"])
    structure = ProteinStructure("ATOM\nEND\n", "fixture")
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
        "file.path": "artifacts/result.pdb",
        "file.path.collection": ["artifacts/a.pdb", "artifacts/b.pdb"],
        "function.annotations": FunctionAnnotations(
            [{"label": "binding", "start": 0, "end": 2}]
        ),
        "protein.prompt": ProteinPrompt(
            target_layout=layout,
            sequence_track=track,
            secondary_structure_track=ResidueTrack(["H", "E"], None),
            function_annotations=FunctionAnnotations(),
        ),
        "protein.sequence": sequence,
        "protein.structure": structure,
        "proteinmpnn.constraints": ProteinMPNNConstraints(
            fixed_positions=[0],
            designed_chains=["A"],
            tied_positions=[[0, 1]],
            bias_by_res={2: {"A": 0.5}},
        ),
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
        "text": "α-helix",
    }
    catalog = builtin_frozen_catalog()

    assert set(samples) == EXPECTED_PORT_TYPE_IDS
    for type_id, value in samples.items():
        definition = catalog.require_port_type(type_id, "2.0.0")
        definition.validate(value)
        assert definition.decode(definition.encode(value)) == value


def test_codec_rejects_malformed_and_noncanonical_values() -> None:
    sequence_type = builtin_frozen_catalog().require_port_type(
        "protein.sequence",
        "2.0.0",
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

    constraints_type = builtin_frozen_catalog().require_port_type(
        "proteinmpnn.constraints",
        "2.0.0",
    )
    constraints = constraints_type.encode(
        ProteinMPNNConstraints(bias_by_res={1: {"A": 0.5}, 2: {"V": -0.5}})
    )
    with pytest.raises(PortValueError, match="canonical key order"):
        constraints_type.decode(
            constraints.replace(
                b'[[1,{"$map":[["A",0.5]]}],[2,{"$map":[["V",-0.5]]}]]',
                b'[[2,{"$map":[["V",-0.5]]}],[1,{"$map":[["A",0.5]]}]]',
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
    definition = builtin_frozen_catalog().require_port_type(type_id, "2.0.0")

    with pytest.raises(
        PortValueError,
        match="requires|must|mismatch|does not match",
    ):
        definition.encode(malformed)


def test_runtime_validators_recheck_mutable_domain_invariants() -> None:
    catalog = builtin_frozen_catalog()
    sequence = ProteinSequence("MA", ["A:1", "A:2"])
    sequence.residue_ids = ["A:1"]
    layout = ResidueLayout("A", 1, ["A:1"])
    layout.length = -1
    malformed_values = [
        ("protein.sequence", sequence),
        ("residue.layout", layout),
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
            catalog.require_port_type(type_id, "2.0.0").encode(malformed)


@pytest.mark.parametrize(
    "constraints",
    [
        ProteinMPNNConstraints(tied_positions=[[0]]),
        ProteinMPNNConstraints(
            designable_positions=[0],
            fixed_positions=[0],
        ),
        ProteinMPNNConstraints(omit_amino_acids=["B"]),
        ProteinMPNNConstraints(bias_by_res={0: {"B": 1.0}}),
    ],
)
def test_proteinmpnn_port_reuses_the_authoritative_constraint_contract(
    constraints: ProteinMPNNConstraints,
) -> None:
    definition = builtin_frozen_catalog().require_port_type(
        "proteinmpnn.constraints",
        "2.0.0",
    )

    with pytest.raises(PortValueError):
        definition.encode(constraints)


def test_proteinmpnn_port_rechecks_constraints_after_mutation() -> None:
    constraints = ProteinMPNNConstraints(tied_positions=[[0, 1]])
    definition = builtin_frozen_catalog().require_port_type(
        "proteinmpnn.constraints",
        "2.0.0",
    )
    definition.validate(constraints)

    constraints.tied_positions[0].pop()

    with pytest.raises(PortValueError, match="at least two positions"):
        definition.encode(constraints)


@pytest.mark.parametrize("invalid_value", [-0.0, float("nan"), float("inf")])
def test_codec_rejects_non_i_json_numbers(invalid_value: float) -> None:
    score_type = builtin_frozen_catalog().require_port_type(
        "score.collection",
        "2.0.0",
    )
    value = ScoreCollection(
        "scores",
        [_typed_observation(invalid_value)],
    )

    with pytest.raises(PortValueError, match="negative zero|NaN|Infinity"):
        score_type.encode(value)


def test_behavior_declarations_require_exact_versions_and_i_json() -> None:
    with pytest.raises(CatalogBuildError, match="exact semantic version"):
        BehaviorReference("example.validate", "", {})
    with pytest.raises(CatalogBuildError, match="negative zero"):
        BehaviorReference("example.validate", "2.0.0", {"threshold": -0.0})
    with pytest.raises(CatalogBuildError, match="NaN|Infinity"):
        BehaviorReference(
            "example.validate",
            "2.0.0",
            {"threshold": float("nan")},
        )
    with pytest.raises(CatalogBuildError, match="exact semantic version"):
        BehaviorReference("example.validate", "2.0.0+local", {})


def test_behavior_declaration_parameters_are_deeply_immutable() -> None:
    supplied = {"schema": {"required": ["sequence"]}}
    behavior = BehaviorReference(
        "example.validate",
        "2.0.0",
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
        "2.0.0",
        "protein.sequence",
        "2.0.0",
    )
    assert not catalog.directly_compatible(
        "residue.track",
        "2.0.0",
        "residue.track.secondary_structure",
        "2.0.0",
    )
    assert not catalog.directly_compatible(
        "protein.sequence",
        "2.0.0",
        "text",
        "2.0.0",
    ), "scientific conversion must be represented by an explicit Node Type"

    for unknown_id, unknown_version in (
        ("unknown.type", "2.0.0"),
        ("protein.sequence", "1.0.0"),
        ("protein.sequence", ">=2"),
    ):
        with pytest.raises(UnknownPortTypeError):
            catalog.directly_compatible(
                unknown_id,
                unknown_version,
                "protein.sequence",
                "2.0.0",
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
    } == EXPECTED_PORT_TYPE_DIGESTS
    assert catalog.contract_digest == (
        "sha256:2e9cf22693fb9cd74b689c401f125a99e20512ab4bcf8f513b2274e2baea9e3d"
    )


def _example_port_type(
    *,
    validator_parameters: dict[str, object] | None = None,
    validator_version: str = "2.0.0",
) -> PortTypeDefinition:
    return PortTypeDefinition(
        type_id="example.text",
        version="2.0.0",
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
            "2.0.0",
            {},
        ),
        content_identity=BehaviorReference(
            "example.text/content",
            "2.0.0",
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
            "2.0.0",
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
            version="2.0.0",
            validator=BehaviorReference(
                "extension.sequence/validate",
                "2.0.0",
                declaration,
            ),
            codec=BehaviorReference(
                "extension.sequence/codec",
                "2.0.0",
                {},
            ),
            content_identity=BehaviorReference(
                "extension.sequence/content",
                "2.0.0",
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
    sequence_type = catalog.require_port_type("protein.sequence", "2.0.0")
    constraints_type = catalog.require_port_type(
        "proteinmpnn.constraints",
        "2.0.0",
    )
    first_map_order = ProteinMPNNConstraints(
        bias_by_res={2: {"V": -0.5}, 1: {"A": 0.5}},
    )
    second_map_order = ProteinMPNNConstraints(
        bias_by_res={1: {"A": 0.5}, 2: {"V": -0.5}},
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
    duplicate = published.require_port_type("text", "2.0.0")

    with pytest.raises(CatalogBuildError, match="duplicate Port Type identity"):
        FrozenCatalog((*published.port_types, duplicate))

    assert published.contract_digest == original_digest
