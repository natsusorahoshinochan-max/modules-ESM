"""Prompt conversion contracts owned by structure annotation."""

from contextlib import contextmanager, nullcontext

import pytest

from core import OperationCall, build_frozen_catalog
from datatypes import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
    FunctionAnnotations,
    ProteinPrompt,
    ProteinStructure,
    ResidueLayout,
    ResidueTrack,
)
from modules.structure_annotation import StructureAnnotationTrack
from modules.structure_annotation.implementation import (
    ApplySASAToPromptOperation,
    ApplySecondaryStructureToPromptOperation,
    ExpectedSecondaryStructureFromPromptOperation,
)
from modules.structure_annotation.package import MODULE_PACKAGE
from tests.fixtures.scientific_operation import admitted_port_fixture


class _RunResources:
    @staticmethod
    def engine_invocation(**kwargs):
        del kwargs
        return nullcontext()


def _operation_call(
    *,
    inputs,
    node_parameters,
    binding_parameters,
    candidate_data=None,
) -> OperationCall:
    references = {} if candidate_data is None else candidate_data
    return OperationCall(
        inputs={
            name: admitted_port_fixture(
                value,
                port_type_id=name,
                value_content_digests=("sha256:" + ("f" * 64),),
                candidate_data=references.get(name, ()),
            )
            for name, value in inputs.items()
        },
        node_parameters=node_parameters,
        binding_parameters=binding_parameters,
        effective_randomness={},
    )


def _candidate_reference(
    candidate_id: str,
    *,
    digest_symbol: str = "a",
) -> CandidateDataReference:
    return CandidateDataReference(
        candidate_id=candidate_id,
        data_type_id="protein.structure",
        content_digest="sha256:" + (digest_symbol * 64),
    )


class _InvocationRecorder:
    def __init__(self) -> None:
        self.invocations = 0

    @contextmanager
    def engine_invocation(self, **kwargs):
        del kwargs
        self.invocations += 1
        yield


def _prompt_authoring_packages():
    from modules.prompt_authoring.package import MODULE_PACKAGE as PROMPT_PACKAGE
    from modules.structure_transform.package import (
        MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
    )

    return (PROMPT_PACKAGE, STRUCTURE_TRANSFORM_PACKAGE)


def test_apply_secondary_structure_to_prompt_maps_exact_ss8_semantics() -> None:
    subject = _candidate_reference("observed-structure")
    layout = ResidueLayout(
        chain_id="A",
        length=9,
        residue_ids=[f"A:{index}" for index in range(1, 10)],
    )
    sequence = ResidueTrack(["A"] * 9, None)
    structure = ResidueTrack(
        [{"CA": [float(index), 0.0, 0.0]} for index in range(9)],
        None,
    )
    visibility = ResidueTrack([True] * 9, None)
    sasa = ResidueTrack([float(index) for index in range(9)], None)
    annotations = FunctionAnnotations(
        [{"label": "active_site", "start": 1, "end": 2}]
    )
    prompt = ProteinPrompt(
        target_layout=layout,
        sequence_track=sequence,
        structure_track=structure,
        structure_visibility_track=visibility,
        secondary_structure_track=ResidueTrack([None] * 9, None),
        sasa_track=sasa,
        function_annotations=annotations,
    )
    source = StructureAnnotationTrack(
        subject=subject,
        layout=layout,
        values=("G", "H", "I", "T", "E", "B", "S", "C", "_"),
    )

    output = ApplySecondaryStructureToPromptOperation(_RunResources()).execute(
        _operation_call(
            inputs={
                "protein_prompt": prompt,
                "secondary_structure_track": source,
            },
            node_parameters={},
            binding_parameters={},
        )
    )

    assert set(output) == {"protein_prompt"}
    updated = output["protein_prompt"]
    assert updated.secondary_structure_track == ResidueTrack(
        ["G", "H", "I", "T", "E", "B", "S", "-", None],
        None,
    )
    assert updated.target_layout is prompt.target_layout
    assert updated.sequence_track is sequence
    assert updated.structure_track is structure
    assert updated.structure_visibility_track is visibility
    assert updated.sasa_track is sasa
    assert updated.function_annotations is annotations

    same_track_other_candidate = StructureAnnotationTrack(
        subject=_candidate_reference(
            "another-observed-structure",
            digest_symbol="b",
        ),
        layout=layout,
        values=source.values,
    )
    other_output = ApplySecondaryStructureToPromptOperation(
        _RunResources()
    ).execute(
        _operation_call(
            inputs={
                "protein_prompt": prompt,
                "secondary_structure_track": same_track_other_candidate,
            },
            node_parameters={},
            binding_parameters={},
        )
    )
    assert other_output == output

    mismatched = StructureAnnotationTrack(
        subject=subject,
        layout=ResidueLayout(
            chain_id="A",
            length=9,
            residue_ids=[f"A:{index}" for index in range(11, 20)],
        ),
        values=source.values,
    )
    with pytest.raises(ValueError, match="layouts must be exactly equal"):
        ApplySecondaryStructureToPromptOperation(_RunResources()).execute(
            _operation_call(
                inputs={
                    "protein_prompt": prompt,
                    "secondary_structure_track": mismatched,
                },
                node_parameters={},
                binding_parameters={},
            )
        )


