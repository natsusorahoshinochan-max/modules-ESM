"""Minimal positive real-Provider gates for exact installed Bindings."""

from __future__ import annotations

from core.catalog.builder import build_frozen_catalog

import os
from pathlib import Path
from typing import Any

import pytest

from tests.acceptance.conftest import PROJECT_ROOT
from tests.acceptance.retained_evidence import retain_service_run


BIOHUB_ESM3_GATE_BINDINGS = (
    "esm3.generate_sequence.biohub_medium",
    "esm3.generate_structure.biohub_medium",
    "esm3.generate_paired.biohub_medium",
    "esm3.generate_sequence.biohub_open",
    "esm3.generate_structure.biohub_open",
    "esm3.generate_paired.biohub_open",
)
BIOHUB_ESM3_GATE_INVOCATIONS = 8
BIOHUB_ESM3_GATE_VERSION = "8.0.0"

_ESM3_GENERATION_PARAMETERS = {
    "num_steps": 2,
    "temperature": 0.25,
    "top_p": 0.9,
    "schedule": "linear",
    "strategy": "entropy",
    "temperature_annealing": False,
}


def _required_absolute_path(variable: str) -> Path:
    configured = os.environ.get(variable)
    assert configured is not None, f"{variable} must be configured"
    path = Path(configured).expanduser()
    assert path.is_absolute(), f"{variable} must be an absolute path"
    return path.resolve()


