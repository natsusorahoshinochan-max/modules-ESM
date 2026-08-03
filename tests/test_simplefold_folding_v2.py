"""Public v2 contracts for the SimpleFold folding Binding."""

from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from core import (
    EnvironmentConfiguration,
    ProjectManager,
    ReadinessResult,
    ResultReplayHit,
    ResultReplaySource,
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
    ProteinSequence,
    ProteinStructure,
)
from tests.fixtures.result_replay_v2 import admitted_replay_outputs
from tests.fixtures.scientific_operation import (
    operation_call,
    operation_context,
)


def test_simplefold_is_one_explicit_binding_of_the_shared_folding_node() -> None:
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
    simplefold = catalog.require_contract(
        "binding",
        "folding.fold.simplefold_local",
        "6.0.0",
    )
    esmfold2 = catalog.require_contract(
        "binding",
        "folding.fold.esmfold2_local",
        "6.0.0",
    )
    assert simplefold.descriptor["node_type"] == esmfold2.descriptor["node_type"]
    assert simplefold.descriptor["execution_route"] == "adapter"
    assert simplefold.descriptor["binding_parameters"] == {
        "num_steps": {
            "parameter_scope": "scientific",
            "scientific_meaning": (
                "Exact SimpleFold Euler-Maruyama sampling step count."
            ),
            "value_contract": {
                "type": "integer",
                "minimum": 1,
                "maximum": 50,
            },
            "default": 50,
        },
    }
    assert simplefold.descriptor["deterministic"] is False
    assert simplefold.descriptor["cacheable"] is False
    assert simplefold.descriptor["implementation_identity"]["model"] == (
        "simplefold_100M"
    )
    assert simplefold.descriptor["implementation_identity"]["device"] == (
        "cpu"
    )
    assert simplefold.descriptor["produced_observations"] == ()

    method_reference = simplefold.descriptor["method"]
    method = catalog.require_contract(
        method_reference["contract_kind"],
        method_reference["contract_id"],
        method_reference["contract_version"],
    )
    assert method_reference["contract_version"] == "4.0.0"
    assert method.descriptor["model_identity"]["folding_model"] == (
        "simplefold_100M"
    )
    assert method.descriptor["scale_contract"]["plddt"] == (
        "provider_high_level_[0,100]_identity"
    )
    assert {
        "model",
        "model_name",
        "checkpoint_path",
        "device",
        "staging_directory",
    }.isdisjoint(simplefold.descriptor["binding_parameters"])
    assert set(
        method.descriptor["checkpoint_identity"][
            "simplefold_artifact_sha256"
        ]
    ) == {
        "ccd.pkl",
        "plddt.ckpt",
        "simplefold_1.6B.ckpt",
        "simplefold_100M.ckpt",
    }


def test_simplefold_readiness_validates_assets_without_hiding_siblings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.folding.package as folding_package
    import modules.folding.simplefold_adapter as adapter
    from modules.structure_prediction.package import (
        MODULE_PACKAGE as STRUCTURE_PREDICTION_PACKAGE,
    )
    from modules.structure_transform.package import (
        MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
    )

    environment = _simplefold_environment(
        tmp_path,
        monkeypatch,
        client=object(),
    )
    assert adapter.simplefold_readiness(environment) == ReadinessResult(
        True,
        proof_source="direct-observation",
    )
    assert set(adapter.provider_identity()["artifact_sha256"]) == {
        "ccd.pkl",
        "plddt.ckpt",
        "simplefold_1.6B.ckpt",
        "simplefold_100M.ckpt",
    }
    (environment["model_root"] / "simplefold_100M.ckpt").write_bytes(
        b"replacement"
    )
    assert adapter.simplefold_readiness(environment) == ReadinessResult(
        False,
        proof_source="direct-observation",
        reason_code="simplefold_runtime_unavailable",
    )

    monkeypatch.setattr(
        folding_package,
        "simplefold_runtime_structurally_available",
        lambda: False,
    )
    catalog = build_frozen_catalog(
        (
            folding_package.MODULE_PACKAGE,
            STRUCTURE_PREDICTION_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        )
    )
    assert catalog.require_contract(
        "binding",
        "folding.fold.esmfold2_remote",
        "7.0.0",
    )
    assert catalog.require_contract(
        "binding",
        "folding.fold.esmfold2_local",
        "6.0.0",
    )
    snapshots = {
        item["binding"]["contract_id"]: item
        for item in catalog.availability
    }
    assert snapshots["folding.fold.simplefold_local"]["available"] is False
    assert {
        "folding.fold.esmfold2_remote",
        "folding.fold.esmfold2_local",
    }.issubset(snapshots)


