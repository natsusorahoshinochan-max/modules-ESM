"""Public v2 contracts for partition-preserving collection operations."""

from __future__ import annotations

from tests.support.public_runs import PublicRunClient

from protein_workbench_public.bootstrap import module_registrations

from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from core.catalog.builder import (
    build_frozen_catalog,
)
from core.operation import (
    OperationCall,
)
from tests.support.contract_test_kit import ModulePackageContractCase, execute_module_package_case
from core.workflow.document import (
    WorkflowDocument,
    WorkflowNodeInstance,
)
from core.scoring.selection import SelectionInput, SelectionObjective
from core.project.manager import ProjectManager
from tests.support.application import create_application
from protein_workbench_public.workflow_codec import encode_workflow_document
from core.workflow.document import WorkflowEdge
from datatypes.candidate import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
)
from datatypes.exact_reference import ExactContractReference
from datatypes.observation import (
    IntrinsicObservationContext,
    CandidateRelation,
    CandidateRelationEntry,
    ScoreCollection,
    ScoreObservation,
)
from datatypes.sequence import ProteinSequence
from modules.collection_ops.package import MODULE_PACKAGE
from modules.selection.package import MODULE_PACKAGE as SELECTION_PACKAGE
from tests.support.runtime_results import decode_service_typed_output_value
from tests.support.inprocess_runs import wait_for_testclient_run_terminal
from tests.fixtures.scientific_operation import (
    admitted_port_fixture,
    build_operation,
    operation_call,
)
from modules.collection_ops.implementation import CollectionOpsImplementation


VERSION = "2.1.0"


def _application_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Path]:
    data_root = tmp_path / "application-data"
    roots = {
        "PROJECT": data_root / "projects",
        "CACHE": data_root / "cache",
        "OUTPUT": data_root / "outputs",
        "RUN": data_root / "runs",
    }
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(data_root))
    return roots


def test_candidate_intersection_and_child_selection_preserve_exact_candidates() -> None:
    all_parents = CandidateCollection(
        "parents",
        "protein.sequence",
        (
            Candidate("parent-a", ProteinSequence("AAAA")),
            Candidate("parent-b", ProteinSequence("AAAA")),
        ),
    )
    children = CandidateCollection(
        "children",
        "protein.sequence",
        (
            Candidate("child-a", ProteinSequence("AAAA"), ("parent-a",)),
            Candidate("child-b", ProteinSequence("AAAA"), ("parent-b",)),
        ),
    )
    catalog = build_frozen_catalog(module_registrations())
    relation = CollectionOpsImplementation("relate_by_parent").execute(
        operation_call(
            catalog=catalog,
            binding_id="collection_ops.relate_by_parent.direct",
            inputs={"subjects": children, "parents": all_parents},
        )
    )["relation"]
    inverted = CollectionOpsImplementation("invert_relation").execute(
        operation_call(
            catalog=catalog,
            binding_id="collection_ops.invert_relation.direct",
            inputs={"relation": relation},
        )
    )["relation"]
    assert tuple(
        (entry.subject, entry.reference)
        for entry in inverted.entries
    ) == tuple(
        (entry.reference, entry.subject)
        for entry in relation.entries
    )
    selected = CollectionOpsImplementation("select_related_subjects").execute(
        operation_call(
            catalog=catalog,
            binding_id="collection_ops.select_related_subjects.direct",
            inputs={
                "subjects": children,
                "selected_references": CandidateCollection(
                    "passing-parents",
                    "protein.sequence",
                    (all_parents.items[0],),
                ),
                "relation": relation,
            },
        )
    )["candidates"]
    assert tuple(item.candidate_id for item in selected.items) == ("child-a",)

    intersection = CollectionOpsImplementation("intersect_candidates").execute(
        OperationCall(
            inputs={
                name: admitted_port_fixture(
                    value,
                    port_type_id="candidate.collection",
                    value_content_digests=("sha256:" + digit * 64,),
                )
                for name, value, digit in (
                    ("candidates_a", children, "a"),
                    ("candidates_b", selected, "b"),
                    (
                        "candidates_c",
                        CandidateCollection(
                            "empty",
                            "protein.sequence",
                            (),
                        ),
                        "c",
                    ),
                )
            },
            node_parameters={},
            binding_parameters={},
            effective_randomness={},
        )
    )["candidates"]
    assert intersection.item_type == "protein.sequence"
    assert intersection.items == ()


def test_pairing_subject_selection_uses_exact_reference_membership() -> None:
    catalog = build_frozen_catalog(module_registrations())
    subjects = CandidateCollection(
        "subjects",
        "protein.sequence",
        tuple(
            Candidate(f"subject-{index}", ProteinSequence("AAAA"))
            for index in range(3)
        ),
    )
    references = CandidateCollection(
        "references",
        "protein.sequence",
        tuple(
            Candidate(f"reference-{index}", ProteinSequence("AAAA"))
            for index in range(3)
        ),
    )
    sequence_type = catalog.require_port_type("protein.sequence")

    def reference(candidate: Candidate) -> CandidateDataReference:
        return CandidateDataReference(
            candidate.candidate_id,
            "protein.sequence",
            sequence_type.content_digest(candidate.data),
        )

    pairing = CandidateRelation(
        tuple(
            CandidateRelationEntry(
                reference(subject),
                reference(reference_candidate),
            )
            for subject, reference_candidate in zip(
                subjects.items,
                references.items,
                strict=True,
            )
        )
    )
    call = operation_call(
        catalog=catalog,
        binding_id="collection_ops.select_related_subjects.direct",
        inputs={
            "subjects": subjects,
            "selected_references": CandidateCollection(
                "selected-references",
                "protein.sequence",
                (references.items[2], references.items[0]),
            ),
            "relation": pairing,
        },
    )

    outputs = CollectionOpsImplementation(
        "select_related_subjects"
    ).execute(call)

    assert [
        item.candidate_id for item in outputs["candidates"].items
    ] == ["subject-0", "subject-2"]
    assert [
        entry.reference.candidate_id for entry in outputs["relation"].entries
    ] == ["reference-0", "reference-2"]


