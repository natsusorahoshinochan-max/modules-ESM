"""Task-shaped Workflow stress journeys through the public v2 protocol."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
import pytest

from core.catalog.builder import build_frozen_catalog
from core.catalog.declarations import (
    AvailabilityResult,
    ModulePackageRegistration,
)
from core.operation import BindingEnvironment, ReadinessResult
from core.workflow.compiler import CompilationRequest, compile
from datatypes.candidate import CandidateCollection
from datatypes.observation import (
    PairwiseCandidateMapping,
    PairwiseObservationContext,
    ScoreCollection,
)
from datatypes.prompt import ProteinPrompt
from modules.selection.package import MODULE_PACKAGE as SELECTION_PACKAGE
from modules.structure_comparison.package import (
    MODULE_PACKAGE as STRUCTURE_COMPARISON_PACKAGE,
)
from modules.structure_transform.package import (
    MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
)
from protein_workbench_public.workflow_codec import decode_workflow_document
from tests.fixtures.multi_objective_selection_sources.package import (
    MODULE_PACKAGE as SELECTION_SOURCE_PACKAGE,
)
from tests.fixtures.canonical_3gb1_v2 import (
    ControlledESM3Client,
    ControlledFoldingClient,
)
from tests.support.application import create_application
from tests.support.workflow_stress import (
    ControlledStressProteinMPNN,
    candidate_ids,
    commit_and_run,
    configure_isolated_roots,
    decode_one,
    emit_stress_report,
    run_committed_workflow,
    stress_registrations,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
STRESS_WORKFLOW_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "workflow_stress"
STRESS_WORKFLOWS = {
    "prompt_conditioning": STRESS_WORKFLOW_ROOT
    / "prompt_conditioning.workflow.json",
    "multi_selection": STRESS_WORKFLOW_ROOT / "multi_selection.workflow.json",
    "multi_parent_batch": STRESS_WORKFLOW_ROOT
    / "multi_parent_batch.workflow.json",
    "provider_downstream_commit": STRESS_WORKFLOW_ROOT
    / "provider_downstream_commit.workflow.json",
}
CONTROLLED_PROVIDER_BINDINGS = frozenset({
    "esm3.generate_paired.biohub_medium",
    "esm3.generate_sequence.biohub_medium",
    "folding.fold.esmfold2_remote",
    "proteinmpnn.design.local",
})


def _controlled_stress_catalog() -> Any:
    def available() -> AvailabilityResult:
        return AvailabilityResult.available()

    def ready(_environment: BindingEnvironment) -> ReadinessResult:
        return ReadinessResult(True)

    registrations: list[ModulePackageRegistration] = []
    for registration in stress_registrations():
        bindings = tuple(
            replace(
                binding,
                availability=replace(binding.availability, check=available),
                readiness=replace(binding.readiness, check=ready),
            )
            if binding.binding_id in CONTROLLED_PROVIDER_BINDINGS
            else binding
            for binding in registration.bindings
        )
        registrations.append(replace(registration, bindings=bindings))
    return build_frozen_catalog(tuple(registrations))


def _stress_payload(name: str, project_id: str) -> dict[str, Any]:
    payload = json.loads(STRESS_WORKFLOWS[name].read_text(encoding="utf-8"))
    payload["workflow_id"] = project_id
    return payload


def test_stress_workflows_are_repository_owned_and_compilable() -> None:
    catalog = build_frozen_catalog(stress_registrations())

    for path in STRESS_WORKFLOWS.values():
        workflow = decode_workflow_document(
            json.loads(path.read_text(encoding="utf-8"))
        )
        assert replace(workflow) == workflow
        plan = compile(CompilationRequest(workflow), catalog)
        assert plan.workflow_id == workflow.workflow_id


def _selection_catalog() -> Any:
    return build_frozen_catalog(
        (
            SELECTION_PACKAGE,
            STRUCTURE_COMPARISON_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
            SELECTION_SOURCE_PACKAGE,
        )
    )


def _selection_payload(project_id: str, *, top_k: int) -> dict[str, Any]:
    payload = _stress_payload("multi_selection", project_id)
    nodes = {node["node_id"]: node for node in payload["nodes"]}
    nodes["select-top_k"]["node_parameters"]["k"] = top_k
    return payload


def test_user_can_compare_selection_strategies_and_change_only_top_k(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All six strategies run together; a downstream revision reuses upstream."""
    configure_isolated_roots(tmp_path, monkeypatch)
    catalog = _selection_catalog()
    locked_payload = _selection_payload(
        "stress-multi-selection",
        top_k=2,
    )
    locked_nodes = {
        node["node_id"]: node for node in locked_payload["nodes"]
    }
    assert locked_nodes["select-filter"]["node_parameters"]["threshold"] == 0.95
    assert all(
        locked_nodes[node_id]["node_parameters"]["out_of_scope_policy"]
        == "ignore"
        for node_id in ("select-filter", "select-sort", "select-top_k")
    )
    app = create_application(frozen_catalog_override=catalog)

    with TestClient(app) as client:
        project_id = client.post(
            "/api/v2/projects",
            json={"name": "selection strategy stress"},
        ).json()["id"]
        first = commit_and_run(
            client,
            project_id,
            _selection_payload(project_id, top_k=2),
            request_id="selection-strategies-k2",
        )
        replay = run_committed_workflow(
            client,
            project_id,
            first.workflow_commit_id,
            request_id="selection-strategies-k2-replay",
        )
        second = commit_and_run(
            client,
            project_id,
            _selection_payload(project_id, top_k=3),
            request_id="selection-strategies-k3",
        )

        assert first.projection["status"] == "succeeded", json.dumps(
            first.projection,
            indent=2,
        )
        assert replay.projection["status"] == "succeeded"
        assert second.projection["status"] == "succeeded", json.dumps(
            second.projection,
            indent=2,
        )
        assert candidate_ids(
            client, catalog, first.projection, "select-filter"
        ) == ()
        assert len(candidate_ids(
            client, catalog, first.projection, "select-sort"
        )) == 4
        first_top = candidate_ids(
            client, catalog, first.projection, "select-top_k"
        )
        second_top = candidate_ids(
            client, catalog, second.projection, "select-top_k"
        )
        assert len(first_top) == 2
        assert len(second_top) == 3
        assert second_top[:2] == first_top
        assert len(candidate_ids(
            client, catalog, first.projection, "select-weighted_rank"
        )) == 4
        assert len(candidate_ids(
            client, catalog, first.projection, "select-pareto"
        )) == 2
        assert len(candidate_ids(
            client, catalog, first.projection, "select-diversity"
        )) == 3

        scores = decode_one(
            client,
            catalog,
            first.projection,
            "canonical-scores",
            "scores",
        )
        assert type(scores) is ScoreCollection
        assert len(scores.entries) == 8
        source_ids = candidate_ids(
            client,
            catalog,
            first.projection,
            "canonical-source",
        )
        assert len(source_ids) == 4
        assert {entry.subject.candidate_id for entry in scores.entries} == set(
            source_ids
        )
        assert {
            entry.metric.contract_id for entry in scores.entries
        } == {"contract_test.multi_objective_selection_score"}
        assert {
            entry.method.contract_id for entry in scores.entries
        } == {"contract_test.multi_objective_selection_source.method"}
        assert all(
            type(entry.context) is PairwiseObservationContext
            for entry in scores.entries
        )
        assert {
            entry.context.pairing_mode for entry in scores.entries
        } == {"fixed_reference", "per_subject_counterpart"}
        assert {
            entry.source_partition for entry in scores.entries
        } == {
            "canonical.selection_score.fixed_3gb1",
            "canonical.selection_score.paired_esm3",
        }

    second_dispositions = {
        item["node_id"]: item for item in second.projection["node_dispositions"]
    }
    assert second_dispositions["select-top_k"]["resolution"] == "executed"
    assert all(
        disposition["resolution"] == "cache_replayed"
        for node_id, disposition in second_dispositions.items()
        if node_id != "select-top_k"
    )
    assert not any(
        message["event"]["type"] == "engine_invocation_started"
        for message in second.events
    )
    assert all(
        item["resolution"] == "cache_replayed"
        for item in replay.projection["node_dispositions"]
    )
    assert not any(
        message["event"]["type"] == "engine_invocation_started"
        for message in replay.events
    )
    emit_stress_report(
        "multi_selection",
        runs={"first": first, "replay": replay, "downstream_commit": second},
        cardinalities={
            "source_candidates": 4,
            "zero_pass_filter": 0,
            "top_k_first": 2,
            "top_k_second": 3,
            "score_observations": 8,
        },
    )