def _two_residue_pdb() -> str:
    return "\n".join(
        (
            "ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00 71.00           N  ",
            "ATOM      2  CA  ALA A   1       1.000   0.000   0.000  1.00 71.00           C  ",
            "ATOM      3  C   ALA A   1       2.000   0.000   0.000  1.00 71.00           C  ",
            "ATOM      4  N   GLY A   2       3.000   0.000   0.000  1.00 83.00           N  ",
            "ATOM      5  CA  GLY A   2       4.000   0.000   0.000  1.00 83.00           C  ",
            "ATOM      6  C   GLY A   2       5.000   0.000   0.000  1.00 83.00           C  ",
            "TER",
            "END",
            "",
        )
    )


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


def _trusted_serialized_pdb_with_independent_residue_names() -> str:
    return "\n".join(
        (
            "ATOM      1  N   GLY A   8       0.000   0.000   0.000  1.00 71.00           N  ",
            "ATOM      2  CA  GLY A   8       1.000   0.000   0.000  1.00 71.00           C  ",
            "ATOM      3  C   GLY A   8       2.000   0.000   0.000  1.00 71.00           C  ",
            "ATOM      4  N   ALA A  13       3.000   0.000   0.000  1.00 83.00           N  ",
            "ATOM      5  CA  ALA A  13       4.000   0.000   0.000  1.00 83.00           C  ",
            "ATOM      6  C   ALA A  13       5.000   0.000   0.000  1.00 83.00           C  ",
            "TER",
            "END",
            "",
        )
    )


