"""Public v2 contracts for the shared ESMFold2 folding Node Type."""

from __future__ import annotations

from tests.support.ledger import public_run_events, public_run_projection

from protein_workbench_public.bootstrap import module_registrations

from contextlib import ExitStack
from pathlib import Path
import hashlib
import json
from typing import Any, cast
from unittest.mock import patch

import pytest
import torch

from core.project.manager import ProjectManager
from core.catalog.builder import (
    build_frozen_catalog,
)
from core.catalog.declarations import ExecutionBindingDefinition
from core.catalog.canonical import canonical_sha256
from core.execution.node_attempt import result_identity_descriptor
from core.operation import (
    ReadinessResult,
)
from core.execution.environment import admit_environment_configuration
from core.execution.node_attempt import NodeAttemptFactory
from core.execution.runtime import (
    V2RunError,
    V2RunService,
)
from tests.support.result_store import result_store
from tests.support.contract_test_kit import (
    ModulePackageContractCase,
    verify_module_package_contract,
)
from core.workflow.authoring import WorkflowAuthoringService
from core.workflow.document import (
    WorkflowDocument,
    WorkflowNodeInstance,
)
from core.workflow.document import WorkflowEdge
from datatypes.candidate import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
)
from datatypes.sequence import ProteinSequence
from datatypes.structure import ProteinStructure
from tests.fixtures.scientific_operation import (
    admitted_port_fixture,
    operation_call,
    operation_context,
)
from tests.fixtures.public_v2 import decode_service_typed_output_value
from tests.fixtures.simplefold import (
    build_fixture_simplefold_closure,
    install_fixture_source_runtime_group,
)


_FOLD_NODE_VERSION = "8.0.0"
_REMOTE_FOLD_BINDING_VERSION = "9.0.0"
_LOCAL_FOLD_BINDING_VERSION = "10.0.0"
_SIMPLEFOLD_BINDING_VERSION = "10.0.0"


def _esmfold2_binding_version(route: str) -> str:
    return (
        _REMOTE_FOLD_BINDING_VERSION
        if route == "remote"
        else _LOCAL_FOLD_BINDING_VERSION
    )


def _two_residue_pdb() -> str:
    return "\n".join(
        (
            "ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00 70.00           N  ",
            "ATOM      2  CA  ALA A   1       1.000   0.000   0.000  1.00 70.00           C  ",
            "ATOM      3  C   ALA A   1       2.000   0.000   0.000  1.00 70.00           C  ",
            "ATOM      4  N   GLY A   2       3.000   0.000   0.000  1.00 80.00           N  ",
            "ATOM      5  CA  GLY A   2       4.000   0.000   0.000  1.00 80.00           C  ",
            "ATOM      6  C   GLY A   2       5.000   0.000   0.000  1.00 80.00           C  ",
            "TER",
            "END",
            "",
        )
    )


def _upstream_simplefold_serialized_pdb() -> str:
    return "\n".join(
        line.ljust(80) for line in (*_two_residue_pdb().splitlines(), "")
    )


def _trusted_serialized_pdb_with_independent_residue_names() -> str:
    return "\n".join(
        (
            "ATOM      1  N   GLY A   8       0.000   0.000   0.000  1.00 70.00           N  ",
            "ATOM      2  CA  GLY A   8       1.000   0.000   0.000  1.00 70.00           C  ",
            "ATOM      3  C   GLY A   8       2.000   0.000   0.000  1.00 70.00           C  ",
            "ATOM      4  N   ALA A  13       3.000   0.000   0.000  1.00 80.00           N  ",
            "ATOM      5  CA  ALA A  13       4.000   0.000   0.000  1.00 80.00           C  ",
            "ATOM      6  C   ALA A  13       5.000   0.000   0.000  1.00 80.00           C  ",
            "TER",
            "END",
            "",
        )
    )


class _RenderedProtein:
    def infer_oxygen(self) -> "_RenderedProtein":
        return self

    def to_pdb_string(self) -> str:
        return _two_residue_pdb()


class _RemoteResultRenderer:
    def to_protein_chain(self) -> _RenderedProtein:
        return _RenderedProtein()


class _LocalComplexRenderer:
    def to_protein_complex(self) -> _RenderedProtein:
        return _RenderedProtein()


def _decode_output(
    service: Any,
    catalog: Any,
    projection: dict[str, Any],
    output: dict[str, Any],
) -> Any:
    return decode_service_typed_output_value(
        service,
        catalog,
        projection,
        output,
    )


def _run_fold(
    tmp_path: Path,
    *,
    route: str,
    client: Any,
    environment_overrides: dict[str, Any] | None = None,
    source_sequence: str = "AG",
    num_samples: int = 1,
) -> tuple[Any, Any, dict[str, Any], tuple[dict[str, Any], ...]]:
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
        node_type_version="4.0.0",
        binding_id="contract_test.folding_sequence_source.direct",
        binding_version="4.0.0",
        node_parameters={"sequence": source_sequence},
        binding_parameters={},
    )
    fold = WorkflowNodeInstance(
        node_id="fold",
        node_type_id="folding.fold",
        node_type_version=_FOLD_NODE_VERSION,
        binding_id=f"folding.fold.esmfold2_{route}",
        binding_version=_esmfold2_binding_version(route),
        node_parameters={
            "effective_seed": 1603,
            "num_samples": num_samples,
        },
        binding_parameters={},
    )
    materialize = WorkflowNodeInstance(
        node_id="materialize-confidence",
        node_type_id="structure_prediction.materialize_confidence",
        node_type_version="2.0.0",
        binding_id="structure_prediction.materialize_confidence.direct",
        binding_version="2.0.0",
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
    project = projects.create(f"folding {route}")
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
        workflow=workflow,
    )
    environment_values = (
        {
            "endpoint_id": "biohub",
            "credential_handle": "must-never-publish",
        }
        if route == "remote"
        else {}
    )
    environment_values.update(environment_overrides or {})
    environment = admit_environment_configuration(
        catalog,
        {
            (
                f"folding.fold.esmfold2_{route}",
                _esmfold2_binding_version(route),
            ): {
                "values": environment_values,
            }
        }
    )
    service = V2RunService(
        projects,
        catalog,
        authoring,
        NodeAttemptFactory(
            projects,
            environment,
            result_store(projects),
        ),
        result_store(projects),
    )
    with ExitStack() as stack:
        if client is not None:
            target = (
                "modules.folding.esmfold2_remote.build_remote_engine"
                if route == "remote"
                else "modules.folding.esmfold2_local.load_local_engine"
            )
            stack.enter_context(patch(target, return_value=client))
        try:
            receipt = service.start_background(
                project.id,
                workflow_commit_id=committed.workflow_commit_id,
                client_request_id=f"fold-{route}",
            )
            service.shutdown()
            projection = public_run_projection(
                service,
                project.id,
                receipt["run_id"],
            )
            events = public_run_events(service, project.id, receipt["run_id"])
        finally:
            service.shutdown()
    return service, catalog, projection, events