def test_user_can_condition_function_tracks_generate_and_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Function-conditioned Prompt branches retain tracks and replay exactly."""
    configure_isolated_roots(tmp_path, monkeypatch)
    esm3 = ControlledESM3Client()
    monkeypatch.setattr(
        "modules.esm3.adapter.build_biohub_esm3_client",
        lambda **_kwargs: esm3,
    )
    catalog = _controlled_stress_catalog()
    environment = {
        binding_id: {
            "credential_handle": "controlled-esm3-credential",
        }
        for binding_id in (
            "esm3.generate_paired.biohub_medium",
            "esm3.generate_sequence.biohub_medium",
        )
    }
    app = create_application(
        frozen_catalog_override=catalog,
        v2_environment_configuration=environment,
    )

    with TestClient(app) as client:
        project_id = client.post(
            "/api/v2/projects",
            json={"name": "prompt conditioning stress"},
        ).json()["id"]
        first = commit_and_run(
            client,
            project_id,
            _stress_payload("prompt_conditioning", project_id),
            request_id="prompt-conditioning-first",
        )
        replay = run_committed_workflow(
            client,
            project_id,
            first.workflow_commit_id,
            request_id="prompt-conditioning-replay",
        )

        assert first.projection["status"] == replay.projection["status"] == (
            "succeeded"
        )
        assembled = decode_one(
            client,
            catalog,
            first.projection,
            "assemble-prompt",
            "protein_prompt",
        )
        masked = decode_one(
            client,
            catalog,
            first.projection,
            "mask-sequence",
            "protein_prompt",
        )
        assert type(assembled) is type(masked) is ProteinPrompt
        assert masked.target_layout == assembled.target_layout
        assert masked.structure_track == assembled.structure_track
        assert masked.structure_visibility_track == (
            assembled.structure_visibility_track
        )
        assert masked.secondary_structure_track == (
            assembled.secondary_structure_track
        )
        assert masked.sasa_track == assembled.sasa_track
        assert masked.function_annotations == assembled.function_annotations
        assert [
            index
            for index, value in enumerate(masked.sequence_track.values)
            if value is None
        ] == [19, 20, 21]
        annotation = masked.function_annotations.annotations[0]
        assert (
            annotation.label,
            annotation.start_residue_id,
            annotation.end_residue_id,
        ) == ("binding_site", "A:10", "A:12")

        paired_sequences = decode_one(
            client,
            catalog,
            first.projection,
            "generate-paired",
            "sequence_candidates",
        )
        paired_structures = decode_one(
            client,
            catalog,
            first.projection,
            "generate-paired",
            "structure_candidates",
        )
        paired_mapping = decode_one(
            client,
            catalog,
            first.projection,
            "generate-paired",
            "counterpart_pairs",
        )
        sequence_only = decode_one(
            client,
            catalog,
            first.projection,
            "generate-sequence",
            "sequence_candidates",
        )
        assert all(
            type(value) is CandidateCollection
            for value in (paired_sequences, paired_structures, sequence_only)
        )
        assert len(paired_sequences.items) == len(paired_structures.items) == 1
        assert len(sequence_only.items) == 1
        assert paired_structures.items[0].parent_ids == (
            paired_sequences.items[0].candidate_id,
        )
        assert type(paired_mapping) is PairwiseCandidateMapping
        assert len(paired_mapping.entries) == 1
        assert (
            paired_mapping.entries[0].subject.candidate_id,
            paired_mapping.entries[0].reference.candidate_id,
        ) == (
            paired_sequences.items[0].candidate_id,
            paired_structures.items[0].candidate_id,
        )

    assert len(esm3.sequence_prompts) == 4
    assert len(esm3.structure_prompts) == 2
    assert all(
        prompt.function_annotations[0].label == "binding_site"
        for prompt in (*esm3.sequence_prompts, *esm3.structure_prompts)
    )
    replay_dispositions = {
        item["node_id"]: item["resolution"]
        for item in replay.projection["node_dispositions"]
    }
    assert replay_dispositions == {
        "prompt-values": "cache_replayed",
        "add-function": "cache_replayed",
        "assemble-prompt": "cache_replayed",
        "mask-sequence": "cache_replayed",
        "generate-paired": "executed",
        "generate-sequence": "executed",
    }
    assert sum(
        message["event"]["type"] == "engine_invocation_started"
        for message in replay.events
    ) == 3
    emit_stress_report(
        "prompt_conditioning",
        runs={"first": first, "replay": replay},
        cardinalities={
            "masked_residues": 3,
            "function_annotations": 1,
            "paired_sequences": 1,
            "paired_structures": 1,
            "sequence_only_candidates": 1,
        },
    )


def test_user_can_design_two_by_two_by_two_with_exact_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two parents produce four designs and eight folds without positional joins."""
    configure_isolated_roots(tmp_path, monkeypatch)
    proteinmpnn = ControlledStressProteinMPNN()
    folding = ControlledFoldingClient()
    monkeypatch.setattr(
        "modules.proteinmpnn.adapter._LocalProteinMPNNProvider",
        lambda **_kwargs: proteinmpnn,
    )
    monkeypatch.setattr(
        "modules.folding.esmfold2_remote.build_remote_engine",
        lambda _environment: folding,
    )
    catalog = _controlled_stress_catalog()
    environment = {
        "proteinmpnn.design.local": {
            "provider_root": PROJECT_ROOT / "repositories" / "ProteinMPNN",
        },
        "folding.fold.esmfold2_remote": {
                "credential_handle": "controlled-folding-credential",
            },
    }
    app = create_application(
        frozen_catalog_override=catalog,
        v2_environment_configuration=environment,
    )

    with TestClient(app) as client:
        project_id = client.post(
            "/api/v2/projects",
            json={"name": "multi-parent multiplicity stress"},
        ).json()["id"]
        first = commit_and_run(
            client,
            project_id,
            _stress_payload("multi_parent_batch", project_id),
            request_id="multi-parent-first",
        )
        replay = run_committed_workflow(
            client,
            project_id,
            first.workflow_commit_id,
            request_id="multi-parent-replay",
        )

        assert first.projection["status"] == replay.projection["status"] == (
            "succeeded"
        )
        parents = decode_one(
            client,
            catalog,
            first.projection,
            "structure-parents",
            "structure_candidates",
        )
        designs = decode_one(
            client,
            catalog,
            first.projection,
            "design-children",
            "sequence_candidates",
        )
        folds = decode_one(
            client,
            catalog,
            first.projection,
            "fold-children",
            "structure_candidates",
        )
        confidence = decode_one(
            client,
            catalog,
            first.projection,
            "materialize-confidence",
            "observations",
        )
        assert len(parents.items) == 2
        assert len(designs.items) == 4
        designs_by_parent = {
            parent.candidate_id: [
                design
                for design in designs.items
                if design.parent_ids == (parent.candidate_id,)
            ]
            for parent in parents.items
        }
        assert {len(children) for children in designs_by_parent.values()} == {2}
        assert {
            tuple(child.metadata["sample_index"] for child in children)
            for children in designs_by_parent.values()
        } == {(0, 1)}

        assert len(folds.items) == 8
        folds_by_design = {
            design.candidate_id: [
                folded
                for folded in folds.items
                if folded.parent_ids == (design.candidate_id,)
            ]
            for design in designs.items
        }
        assert {len(children) for children in folds_by_design.values()} == {2}
        assert {
            tuple(child.metadata["sample_index"] for child in children)
            for children in folds_by_design.values()
        } == {(0, 1)}
        assert type(confidence) is ScoreCollection
        assert len(confidence.entries) == 32
        assert {entry.subject.candidate_id for entry in confidence.entries} == {
            folded.candidate_id for folded in folds.items
        }
        assert {
            entry.metric.contract_id for entry in confidence.entries
        } == {
            "structure.ptm",
            "structure.plddt.per_residue",
            "structure.plddt.mean_residue",
            "structure.pae",
        }
        assert {
            sum(
                entry.subject.candidate_id == folded.candidate_id
                for entry in confidence.entries
            )
            for folded in folds.items
        } == {4}

    assert len(proteinmpnn.parsed) == len(proteinmpnn.requests) == 2
    assert len(folding.calls) == 16
    replay_dispositions = {
        item["node_id"]: item["resolution"]
        for item in replay.projection["node_dispositions"]
    }
    assert replay_dispositions == {
        "structure-parents": "cache_replayed",
        "resolve-parent-axes": "cache_replayed",
        "design-children": "cache_replayed",
        "fold-children": "executed",
        "materialize-confidence": "executed",
    }
    emit_stress_report(
        "multi_parent_batch",
        runs={"first": first, "replay": replay},
        cardinalities={
            "structure_parents": 2,
            "designed_sequences": 4,
            "folded_structures": 8,
            "confidence_observations": 32,
        },
    )