def test_score_merge_preserves_exact_i_json_value_types() -> None:
    from tests.fixtures.collection_ops_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    catalog = build_frozen_catalog((MODULE_PACKAGE, SOURCE_PACKAGE))
    metric = ExactContractReference(
        **catalog.require_contract(
            "metric",
            "contract_test.collection_ops_value").reference()
    )
    method = ExactContractReference(
        **catalog.require_contract(
            "method",
            "contract_test.collection_ops_scorer.method").reference()
    )
    observation = ScoreObservation(
        subject=CandidateDataReference(
            "candidate-a",
            "protein.sequence",
            "sha256:" + "a" * 64,
        ),
        metric=metric,
        method=method,
        context=IntrinsicObservationContext(),
        source_partition="default",
        value={"nested": [True]},
    )
    call = operation_call(
        catalog=catalog,
        binding_id="collection_ops.merge_scores.direct",
        inputs={
            "scores_a": ScoreCollection("scores-a", (observation,)),
            "scores_b": ScoreCollection(
                "scores-b",
                (replace(observation, value={"nested": [1]}),),
            ),
        },
    )

    with pytest.raises(ValueError, match="conflicting values"):
        CollectionOpsImplementation("merge_scores").execute(call)


def _two_hop_lineage_collections() -> tuple[
    CandidateCollection,
    CandidateCollection,
    CandidateCollection,
]:
    ancestors = CandidateCollection(
        "ancestors",
        "protein.sequence",
        tuple(
            Candidate(f"ancestor-{index}", ProteinSequence("AAAA"))
            for index in range(2)
        ),
    )
    intermediates = CandidateCollection(
        "intermediates",
        "protein.sequence",
        tuple(
            Candidate(
                f"intermediate-{index}",
                ProteinSequence("AAAA"),
                (f"ancestor-{index // 3}",),
            )
            for index in range(6)
        ),
    )
    subjects = CandidateCollection(
        "subjects",
        "protein.sequence",
        tuple(
            Candidate(
                f"subject-{index}",
                ProteinSequence("AAAA"),
                (f"intermediate-{index}",),
            )
            for index in range(6)
        ),
    )
    return subjects, intermediates, ancestors


def test_two_hop_ancestor_pairing_allows_three_subjects_per_reference() -> None:
    catalog = build_frozen_catalog(module_registrations())
    subjects, intermediates, ancestors = _two_hop_lineage_collections()
    subject_to_intermediate = CollectionOpsImplementation(
        "relate_by_parent"
    ).execute(operation_call(
        catalog=catalog,
        binding_id="collection_ops.relate_by_parent.direct",
        inputs={"subjects": subjects, "parents": intermediates},
    ))["relation"]
    intermediate_to_ancestor = CollectionOpsImplementation(
        "relate_by_parent"
    ).execute(operation_call(
        catalog=catalog,
        binding_id="collection_ops.relate_by_parent.direct",
        inputs={"subjects": intermediates, "parents": ancestors},
    ))["relation"]
    pairing = CollectionOpsImplementation("compose_relations").execute(
        operation_call(
            catalog=catalog,
            binding_id="collection_ops.compose_relations.direct",
            inputs={
                "left_relation": subject_to_intermediate,
                "right_relation": intermediate_to_ancestor,
            },
        )
    )["relation"]

    assert [entry.subject.candidate_id for entry in pairing.entries] == [
        f"subject-{index}" for index in range(6)
    ]
    assert [entry.reference.candidate_id for entry in pairing.entries] == [
        "ancestor-0",
        "ancestor-0",
        "ancestor-0",
        "ancestor-1",
        "ancestor-1",
        "ancestor-1",
    ]


@pytest.mark.parametrize("failure", ["unrelated", "ambiguous"])
def test_two_hop_ancestor_pairing_rejects_unclosed_lineage(
    failure: str,
) -> None:
    catalog = build_frozen_catalog(module_registrations())
    subjects, intermediates, ancestors = _two_hop_lineage_collections()
    if failure == "unrelated":
        ancestors = CandidateCollection(
            ancestors.collection_id,
            ancestors.item_type,
            (*ancestors.items, Candidate("unrelated", ProteinSequence("AAAA"))),
        )
    else:
        first = intermediates.items[0]
        intermediates = CandidateCollection(
            intermediates.collection_id,
            intermediates.item_type,
            (
                replace(first, parent_ids=("ancestor-0", "ancestor-1")),
                *intermediates.items[1:],
            ),
        )
    with pytest.raises(ValueError):
        CollectionOpsImplementation("relate_by_parent").execute(
            operation_call(
                catalog=catalog,
                binding_id="collection_ops.relate_by_parent.direct",
                inputs={"subjects": intermediates, "parents": ancestors},
            )
        )


def _assert_workflow_commit_owner(
    app: FastAPI,
    project_id: str,
    *,
    source_draft_revision: int,
) -> None:
    owner = app.state.workflow_authoring
    commit = owner.load_active_commit(project_id)
    draft = owner.load_draft(project_id)
    compiled = owner.require_verified_commit(
        project_id,
        workflow_commit_id=commit.workflow_commit_id,
    )
    plan = compiled.execution_plan

    assert commit.source_draft_revision == source_draft_revision
    assert commit.source_draft_revision == draft.draft_revision
    assert commit.workflow == draft.workflow
    assert plan.workflow_id == commit.workflow.workflow_id
    assert commit.scientific_definitions == plan.scientific_definitions


def _source(
    partition: str,
    *,
    candidate_count: int = 1,
) -> WorkflowNodeInstance:
    return WorkflowNodeInstance(
        node_id=f"source-{partition}",
        node_type_id="contract_test.collection_ops_source",
        binding_id=f"contract_test.collection_ops_source.{partition}",
        node_parameters={"candidate_count": candidate_count},
        binding_parameters={},
    )


def _lineage_source(*, candidate_count: int = 2) -> WorkflowNodeInstance:
    return WorkflowNodeInstance(
        node_id="lineage-source",
        node_type_id="contract_test.collection_ops_lineage_source",
        binding_id="contract_test.collection_ops_lineage_source.direct",
        node_parameters={"candidate_count": candidate_count},
        binding_parameters={},
    )


def _public_collection_contracts() -> dict[tuple[str, str], dict]:
    catalog = build_frozen_catalog(module_registrations())
    app = create_application(frozen_catalog_override=catalog)
    with TestClient(app) as client:
        response = client.get("/api/v2/catalog")
    assert response.status_code == 200
    return {
        (
            contract["reference"]["contract_kind"],
            contract["reference"]["contract_id"],
        ): contract["descriptor"]
        for contract in response.json()["contracts"]
        if contract["reference"]["contract_id"].startswith(
            "collection_ops."
        )
    }


