"""Required real-Provider acceptance for SimpleFold confidence."""

from __future__ import annotations

from tests.support.ledger import public_run_events, public_run_projection

import builtins
import io
import json
import os
from pathlib import Path

import pytest

from core.project.manager import ProjectManager
from core.catalog.builder import (
    build_frozen_catalog,
)
from core.execution.environment import admit_environment_configuration
from core.execution.node_attempt import NodeAttemptFactory
from core.execution.runtime import V2RunService
from tests.support.result_store import result_store
from core.workflow.authoring import WorkflowAuthoringService
from core.workflow.document import (
    WorkflowDocument,
    WorkflowNodeInstance,
)
from core.workflow.document import WorkflowEdge
from datatypes.observation import ScoreCollection
from tests.acceptance.retained_evidence import retain_service_run


@pytest.mark.acceptance
@pytest.mark.local_provider
@pytest.mark.slow
def test_simplefold_confidence_v2_evaluates_3gb1_exact_assets_without_refold(
    pdb_3gb1: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Execute the exact confidence-only Binding; its full gate forbids skips."""
    from modules.folding.package import MODULE_PACKAGE as FOLDING_PACKAGE
    from modules.folding.simplefold_contract import (
        SIMPLEFOLD_CONFIDENCE_ASSET_CLOSURE,
    )
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
        node_type_id="contract_test.folding_structure_source",
        binding_id="contract_test.folding_structure_source.direct",
        node_parameters={"pdb_string": pdb_3gb1.pdb_string},
        binding_parameters={},
    )
    axis = WorkflowNodeInstance(
        node_id="axis",
        node_type_id=(
            "structure_transform.resolve_candidate_residue_axes"
        ),
        binding_id=(
            "structure_transform."
            "resolve_candidate_residue_axes.direct"
        ),
        node_parameters={},
        binding_parameters={},
    )
    confidence = WorkflowNodeInstance(
        node_id="confidence",
        node_type_id="folding.simplefold_confidence",
        binding_id="folding.simplefold_confidence.simplefold_local",
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
    project = projects.create("SimpleFold confidence v2 3GB1")
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
        ))
    committed = authoring.commit(
        project.id,
        workflow=workflow,
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
    for entry in SIMPLEFOLD_CONFIDENCE_ASSET_CLOSURE.files:
        if entry.environment_key == "model_root":
            (model_root / entry.runtime_filename).symlink_to(
                configured_model_root / entry.runtime_filename
            )
        elif entry.environment_key == "esm2_model_root":
            (esm2_model_root / entry.runtime_filename).symlink_to(
                configured_esm2_model_root / entry.runtime_filename
            )
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
    environment = admit_environment_configuration(catalog, {
        "folding.simplefold_confidence.simplefold_local": {
                "model_root": model_root,
                "esm2_source_root": Path(
                    os.environ["PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_ROOT"]
                ),
                "esm2_model_root": esm2_model_root,
            }
    })
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
    try:
        receipt = service.start_background(
            project.id,
            workflow_commit_id=committed.workflow_commit_id,
            client_request_id="simplefold-confidence-v2-heavy",
        )
        service.shutdown()
        projection = public_run_projection(service, project.id, receipt["run_id"])
        events = public_run_events(service, project.id, receipt["run_id"])
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
    from tests.fixtures.public_v2 import decode_service_typed_output_value

    scores = decode_service_typed_output_value(
        service,
        catalog,
        projection,
        output,
    )
    assert type(scores) is ScoreCollection
    assert len(scores.entries) == 2
    axis_output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "axis"
        and item["output_port"] == "residue_axes"
    )
    associations = decode_service_typed_output_value(
        service,
        catalog,
        projection,
        axis_output,
    )
    assert len(associations.entries) == 1
    resolved = associations.entries[0]
    assert resolved.residue_axis.layout.length == 56
    assert {
        entry.subject for entry in scores.entries
    } == {resolved.subject}
    assert all(
        entry.residue_axis is not None
        and entry.residue_axis.axis_kind == "resolved_structure"
        and entry.residue_axis.source == resolved.subject
        and entry.residue_axis.layout == resolved.residue_axis.layout
        for entry in scores.entries
    )
    by_metric = {
        entry.metric.contract_id: entry.value
        for entry in scores.entries
    }
    per_residue = by_metric["structure.plddt.per_residue"]
    mean_residue = by_metric["structure.plddt.mean_residue"]
    assert isinstance(per_residue, tuple) and len(per_residue) == 56
    assert all(
        isinstance(value, float) and 0.0 <= value <= 100.0
        for value in per_residue
    )
    missing_ca_mask = tuple(value is None for value in per_residue)
    assert missing_ca_mask == (False,) * 56
    assert mean_residue == pytest.approx(
        sum(per_residue) / len(per_residue),
        rel=0.0,
        abs=1e-12,
    )
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
        "folding.simplefold_confidence.simplefold_local")
    method_ref = binding.descriptor["method"]
    method = catalog.require_contract(
        "method",
        method_ref["contract_id"])
    assert started[0]["engine_identity"] == method.contract_id
    readiness_index = next(
        index
        for index, event in enumerate(events)
        if event["event"]["type"] == "readiness_attested"
        and event["event"]["binding"]["contract_id"]
        == "folding.simplefold_confidence.simplefold_local"
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
    retain_service_run(
        "simplefold-confidence",
        service=service,
        projection=projection,
        events=events,
    )