def test_downstream_commit_replays_cacheable_provider_without_invocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Changing only a terminal prefix does not re-enter ProteinMPNN."""
    configure_isolated_roots(tmp_path, monkeypatch)
    proteinmpnn = ControlledStressProteinMPNN()
    monkeypatch.setattr(
        "modules.proteinmpnn.adapter._LocalProteinMPNNProvider",
        lambda **_kwargs: proteinmpnn,
    )
    catalog = _controlled_stress_catalog()
    app = create_application(
        frozen_catalog_override=catalog,
        v2_environment_configuration={
            "proteinmpnn.design.local": {
                "provider_root": (
                    PROJECT_ROOT / "repositories" / "ProteinMPNN"
                ),
            }
        },
    )

    with TestClient(app) as client:
        project_id = client.post(
            "/api/v2/projects",
            json={"name": "provider downstream commit stress"},
        ).json()["id"]
        first_payload = _stress_payload(
            "provider_downstream_commit",
            project_id,
        )
        first = commit_and_run(
            client,
            project_id,
            first_payload,
            request_id="provider-downstream-k2",
        )
        replay = run_committed_workflow(
            client,
            project_id,
            first.workflow_commit_id,
            request_id="provider-downstream-k2-replay",
        )
        second_payload = _stress_payload(
            "provider_downstream_commit",
            project_id,
        )
        second_nodes = {
            node["node_id"]: node for node in second_payload["nodes"]
        }
        second_nodes["take-designs"]["node_parameters"]["k"] = 3
        second = commit_and_run(
            client,
            project_id,
            second_payload,
            request_id="provider-downstream-k3",
        )

        assert {
            first.projection["status"],
            replay.projection["status"],
            second.projection["status"],
        } == {"succeeded"}
        assert len(candidate_ids(
            client,
            catalog,
            first.projection,
            "take-designs",
        )) == 2
        assert len(candidate_ids(
            client,
            catalog,
            second.projection,
            "take-designs",
        )) == 3

    assert len(proteinmpnn.parsed) == len(proteinmpnn.requests) == 2
    assert all(
        item["resolution"] == "cache_replayed"
        for item in replay.projection["node_dispositions"]
    )
    second_dispositions = {
        item["node_id"]: item["resolution"]
        for item in second.projection["node_dispositions"]
    }
    assert second_dispositions == {
        "structure-parents": "cache_replayed",
        "resolve-parent-axes": "cache_replayed",
        "design-children": "cache_replayed",
        "take-designs": "executed",
    }
    assert not any(
        message["event"]["type"] == "engine_invocation_started"
        for run in (replay, second)
        for message in run.events
    )
    emit_stress_report(
        "provider_downstream_commit",
        runs={"first": first, "replay": replay, "downstream_commit": second},
        cardinalities={
            "provider_parents": 2,
            "designed_sequences": 4,
            "selected_first": 2,
            "selected_second": 3,
        },
    )