def test_public_catalog_has_exact_collection_operation_nodes() -> None:
    contracts = _public_collection_contracts()
    operations = {
        "concat_candidates",
        "merge_scores",
        "concat_relations",
        "relate_by_parent",
        "relate_to_single_reference",
        "compose_relations",
        "invert_relation",
        "join_relation_subjects",
        "take_candidates",
        "select_related_subjects",
        "intersect_candidates",
    }
    assert set(contracts) == {
        (kind, f"collection_ops.{operation}{suffix}")
        for operation in operations
        for kind, suffix in (
            ("binding", ".direct"),
            ("method", ".method"),
            ("node_type", ""),
        )
    }
    assert not any(
        "aggregate" in contract_id for _, contract_id in contracts
    )
    assert contracts[
        ("method", "collection_ops.compose_relations.method")
    ]["algorithm_identity"] == {
        "name": "compose_relations",
        "join": "left-reference-equals-right-subject",
        "cardinality": "one-reference-per-subject-shared-reference-allowed",
    }


def test_collection_ports_and_score_union_keep_stable_scientific_types() -> None:
    contracts = _public_collection_contracts()
    candidates = contracts[
        ("node_type", "collection_ops.concat_candidates")
    ]
    scores = contracts[("node_type", "collection_ops.merge_scores")]
    score_binding = contracts[
        ("binding", "collection_ops.merge_scores.direct")
    ]
    operations = {
        "concat_candidates",
        "concat_relations",
        "relate_by_parent",
        "relate_to_single_reference",
        "compose_relations",
        "join_relation_subjects",
        "take_candidates",
        "intersect_candidates",
        "select_related_subjects",
    }
    for operation in operations:
        node = contracts[("node_type", f"collection_ops.{operation}")]
        assert node["contract_id"] == f"collection_ops.{operation}"

    for (contract_kind, _), descriptor in contracts.items():
        if contract_kind != "node_type":
            continue
        for port in (*descriptor["inputs"], *descriptor["outputs"]):
            port_type = port["port_type"]
            assert port_type["contract_id"] in {
                "candidate.collection",
                "candidate.relation",
                "score.collection",
            }

    assert [
        (
            port["name"],
            port["port_type"]["contract_id"],
            port["required"],
            port["multiplicity"],
        )
        for port in candidates["inputs"]
    ] == [
        ("candidates_a", "candidate.collection", False, "one"),
        ("candidates_b", "candidate.collection", False, "one"),
        ("candidates_c", "candidate.collection", False, "one"),
    ]
    assert [
        (
            port["name"],
            port["port_type"]["contract_id"],
            port["required"],
            port["multiplicity"],
        )
        for port in scores["inputs"]
    ] == [
        ("scores_a", "score.collection", False, "one"),
        ("scores_b", "score.collection", False, "one"),
        ("scores_c", "score.collection", False, "one"),
    ]
    assert score_binding["produced_observations"] == []
    assert score_binding["observation_propagation"] == {
        "mode": "union",
        "output_port": "scores",
        "input_ports": ["scores_a", "scores_b", "scores_c"],
        "filter": None,
        "absent_input_policy": "ignore",
    }


def test_score_fixture_separates_candidate_admission_from_score_production(
) -> None:
    from tests.fixtures.collection_ops_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    catalog = build_frozen_catalog((SOURCE_PACKAGE,))
    source = catalog.require_contract(
        "node_type",
        "contract_test.collection_ops_source").descriptor
    scorer = catalog.require_contract(
        "node_type",
        "contract_test.collection_ops_scorer").descriptor
    source_binding = catalog.require_contract(
        "binding",
        "contract_test.collection_ops_source.a").descriptor
    scorer_binding = catalog.require_contract(
        "binding",
        "contract_test.collection_ops_scorer.a").descriptor

    assert source["inputs"] == ()
    assert [
        (
            port["name"],
            port["port_type"]["contract_id"],
        )
        for port in source["outputs"]
    ] == [
        ("candidates", "candidate.collection"),
    ]
    assert [
        (
            port["name"],
            port["port_type"]["contract_id"],
        )
        for port in scorer["inputs"]
    ] == [
        ("candidates", "candidate.collection"),
    ]
    assert [
        (
            port["name"],
            port["port_type"]["contract_id"],
        )
        for port in scorer["outputs"]
    ] == [
        ("scores", "score.collection"),
    ]
    assert source_binding["produced_observations"] == ()
    assert len(scorer_binding["produced_observations"]) == 1
    produced = scorer_binding["produced_observations"][0]
    assert (
        produced["output_port"],
        produced["output_partition"],
        produced["subject_direction"],
        produced["subject_port"],
        produced["guaranteed_multiplicity"],
    ) == (
        "scores",
        "contract_test.partition.a",
        "input",
        "candidates",
        "one",
    )


