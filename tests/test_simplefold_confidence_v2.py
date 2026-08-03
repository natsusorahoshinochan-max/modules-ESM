"""Public v2 contracts for existing-structure SimpleFold confidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from core import (
    EnvironmentConfiguration,
    ProjectManager,
    ReadinessResult,
    ResultReplaySource,
    V2RunError,
    V2RunService,
    WorkflowAuthoringService,
    WorkflowDocument,
    WorkflowNodeInstance,
    build_discovered_frozen_catalog,
    build_frozen_catalog,
    discover_module_packages,
)
from core.port_types import canonical_json_bytes
from core.workflow_v2 import WorkflowEdge
from datatypes import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
    ProteinStructure,
    ScoreCollection,
)
from modules.structure_prediction.package import (
    MODULE_PACKAGE as STRUCTURE_PREDICTION_PACKAGE,
)
from tests.fixtures.scientific_operation import (
    operation_call,
    operation_context,
)


def _two_residue_pdb() -> str:
    return "\n".join(
        (
            "ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00 20.00           N  ",
            "ATOM      2  CA  ALA A   1       1.000   0.000   0.000  1.00 20.00           C  ",
            "ATOM      3  C   ALA A   1       2.000   0.000   0.000  1.00 20.00           C  ",
            "ATOM      4  N   GLY A   2       3.000   0.000   0.000  1.00 20.00           N  ",
            "ATOM      5  CA  GLY A   2       4.000   0.000   0.000  1.00 20.00           C  ",
            "ATOM      6  C   GLY A   2       5.000   0.000   0.000  1.00 20.00           C  ",
            "TER",
            "END",
            "",
        )
    )


def _two_residue_missing_ca_pdb() -> str:
    return "\n".join(
        (
            "ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00 20.00           N  ",
            "ATOM      2  CA  ALA A   1       1.000   0.000   0.000  1.00 20.00           C  ",
            "ATOM      3  C   ALA A   1       2.000   0.000   0.000  1.00 20.00           C  ",
            "ATOM      4  N   GLY A   2       3.000   0.000   0.000  1.00 20.00           N  ",
            "ATOM      5  C   GLY A   2       5.000   0.000   0.000  1.00 20.00           C  ",
            "TER",
            "END",
            "",
        )
    )


def _two_residue_no_ca_pdb() -> str:
    return "\n".join(
        (
            "ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00 20.00           N  ",
            "ATOM      2  C   ALA A   1       2.000   0.000   0.000  1.00 20.00           C  ",
            "ATOM      3  N   GLY A   2       3.000   0.000   0.000  1.00 20.00           N  ",
            "ATOM      4  C   GLY A   2       5.000   0.000   0.000  1.00 20.00           C  ",
            "TER",
            "END",
            "",
        )
    )


def _two_chain_pdb() -> str:
    return "\n".join(
        (
            "ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00 20.00           N  ",
            "ATOM      2  CA  ALA A   1       1.000   0.000   0.000  1.00 20.00           C  ",
            "TER",
            "ATOM      3  N   GLY B   4       2.000   0.000   0.000  1.00 20.00           N  ",
            "ATOM      4  CA  GLY B   4       3.000   0.000   0.000  1.00 20.00           C  ",
            "END",
            "",
        )
    )


def test_confidence_provider_segments_come_only_from_resolved_axis() -> None:
    import modules.folding.simplefold_confidence_adapter as adapter
    from modules.structure_transform.implementation import resolve_residue_axis

    axis = resolve_residue_axis(ProteinStructure(_two_chain_pdb()))

    assert [(segment.chain_id, segment.residue_ids) for segment in axis.segments] == [
        ("A", ("A:1",)),
        ("B", ("B:4",)),
    ]
    assert adapter._provider_chain_ids(axis.segments) == ("A", "B")
    assert not hasattr(adapter, "_pdb_residues")


def test_confidence_features_use_normalized_modified_polymer_axis() -> None:
    import modules.folding.simplefold_confidence_adapter as adapter
    from modules.structure_transform.implementation import resolve_residue_axis
    from tests.fixtures.structure_transform_sources.package import _FIXTURES

    axis = resolve_residue_axis(
        ProteinStructure(_FIXTURES["mse_ligand_water"]())
    )

    coordinates = adapter._coordinates_by_residue(axis)
    assert adapter._segment_sequences(axis) == ("AMG",)
    assert tuple(coordinates) == ("A:1", "A:2", "A:3")
    assert coordinates["A:2"]["SD"] == (11.0, 2.0, 3.0)
    assert "SE" not in coordinates["A:2"]
    assert axis.ca_coordinate_mask == (True, True, True)


def _confidence_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    client: Any,
    asset_prefix: str = "fixture",
) -> dict[str, Any]:
    import modules.folding.simplefold_confidence_adapter as adapter

    model_root = tmp_path / "models"
    esm2_model_root = tmp_path / "esm2-models"
    esm2_source_root = tmp_path / "esm2-source"
    model_root.mkdir(parents=True)
    esm2_model_root.mkdir()
    esm2_source_root.mkdir()
    model_payloads = {
        name: f"{asset_prefix}-{name}".encode()
        for name in adapter.SIMPLEFOLD_CONFIDENCE_ARTIFACTS
    }
    esm2_payloads = {
        name: f"{asset_prefix}-{name}".encode()
        for name in adapter.SIMPLEFOLD_CONFIDENCE_ESM2_ARTIFACTS
    }
    for name, payload in model_payloads.items():
        (model_root / name).write_bytes(payload)
    for name, payload in esm2_payloads.items():
        (esm2_model_root / name).write_bytes(payload)
    monkeypatch.setattr(
        adapter,
        "SIMPLEFOLD_ARTIFACT_SHA256",
        {
            name: hashlib.sha256(payload).hexdigest()
            for name, payload in model_payloads.items()
        },
    )
    monkeypatch.setattr(
        adapter,
        "SIMPLEFOLD_ARTIFACT_IDENTITIES",
        {
            name: {"bytes": len(payload)}
            for name, payload in model_payloads.items()
        },
    )
    monkeypatch.setattr(
        adapter,
        "SIMPLEFOLD_ESM2_ARTIFACT_SHA256",
        {
            name: hashlib.sha256(payload).hexdigest()
            for name, payload in esm2_payloads.items()
        },
    )
    monkeypatch.setattr(
        adapter,
        "SIMPLEFOLD_ESM2_ARTIFACT_IDENTITIES",
        {
            name: {"bytes": len(payload)}
            for name, payload in esm2_payloads.items()
        },
    )
    monkeypatch.setattr(
        adapter,
        "validate_installed_provider_checkout",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        adapter,
        "validated_simplefold_esm2_root",
        lambda root=None: root,
    )
    fingerprint = adapter.configured_runtime_fingerprint()
    return {
        "model_root": model_root,
        "esm2_model_root": esm2_model_root,
        "esm2_source_root": esm2_source_root,
        "device": adapter.SIMPLEFOLD_CONFIDENCE_DEVICE,
        "resolved_runtime_fingerprint": fingerprint,
        "provider_client": client,
        "private_token": "must-never-publish",
    }


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


def _run_confidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    client: Any,
    result_replay_source: ResultReplaySource | None = None,
    environment_values: dict[str, Any] | None = None,
    pdb_string: str | None = None,
) -> tuple[Any, dict[str, Any], tuple[dict[str, Any], ...]]:
    from modules.folding.package import MODULE_PACKAGE as FOLDING_PACKAGE
    from modules.structure_transform.package import (
        MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
    )
    from tests.fixtures.folding_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    source = WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.folding_structure_source",
        node_type_version="3.0.0",
        binding_id="contract_test.folding_structure_source.direct",
        binding_version="3.0.0",
        node_parameters={
            "pdb_string": _two_residue_pdb() if pdb_string is None else pdb_string
        },
        binding_parameters={},
    )
    confidence = WorkflowNodeInstance(
        node_id="confidence",
        node_type_id="folding.simplefold_confidence",
        node_type_version="4.0.0",
        binding_id="folding.simplefold_confidence.simplefold_local",
        binding_version="4.0.0",
        node_parameters={},
        binding_parameters={},
    )
    axis = WorkflowNodeInstance(
        node_id="axis",
        node_type_id="structure_transform.resolve_candidate_residue_axes",
        node_type_version="5.0.0",
        binding_id="structure_transform.resolve_candidate_residue_axes.direct",
        binding_version="5.0.0",
        node_parameters={},
        binding_parameters={},
    )
    catalog = build_frozen_catalog(
        (
            FOLDING_PACKAGE,
            SOURCE_PACKAGE,
            STRUCTURE_PREDICTION_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        )
    )
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create("SimpleFold confidence")
    authoring = WorkflowAuthoringService(projects, catalog)
    workflow = WorkflowDocument(
        schema_version="2.1.0",
        workflow_id=project.id,
        nodes=(source, axis, confidence),
        edges=(
            WorkflowEdge(
                "source",
                "structure_candidates",
                "axis",
                "structure_candidates",
            ),
            WorkflowEdge(
                "source",
                "structure_candidates",
                "confidence",
                "structure_candidates",
            ),
            WorkflowEdge(
                "axis",
                "residue_axes",
                "confidence",
                "structure_residue_axes",
            ),
        ),
        contract_lock=(),
    )
    committed = authoring.commit(
        project.id,
        expected_draft_revision=0,
        workflow=workflow,
    )
    if environment_values is None:
        environment_values = _confidence_environment(
            tmp_path,
            monkeypatch,
            client=client,
        )
    fingerprint = environment_values["resolved_runtime_fingerprint"]
    environment = EnvironmentConfiguration({
        ("folding.simplefold_confidence.simplefold_local", "4.0.0"): {
            "values": environment_values,
            "safe_fingerprint": fingerprint,
            "invalidation_token": fingerprint,
        }
    })
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
            workflow_commit_id=committed.workflow_commit_id,
            client_request_id="simplefold-confidence",
        )
        service.shutdown()
        projection = service.projection(project.id, receipt["run_id"])
        events = service.public_events(project.id, receipt["run_id"])
    finally:
        service.shutdown()
    return catalog, projection, events


def test_simplefold_confidence_is_a_separate_fixed_existing_structure_node() -> None:
    registrations = {
        registration.package_id: registration
        for registration in discover_module_packages()
    }
    registration = registrations["folding"]
    assert {
        resource.resource for resource in registration.node_definitions
    } == {
        "definitions/fold.yaml",
        "definitions/simplefold_confidence.yaml",
    }

    catalog = build_discovered_frozen_catalog()
    binding = catalog.require_contract(
        "binding",
        "folding.simplefold_confidence.simplefold_local",
        "4.0.0",
    )
    node = catalog.require_contract(
        "node_type",
        "folding.simplefold_confidence",
        "4.0.0",
    )
    assert [item["name"] for item in node.descriptor["inputs"]] == [
        "structure_candidates",
        "structure_residue_axes",
    ]
    inputs = {
        item["name"]: item["port_type"]
        for item in node.descriptor["inputs"]
    }
    assert inputs["structure_candidates"]["contract_version"] == "3.0.0"
    assert inputs["structure_residue_axes"] == {
        "contract_kind": "port_type",
        "contract_id": (
            "structure_transform."
            "candidate_resolved_residue_axis_associations"
        ),
        "contract_version": "5.0.0",
        "contract_digest": inputs["structure_residue_axes"][
            "contract_digest"
        ],
    }
    assert node.descriptor["outputs"][0]["port_type"][
        "contract_version"
    ] == "4.0.0"
    assert binding.descriptor["node_type"]["contract_id"] != "folding.fold"
    assert binding.descriptor["binding_parameters"] == {}
    assert binding.descriptor["deterministic"] is True
    assert binding.descriptor["cacheable"] is True
    assert {
        item["metric"]["contract_id"]
        for item in binding.descriptor["produced_observations"]
    } == {
        "structure.plddt.per_residue",
        "structure.plddt.mean_residue",
    }
    assert {
        item["metric"]["contract_version"]
        for item in binding.descriptor["produced_observations"]
    } == {"3.0.0"}
    assert {
        (
            item["output_port"],
            item["subject_grain"],
            item["guaranteed_multiplicity"],
            item["context_profile"]["kind"],
            item["axis_direction"],
            item["axis_port"],
        )
        for item in binding.descriptor["produced_observations"]
    } == {
        (
            "confidence_observations",
            "candidate",
            "one",
            "intrinsic",
            "input",
            "structure_residue_axes",
        )
    }

    method_reference = binding.descriptor["method"]
    assert method_reference["contract_version"] == "3.0.0"
    method = catalog.require_contract(
        method_reference["contract_kind"],
        method_reference["contract_id"],
        method_reference["contract_version"],
    )
    assert method.descriptor["model_identity"] == {
        "confidence_latent_model": "simplefold_1.6B.ckpt",
        "confidence_output_head": "plddt_module_1.6B.ckpt",
        "language_model": "esm2_t36_3B_UR50D.pt",
    }
    assert set(
        method.descriptor["checkpoint_identity"][
            "simplefold_artifact_sha256"
        ]
    ) == {"ccd.pkl", "plddt.ckpt", "simplefold_1.6B.ckpt"}
    assert set(
        method.descriptor["checkpoint_identity"]["esm2_artifact_sha256"]
    ) == {"esm2_t36_3B_UR50D.pt"}
    descriptor = repr(method.descriptor)
    for forbidden in (
        "contact-regression",
        "boltz1_conf",
        "simplefold_100M",
        "simplefold_360M",
    ):
        assert forbidden not in descriptor
    assert method.descriptor["scale_contract"] == {
        "plddt": "direct_confidence_head_[0,1]_multiply_100"
    }
    assert method.descriptor["featurization_identity"]["axis_contract"] == (
        "structure_transform.resolved_residue_axis@4.0.0"
    )
    assert method.descriptor["featurization_identity"]["raw_pdb_reparse"] == (
        "forbidden"
    )


@pytest.mark.parametrize(
    ("root_name", "asset_name"),
    (
        ("model_root", "ccd.pkl"),
        ("model_root", "plddt.ckpt"),
        ("model_root", "simplefold_1.6B.ckpt"),
        ("esm2_model_root", "esm2_t36_3B_UR50D.pt"),
    ),
)
def test_confidence_readiness_has_exact_asset_closure_and_invalidates_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    root_name: str,
    asset_name: str,
) -> None:
    import modules.folding.simplefold_confidence_adapter as adapter

    environment = _confidence_environment(
        tmp_path,
        monkeypatch,
        client=object(),
    )
    assert adapter.simplefold_confidence_readiness(
        environment
    ) == ReadinessResult(True, proof_source="direct-observation")
    validated = adapter.validate_simplefold_confidence_environment(
        environment
    )
    identity = adapter.provider_identity()
    assert validated["resolved_provider_identity"] == identity
    assert set(identity["artifact_sha256"]) == {
        "ccd.pkl",
        "plddt.ckpt",
        "simplefold_1.6B.ckpt",
    }
    assert set(identity["esm2_artifact_sha256"]) == {
        "esm2_t36_3B_UR50D.pt"
    }
    closure = json.dumps(identity, sort_keys=True)
    assert "contact-regression" not in closure
    assert "boltz1_conf" not in closure
    (environment[root_name] / asset_name).write_bytes(
        b"replacement"
    )
    assert adapter.simplefold_confidence_readiness(
        environment
    ) == ReadinessResult(
        False,
        proof_source="direct-observation",
        reason_code="simplefold_confidence_runtime_unavailable",
    )


def test_direct_head_is_statically_scaled_and_masks_invalid_residues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Client:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def evaluate(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(kwargs)
            return {
                "native_plddt": [float("nan"), 0.83],
                "valid_protein_residues": [False, True],
            }

    client = Client()
    catalog, projection, events = _run_confidence(
        tmp_path,
        monkeypatch,
        client=client,
    )
    assert projection["status"] == "succeeded", json.dumps(events, indent=2)
    output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "confidence"
        and item["output_port"] == "confidence_observations"
    )
    scores = _decode_output(catalog, output)
    assert type(scores) is ScoreCollection
    assert {
        (
            entry.metric.contract_id,
            tuple(entry.value)
            if isinstance(entry.value, list)
            else entry.value,
        )
        for entry in scores.entries
    } == {
        ("structure.plddt.per_residue", (None, 83.0)),
        ("structure.plddt.mean_residue", 83.0),
    }
    assert len({entry.candidate_id for entry in scores.entries}) == 1
    assert scores.entries[0].candidate_id.startswith("candidate-")
    assert len(client.calls) == 1
    residue_axis = client.calls[0]["residue_axis"]
    assert residue_axis.layout.residue_ids == ("A:1", "A:2")
    assert residue_axis.sequence == "AG"
    assert "fold" not in client.calls[0]
    started = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_role"] == "confidence_subject_0"
    ]
    terminal = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_terminal"
        and event["event"]["invocation_id"]
        in {item["invocation_id"] for item in started}
    ]
    assert len(started) == len(terminal) == 1
    assert terminal[0]["status"] == "succeeded"
    binding = catalog.require_contract(
        "binding",
        "folding.simplefold_confidence.simplefold_local",
        "4.0.0",
    )
    method_ref = binding.descriptor["method"]
    method = catalog.require_contract(
        "method",
        method_ref["contract_id"],
        method_ref["contract_version"],
    )
    assert started[0]["engine_identity"] == method.contract_digest
    public = json.dumps({"projection": projection, "events": events})
    for forbidden in (
        "contact-regression",
        "boltz1_conf",
        "simplefold_100M",
        "simplefold_360M",
        "must-never-publish",
    ):
        assert forbidden not in public


def test_missing_ca_axis_emits_null_and_excludes_it_from_mean(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Client:
        def __init__(self) -> None:
            self.masks: list[tuple[bool, ...]] = []

        def evaluate(self, **kwargs: Any) -> dict[str, Any]:
            residue_axis = kwargs["residue_axis"]
            self.masks.append(tuple(residue_axis.ca_coordinate_mask))
            return {
                "native_plddt": [0.71, 0.99],
                "valid_protein_residues": list(
                    residue_axis.ca_coordinate_mask
                ),
            }

    client = Client()
    catalog, projection, events = _run_confidence(
        tmp_path,
        monkeypatch,
        client=client,
        pdb_string=_two_residue_missing_ca_pdb(),
    )

    assert projection["status"] == "succeeded", json.dumps(events, indent=2)
    output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "confidence"
        and item["output_port"] == "confidence_observations"
    )
    scores = _decode_output(catalog, output)
    by_metric = {
        entry.metric.contract_id: entry.value
        for entry in scores.entries
    }
    assert client.masks == [(True, False)]
    assert by_metric["structure.plddt.per_residue"] == (71.0, None)
    assert by_metric["structure.plddt.mean_residue"] == 71.0


def test_canonical_confidence_operation_consumes_normalized_adapter_dto() -> None:
    from modules.folding.implementation import (
        SimpleFoldConfidenceImplementation,
    )
    from modules.folding.package import MODULE_PACKAGE as FOLDING_PACKAGE
    from modules.folding.simplefold_confidence_adapter import (
        SimpleFoldConfidenceAdapterResult,
    )
    from modules.structure_transform.domain import (
        CandidateResolvedResidueAxisAssociation,
        CandidateResolvedResidueAxisAssociations,
    )
    from modules.structure_transform.implementation import resolve_residue_axis
    from modules.structure_transform.package import (
        MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
    )

    class Adapter:
        def __init__(self) -> None:
            self.calls: list[tuple[Any, str]] = []

        def evaluate(
            self,
            *,
            residue_axis: Any,
            engine_role: str,
        ) -> SimpleFoldConfidenceAdapterResult:
            self.calls.append((residue_axis, engine_role))
            return SimpleFoldConfidenceAdapterResult(
                per_residue_plddt=(None, 83.0),
            )

    catalog = build_frozen_catalog(
        (
            FOLDING_PACKAGE,
            STRUCTURE_PREDICTION_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        )
    )
    context = operation_context(
        catalog,
        "folding.simplefold_confidence.simplefold_local",
        object(),
        binding_version="4.0.0",
        environment={"native_tensor": object()},
    )
    adapter = Adapter()
    operation = SimpleFoldConfidenceImplementation(
        adapter=adapter,
        method=context.method,
        produced_observations=context.produced_observations,
    )
    structure = ProteinStructure(_two_residue_pdb())
    parent = Candidate("structure", structure, [], {})
    residue_axis = resolve_residue_axis(structure)
    structure_port = catalog.require_port_type(
        "protein.structure",
        "4.0.0",
    )
    subject = CandidateDataReference(
        candidate_id=parent.candidate_id,
        data_type_id="protein.structure",
        content_digest=structure_port.content_digest(structure),
    )
    associations = CandidateResolvedResidueAxisAssociations(
        entries=(
            CandidateResolvedResidueAxisAssociation(
                subject=subject,
                residue_axis=residue_axis,
            ),
        )
    )

    outputs = operation.execute(
        operation_call(
            catalog=catalog,
            binding_id=(
                "folding.simplefold_confidence.simplefold_local"
            ),
            binding_version="4.0.0",
            inputs={
                "structure_candidates": CandidateCollection(
                    "structures",
                    "protein.structure",
                    [parent],
                ),
                "structure_residue_axes": associations,
            },
            node_parameters={},
            binding_parameters={},
        )
    )

    scores = outputs["confidence_observations"]
    assert type(scores) is ScoreCollection
    assert [entry.value for entry in scores.entries] == [
        (None, 83.0),
        83.0,
    ]
    assert {entry.subject for entry in scores.entries} == {subject}
    assert {
        entry.residue_axis.layout for entry in scores.entries
    } == {residue_axis.layout}
    assert {
        entry.residue_axis.axis_kind for entry in scores.entries
    } == {"resolved_structure"}
    assert adapter.calls == [(residue_axis, "confidence_subject_0")]


def test_confidence_joins_exact_axes_before_provider_in_candidate_order() -> None:
    from modules.folding.implementation import (
        SimpleFoldConfidenceImplementation,
    )
    from modules.folding.package import MODULE_PACKAGE as FOLDING_PACKAGE
    from modules.folding.simplefold_confidence_adapter import (
        SimpleFoldConfidenceAdapterResult,
    )
    from modules.structure_transform.domain import (
        CandidateResolvedResidueAxisAssociation,
        CandidateResolvedResidueAxisAssociations,
    )
    from modules.structure_transform.implementation import resolve_residue_axis
    from modules.structure_transform.package import (
        MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
    )
    from tests.fixtures.structure_transform_sources.package import _FIXTURES

    class Adapter:
        def __init__(self) -> None:
            self.calls: list[Any] = []

        def evaluate(
            self,
            *,
            residue_axis: Any,
            engine_role: str,
        ) -> SimpleFoldConfidenceAdapterResult:
            self.calls.append((residue_axis, engine_role))
            return SimpleFoldConfidenceAdapterResult(
                per_residue_plddt=tuple(
                    80.0 for _ in residue_axis.sequence
                ),
            )

    catalog = build_frozen_catalog(
        (
            FOLDING_PACKAGE,
            STRUCTURE_PREDICTION_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        )
    )
    context = operation_context(
        catalog,
        "folding.simplefold_confidence.simplefold_local",
        object(),
        binding_version="4.0.0",
    )
    adapter = Adapter()
    operation = SimpleFoldConfidenceImplementation(
        adapter=adapter,
        method=context.method,
        produced_observations=context.produced_observations,
    )
    mse_structure = ProteinStructure(_FIXTURES["mse_ligand_water"]())
    two_structure = ProteinStructure(_two_residue_pdb())
    mse_candidate = Candidate("z-mse", mse_structure, [], {})
    two_candidate = Candidate("a-two", two_structure, [], {})
    structure_port = catalog.require_port_type("protein.structure", "4.0.0")
    mse_subject = CandidateDataReference(
        mse_candidate.candidate_id,
        "protein.structure",
        structure_port.content_digest(mse_structure),
    )
    two_subject = CandidateDataReference(
        two_candidate.candidate_id,
        "protein.structure",
        structure_port.content_digest(two_structure),
    )
    mse_axis = resolve_residue_axis(mse_structure)
    two_axis = resolve_residue_axis(two_structure)
    associations = CandidateResolvedResidueAxisAssociations(
        entries=(
            CandidateResolvedResidueAxisAssociation(
                subject=mse_subject,
                residue_axis=mse_axis,
            ),
            CandidateResolvedResidueAxisAssociation(
                subject=two_subject,
                residue_axis=two_axis,
            ),
        )
    )
    assert [entry.subject for entry in associations.entries] == [
        two_subject,
        mse_subject,
    ]

    outputs = operation.execute(
        operation_call(
            catalog=catalog,
            binding_id=(
                "folding.simplefold_confidence.simplefold_local"
            ),
            binding_version="4.0.0",
            inputs={
                "structure_candidates": CandidateCollection(
                    "structures",
                    "protein.structure",
                    [mse_candidate, two_candidate],
                ),
                "structure_residue_axes": associations,
            },
        )
    )

    assert adapter.calls == [
        (mse_axis, "confidence_subject_0"),
        (two_axis, "confidence_subject_1"),
    ]
    scores = outputs["confidence_observations"]
    assert [entry.subject for entry in scores.entries] == [
        mse_subject,
        mse_subject,
        two_subject,
        two_subject,
    ]
    assert [entry.residue_axis.layout for entry in scores.entries] == [
        mse_axis.layout,
        mse_axis.layout,
        two_axis.layout,
        two_axis.layout,
    ]


def test_confidence_validates_complete_axis_join_before_provider() -> None:
    from modules.folding.implementation import (
        SimpleFoldConfidenceImplementation,
    )
    from modules.folding.package import MODULE_PACKAGE as FOLDING_PACKAGE
    from modules.structure_transform.domain import (
        CandidateResolvedResidueAxisAssociation,
        CandidateResolvedResidueAxisAssociations,
    )
    from modules.structure_transform.implementation import resolve_residue_axis
    from modules.structure_transform.package import (
        MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
    )

    class BombAdapter:
        def __init__(self) -> None:
            self.calls = 0

        def evaluate(self, **_kwargs: Any) -> Any:
            self.calls += 1
            raise AssertionError("provider must not run before the full join")

    catalog = build_frozen_catalog(
        (
            FOLDING_PACKAGE,
            STRUCTURE_PREDICTION_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        )
    )
    context = operation_context(
        catalog,
        "folding.simplefold_confidence.simplefold_local",
        object(),
        binding_version="4.0.0",
    )
    adapter = BombAdapter()
    operation = SimpleFoldConfidenceImplementation(
        adapter=adapter,
        method=context.method,
        produced_observations=context.produced_observations,
    )
    first_structure = ProteinStructure(_two_residue_pdb())
    second_structure = ProteinStructure(_two_chain_pdb())
    first = Candidate("first", first_structure, [], {})
    second = Candidate("second", second_structure, [], {})
    structure_port = catalog.require_port_type("protein.structure", "4.0.0")
    first_subject = CandidateDataReference(
        first.candidate_id,
        "protein.structure",
        structure_port.content_digest(first_structure),
    )
    incomplete_associations = CandidateResolvedResidueAxisAssociations(
        entries=(
            CandidateResolvedResidueAxisAssociation(
                subject=first_subject,
                residue_axis=resolve_residue_axis(first_structure),
            ),
        )
    )
    call = operation_call(
        catalog=catalog,
        binding_id="folding.simplefold_confidence.simplefold_local",
        binding_version="4.0.0",
        inputs={
            "structure_candidates": CandidateCollection(
                "structures",
                "protein.structure",
                [first, second],
            ),
            "structure_residue_axes": incomplete_associations,
        },
    )

    with pytest.raises(
        ValueError,
        match="resolved axes must cover exact structure references",
    ):
        operation.execute(call)
    assert adapter.calls == 0


def test_confidence_preflights_resolved_ca_eligibility_before_provider() -> None:
    from modules.folding.implementation import (
        SimpleFoldConfidenceImplementation,
    )
    from modules.folding.package import MODULE_PACKAGE as FOLDING_PACKAGE
    from modules.structure_transform.domain import (
        CandidateResolvedResidueAxisAssociation,
        CandidateResolvedResidueAxisAssociations,
    )
    from modules.structure_transform.implementation import resolve_residue_axis
    from modules.structure_transform.package import (
        MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
    )

    class BombAdapter:
        def __init__(self) -> None:
            self.calls = 0

        def evaluate(self, **_kwargs: Any) -> Any:
            self.calls += 1
            raise AssertionError("provider must not run before axis preflight")

    catalog = build_frozen_catalog(
        (
            FOLDING_PACKAGE,
            STRUCTURE_PREDICTION_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        )
    )
    context = operation_context(
        catalog,
        "folding.simplefold_confidence.simplefold_local",
        object(),
        binding_version="4.0.0",
    )
    adapter = BombAdapter()
    operation = SimpleFoldConfidenceImplementation(
        adapter=adapter,
        method=context.method,
        produced_observations=context.produced_observations,
    )
    valid_structure = ProteinStructure(_two_residue_pdb())
    no_ca_structure = ProteinStructure(_two_residue_no_ca_pdb())
    valid = Candidate("valid", valid_structure, [], {})
    no_ca = Candidate("no-ca", no_ca_structure, [], {})
    structure_port = catalog.require_port_type("protein.structure", "4.0.0")
    valid_subject = CandidateDataReference(
        valid.candidate_id,
        "protein.structure",
        structure_port.content_digest(valid_structure),
    )
    no_ca_subject = CandidateDataReference(
        no_ca.candidate_id,
        "protein.structure",
        structure_port.content_digest(no_ca_structure),
    )
    associations = CandidateResolvedResidueAxisAssociations(
        entries=tuple(
            CandidateResolvedResidueAxisAssociation(
                subject=subject,
                residue_axis=resolve_residue_axis(structure),
            )
            for subject, structure in (
                (valid_subject, valid_structure),
                (no_ca_subject, no_ca_structure),
            )
        )
    )

    with pytest.raises(ValueError, match="at least one resolved CA"):
        operation.execute(
            operation_call(
                catalog=catalog,
                binding_id=(
                    "folding.simplefold_confidence.simplefold_local"
                ),
                binding_version="4.0.0",
                inputs={
                    "structure_candidates": CandidateCollection(
                        "structures",
                        "protein.structure",
                        [valid, no_ca],
                    ),
                    "structure_residue_axes": associations,
                },
            )
        )
    assert adapter.calls == 0


def test_resolved_asset_digests_are_bound_to_result_contract_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.folding.simplefold_confidence_adapter as adapter
    from modules.folding.package import _simplefold_confidence_binding

    class Client:
        def evaluate(self, **_kwargs: Any) -> dict[str, Any]:
            return {
                "native_plddt": [0.71, 0.83],
                "valid_protein_residues": [True, True],
            }

    baseline_identity = dict(
        _simplefold_confidence_binding().implementation_identity
    )
    environment = _confidence_environment(
        tmp_path / "environment",
        monkeypatch,
        client=Client(),
    )
    _catalog, projection, _ = _run_confidence(
        tmp_path / "run",
        monkeypatch,
        client=Client(),
        environment_values=environment,
    )
    result_identity = next(
        output["result_identity"]
        for output in projection["outputs"]
        if output["node_id"] == "confidence"
    )
    assert result_identity.startswith("sha256:")
    replacement = dict(adapter.SIMPLEFOLD_ARTIFACT_SHA256)
    replacement["ccd.pkl"] = "0" * 64
    monkeypatch.setattr(
        adapter,
        "SIMPLEFOLD_ARTIFACT_SHA256",
        replacement,
    )
    changed_identity = dict(
        _simplefold_confidence_binding().implementation_identity
    )
    assert changed_identity != baseline_identity


def test_failed_confidence_readiness_precedes_cache_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Replay(ResultReplaySource):
        def lookup(self, **kwargs: Any) -> Any:
            raise AssertionError("cache lookup must not precede Readiness")

    environment = _confidence_environment(
        tmp_path,
        monkeypatch,
        client=object(),
    )
    (environment["model_root"] / "ccd.pkl").unlink()
    with pytest.raises(V2RunError) as rejected:
        _run_confidence(
            tmp_path,
            monkeypatch,
            client=object(),
            result_replay_source=Replay(),
            environment_values=environment,
        )
    assert rejected.value.code == "readiness_rejected"