def test_remote_and_local_esmfold2_are_explicit_bindings_of_one_node() -> None:
    registrations = {
        registration.package_id: registration
        for registration in module_registrations()
    }
    registration = registrations["folding"]
    assert registration.package_version == "10.0.0"
    assert {
        resource.resource for resource in registration.node_definitions
    } == {
        "definitions/fold.yaml",
        "definitions/simplefold_confidence.yaml",
    }

    catalog = build_frozen_catalog(module_registrations())
    remote = catalog.require_contract(
        "binding",
        "folding.fold.esmfold2_remote",
        _REMOTE_FOLD_BINDING_VERSION,
    )
    local = catalog.require_contract(
        "binding",
        "folding.fold.esmfold2_local",
        _LOCAL_FOLD_BINDING_VERSION,
    )
    remote_definition = cast(ExecutionBindingDefinition, remote.definition)
    local_definition = cast(ExecutionBindingDefinition, local.definition)
    assert remote.descriptor["node_type"] == local.descriptor["node_type"]
    assert remote.descriptor["produced_observations"] == ()
    assert local.descriptor["produced_observations"] == ()
    assert remote.descriptor["binding_parameters"] == {}
    assert local.descriptor["binding_parameters"] == {}
    assert remote.descriptor["execution_route"] == "adapter"
    assert local.descriptor["execution_route"] == "adapter"
    assert remote.descriptor["deterministic"] is False
    assert local.descriptor["deterministic"] is False
    assert remote.descriptor["cacheable"] is False
    assert local.descriptor["cacheable"] is False
    assert "effective_randomness_parameters" not in remote.descriptor
    assert remote_definition.effective_randomness_resolver is None
    assert tuple(local.descriptor["effective_randomness_parameters"]) == (
        "effective_seed",
    )
    assert local_definition.effective_randomness_resolver is not None
    assert remote.descriptor["implementation_identity"]["model"] == (
        "esmfold2-fast-2026-05"
    )
    assert local.descriptor["implementation_identity"]["model"] == (
        "biohub/ESMFold2"
    )
    assert local.descriptor["method"]["contract_version"] == "6.0.0"
    assert local.descriptor["implementation_identity"][
        "language_model_precision"
    ] == "fp32"
    assert local.descriptor["route_behavior"]["parameters"][
        "language_model_precision"
    ] == "fp32"
    assert local.descriptor["readiness_declaration"]["prerequisites"][
        "language_model_snapshot"
    ]["precision"] == "fp32"
    assert local.descriptor["route_behavior"]["parameters"][
        "provider_seed_domain"
    ] == "unsigned_32_bit"
    assert local.descriptor["implementation_identity"]["seed_control"] == (
        "python_numpy_mt19937_torch_shared"
    )
    local_method = catalog.require_contract(
        "method",
        "folding.fold.esmfold2_hf_1ebf0e3",
        "6.0.0",
    )
    assert local_method.descriptor["model_identity"][
        "language_model_precision"
    ] == "fp32"
    assert "protein-workbench-esmfold2-call/v3" in local_method.descriptor[
        "algorithm_identity"
    ]["randomness_contract"]

    node = catalog.require_contract(
        "node_type",
        "folding.fold",
        _FOLD_NODE_VERSION,
    )
    assert {
        output["name"]: (
            output["port_type"]["contract_id"],
            output["port_type"]["contract_version"],
        )
        for output in node.descriptor["outputs"]
    } == {
        "structure_candidates": ("candidate.collection", "4.0.0"),
        "confidence_facts": (
            "structure_prediction.confidence_facts",
            "2.0.0",
        ),
    }
    assert set(node.descriptor["node_parameters"]) == {
        "effective_seed",
        "num_samples",
    }
    forbidden = {
        "model",
        "model_name",
        "credential",
        "endpoint",
        "model_snapshot_path",
        "language_model_snapshot_path",
        "device",
    }
    assert forbidden.isdisjoint(node.descriptor["node_parameters"])