@pytest.mark.parametrize(
    ("case_id", "candidate_counts", "observation_counts"),
    [
        ("collection-ops-concat-candidates", {"candidates": 2}, {}),
        ("collection-ops-merge-scores", {}, {"scores": 2}),
        ("collection-ops-concat-relations", {}, {}),
        ("collection-ops-relate-by-parent", {}, {}),
        ("collection-ops-relate-to-single-reference", {}, {}),
        ("collection-ops-compose-relations", {}, {}),
        ("collection-ops-invert-relation", {}, {}),
        ("collection-ops-join-relation-subjects", {}, {}),
        ("collection-ops-take-candidates", {"candidates": 1}, {}),
        ("collection-ops-select-related-subjects", {"candidates": 2}, {}),
        ("collection-ops-intersect-candidates", {"candidates": 1}, {}),
    ],
    ids=[
        "collection-ops-concat-candidates",
        "collection-ops-merge-scores",
        "collection-ops-concat-relations",
        "collection-ops-relate-by-parent",
        "collection-ops-relate-to-single-reference",
        "collection-ops-compose-relations",
        "collection-ops-invert-relation",
        "collection-ops-join-relation-subjects",
        "collection-ops-take-candidates",
        "collection-ops-select-related-subjects",
        "collection-ops-intersect-candidates",
    ],
)
def test_all_collection_nodes_pass_the_shared_contract_test_kit(
    tmp_path: Path,
    case_id: str,
    candidate_counts: dict[str, int],
    observation_counts: dict[str, int],
) -> None:
    from tests.fixtures.collection_ops_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    source_a = _source("a")
    source_b = _source("b")
    scorer_a = _scorer("a", "a")
    scorer_b = _scorer("b", "b")
    lineage_source = _lineage_source()
    parent_relation_node = WorkflowNodeInstance(
        node_id="parent-relation",
        node_type_id="collection_ops.relate_by_parent",
        binding_id="collection_ops.relate_by_parent.direct",
        node_parameters={},
        binding_parameters={},
    )
    case = {
        "collection-ops-concat-candidates": lambda: ModulePackageContractCase(
            case_id="collection-ops-concat-candidates",
            node_type_id="collection_ops.concat_candidates",
            binding_id="collection_ops.concat_candidates.direct",
            node_parameters={},
            binding_parameters={},
            environment_values={},
            workflow_nodes=(source_a, source_b),
            workflow_edges=(
                WorkflowEdge(
                    "source-a", "candidates", "contract-test-node", "candidates_a"
                ),
                WorkflowEdge(
                    "source-b", "candidates", "contract-test-node", "candidates_b"
                ),
            ),
        ),
        "collection-ops-merge-scores": lambda: ModulePackageContractCase(
            case_id="collection-ops-merge-scores",
            node_type_id="collection_ops.merge_scores",
            binding_id="collection_ops.merge_scores.direct",
            node_parameters={},
            binding_parameters={},
            environment_values={},
            workflow_nodes=(source_a, source_b, scorer_a, scorer_b),
            workflow_edges=(
                WorkflowEdge("source-a", "candidates", "scorer-a", "candidates"),
                WorkflowEdge("source-b", "candidates", "scorer-b", "candidates"),
                WorkflowEdge("scorer-a", "scores", "contract-test-node", "scores_a"),
                WorkflowEdge("scorer-b", "scores", "contract-test-node", "scores_b"),
            ),
        ),
        "collection-ops-concat-relations": lambda: ModulePackageContractCase(
            case_id="collection-ops-concat-relations",
            node_type_id="collection_ops.concat_relations",
            binding_id="collection_ops.concat_relations.direct",
            node_parameters={},
            binding_parameters={},
            environment_values={},
            workflow_nodes=(lineage_source,),
            workflow_edges=(
                WorkflowEdge(
                    "lineage-source",
                    "parent_pairing",
                    "contract-test-node",
                    "relation_a",
                ),
            ),
        ),
        "collection-ops-relate-by-parent": lambda: ModulePackageContractCase(
            case_id="collection-ops-relate-by-parent",
            node_type_id="collection_ops.relate_by_parent",
            binding_id="collection_ops.relate_by_parent.direct",
            node_parameters={},
            binding_parameters={},
            environment_values={},
            workflow_nodes=(lineage_source,),
            workflow_edges=(
                WorkflowEdge(
                    "lineage-source", "subjects", "contract-test-node", "subjects"
                ),
                WorkflowEdge(
                    "lineage-source", "parents", "contract-test-node", "parents"
                ),
            ),
        ),
        "collection-ops-relate-to-single-reference": lambda: ModulePackageContractCase(
            case_id="collection-ops-relate-to-single-reference",
            node_type_id="collection_ops.relate_to_single_reference",
            binding_id="collection_ops.relate_to_single_reference.direct",
            node_parameters={},
            binding_parameters={},
            environment_values={},
            workflow_nodes=(source_a, source_b),
            workflow_edges=(
                WorkflowEdge(
                    "source-a", "candidates", "contract-test-node", "subjects"
                ),
                WorkflowEdge(
                    "source-b", "candidates", "contract-test-node", "references"
                ),
            ),
        ),
        "collection-ops-compose-relations": lambda: ModulePackageContractCase(
            case_id="collection-ops-compose-relations",
            node_type_id="collection_ops.compose_relations",
            binding_id="collection_ops.compose_relations.direct",
            node_parameters={},
            binding_parameters={},
            environment_values={},
            workflow_nodes=(lineage_source, parent_relation_node),
            workflow_edges=(
                WorkflowEdge(
                    "lineage-source", "subjects", "parent-relation", "subjects"
                ),
                WorkflowEdge("lineage-source", "parents", "parent-relation", "parents"),
                WorkflowEdge(
                    "parent-relation", "relation", "contract-test-node", "left_relation"
                ),
                WorkflowEdge(
                    "lineage-source",
                    "parent_pairing",
                    "contract-test-node",
                    "right_relation",
                ),
            ),
        ),
        "collection-ops-invert-relation": lambda: ModulePackageContractCase(
            case_id="collection-ops-invert-relation",
            node_type_id="collection_ops.invert_relation",
            binding_id="collection_ops.invert_relation.direct",
            node_parameters={},
            binding_parameters={},
            environment_values={},
            workflow_nodes=(lineage_source,),
            workflow_edges=(
                WorkflowEdge(
                    "lineage-source", "parent_pairing", "contract-test-node", "relation"
                ),
            ),
        ),
        "collection-ops-join-relation-subjects": lambda: ModulePackageContractCase(
            case_id="collection-ops-join-relation-subjects",
            node_type_id="collection_ops.join_relation_subjects",
            binding_id="collection_ops.join_relation_subjects.direct",
            node_parameters={},
            binding_parameters={},
            environment_values={},
            workflow_nodes=(lineage_source,),
            workflow_edges=(
                WorkflowEdge(
                    "lineage-source",
                    "parent_pairing",
                    "contract-test-node",
                    "left_relation",
                ),
                WorkflowEdge(
                    "lineage-source",
                    "parent_pairing",
                    "contract-test-node",
                    "right_relation",
                ),
            ),
        ),
        "collection-ops-take-candidates": lambda: ModulePackageContractCase(
            case_id="collection-ops-take-candidates",
            node_type_id="collection_ops.take_candidates",
            binding_id="collection_ops.take_candidates.direct",
            node_parameters={"k": 1},
            binding_parameters={},
            environment_values={},
            workflow_nodes=(source_a,),
            workflow_edges=(
                WorkflowEdge(
                    "source-a", "candidates", "contract-test-node", "candidates"
                ),
            ),
        ),
        "collection-ops-select-related-subjects": lambda: ModulePackageContractCase(
            case_id="collection-ops-select-related-subjects",
            node_type_id="collection_ops.select_related_subjects",
            binding_id="collection_ops.select_related_subjects.direct",
            node_parameters={},
            binding_parameters={},
            environment_values={},
            workflow_nodes=(lineage_source,),
            workflow_edges=(
                WorkflowEdge(
                    "lineage-source", "parents", "contract-test-node", "subjects"
                ),
                WorkflowEdge(
                    "lineage-source",
                    "references",
                    "contract-test-node",
                    "selected_references",
                ),
                WorkflowEdge(
                    "lineage-source", "parent_pairing", "contract-test-node", "relation"
                ),
            ),
        ),
        "collection-ops-intersect-candidates": lambda: ModulePackageContractCase(
            case_id="collection-ops-intersect-candidates",
            node_type_id="collection_ops.intersect_candidates",
            binding_id="collection_ops.intersect_candidates.direct",
            node_parameters={},
            binding_parameters={},
            environment_values={},
            workflow_nodes=(source_a,),
            workflow_edges=(
                WorkflowEdge(
                    "source-a", "candidates", "contract-test-node", "candidates_a"
                ),
                WorkflowEdge(
                    "source-a", "candidates", "contract-test-node", "candidates_b"
                ),
            ),
        ),
    }[case_id]()
    result = execute_module_package_case(
        MODULE_PACKAGE,
        case,
        supporting_registrations=(SOURCE_PACKAGE,),
        work_root=tmp_path,
    )
    assert result.projection.status == "succeeded"
    assert result.publication.node_id == "contract-test-node"
    for port, expected_count in candidate_counts.items():
        (value,) = result.outputs[port]
        assert isinstance(value, CandidateCollection)
        assert len(value.items) == expected_count
        assert all(
            (
                candidate.candidate_id.startswith("candidate-")
                for candidate in value.items
            )
        )
    for port, expected_count in observation_counts.items():
        (value,) = result.outputs[port]
        assert isinstance(value, ScoreCollection)
        assert len(value.entries) == expected_count
        assert all((isinstance(entry, ScoreObservation) for entry in value.entries))