def _simplefold_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    client: Any,
) -> dict[str, Any]:
    import modules.folding.simplefold_adapter as adapter

    model_root = tmp_path / "models"
    esm2_model_root = tmp_path / "esm2-models"
    esm2_source_root = tmp_path / "esm2-source"
    model_root.mkdir(parents=True)
    esm2_model_root.mkdir()
    esm2_source_root.mkdir()
    model_payloads = {
        name: f"fixture-{name}".encode()
        for name in adapter.SIMPLEFOLD_FOLDING_ARTIFACTS
    }
    esm2_payloads = {
        "esm2_t36_3B_UR50D.pt": b"fixture-esm2",
        "esm2_t36_3B_UR50D-contact-regression.pt": b"fixture-contact",
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
    import modules.folding.simplefold_runtime as provider_runtime

    monkeypatch.setattr(
        provider_runtime,
        "validated_simplefold_esm2_root",
        lambda root=None: root,
    )
    return {
        "model_root": model_root,
        "esm2_model_root": esm2_model_root,
        "esm2_source_root": esm2_source_root,
        "device": adapter.SIMPLEFOLD_DEVICE,
        "resolved_runtime_fingerprint": adapter.configured_runtime_fingerprint(),
        "provider_client": client,
        "private_token": "must-never-publish",
    }


def _run_simplefold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    client: Any,
    num_samples: int = 2,
    result_replay_source: ResultReplaySource | None = None,
    environment_values: dict[str, Any] | None = None,
    project_id: str = "simplefold",
) -> tuple[Any, dict[str, Any], tuple[dict[str, Any], ...]]:
    from modules.folding.package import MODULE_PACKAGE as FOLDING_PACKAGE
    from modules.structure_prediction.package import (
        MODULE_PACKAGE as STRUCTURE_PREDICTION_PACKAGE,
    )
    from modules.structure_transform.package import (
        MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
    )
    from tests.fixtures.folding_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    source = WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.folding_sequence_source",
        node_type_version="3.0.0",
        binding_id="contract_test.folding_sequence_source.direct",
        binding_version="3.0.0",
        node_parameters={"sequence": "AG"},
        binding_parameters={},
    )
    fold = WorkflowNodeInstance(
        node_id="fold",
        node_type_id="folding.fold",
        node_type_version="6.0.0",
        binding_id="folding.fold.simplefold_local",
        binding_version="6.0.0",
        node_parameters={
            "effective_seed": 1603,
            "num_samples": num_samples,
        },
        binding_parameters={"num_steps": 10},
    )
    materialize = WorkflowNodeInstance(
        node_id="materialize-confidence",
        node_type_id="structure_prediction.materialize_confidence",
        node_type_version="1.0.0",
        binding_id="structure_prediction.materialize_confidence.direct",
        binding_version="1.0.0",
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
    project = projects.create(project_id)
    authoring = WorkflowAuthoringService(projects, catalog)
    workflow = WorkflowDocument(
        schema_version="2.1.0",
        workflow_id=project.id,
        nodes=(source, fold, materialize),
        edges=(
            WorkflowEdge(
                "source",
                "sequence_candidates",
                "fold",
                "sequence_candidates",
            ),
            WorkflowEdge(
                "fold",
                "structure_candidates",
                "materialize-confidence",
                "structure_candidates",
            ),
            WorkflowEdge(
                "fold",
                "confidence_facts",
                "materialize-confidence",
                "confidence_facts",
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
        environment_values = _simplefold_environment(
            tmp_path,
            monkeypatch,
            client,
        )
    environment = EnvironmentConfiguration({
        ("folding.fold.simplefold_local", "6.0.0"): {
            "values": environment_values,
            "safe_fingerprint": environment_values[
                "resolved_runtime_fingerprint"
            ],
            "invalidation_token": environment_values[
                "resolved_runtime_fingerprint"
            ],
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
            client_request_id="simplefold",
        )
        service.shutdown()
        projection = service.projection(project.id, receipt["run_id"])
        events = service.public_events(project.id, receipt["run_id"])
    finally:
        service.shutdown()
    return catalog, projection, events


def test_simplefold_preserves_high_level_plddt_and_exact_multi_sample_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Client:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def fold(self, **kwargs: Any) -> tuple[list[ProteinStructure], list[dict[str, Any]]]:
            self.calls.append(kwargs)
            return (
                [
                    ProteinStructure(_two_residue_pdb()),
                    ProteinStructure(_two_residue_pdb()),
                ],
                [
                    {
                        "per_residue": (
                            [0.71, 0.83]
                            if sample == 0
                            else [71.0, 83.0]
                        ),
                        "sample_index": sample,
                    }
                    for sample in range(2)
                ],
            )

    client = Client()
    catalog, projection, events = _run_simplefold(
        tmp_path,
        monkeypatch,
        client=client,
    )

    assert projection["status"] == "succeeded", json.dumps(events, indent=2)
    outputs = {
        output["output_port"]: output
        for output in projection["outputs"]
        if output["node_id"] == "fold"
    }
    structures = _decode_output(catalog, outputs["structure_candidates"])
    facts = _decode_output(
        catalog,
        outputs["confidence_facts"],
    )
    materialized_output = next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "materialize-confidence"
        and output["output_port"] == "observations"
    )
    observations = _decode_output(
        catalog,
        materialized_output,
    )
    assert len(structures.items) == 2
    assert len(set(item.candidate_id for item in structures.items)) == 2
    assert {
        item.metadata["sample_index"] for item in structures.items
    } == {0, 1}
    assert all(len(item.parent_ids) == 1 for item in structures.items)
    assert len(facts.entries) == 2
    assert {
        fact.plddt_per_residue for fact in facts.entries
    } == {(0.71, 0.83), (71.0, 83.0)}
    assert all(fact.ptm is None and fact.pae is None for fact in facts.entries)
    assert {
        item.metadata["prediction_key"] for item in structures.items
    } == {fact.prediction_key for fact in facts.entries}
    assert len({fact.prediction_key for fact in facts.entries}) == 2
    assert all(
        fact.prediction_axis == facts.entries[0].prediction_axis
        for fact in facts.entries
    )
    assert {
        (entry.metric.contract_id, entry.value)
        for entry in observations.entries
    } == {
        ("structure.plddt.per_residue", (0.71, 0.83)),
        ("structure.plddt.mean_residue", 0.77),
        ("structure.plddt.per_residue", (71.0, 83.0)),
        ("structure.plddt.mean_residue", 77.0),
    }
    assert len(observations.entries) == 4
    assert {entry.candidate_id for entry in observations.entries} == {
        item.candidate_id for item in structures.items
    }
    assert all(
        entry.residue_axis is not None
        and entry.residue_axis.layout.residue_ids == ("A:1", "A:2")
        for entry in observations.entries
    )
    assert len(client.calls) == 1
    assert client.calls[0]["num_steps"] == 10
    assert client.calls[0]["num_samples"] == 2
    assert not client.calls[0]["staging_directory"].exists()
    readiness_index = next(
        index
        for index, event in enumerate(events)
        if event["event"]["type"] == "readiness_attested"
        and event["event"]["binding"]["contract_id"]
        == "folding.fold.simplefold_local"
    )
    binding = catalog.require_contract(
        "binding",
        "folding.fold.simplefold_local",
        "6.0.0",
    )
    method = catalog.require_contract(
        "method",
        binding.descriptor["method"]["contract_id"],
        binding.descriptor["method"]["contract_version"],
    )
    started = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_role"] == "fold_parent_0"
    ]
    invocation_index = next(
        index
        for index, event in enumerate(events)
        if event["event"] in started
    )
    assert readiness_index < invocation_index
    terminal = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_terminal"
        and event["event"]["invocation_id"]
        in {item["invocation_id"] for item in started}
    ]
    assert len(started) == len(terminal) == 1
    assert terminal[0]["status"] == "succeeded"
    assert started[0]["engine_identity"] == method.contract_digest
    assert started[0]["invocation_provenance"] == {
        "effective_randomness": {
            "control": "exact_seed",
            "effective_seed": structures.items[0].metadata[
                "effective_call_seed"
            ],
        }
    }
    assert {
        "provider",
        "model",
        "route",
        "runtime_fingerprint",
        "checkpoint",
        "seed_control",
    }.isdisjoint(structures.items[0].metadata)


def test_simplefold_admits_provider_pdb_without_rebuilding_sequence(
    tmp_path: Path,
) -> None:
    from modules.folding.simplefold_adapter import LocalSimpleFoldAdapter

    class Client:
        def fold(
            self,
            **_kwargs: Any,
        ) -> tuple[list[ProteinStructure], list[dict[str, Any]]]:
            return (
                [
                    ProteinStructure(
                        _trusted_serialized_pdb_with_independent_residue_names()
                    )
                ],
                [{"per_residue": [71.0, 83.0], "sample_index": 0}],
            )

    class Resources:
        @contextmanager
        def temporary_directory(self, *, prefix: str):
            staging = tmp_path / prefix
            staging.mkdir()
            yield staging

        @contextmanager
        def engine_invocation(self, **_kwargs: Any):
            yield

    result = LocalSimpleFoldAdapter(
        environment={"provider_client": Client()},
        resources=Resources(),
    ).fold(
        sequence=ProteinSequence("AG", ("Q:-2A", "Q:10")),
        num_steps=10,
        num_samples=1,
        derived_call_seed=1603,
        engine_role="fold_parent_0",
    )

    assert result.samples[0].structure == ProteinStructure(
        _trusted_serialized_pdb_with_independent_residue_names()
    )


def test_canonical_simplefold_operation_consumes_normalized_adapter_dto() -> None:
    from modules.folding.implementation import (
        SimpleFoldFoldingImplementation,
    )
    from modules.folding.package import MODULE_PACKAGE as FOLDING_PACKAGE
    from modules.folding.simplefold_adapter import (
        SimpleFoldAdapterResult,
        SimpleFoldSampleResult,
    )
    from modules.structure_prediction.package import (
        MODULE_PACKAGE as STRUCTURE_PREDICTION_PACKAGE,
    )
    from modules.structure_transform.package import (
        MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
    )
    from modules.structure_prediction.domain import ConfidenceFactCollection

    class Adapter:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def fold(self, **kwargs: Any) -> SimpleFoldAdapterResult:
            self.calls.append(kwargs)
            return SimpleFoldAdapterResult(
                samples=(
                    SimpleFoldSampleResult(
                        structure=ProteinStructure(
                            _two_residue_pdb(),
                        ),
                        per_residue_plddt=(71.0, 83.0),
                    ),
                ),
                effective_call_seed=kwargs["derived_call_seed"],
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
        "folding.fold.simplefold_local",
        object(),
        binding_version="6.0.0",
        environment={"native_scores": object()},
    )
    adapter = Adapter()
    operation = SimpleFoldFoldingImplementation(
        adapter=adapter,
        method=context.method,
    )
    parent = Candidate(
        "parent",
        ProteinSequence("AG"),
        [],
        {},
    )

    outputs = operation.execute(
        operation_call(
            catalog=catalog,
            binding_id="folding.fold.simplefold_local",
            binding_version="6.0.0",
            inputs={
                "sequence_candidates": CandidateCollection(
                    "parents",
                    "protein.sequence",
                    [parent],
                )
            },
            node_parameters={"effective_seed": 1603, "num_samples": 1},
            binding_parameters={"num_steps": 10},
        )
    )

    structures = outputs["structure_candidates"]
    facts = outputs["confidence_facts"]
    assert type(structures) is CandidateCollection
    assert type(facts) is ConfidenceFactCollection
    assert {
        "provider",
        "model",
        "route",
        "runtime_fingerprint",
        "checkpoint",
        "seed_control",
    }.isdisjoint(structures.items[0].metadata)
    assert len(facts.entries) == 1
    fact = facts.entries[0]
    assert fact.plddt_per_residue == (71.0, 83.0)
    assert fact.ptm is None
    assert fact.pae is None
    assert fact.prediction_axis.sequence.sequence == "AG"
    assert fact.prediction_axis.sequence.residue_ids == ("A:1", "A:2")
    assert fact.prediction_axis.layout.residue_ids == ("A:1", "A:2")
    assert facts.observation_method == context.method
    assert structures.items[0].metadata["prediction_key"] == (
        fact.prediction_key
    )
    assert set(outputs) == {"structure_candidates", "confidence_facts"}
    assert adapter.calls == [
        {
            "sequence": parent.data,
            "num_steps": 10,
            "num_samples": 1,
            "derived_call_seed": structures.items[0].metadata[
                "effective_call_seed"
            ],
            "engine_role": "fold_parent_0",
        }
    ]


def test_simplefold_call_seed_uses_candidate_content_not_candidate_identity(
) -> None:
    from modules.folding.implementation import SimpleFoldFoldingImplementation
    from modules.folding.package import MODULE_PACKAGE as FOLDING_PACKAGE
    from modules.folding.simplefold_adapter import (
        SimpleFoldAdapterResult,
        SimpleFoldSampleResult,
    )
    from modules.structure_prediction.package import (
        MODULE_PACKAGE as STRUCTURE_PREDICTION_PACKAGE,
    )
    from modules.structure_transform.package import (
        MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
    )

    class Adapter:
        def __init__(self) -> None:
            self.seeds: list[int] = []

        def fold(self, **kwargs: Any) -> SimpleFoldAdapterResult:
            seed = kwargs["derived_call_seed"]
            self.seeds.append(seed)
            return SimpleFoldAdapterResult(
                samples=(
                    SimpleFoldSampleResult(
                        structure=ProteinStructure(_two_residue_pdb()),
                        per_residue_plddt=(71.0, 83.0),
                    ),
                ),
                effective_call_seed=seed,
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
        "folding.fold.simplefold_local",
        object(),
        binding_version="6.0.0",
    )

    def observed(candidate_id: str, sequence: str) -> int:
        adapter = Adapter()
        operation = SimpleFoldFoldingImplementation(
            adapter=adapter,
            method=context.method,
        )
        parent = Candidate(candidate_id, ProteinSequence(sequence), [], {})
        operation.execute(
            operation_call(
                catalog=catalog,
                binding_id="folding.fold.simplefold_local",
                binding_version="6.0.0",
                inputs={
                    "sequence_candidates": CandidateCollection(
                        "parents",
                        "protein.sequence",
                        [parent],
                    )
                },
                node_parameters={"effective_seed": 1603, "num_samples": 1},
                binding_parameters={"num_steps": 10},
            )
        )
        return adapter.seeds[0]

    original = observed("candidate-a", "AG")
    renamed = observed("candidate-renamed", "AG")
    changed_content = observed("candidate-a", "AA")

    assert original == renamed
    assert original != changed_content


def test_source_cache_replay_preserves_noncacheable_simplefold_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.folding.package import MODULE_PACKAGE as FOLDING_PACKAGE
    from modules.structure_prediction.package import (
        MODULE_PACKAGE as STRUCTURE_PREDICTION_PACKAGE,
    )
    from modules.structure_transform.package import (
        MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
    )
    from tests.fixtures.folding_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    class Client:
        def __init__(self) -> None:
            self.staging: list[Path] = []

        def fold(self, **kwargs: Any) -> tuple[list[ProteinStructure], list[dict[str, Any]]]:
            staging = kwargs["staging_directory"]
            assert not (staging / "fixed-provider-name").exists()
            (staging / "fixed-provider-name").write_text("owned")
            self.staging.append(staging)
            return (
                [ProteinStructure(_two_residue_pdb())],
                [{"per_residue": [71.0, 83.0], "sample_index": 0}],
            )

    cached_source = CandidateCollection(
        "fixture-sequences",
        "protein.sequence",
        [
            Candidate(
                "fixture-sequence",
                ProteinSequence("AG", ["A:1", "A:2"]),
                [],
                {"source": "independent-literal"},
            )
        ],
    )
    replay_catalog = build_frozen_catalog(
        (
            FOLDING_PACKAGE,
            SOURCE_PACKAGE,
            STRUCTURE_PREDICTION_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        )
    )

    class SourceReplay(ResultReplaySource):
        def __init__(self) -> None:
            self.node_ids: list[str] = []

        def lookup(self, **kwargs: Any) -> ResultReplayHit | None:
            node_id = kwargs["node"].node_id
            self.node_ids.append(node_id)
            if node_id == "materialize-confidence":
                return None
            assert node_id == "source"
            outputs = {"sequence_candidates": cached_source}
            return ResultReplayHit(
                result_identity=kwargs["result_identity"],
                producer_run_id="cached-source-run",
                admitted_outputs=admitted_replay_outputs(
                    catalog=replay_catalog,
                    node=kwargs["node"],
                    outputs=outputs,
                ),
            )

    client = Client()
    replay = SourceReplay()
    first_catalog, first_projection, _ = _run_simplefold(
        tmp_path,
        monkeypatch,
        client=client,
        num_samples=1,
        result_replay_source=replay,
    )

    def candidate_id(catalog: Any, projection: dict[str, Any]) -> str:
        output = next(
            item
            for item in projection["outputs"]
            if item["node_id"] == "fold"
            and item["output_port"] == "structure_candidates"
        )
        return _decode_output(catalog, output).items[0].candidate_id

    assert first_projection["status"] == "succeeded"
    assert candidate_id(first_catalog, first_projection)
    dispositions = {
        item["node_id"]: item
        for item in first_projection["node_dispositions"]
    }
    assert dispositions["source"]["resolution"] == "cache_replayed"
    assert dispositions["fold"]["resolution"] == "executed"
    assert len(client.staging) == 1
    assert all(not path.exists() for path in client.staging)
    assert replay.node_ids == ["source", "materialize-confidence"]


def test_concurrent_runs_use_disjoint_live_staging_and_stable_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    barrier = threading.Barrier(2)

    class Client:
        def __init__(self) -> None:
            self.staging: list[Path] = []
            self.lock = threading.Lock()

        def fold(
            self,
            **kwargs: Any,
        ) -> tuple[list[ProteinStructure], list[dict[str, Any]]]:
            staging = kwargs["staging_directory"]
            owned = staging / "fixed-provider-name"
            assert not owned.exists()
            owned.write_text("owned")
            with self.lock:
                self.staging.append(staging)
            barrier.wait(timeout=5)
            assert owned.read_text() == "owned"
            return (
                [ProteinStructure(_two_residue_pdb())],
                [{"per_residue": [71.0, 83.0], "sample_index": 0}],
            )

    client = Client()
    environment_values = _simplefold_environment(
        tmp_path,
        monkeypatch,
        client,
    )
    for root_name in ("projects", "cache", "outputs", "runs"):
        (tmp_path / root_name).mkdir(exist_ok=True)

    def run(project_id: str) -> tuple[Any, dict[str, Any], Any]:
        return _run_simplefold(
            tmp_path,
            monkeypatch,
            client=client,
            num_samples=1,
            environment_values=environment_values,
            project_id=project_id,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(run, "simplefold-concurrent-a")
        second_future = executor.submit(run, "simplefold-concurrent-b")
        first_catalog, first_projection, _ = first_future.result(timeout=20)
        second_catalog, second_projection, _ = second_future.result(timeout=20)

    def candidate_id(catalog: Any, projection: dict[str, Any]) -> str:
        output = next(
            item
            for item in projection["outputs"]
            if item["node_id"] == "fold"
            and item["output_port"] == "structure_candidates"
        )
        return _decode_output(catalog, output).items[0].candidate_id

    assert first_projection["status"] == second_projection["status"] == "succeeded"
    assert candidate_id(first_catalog, first_projection) == candidate_id(
        second_catalog,
        second_projection,
    )
    assert len(client.staging) == 2
    assert client.staging[0] != client.staging[1]
    assert all(not path.exists() for path in client.staging)


@pytest.mark.parametrize(
    ("provider_fails", "expected_exception_type"),
    ((False, "OSError"), (True, "RuntimeError")),
)
def test_simplefold_cleanup_failure_is_visible_without_masking_provider_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_fails: bool,
    expected_exception_type: str,
) -> None:
    import core.run_context as run_context

    original_rmtree = run_context.shutil.rmtree

    def fail_invocation_cleanup(
        path: Any,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        if isinstance(path, str) and path.startswith("simplefold-fold-"):
            raise OSError("fixture cleanup failure")
        original_rmtree(path, *args, **kwargs)

    fail_invocation_cleanup.avoids_symlink_attacks = (  # type: ignore[attr-defined]
        original_rmtree.avoids_symlink_attacks
    )
    monkeypatch.setattr(run_context.shutil, "rmtree", fail_invocation_cleanup)

    class Client:
        def fold(self, **kwargs: Any) -> tuple[list[ProteinStructure], list[dict[str, Any]]]:
            del kwargs
            if provider_fails:
                raise RuntimeError("fixture provider failure")
            return (
                [ProteinStructure(_two_residue_pdb())],
                [{"per_residue": [71.0, 83.0], "sample_index": 0}],
            )

    _, projection, events = _run_simplefold(
        tmp_path,
        monkeypatch,
        client=Client(),
        num_samples=1,
    )

    assert projection["status"] == "failed"
    terminals = [
        event["event"]
        for event in events
        if event["event"]["type"] == "node_attempt_terminal"
        and event["event"]["status"] == "failed"
    ]
    assert [
        item["error"]["details"]["exception_type"] for item in terminals
    ] == [expected_exception_type]
    terminal = terminals[0]
    assert terminal["resolution"] == "executed"
    assert all(
        output["node_id"] != "fold"
        for output in projection["outputs"]
    )