def test_remote_base_seed_is_ordinary_but_local_seed_is_declared_randomness(
    tmp_path: Path,
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

    catalog = build_frozen_catalog(
        (
            FOLDING_PACKAGE,
            SOURCE_PACKAGE,
            STRUCTURE_PREDICTION_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        )
    )
    projects = ProjectManager(tmp_path / "projects")
    authoring = WorkflowAuthoringService(projects, catalog)
    parents = CandidateCollection(
        "parents",
        "protein.sequence",
        (Candidate("parent", ProteinSequence("AG", ("A:1", "A:2"))),),
    )
    collection_type = catalog.require_port_type(
        "candidate.collection",
        "4.0.0",
    )
    admitted_parents = admitted_port_fixture(
        parents,
        port_type_id="candidate.collection",
        value_content_digests=(collection_type.content_digest(parents),),
    )

    def descriptor_for_binding(
        *,
        binding_id: str,
        binding_version: str,
        seed: int,
    ) -> dict[str, Any]:
        project = projects.create(f"{binding_id} seed {seed}")
        source = WorkflowNodeInstance(
            node_id="source",
            node_type_id="contract_test.folding_sequence_source",
            node_type_version="4.0.0",
            binding_id="contract_test.folding_sequence_source.direct",
            binding_version="4.0.0",
            node_parameters={"sequence": "AG"},
            binding_parameters={},
        )
        fold = WorkflowNodeInstance(
            node_id="fold",
            node_type_id="folding.fold",
            node_type_version=_FOLD_NODE_VERSION,
            binding_id=binding_id,
            binding_version=binding_version,
            node_parameters={
                "effective_seed": seed,
                "num_samples": 1,
            },
            binding_parameters={},
        )
        committed = authoring.commit(
            project.id,
            workflow=WorkflowDocument(
                schema_version="2.1.0",
                workflow_id=project.id,
                nodes=(source, fold),
                edges=(
                    WorkflowEdge(
                        "source",
                        "sequence_candidates",
                        "fold",
                        "sequence_candidates",
                    ),
                ),
                contract_lock=(),
            ),
        )
        compiled = authoring.require_verified_commit(
            project.id,
            workflow_commit_id=committed.workflow_commit_id,
        )
        plan_node = next(
            node
            for node in compiled.execution_plan.nodes
            if node.node_type.contract_id == "folding.fold"
        )
        return result_identity_descriptor(
            plan_node,
            {"sequence_candidates": admitted_parents},
        )

    first = descriptor_for_binding(
        binding_id="folding.fold.esmfold2_remote",
        binding_version=_REMOTE_FOLD_BINDING_VERSION,
        seed=1603,
    )
    second = descriptor_for_binding(
        binding_id="folding.fold.esmfold2_remote",
        binding_version=_REMOTE_FOLD_BINDING_VERSION,
        seed=1604,
    )
    local = descriptor_for_binding(
        binding_id="folding.fold.esmfold2_local",
        binding_version=_LOCAL_FOLD_BINDING_VERSION,
        seed=1603,
    )

    assert first["node_parameters"] == {
        "effective_seed": 1603,
        "num_samples": 1,
    }
    assert second["node_parameters"] == {
        "effective_seed": 1604,
        "num_samples": 1,
    }
    assert first["determinism"]["effective_randomness"] == {}
    assert second["determinism"]["effective_randomness"] == {}
    assert canonical_sha256(first) != canonical_sha256(second)
    assert local["node_parameters"] == {"num_samples": 1}
    assert local["determinism"]["effective_randomness"] == {
        "effective_seed": 1603,
    }


def test_local_and_remote_esmfold2_have_independent_availability() -> None:
    catalog = build_frozen_catalog(module_registrations())
    availability = {
        snapshot.binding.contract_id: snapshot
        for snapshot in catalog.availability
    }
    assert {
        "folding.fold.esmfold2_remote",
        "folding.fold.esmfold2_local",
    }.issubset(availability)
    assert catalog.require_contract(
        "binding",
        "folding.fold.esmfold2_remote",
        _REMOTE_FOLD_BINDING_VERSION,
    )
    assert catalog.require_contract(
        "binding",
        "folding.fold.esmfold2_local",
        _LOCAL_FOLD_BINDING_VERSION,
    )
    assert availability["folding.fold.esmfold2_remote"] is not (
        availability["folding.fold.esmfold2_local"]
    )


def _write_local_runtime_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    import modules.folding.esmfold2_local as adapter

    fold_snapshot = tmp_path / "esmfold2"
    language_snapshot = tmp_path / "esmc"
    fold_snapshot.mkdir()
    language_snapshot.mkdir()
    fold_payload = b"folding-model-fixture"
    language_payload = b"language-model-fixture"
    (fold_snapshot / "model.bin").write_bytes(fold_payload)
    (language_snapshot / "model.bin").write_bytes(language_payload)
    monkeypatch.setattr(
        adapter,
        "LOCAL_ESMFOLD2_ARTIFACT_SHA256",
        {"model.bin": hashlib.sha256(fold_payload).hexdigest()},
    )
    monkeypatch.setattr(
        adapter,
        "LOCAL_ESMC_ARTIFACT_SHA256",
        {"model.bin": hashlib.sha256(language_payload).hexdigest()},
    )
    return {
        "model_snapshot_path": fold_snapshot,
        "model_snapshot_revision": adapter.LOCAL_ESMFOLD2_REVISION,
        "language_model_snapshot_path": language_snapshot,
        "language_model_snapshot_revision": adapter.LOCAL_ESMC_REVISION,
        "device": "cpu",
    }


def test_local_readiness_validates_both_exact_snapshots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.folding.esmfold2_local as adapter

    environment = _write_local_runtime_fixture(tmp_path, monkeypatch)
    conclusion = adapter.local_readiness(environment)
    assert conclusion == ReadinessResult(
        True,
        proof_source="direct-observation",
    )

    (environment["model_snapshot_path"] / "model.bin").write_bytes(
        b"replacement"
    )
    rejected = adapter.local_readiness(environment)
    assert rejected == ReadinessResult(
        False,
        proof_source="direct-observation",
        reason_code="local_runtime_unavailable",
    )


def test_local_esmfold2_loads_esmc_at_exact_cpu_float32_precision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import esm.models.esmfold2 as esmfold2
    import modules.folding.esmfold2_local as adapter
    from transformers.models.esmfold2.configuration_esmfold2 import (
        ESMFold2Config,
    )
    from transformers.models.esmfold2.modeling_esmfold2 import ESMFold2Model

    calls: dict[str, Any] = {}

    class Configuration:
        esmc_id = "unset"

    class Model:
        def to(self, device: str) -> "Model":
            calls["device"] = device
            return self

        def eval(self) -> "Model":
            calls["eval"] = True
            return self

    def load_configuration(path: Path, **kwargs: Any) -> Configuration:
        calls["configuration"] = (path, kwargs)
        return Configuration()

    def load_model(path: Path, **kwargs: Any) -> Model:
        calls["model"] = (path, kwargs)
        return Model()

    monkeypatch.setattr(
        ESMFold2Config,
        "from_pretrained",
        staticmethod(load_configuration),
    )
    monkeypatch.setattr(
        ESMFold2Model,
        "from_pretrained",
        staticmethod(load_model),
    )
    monkeypatch.setattr(
        esmfold2,
        "ESMFold2InputBuilder",
        lambda *, ccd_cache: object(),
    )
    runtime = adapter.LocalESMFold2Runtime(
        model_snapshot_path=tmp_path / "esmfold2",
        language_model_snapshot_path=tmp_path / "esmc",
        device="cpu",
    )

    adapter.load_local_engine(runtime)

    assert calls["configuration"] == (
        runtime.model_snapshot_path,
        {"local_files_only": True},
    )
    model_path, model_kwargs = calls["model"]
    assert model_path == runtime.model_snapshot_path
    assert set(model_kwargs) == {
        "config",
        "local_files_only",
        "esmc_precision",
    }
    assert model_kwargs["local_files_only"] is True
    assert model_kwargs["esmc_precision"] == "fp32"
    assert model_kwargs["config"].esmc_id == str(
        runtime.language_model_snapshot_path
    )
    assert calls["device"] == "cpu"
    assert calls["eval"] is True


def test_native_plddt_is_statically_scaled_and_projects_protein_tokens() -> None:
    from modules.folding.domain import normalize_native_confidence

    confidence = normalize_native_confidence(
        native_plddt=(0.70, 0.80, 0.40, 0.60, 0.90, 0.50),
        valid_protein_residues=(True, True, False, True, False, False),
        ptm=0.625,
        pae=(
            (0.0, 1.0, 2.0, 3.0, 4.0, 5.0),
            (1.0, 0.0, 6.0, 7.0, 8.0, 9.0),
            (2.0, 6.0, 0.0, 1.0, 2.0, 3.0),
            (3.0, 7.0, 1.0, 0.0, 4.0, 5.0),
            (4.0, 8.0, 2.0, 4.0, 0.0, 6.0),
            (5.0, 9.0, 3.0, 5.0, 6.0, 0.0),
        ),
    )

    assert confidence.per_residue_plddt == (70.0, 80.0, 60.0)
    assert confidence.ptm == 0.625
    assert confidence.pae == (
        (0.0, 1.0, 3.0),
        (1.0, 0.0, 7.0),
        (3.0, 7.0, 0.0),
    )


def test_remote_provider_native_result_translates_to_canonical_confidence() -> None:
    import torch

    from modules.folding.esmfold2_remote import decode_remote_fold_result

    class RemoteResult(_RemoteResultRenderer):
        sequence = "AG"
        plddt = torch.tensor([0.70, 0.80])
        ptm = torch.tensor(0.625)
        pae = torch.tensor(((0.0, 1.0), (1.0, 0.0)))

    result = decode_remote_fold_result(
        RemoteResult(),
        ProteinSequence("AG", ["A:1", "A:2"]),
    )
    expected_plddt = tuple(
        float(value) * 100.0 for value in RemoteResult.plddt.tolist()
    )

    assert result.structure.pdb_string == _two_residue_pdb()
    assert result.confidence.per_residue_plddt == expected_plddt
    assert result.confidence.ptm == 0.625
    assert result.confidence.pae == ((0.0, 1.0), (1.0, 0.0))


def test_remote_provider_official_error_union_is_an_operational_failure() -> None:
    from esm.sdk.api import ESMProteinError
    from modules.folding.esmfold2_remote import decode_remote_fold_result

    with pytest.raises(
        RuntimeError,
        match="remote ESMFold2 provider returned an error",
    ):
        decode_remote_fold_result(
            ESMProteinError(error_code=503, error_msg="provider unavailable"),
            ProteinSequence("AG", ["A:1", "A:2"]),
        )


def test_folding_operation_failure_publishes_no_partial_samples(
    tmp_path: Path,
) -> None:
    from esm.sdk.api import ESMProteinError

    class RemoteResult(_RemoteResultRenderer):
        sequence = "AG"
        plddt = torch.tensor([0.70, 0.80])
        ptm = torch.tensor(0.625)
        pae = torch.tensor(((0.0, 1.0), (1.0, 0.0)))

    class Client:
        def __init__(self) -> None:
            self.calls = 0

        def fold(self, **_kwargs: Any) -> object:
            self.calls += 1
            if self.calls == 1:
                return RemoteResult()
            return ESMProteinError(
                error_code=503,
                error_msg="provider unavailable",
            )

    client = Client()
    _, _, projection, events = _run_fold(
        tmp_path,
        route="remote",
        client=client,
        num_samples=2,
    )

    assert client.calls == 2
    assert projection["status"] == "failed"
    assert all(
        output["node_id"] != "fold"
        or output["output_port"]
        not in {"structure_candidates", "confidence_facts"}
        for output in projection["outputs"]
    )
    assert all(
        event["event"]["type"] != "outputs_published"
        or event["event"]["node_id"] != "fold"
        for event in events
    )

    started = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_role"].startswith("fold_parent_")
    ]
    assert [event["engine_role"] for event in started] == [
        "fold_parent_0_sample_0",
        "fold_parent_0_sample_1",
    ]
    terminals_by_invocation = {
        event["event"]["invocation_id"]: event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_terminal"
    }
    assert [
        terminals_by_invocation[event["invocation_id"]]["status"]
        for event in started
    ] == ["succeeded", "succeeded"]

    operation_attempt_id = started[0]["operation_attempt_id"]
    operation_terminal = next(
        event["event"]
        for event in events
        if event["event"]["type"] == "operation_attempt_terminal"
        and event["event"]["operation_attempt_id"] == operation_attempt_id
    )
    assert operation_terminal["status"] == "failed"
    fold_attempt = next(
        event["event"]
        for event in events
        if event["event"]["type"] == "node_attempt_started"
        and event["event"]["node_id"] == "fold"
    )
    fold_terminal = next(
        event["event"]
        for event in events
        if event["event"]["type"] == "node_attempt_terminal"
        and event["event"]["node_attempt_id"]
        == fold_attempt["node_attempt_id"]
    )
    assert fold_terminal["status"] == "failed"
    assert fold_terminal["failure_origin"] == "operation"