@pytest.mark.parametrize(
    (
        "subject_parent_ids",
        "include_surplus_parent",
        "expected_message",
    ),
    (
        (
            ["parent", "unexpected-parent"],
            False,
            "exactly one supplied parent",
        ),
        (["parent"], True, "do not cover every supplied parent"),
    ),
)
def test_relate_by_parent_rejects_nonexact_lineage_and_parent_sets(
    subject_parent_ids: list[str],
    include_surplus_parent: bool,
    expected_message: str,
) -> None:
    catalog = build_frozen_catalog(module_registrations())
    parents = [Candidate("parent", ProteinSequence("AA"))]
    if include_surplus_parent:
        parents.append(
            Candidate("surplus-parent", ProteinSequence("DD"))
        )
    inputs = {
        "subjects": CandidateCollection(
            "subjects",
            "protein.sequence",
            [
                Candidate(
                    "subject",
                    ProteinSequence("EE"),
                    subject_parent_ids,
                )
            ],
        ),
        "parents": CandidateCollection(
            "parents",
            "protein.sequence",
            parents,
        ),
    }

    with pytest.raises(ValueError, match=expected_message):
        build_operation(
            catalog,
            "collection_ops.relate_by_parent.direct",
            None).execute(operation_call(
            catalog=catalog,
            binding_id="collection_ops.relate_by_parent.direct",
            inputs=inputs,
            node_parameters={},
            binding_parameters={},
        ))


def _run_public_collection_workflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    operation: str,
    counts: tuple[int, int] = (2, 1),
    connected_partitions: tuple[str, ...] = ("a", "b"),
) -> tuple[object, object, dict[str, object], dict[str, object], tuple[dict, ...]]:
    from tests.fixtures.collection_ops_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    catalog = build_frozen_catalog((MODULE_PACKAGE, SOURCE_PACKAGE))
    roots = _application_roots(tmp_path, monkeypatch)
    collection_op = WorkflowNodeInstance(
        node_id="collection-op",
        node_type_id=f"collection_ops.{operation}",
        binding_id=f"collection_ops.{operation}.direct",
        node_parameters={},
        binding_parameters={},
    )
    if operation == "relate_by_parent":
        workflow_nodes = (
            _lineage_source(candidate_count=counts[0]),
            collection_op,
        )
        workflow_edges = (
            WorkflowEdge(
                "lineage-source",
                "subjects",
                "collection-op",
                "subjects",
            ),
            WorkflowEdge(
                "lineage-source",
                "parents",
                "collection-op",
                "parents",
            ),
        )
    elif operation == "merge_scores":
        workflow_nodes = (
            _source("a", candidate_count=counts[0]),
            _source("b", candidate_count=counts[1]),
            _scorer("a", "a"),
            _scorer("b", "b"),
            collection_op,
        )
        workflow_edges = (
            WorkflowEdge("source-a", "candidates", "scorer-a", "candidates"),
            WorkflowEdge("source-b", "candidates", "scorer-b", "candidates"),
            *(
                WorkflowEdge(
                    f"scorer-{partition}",
                    "scores",
                    "collection-op",
                    f"scores_{partition}",
                )
                for partition in connected_partitions
            ),
        )
    else:
        workflow_nodes = (
            _source("a", candidate_count=counts[0]),
            _source("b", candidate_count=counts[1]),
            collection_op,
        )
        workflow_edges = tuple(
            WorkflowEdge(
                f"source-{partition}",
                "candidates",
                "collection-op",
                f"candidates_{partition}",
            )
            for partition in connected_partitions
        )
    project_id = ProjectManager(root_dir=roots["PROJECT"]).create(
        f"collection operations {operation}"
    ).id
    app = create_application(frozen_catalog_override=catalog)
    with TestClient(app) as client:
        workflow = WorkflowDocument(
            schema_version=VERSION,
            workflow_id=project_id,
            nodes=workflow_nodes,
            edges=workflow_edges)
        committed = PublicRunClient(client).commit_workflow(
            project_id, encode_workflow_document(workflow)
        )
        _assert_workflow_commit_owner(
            app,
            project_id,
            source_draft_revision=1)

        def run(request_id: str) -> dict[str, object]:
            started = PublicRunClient(client).start_run(
                project_id, committed["workflow_commit_id"], request_id=request_id
            )
            return wait_for_testclient_run_terminal(
                client,
                project_id,
                started["run_id"],
            )

        first = run("collection-ops-first")
        second = run("collection-ops-second")
        with client.websocket_connect(
            f"/api/v2/projects/{project_id}/runs/"
            f"{second['run_id']}/events"
        ) as websocket:
            replay_messages: list[dict] = []
            try:
                while True:
                    replay_messages.append(websocket.receive_json())
            except WebSocketDisconnect as closed:
                assert closed.code == 1000
        replay_events = tuple(
            message
            for message in replay_messages
            if message["event"]["type"] not in {
                "replay_started",
                "replay_complete",
            }
        )
    return app.state.run_runtime, catalog, first, second, replay_events