def _event_payloads(
    events: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    return tuple(item["event"] for item in events)


def _assert_exact_execution(
    *,
    projection: dict[str, Any],
    events: tuple[dict[str, Any], ...],
    node_id: str,
    binding_id: str,
    binding_version: str,
    method_digest: str,
    expected_roles: tuple[str, ...],
) -> tuple[dict[str, Any], ...]:
    dispositions = [
        item
        for item in projection["node_dispositions"]
        if item["node_id"] == node_id
    ]
    assert len(dispositions) == 1
    assert dispositions[0]["outcome"] == "succeeded"
    assert dispositions[0]["resolution"] == "executed"

    payloads = _event_payloads(events)
    readiness_index = next(
        index
        for index, event in enumerate(payloads)
        if event["type"] == "readiness_attested"
        and event["binding"]["contract_id"] == binding_id
        and event["binding"]["contract_version"] == binding_version
        and event["conclusion"] == "passing"
    )
    started = tuple(
        event
        for event in payloads
        if event["type"] == "engine_invocation_started"
        and event["engine_identity"] == method_digest
    )
    assert tuple(event["engine_role"] for event in started) == expected_roles
    operation_attempt_ids = {
        invocation["operation_attempt_id"] for invocation in started
    }
    assert len(operation_attempt_ids) == 1
    operation_attempt_id = next(iter(operation_attempt_ids))
    operation_started = next(
        event
        for event in payloads
        if event["type"] == "operation_attempt_started"
        and event["operation_attempt_id"] == operation_attempt_id
    )
    assert readiness_index < payloads.index(operation_started)
    assert payloads.index(operation_started) < payloads.index(started[0])

    terminal_by_id = {
        event["invocation_id"]: event
        for event in payloads
        if event["type"] == "engine_invocation_terminal"
        and event["invocation_id"]
        in {invocation["invocation_id"] for invocation in started}
    }
    assert set(terminal_by_id) == {
        invocation["invocation_id"] for invocation in started
    }
    assert all(
        terminal_by_id[invocation["invocation_id"]]["status"]
        == "succeeded"
        for invocation in started
    )
    operation_terminal = next(
        event
        for event in payloads
        if event["type"] == "operation_attempt_terminal"
        and event["operation_attempt_id"] == operation_attempt_id
    )
    assert operation_terminal["status"] == "succeeded"
    assert max(
        payloads.index(terminal_by_id[invocation["invocation_id"]])
        for invocation in started
    ) < payloads.index(operation_terminal)
    assert [
        event["status"]
        for event in payloads
        if event["type"] == "run_terminal"
    ] == ["succeeded"]
    return started


def _method_for_binding(
    catalog: Any,
    binding_id: str,
    binding_version: str,
) -> Any:
    binding = catalog.require_contract(
        "binding",
        binding_id,
        binding_version,
    )
    method = binding.descriptor["method"]
    return catalog.require_contract(
        "method",
        method["contract_id"],
        method["contract_version"],
    )


def _run_rich_esm3_generation(
    tmp_path: Path,
    *,
    operation: str,
    prompt_mode: str,
    binding_route: str,
    credential_handle: str,
) -> tuple[Any, Any, dict[str, Any], tuple[dict[str, Any], ...]]:
    from core.project.manager import ProjectManager
    from core.catalog.builder import (
        build_frozen_catalog,
    )
    from core.execution.environment import admit_environment_configuration
    from core.run_execution_v2 import V2RunService
    from core.workflow.authoring import WorkflowAuthoringService
    from core.workflow.document import (
        WorkflowDocument,
        WorkflowEdge,
        WorkflowNodeInstance,
    )
    from modules.esm3.package import MODULE_PACKAGE as ESM3_PACKAGE
    from modules.prompt_authoring.package import (
        MODULE_PACKAGE as PROMPT_AUTHORING_PACKAGE,
    )
    from modules.structure_prediction.package import (
        MODULE_PACKAGE as STRUCTURE_PREDICTION_PACKAGE,
    )
    from modules.structure_transform.package import (
        MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
    )
    from tests.fixtures.esm3_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    binding_id = f"esm3.{operation}.{binding_route}"
    catalog = build_frozen_catalog(
        (
            ESM3_PACKAGE,
            PROMPT_AUTHORING_PACKAGE,
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
    project = projects.create(f"Biohub ESM-3 {operation} rich prompt gate")
    authoring = WorkflowAuthoringService(projects, catalog)
    committed = authoring.commit(
        project.id,
        workflow=WorkflowDocument(
            schema_version="2.1.0",
            workflow_id=project.id,
            nodes=(
                WorkflowNodeInstance(
                    node_id="source",
                    node_type_id="contract_test.esm3_prompt_source",
                    node_type_version="3.0.0",
                    binding_id=(
                        "contract_test.esm3_prompt_source.direct"
                    ),
                    binding_version="3.0.0",
                    node_parameters={"mode": prompt_mode},
                    binding_parameters={},
                ),
                WorkflowNodeInstance(
                    node_id="generate",
                    node_type_id=f"esm3.{operation}",
                    node_type_version=BIOHUB_ESM3_GATE_VERSION,
                    binding_id=binding_id,
                    binding_version=BIOHUB_ESM3_GATE_VERSION,
                    node_parameters={
                        "effective_seed": 1603,
                        "num_samples": 1,
                        **_ESM3_GENERATION_PARAMETERS,
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
        ),
    )
    service = V2RunService(
        projects,
        catalog,
        authoring,
        admit_environment_configuration(
            catalog,
            {
                (binding_id, BIOHUB_ESM3_GATE_VERSION): {
                    "values": {
                        "endpoint_id": "biohub",
                        "credential_handle": credential_handle,
                    },
                }
            }
        ),
    )
    try:
        receipt = service.start_background(
            project.id,
            workflow_commit_id=committed.workflow_commit_id,
            client_request_id=f"biohub-{binding_route}-{operation}",
        )
        service.shutdown()
        projection = service.projection(project.id, receipt["run_id"])
        events = service.public_events(project.id, receipt["run_id"])
    finally:
        service.shutdown()
    return service, catalog, projection, events


@pytest.mark.acceptance
@pytest.mark.live_provider
def test_biohub_esm3_all_remote_bindings_execute_exact_methods(
    tmp_path: Path,
) -> None:
    from modules.esm3.adapter import (
        BIOHUB_ESM3_MEDIUM_MODEL,
        BIOHUB_ESM3_OPEN_MODEL,
    )
    from modules.esm3.credentials import read_biohub_token
    from tests.fixtures.esm3_generation import decode_output

    token = read_biohub_token(str(PROJECT_ROOT))
    routes = {
        "biohub_medium": BIOHUB_ESM3_MEDIUM_MODEL,
        "biohub_open": BIOHUB_ESM3_OPEN_MODEL,
    }
    expected_roles = {
        "generate_sequence": ("sequence_sample",),
        "generate_structure": ("structure_sample",),
        "generate_paired": ("sequence_parent", "structure_child"),
    }
    invocation_count = 0
    selected_bindings: set[str] = set()
    retained_runs: list[
        tuple[str, Any, Any, dict[str, Any], tuple[dict[str, Any], ...]]
    ] = []

    for route, expected_model in routes.items():
        for operation in (
            "generate_sequence",
            "generate_structure",
            "generate_paired",
        ):
            binding_id = f"esm3.{operation}.{route}"
            service, catalog, projection, events = _run_rich_esm3_generation(
                tmp_path / route / operation,
                operation=operation,
                prompt_mode=(
                    "rich_assigned"
                    if operation == "generate_structure"
                    else "rich_masked"
                ),
                binding_route=route,
                credential_handle=token,
            )

            assert projection["status"] == "succeeded", events
            method = _method_for_binding(
                catalog,
                binding_id,
                BIOHUB_ESM3_GATE_VERSION,
            )
            assert method.descriptor["model_identity"]["model"] == (
                expected_model
            )
            started = _assert_exact_execution(
                projection=projection,
                events=events,
                node_id="generate",
                binding_id=binding_id,
                binding_version=BIOHUB_ESM3_GATE_VERSION,
                method_digest=method.contract_digest,
                expected_roles=expected_roles[operation],
            )
            assert all(
                invocation["invocation_provenance"][
                    "effective_randomness"
                ]
                == {"control": "provider_uncontrolled"}
                for invocation in started
            )
            if operation == "generate_paired":
                assert started[1]["parent_invocation_id"] == (
                    started[0]["invocation_id"]
                )

            outputs = {
                output["output_port"]: output
                for output in projection["outputs"]
                if output["node_id"] == "generate"
            }
            prompt_output = next(
                output
                for output in projection["outputs"]
                if output["node_id"] == "source"
                and output["output_port"] == "protein_prompt"
            )
            if operation == "generate_sequence":
                sequences = decode_output(
                    service,
                    catalog,
                    projection,
                    outputs["sequence_candidates"],
                )
                assert len(sequences.items) == 1
                assert sequences.items[0].metadata[
                    "requested_generation_parameters"
                ] == _ESM3_GENERATION_PARAMETERS
                assert sequences.items[0].metadata[
                    "effective_generation_parameters"
                ]["sequence"] == _ESM3_GENERATION_PARAMETERS
            elif operation == "generate_structure":
                structures = decode_output(
                    service,
                    catalog,
                    projection,
                    outputs["structure_candidates"],
                )
                facts = decode_output(
                    service,
                    catalog,
                    projection,
                    outputs["confidence_facts"],
                )
                assert len(structures.items) == 1
                assert structures.items[0].data.pdb_string
                assert len(facts.entries) == 1
                assert structures.items[0].metadata["prediction_key"] == (
                    facts.entries[0].prediction_key
                )
                assert facts.observation_method.contract_digest == (
                    method.contract_digest
                )
                assert structures.items[0].metadata[
                    "requested_generation_parameters"
                ] == _ESM3_GENERATION_PARAMETERS
                assert structures.items[0].metadata[
                    "effective_generation_parameters"
                ]["structure"] == _ESM3_GENERATION_PARAMETERS
                assert facts.entries[0].prediction_axis.source.content_digest == (
                    prompt_output["content_digest"]
                )
            else:
                sequences = decode_output(
                    service,
                    catalog,
                    projection,
                    outputs["sequence_candidates"],
                )
                structures = decode_output(
                    service,
                    catalog,
                    projection,
                    outputs["structure_candidates"],
                )
                pairing = decode_output(
                    service,
                    catalog,
                    projection,
                    outputs["counterpart_pairs"],
                )
                facts = decode_output(
                    service,
                    catalog,
                    projection,
                    outputs["confidence_facts"],
                )
                assert len(sequences.items) == len(structures.items) == 1
                assert len(facts.entries) == 1
                assert structures.items[0].metadata["prediction_key"] == (
                    facts.entries[0].prediction_key
                )
                assert facts.observation_method.contract_digest == (
                    method.contract_digest
                )
                assert pairing.entries[0].subject.candidate_id == (
                    sequences.items[0].candidate_id
                )
                assert pairing.entries[0].reference.candidate_id == (
                    structures.items[0].candidate_id
                )
                assert structures.items[0].metadata[
                    "requested_generation_parameters"
                ] == _ESM3_GENERATION_PARAMETERS
                assert structures.items[0].metadata[
                    "effective_generation_parameters"
                ] == {
                    "sequence": _ESM3_GENERATION_PARAMETERS,
                    "structure": _ESM3_GENERATION_PARAMETERS,
                }
                assert facts.entries[0].prediction_axis.source.content_digest == (
                    prompt_output["content_digest"]
                )

            invocation_count += len(started)
            selected_bindings.add(binding_id)
            retained_runs.append((
                (
                    f"biohub-{route.removeprefix('biohub_')}-"
                    f"{operation.replace('_', '-')}"
                ),
                catalog,
                service,
                projection,
                events,
            ))

    assert invocation_count == BIOHUB_ESM3_GATE_INVOCATIONS
    assert selected_bindings == set(BIOHUB_ESM3_GATE_BINDINGS)
    for run_label, catalog, service, projection, events in retained_runs:
        retain_service_run(
            run_label,
            catalog=catalog,
            service=service,
            projection=projection,
            events=events,
        )


@pytest.mark.acceptance
@pytest.mark.live_provider
def test_biohub_esmfold2_executes_exact_method(
    tmp_path: Path,
) -> None:
    from modules.folding.adapter import REMOTE_ESMFOLD2_MODEL
    from modules.esm3.credentials import read_biohub_token
    from tests.acceptance.test_esmfold2_v2 import _fold_outputs
    from tests.test_folding_v2 import _run_fold

    token = read_biohub_token(str(PROJECT_ROOT))
    service, catalog, projection, events = _run_fold(
        tmp_path,
        route="remote",
        client=None,
        environment_overrides={
            "credential_handle": token,
        },
        source_sequence=(
            "MTYKLILNGKTLKGETTTEAVDAATAEKVFKQYANDNGVDGEWTYDDATKTFTVTE"
        ),
    )

    assert projection["status"] == "succeeded", events
    method = _method_for_binding(
        catalog,
        "folding.fold.esmfold2_remote",
        "9.0.0",
    )
    assert method.descriptor["model_identity"]["model"] == (
        REMOTE_ESMFOLD2_MODEL
    )
    started = _assert_exact_execution(
        projection=projection,
        events=events,
        node_id="fold",
        binding_id="folding.fold.esmfold2_remote",
        binding_version="9.0.0",
        method_digest=method.contract_digest,
        expected_roles=("fold_parent_0_sample_0",),
    )
    assert started[0]["invocation_provenance"] == {
        "effective_randomness": {"control": "provider_uncontrolled"}
    }
    structures, observations, facts = _fold_outputs(
        service,
        catalog,
        projection,
    )
    assert len(structures.items) == 1
    assert structures.items[0].data.pdb_string
    assert observations.entries
    assert len(facts.entries) == 1
    retain_service_run(
        "biohub-esmfold2",
        catalog=catalog,
        service=service,
        projection=projection,
        events=events,
    )


@pytest.mark.acceptance
@pytest.mark.local_provider
@pytest.mark.slow
def test_local_esmfold2_executes_exact_method(tmp_path: Path) -> None:
    from modules.folding.adapter import (
        LOCAL_ESMC_REVISION,
        LOCAL_ESMFOLD2_REVISION,
    )
    from tests.acceptance.test_esmfold2_v2 import _fold_outputs
    from tests.test_folding_v2 import _run_fold

    model_root = _required_absolute_path(
        "PROTEIN_WORKBENCH_ESMFOLD2_MODEL_ROOT"
    )
    esmc_model_root = _required_absolute_path(
        "PROTEIN_WORKBENCH_ESMFOLD2_ESMC_MODEL_ROOT"
    )
    runtime_directory = tmp_path / "runtime"
    runtime_directory.mkdir()
    service, catalog, projection, events = _run_fold(
        tmp_path,
        route="local",
        client=None,
        environment_overrides={
            "model_snapshot_path": model_root,
            "model_snapshot_revision": LOCAL_ESMFOLD2_REVISION,
            "language_model_snapshot_path": esmc_model_root,
            "language_model_snapshot_revision": LOCAL_ESMC_REVISION,
            "device": "cpu",
            "runtime_directory": runtime_directory,
        },
        source_sequence="AG",
    )

    assert projection["status"] == "succeeded", events
    method = _method_for_binding(
        catalog,
        "folding.fold.esmfold2_local",
        "10.0.0",
    )
    started = _assert_exact_execution(
        projection=projection,
        events=events,
        node_id="fold",
        binding_id="folding.fold.esmfold2_local",
        binding_version="10.0.0",
        method_digest=method.contract_digest,
        expected_roles=("fold_parent_0_sample_0",),
    )
    structures, observations, facts = _fold_outputs(
        service,
        catalog,
        projection,
    )
    assert len(structures.items) == 1
    assert structures.items[0].data.pdb_string
    assert observations.entries
    assert len(facts.entries) == 1
    assert started[0]["invocation_provenance"] == {
        "effective_randomness": {
            "control": "exact_seed",
            "effective_seed": structures.items[0].metadata[
                "effective_call_seed"
            ],
        }
    }
    retain_service_run(
        "local-esmfold2",
        catalog=catalog,
        service=service,
        projection=projection,
        events=events,
    )


@pytest.mark.acceptance
@pytest.mark.local_provider
@pytest.mark.slow
def test_proteinmpnn_design_and_score_execute_exact_methods(
    tmp_path: Path,
) -> None:
    from core.workflow.document import WorkflowEdge, WorkflowNodeInstance
    from datatypes.candidate import CandidateCollection
    from datatypes.observation import ScoreCollection
    from tests.acceptance.test_proteinmpnn_scoring_v2 import (
        _axis_resolver,
        _decode,
        _run,
    )

    structure_source = WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.proteinmpnn_3gb1_structure",
        node_type_version="4.0.0",
        binding_id="contract_test.proteinmpnn_3gb1_structure.direct",
        binding_version="4.0.0",
        node_parameters={},
        binding_parameters={},
    )
    design_nodes = (
        structure_source,
        _axis_resolver(),
        WorkflowNodeInstance(
            node_id="design",
            node_type_id="proteinmpnn.design",
            node_type_version="10.0.0",
            binding_id="proteinmpnn.design.local",
            binding_version="11.0.0",
            node_parameters={
                "effective_seed": 1603,
                "num_sequences": 1,
                "temperature": 0.1,
                "backbone_noise": 0,
            },
            binding_parameters={},
        ),
    )
    design_catalog, design_service, design_projection, design_events = _run(
        tmp_path / "design",
        nodes=design_nodes,
        edges=(
            WorkflowEdge(
                "source",
                "structure_candidates",
                "resolve-axes",
                "structure_candidates",
            ),
            WorkflowEdge(
                "source",
                "structure_candidates",
                "design",
                "structure_candidates",
            ),
            WorkflowEdge(
                "resolve-axes",
                "residue_axes",
                "design",
                "structure_residue_axes",
            ),
        ),
        binding_id="proteinmpnn.design.local",
        binding_version="11.0.0",
    )
    assert design_projection["status"] == "succeeded", design_events
    design_method = _method_for_binding(
        design_catalog,
        "proteinmpnn.design.local",
        "11.0.0",
    )
    design_started = _assert_exact_execution(
        projection=design_projection,
        events=design_events,
        node_id="design",
        binding_id="proteinmpnn.design.local",
        binding_version="11.0.0",
        method_digest=design_method.contract_digest,
        expected_roles=("design_parent_0",),
    )
    design_output = next(
        item
        for item in design_projection["outputs"]
        if item["node_id"] == "design"
    )
    designed = _decode(
        design_catalog,
        design_service,
        design_projection,
        design_output,
    )
    assert type(designed) is CandidateCollection
    assert len(designed.items) == 1
    assert designed.items[0].parent_ids
    assert design_started[0]["invocation_provenance"][
        "effective_randomness"
    ]["control"] == "exact_seed"

    score_nodes = (
        structure_source,
        _axis_resolver(),
        WorkflowNodeInstance(
            node_id="sequence-source",
            node_type_id="contract_test.proteinmpnn_3gb1_sequence",
            node_type_version="4.0.0",
            binding_id="contract_test.proteinmpnn_3gb1_sequence.direct",
            binding_version="4.0.0",
            node_parameters={},
            binding_parameters={},
        ),
        WorkflowNodeInstance(
            node_id="score",
            node_type_id="proteinmpnn.score",
            node_type_version="7.0.0",
            binding_id="proteinmpnn.score.local",
            binding_version="8.0.0",
            node_parameters={},
            binding_parameters={},
        ),
    )
    score_catalog, score_service, score_projection, score_events = _run(
        tmp_path / "score",
        nodes=score_nodes,
        edges=(
            WorkflowEdge(
                "source",
                "structure_candidates",
                "sequence-source",
                "structure_candidates",
            ),
            WorkflowEdge(
                "source",
                "structure_candidates",
                "resolve-axes",
                "structure_candidates",
            ),
            WorkflowEdge(
                "resolve-axes",
                "residue_axes",
                "score",
                "structure_residue_axes",
            ),
            WorkflowEdge(
                "source",
                "structure_candidates",
                "score",
                "structure_candidates",
            ),
            WorkflowEdge(
                "sequence-source",
                "sequence_candidates",
                "score",
                "sequence_candidates",
            ),
        ),
        binding_id="proteinmpnn.score.local",
        binding_version="8.0.0",
    )
    assert score_projection["status"] == "succeeded", score_events
    score_method = _method_for_binding(
        score_catalog,
        "proteinmpnn.score.local",
        "8.0.0",
    )
    _assert_exact_execution(
        projection=score_projection,
        events=score_events,
        node_id="score",
        binding_id="proteinmpnn.score.local",
        binding_version="8.0.0",
        method_digest=score_method.contract_digest,
        expected_roles=("score_subject",),
    )
    score_output = next(
        item
        for item in score_projection["outputs"]
        if item["node_id"] == "score"
    )
    scores = _decode(
        score_catalog,
        score_service,
        score_projection,
        score_output,
    )
    assert type(scores) is ScoreCollection
    assert len(scores.entries) == 1
    assert scores.entries[0].method.contract_digest == (
        score_method.contract_digest
    )
    retain_service_run(
        "proteinmpnn-design",
        catalog=design_catalog,
        service=design_service,
        projection=design_projection,
        events=design_events,
    )
    retain_service_run(
        "proteinmpnn-score",
        catalog=score_catalog,
        service=score_service,
        projection=score_projection,
        events=score_events,
    )


@pytest.mark.acceptance
@pytest.mark.local_provider
def test_mkdssp_executes_exact_method_through_public_run(
    tmp_path: Path,
    pdb_3gb1: Any,
) -> None:
    from core.project.manager import ProjectManager
    from core.catalog.builder import (
        build_frozen_catalog,
    )
    from core.execution.environment import admit_environment_configuration
    from core.run_execution_v2 import V2RunService
    from core.workflow.authoring import WorkflowAuthoringService
    from core.workflow.document import (
        WorkflowDocument,
        WorkflowEdge,
        WorkflowNodeInstance,
    )
    from modules.protein_io.package import MODULE_PACKAGE as PROTEIN_IO_PACKAGE
    from modules.prompt_authoring.package import (
        MODULE_PACKAGE as PROMPT_AUTHORING_PACKAGE,
    )
    from modules.structure_annotation.domain import DSSPAnnotation
    from modules.structure_annotation.package import (
        MODULE_PACKAGE as STRUCTURE_ANNOTATION_PACKAGE
    )
    from modules.structure_transform.package import (
        MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
    )

    binary = _required_absolute_path("PROTEIN_WORKBENCH_MKDSSP_BINARY")

    catalog = build_frozen_catalog(
        (
            PROTEIN_IO_PACKAGE,
            PROMPT_AUTHORING_PACKAGE,
            STRUCTURE_ANNOTATION_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        )
    )
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create("installed mkdssp acceptance")
    projects.publish_input(
        project.id,
        "structure-input",
        pdb_3gb1.pdb_string.encode("ascii"),
        filename="3GB1.pdb",
    )
    authoring = WorkflowAuthoringService(projects, catalog)
    workflow = WorkflowDocument(
        schema_version="2.1.0",
        workflow_id=project.id,
        nodes=(
            WorkflowNodeInstance(
                node_id="import",
                node_type_id="protein_io.import_structure",
                node_type_version="6.0.0",
                binding_id="protein_io.import_structure.direct",
                binding_version="6.0.0",
                node_parameters={"project_input_ref": "structure-input"},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="resolve-axis",
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
            ),
            WorkflowNodeInstance(
                node_id="annotate",
                node_type_id="structure_annotation.dssp_compute",
                node_type_version="7.0.0",
                binding_id=(
                    "structure_annotation.dssp_compute.mkdssp_local"
                ),
                binding_version="7.0.0",
                node_parameters={},
                binding_parameters={},
            ),
        ),
        edges=(
            WorkflowEdge(
                "import",
                "structure_candidates",
                "resolve-axis",
                "structure_candidates",
            ),
            WorkflowEdge(
                "import",
                "structure_candidates",
                "annotate",
                "structure_candidates",
            ),
            WorkflowEdge(
                "resolve-axis",
                "residue_axes",
                "annotate",
                "residue_axes",
            ),
        ),
        contract_lock=(),
    )
    committed = authoring.commit(
        project.id,
        workflow=workflow,
    )
    binding_id = "structure_annotation.dssp_compute.mkdssp_local"
    service = V2RunService(
        projects,
        catalog,
        authoring,
        admit_environment_configuration(
            catalog,
            {
                (binding_id, "7.0.0"): {
                    "values": {"dssp_binary": str(binary)},
                }
            },
        ),
    )
    try:
        receipt = service.start_background(
            project.id,
            workflow_commit_id=committed.workflow_commit_id,
            client_request_id="installed-mkdssp",
        )
        service.shutdown()
        projection = service.projection(project.id, receipt["run_id"])
        events = service.public_events(project.id, receipt["run_id"])
    finally:
        service.shutdown()

    assert projection["status"] == "succeeded", events
    output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "annotate"
    )
    from tests.fixtures.public_v2 import decode_service_typed_output_value

    annotation = decode_service_typed_output_value(
        service,
        catalog,
        projection,
        output,
    )
    axis_output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "resolve-axis"
        and item["output_port"] == "residue_axes"
    )
    axis_associations = decode_service_typed_output_value(
        service,
        catalog,
        projection,
        axis_output,
    )
    association = axis_associations.entries[0]
    assert type(annotation) is DSSPAnnotation
    assert annotation.subject == association.subject
    assert annotation.layout == association.residue_axis.layout
    assert annotation.layout.residue_ids == tuple(
        f"A:{residue_number}" for residue_number in range(1, 57)
    )
    assert "".join(annotation.secondary_structure) == (
        "CEEEEEEECSSCEEEEEEECSSHHHHHHHHHHHHHHTTCCSEEEEETTTTEEEEEC"
    )
    assert all(type(value) is float for value in annotation.sasa)

    method = _method_for_binding(catalog, binding_id, "7.0.0")
    _assert_exact_execution(
        projection=projection,
        events=events,
        node_id="annotate",
        binding_id=binding_id,
        binding_version="7.0.0",
        method_digest=method.contract_digest,
        expected_roles=("primary",),
    )
    retain_service_run(
        "mkdssp",
        catalog=catalog,
        service=service,
        projection=projection,
        events=events,
    )