def test_local_provider_native_result_translates_to_canonical_confidence() -> None:
    import torch

    from modules.folding.esmfold2_local import decode_local_fold_result

    class LocalComplex(_LocalComplexRenderer):
        sequence = ("ALA", "GLY")

    class LocalResult:
        complex = LocalComplex()
        plddt = torch.tensor([0.70, 0.80])
        ptm = 0.625
        pae = torch.tensor(((0.0, 1.0), (1.0, 0.0)))

    result = decode_local_fold_result(LocalResult())
    expected_plddt = tuple(
        float(value) * 100.0 for value in LocalResult.plddt.tolist()
    )

    assert result.structure.pdb_string == _two_residue_pdb()
    assert result.confidence.per_residue_plddt == expected_plddt
    assert result.confidence.ptm == 0.625
    assert result.confidence.pae == ((0.0, 1.0), (1.0, 0.0))


def test_provider_pdb_renderer_is_translated_to_the_canonical_end_record() -> None:
    from modules.folding.esmfold2_local import decode_local_fold_result

    class RenderedProtein:
        def infer_oxygen(self) -> "RenderedProtein":
            return self

        def to_pdb_string(self) -> str:
            return _two_residue_pdb().removesuffix("END\n")

    class LocalComplex:
        sequence = ("ALA", "GLY")

        def to_protein_complex(self) -> RenderedProtein:
            return RenderedProtein()

    class LocalResult:
        complex = LocalComplex()
        plddt = torch.tensor([0.70, 0.80])
        ptm = 0.625
        pae = torch.tensor(((0.0, 1.0), (1.0, 0.0)))

    result = decode_local_fold_result(LocalResult())

    assert result.structure.pdb_string == _two_residue_pdb()