def test_apply_sasa_to_prompt_preserves_angstrom_squared_values() -> None:
    subject = _candidate_reference("observed-structure")
    layout = ResidueLayout(
        chain_id="A",
        length=4,
        residue_ids=["A:1", "A:2", "A:3", "A:4"],
    )
    secondary = ResidueTrack(["H", "-", None, "E"], None)
    prompt = ProteinPrompt(
        target_layout=layout,
        sequence_track=ResidueTrack(["A", "C", "D", "E"], None),
        secondary_structure_track=secondary,
        sasa_track=ResidueTrack([None] * 4, None),
    )
    source = StructureAnnotationTrack(
        subject=subject,
        layout=layout,
        values=(0.0, 12.5, None, 301.25),
    )

    output = ApplySASAToPromptOperation(_RunResources()).execute(
        _operation_call(
            inputs={"protein_prompt": prompt, "sasa_track": source},
            node_parameters={},
            binding_parameters={},
        )
    )

    updated = output["protein_prompt"]
    assert updated.sasa_track == ResidueTrack([0.0, 12.5, None, 301.25], None)
    assert updated.target_layout is prompt.target_layout
    assert updated.sequence_track is prompt.sequence_track
    assert updated.secondary_structure_track is secondary
    assert updated.function_annotations is prompt.function_annotations

    mismatched = StructureAnnotationTrack(
        subject=subject,
        layout=ResidueLayout(
            chain_id="A",
            length=4,
            residue_ids=["A:11", "A:12", "A:13", "A:14"],
        ),
        values=source.values,
    )
    with pytest.raises(ValueError, match="layouts must be exactly equal"):
        ApplySASAToPromptOperation(_RunResources()).execute(
            _operation_call(
                inputs={"protein_prompt": prompt, "sasa_track": mismatched},
                node_parameters={},
                binding_parameters={},
            )
        )


def test_expected_secondary_structure_from_prompt_restores_annotation_symbols() -> None:
    layout = ResidueLayout(
        chain_id="A",
        length=9,
        residue_ids=[f"A:{index}" for index in range(1, 10)],
    )
    prompt = ProteinPrompt(
        target_layout=layout,
        secondary_structure_track=ResidueTrack(
            ["G", "H", "I", "T", "E", "B", "S", "-", None],
            None,
        ),
    )
    reference = _candidate_reference("reference-structure", digest_symbol="c")
    structure = ProteinStructure(
        "ATOM      1  CA  GLY A   1       "
        "1.000   2.000   3.000  1.00 20.00           C  \n"
        "TER\nEND\n"
    )
    references = CandidateCollection(
        collection_id="reference-structures",
        item_type="protein.structure",
        items=[Candidate(candidate_id=reference.candidate_id, data=structure)],
    )
    output = ExpectedSecondaryStructureFromPromptOperation(
        _RunResources()
    ).execute(
        _operation_call(
            inputs={
                "protein_prompt": prompt,
                "references": references,
            },
            node_parameters={},
            binding_parameters={},
            candidate_data={"references": (reference,)},
        )
    )

    assert output == {
        "secondary_structure_track": StructureAnnotationTrack(
            subject=reference,
            layout=layout,
            values=("G", "H", "I", "T", "E", "B", "S", "C", "_"),
        )
    }
    with pytest.raises(ValueError, match="must carry a secondary-structure track"):
        ExpectedSecondaryStructureFromPromptOperation(_RunResources()).execute(
            _operation_call(
                inputs={
                    "protein_prompt": ProteinPrompt(target_layout=layout),
                    "references": references,
                },
                node_parameters={},
                binding_parameters={},
                candidate_data={"references": (reference,)},
            )
        )


def test_apply_secondary_structure_to_prompt_is_an_exact_direct_node() -> None:
    catalog = build_frozen_catalog((MODULE_PACKAGE, *_prompt_authoring_packages()))

    node = catalog.require_contract(
        "node_type",
        "structure_annotation.apply_secondary_structure_to_prompt",
        "5.0.0",
    ).descriptor
    assert [
        (port["name"], port["port_type"]["contract_id"])
        for port in node["inputs"]
    ] == [
        ("protein_prompt", "protein.prompt"),
        (
            "secondary_structure_track",
            "structure_annotation.secondary_structure_track",
        ),
    ]
    assert [
        (port["name"], port["port_type"]["contract_id"])
        for port in node["outputs"]
    ] == [("protein_prompt", "protein.prompt")]
    assert node["node_parameters"] == {}

    method = catalog.require_contract(
        "method",
        "structure_annotation.apply_secondary_structure_to_prompt.method",
        "2.2.0",
    ).descriptor
    assert method["algorithm_identity"] == {
        "name": "exact-annotation-SS8-to-ProteinPrompt-conditioning",
        "source_alphabet": "GHITEBSC_",
        "target_alphabet": "GHITEBS-",
        "symbol_mapping": {"C": "-", "GHITEBS": "identity", "_": "null"},
        "source_missing_role": "annotation_unavailable",
        "target_missing_role": "prompt_unspecified",
        "layout": "exact_identity",
        "unaffected_prompt_fields": "byte-equivalent-canonical-values",
        "provenance_transition": "observed_annotation_to_prompt_conditioning",
    }

    binding = catalog.require_contract(
        "binding",
        "structure_annotation.apply_secondary_structure_to_prompt.direct",
        "5.0.0",
    ).descriptor
    assert binding["binding_parameters"] == {}
    assert binding["execution_route"] == "direct"
    assert binding["deterministic"] is True
    assert binding["cacheable"] is True


