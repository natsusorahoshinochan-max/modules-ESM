"""Public v2 contracts for the shared ESMFold2 folding Node Type."""

from __future__ import annotations

import math
from pathlib import Path
import hashlib
import json
from typing import Any

import pytest

from core import (
    EnvironmentConfiguration,
    ModulePackageContractCase,
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
    parse_workflow_document,
    verify_module_package_contract,
)
from core.port_types import canonical_json_bytes
from core.workflow_v2 import WorkflowEdge
from datatypes import (
    ProteinSequence,
    ProteinStructure,
)


def _two_residue_pdb() -> str:
    return "\n".join(
        (
            "ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00 70.00           N",
            "ATOM      2  CA  ALA A   1       1.000   0.000   0.000  1.00 70.00           C",
            "ATOM      3  C   ALA A   1       2.000   0.000   0.000  1.00 70.00           C",
            "ATOM      4  N   GLY A   2       3.000   0.000   0.000  1.00 80.00           N",
            "ATOM      5  CA  GLY A   2       4.000   0.000   0.000  1.00 80.00           C",
            "ATOM      6  C   GLY A   2       5.000   0.000   0.000  1.00 80.00           C",
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


def _run_fold(
    tmp_path: Path,
    *,
    route: str,
    client: Any,
    environment_overrides: dict[str, Any] | None = None,
    result_replay_source: ResultReplaySource | None = None,
    source_sequence: str = "AG",
    safe_environment_fingerprint: str | None = None,
) -> tuple[Any, dict[str, Any], tuple[dict[str, Any], ...]]:
    from modules.folding.package import MODULE_PACKAGE as FOLDING_PACKAGE
    from tests.fixtures.folding_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    source = WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.folding_sequence_source",
        node_type_version="2.1.0",
        binding_id="contract_test.folding_sequence_source.direct",
        binding_version="2.1.0",
        node_parameters={"sequence": source_sequence},
        binding_parameters={},
    )
    fold = WorkflowNodeInstance(
        node_id="fold",
        node_type_id="folding.fold",
        node_type_version="2.1.0",
        binding_id=f"folding.fold.esmfold2_{route}",
        binding_version="2.1.0",
        node_parameters={"effective_seed": 1603, "num_samples": 1},
        binding_parameters={},
    )
    catalog = build_frozen_catalog((FOLDING_PACKAGE, SOURCE_PACKAGE))
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
        "provider_client": client,
        "private_token": "must-never-publish",
    }
    if route == "remote":
        environment_values.update(
            {
                "endpoint_id": "biohub",
                "credential_handle": object(),
            }
        )
    environment_values.update(environment_overrides or {})
    environment = EnvironmentConfiguration(
        {
            (f"folding.fold.esmfold2_{route}", "2.1.0"): {
                "values": environment_values,
                "safe_fingerprint": (
                    safe_environment_fingerprint
                    or f"{route}-fixture-v1"
                ),
                "invalidation_token": (
                    safe_environment_fingerprint
                    or f"{route}-fixture-v1"
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
            client_request_id=f"fold-{route}",
        )
        service.shutdown()
        projection = service.projection(project.id, receipt["run_id"])
        events = service.public_events(project.id, receipt["run_id"])
    finally:
        service.shutdown()
    return catalog, projection, events


def test_remote_and_local_esmfold2_are_explicit_bindings_of_one_node() -> None:
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
    remote = catalog.require_contract(
        "binding",
        "folding.fold.esmfold2_remote",
        "2.1.0",
    )
    local = catalog.require_contract(
        "binding",
        "folding.fold.esmfold2_local",
        "2.1.0",
    )
    assert remote.descriptor["node_type"] == local.descriptor["node_type"]
    assert remote.descriptor["produced_observations"] == (
        local.descriptor["produced_observations"]
    )
    assert remote.descriptor["binding_parameters"] == {}
    assert local.descriptor["binding_parameters"] == {}
    assert remote.descriptor["execution_route"] == "adapter"
    assert local.descriptor["execution_route"] == "adapter"
    assert remote.descriptor["deterministic"] is False
    assert local.descriptor["deterministic"] is False
    assert remote.descriptor["cacheable"] is False
    assert local.descriptor["cacheable"] is False
    assert remote.descriptor["implementation_identity"]["model"] == (
        "esmfold2-fast-2026-05"
    )
    assert local.descriptor["implementation_identity"]["model"] == (
        "biohub/ESMFold2"
    )

    node = catalog.require_contract(
        "node_type",
        "folding.fold",
        "2.1.0",
    )
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
        "runtime_directory",
    }
    assert forbidden.isdisjoint(node.descriptor["node_parameters"])


def test_missing_local_esmfold2_stays_fail_closed_without_hiding_remote() -> None:
    from modules.folding.adapter import local_readiness

    catalog = build_discovered_frozen_catalog()
    availability = {
        snapshot["binding"]["contract_id"]: snapshot
        for snapshot in catalog.availability
    }
    assert {
        "folding.fold.esmfold2_remote",
        "folding.fold.esmfold2_local",
    }.issubset(availability)
    assert catalog.require_contract(
        "binding",
        "folding.fold.esmfold2_remote",
        "2.1.0",
    )
    assert catalog.require_contract(
        "binding",
        "folding.fold.esmfold2_local",
        "2.1.0",
    )
    assert availability["folding.fold.esmfold2_remote"] is not (
        availability["folding.fold.esmfold2_local"]
    )
    assert not local_readiness({}).passing


def _write_local_runtime_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    import modules.folding.adapter as adapter

    fold_snapshot = tmp_path / "esmfold2"
    language_snapshot = tmp_path / "esmc"
    runtime_directory = tmp_path / "runtime"
    fold_snapshot.mkdir()
    language_snapshot.mkdir()
    runtime_directory.mkdir()
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
    monkeypatch.setattr(
        adapter,
        "local_runtime_structurally_available",
        lambda: True,
    )
    fingerprint = adapter.configured_local_runtime_fingerprint()
    return {
        "model_snapshot_path": fold_snapshot,
        "model_snapshot_revision": adapter.LOCAL_ESMFOLD2_REVISION,
        "language_model_snapshot_path": language_snapshot,
        "language_model_snapshot_revision": adapter.LOCAL_ESMC_REVISION,
        "device": "cpu",
        "runtime_directory": runtime_directory,
        "resolved_runtime_fingerprint": fingerprint,
        "provider_client": object(),
        "private_model_token": "must-not-publish",
    }


def test_local_readiness_validates_both_exact_snapshots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.folding.adapter as adapter

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


def test_native_plddt_is_statically_scaled_and_masks_invalid_tokens() -> None:
    from modules.folding.adapter import normalize_native_confidence

    confidence = normalize_native_confidence(
        native_plddt=(0.70, 0.80, 0.40, math.nan, 0.90, 0.50),
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

    assert confidence.per_residue_plddt == (70.0, 80.0, None)
    assert confidence.mean_residue_plddt == 75.0
    assert confidence.ptm == 0.625
    assert confidence.pae == (
        (0.0, 1.0, 3.0),
        (1.0, 0.0, 7.0),
        (3.0, 7.0, 0.0),
    )


def test_local_builder_rejects_foreign_preinitialized_ccd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.folding.adapter as adapter

    class ForeignConformers:
        _CCD_MOLECULES = {"foreign": object()}

    class Builder:
        def __init__(self, **kwargs: object) -> None:
            raise AssertionError(f"builder must not run: {kwargs}")

    runtime = adapter.LocalESMFold2Runtime(
        model_snapshot_path=tmp_path / "model",
        language_model_snapshot_path=tmp_path / "language-model",
        runtime_directory=tmp_path / "runtime",
        device="cpu",
        safe_fingerprint="sha256:" + "0" * 64,
    )
    monkeypatch.setattr(adapter, "_LOCAL_CCD_DIGEST", None)
    monkeypatch.setattr(adapter, "_LOCAL_CCD_OBJECT", None)

    with pytest.raises(RuntimeError, match="outside this adapter"):
        adapter._initialize_local_ccd(
            ForeignConformers,
            Builder,
            runtime,
        )


def test_local_builder_rejects_ccd_replaced_after_adapter_initialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.folding.adapter as adapter

    owned = {"owned": object()}

    class Conformers:
        _CCD_MOLECULES = owned

    class Builder:
        def __init__(self, **kwargs: object) -> None:
            del kwargs

    runtime = adapter.LocalESMFold2Runtime(
        model_snapshot_path=tmp_path / "model",
        language_model_snapshot_path=tmp_path / "language-model",
        runtime_directory=tmp_path / "runtime",
        device="cpu",
        safe_fingerprint="sha256:" + "0" * 64,
    )
    monkeypatch.setattr(
        adapter,
        "_LOCAL_CCD_DIGEST",
        adapter.LOCAL_ESMFOLD2_ARTIFACT_SHA256["ccd.pkl"],
    )
    monkeypatch.setattr(adapter, "_LOCAL_CCD_OBJECT", owned)
    Conformers._CCD_MOLECULES = {"replaced": object()}

    with pytest.raises(RuntimeError, match="global identity changed"):
        adapter._initialize_local_ccd(Conformers, Builder, runtime)


def test_remote_and_local_provider_native_results_normalize_identically() -> None:
    import torch

    from modules.folding.adapter import (
        decode_local_fold_result,
        decode_remote_fold_result,
    )

    class RemoteResult(_RemoteResultRenderer):
        sequence = "AG"
        plddt = (0.70, 0.80)
        ptm = torch.tensor([0.625])
        pae = ((0.0, 1.0), (1.0, 0.0))

    class LocalComplex(_LocalComplexRenderer):
        sequence = ("ALA", "GLY", "LIG", "PAD")

    class LocalResult:
        complex = LocalComplex()
        plddt = (0.70, 0.80, 0.40, math.nan)
        ptm = torch.tensor(0.625)
        pae = (
            (0.0, 1.0, 2.0, 3.0),
            (1.0, 0.0, 4.0, 5.0),
            (2.0, 4.0, 0.0, 6.0),
            (3.0, 5.0, 6.0, 0.0),
        )

    sequence = ProteinSequence("AG", ["A:1", "A:2"])
    remote = decode_remote_fold_result(RemoteResult(), sequence)
    local = decode_local_fold_result(LocalResult(), sequence)

    assert remote.structure.pdb_string == local.structure.pdb_string
    assert remote.confidence == local.confidence
    assert remote.confidence.per_residue_plddt == (70.0, 80.0)
    assert remote.confidence.mean_residue_plddt == 75.0
    assert remote.confidence.ptm == 0.625
    assert remote.confidence.pae == ((0.0, 1.0), (1.0, 0.0))


@pytest.mark.parametrize("route", ("remote", "local"))
def test_selected_binding_folds_without_fallback_and_publishes_exact_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    route: str,
) -> None:
    class RemoteResult(_RemoteResultRenderer):
        sequence = "AG"
        plddt = (0.70, 0.80)
        ptm = 0.625
        pae = ((0.0, 31.75), (31.75, 0.0))

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
        plddt = (0.70, 0.80)
        ptm = 0.625
        pae = ((0.0, 31.75), (31.75, 0.0))

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
        environment["provider_client"] = client

    catalog, projection, events = _run_fold(
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
    parents = _decode_output(catalog, source_output)
    structures = _decode_output(catalog, outputs["structure_candidates"])
    confidence = _decode_output(
        catalog,
        outputs["confidence_observations"],
    )
    pae = _decode_output(catalog, outputs["pae_observations"])
    assert len(structures.items) == 1
    assert structures.items[0].parent_ids == [
        parents.items[0].candidate_id
    ]
    assert structures.items[0].metadata["route"] == route
    assert structures.items[0].metadata["sample_index"] == 0
    assert structures.items[0].data.pdb_string == _two_residue_pdb()
    values = {
        observation.metric.contract_id: observation.value
        for observation in confidence.entries
    }
    assert values == {
        "structure.ptm": 0.625,
        "structure.plddt.per_residue": [70.0, 80.0],
        "structure.plddt.mean_residue": 75.0,
    }
    assert len(pae.entries) == 1
    assert pae.entries[0].metric.contract_id == "structure.pae"
    assert pae.entries[0].value == [
        [0.0, 31.75],
        [31.75, 0.0],
    ]
    assert {
        observation.candidate_id
        for observation in (*confidence.entries, *pae.entries)
    } == {structures.items[0].candidate_id}
    readiness_index = next(
        index
        for index, event in enumerate(events)
        if event["event"]["type"] == "readiness_attested"
        and event["event"]["binding"]["contract_id"]
        == f"folding.fold.esmfold2_{route}"
    )
    invocation_index = next(
        index
        for index, event in enumerate(events)
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_identity"].startswith(
            f"folding.esmfold2_{route}."
        )
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
def test_readiness_rejects_before_cache_lookup_or_fold_call(
    tmp_path: Path,
) -> None:
    class LookupRecorder(ResultReplaySource):
        def __init__(self) -> None:
            self.lookups = 0

        def lookup(self, **kwargs: Any) -> None:
            del kwargs
            self.lookups += 1
            return None

    class BombClient:
        def __init__(self) -> None:
            self.calls = 0

        def fold(self, **kwargs: Any) -> object:
            del kwargs
            self.calls += 1
            raise AssertionError("provider call must not happen")

    cache = LookupRecorder()
    client = BombClient()
    with pytest.raises(V2RunError, match="not ready"):
        _run_fold(
            tmp_path,
            route="remote",
            client=client,
            environment_overrides={"credential_handle": None},
            result_replay_source=cache,
        )
    assert cache.lookups == 0
    assert client.calls == 0


def test_decode_failure_cannot_publish_a_successful_candidate(
    tmp_path: Path,
) -> None:
    class InvalidResult:
        sequence = "AG"
        plddt = (70.0, 80.0)
        ptm = 0.625
        pae = ((0.0, 1.0), (1.0, 0.0))
        pdb_string = _two_residue_pdb()

    class Client:
        def __init__(self) -> None:
            self.calls = 0

        def fold(self, **kwargs: Any) -> InvalidResult:
            del kwargs
            self.calls += 1
            return InvalidResult()

    client = Client()
    _, projection, events = _run_fold(
        tmp_path,
        route="remote",
        client=client,
    )

    assert projection["status"] == "failed"
    assert client.calls == 1
    assert all(
        output["node_id"] != "fold"
        for output in projection["outputs"]
    )
    invocations = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_terminal"
        and any(
            started["event"]["type"] == "engine_invocation_started"
            and started["event"]["invocation_id"]
            == event["event"]["invocation_id"]
            and started["event"]["engine_identity"].startswith(
                "folding.esmfold2_remote."
            )
            for started in events
        )
    ]
    assert len(invocations) == 1
    assert invocations[0]["status"] == "failed"


def test_remote_and_local_bindings_pass_shared_contract_test_kit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.folding.package import MODULE_PACKAGE as FOLDING_PACKAGE
    from tests.fixtures.folding_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    class RemoteResult(_RemoteResultRenderer):
        sequence = "AG"
        plddt = (0.70, 0.80)
        ptm = 0.625
        pae = ((0.0, 1.0), (1.0, 0.0))

    class RemoteClient:
        def fold(self, **kwargs: Any) -> RemoteResult:
            del kwargs
            return RemoteResult()

    class LocalComplex(_LocalComplexRenderer):
        sequence = ("ALA", "GLY")

    class LocalResult:
        complex = LocalComplex()
        plddt = (0.70, 0.80)
        ptm = 0.625
        pae = ((0.0, 1.0), (1.0, 0.0))

    class LocalClient:
        def fold(self, **kwargs: Any) -> LocalResult:
            del kwargs
            return LocalResult()

    source_node = WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.folding_sequence_source",
        node_type_version="2.1.0",
        binding_id="contract_test.folding_sequence_source.direct",
        binding_version="2.1.0",
        node_parameters={"sequence": "AG"},
        binding_parameters={},
    )
    local_environment = _write_local_runtime_fixture(
        tmp_path,
        monkeypatch,
    )
    local_environment["provider_client"] = LocalClient()
    import modules.folding.simplefold_adapter as simplefold_adapter

    simplefold_model_root = tmp_path / "simplefold-models"
    simplefold_esm2_models = tmp_path / "simplefold-esm2-models"
    simplefold_esm2_source = tmp_path / "simplefold-esm2-source"
    simplefold_model_root.mkdir()
    simplefold_esm2_models.mkdir()
    simplefold_esm2_source.mkdir()
    simplefold_payloads = {
        name: f"fixture-{name}".encode()
        for name in simplefold_adapter.SIMPLEFOLD_FOLDING_ARTIFACTS
    }
    simplefold_esm2_payloads = {
        "esm2_t36_3B_UR50D.pt": b"fixture-esm2",
        "esm2_t36_3B_UR50D-contact-regression.pt": b"fixture-contact",
    }
    for name, payload in simplefold_payloads.items():
        (simplefold_model_root / name).write_bytes(payload)
    for name, payload in simplefold_esm2_payloads.items():
        (simplefold_esm2_models / name).write_bytes(payload)
    monkeypatch.setattr(
        simplefold_adapter,
        "SIMPLEFOLD_ARTIFACT_SHA256",
        {
            name: hashlib.sha256(payload).hexdigest()
            for name, payload in simplefold_payloads.items()
        },
    )
    monkeypatch.setattr(
        simplefold_adapter,
        "SIMPLEFOLD_ARTIFACT_IDENTITIES",
        {
            name: {"bytes": len(payload)}
            for name, payload in simplefold_payloads.items()
        },
    )
    monkeypatch.setattr(
        simplefold_adapter,
        "SIMPLEFOLD_ESM2_ARTIFACT_SHA256",
        {
            name: hashlib.sha256(payload).hexdigest()
            for name, payload in simplefold_esm2_payloads.items()
        },
    )
    monkeypatch.setattr(
        simplefold_adapter,
        "SIMPLEFOLD_ESM2_ARTIFACT_IDENTITIES",
        {
            name: {"bytes": len(payload)}
            for name, payload in simplefold_esm2_payloads.items()
        },
    )
    monkeypatch.setattr(
        simplefold_adapter,
        "validate_installed_provider_checkout",
        lambda *_args, **_kwargs: None,
    )
    import modules.folding.simplefold_runtime as simplefold_runtime

    monkeypatch.setattr(
        simplefold_runtime,
        "validated_simplefold_esm2_root",
        lambda root=None: root,
    )
    import modules.folding.simplefold_confidence_adapter as confidence_adapter

    monkeypatch.setattr(
        confidence_adapter,
        "SIMPLEFOLD_ARTIFACT_SHA256",
        {
            name: hashlib.sha256(simplefold_payloads[name]).hexdigest()
            for name in confidence_adapter.SIMPLEFOLD_CONFIDENCE_ARTIFACTS
        },
    )
    monkeypatch.setattr(
        confidence_adapter,
        "SIMPLEFOLD_ARTIFACT_IDENTITIES",
        {
            name: {"bytes": len(simplefold_payloads[name])}
            for name in confidence_adapter.SIMPLEFOLD_CONFIDENCE_ARTIFACTS
        },
    )
    monkeypatch.setattr(
        confidence_adapter,
        "SIMPLEFOLD_ESM2_ARTIFACT_SHA256",
        {
            name: hashlib.sha256(
                simplefold_esm2_payloads[name]
            ).hexdigest()
            for name in (
                confidence_adapter.SIMPLEFOLD_CONFIDENCE_ESM2_ARTIFACTS
            )
        },
    )
    monkeypatch.setattr(
        confidence_adapter,
        "SIMPLEFOLD_ESM2_ARTIFACT_IDENTITIES",
        {
            name: {"bytes": len(simplefold_esm2_payloads[name])}
            for name in (
                confidence_adapter.SIMPLEFOLD_CONFIDENCE_ESM2_ARTIFACTS
            )
        },
    )
    monkeypatch.setattr(
        confidence_adapter,
        "validate_installed_provider_checkout",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        confidence_adapter,
        "validated_simplefold_esm2_root",
        lambda root=None: root,
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
                    ProteinStructure(
                        _two_residue_pdb(),
                        source="simplefold",
                    )
                ],
                [{"per_residue": [70.0, 80.0], "sample_index": 0}],
            )

    class ConfidenceClient:
        def evaluate(self, **kwargs: Any) -> dict[str, Any]:
            assert kwargs["structure"].pdb_string == _two_residue_pdb()
            return {
                "native_plddt": [0.70, 0.80],
                "valid_protein_residues": [True, True],
            }

    simplefold_environment = {
        "model_root": simplefold_model_root,
        "esm2_model_root": simplefold_esm2_models,
        "esm2_source_root": simplefold_esm2_source,
        "device": simplefold_adapter.SIMPLEFOLD_DEVICE,
        "resolved_runtime_fingerprint": (
            simplefold_adapter.configured_runtime_fingerprint()
        ),
        "provider_client": SimpleFoldClient(),
        "private_token": "ctk-secret-must-not-publish",
    }
    confidence_environment = {
        "model_root": simplefold_model_root,
        "esm2_model_root": simplefold_esm2_models,
        "esm2_source_root": simplefold_esm2_source,
        "device": confidence_adapter.SIMPLEFOLD_CONFIDENCE_DEVICE,
        "resolved_runtime_fingerprint": (
            confidence_adapter.configured_runtime_fingerprint()
        ),
        "provider_client": ConfidenceClient(),
        "private_token": "ctk-secret-must-not-publish",
    }
    structure_source_node = WorkflowNodeInstance(
        node_id="structure-source",
        node_type_id="contract_test.folding_structure_source",
        node_type_version="2.1.0",
        binding_id="contract_test.folding_structure_source.direct",
        binding_version="2.1.0",
        node_parameters={"pdb_string": _two_residue_pdb()},
        binding_parameters={},
    )
    common = {
        "node_type_id": "folding.fold",
        "node_type_version": "2.1.0",
        "binding_version": "2.1.0",
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
        "expected_observation_counts": {
            "confidence_observations": 3,
            "pae_observations": 1,
        },
        "safe_environment_fingerprint": "folding-ctk-fixture-v1",
        "invalidation_token": "folding-ctk-fixture-v1",
        "forbidden_public_fragments": (
            "ctk-secret-must-not-publish",
        ),
    }
    cases = (
        ModulePackageContractCase(
            case_id="esmfold2-remote",
            binding_id="folding.fold.esmfold2_remote",
            binding_parameters={},
            environment_values={
                "endpoint_id": "biohub",
                "credential_handle": object(),
                "provider_client": RemoteClient(),
                "private_token": "ctk-secret-must-not-publish",
            },
            **common,
        ),
        ModulePackageContractCase(
            case_id="esmfold2-local",
            binding_id="folding.fold.esmfold2_local",
            binding_parameters={},
            environment_values={
                **local_environment,
                "private_token": "ctk-secret-must-not-publish",
            },
            **common,
        ),
        ModulePackageContractCase(
            case_id="simplefold-local",
            binding_id="folding.fold.simplefold_local",
            binding_parameters={"num_steps": 10},
            environment_values=simplefold_environment,
            expected_candidate_counts={
                "structure_candidates": 1,
            },
            expected_observation_counts={
                "confidence_observations": 2,
                "pae_observations": 0,
            },
            safe_environment_fingerprint=simplefold_environment[
                "resolved_runtime_fingerprint"
            ],
            invalidation_token=simplefold_environment[
                "resolved_runtime_fingerprint"
            ],
            **{
                key: value
                for key, value in common.items()
                if key
                not in {
                    "expected_candidate_counts",
                    "expected_observation_counts",
                    "safe_environment_fingerprint",
                    "invalidation_token",
                }
            },
        ),
        ModulePackageContractCase(
            case_id="simplefold-confidence-local",
            node_type_id="folding.simplefold_confidence",
            node_type_version="2.1.0",
            binding_id=(
                "folding.simplefold_confidence.simplefold_local"
            ),
            binding_version="2.1.0",
            node_parameters={},
            binding_parameters={},
            environment_values=confidence_environment,
            workflow_nodes=(structure_source_node,),
            workflow_edges=(
                WorkflowEdge(
                    "structure-source",
                    "structure_candidates",
                    "contract-test-node",
                    "structure_candidates",
                ),
            ),
            expected_observation_counts={
                "confidence_observations": 2,
            },
            safe_environment_fingerprint=confidence_environment[
                "resolved_runtime_fingerprint"
            ],
            invalidation_token=confidence_environment[
                "resolved_runtime_fingerprint"
            ],
            forbidden_public_fragments=(
                "ctk-secret-must-not-publish",
            ),
        ),
    )

    report = verify_module_package_contract(
        FOLDING_PACKAGE,
        execution_cases=cases,
        supporting_registrations=(SOURCE_PACKAGE,),
        work_root=tmp_path / "ctk",
    )

    assert [case.status for case in report.case_reports] == [
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
    ]


@pytest.mark.parametrize("native_value", (50.0, -0.01, 1.01))
def test_native_plddt_never_uses_observed_range_to_guess_scale(
    native_value: float,
) -> None:
    from modules.folding.adapter import normalize_native_confidence

    with pytest.raises(ValueError, match="native pLDDT"):
        normalize_native_confidence(
            native_plddt=(native_value,),
            valid_protein_residues=(True,),
            ptm=0.5,
            pae=((0.0,),),
        )