def _decoded_outputs(
    service: object,
    catalog: object,
    projection: dict[str, object],
) -> dict[tuple[str, str], object]:
    return {
        (output["node_id"], output["output_port"]): (
            decode_service_typed_output_value(
                service,
                catalog,
                projection,
                output,
            )
        )
        for output in projection["outputs"]
    }


def test_public_relation_uses_exact_parent_identity_not_collection_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, catalog, first, _, _ = _run_public_collection_workflow(
        tmp_path,
        monkeypatch,
        operation="relate_by_parent",
        counts=(2, 1),
    )
    decoded = _decoded_outputs(service, catalog, first)
    subjects = decoded[("lineage-source", "subjects")]
    parents = decoded[("lineage-source", "parents")]
    relation = decoded[("collection-op", "relation")]

    assert type(subjects) is CandidateCollection
    assert type(parents) is CandidateCollection
    assert type(relation) is CandidateRelation
    assert [
        (
            entry.subject.candidate_id,
            entry.reference.candidate_id,
        )
        for entry in relation.entries
    ] == [
        (
            subject.candidate_id,
            subject.parent_ids[0],
        )
        for subject in subjects.items
    ]


def test_public_candidate_concatenation_preserves_exact_input_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, catalog, first, second, replay_events = (
        _run_public_collection_workflow(
            tmp_path,
            monkeypatch,
            operation="concat_candidates",
        )
    )
    assert first["status"] == second["status"] == "succeeded"
    first_values = _decoded_outputs(service, catalog, first)
    replay_values = _decoded_outputs(service, catalog, second)
    left = first_values[("source-a", "candidates")]
    right = first_values[("source-b", "candidates")]
    concatenated = first_values[("collection-op", "candidates")]

    assert concatenated.items == (*left.items, *right.items)
    assert [item.candidate_id for item in concatenated.items] == [
        *[item.candidate_id for item in left.items],
        *[item.candidate_id for item in right.items],
    ]
    assert concatenated.items[1].parent_ids == (
        concatenated.items[0].candidate_id,
    )
    assert [
        (
            item.metadata["producer_result_identity"],
            item.metadata["output_port"],
            item.metadata["sample_slot"],
            item.metadata["fixture_partition"],
        )
        for item in concatenated.items
    ] == [
        (
            item.metadata["producer_result_identity"],
            item.metadata["output_port"],
            item.metadata["sample_slot"],
            item.metadata["fixture_partition"],
        )
        for item in [*left.items, *right.items]
    ]
    assert replay_values[("collection-op", "candidates")] == concatenated
    assert all(
        disposition["resolution"] == "cache_replayed"
        for disposition in second["node_dispositions"]
    )
    assert not {
        "operation_attempt_started",
        "engine_invocation_started",
    }.intersection(
        event["event"]["type"] for event in replay_events
    )


def test_public_score_merge_preserves_observation_identity_and_partitions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, catalog, first, second, replay_events = (
        _run_public_collection_workflow(
            tmp_path,
            monkeypatch,
            operation="merge_scores",
        )
    )
    assert first["status"] == second["status"] == "succeeded"
    first_values = _decoded_outputs(service, catalog, first)
    replay_values = _decoded_outputs(service, catalog, second)
    left = first_values[("scorer-a", "scores")]
    right = first_values[("scorer-b", "scores")]
    merged = first_values[("collection-op", "scores")]
    source_candidates = (
        *first_values[("source-a", "candidates")].items,
        *first_values[("source-b", "candidates")].items,
    )
    sequence_port = catalog.require_port_type(
        "protein.sequence")
    expected_subjects = {
        candidate.candidate_id: CandidateDataReference(
            candidate_id=candidate.candidate_id,
            data_type_id="protein.sequence",
            content_digest=sequence_port.content_digest(candidate.data),
        )
        for candidate in source_candidates
    }

    assert merged.entries == (*left.entries, *right.entries)
    assert [entry.subject for entry in merged.entries] == [
        expected_subjects[entry.candidate_id]
        for entry in merged.entries
    ]
    assert [
        (
            entry.identity,
            entry.value,
            entry.source_partition,
            entry.candidate_id,
            entry.method,
            entry.context,
        )
        for entry in merged.entries
    ] == [
        (
            entry.identity,
            entry.value,
            entry.source_partition,
            entry.candidate_id,
            entry.method,
            entry.context,
        )
        for entry in [*left.entries, *right.entries]
    ]
    assert {
        entry.source_partition for entry in merged.entries
    } == {
        "contract_test.partition.a",
        "contract_test.partition.b",
    }
    assert replay_values[("collection-op", "scores")] == merged
    assert all(
        disposition["resolution"] == "cache_replayed"
        for disposition in second["node_dispositions"]
    )
    assert not {
        "operation_attempt_started",
        "engine_invocation_started",
    }.intersection(
        event["event"]["type"] for event in replay_events
    )


def test_public_optional_score_inputs_distinguish_empty_from_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, catalog, empty_first, empty_replay, _ = (
        _run_public_collection_workflow(
            tmp_path / "empty",
            monkeypatch,
            operation="merge_scores",
            counts=(0, 1),
            connected_partitions=("a",),
        )
    )
    assert empty_first["status"] == empty_replay["status"] == "succeeded"
    assert (
        _decoded_outputs(
            service,
            catalog,
            empty_first,
        )[("collection-op", "scores")].entries
        == ()
    )

    _, _, absent_first, absent_replay, _ = (
        _run_public_collection_workflow(
            tmp_path / "absent",
            monkeypatch,
            operation="merge_scores",
            connected_partitions=(),
        )
    )
    assert absent_first["status"] == absent_replay["status"] == "failed"
    assert not any(
        output["node_id"] == "collection-op"
        for output in absent_first["outputs"]
    )


