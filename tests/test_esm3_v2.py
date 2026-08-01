"""Public v2 contracts for the cohesive remote ESM-3 package."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import FrozenInstanceError, replace
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from core import (
    EnvironmentConfiguration,
    InputContentDigests,
    ModulePackageContractCase,
    ModulePackagePortCase,
    OperationCall,
    ProjectManager,
    ReadinessCheckInput,
    ResultReplaySource,
    V2RunError,
    V2RunService,
    WorkflowAuthoringService,
    WorkflowDocument,
    WorkflowNodeInstance,
    build_discovered_frozen_catalog,
    build_frozen_catalog,
    discover_module_packages,
    parse_workflow_document,
    verify_module_package_contract,
)
from core.port_types import canonical_json_bytes
from core.workflow_v2 import WorkflowEdge
from datatypes import (
    ExactContractReference,
    FunctionAnnotation,
    FunctionAnnotations,
    ProteinPrompt,
    ProteinSequence,
    ProteinStructure,
    ResidueLayout,
    ResidueTrack,
)


def test_esm_package_owns_generation_and_direct_esmc_representation_nodes() -> None:
    registrations = {
        registration.package_id: registration
        for registration in discover_module_packages()
    }

    registration = registrations["esm3"]
    assert registration.package_module == "modules.esm3"
    assert {
        resource.resource for resource in registration.node_definitions
    } == {
        "definitions/generate_sequence.yaml",
        "definitions/generate_structure.yaml",
        "definitions/generate_paired.yaml",
        "definitions/represent_sequence.yaml",
    }

    catalog = build_discovered_frozen_catalog()
    owned_nodes = {
        (contract_id, version)
        for kind, contract_id, version in catalog.owners
        if kind == "node_type"
        and "esm3" in catalog.owners[(kind, contract_id, version)]
    }
    assert owned_nodes == {
        ("esm3.generate_sequence", "3.0.0"),
        ("esm3.generate_structure", "3.0.0"),
        ("esm3.generate_paired", "3.0.0"),
        ("esm3.represent_sequence", "2.1.0"),
    }

    representation = catalog.require_contract(
        "node_type",
        "esm3.represent_sequence",
        "2.1.0",
    )
    assert representation.descriptor["inputs"][0]["port_type"][
        "contract_id"
    ] == "protein.sequence"
    assert representation.descriptor["outputs"][0]["port_type"][
        "contract_id"
    ] == "esm3.esmc_sequence_representation"
    assert representation.descriptor["title"] == "Represent a sequence"
    assert "Biohub" not in representation.descriptor["summary"]
    assert "ESMC" not in representation.descriptor["summary"]
    binding = catalog.require_contract(
        "binding",
        "esm3.represent_sequence.biohub_esmc_600m_2024_12",
        "2.2.0",
    )
    assert binding.descriptor["method"]["contract_id"] == (
        "esm3.represent_sequence.esmc_600m_2024_12"
    )
    assert {
        key: binding.descriptor["implementation_identity"][key]
        for key in (
            "name",
            "model",
            "source",
            "provider_operations",
            "output_contract",
        )
    } == {
        "name": "esm3.represent_sequence.biohub-esmc-adapter",
        "model": "esmc-600m-2024-12",
        "source": "Biohub",
        "provider_operations": ("encode", "logits"),
        "output_contract": (
            "provider mean embedding plus validated sequence-logits shape"
        ),
    }
    assert binding.descriptor["readiness_declaration"]["prerequisites"] == {
        "credential": {
            "source": "trusted_environment_configuration",
        },
        "endpoint": {
            "endpoint_id": "biohub",
            "source": "trusted_environment_configuration",
        },
        "provider_sdk": {
            "name": "esm",
            "source_revision": (
                "917af90b624535eed1e072d343c717e3ec11fef4"
            ),
        },
    }

    models = (
        (
            "biohub_medium",
            "medium_2024_08",
            "esm3-medium-2024-08",
        ),
        (
            "biohub_open",
            "open_2024_03",
            "esm3-open-2024-03",
        ),
    )
    for operation in (
        "generate_sequence",
        "generate_structure",
        "generate_paired",
    ):
        node = catalog.require_contract(
            "node_type",
            f"esm3.{operation}",
            "3.0.0",
        )
        assert "model_name" not in node.descriptor["node_parameters"]
        if operation in {"generate_sequence", "generate_paired"}:
            assert "at least one masked sequence residue" in (
                node.descriptor["summary"]
            )
            assert "at least one masked sequence residue" in (
                node.descriptor["inputs"][0]["scientific_meaning"]
            )
        for route, method_suffix, model_name in models:
            binding = catalog.require_contract(
                "binding",
                f"esm3.{operation}.{route}",
                "3.0.0",
            )
            assert "model_name" not in (
                binding.descriptor["binding_parameters"]
            )
            assert binding.descriptor["execution_route"] == "adapter"
            assert binding.descriptor["method"]["contract_id"] == (
                f"esm3.{operation}.esm3_{method_suffix}"
            )
            assert (
                binding.descriptor["implementation_identity"]["model"]
                == model_name
            )
            assert binding.descriptor["availability_declaration"][
                "prerequisites"
            ]["provider_sdk"]["source_revision"] == (
                "917af90b624535eed1e072d343c717e3ec11fef4"
            )
            assert binding.descriptor["readiness_declaration"][
                "prerequisites"
            ] == {
                "credential": {
                    "source": "trusted_environment_configuration",
                },
                "endpoint": {
                    "endpoint_id": "biohub",
                    "source": "trusted_environment_configuration",
                },
                "provider_sdk": {
                    "name": "esm",
                    "source_revision": (
                        "917af90b624535eed1e072d343c717e3ec11fef4"
                    ),
                },
            }


def test_direct_esmc_representation_crosses_public_run_and_engine_seams(
    tmp_path: Path,
) -> None:
    import torch

    from modules.esm3.domain import ESMCSequenceRepresentation
    from modules.esm3.package import MODULE_PACKAGE as ESM3_PACKAGE
    from modules.prompt_authoring.package import (
        MODULE_PACKAGE as PROMPT_AUTHORING_PACKAGE,
    )
    from modules.protein_io.package import MODULE_PACKAGE as PROTEIN_IO_PACKAGE

    class ESMCClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object]] = []

        def encode(self, protein: object) -> object:
            self.calls.append(("encode", protein))
            return SimpleNamespace(sequence=torch.tensor([0, 1, 2, 3, 4]))

        def logits(self, encoded: object, config: object) -> object:
            self.calls.append(("logits", (encoded, config)))
            return SimpleNamespace(
                logits=SimpleNamespace(
                    sequence=torch.zeros((5, 64), dtype=torch.float32),
                ),
                mean_embedding=torch.cat((
                    torch.tensor([0.0, 1.0, -0.25, 0.5]),
                    torch.zeros(1148),
                )).reshape(1, 1, 1152),
            )

    catalog = build_frozen_catalog((
        ESM3_PACKAGE,
        PROMPT_AUTHORING_PACKAGE,
        PROTEIN_IO_PACKAGE,
    ))
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create("direct ESMC representation")
    projects.publish_input(project.id, "sequence.fasta", b">3GB1\nACD\n")
    authoring = WorkflowAuthoringService(projects, catalog)
    workflow = WorkflowDocument(
        schema_version="2.1.0",
        workflow_id=project.id,
        nodes=(
            WorkflowNodeInstance(
                node_id="import",
                node_type_id="protein_io.import_sequence",
                node_type_version="3.0.0",
                binding_id="protein_io.import_sequence.direct",
                binding_version="3.0.0",
                node_parameters={"project_input_ref": "sequence.fasta"},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="represent",
                node_type_id="esm3.represent_sequence",
                node_type_version="2.1.0",
                binding_id=(
                    "esm3.represent_sequence.biohub_esmc_600m_2024_12"
                ),
                binding_version="2.2.0",
                node_parameters={},
                binding_parameters={},
            ),
        ),
        edges=(
            WorkflowEdge("import", "sequence", "represent", "sequence"),
        ),
        contract_lock=(),
    )
    saved = authoring.save(
        project.id,
        expected_workflow_revision=0,
        workflow=workflow,
    )
    relocked = authoring.relock(
        project.id,
        workflow_revision=saved["workflow_revision"],
    )
    compiled = authoring.compile(
        project.id,
        workflow_revision=relocked["workflow_revision"],
        workflow=parse_workflow_document(relocked["workflow"]),
    )
    client = ESMCClient()
    environment = EnvironmentConfiguration({
        (
            "esm3.represent_sequence.biohub_esmc_600m_2024_12",
            "2.2.0",
        ): {
            "values": {
                "endpoint_id": "biohub",
                "credential_handle": object(),
                "provider_client": client,
            },
            "safe_fingerprint": "biohub-esmc-fixture-v1",
            "invalidation_token": "biohub-esmc-fixture-v1",
        }
    })
    service = V2RunService(projects, catalog, authoring, environment)
    try:
        receipt = service.start_background(
            project.id,
            workflow_revision=relocked["workflow_revision"],
            compile_id=compiled.public_receipt()["compile_id"],
            client_request_id="direct-esmc",
        )
        service.shutdown()
        projection = service.projection(project.id, receipt["run_id"])
        events = service.public_events(project.id, receipt["run_id"])
    finally:
        service.shutdown()

    assert projection["status"] == "succeeded"
    output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "represent"
    )
    representation = _decode_output(catalog, output)
    assert representation == ESMCSequenceRepresentation(
        sequence="ACD",
        residue_ids=None,
        mean_embedding=(0.0, 1.0, -0.25, 0.5) + (0.0,) * 1148,
        sequence_logits_shape=(5, 64),
    )
    assert [call[0] for call in client.calls] == ["encode", "logits"]
    started = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_role"]
        in {"sequence_encode", "sequence_logits"}
    ]
    method = catalog.require_contract(
        "method",
        "esm3.represent_sequence.esmc_600m_2024_12",
        "2.1.0",
    )
    assert {event["engine_identity"] for event in started} == {
        method.contract_digest
    }
    assert [event["engine_role"] for event in started] == [
        "sequence_encode",
        "sequence_logits",
    ]
    encode_started, logits_started = started
    assert "parent_invocation_id" not in encode_started
    assert logits_started["parent_invocation_id"] == (
        encode_started["invocation_id"]
    )
    terminals = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_terminal"
        and event["event"]["invocation_id"]
        in {started_event["invocation_id"] for started_event in started}
    ]
    assert len(terminals) == 2
    assert all(event["status"] == "succeeded" for event in terminals)

    port_type = catalog.require_port_type(
        "esm3.esmc_sequence_representation",
        "2.1.0",
    )
    assert port_type.decode(port_type.encode(representation)) == representation
    integer_form_embedding = ESMCSequenceRepresentation(
        sequence="ACD",
        residue_ids=None,
        mean_embedding=(0.0, 1.0),
        sequence_logits_shape=(5, 64),
    )
    assert (
        port_type.decode(port_type.encode(integer_form_embedding))
        == integer_form_embedding
    )
    with pytest.raises(ValueError, match="finite"):
        ESMCSequenceRepresentation(
            sequence="ACD",
            residue_ids=("A:1", "A:2", "A:3"),
            mean_embedding=(float("nan"),),
            sequence_logits_shape=(5, 64),
        )
    with pytest.raises(ValueError, match="binary32"):
        ESMCSequenceRepresentation(
            sequence="ACD",
            residue_ids=None,
            mean_embedding=(1e300,),
            sequence_logits_shape=(5, 64),
        )
    with pytest.raises(ValueError, match="negative zero"):
        ESMCSequenceRepresentation(
            sequence="ACD",
            residue_ids=None,
            mean_embedding=(-0.0,),
            sequence_logits_shape=(5, 64),
        )


def test_exact_esmc_rejects_contract_mismatched_feature_dimensions() -> None:
    import torch

    from modules.esm3.esmc_adapter import normalize_representation

    sequence = ProteinSequence("ACD")

    def result(
        embedding_dimension: int,
        logits_dimension: int,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            logits=SimpleNamespace(
                sequence=torch.zeros(
                    (5, logits_dimension),
                    dtype=torch.float32,
                )
            ),
            mean_embedding=torch.zeros(
                (1, 1, embedding_dimension),
                dtype=torch.float32,
            ),
        )

    with pytest.raises(ValueError, match="embedding dimension"):
        normalize_representation(
            sequence,
            result(1151, 64),
            model_name="esmc-600m-2024-12",
        )
    with pytest.raises(ValueError, match="logits dimension"):
        normalize_representation(
            sequence,
            result(1152, 63),
            model_name="esmc-600m-2024-12",
        )


def test_biohub_esmc_adapter_owns_both_sdk_calls_and_result_admission() -> None:
    import torch

    from modules.esm3.domain import ESMCSequenceRepresentation
    from modules.esm3.esmc_adapter import (
        BIOHUB_ESMC_MODEL,
        BiohubESMCAdapter,
    )

    class ESMCClient:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def encode(self, protein: object) -> object:
            self.calls.append("encode")
            return SimpleNamespace(sequence=protein)

        def logits(self, encoded: object, config: object) -> object:
            del encoded, config
            self.calls.append("logits")
            return SimpleNamespace(
                logits=SimpleNamespace(sequence=torch.zeros((5, 64))),
                mean_embedding=torch.zeros((1152,)),
            )

    class InvocationResources:
        def __init__(self) -> None:
            self.invocations: list[dict[str, object]] = []

        @contextmanager
        def engine_invocation(self, **kwargs: object):
            self.invocations.append(dict(kwargs))
            yield f"esmc-invocation-{len(self.invocations)}"

    client = ESMCClient()
    resources = InvocationResources()
    adapter = BiohubESMCAdapter(
        environment={
            "endpoint_id": "biohub",
            "credential_handle": object(),
            "provider_client": client,
        },
        resources=resources,
        model_name=BIOHUB_ESMC_MODEL,
    )

    result = adapter.represent(
        ProteinSequence("ACD", ["A:1", "A:2", "A:3"])
    )

    assert result == ESMCSequenceRepresentation(
        sequence="ACD",
        residue_ids=("A:1", "A:2", "A:3"),
        mean_embedding=(0.0,) * 1152,
        sequence_logits_shape=(5, 64),
    )
    assert client.calls == ["encode", "logits"]
    assert resources.invocations == [
        {
            "engine_role": "sequence_encode",
        },
        {
            "engine_role": "sequence_logits",
            "parent_invocation_id": "esmc-invocation-1",
        },
    ]


def test_adapter_preserves_every_representable_prompt_track_and_symbol() -> None:
    from modules.esm3.adapter import (
        protein_prompt_to_provider,
        structure_prompt_for_sequence,
    )

    layout = ResidueLayout(
        chain_id="A",
        length=8,
        residue_ids=[f"A:{index}" for index in range(1, 9)],
    )
    prompt = ProteinPrompt(
        target_layout=layout,
        sequence_track=ResidueTrack(
            ["A", "B", "Z", "U", "O", "X", None, "G"],
            None,
        ),
        structure_track=ResidueTrack(
            [
                {
                    "N": (1.0, 2.0, 3.0),
                    "CA": (4.0, 5.0, 6.0),
                    "C": (7.0, 8.0, 9.0),
                    "O": (10.0, 11.0, 12.0),
                },
                *([None] * 7),
            ],
            None,
        ),
        structure_visibility_track=ResidueTrack(
            [True, False, True, True, True, True, True, True],
            None,
        ),
        secondary_structure_track=ResidueTrack(
            ["G", "H", "I", "T", "E", "B", "S", "-"],
            None,
        ),
        sasa_track=ResidueTrack(
            [0.0, 0.8, 4.0, None, 16.4, 32.9, 70.9, 151.4],
            None,
        ),
        function_annotations=FunctionAnnotations(
            [
                FunctionAnnotation(
                    label="binding site",
                    start=2,
                    end=5,
                    chain_id="A",
                    start_residue_id="A:2",
                    end_residue_id="A:5",
                    overlap_policy="reject",
                )
            ]
        ),
    )

    provider = protein_prompt_to_provider(prompt)

    assert provider.sequence == "ABZUOX_G"
    assert provider.secondary_structure == "GHITEBSC"
    assert provider.sasa == [0.0, 0.8, 4.0, None, 16.4, 32.9, 70.9, 151.4]
    assert provider.function_annotations[0].label == "binding site"
    assert provider.function_annotations[0].start == 2
    assert provider.function_annotations[0].end == 5
    assert tuple(provider.coordinates.shape) == (8, 37, 3)
    assert provider.coordinates[0, 0].tolist() == [1.0, 2.0, 3.0]
    assert provider.coordinates[0, 1].tolist() == [4.0, 5.0, 6.0]
    assert math.isnan(float(provider.coordinates[1, 1, 0]))

    paired_structure_prompt = structure_prompt_for_sequence(
        provider,
        "ACDEFGHI",
    )
    assert paired_structure_prompt.sequence == "ACDEFGHI"
    assert paired_structure_prompt.coordinates is provider.coordinates
    assert (
        paired_structure_prompt.secondary_structure
        == provider.secondary_structure
    )
    assert paired_structure_prompt.sasa == provider.sasa
    assert (
        paired_structure_prompt.function_annotations
        is provider.function_annotations
    )

    with pytest.raises(TypeError, match="does not support item assignment"):
        prompt.sequence_track.values[0] = "J"
    assert prompt.sequence_track.values == (
        "A",
        "B",
        "Z",
        "U",
        "O",
        "X",
        None,
        "G",
    )
    assert protein_prompt_to_provider(prompt).sequence == provider.sequence

    invalid_prompt = replace(
        prompt,
        sequence_track=ResidueTrack(
            ("J", "B", "Z", "U", "O", "X", None, "G"),
            None,
        ),
    )
    with pytest.raises(ValueError, match="cannot represent sequence symbol 'J'"):
        protein_prompt_to_provider(invalid_prompt)


def test_biohub_adapter_admits_a_frozen_provider_independent_sequence_result(
) -> None:
    from modules.esm3.adapter import (
        BIOHUB_ESM3_MEDIUM_MODEL,
        BiohubESM3Adapter,
        ESM3CallParameters,
        ESM3SequenceResult,
    )

    class InvocationResources:
        def __init__(self) -> None:
            self.invocations: list[dict[str, object]] = []

        @contextmanager
        def engine_invocation(self, **kwargs: object):
            self.invocations.append(dict(kwargs))
            yield "invocation-1"

    client = _ProviderClient([_ProviderResponse("ACD")])
    resources = InvocationResources()
    adapter = BiohubESM3Adapter(
        environment={
            "endpoint_id": "biohub",
            "credential_handle": object(),
            "provider_client": client,
        },
        resources=resources,
        model_name=BIOHUB_ESM3_MEDIUM_MODEL,
    )
    prompt = ProteinPrompt(
        target_layout=ResidueLayout("A", 3, ["A:1", "A:2", "A:3"]),
        sequence_track=ResidueTrack([None, "C", "D"], None),
    )

    with adapter:
        result = adapter.generate_sequence(
            prompt,
            parameters=ESM3CallParameters(
                num_steps=4,
                temperature=1.0,
                top_p=1.0,
                schedule="cosine",
                strategy="random",
                temperature_annealing=True,
            ),
            derived_call_seed=17,
        )

    assert result == ESM3SequenceResult(
        sequence=ProteinSequence("ACD", ["A:1", "A:2", "A:3"]),
        reconstruction=None,
        confidence=None,
        effective_num_steps=4,
        effective_call_seed=None,
    )
    assert resources.invocations == [
        {
            "engine_role": "sequence_sample",
            "parent_invocation_id": None,
            "invocation_provenance": {
                "effective_randomness": {
                    "control": "provider_uncontrolled",
                }
            },
        }
    ]
    assert [call[1].track for call in client.calls] == ["sequence"]
    with pytest.raises(FrozenInstanceError):
        result.reconstruction = object()  # type: ignore[misc]


def test_biohub_adapter_preserves_paired_engine_causality_and_confidence(
) -> None:
    import torch

    from modules.esm3.adapter import (
        BIOHUB_ESM3_MEDIUM_MODEL,
        BiohubESM3Adapter,
        ESM3CallParameters,
        ESM3Confidence,
        ESM3PairResult,
        ESM3SequenceResult,
        ESM3StructureResult,
    )

    class InvocationResources:
        def __init__(self) -> None:
            self.invocations: list[dict[str, object]] = []

        @contextmanager
        def engine_invocation(self, **kwargs: object):
            self.invocations.append(dict(kwargs))
            yield f"invocation-{len(self.invocations)}"

    sequence_response = _ProviderResponse("ACD")
    structure_response = _ProviderResponse(
        "ACD",
        coordinates=torch.zeros((3, 37, 3)),
        ptm=torch.tensor(0.75),
        plddt=torch.tensor([0.7, 0.8, 0.9]),
        pae=torch.tensor(
            [
                [0.0, 1.0, 2.0],
                [1.0, 0.0, 1.0],
                [2.0, 1.0, 0.0],
            ]
        ),
        pdb_string=_three_residue_pdb(),
    )
    resources = InvocationResources()
    adapter = BiohubESM3Adapter(
        environment={
            "endpoint_id": "biohub",
            "credential_handle": object(),
            "provider_client": _ProviderClient(
                [sequence_response, structure_response]
            ),
        },
        resources=resources,
        model_name=BIOHUB_ESM3_MEDIUM_MODEL,
    )
    prompt = ProteinPrompt(
        target_layout=ResidueLayout("A", 3, ["A:1", "A:2", "A:3"]),
        sequence_track=ResidueTrack([None, "C", "D"], None),
    )
    parameters = ESM3CallParameters(
        num_steps=4,
        temperature=1.0,
        top_p=1.0,
        schedule="cosine",
        strategy="random",
        temperature_annealing=True,
    )

    with adapter:
        result = adapter.generate_pair(
            prompt,
            parameters=parameters,
            sequence_derived_call_seed=17,
            structure_derived_call_seed=23,
        )

    assert type(result) is ESM3PairResult
    assert result.sequence == ESM3SequenceResult(
        sequence=ProteinSequence("ACD", ["A:1", "A:2", "A:3"]),
        reconstruction=None,
        confidence=None,
        effective_num_steps=4,
        effective_call_seed=None,
    )
    assert type(result.structure) is ESM3StructureResult
    assert result.structure.structure == ProteinStructure(
        _three_residue_pdb(),
    )
    assert type(result.structure.confidence) is ESM3Confidence
    confidence = result.structure.confidence
    assert confidence.ptm == pytest.approx(0.75)
    assert confidence.plddt_per_residue == pytest.approx((70.0, 80.0, 90.0))
    assert confidence.pae == (
        (0.0, 1.0, 2.0),
        (1.0, 0.0, 1.0),
        (2.0, 1.0, 0.0),
    )
    assert result.structure.effective_num_steps == 4
    assert result.structure.effective_call_seed is None
    assert resources.invocations == [
        {
            "engine_role": "sequence_parent",
            "parent_invocation_id": None,
            "invocation_provenance": {
                "effective_randomness": {
                    "control": "provider_uncontrolled",
                }
            },
        },
        {
            "engine_role": "structure_child",
            "parent_invocation_id": "invocation-1",
            "invocation_provenance": {
                "effective_randomness": {
                    "control": "provider_uncontrolled",
                }
            },
        },
    ]


def test_esm3_call_seed_uses_prompt_content_and_stable_sample_track_slot() -> None:
    from modules.esm3.adapter import ESM3SequenceResult
    from modules.esm3.implementation import ESM3GenerationOperation

    class RecordingAdapter:
        def __init__(self) -> None:
            self.seeds: list[int] = []

        def __enter__(self) -> RecordingAdapter:
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def generate_sequence(
            self,
            prompt: ProteinPrompt,
            *,
            parameters: object,
            derived_call_seed: int,
        ) -> ESM3SequenceResult:
            del prompt, parameters
            self.seeds.append(derived_call_seed)
            return ESM3SequenceResult(
                sequence=ProteinSequence("ACD"),
                reconstruction=None,
                confidence=None,
                effective_num_steps=4,
                effective_call_seed=derived_call_seed,
            )

    prompt = ProteinPrompt(
        target_layout=ResidueLayout("A", 3, ["A:1", "A:2", "A:3"]),
        sequence_track=ResidueTrack([None, "C", "D"], None),
    )

    def observed(content_digest: str) -> tuple[int, ...]:
        adapter = RecordingAdapter()
        operation = ESM3GenerationOperation(
            adapter=adapter,
            operation="generate_sequence",
            method=ExactContractReference(
                "method",
                "esm3.generate_sequence.fixture",
                "3.0.0",
                "sha256:" + "3" * 64,
            ),
            produced_observations=(),
        )
        operation.execute(
            OperationCall(
                inputs={"protein_prompt": prompt},
                node_parameters={
                    "effective_seed": 1603,
                    "num_samples": 2,
                    "num_steps": 4,
                    "temperature": 1.0,
                    "top_p": 1.0,
                    "schedule": "cosine",
                    "strategy": "random",
                    "temperature_annealing": True,
                },
                binding_parameters={},
                input_content_digests={
                    "protein_prompt": InputContentDigests(
                        port_type_id="protein.prompt",
                        value_content_digests=(content_digest,),
                    )
                },
            )
        )
        return tuple(adapter.seeds)

    first = observed("sha256:" + "a" * 64)
    repeated = observed("sha256:" + "a" * 64)
    changed_content = observed("sha256:" + "b" * 64)

    assert first == repeated
    assert first[0] != first[1]
    assert first != changed_content


class _ProviderResponse:
    def __init__(
        self,
        sequence: str,
        *,
        coordinates: Any = None,
        ptm: Any = None,
        plddt: Any = None,
        pae: Any = None,
        pdb_string: str | None = None,
    ) -> None:
        self.sequence = sequence
        self.coordinates = coordinates
        self.ptm = ptm
        self.plddt = plddt
        self.pae = pae
        self._pdb_string = pdb_string

    def to_pdb_string(self) -> str:
        if self._pdb_string is None:
            raise AssertionError("coordinate-free fixture cannot render a PDB")
        return self._pdb_string


class _ProviderClient:
    def __init__(self, responses: list[_ProviderResponse]) -> None:
        self._responses = iter(responses)
        self.calls: list[tuple[Any, Any]] = []

    def generate(self, protein: Any, config: Any) -> _ProviderResponse:
        self.calls.append((protein, config))
        return next(self._responses)


class _StepShorteningProviderClient(_ProviderClient):
    def generate(self, protein: Any, config: Any) -> _ProviderResponse:
        config.num_steps = 1
        return super().generate(protein, config)


def _decode_output(catalog: Any, output: dict[str, Any]) -> Any:
    reference = output["port_type"]
    port_type = catalog.require_port_type(
        reference["contract_id"],
        reference["contract_version"],
    )
    return port_type.decode(
        canonical_json_bytes(
            {
                "schema_namespace": "protein-workbench-port-value/v2",
                "port_type_id": port_type.type_id,
                "port_type_version": port_type.version,
                "value": output["values"][0],
            }
        )
    )


def _run_generation(
    tmp_path: Path,
    *,
    operation: str,
    client: Any | None,
    num_samples: int,
    sequence: str | None = None,
    environment_overrides: dict[str, Any] | None = None,
    result_replay_source: ResultReplaySource | None = None,
    generation_parameters: dict[str, Any] | None = None,
    binding_route: str = "biohub_medium",
    sequence_mask_residue_ids: tuple[str, ...] = (),
    safe_environment_fingerprint: str | None = None,
    invalidation_token: str | None = None,
) -> tuple[Any, dict[str, Any], tuple[dict[str, Any], ...]]:
    from modules.esm3.package import MODULE_PACKAGE as ESM3_PACKAGE
    from modules.prompt_authoring.package import (
        MODULE_PACKAGE as PROMPT_AUTHORING_PACKAGE,
    )
    from modules.protein_io.package import MODULE_PACKAGE as PROTEIN_IO_PACKAGE

    supporting = [PROMPT_AUTHORING_PACKAGE]
    nodes = [
        WorkflowNodeInstance(
            node_id="layout",
            node_type_id="prompt_authoring.build_residue_layout",
            node_type_version="2.1.0",
            binding_id="prompt_authoring.build_residue_layout.direct",
            binding_version="2.1.0",
            node_parameters={
                "chains": [
                    {
                        "chain_id": "A",
                        "length": len(sequence) if sequence is not None else 3,
                    }
                ]
            },
            binding_parameters={},
        ),
        WorkflowNodeInstance(
            node_id="assemble",
            node_type_id="prompt_authoring.assemble_protein_prompt",
            node_type_version="2.1.0",
            binding_id="prompt_authoring.assemble_protein_prompt.direct",
            binding_version="2.1.0",
            node_parameters={},
            binding_parameters={},
        ),
    ]
    edges = [
        WorkflowEdge("layout", "layout", "assemble", "layout"),
    ]
    project_inputs: dict[str, bytes] = {}
    prompt_source = "assemble"
    if sequence is not None:
        supporting.append(PROTEIN_IO_PACKAGE)
        project_inputs["sequence-input"] = f">fixture\n{sequence}\n".encode()
        nodes.extend(
            [
                WorkflowNodeInstance(
                    node_id="import_sequence",
                    node_type_id="protein_io.import_sequence",
                    node_type_version="3.0.0",
                    binding_id="protein_io.import_sequence.direct",
                    binding_version="3.0.0",
                    node_parameters={"project_input_ref": "sequence-input"},
                    binding_parameters={},
                ),
                WorkflowNodeInstance(
                    node_id="update_sequence",
                    node_type_id="prompt_authoring.update_prompt_sequence",
                    node_type_version="2.1.0",
                    binding_id="prompt_authoring.update_prompt_sequence.direct",
                    binding_version="2.1.0",
                    node_parameters={},
                    binding_parameters={},
                ),
            ]
        )
        edges.extend(
            [
                WorkflowEdge(
                    "assemble",
                    "protein_prompt",
                    "update_sequence",
                    "protein_prompt",
                ),
                WorkflowEdge(
                    "import_sequence",
                    "sequence",
                    "update_sequence",
                    "sequence",
                ),
            ]
        )
        prompt_source = "update_sequence"
        if sequence_mask_residue_ids:
            nodes.append(
                WorkflowNodeInstance(
                    node_id="mask_sequence",
                    node_type_id="prompt_authoring.random_mask",
                    node_type_version="2.1.0",
                    binding_id="prompt_authoring.random_mask.direct",
                    binding_version="2.1.0",
                    node_parameters={
                        "effective_seed": 1603,
                        "count": len(sequence_mask_residue_ids),
                        "track": "sequence",
                        "eligible_residue_ids": list(
                            sequence_mask_residue_ids
                        ),
                    },
                    binding_parameters={},
                )
            )
            edges.append(
                WorkflowEdge(
                    "update_sequence",
                    "protein_prompt",
                    "mask_sequence",
                    "protein_prompt",
                )
            )
            prompt_source = "mask_sequence"
    resolved_generation_parameters = {
        "effective_seed": 1603,
        "num_samples": num_samples,
    }
    resolved_generation_parameters.update(generation_parameters or {})
    nodes.append(
        WorkflowNodeInstance(
            node_id="generate",
            node_type_id=f"esm3.{operation}",
            node_type_version="3.0.0",
            binding_id=f"esm3.{operation}.{binding_route}",
            binding_version="3.0.0",
            node_parameters=resolved_generation_parameters,
            binding_parameters={},
        )
    )
    edges.append(
        WorkflowEdge(
            prompt_source,
            "protein_prompt",
            "generate",
            "protein_prompt",
        )
    )

    catalog = build_frozen_catalog((ESM3_PACKAGE, *supporting))
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create(f"ESM3 {operation}")
    for reference, payload in project_inputs.items():
        projects.publish_input(project.id, reference, payload)
    authoring = WorkflowAuthoringService(projects, catalog)
    workflow = WorkflowDocument(
        schema_version="2.1.0",
        workflow_id=project.id,
        nodes=tuple(nodes),
        edges=tuple(edges),
        contract_lock=(),
    )
    saved = authoring.save(
        project.id,
        expected_workflow_revision=0,
        workflow=workflow,
    )
    relocked = authoring.relock(
        project.id,
        workflow_revision=saved["workflow_revision"],
    )
    compiled = authoring.compile(
        project.id,
        workflow_revision=relocked["workflow_revision"],
        workflow=parse_workflow_document(relocked["workflow"]),
    )
    environment_values = {
        "endpoint_id": "biohub",
        "credential_handle": object(),
        "provider_client": client,
        "private_token": "secret-must-never-publish",
        "runtime_path": "/private/esm3-runtime",
    }
    environment_values.update(environment_overrides or {})
    environment = EnvironmentConfiguration(
        {
            (f"esm3.{operation}.{binding_route}", "3.0.0"): {
                "values": environment_values,
                "safe_fingerprint": (
                    safe_environment_fingerprint
                    or f"{binding_route}-fixture-v1"
                ),
                "invalidation_token": (
                    invalidation_token or f"{binding_route}-fixture-v1"
                ),
            }
        }
    )
    service = V2RunService(
        projects,
        catalog,
        authoring,
        environment,
        result_replay_source,
    )
    try:
        receipt = service.start_background(
            project.id,
            workflow_revision=relocked["workflow_revision"],
            compile_id=compiled.public_receipt()["compile_id"],
            client_request_id=f"esm3-{operation}",
        )
        service.shutdown()
        projection = service.projection(project.id, receipt["run_id"])
        events = service.public_events(project.id, receipt["run_id"])
    finally:
        service.shutdown()
    return catalog, projection, events


def test_readiness_rejects_before_cache_lookup_or_provider_call(
    tmp_path: Path,
) -> None:
    class LookupRecorder(ResultReplaySource):
        def __init__(self) -> None:
            self.lookups = 0

        def lookup(self, **kwargs: Any) -> None:
            del kwargs
            self.lookups += 1
            return None

    cache = LookupRecorder()
    client = _ProviderClient([])

    with pytest.raises(V2RunError) as rejected:
        _run_generation(
            tmp_path,
            operation="generate_sequence",
            client=client,
            num_samples=1,
            environment_overrides={"endpoint_id": "wrong-provider"},
            result_replay_source=cache,
        )

    assert rejected.value.code == "readiness_rejected"
    assert cache.lookups == 0
    assert client.calls == []


def test_readiness_has_no_implicit_process_credential_fallback(
    tmp_path: Path,
) -> None:
    from modules.esm3.package import _ready

    credential_file = tmp_path / "biohub-token"
    credential_file.write_text("must-not-be-read\n", encoding="utf-8")

    assert not _ready(
        ReadinessCheckInput(
            {
                "endpoint_id": "biohub",
                "credential_file": credential_file,
            },
            None,
        )
    ).passing


def test_provider_installation_is_reobserved_without_process_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.esm3.package as package

    validations: list[tuple[str, str]] = []
    monkeypatch.setattr(
        package.importlib.util,
        "find_spec",
        lambda name: SimpleNamespace(name=name),
    )
    monkeypatch.setattr(
        package,
        "validate_installed_provider_checkout",
        lambda name, revision: validations.append((name, revision)),
    )

    assert package._available().is_available
    assert package._available().is_available
    environment = {
        "endpoint_id": "biohub",
        "credential_handle": object(),
        "provider_client": _ProviderClient([]),
    }
    check_input = ReadinessCheckInput(environment, None)
    assert package._ready(check_input).passing
    assert package._ready(check_input).passing
    assert validations == [
        ("esm", package.ESM_SDK_REVISION),
        ("esm", package.ESM_SDK_REVISION),
        ("esm", package.ESM_SDK_REVISION),
        ("esm", package.ESM_SDK_REVISION),
    ]


def test_open_binding_factory_receives_its_exact_model(
    tmp_path: Path,
) -> None:
    created_with: list[dict[str, Any]] = []
    client = _ProviderClient([_ProviderResponse("ACD")])

    def factory(**kwargs: Any) -> _ProviderClient:
        created_with.append(kwargs)
        return client

    catalog, projection, events = _run_generation(
        tmp_path,
        operation="generate_sequence",
        client=_ProviderClient([]),
        num_samples=1,
        binding_route="biohub_open",
        environment_overrides={
            "provider_client": None,
            "client_factory": factory,
        },
    )

    assert projection["status"] == "succeeded"
    output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "generate"
        and item["output_port"] == "sequence_candidates"
    )
    candidates = _decode_output(catalog, output)
    forbidden = {
        "provider",
        "model",
        "route",
        "runtime_fingerprint",
        "checkpoint",
        "seed_control",
        "effective_seed",
        "effective_call_seed",
    }
    assert forbidden.isdisjoint(candidates.items[0].metadata)
    assert len(created_with) == 1
    assert created_with[0]["model_name"] == "esm3-open-2024-03"
    assert created_with[0]["endpoint_id"] == "biohub"
    assert created_with[0]["credential_handle"] is not None
    binding = catalog.require_contract(
        "binding",
        "esm3.generate_sequence.biohub_open",
        "3.0.0",
    )
    method = catalog.require_contract(
        "method",
        binding.descriptor["method"]["contract_id"],
        binding.descriptor["method"]["contract_version"],
    )
    invocations = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_role"] == "sequence_sample"
    ]
    assert len(invocations) == 1
    assert invocations[0]["engine_identity"] == method.contract_digest
    assert invocations[0]["invocation_provenance"] == {
        "effective_randomness": {
            "control": "provider_uncontrolled",
        }
    }


def _run_generation_from_prompt_fixture(
    tmp_path: Path,
    *,
    operation: str,
    mode: str,
    client: _ProviderClient,
    num_samples: int = 1,
    binding_route: str = "biohub_medium",
) -> tuple[Any, dict[str, Any], tuple[dict[str, Any], ...]]:
    from modules.esm3.package import MODULE_PACKAGE as ESM3_PACKAGE
    from modules.prompt_authoring.package import (
        MODULE_PACKAGE as PROMPT_AUTHORING_PACKAGE,
    )
    from tests.fixtures.esm3_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    catalog = build_frozen_catalog(
        (ESM3_PACKAGE, PROMPT_AUTHORING_PACKAGE, SOURCE_PACKAGE)
    )
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create(f"ESM3 {operation} fixture")
    authoring = WorkflowAuthoringService(projects, catalog)
    workflow = WorkflowDocument(
        schema_version="2.1.0",
        workflow_id=project.id,
        nodes=(
            WorkflowNodeInstance(
                node_id="source",
                node_type_id="contract_test.esm3_prompt_source",
                node_type_version="2.1.0",
                binding_id="contract_test.esm3_prompt_source.direct",
                binding_version="2.1.0",
                node_parameters={"mode": mode},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="generate",
                node_type_id=f"esm3.{operation}",
                node_type_version="3.0.0",
                binding_id=f"esm3.{operation}.{binding_route}",
                binding_version="3.0.0",
                node_parameters={
                    "effective_seed": 1603,
                    "num_samples": num_samples,
                },
                binding_parameters={},
            ),
        ),
        edges=(
            WorkflowEdge(
                "source",
                "protein_prompt",
                "generate",
                "protein_prompt",
            ),
        ),
        contract_lock=(),
    )
    saved = authoring.save(
        project.id,
        expected_workflow_revision=0,
        workflow=workflow,
    )
    relocked = authoring.relock(
        project.id,
        workflow_revision=saved["workflow_revision"],
    )
    compiled = authoring.compile(
        project.id,
        workflow_revision=relocked["workflow_revision"],
        workflow=parse_workflow_document(relocked["workflow"]),
    )
    environment = EnvironmentConfiguration(
        {
            (f"esm3.{operation}.{binding_route}", "3.0.0"): {
                "values": {
                    "endpoint_id": "biohub",
                    "credential_handle": object(),
                    "provider_client": client,
                },
                "safe_fingerprint": f"{binding_route}-fixture-v1",
                "invalidation_token": f"{binding_route}-fixture-v1",
            }
        }
    )
    service = V2RunService(projects, catalog, authoring, environment)
    try:
        receipt = service.start_background(
            project.id,
            workflow_revision=relocked["workflow_revision"],
            compile_id=compiled.public_receipt()["compile_id"],
            client_request_id=f"esm3-{operation}-{mode}",
        )
        service.shutdown()
        projection = service.projection(project.id, receipt["run_id"])
        events = service.public_events(project.id, receipt["run_id"])
    finally:
        service.shutdown()
    return catalog, projection, events


def test_coordinate_conditioned_sequence_returns_prompt_reconstruction(
    tmp_path: Path,
) -> None:
    import torch

    client = _ProviderClient(
        [
            _ProviderResponse(
                "ACD",
                coordinates=torch.zeros((3, 37, 3)),
                ptm=torch.tensor(0.75),
                plddt=torch.tensor([0.7, 0.8, 0.9]),
                pdb_string=_three_residue_pdb(),
            )
        ]
    )

    catalog, projection, _ = _run_generation_from_prompt_fixture(
        tmp_path,
        operation="generate_sequence",
        mode="coordinate_conditioned",
        client=client,
    )

    assert projection["status"] == "succeeded"
    outputs = {
        item["output_port"]: item
        for item in projection["outputs"]
        if item["node_id"] == "generate"
    }
    sequences = _decode_output(catalog, outputs["sequence_candidates"])
    structures = _decode_output(
        catalog,
        outputs["sequence_reconstruction_candidates"],
    )
    confidence = _decode_output(
        catalog,
        outputs["confidence_observations"],
    )
    assert len(sequences.items) == len(structures.items) == 1
    assert structures.items[0].parent_ids == (
        sequences.items[0].candidate_id,
    )
    assert structures.items[0].metadata["classification"] == (
        "prompt_reconstruction"
    )
    assert len(confidence.entries) == 3


def test_coordinate_conditioned_paired_generation_retains_reconstruction(
    tmp_path: Path,
) -> None:
    import torch

    response = lambda: _ProviderResponse(
        "ACD",
        coordinates=torch.zeros((3, 37, 3)),
        ptm=torch.tensor(0.75),
        plddt=torch.tensor([0.7, 0.8, 0.9]),
        pdb_string=_three_residue_pdb(),
    )
    catalog, projection, _ = _run_generation_from_prompt_fixture(
        tmp_path,
        operation="generate_paired",
        mode="coordinate_conditioned",
        client=_ProviderClient([response(), response()]),
    )

    assert projection["status"] == "succeeded"
    outputs = {
        item["output_port"]: item
        for item in projection["outputs"]
        if item["node_id"] == "generate"
    }
    sequences = _decode_output(catalog, outputs["sequence_candidates"])
    reconstructions = _decode_output(
        catalog,
        outputs["sequence_reconstruction_candidates"],
    )
    counterparts = _decode_output(
        catalog,
        outputs["structure_candidates"],
    )
    reconstruction_confidence = _decode_output(
        catalog,
        outputs[
            "sequence_reconstruction_confidence_observations"
        ],
    )
    assert len(sequences.items) == 1
    assert len(reconstructions.items) == 1
    assert len(counterparts.items) == 1
    assert reconstructions.items[0].parent_ids == (
        sequences.items[0].candidate_id,
    )
    assert reconstructions.items[0].metadata["classification"] == (
        "prompt_reconstruction"
    )
    assert counterparts.items[0].metadata["classification"] == (
        "sampled_structure"
    )
    assert len(reconstruction_confidence.entries) == 3


def test_sequence_generation_publishes_ordered_complete_candidates(
    tmp_path: Path,
) -> None:
    client = _ProviderClient(
        [
            _ProviderResponse("ACD"),
            _ProviderResponse("EFG"),
        ]
    )

    catalog, projection, events = _run_generation(
        tmp_path,
        operation="generate_sequence",
        client=client,
        num_samples=2,
    )

    assert projection["status"] == "succeeded"
    output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "generate"
        and item["output_port"] == "sequence_candidates"
    )
    candidates = _decode_output(catalog, output)
    assert [candidate.data.sequence for candidate in candidates.items] == [
        "ACD",
        "EFG",
    ]
    assert [candidate.metadata["sample_index"] for candidate in candidates.items] == [
        0,
        1,
    ]
    assert all(candidate.parent_ids == () for candidate in candidates.items)
    assert [call[1].track for call in client.calls] == ["sequence", "sequence"]
    generation_events = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_role"] == "sequence_sample"
    ]
    assert len(generation_events) == 2
    public = str({"projection": projection, "events": events})
    assert "secret-must-never-publish" not in public
    assert "/private/esm3-runtime" not in public


@pytest.mark.parametrize(
    "operation",
    ("generate_sequence", "generate_paired"),
)
def test_sequence_generation_rejects_a_fully_assigned_track_before_call(
    tmp_path: Path,
    operation: str,
) -> None:
    client = _ProviderClient([_ProviderResponse("ACD")])

    _, projection, events = _run_generation(
        tmp_path,
        operation=operation,
        client=client,
        num_samples=1,
        sequence="ACD",
    )

    assert projection["status"] == "failed"
    assert client.calls == []
    assert not [
        event
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_role"]
        in {"sequence_sample", "sequence_parent"}
    ]


def test_sequence_generation_calls_provider_with_explicit_workflow_mask(
    tmp_path: Path,
) -> None:
    client = _ProviderClient([_ProviderResponse("ACD")])

    _, projection, _ = _run_generation(
        tmp_path,
        operation="generate_sequence",
        client=client,
        num_samples=1,
        sequence="ACD",
        sequence_mask_residue_ids=("A:1",),
    )

    assert projection["status"] == "succeeded"
    assert len(client.calls) == 1
    assert client.calls[0][0].sequence == "_CD"


def test_generation_records_requested_and_sdk_effective_steps_per_call(
    tmp_path: Path,
) -> None:
    client = _StepShorteningProviderClient(
        [_ProviderResponse("ACD"), _ProviderResponse("ACD")]
    )

    catalog, projection, _ = _run_generation(
        tmp_path,
        operation="generate_sequence",
        client=client,
        num_samples=2,
        sequence="ACD",
        sequence_mask_residue_ids=("A:1",),
        generation_parameters={"num_steps": 20},
    )

    assert projection["status"] == "succeeded"
    output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "generate"
        and item["output_port"] == "sequence_candidates"
    )
    candidates = _decode_output(catalog, output)
    assert len({id(config) for _, config in client.calls}) == 2
    for candidate in candidates.items:
        assert candidate.metadata[
            "requested_generation_parameters"
        ]["num_steps"] == 20
        assert candidate.metadata[
            "effective_generation_parameters"
        ]["sequence"]["num_steps"] == 1


def _three_residue_pdb(sequence: str = "ACD") -> str:
    residue_names = {
        "A": "ALA",
        "C": "CYS",
        "D": "ASP",
    }
    lines: list[str] = []
    serial = 1
    for residue_index, symbol in enumerate(sequence, start=1):
        for atom_name, offset in (
            ("N", 0.0),
            ("CA", 0.3),
            ("C", 0.6),
            ("O", 0.9),
        ):
            x = residue_index * 3.0 + offset
            lines.append(
                f"ATOM  {serial:5d} {atom_name:^4s} "
                f"{residue_names[symbol]:>3s} A{residue_index:4d}    "
                f"{x:8.3f}{1.0:8.3f}{2.0:8.3f}"
                "  1.00 20.00           C"
            )
            serial += 1
    return "\n".join([*lines, "TER", "END", ""])


def test_structure_generation_normalizes_exact_confidence_before_publication(
    tmp_path: Path,
) -> None:
    import torch

    coordinates = torch.zeros((3, 37, 3), dtype=torch.float32)
    client = _ProviderClient(
        [
            _ProviderResponse(
                "ACD",
                coordinates=coordinates,
                ptm=torch.tensor([0.8]),
                plddt=torch.tensor([0.8, 0.9, 1.0]),
                pdb_string=_three_residue_pdb(),
            )
        ]
    )

    catalog, projection, events = _run_generation(
        tmp_path,
        operation="generate_structure",
        client=client,
        num_samples=1,
        sequence="ACD",
    )

    assert projection["status"] == "succeeded"
    outputs = {
        item["output_port"]: item
        for item in projection["outputs"]
        if item["node_id"] == "generate"
    }
    structures = _decode_output(catalog, outputs["structure_candidates"])
    assert len(structures.items) == 1
    assert structures.items[0].data.pdb_string == _three_residue_pdb()
    assert structures.items[0].metadata["classification"] == "sampled_structure"
    observations = _decode_output(
        catalog,
        outputs["confidence_observations"],
    )
    by_metric = {
        observation.metric.contract_id: observation
        for observation in observations.entries
    }
    assert by_metric["structure.ptm"].value == pytest.approx(0.8)
    per_residue_plddt = by_metric["structure.plddt.per_residue"].value
    assert isinstance(per_residue_plddt, tuple)
    assert per_residue_plddt == pytest.approx(
        (80.0, 90.0, 100.0)
    )
    assert by_metric["structure.plddt.mean_residue"].value == pytest.approx(
        90.0
    )
    assert {
        observation.candidate_id
        for observation in observations.entries
    } == {structures.items[0].candidate_id}
    assert [call[1].track for call in client.calls] == ["structure"]
    assert [
        event["event"]["engine_role"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_role"] == "structure_sample"
    ] == ["structure_sample"]


def test_structure_generation_publishes_exact_provider_pae_matrix(
    tmp_path: Path,
) -> None:
    import torch

    pae = torch.tensor(
        [
            [0.0, 31.75, 2.0],
            [3.0, 4.0, 5.0],
            [6.0, 7.0, 8.0],
        ]
    )
    client = _ProviderClient(
        [
            _ProviderResponse(
                "ACD",
                coordinates=torch.zeros((3, 37, 3)),
                ptm=torch.tensor(0.75),
                plddt=torch.tensor([0.7, 0.8, 0.9]),
                pae=pae,
                pdb_string=_three_residue_pdb(),
            )
        ]
    )

    catalog, projection, _ = _run_generation(
        tmp_path,
        operation="generate_structure",
        client=client,
        num_samples=1,
        sequence="ACD",
    )

    assert projection["status"] == "succeeded"
    output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "generate"
        and item["output_port"] == "pae_observations"
    )
    observations = _decode_output(catalog, output)
    assert len(observations.entries) == 1
    assert observations.entries[0].value == (
        (0.0, 31.75, 2.0),
        (3.0, 4.0, 5.0),
        (6.0, 7.0, 8.0),
    )


def test_invalid_confidence_fails_after_call_without_publication(
    tmp_path: Path,
) -> None:
    import torch

    client = _ProviderClient(
        [
            _ProviderResponse(
                "ACD",
                coordinates=torch.zeros((3, 37, 3)),
                ptm=torch.tensor(0.75),
                plddt=torch.tensor([0.7, 0.8]),
                pdb_string=_three_residue_pdb(),
            )
        ]
    )

    _, projection, events = _run_generation(
        tmp_path,
        operation="generate_structure",
        client=client,
        num_samples=1,
        sequence="ACD",
    )

    assert projection["status"] == "failed"
    assert not [
        output
        for output in projection["outputs"]
        if output["node_id"] == "generate"
    ]
    invocation_ids = {
        event["event"]["invocation_id"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_role"] == "structure_sample"
    }
    terminals = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_terminal"
        and event["event"]["invocation_id"] in invocation_ids
    ]
    assert [event["status"] for event in terminals] == ["succeeded"]


def test_paired_generation_publishes_ten_exact_counterparts_and_real_calls(
    tmp_path: Path,
) -> None:
    import torch

    responses: list[_ProviderResponse] = []
    for _ in range(10):
        responses.extend(
            [
                _ProviderResponse("ACD"),
                _ProviderResponse(
                    "ACD",
                    coordinates=torch.zeros((3, 37, 3)),
                    ptm=torch.tensor(0.75),
                    plddt=torch.tensor([0.7, 0.8, 0.9]),
                    pdb_string=_three_residue_pdb(),
                ),
            ]
        )
    client = _ProviderClient(responses)

    catalog, projection, events = _run_generation(
        tmp_path,
        operation="generate_paired",
        client=client,
        num_samples=10,
    )

    assert projection["status"] == "succeeded"
    outputs = {
        item["output_port"]: item
        for item in projection["outputs"]
        if item["node_id"] == "generate"
    }
    sequences = _decode_output(catalog, outputs["sequence_candidates"])
    structures = _decode_output(catalog, outputs["structure_candidates"])
    pairing = _decode_output(catalog, outputs["counterpart_pairs"])
    confidence = _decode_output(
        catalog,
        outputs["confidence_observations"],
    )
    assert len(sequences.items) == len(structures.items) == 10
    assert len(pairing.entries) == 10
    assert len(confidence.entries) == 30
    assert [
        structure.parent_ids
        for structure in structures.items
    ] == [(sequence.candidate_id,) for sequence in sequences.items]
    assert [
        (
            entry.subject_candidate_id,
            entry.reference_candidate_id,
        )
        for entry in pairing.entries
    ] == [
        (sequence.candidate_id, structure.candidate_id)
        for sequence, structure in zip(
            sequences.items,
            structures.items,
            strict=True,
        )
    ]
    assert [
        candidate.metadata["sample_index"]
        for candidate in sequences.items
    ] == list(range(10))
    assert [
        candidate.metadata["sample_index"]
        for candidate in structures.items
    ] == list(range(10))
    assert all(
        set(candidate.metadata["effective_generation_parameters"])
        == {"sequence", "structure"}
        for candidate in structures.items
    )
    assert len({id(config) for _, config in client.calls}) == 20
    assert [call[1].track for call in client.calls] == [
        track
        for _ in range(10)
        for track in ("sequence", "structure")
    ]
    generation_events = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_role"]
        in {"sequence_parent", "structure_child"}
    ]
    assert [event["engine_role"] for event in generation_events] == [
        role
        for _ in range(10)
        for role in ("sequence_parent", "structure_child")
    ]
    for sample_index in range(10):
        parent = generation_events[sample_index * 2]
        child = generation_events[sample_index * 2 + 1]
        assert "parent_invocation_id" not in parent
        assert child["parent_invocation_id"] == parent["invocation_id"]
    terminals = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_terminal"
    ]
    assert len(terminals) >= 20
    assert all(event["status"] == "succeeded" for event in terminals)


def test_esm3_generation_and_direct_esmc_pass_the_shared_ctk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import torch
    import modules.esm3.local_adapter as local_adapter
    import modules.esm3.package as esm3_package

    from modules.esm3.package import MODULE_PACKAGE as ESM3_PACKAGE
    from modules.esm3.domain import ESMCSequenceRepresentation
    from modules.prompt_authoring.package import (
        MODULE_PACKAGE as PROMPT_AUTHORING_PACKAGE,
    )
    from modules.protein_io.package import MODULE_PACKAGE as PROTEIN_IO_PACKAGE
    from tests.fixtures.esm3_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    def source_node(mode: str) -> WorkflowNodeInstance:
        return WorkflowNodeInstance(
            node_id="source",
            node_type_id="contract_test.esm3_prompt_source",
            node_type_version="2.1.0",
            binding_id="contract_test.esm3_prompt_source.direct",
            binding_version="2.1.0",
            node_parameters={"mode": mode},
            binding_parameters={},
        )

    def environment(client: _ProviderClient) -> dict[str, Any]:
        return {
            "endpoint_id": "biohub",
            "credential_handle": object(),
            "provider_client": client,
            "private_token": "ctk-secret-must-not-publish",
        }

    local_snapshot = tmp_path / "local-snapshot"
    local_runtime_directory = tmp_path / "local-runtime"
    local_snapshot.mkdir()
    local_runtime_directory.mkdir()

    def resolve_local_runtime(
        environment_values: Any,
    ) -> local_adapter.LocalESM3Runtime:
        assert environment_values["model_snapshot_revision"] == (
            local_adapter.LOCAL_ESM3_SNAPSHOT_REVISION
        )
        return local_adapter.LocalESM3Runtime(
            snapshot_path=local_snapshot,
            runtime_directory=local_runtime_directory,
            device="cpu",
            performance_settings={},
            safe_fingerprint=f"sha256:{'c' * 64}",
        )

    monkeypatch.setattr(
        esm3_package,
        "local_runtime_structurally_available",
        lambda: True,
    )
    monkeypatch.setattr(
        local_adapter,
        "resolve_local_runtime",
        resolve_local_runtime,
    )

    def local_environment(client: _ProviderClient) -> dict[str, Any]:
        return {
            "model_snapshot_path": local_snapshot,
            "model_snapshot_revision": (
                local_adapter.LOCAL_ESM3_SNAPSHOT_REVISION
            ),
            "device": "cpu",
            "runtime_directory": local_runtime_directory,
            "performance_settings": {},
            "resolved_runtime_fingerprint": f"sha256:{'c' * 64}",
            "provider_client": client,
            "private_token": "ctk-secret-must-not-publish",
        }

    structure_response = lambda: _ProviderResponse(
        "ACD",
        coordinates=torch.zeros((3, 37, 3)),
        ptm=torch.tensor(0.75),
        plddt=torch.tensor([0.7, 0.8, 0.9]),
        pdb_string=_three_residue_pdb(),
    )
    paired_responses = [
        response
        for _ in range(10)
        for response in (_ProviderResponse("ACD"), structure_response())
    ]
    generation_common = {
        "node_type_version": "3.0.0",
        "binding_version": "3.0.0",
        "binding_parameters": {},
        "safe_environment_fingerprint": "esm3-ctk-fixture-v1",
        "invalidation_token": "esm3-ctk-fixture-v1",
        "forbidden_public_fragments": (
            "ctk-secret-must-not-publish",
        ),
    }
    esmc_common = {
        **generation_common,
        "node_type_version": "2.1.0",
        "binding_version": "2.2.0",
    }

    class ESMCClient:
        def encode(self, protein: object) -> object:
            del protein
            return SimpleNamespace(sequence=torch.tensor([0, 1, 2, 3, 4]))

        def logits(self, encoded: object, config: object) -> object:
            del encoded, config
            return SimpleNamespace(
                logits=SimpleNamespace(
                    sequence=torch.zeros((5, 64), dtype=torch.float32),
                ),
                mean_embedding=torch.zeros(
                    (1, 1, 1152),
                    dtype=torch.float32,
                ),
            )

    cases = (
        ModulePackageContractCase(
            case_id="sequence",
            node_type_id="esm3.generate_sequence",
            binding_id="esm3.generate_sequence.biohub_medium",
            node_parameters={"effective_seed": 1603, "num_samples": 1},
            environment_values=environment(
                _ProviderClient([_ProviderResponse("ACD")])
            ),
            workflow_nodes=(source_node("unassigned"),),
            workflow_edges=(
                WorkflowEdge(
                    "source",
                    "protein_prompt",
                    "contract-test-node",
                    "protein_prompt",
                ),
            ),
            expected_candidate_counts={"sequence_candidates": 1},
            **generation_common,
        ),
        ModulePackageContractCase(
            case_id="structure",
            node_type_id="esm3.generate_structure",
            binding_id="esm3.generate_structure.biohub_medium",
            node_parameters={"effective_seed": 1603, "num_samples": 1},
            environment_values=environment(
                _ProviderClient([structure_response()])
            ),
            workflow_nodes=(source_node("assigned_sequence"),),
            workflow_edges=(
                WorkflowEdge(
                    "source",
                    "protein_prompt",
                    "contract-test-node",
                    "protein_prompt",
                ),
            ),
            expected_candidate_counts={"structure_candidates": 1},
            expected_observation_counts={"confidence_observations": 3},
            **generation_common,
        ),
        ModulePackageContractCase(
            case_id="paired",
            node_type_id="esm3.generate_paired",
            binding_id="esm3.generate_paired.biohub_medium",
            node_parameters={"effective_seed": 1603, "num_samples": 10},
            environment_values=environment(
                _ProviderClient(paired_responses)
            ),
            workflow_nodes=(source_node("unassigned"),),
            workflow_edges=(
                WorkflowEdge(
                    "source",
                    "protein_prompt",
                    "contract-test-node",
                    "protein_prompt",
                ),
            ),
            expected_candidate_counts={
                "sequence_candidates": 10,
                "structure_candidates": 10,
            },
            expected_observation_counts={"confidence_observations": 30},
            **generation_common,
        ),
        ModulePackageContractCase(
            case_id="sequence-open",
            node_type_id="esm3.generate_sequence",
            binding_id="esm3.generate_sequence.biohub_open",
            node_parameters={"effective_seed": 1603, "num_samples": 1},
            environment_values=environment(
                _ProviderClient([_ProviderResponse("ACD")])
            ),
            workflow_nodes=(source_node("unassigned"),),
            workflow_edges=(
                WorkflowEdge(
                    "source",
                    "protein_prompt",
                    "contract-test-node",
                    "protein_prompt",
                ),
            ),
            expected_candidate_counts={"sequence_candidates": 1},
            **generation_common,
        ),
        ModulePackageContractCase(
            case_id="structure-open",
            node_type_id="esm3.generate_structure",
            binding_id="esm3.generate_structure.biohub_open",
            node_parameters={"effective_seed": 1603, "num_samples": 1},
            environment_values=environment(
                _ProviderClient([structure_response()])
            ),
            workflow_nodes=(source_node("assigned_sequence"),),
            workflow_edges=(
                WorkflowEdge(
                    "source",
                    "protein_prompt",
                    "contract-test-node",
                    "protein_prompt",
                ),
            ),
            expected_candidate_counts={"structure_candidates": 1},
            expected_observation_counts={"confidence_observations": 3},
            **generation_common,
        ),
        ModulePackageContractCase(
            case_id="paired-open",
            node_type_id="esm3.generate_paired",
            binding_id="esm3.generate_paired.biohub_open",
            node_parameters={"effective_seed": 1603, "num_samples": 1},
            environment_values=environment(
                _ProviderClient(
                    [_ProviderResponse("ACD"), structure_response()]
                )
            ),
            workflow_nodes=(source_node("unassigned"),),
            workflow_edges=(
                WorkflowEdge(
                    "source",
                    "protein_prompt",
                    "contract-test-node",
                    "protein_prompt",
                ),
            ),
            expected_candidate_counts={
                "sequence_candidates": 1,
                "structure_candidates": 1,
            },
            expected_observation_counts={"confidence_observations": 3},
            **generation_common,
        ),
        ModulePackageContractCase(
            case_id="sequence-local",
            node_type_id="esm3.generate_sequence",
            binding_id="esm3.generate_sequence.local_open",
            node_parameters={"effective_seed": 1603, "num_samples": 1},
            environment_values=local_environment(
                _ProviderClient([_ProviderResponse("ACD")])
            ),
            workflow_nodes=(source_node("unassigned"),),
            workflow_edges=(
                WorkflowEdge(
                    "source",
                    "protein_prompt",
                    "contract-test-node",
                    "protein_prompt",
                ),
            ),
            expected_candidate_counts={"sequence_candidates": 1},
            **generation_common,
        ),
        ModulePackageContractCase(
            case_id="structure-local",
            node_type_id="esm3.generate_structure",
            binding_id="esm3.generate_structure.local_open",
            node_parameters={"effective_seed": 1603, "num_samples": 1},
            environment_values=local_environment(
                _ProviderClient([structure_response()])
            ),
            workflow_nodes=(source_node("assigned_sequence"),),
            workflow_edges=(
                WorkflowEdge(
                    "source",
                    "protein_prompt",
                    "contract-test-node",
                    "protein_prompt",
                ),
            ),
            expected_candidate_counts={"structure_candidates": 1},
            expected_observation_counts={"confidence_observations": 3},
            **generation_common,
        ),
        ModulePackageContractCase(
            case_id="paired-local",
            node_type_id="esm3.generate_paired",
            binding_id="esm3.generate_paired.local_open",
            node_parameters={"effective_seed": 1603, "num_samples": 1},
            environment_values=local_environment(
                _ProviderClient(
                    [_ProviderResponse("ACD"), structure_response()]
                )
            ),
            workflow_nodes=(source_node("unassigned"),),
            workflow_edges=(
                WorkflowEdge(
                    "source",
                    "protein_prompt",
                    "contract-test-node",
                    "protein_prompt",
                ),
            ),
            expected_candidate_counts={
                "sequence_candidates": 1,
                "structure_candidates": 1,
            },
            expected_observation_counts={"confidence_observations": 3},
            **generation_common,
        ),
        ModulePackageContractCase(
            case_id="direct-esmc",
            node_type_id="esm3.represent_sequence",
            binding_id=(
                "esm3.represent_sequence.biohub_esmc_600m_2024_12"
            ),
            node_parameters={},
            environment_values={
                "endpoint_id": "biohub",
                "credential_handle": object(),
                "provider_client": ESMCClient(),
                "private_token": "ctk-secret-must-not-publish",
            },
            workflow_nodes=(
                WorkflowNodeInstance(
                    node_id="sequence-source",
                    node_type_id="protein_io.import_sequence",
                    node_type_version="3.0.0",
                    binding_id="protein_io.import_sequence.direct",
                    binding_version="3.0.0",
                    node_parameters={
                        "project_input_ref": "sequence-input",
                    },
                    binding_parameters={},
                ),
            ),
            workflow_edges=(
                WorkflowEdge(
                    "sequence-source",
                    "sequence",
                    "contract-test-node",
                    "sequence",
                ),
            ),
            project_inputs={"sequence-input": b">ctk\nACD\n"},
            **esmc_common,
        ),
    )

    report = verify_module_package_contract(
        ESM3_PACKAGE,
        execution_cases=cases,
        port_cases=(
            ModulePackagePortCase(
                type_id="esm3.esmc_sequence_representation",
                version="2.1.0",
                valid_value=ESMCSequenceRepresentation(
                    sequence="ACD",
                    residue_ids=None,
                    mean_embedding=(0.125, -0.25, 0.5),
                    sequence_logits_shape=(5, 64),
                ),
                invalid_values=(ProteinSequence("ACD"),),
            ),
        ),
        supporting_registrations=(
            PROMPT_AUTHORING_PACKAGE,
            PROTEIN_IO_PACKAGE,
            SOURCE_PACKAGE,
        ),
        work_root=tmp_path / "ctk",
    )

    assert [case.status for case in report.case_reports] == [
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
    ]
    assert report.verified_port_types == (
        "esm3.esmc_sequence_representation@2.1.0",
    )
