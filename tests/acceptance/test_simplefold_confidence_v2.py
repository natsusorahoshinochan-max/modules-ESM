"""Required source-bound heavy acceptance for SimpleFold confidence."""

from __future__ import annotations

import builtins
import io
import json
import os
from pathlib import Path

import pytest

from core import (
    EnvironmentConfiguration,
    ProjectManager,
    V2RunService,
    WorkflowAuthoringService,
    WorkflowDocument,
    WorkflowNodeInstance,
    build_frozen_catalog,
    parse_workflow_document,
)
from core.port_types import canonical_json_bytes
from core.workflow_v2 import WorkflowEdge
from datatypes import ScoreCollection
from tests.acceptance.conftest import require_ready


@pytest.mark.acceptance
@pytest.mark.local_provider
@pytest.mark.slow
def test_simplefold_confidence_v2_evaluates_3gb1_exact_assets_without_refold(
    readiness: dict[str, bool],
    pdb_3gb1: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Execute the exact confidence-only Binding; its full gate forbids skips."""
    require_ready("simplefold", readiness)
    from modules.folding.package import MODULE_PACKAGE as FOLDING_PACKAGE
    from modules.folding.simplefold_confidence_adapter import (
        SIMPLEFOLD_CONFIDENCE_ARTIFACTS,
        SIMPLEFOLD_CONFIDENCE_DEVICE,
        SIMPLEFOLD_CONFIDENCE_ESM2_ARTIFACTS,
        configured_runtime_fingerprint,
        provider_identity,
    )
    from tests.fixtures.folding_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    source = WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.folding_structure_source",
        node_type_version="2.1.0",
        binding_id="contract_test.folding_structure_source.direct",
        binding_version="2.1.0",
        node_parameters={"pdb_string": pdb_3gb1.pdb_string},
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
    project = projects.create("SimpleFold confidence v2 3GB1")
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
    configured_model_root = Path(
        os.environ["PROTEIN_WORKBENCH_SIMPLEFOLD_MODEL_ROOT"]
    )
    configured_esm2_model_root = Path(
        os.environ["PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_MODEL_ROOT"]
    )
    model_root = tmp_path / "exact-confidence-models"
    esm2_model_root = tmp_path / "exact-confidence-esm2"
    model_root.mkdir()
    esm2_model_root.mkdir()
    for name in SIMPLEFOLD_CONFIDENCE_ARTIFACTS:
        os.link(configured_model_root / name, model_root / name)
    for name in SIMPLEFOLD_CONFIDENCE_ESM2_ARTIFACTS:
        os.link(configured_esm2_model_root / name, esm2_model_root / name)
    assert not (model_root / "boltz1_conf.ckpt").exists()
    assert not (model_root / "simplefold_100M.ckpt").exists()
    assert not (model_root / "simplefold_360M.ckpt").exists()
    assert not (
        esm2_model_root
        / "esm2_t36_3B_UR50D-contact-regression.pt"
    ).exists()
    forbidden_assets = {
        "boltz1_conf.ckpt",
        "simplefold_100M.ckpt",
        "simplefold_360M.ckpt",
        "esm2_t36_3B_UR50D-contact-regression.pt",
    }
    forbidden_accesses: list[str] = []

    def reject_forbidden(path: object) -> None:
        try:
            name = Path(os.fspath(path)).name
        except TypeError:
            return
        if name in forbidden_assets:
            forbidden_accesses.append(name)
            raise AssertionError(
                f"forbidden confidence asset was probed: {name}"
            )

    real_builtin_open = builtins.open
    real_io_open = io.open
    real_os_open = os.open
    real_os_stat = os.stat
    real_os_lstat = os.lstat
    real_os_access = os.access

    def guarded_builtin_open(file: object, *args: object, **kwargs: object):
        reject_forbidden(file)
        return real_builtin_open(file, *args, **kwargs)

    def guarded_io_open(file: object, *args: object, **kwargs: object):
        reject_forbidden(file)
        return real_io_open(file, *args, **kwargs)

    def guarded_os_open(path: object, *args: object, **kwargs: object):
        reject_forbidden(path)
        return real_os_open(path, *args, **kwargs)

    def guarded_os_stat(path: object, *args: object, **kwargs: object):
        reject_forbidden(path)
        return real_os_stat(path, *args, **kwargs)

    def guarded_os_lstat(path: object, *args: object, **kwargs: object):
        reject_forbidden(path)
        return real_os_lstat(path, *args, **kwargs)

    def guarded_os_access(path: object, *args: object, **kwargs: object):
        reject_forbidden(path)
        return real_os_access(path, *args, **kwargs)

    from modules.folding.simplefold_runtime import _setup_simplefold_imports

    old_cwd = _setup_simplefold_imports()
    try:
        from simplefold.wrapper import InferenceWrapper, ModelWrapper
    finally:
        os.chdir(old_cwd)
    refold_attempts: list[str] = []

    def reject_refold(*_args: object, **_kwargs: object) -> None:
        refold_attempts.append("refold")
        raise AssertionError(
            "existing-structure confidence invoked a folding path"
        )

    monkeypatch.setattr(
        ModelWrapper,
        "from_pretrained_folding_model",
        reject_refold,
    )
    monkeypatch.setattr(
        InferenceWrapper,
        "run_inference",
        reject_refold,
    )
    monkeypatch.setattr(builtins, "open", guarded_builtin_open)
    monkeypatch.setattr(io, "open", guarded_io_open)
    monkeypatch.setattr(os, "open", guarded_os_open)
    monkeypatch.setattr(os, "stat", guarded_os_stat)
    monkeypatch.setattr(os, "lstat", guarded_os_lstat)
    monkeypatch.setattr(os, "access", guarded_os_access)
    fingerprint = configured_runtime_fingerprint()
    environment = EnvironmentConfiguration({
        ("folding.simplefold_confidence.simplefold_local", "2.1.0"): {
            "values": {
                "model_root": model_root,
                "esm2_source_root": Path(
                    os.environ["PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_ROOT"]
                ),
                "esm2_model_root": esm2_model_root,
                "device": SIMPLEFOLD_CONFIDENCE_DEVICE,
                "resolved_runtime_fingerprint": fingerprint,
            },
            "safe_fingerprint": fingerprint,
            "invalidation_token": fingerprint,
        }
    })
    service = V2RunService(projects, catalog, authoring, environment)
    try:
        receipt = service.start_background(
            project.id,
            workflow_revision=relocked["workflow_revision"],
            compile_id=compiled.public_receipt()["compile_id"],
            client_request_id="simplefold-confidence-v2-heavy",
        )
        service.shutdown()
        projection = service.projection(project.id, receipt["run_id"])
        events = service.public_events(project.id, receipt["run_id"])
    finally:
        service.shutdown()

    assert forbidden_accesses == []
    assert refold_attempts == []
    assert projection["status"] == "succeeded", json.dumps(events, indent=2)
    output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "confidence"
        and item["output_port"] == "confidence_observations"
    )
    reference = output["port_type"]
    scores = catalog.require_port_type(
        reference["contract_id"],
        reference["contract_version"],
    ).decode(
        canonical_json_bytes(
            {
                "schema_namespace": "protein-workbench-port-value/v2",
                "port_type_id": reference["contract_id"],
                "port_type_version": reference["contract_version"],
                "value": output["values"][0],
            }
        )
    )
    assert type(scores) is ScoreCollection
    assert len(scores.entries) == 2
    by_metric = {
        entry.metric.contract_id: entry.value
        for entry in scores.entries
    }
    per_residue = by_metric["structure.plddt.per_residue"]
    mean_residue = by_metric["structure.plddt.mean_residue"]
    assert isinstance(per_residue, list) and len(per_residue) == 56
    assert all(
        isinstance(value, float) and 0.0 <= value <= 100.0
        for value in per_residue
    )
    assert mean_residue == pytest.approx(
        sum(per_residue) / len(per_residue),
        rel=0.0,
        abs=1e-12,
    )
    started = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_identity"].startswith(
            "folding.simplefold_confidence.assets."
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
    assert started[0]["engine_identity"].endswith(fingerprint)
    readiness_index = next(
        index
        for index, event in enumerate(events)
        if event["event"]["type"] == "readiness_attested"
        and event["event"]["binding"]["contract_id"]
        == "folding.simplefold_confidence.simplefold_local"
        and event["event"]["binding"]["contract_version"] == "2.1.0"
        and event["event"]["conclusion"] == "passing"
    )
    invocation_index = next(
        index
        for index, event in enumerate(events)
        if event["event"] == started[0]
    )
    assert readiness_index < invocation_index
    assert [
        event["event"]["status"]
        for event in events
        if event["event"]["type"] == "run_terminal"
    ] == ["succeeded"]
    identity = provider_identity()
    assert set(identity["artifact_sha256"]) == {
        "ccd.pkl",
        "plddt.ckpt",
        "simplefold_1.6B.ckpt",
    }
    assert set(identity["esm2_artifact_sha256"]) == {
        "esm2_t36_3B_UR50D.pt"
    }
    public = json.dumps({"projection": projection, "events": events})
    for forbidden in (
        "contact-regression",
        "boltz1_conf",
        "simplefold_100M",
        "simplefold_360M",
        os.environ["PROTEIN_WORKBENCH_SIMPLEFOLD_MODEL_ROOT"],
        os.environ["PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_ROOT"],
        os.environ["PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_MODEL_ROOT"],
    ):
        assert forbidden not in public