def _commit_through_public_rest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    catalog: object,
    workflow: WorkflowDocument,
):
    roots = _application_roots(tmp_path, monkeypatch)
    project_id = ProjectManager(root_dir=roots["PROJECT"]).create(workflow.workflow_id).id
    app = create_application(frozen_catalog_override=catalog)
    with TestClient(app) as client:
        public_workflow = replace(
            workflow,
            workflow_id=project_id)
        response = client.post(
            f"/api/v2/projects/{project_id}/workflow:commit",
            json={
                "workflow": encode_workflow_document(public_workflow),
            },
        )
        if response.status_code == 200:
            _assert_workflow_commit_owner(
                app,
                project_id,
                source_draft_revision=1)
        return response


def _run_through_public_rest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    catalog: object,
    workflow: WorkflowDocument,
) -> tuple[object, dict, tuple[dict, ...]]:
    roots = _application_roots(tmp_path, monkeypatch)
    project_id = ProjectManager(root_dir=roots["PROJECT"]).create(workflow.workflow_id).id
    app = create_application(frozen_catalog_override=catalog)
    with TestClient(app) as client:
        public_workflow = replace(
            workflow,
            workflow_id=project_id)
        committed = PublicRunClient(client).commit_workflow(
            project_id, encode_workflow_document(public_workflow)
        )
        _assert_workflow_commit_owner(
            app,
            project_id,
            source_draft_revision=1)
        started = PublicRunClient(client).start_run(
            project_id,
            committed["workflow_commit_id"],
            request_id="collection-ops-failure-case",
        )
        run_id = started["run_id"]
        projection = wait_for_testclient_run_terminal(
            client,
            project_id,
            run_id,
        )
        with client.websocket_connect(
            f"/api/v2/projects/{project_id}/runs/{run_id}/events"
        ) as websocket:
            messages: list[dict] = []
            try:
                while True:
                    messages.append(websocket.receive_json())
            except WebSocketDisconnect as closed:
                assert closed.code == 1000
    events = tuple(
        message
        for message in messages
        if message["event"]["type"] not in {
            "replay_started",
            "replay_complete",
        }
    )
    return app.state.run_runtime, projection, events


def _scorer(partition: str, binding: str) -> WorkflowNodeInstance:
    return WorkflowNodeInstance(
        node_id=f"scorer-{partition}",
        node_type_id="contract_test.collection_ops_scorer",
        binding_id=f"contract_test.collection_ops_scorer.{binding}",
        node_parameters={},
        binding_parameters={},
    )


def _score_union_workflow(second_binding: str) -> WorkflowDocument:
    return WorkflowDocument(
        schema_version=VERSION,
        workflow_id=f"score-union-{second_binding}",
        nodes=(
            _source("a"),
            _scorer("left", "low"),
            _scorer("right", second_binding),
            WorkflowNodeInstance(
                node_id="merge",
                node_type_id="collection_ops.merge_scores",
                binding_id="collection_ops.merge_scores.direct",
                node_parameters={},
                binding_parameters={},
            ),
        ),
        edges=(
            WorkflowEdge(
                "source-a",
                "candidates",
                "scorer-left",
                "candidates",
            ),
            WorkflowEdge(
                "source-a",
                "candidates",
                "scorer-right",
                "candidates",
            ),
            WorkflowEdge("scorer-left", "scores", "merge", "scores_a"),
            WorkflowEdge("scorer-right", "scores", "merge", "scores_b"),
        ))


@pytest.mark.parametrize(
    ("second_binding", "expected_status"),
    (
        ("low", "succeeded"),
        ("high", "failed"),
        ("collision", "failed"),
    ),
)
def test_public_score_union_fails_closed_on_dynamic_contradictions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    second_binding: str,
    expected_status: str,
) -> None:
    from tests.fixtures.collection_ops_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    catalog = build_frozen_catalog((MODULE_PACKAGE, SOURCE_PACKAGE))
    service, projection, _ = _run_through_public_rest(
        tmp_path,
        monkeypatch,
        catalog=catalog,
        workflow=_score_union_workflow(second_binding),
    )

    assert projection["status"] == expected_status
    merged_outputs = [
        output
        for output in projection["outputs"]
        if output["node_id"] == "merge"
        and output["output_port"] == "scores"
    ]
    if second_binding == "low":
        assert len(merged_outputs) == 1
        merged = _decoded_outputs(service, catalog, projection)[
            ("merge", "scores")
        ]
        assert len(merged.entries) == 1
    else:
        assert merged_outputs == []


def test_public_collection_operations_reject_candidate_partition_aliasing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.fixtures.collection_ops_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    catalog = build_frozen_catalog((MODULE_PACKAGE, SOURCE_PACKAGE))
    workflow = WorkflowDocument(
        schema_version=VERSION,
        workflow_id="candidate-input-partition-alias",
        nodes=(
            _source("a"),
            WorkflowNodeInstance(
                node_id="concat",
                node_type_id="collection_ops.concat_candidates",
                binding_id="collection_ops.concat_candidates.direct",
                node_parameters={},
                binding_parameters={},
            ),
        ),
        edges=(
            WorkflowEdge(
                "source-a",
                "candidates",
                "concat",
                "candidates_a",
            ),
            WorkflowEdge(
                "source-a",
                "candidates",
                "concat",
                "candidates_b",
            ),
        ))

    _, projection, _ = _run_through_public_rest(
        tmp_path,
        monkeypatch,
        catalog=catalog,
        workflow=workflow,
    )

    assert projection["status"] == "failed"
    assert not any(
        output["node_id"] == "concat"
        for output in projection["outputs"]
    )


