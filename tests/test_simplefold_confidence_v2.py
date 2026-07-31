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
    parse_workflow_document,
)
from core.port_types import canonical_json_bytes
from core.workflow_v2 import WorkflowEdge
from datatypes import ScoreCollection


def _two_residue_pdb() -> str:
    return "\n".join(
        (
            "ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00 20.00           N",
            "ATOM      2  CA  ALA A   1       1.000   0.000   0.000  1.00 20.00           C",
            "ATOM      3  C   ALA A   1       2.000   0.000   0.000  1.00 20.00           C",
            "ATOM      4  N   GLY A   2       3.000   0.000   0.000  1.00 20.00           N",
            "ATOM      5  CA  GLY A   2       4.000   0.000   0.000  1.00 20.00           C",
            "ATOM      6  C   GLY A   2       5.000   0.000   0.000  1.00 20.00           C",
            "TER",
            "END",
            "",
        )
    )


def _two_chain_pdb() -> str:
    return "\n".join(
        (
            "ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00 20.00           N",
            "ATOM      2  CA  ALA A   1       1.000   0.000   0.000  1.00 20.00           C",
            "TER",
            "ATOM      3  N   GLY B   4       2.000   0.000   0.000  1.00 20.00           N",
            "ATOM      4  CA  GLY B   4       3.000   0.000   0.000  1.00 20.00           C",
            "END",
            "",
        )
    )


def _blank_and_named_chain_pdb() -> str:
    return "\n".join(
        (
            "ATOM      1  CA  ALA     1       0.000   0.000   0.000  1.00 20.00           C",
            "TER",
            "ATOM      2  CA  GLY A   1       1.000   0.000   0.000  1.00 20.00           C",
            "END",
            "",
        )
    )


def _two_blank_chain_pdb() -> str:
    return "\n".join(
        (
            "ATOM      1  CA  ALA     1       0.000   0.000   0.000  1.00 20.00           C",
            "TER",
            "ATOM      2  CA  GLY     1       1.000   0.000   0.000  1.00 20.00           C",
            "END",
            "",
        )
    )


def test_existing_structure_parser_preserves_chain_breaks() -> None:
    from modules.folding.simplefold_confidence_adapter import (
        _pdb_residues,
        _provider_chain_ids,
    )

    parsed = _pdb_residues(_two_chain_pdb())

    assert [
        (chain.chain_id, chain.sequence)
        for chain in parsed.chains
    ] == [("A", "A"), ("B", "G")]
    assert [
        residue.identity.chain_id
        for chain in parsed.chains
        for residue in chain.residues
    ] == ["A", "B"]
    blank_and_named = _pdb_residues(_blank_and_named_chain_pdb())
    assert _provider_chain_ids(blank_and_named.chains) == ("B", "A")
    blank_segments = _pdb_residues(_two_blank_chain_pdb())
    assert [chain.sequence for chain in blank_segments.chains] == ["A", "G"]
    assert _provider_chain_ids(blank_segments.chains) == ("A", "B")


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
) -> tuple[Any, dict[str, Any], tuple[dict[str, Any], ...]]:
    from modules.folding.package import MODULE_PACKAGE as FOLDING_PACKAGE
    from tests.fixtures.folding_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    source = WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.folding_structure_source",
        node_type_version="2.1.0",
        binding_id="contract_test.folding_structure_source.direct",
        binding_version="2.1.0",
        node_parameters={"pdb_string": _two_residue_pdb()},
        binding_parameters={},
    )
    confidence = WorkflowNodeInstance(
        node_id="confidence",
        node_type_id="folding.simplefold_confidence",
        node_type_version="2.1.0",
        binding_id="folding.simplefold_confidence.simplefold_local",
        binding_version="2.1.0",
        node_parameters={},
        binding_parameters={},
    )
    catalog = build_frozen_catalog((FOLDING_PACKAGE, SOURCE_PACKAGE))
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
        nodes=(source, confidence),
        edges=(
            WorkflowEdge(
                "source",
                "structure_candidates",
                "confidence",
                "structure_candidates",
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
    if environment_values is None:
        environment_values = _confidence_environment(
            tmp_path,
            monkeypatch,
            client=client,
        )
    fingerprint = environment_values["resolved_runtime_fingerprint"]
    environment = EnvironmentConfiguration({
        ("folding.simplefold_confidence.simplefold_local", "2.1.0"): {
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
            workflow_revision=relocked["workflow_revision"],
            compile_id=compiled.public_receipt()["compile_id"],
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
        "2.1.0",
    )
    node = catalog.require_contract(
        "node_type",
        "folding.simplefold_confidence",
        "2.1.0",
    )
    assert [item["name"] for item in node.descriptor["inputs"]] == [
        "structure_candidates"
    ]
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
        (
            item["output_port"],
            item["subject_grain"],
            item["guaranteed_multiplicity"],
            item["context_profile"]["kind"],
        )
        for item in binding.descriptor["produced_observations"]
    } == {
        ("confidence_observations", "candidate", "one", "intrinsic")
    }

    method_reference = binding.descriptor["method"]
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
    assert client.calls[0]["structure"].pdb_string == _two_residue_pdb()
    assert "fold" not in client.calls[0]
    started = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_identity"].startswith(
            "folding.simplefold_confidence."
        )
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
    from modules.folding.simplefold_confidence_adapter import (
        invocation_identity,
    )

    resolved_identity = client.calls[0]["resolved_provider_identity"]
    assert started[0]["engine_identity"] == invocation_identity(
        resolved_identity
    )
    changed_identity = {
        **resolved_identity,
        "artifact_sha256": {
            **resolved_identity["artifact_sha256"],
            "ccd.pkl": "0" * 64,
        },
    }
    assert invocation_identity(changed_identity) != started[0][
        "engine_identity"
    ]
    public = json.dumps({"projection": projection, "events": events})
    for forbidden in (
        "contact-regression",
        "boltz1_conf",
        "simplefold_100M",
        "simplefold_360M",
        "must-never-publish",
    ):
        assert forbidden not in public


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


@pytest.mark.parametrize("native_value", (77.0, -0.01, 1.01))
def test_confidence_direct_head_never_guesses_native_scale(
    native_value: float,
) -> None:
    from modules.folding.implementation import (
        SimpleFoldConfidenceImplementation,
    )

    with pytest.raises(ValueError, match="direct-head pLDDT"):
        SimpleFoldConfidenceImplementation.normalize_native_confidence(
            native_plddt=[native_value],
            valid_protein_residues=[True],
        )


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