def test_apply_sasa_to_prompt_is_an_exact_angstrom_squared_direct_node() -> None:
    catalog = build_frozen_catalog((MODULE_PACKAGE, *_prompt_authoring_packages()))
    quantity_contract = {
        "quantity": "solvent_accessible_surface_area",
        "measure": "absolute",
        "unit": "angstrom_squared",
        "granularity": "per_residue",
        "normalization": "none",
    }

    source_port = catalog.require_port_type(
        "structure_annotation.sasa_track",
        "4.0.0",
    )
    target_port = catalog.require_port_type("protein.prompt", "3.0.0")
    assert source_port.validator.parameters["quantity_contract"] == (
        quantity_contract
    )
    assert target_port.validator.parameters["track_contracts"][
        "sasa_track"
    ] == quantity_contract

    node = catalog.require_contract(
        "node_type",
        "structure_annotation.apply_sasa_to_prompt",
        "5.0.0",
    ).descriptor
    assert [
        (port["name"], port["port_type"]["contract_id"])
        for port in node["inputs"]
    ] == [
        ("protein_prompt", "protein.prompt"),
        ("sasa_track", "structure_annotation.sasa_track"),
    ]
    assert [
        (port["name"], port["port_type"]["contract_id"])
        for port in node["outputs"]
    ] == [("protein_prompt", "protein.prompt")]
    assert node["node_parameters"] == {}

    method = catalog.require_contract(
        "method",
        "structure_annotation.apply_sasa_to_prompt.method",
        "2.2.0",
    ).descriptor
    assert method["algorithm_identity"] == {
        "name": "exact-DSSP-SASA-to-ProteinPrompt-conditioning",
        "unit": "angstrom_squared",
        "numeric_mapping": "identity",
        "source_missing_role": "annotation_unavailable",
        "target_missing_role": "prompt_unspecified",
        "layout": "exact_identity",
        "unaffected_prompt_fields": "byte-equivalent-canonical-values",
        "provenance_transition": "observed_annotation_to_prompt_conditioning",
    }

    binding = catalog.require_contract(
        "binding",
        "structure_annotation.apply_sasa_to_prompt.direct",
        "5.0.0",
    ).descriptor
    assert binding["binding_parameters"] == {}
    assert binding["execution_route"] == "direct"
    assert binding["deterministic"] is True
    assert binding["cacheable"] is True


def test_expected_secondary_structure_from_prompt_is_an_explicit_role_node() -> None:
    catalog = build_frozen_catalog((MODULE_PACKAGE, *_prompt_authoring_packages()))

    node = catalog.require_contract(
        "node_type",
        "structure_annotation.expected_secondary_structure_from_prompt",
        "6.0.0",
    ).descriptor
    assert [
        (port["name"], port["port_type"]["contract_id"])
        for port in node["inputs"]
    ] == [
        ("protein_prompt", "protein.prompt"),
        ("references", "candidate.collection"),
    ]
    assert [
        (port["name"], port["port_type"]["contract_id"])
        for port in node["outputs"]
    ] == [
        (
            "secondary_structure_track",
            "structure_annotation.secondary_structure_track",
        )
    ]
    assert node["node_parameters"] == {}

    method = catalog.require_contract(
        "method",
        (
            "structure_annotation."
            "expected_secondary_structure_from_prompt.method"
        ),
        "3.0.0",
    ).descriptor
    assert method["algorithm_identity"] == {
        "name": "exact-ProteinPrompt-conditioning-to-expected-annotation-SS8",
        "source_alphabet": "GHITEBS-",
        "target_alphabet": "GHITEBSC_",
        "symbol_mapping": {"-": "C", "GHITEBS": "identity", "null": "_"},
        "source_missing_role": "prompt_unspecified",
        "target_missing_role": "expected_comparison_excluded",
        "layout": "exact_identity",
        "provenance_transition": "prompt_conditioning_to_expected_annotation",
    }

    binding = catalog.require_contract(
        "binding",
        (
            "structure_annotation."
            "expected_secondary_structure_from_prompt.direct"
        ),
        "6.0.0",
    ).descriptor
    assert binding["binding_parameters"] == {}
    assert binding["execution_route"] == "direct"
    assert binding["deterministic"] is True
    assert binding["cacheable"] is True