def test_public_score_merge_rejects_legacy_subject_free_scores(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.fixtures.collection_ops_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    catalog = build_frozen_catalog((MODULE_PACKAGE, SOURCE_PACKAGE))
    workflow = WorkflowDocument(
        schema_version=VERSION,
        workflow_id="legacy-score-rejection",
        nodes=(
            WorkflowNodeInstance(
                node_id="legacy",
                node_type_id="contract_test.collection_ops_legacy_scores",
                binding_id=(
                    "contract_test.collection_ops_legacy_scores.direct"
                ),
                node_parameters={},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="merge",
                node_type_id="collection_ops.merge_scores",
                binding_id="collection_ops.merge_scores.direct",
                node_parameters={},
                binding_parameters={},
            ),
        ),
        edges=(
            WorkflowEdge("legacy", "scores", "merge", "scores_a"),
        ))

    _, projection, _ = _run_through_public_rest(
        tmp_path,
        monkeypatch,
        catalog=catalog,
        workflow=workflow,
    )

    assert projection["status"] == "failed"
    assert not any(
        output["node_id"] == "merge"
        for output in projection["outputs"]
    )


def test_compiler_derives_exact_capabilities_through_score_union(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.fixtures.collection_ops_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    catalog = build_frozen_catalog(
        (MODULE_PACKAGE, SELECTION_PACKAGE, SOURCE_PACKAGE)
    )
    metric = ExactContractReference(
        **catalog.require_contract(
            "metric",
            "contract_test.collection_ops_value").reference()
    )
    method = ExactContractReference(
        **catalog.require_contract(
            "method",
            "contract_test.collection_ops_scorer.method").reference()
    )
    utility = ExactContractReference(
        **catalog.require_contract(
            "utility_transform",
            "contract_test.collection_ops_identity.a").reference()
    )
    source_a = _source("a")
    source_b = _source("b")
    scorer_a = _scorer("a", "a")
    scorer_b = _scorer("b", "b")
    merge = WorkflowNodeInstance(
        node_id="merge",
        node_type_id="collection_ops.merge_scores",
        binding_id="collection_ops.merge_scores.direct",
        node_parameters={},
        binding_parameters={},
    )
    select = WorkflowNodeInstance(
        node_id="select",
        node_type_id="selection.sort",
        binding_id="selection.sort.direct",
        node_parameters={"objective_id": "partition-a-only"},
        binding_parameters={},
    )
    workflow = WorkflowDocument(
        schema_version=VERSION,
        workflow_id="compile-collection-union",
        nodes=(source_a, source_b, scorer_a, scorer_b, merge, select),
        edges=(
            WorkflowEdge("source-a", "candidates", "scorer-a", "candidates"),
            WorkflowEdge("source-b", "candidates", "scorer-b", "candidates"),
            WorkflowEdge("scorer-a", "scores", "merge", "scores_a"),
            WorkflowEdge("scorer-b", "scores", "merge", "scores_b"),
            WorkflowEdge(
                "source-a",
                "candidates",
                "select",
                "candidates",
            ),
            WorkflowEdge("merge", "scores", "select", "scores"),
        ),
        selection_objectives=(
            SelectionObjective(
                objective_id="partition-a-only",
                candidate_input=SelectionInput(
                    "source-a",
                    "candidates",
                ),
                score_collection_input=SelectionInput("merge", "scores"),
                source_partition="contract_test.partition.a",
                metric=metric,
                method=method,
                context_selector=IntrinsicObservationContext(),
                utility_transform=utility,
                utility_parameters={},
                weight=1.0,
            ),
        ),
    )

    committed = _commit_through_public_rest(
        tmp_path / "accepted",
        monkeypatch,
        catalog=catalog,
        workflow=workflow,
    )

    assert committed.status_code == 200

    unknown_partition = replace(
        workflow,
        selection_objectives=(
            replace(
                workflow.selection_objectives[0],
                source_partition="contract_test.partition.unknown",
            ),
        ))
    rejected = _commit_through_public_rest(
        tmp_path / "unknown",
        monkeypatch,
        catalog=catalog,
        workflow=unknown_partition,
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "compile_rejected"
    assert rejected.json()["error"]["details"]["issues"][0]["code"] == (
        "unsatisfied_selection_objective"
    )


def test_compiler_rejects_multiple_collections_on_one_optional_port(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.fixtures.collection_ops_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    catalog = build_frozen_catalog((MODULE_PACKAGE, SOURCE_PACKAGE))
    workflow = WorkflowDocument(
        schema_version=VERSION,
        workflow_id="invalid-collection-multiplicity",
        nodes=(
            _source("a"),
            _source("b"),
            _scorer("a", "a"),
            _scorer("b", "b"),
            WorkflowNodeInstance(
                node_id="merge",
                node_type_id="collection_ops.merge_scores",
                binding_id="collection_ops.merge_scores.direct",
                node_parameters={},
                binding_parameters={},
            ),
        ),
        edges=(
            WorkflowEdge("source-a", "candidates", "scorer-a", "candidates"),
            WorkflowEdge("source-b", "candidates", "scorer-b", "candidates"),
            WorkflowEdge("scorer-a", "scores", "merge", "scores_a"),
            WorkflowEdge("scorer-b", "scores", "merge", "scores_a"),
        ))

    rejected = _commit_through_public_rest(
        tmp_path,
        monkeypatch,
        catalog=catalog,
        workflow=workflow,
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "compile_rejected"
    assert rejected.json()["error"]["details"]["issues"][0]["code"] == (
        "duplicate_input_connection"
    )


def test_compiler_rejects_a_malformed_optional_collection_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.fixtures.collection_ops_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    catalog = build_frozen_catalog((MODULE_PACKAGE, SOURCE_PACKAGE))
    workflow = WorkflowDocument(
        schema_version=VERSION,
        workflow_id="malformed-optional-score-input",
        nodes=(
            _source("a"),
            WorkflowNodeInstance(
                node_id="merge",
                node_type_id="collection_ops.merge_scores",
                binding_id="collection_ops.merge_scores.direct",
                node_parameters={},
                binding_parameters={},
            ),
        ),
        edges=(
            WorkflowEdge(
                "source-a",
                "candidates",
                "merge",
                "scores_a",
            ),
        ))

    rejected = _commit_through_public_rest(
        tmp_path,
        monkeypatch,
        catalog=catalog,
        workflow=workflow,
    )

    assert rejected.status_code == 422
    assert rejected.json()["error"]["details"]["issues"][0]["code"] == (
        "port_type_mismatch"
    )