def test_esmfold2_admits_official_pdb_serialization_without_rebuilding_sequence(
) -> None:
    from modules.folding.esmfold2_remote import decode_remote_fold_result

    class RenderedProtein:
        def infer_oxygen(self) -> "RenderedProtein":
            return self

        def to_pdb_string(self) -> str:
            return _trusted_serialized_pdb_with_independent_residue_names()

    class RemoteResult:
        sequence = "AG"
        plddt = torch.tensor([0.70, 0.80])
        ptm = torch.tensor(0.625)
        pae = torch.tensor(((0.0, 1.0), (1.0, 0.0)))

        def to_protein_chain(self) -> RenderedProtein:
            return RenderedProtein()

    result = decode_remote_fold_result(
        RemoteResult(),
        ProteinSequence("AG", ("Q:-2A", "Q:10")),
    )

    assert result.structure == ProteinStructure(
        _trusted_serialized_pdb_with_independent_residue_names()
    )


def test_all_folding_axes_validate_before_any_provider_invocation() -> None:
    from modules.folding.implementation import (
        ESMFold2FoldingImplementation,
        SimpleFoldFoldingImplementation,
    )
    from modules.folding.package import MODULE_PACKAGE as FOLDING_PACKAGE
    from modules.structure_prediction.package import (
        MODULE_PACKAGE as STRUCTURE_PREDICTION_PACKAGE,
    )
    from modules.structure_transform.package import (
        MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
    )

    class RecordingAdapter:
        def __init__(self) -> None:
            self.calls = 0

        def fold(self, **_kwargs: Any) -> Any:
            self.calls += 1
            raise AssertionError("provider ran before all axes were validated")

    catalog = build_frozen_catalog(
        (
            FOLDING_PACKAGE,
            STRUCTURE_PREDICTION_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        )
    )
    cases = (
        (
            "folding.fold.esmfold2_remote",
            _REMOTE_FOLD_BINDING_VERSION,
            {},
            ESMFold2FoldingImplementation,
        ),
        (
            "folding.fold.simplefold_local",
            _SIMPLEFOLD_BINDING_VERSION,
            {"num_steps": 10},
            SimpleFoldFoldingImplementation,
        ),
    )
    invalid_sequences = (
        ProteinSequence("AG", ["A:1", "B:1"]),
        ProteinSequence("AX", ["A:1", "A:2"]),
    )
    for invalid_sequence in invalid_sequences:
        parents = CandidateCollection(
            "parents",
            "protein.sequence",
            (
                Candidate(
                    "single",
                    ProteinSequence("AG", ["A:1", "A:2"]),
                ),
                Candidate("invalid", invalid_sequence),
            ),
        )
        for (
            binding_id,
            binding_version,
            binding_parameters,
            implementation_type,
        ) in cases:
            adapter = RecordingAdapter()
            context = operation_context(
                catalog,
                binding_id,
                object(),
                binding_version=binding_version,
            )
            operation = implementation_type(
                adapter=adapter,
                method=context.method,
            )
            with pytest.raises(ValueError, match="folding requires"):
                operation.execute(
                    operation_call(
                        catalog=catalog,
                        binding_id=binding_id,
                        binding_version=binding_version,
                        inputs={"sequence_candidates": parents},
                        node_parameters={
                            "num_samples": 1,
                            **(
                                {"effective_seed": 1603}
                                if binding_id.endswith("_remote")
                                else {}
                            ),
                        },
                        binding_parameters=binding_parameters,
                        effective_randomness=(
                            {}
                            if binding_id.endswith("_remote")
                            else {"effective_seed": 1603}
                        ),
                    )
                )
            assert adapter.calls == 0


def test_canonical_folding_operation_consumes_only_adapter_result_dto() -> None:
    from modules.folding.domain import (
        ESMFold2AdapterResult,
        NormalizedConfidence,
    )
    from modules.folding.implementation import (
        ESMFold2FoldingImplementation,
    )
    from modules.folding.package import MODULE_PACKAGE as FOLDING_PACKAGE
    from core.operation import OutputIdentityIntent
    from datatypes.prediction import PendingConfidenceFactCollection
    from modules.structure_prediction.package import (
        MODULE_PACKAGE as STRUCTURE_PREDICTION_PACKAGE,
    )
    from modules.structure_transform.package import (
        MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
    )

    class Adapter:
        def __init__(self) -> None:
            self.calls: list[tuple[ProteinSequence, int | None, str]] = []

        def fold(
            self,
            *,
            sequence: ProteinSequence,
            derived_call_seed: int | None,
            engine_role: str,
        ) -> ESMFold2AdapterResult:
            self.calls.append((sequence, derived_call_seed, engine_role))
            return ESMFold2AdapterResult(
                structure=ProteinStructure(
                    _two_residue_pdb(),
                ),
                confidence=NormalizedConfidence(
                    per_residue_plddt=(70.0, 80.0),
                    ptm=0.625,
                    pae=((0.0, 1.0), (1.0, 0.0)),
                ),
                effective_call_seed=None,
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
        "folding.fold.esmfold2_remote",
        object(),
        binding_version=_REMOTE_FOLD_BINDING_VERSION,
        environment={"raw_provider_value": object()},
    )
    adapter = Adapter()
    operation = ESMFold2FoldingImplementation(
        adapter=adapter,
        method=context.method,
    )
    parent = Candidate(
        "parent",
        ProteinSequence("AG", ["Q:-2A", "Q:10"]),
        [],
        {},
    )

    outputs = operation.execute(
        operation_call(
            catalog=catalog,
            binding_id="folding.fold.esmfold2_remote",
            binding_version=_REMOTE_FOLD_BINDING_VERSION,
            inputs={
                "sequence_candidates": CandidateCollection(
                    "parents",
                    "protein.sequence",
                    [parent],
                )
            },
            node_parameters={"effective_seed": 1603, "num_samples": 1},
            binding_parameters={},
        )
    )

    structures = outputs["structure_candidates"]
    assert type(structures) is CandidateCollection
    assert structures.items[0].data == ProteinStructure(_two_residue_pdb())
    assert {
        "provider",
        "model",
        "route",
        "runtime_fingerprint",
        "checkpoint",
        "seed_control",
    }.isdisjoint(structures.items[0].metadata)
    assert "effective_call_seed" not in structures.items[0].metadata
    assert adapter.calls[0][1] is None
    assert adapter.calls[0][0] == parent.data
    assert adapter.calls[0][2] == "fold_parent_0_sample_0"
    intent = outputs["confidence_facts"]
    assert type(intent) is OutputIdentityIntent
    facts = intent.relation
    assert type(facts) is PendingConfidenceFactCollection
    assert len(facts.entries) == 1
    fact = facts.entries[0]
    assert fact.prediction_axis.sequence == parent.data
    assert fact.prediction_axis.layout.residue_ids == (
        "Q:-2A",
        "Q:10",
    )
    assert fact.prediction_axis.source.candidate_id == parent.candidate_id
    assert facts.observation_method == context.method
    assert fact.plddt_per_residue == (70.0, 80.0)
    assert fact.ptm == 0.625
    assert fact.pae == ((0.0, 1.0), (1.0, 0.0))
    assert "prediction_key" not in structures.items[0].metadata
    assert set(outputs) == {"structure_candidates", "confidence_facts"}


