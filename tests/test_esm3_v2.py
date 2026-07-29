"""Public v2 contracts for the cohesive remote ESM-3 package."""

from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from core import (
    EnvironmentConfiguration,
    ProjectManager,
    V2RunService,
    WorkflowAuthoringService,
    WorkflowDocument,
    WorkflowNodeInstance,
    build_discovered_frozen_catalog,
    build_frozen_catalog,
    discover_module_packages,
    parse_workflow_document,
)
from core.port_types import canonical_json_bytes
from core.workflow_v2 import WorkflowEdge
from datatypes import (
    FunctionAnnotation,
    FunctionAnnotations,
    ProteinPrompt,
    ResidueLayout,
    ResidueTrack,
)


def test_remote_esm3_is_one_package_with_three_fixed_generation_nodes() -> None:
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
    }

    catalog = build_discovered_frozen_catalog()
    owned_nodes = {
        (contract_id, version)
        for kind, contract_id, version in catalog.owners
        if kind == "node_type"
        and "esm3" in catalog.owners[(kind, contract_id, version)]
    }
    assert owned_nodes == {
        ("esm3.generate_sequence", "2.0.0"),
        ("esm3.generate_structure", "2.0.0"),
        ("esm3.generate_paired", "2.0.0"),
    }

    for operation in ("generate_sequence", "generate_structure", "generate_paired"):
        node = catalog.require_contract(
            "node_type",
            f"esm3.{operation}",
            "2.0.0",
        )
        binding = catalog.require_contract(
            "binding",
            f"esm3.{operation}.biohub_medium",
            "2.0.0",
        )
        assert "model_name" not in node.descriptor["node_parameters"]
        assert "model_name" not in binding.descriptor["binding_parameters"]
        assert binding.descriptor["execution_route"] == "adapter"
        assert binding.descriptor["method"]["contract_id"] == (
            f"esm3.{operation}.esm3_medium_2024_08"
        )
        assert binding.descriptor["implementation_identity"]["model"] == (
            "esm3-medium-2024-08"
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


def test_adapter_preserves_every_representable_prompt_track_and_symbol() -> None:
    from modules.esm3.adapter import protein_prompt_to_provider

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

    prompt.sequence_track.values[0] = "J"
    with pytest.raises(ValueError, match="cannot represent sequence symbol 'J'"):
        protein_prompt_to_provider(prompt)


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
    client: _ProviderClient,
    num_samples: int,
    sequence: str | None = None,
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
            node_type_version="2.0.0",
            binding_id="prompt_authoring.build_residue_layout.direct",
            binding_version="2.0.0",
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
            node_type_version="2.0.0",
            binding_id="prompt_authoring.assemble_protein_prompt.direct",
            binding_version="2.0.0",
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
                    node_type_version="2.0.0",
                    binding_id="protein_io.import_sequence.direct",
                    binding_version="2.0.0",
                    node_parameters={"project_input_ref": "sequence-input"},
                    binding_parameters={},
                ),
                WorkflowNodeInstance(
                    node_id="update_sequence",
                    node_type_id="prompt_authoring.update_prompt_sequence",
                    node_type_version="2.0.0",
                    binding_id="prompt_authoring.update_prompt_sequence.direct",
                    binding_version="2.0.0",
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
    nodes.append(
        WorkflowNodeInstance(
            node_id="generate",
            node_type_id=f"esm3.{operation}",
            node_type_version="2.0.0",
            binding_id=f"esm3.{operation}.biohub_medium",
            binding_version="2.0.0",
            node_parameters={
                "effective_seed": 1603,
                "num_samples": num_samples,
            },
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
        schema_version="2.0.0",
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
    environment = EnvironmentConfiguration(
        {
            (f"esm3.{operation}.biohub_medium", "2.0.0"): {
                "values": {
                    "endpoint_id": "biohub",
                    "credential_handle": object(),
                    "provider_client": client,
                    "private_token": "secret-must-never-publish",
                    "runtime_path": "/private/esm3-runtime",
                },
                "safe_fingerprint": "biohub-medium-fixture-v1",
                "invalidation_token": "biohub-medium-fixture-v1",
            }
        }
    )
    service = V2RunService(projects, catalog, authoring, environment)
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
    assert all(candidate.parent_ids == [] for candidate in candidates.items)
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
    assert structures.items[0].data.source == "esm3"
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
    assert by_metric["structure.plddt.per_residue"].value == pytest.approx(
        [80.0, 90.0, 100.0]
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
            [0.0, 1.0, 2.0],
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
    assert observations.entries[0].value == pae.tolist()


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
    ] == [[sequence.candidate_id] for sequence in sequences.items]
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
    assert [call[1].track for call in client.calls] == [
        track
        for _ in range(10)
        for track in ("sequence", "structure")
    ]
    generation_roles = [
        event["event"]["engine_role"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_role"]
        in {"sequence_parent", "structure_child"}
    ]
    assert generation_roles == [
        role
        for _ in range(10)
        for role in ("sequence_parent", "structure_child")
    ]
    terminals = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_terminal"
    ]
    assert len(terminals) >= 20
    assert all(event["status"] == "succeeded" for event in terminals)