def test_esmfold_call_seed_uses_candidate_content_not_candidate_identity() -> None:
    from modules.folding.domain import (
        ESMFold2AdapterResult,
        NormalizedConfidence,
    )
    from modules.folding.implementation import ESMFold2FoldingImplementation
    from modules.folding.package import MODULE_PACKAGE as FOLDING_PACKAGE
    from modules.structure_prediction.package import (
        MODULE_PACKAGE as STRUCTURE_PREDICTION_PACKAGE,
    )
    from modules.structure_transform.package import (
        MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
    )

    assert ESMFold2FoldingImplementation._call_seed(
        1603,
        "sha256:" + "0" * 64,
        0,
        0,
    ) == 299_330_669

    class Adapter:
        def __init__(self) -> None:
            self.seeds: list[int] = []

        def fold(self, **kwargs: Any) -> ESMFold2AdapterResult:
            seed = kwargs["derived_call_seed"]
            self.seeds.append(seed)
            return ESMFold2AdapterResult(
                structure=ProteinStructure(_two_residue_pdb()),
                confidence=NormalizedConfidence(
                    per_residue_plddt=(70.0, 80.0),
                    ptm=0.625,
                    pae=((0.0, 1.0), (1.0, 0.0)),
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
        "folding.fold.esmfold2_local",
        object(),
        binding_version="10.0.0",
    )

    def observed(candidate_id: str, sequence: str) -> int:
        adapter = Adapter()
        operation = ESMFold2FoldingImplementation(
            adapter=adapter,
            method=context.method,
        )
        parent = Candidate(
            candidate_id,
            ProteinSequence(sequence),
            [],
            {},
        )
        operation.execute(
            operation_call(
                catalog=catalog,
                binding_id="folding.fold.esmfold2_local",
                binding_version="10.0.0",
                inputs={
                    "sequence_candidates": CandidateCollection(
                        "parents",
                        "protein.sequence",
                        [parent],
                    )
                },
                node_parameters={"num_samples": 1},
                binding_parameters={},
                effective_randomness={"effective_seed": 1603},
            )
        )
        return adapter.seeds[0]

    original = observed("candidate-a", "AG")
    renamed = observed("candidate-renamed", "AG")
    changed_content = observed("candidate-a", "AA")

    assert 0 <= original <= 4_294_967_295
    assert original == renamed
    assert original != changed_content


@pytest.mark.parametrize("route", ("remote", "local"))
def test_selected_binding_folds_without_fallback_and_publishes_exact_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    route: str,
) -> None:
    native_plddt = torch.tensor([0.70, 0.80])

    class RemoteResult(_RemoteResultRenderer):
        sequence = "AG"
        plddt = native_plddt
        ptm = torch.tensor(0.625)
        pae = torch.tensor(((0.0, 31.75), (31.75, 0.0)))

    class RemoteClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, Any]] = []

        def fold(
            self,
            *,
            sequence: str,
            model_name: str,
            config: Any,
        ) -> RemoteResult:
            self.calls.append((sequence, model_name, config))
            return RemoteResult()

    class LocalComplex(_LocalComplexRenderer):
        sequence = ("ALA", "GLY")

    class LocalResult:
        complex = LocalComplex()
        plddt = native_plddt
        ptm = 0.625
        pae = torch.tensor(((0.0, 31.75), (31.75, 0.0)))

    class LocalClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, int]] = []

        def fold(
            self,
            *,
            sequence: str,
            effective_seed: int,
        ) -> LocalResult:
            self.calls.append((sequence, effective_seed))
            return LocalResult()

    environment: dict[str, Any] = {}
    if route == "remote":
        client: Any = RemoteClient()
    else:
        client = LocalClient()
        environment = _write_local_runtime_fixture(tmp_path, monkeypatch)

    service, catalog, projection, events = _run_fold(
        tmp_path,
        route=route,
        client=client,
        environment_overrides=environment,
    )

    assert projection["status"] == "succeeded", json.dumps(
        events,
        indent=2,
    )
    outputs = {
        output["output_port"]: output
        for output in projection["outputs"]
        if output["node_id"] == "fold"
    }
    source_output = next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "source"
        and output["output_port"] == "sequence_candidates"
    )
    parents = _decode_output(service, catalog, projection, source_output)
    structures = _decode_output(
        service, catalog, projection, outputs["structure_candidates"]
    )
    facts = _decode_output(
        service,
        catalog,
        projection,
        outputs["confidence_facts"],
    )
    observation_output = next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "materialize-confidence"
        and output["output_port"] == "observations"
    )
    observations = _decode_output(
        service,
        catalog,
        projection,
        observation_output,
    )
    assert len(structures.items) == 1
    assert structures.items[0].parent_ids == (
        parents.items[0].candidate_id,
    )
    metadata = structures.items[0].metadata
    assert {
        "provider",
        "model",
        "route",
        "runtime_fingerprint",
        "checkpoint",
        "seed_control",
    }.isdisjoint(metadata)
    assert "configured_base_seed" not in metadata
    if route == "remote":
        assert "effective_call_seed" not in metadata
    else:
        assert type(metadata["effective_call_seed"]) is int
    assert structures.items[0].metadata["sample_index"] == 0
    assert structures.items[0].data.pdb_string == _two_residue_pdb()
    assert len(facts.entries) == 1
    assert facts.entries[0].prediction_key == metadata["prediction_key"]
    assert facts.entries[0].prediction_axis.layout.residue_ids == (
        "A:1",
        "A:2",
    )
    values = {
        observation.metric.contract_id: observation.value
        for observation in observations.entries
    }
    expected_plddt = tuple(
        float(value) * 100.0 for value in native_plddt.tolist()
    )
    assert values == {
        "structure.ptm": 0.625,
        "structure.plddt.per_residue": expected_plddt,
        "structure.plddt.mean_residue": sum(expected_plddt) / 2,
        "structure.pae": (
            (0.0, 31.75),
            (31.75, 0.0),
        ),
    }
    assert {
        observation.candidate_id
        for observation in observations.entries
    } == {structures.items[0].candidate_id}
    axis_by_metric = {
        observation.metric.contract_id: observation.residue_axis
        for observation in observations.entries
    }
    assert axis_by_metric["structure.ptm"] is None
    assert all(
        axis_by_metric[metric] is not None
        and axis_by_metric[metric].axis_kind == "prediction_input"
        and axis_by_metric[metric].layout.residue_ids == ("A:1", "A:2")
        for metric in (
            "structure.plddt.per_residue",
            "structure.plddt.mean_residue",
            "structure.pae",
        )
    )
    readiness_index = next(
        index
        for index, event in enumerate(events)
        if event["event"]["type"] == "readiness_attested"
        and event["event"]["binding"]["contract_id"]
        == f"folding.fold.esmfold2_{route}"
    )
    binding = catalog.require_contract(
        "binding",
        f"folding.fold.esmfold2_{route}",
        _esmfold2_binding_version(route),
    )
    method = catalog.require_contract(
        "method",
        binding.descriptor["method"]["contract_id"],
        binding.descriptor["method"]["contract_version"],
    )
    started = next(
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_role"] == "fold_parent_0_sample_0"
    )
    invocation_index = next(
        index
        for index, event in enumerate(events)
        if event["event"] == started
    )
    assert started["engine_identity"] == method.contract_digest
    randomness = started["invocation_provenance"]["effective_randomness"]
    assert randomness == (
        {"control": "provider_uncontrolled"}
        if route == "remote"
        else {
            "control": "exact_seed",
            "effective_seed": metadata["effective_call_seed"],
        }
    )
    if route == "local":
        assert randomness["effective_seed"] == (
            metadata["effective_call_seed"]
        )
    assert readiness_index < invocation_index
    if route == "remote":
        assert len(client.calls) == 1
        sequence, model_name, config = client.calls[0]
        assert sequence == "AG"
        assert model_name == "esmfold2-fast-2026-05"
        assert config.include_pae is True
        assert config.include_embeddings is False
    else:
        assert len(client.calls) == 1
        assert client.calls[0][0] == "AG"
        assert isinstance(client.calls[0][1], int)


@pytest.mark.deterministic_acceptance
def test_readiness_rejects_before_fold_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.folding.esmfold2_remote as folding_adapter

    class BombClient:
        def __init__(self) -> None:
            self.calls = 0

        def fold(self, **kwargs: Any) -> object:
            del kwargs
            self.calls += 1
            raise AssertionError("provider call must not happen")

    client = BombClient()
    monkeypatch.setattr(
        folding_adapter,
        "_remote_provider_installation_is_exact",
        lambda: False,
    )
    _, _, projection, _ = _run_fold(
        tmp_path,
        route="remote",
        client=client,
    )
    assert projection["status"] == "failed"
    assert client.calls == 0


def test_remote_and_local_bindings_pass_shared_contract_test_kit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.folding.esmfold2_local as local_adapter
    import modules.folding.esmfold2_remote as remote_adapter
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

    class RemoteResult(_RemoteResultRenderer):
        sequence = "AG"
        plddt = torch.tensor([0.70, 0.80])
        ptm = torch.tensor(0.625)
        pae = torch.tensor(((0.0, 1.0), (1.0, 0.0)))

    class RemoteClient:
        def fold(self, **kwargs: Any) -> RemoteResult:
            del kwargs
            return RemoteResult()

    class LocalComplex(_LocalComplexRenderer):
        sequence = ("ALA", "GLY")

    class LocalResult:
        complex = LocalComplex()
        plddt = torch.tensor([0.70, 0.80])
        ptm = 0.625
        pae = torch.tensor(((0.0, 1.0), (1.0, 0.0)))

    class LocalClient:
        def fold(self, **kwargs: Any) -> LocalResult:
            del kwargs
            return LocalResult()

    source_node = WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.folding_sequence_source",
        node_type_version="4.0.0",
        binding_id="contract_test.folding_sequence_source.direct",
        binding_version="4.0.0",
        node_parameters={"sequence": "AG"},
        binding_parameters={},
    )
    local_environment = _write_local_runtime_fixture(
        tmp_path,
        monkeypatch,
    )
    import modules.folding.simplefold_asset_closure as asset_closure
    import modules.folding.simplefold_adapter as simplefold_adapter
    import modules.folding.simplefold_confidence_adapter as confidence_adapter
    import modules.folding.simplefold_contract as simplefold_contract
    import modules.folding.simplefold_runtime as simplefold_runtime

    simplefold_model_root = tmp_path / "simplefold-models"
    simplefold_esm2_models = tmp_path / "simplefold-esm2-models"
    simplefold_esm2_source = tmp_path / "simplefold-esm2-source"
    simplefold_model_root.mkdir()
    simplefold_esm2_models.mkdir()
    simplefold_esm2_source.mkdir()
    simplefold_payloads = {
        entry.runtime_filename: f"fixture-{entry.runtime_filename}".encode()
        for entry in (
            simplefold_contract.SIMPLEFOLD_FOLDING_ASSET_CLOSURE.files
        )
        if entry.environment_key == "model_root"
    }
    simplefold_esm2_payloads = {
        "esm2_t36_3B_UR50D.pt": b"fixture-esm2",
        "esm2_t36_3B_UR50D-contact-regression.pt": b"fixture-contact",
    }
    for name, payload in simplefold_payloads.items():
        (simplefold_model_root / name).write_bytes(payload)
    for name, payload in simplefold_esm2_payloads.items():
        (simplefold_esm2_models / name).write_bytes(payload)
    fixture_digests = {
        name: hashlib.sha256(payload).hexdigest()
        for name, payload in (
            *simplefold_payloads.items(),
            *simplefold_esm2_payloads.items(),
        )
    }

    monkeypatch.setattr(
        simplefold_contract,
        "SIMPLEFOLD_FOLDING_ASSET_CLOSURE",
        build_fixture_simplefold_closure(
            simplefold_contract.SIMPLEFOLD_FOLDING_ASSET_CLOSURE,
            fixture_digests,
        ),
    )
    monkeypatch.setattr(
        simplefold_contract,
        "SIMPLEFOLD_CONFIDENCE_ASSET_CLOSURE",
        build_fixture_simplefold_closure(
            simplefold_contract.SIMPLEFOLD_CONFIDENCE_ASSET_CLOSURE,
            fixture_digests,
        ),
    )
    monkeypatch.setattr(
        asset_closure,
        "validate_installed_provider_checkout",
        lambda *_args, **_kwargs: None,
    )

    class SimpleFoldClient:
        def fold(
            self,
            **kwargs: Any,
        ) -> tuple[list[ProteinStructure], list[dict[str, Any]]]:
            assert kwargs["num_steps"] == 10
            assert kwargs["num_samples"] == 1
            return (
                [
                    ProteinStructure(_upstream_simplefold_serialized_pdb())
                ],
                [{"per_residue": [70.0, 80.0], "sample_index": 0}],
            )

    class ConfidenceClient:
        def evaluate(self, **kwargs: Any) -> dict[str, Any]:
            residue_axis = kwargs["residue_axis"]
            assert residue_axis.layout.residue_ids == ("A:1", "A:2")
            assert residue_axis.sequence == "AG"
            return {
                "native_plddt": [0.70, 0.80],
                "valid_protein_residues": [True, True],
            }

    simplefold_client = SimpleFoldClient()
    confidence_client = ConfidenceClient()
    monkeypatch.setattr(
        remote_adapter,
        "build_remote_engine",
        lambda _environment: RemoteClient(),
    )
    monkeypatch.setattr(
        local_adapter,
        "load_local_engine",
        lambda _runtime: LocalClient(),
    )
    monkeypatch.setattr(
        simplefold_runtime,
        "fold_sequence",
        lambda **kwargs: simplefold_client.fold(**kwargs),
    )
    monkeypatch.setattr(
        confidence_adapter,
        "_native_existing_structure_confidence",
        lambda **kwargs: confidence_client.evaluate(
            residue_axis=kwargs["residue_axis"]
        ),
    )
    install_fixture_source_runtime_group(monkeypatch, simplefold_adapter)
    install_fixture_source_runtime_group(monkeypatch, confidence_adapter)

    simplefold_environment = {
        "model_root": simplefold_model_root,
        "esm2_model_root": simplefold_esm2_models,
        "esm2_source_root": simplefold_esm2_source,
        "device": simplefold_contract.SIMPLEFOLD_DEVICE,
    }
    confidence_environment = {
        "model_root": simplefold_model_root,
        "esm2_model_root": simplefold_esm2_models,
        "esm2_source_root": simplefold_esm2_source,
        "device": simplefold_contract.SIMPLEFOLD_CONFIDENCE_DEVICE,
    }
    structure_source_node = WorkflowNodeInstance(
        node_id="structure-source",
        node_type_id="contract_test.folding_structure_source",
        node_type_version="4.0.0",
        binding_id="contract_test.folding_structure_source.direct",
        binding_version="4.0.0",
        node_parameters={"pdb_string": _two_residue_pdb()},
        binding_parameters={},
    )
    structure_axis_node = WorkflowNodeInstance(
        node_id="structure-axis",
        node_type_id=(
            "structure_transform.resolve_candidate_residue_axes"
        ),
        node_type_version="6.0.0",
        binding_id=(
            "structure_transform."
            "resolve_candidate_residue_axes.direct"
        ),
        binding_version="6.0.0",
        node_parameters={},
        binding_parameters={},
    )
    common = {
        "node_type_id": "folding.fold",
        "node_type_version": _FOLD_NODE_VERSION,
        "node_parameters": {
            "effective_seed": 1603,
            "num_samples": 1,
        },
        "workflow_nodes": (source_node,),
        "workflow_edges": (
            WorkflowEdge(
                "source",
                "sequence_candidates",
                "contract-test-node",
                "sequence_candidates",
            ),
        ),
        "expected_candidate_counts": {
            "structure_candidates": 1,
        },
        "forbidden_public_fragments": (
            "ctk-secret-must-not-publish",
        ),
    }
    cases = (
        ModulePackageContractCase(
            case_id="esmfold2-remote",
            binding_id="folding.fold.esmfold2_remote",
            binding_version=_REMOTE_FOLD_BINDING_VERSION,
            binding_parameters={},
            environment_values={
                "endpoint_id": "biohub",
                "credential_handle": "ctk-secret-must-not-publish",
            },
            **common,
        ),
        ModulePackageContractCase(
            case_id="esmfold2-local",
            binding_id="folding.fold.esmfold2_local",
            binding_version=_LOCAL_FOLD_BINDING_VERSION,
            binding_parameters={},
            environment_values=local_environment,
            **common,
        ),
        ModulePackageContractCase(
            case_id="simplefold-local",
            binding_id="folding.fold.simplefold_local",
            binding_version=_SIMPLEFOLD_BINDING_VERSION,
            binding_parameters={"num_steps": 10},
            environment_values=simplefold_environment,
            expected_candidate_counts={
                "structure_candidates": 1,
            },
            **{
                key: value
                for key, value in common.items()
                if key
                not in {
                    "expected_candidate_counts",
                }
            },
        ),
        ModulePackageContractCase(
            case_id="simplefold-confidence-local",
            node_type_id="folding.simplefold_confidence",
            node_type_version="5.0.0",
            binding_id=(
                "folding.simplefold_confidence.simplefold_local"
            ),
            binding_version="6.0.0",
            node_parameters={},
            binding_parameters={},
            environment_values=confidence_environment,
            workflow_nodes=(structure_source_node, structure_axis_node),
            workflow_edges=(
                WorkflowEdge(
                    "structure-source",
                    "structure_candidates",
                    "contract-test-node",
                    "structure_candidates",
                ),
                WorkflowEdge(
                    "structure-source",
                    "structure_candidates",
                    "structure-axis",
                    "structure_candidates",
                ),
                WorkflowEdge(
                    "structure-axis",
                    "residue_axes",
                    "contract-test-node",
                    "structure_residue_axes",
                ),
            ),
            expected_observation_counts={
                "confidence_observations": 2,
            },
            forbidden_public_fragments=(
                "ctk-secret-must-not-publish",
            ),
        ),
    )

    report = verify_module_package_contract(
        FOLDING_PACKAGE,
        execution_cases=cases,
        supporting_registrations=(
            SOURCE_PACKAGE,
            STRUCTURE_PREDICTION_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        ),
        work_root=tmp_path / "ctk",
    )

    assert [case.status for case in report.case_reports] == [
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
    ]
