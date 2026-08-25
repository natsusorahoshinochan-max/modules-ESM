"""Public v2 contracts for partition-preserving collection operations."""

from __future__ import annotations

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
from tests.support.contract_test_kit import (
    ModulePackageContractCase,
    verify_module_package_contract,
)
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
    PairwiseCandidateMapping,
    PairwiseCandidateMatch,
    ScoreCollection,
    ScoreObservation,
)
from datatypes.sequence import ProteinSequence
from modules.collection_ops.package import MODULE_PACKAGE
from modules.selection.package import MODULE_PACKAGE as SELECTION_PACKAGE
from tests.fixtures.public_v2 import (
    decode_service_typed_output_value,
    wait_for_testclient_run_terminal,
)
from tests.fixtures.scientific_operation import (
    admitted_port_fixture,
    build_operation,
    operation_call,
)
from modules.collection_ops.implementation import CollectionOpsImplementation


VERSION = "2.1.0"
CANDIDATE_NODE_VERSION = "4.0.0"
SCORE_NODE_VERSION = "5.0.0"
PAIRING_METHOD_VERSION = "3.0.0"
SOURCE_NODE_VERSION = CANDIDATE_NODE_VERSION
SCORER_NODE_VERSION = SCORE_NODE_VERSION


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
    parents = CandidateCollection(
        "passing-parents",
        "protein.sequence",
        (Candidate("parent-a", ProteinSequence("AAAA")),),
    )
    children = CandidateCollection(
        "children",
        "protein.sequence",
        (
            Candidate("child-a", ProteinSequence("AAAA"), ("parent-a",)),
            Candidate("child-b", ProteinSequence("AAAA"), ("parent-b",)),
        ),
    )
    selected = CollectionOpsImplementation("select_children_by_parent").execute(
        OperationCall(
            inputs={
                name: admitted_port_fixture(
                    value,
                    port_type_id="candidate.collection",
                    value_content_digests=("sha256:" + digit * 64,),
                )
                for name, value, digit in (
                    ("candidates", children, "a"),
                    ("parents", parents, "b"),
                )
            },
            node_parameters={},
            binding_parameters={},
            effective_randomness={},
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


def test_score_merge_preserves_exact_i_json_value_types() -> None:
    from tests.fixtures.collection_ops_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    catalog = build_frozen_catalog((MODULE_PACKAGE, SOURCE_PACKAGE))
    metric = ExactContractReference(
        **catalog.require_contract(
            "metric",
            "contract_test.collection_ops_value",
            VERSION,
        ).reference()
    )
    method = ExactContractReference(
        **catalog.require_contract(
            "method",
            "contract_test.collection_ops_scorer.method",
            VERSION,
        ).reference()
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
        binding_version=SCORE_NODE_VERSION,
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


def _assert_workflow_commit_owner(
    app: FastAPI,
    project_id: str,
    *,
    source_draft_revision: int,
    workflow_commit_revision: int,
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
    assert commit.source_draft_digest == draft.draft_digest
    assert commit.workflow_commit_revision == workflow_commit_revision
    assert plan.workflow_commit_revision == commit.workflow_commit_revision
    assert plan.workflow_digest == commit.workflow_digest
    assert plan.catalog_contract_digest == commit.catalog_contract_digest
    assert plan.contract_lock_digest == commit.contract_lock_digest
    assert plan.execution_plan_digest == commit.execution_plan_digest
    assert commit.workflow_commit_id == plan.execution_plan_digest.replace(
        "sha256:",
        "workflow-commit-",
    )


def _source(
    partition: str,
    *,
    candidate_count: int = 1,
) -> WorkflowNodeInstance:
    return WorkflowNodeInstance(
        node_id=f"source-{partition}",
        node_type_id="contract_test.collection_ops_source",
        node_type_version=SOURCE_NODE_VERSION,
        binding_id=f"contract_test.collection_ops_source.{partition}",
        binding_version=SOURCE_NODE_VERSION,
        node_parameters={"candidate_count": candidate_count},
        binding_parameters={},
    )


def _lineage_source(*, candidate_count: int = 2) -> WorkflowNodeInstance:
    return WorkflowNodeInstance(
        node_id="lineage-source",
        node_type_id="contract_test.collection_ops_lineage_source",
        node_type_version=CANDIDATE_NODE_VERSION,
        binding_id="contract_test.collection_ops_lineage_source.direct",
        binding_version=CANDIDATE_NODE_VERSION,
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

    assert set(contracts) == {
        ("binding", "collection_ops.concat_candidates.direct"),
        ("binding", "collection_ops.concat_pairings.direct"),
        ("binding", "collection_ops.merge_scores.direct"),
        ("binding", "collection_ops.pair_siblings_by_parent.direct"),
        ("binding", "collection_ops.rebind_candidate_pairing.direct"),
        ("binding", "collection_ops.take_candidates.direct"),
        ("binding", "collection_ops.intersect_candidates.direct"),
        ("binding", "collection_ops.select_children_by_parent.direct"),
        ("method", "collection_ops.concat_candidates.method"),
        ("method", "collection_ops.concat_pairings.method"),
        ("method", "collection_ops.merge_scores.method"),
        ("method", "collection_ops.pair_siblings_by_parent.method"),
        ("method", "collection_ops.rebind_candidate_pairing.method"),
        ("method", "collection_ops.take_candidates.method"),
        ("method", "collection_ops.intersect_candidates.method"),
        ("method", "collection_ops.select_children_by_parent.method"),
        ("node_type", "collection_ops.concat_candidates"),
        ("node_type", "collection_ops.concat_pairings"),
        ("node_type", "collection_ops.merge_scores"),
        ("node_type", "collection_ops.pair_siblings_by_parent"),
        ("node_type", "collection_ops.rebind_candidate_pairing"),
        ("node_type", "collection_ops.take_candidates"),
        ("node_type", "collection_ops.intersect_candidates"),
        ("node_type", "collection_ops.select_children_by_parent"),
    }
    assert not any(
        "aggregate" in contract_id for _, contract_id in contracts
    )
    for operation in (
        "concat_pairings",
        "pair_siblings_by_parent",
        "rebind_candidate_pairing",
    ):
        method = contracts[("method", f"collection_ops.{operation}.method")]
        assert method["contract_version"] == PAIRING_METHOD_VERSION
        assert method["algorithm_identity"]["pairing_contract"] == {
            "participant_identity": "CandidateDataReference",
            "join": "complete-reference-equality",
            "cardinality": "one-to-one",
        }
        binding = contracts[("binding", f"collection_ops.{operation}.direct")]
        assert binding["method"]["contract_version"] == (
            PAIRING_METHOD_VERSION
        )


def test_collection_ports_and_score_union_are_closed_and_versioned() -> None:
    contracts = _public_collection_contracts()
    candidates = contracts[
        ("node_type", "collection_ops.concat_candidates")
    ]
    scores = contracts[("node_type", "collection_ops.merge_scores")]
    score_binding = contracts[
        ("binding", "collection_ops.merge_scores.direct")
    ]

    candidate_only_operations = {
        "concat_candidates",
        "concat_pairings",
        "pair_siblings_by_parent",
        "rebind_candidate_pairing",
        "take_candidates",
        "intersect_candidates",
        "select_children_by_parent",
    }
    for operation in candidate_only_operations:
        node = contracts[("node_type", f"collection_ops.{operation}")]
        binding = contracts[
            ("binding", f"collection_ops.{operation}.direct")
        ]
        assert node["contract_version"] == CANDIDATE_NODE_VERSION
        assert binding["contract_version"] == CANDIDATE_NODE_VERSION
        assert binding["node_type"]["contract_version"] == (
            CANDIDATE_NODE_VERSION
        )

    assert scores["contract_version"] == SCORE_NODE_VERSION
    assert score_binding["contract_version"] == SCORE_NODE_VERSION
    assert score_binding["node_type"]["contract_version"] == (
        SCORE_NODE_VERSION
    )

    for (contract_kind, _), descriptor in contracts.items():
        if contract_kind != "node_type":
            continue
        for port in (*descriptor["inputs"], *descriptor["outputs"]):
            port_type = port["port_type"]
            if port_type["contract_id"] in {
                "candidate.collection",
                "candidate.pairing",
            }:
                assert port_type["contract_version"] == (
                    CANDIDATE_NODE_VERSION
                )
            elif port_type["contract_id"] == "score.collection":
                assert port_type["contract_version"] == SCORE_NODE_VERSION

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
        "schema_version": VERSION,
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
        "contract_test.collection_ops_source",
        SOURCE_NODE_VERSION,
    ).descriptor
    scorer = catalog.require_contract(
        "node_type",
        "contract_test.collection_ops_scorer",
        SCORER_NODE_VERSION,
    ).descriptor
    source_binding = catalog.require_contract(
        "binding",
        "contract_test.collection_ops_source.a",
        SOURCE_NODE_VERSION,
    ).descriptor
    scorer_binding = catalog.require_contract(
        "binding",
        "contract_test.collection_ops_scorer.a",
        SCORER_NODE_VERSION,
    ).descriptor

    assert source["inputs"] == ()
    assert [
        (
            port["name"],
            port["port_type"]["contract_id"],
            port["port_type"]["contract_version"],
        )
        for port in source["outputs"]
    ] == [
        ("candidates", "candidate.collection", CANDIDATE_NODE_VERSION),
    ]
    assert [
        (
            port["name"],
            port["port_type"]["contract_id"],
            port["port_type"]["contract_version"],
        )
        for port in scorer["inputs"]
    ] == [
        ("candidates", "candidate.collection", CANDIDATE_NODE_VERSION),
    ]
    assert [
        (
            port["name"],
            port["port_type"]["contract_id"],
            port["port_type"]["contract_version"],
        )
        for port in scorer["outputs"]
    ] == [
        ("scores", "score.collection", SCORE_NODE_VERSION),
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


def test_all_collection_nodes_pass_the_shared_contract_test_kit(
    tmp_path: Path,
) -> None:
    from tests.fixtures.collection_ops_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    source_a = _source("a")
    source_b = _source("b")
    scorer_a = _scorer("a", "a")
    scorer_b = _scorer("b", "b")
    lineage_source = _lineage_source()
    candidate_case = ModulePackageContractCase(
        case_id="collection-ops-concat-candidates",
        node_type_id="collection_ops.concat_candidates",
        node_type_version=CANDIDATE_NODE_VERSION,
        binding_id="collection_ops.concat_candidates.direct",
        binding_version=CANDIDATE_NODE_VERSION,
        node_parameters={},
        binding_parameters={},
        environment_values={},
        workflow_nodes=(source_a, source_b),
        workflow_edges=(
            WorkflowEdge(
                "source-a",
                "candidates",
                "contract-test-node",
                "candidates_a",
            ),
            WorkflowEdge(
                "source-b",
                "candidates",
                "contract-test-node",
                "candidates_b",
            ),
        ),
        expected_candidate_counts={"candidates": 2},
    )
    score_case = ModulePackageContractCase(
        case_id="collection-ops-merge-scores",
        node_type_id="collection_ops.merge_scores",
        node_type_version=SCORE_NODE_VERSION,
        binding_id="collection_ops.merge_scores.direct",
        binding_version=SCORE_NODE_VERSION,
        node_parameters={},
        binding_parameters={},
        environment_values={},
        workflow_nodes=(source_a, source_b, scorer_a, scorer_b),
        workflow_edges=(
            WorkflowEdge(
                "source-a",
                "candidates",
                "scorer-a",
                "candidates",
            ),
            WorkflowEdge(
                "source-b",
                "candidates",
                "scorer-b",
                "candidates",
            ),
            WorkflowEdge(
                "scorer-a",
                "scores",
                "contract-test-node",
                "scores_a",
            ),
            WorkflowEdge(
                "scorer-b",
                "scores",
                "contract-test-node",
                "scores_b",
            ),
        ),
        expected_observation_counts={"scores": 2},
    )
    take_case = ModulePackageContractCase(
        case_id="collection-ops-take-candidates",
        node_type_id="collection_ops.take_candidates",
        node_type_version=CANDIDATE_NODE_VERSION,
        binding_id="collection_ops.take_candidates.direct",
        binding_version=CANDIDATE_NODE_VERSION,
        node_parameters={"k": 1},
        binding_parameters={},
        environment_values={},
        workflow_nodes=(source_a,),
        workflow_edges=(
            WorkflowEdge(
                "source-a",
                "candidates",
                "contract-test-node",
                "candidates",
            ),
        ),
        expected_candidate_counts={"candidates": 1},
    )
    rebind_case = ModulePackageContractCase(
        case_id="collection-ops-rebind-candidate-pairing",
        node_type_id="collection_ops.rebind_candidate_pairing",
        node_type_version=CANDIDATE_NODE_VERSION,
        binding_id="collection_ops.rebind_candidate_pairing.direct",
        binding_version=CANDIDATE_NODE_VERSION,
        node_parameters={},
        binding_parameters={},
        environment_values={},
        workflow_nodes=(lineage_source,),
        workflow_edges=(
            WorkflowEdge(
                "lineage-source",
                "subjects",
                "contract-test-node",
                "subjects",
            ),
            WorkflowEdge(
                "lineage-source",
                "parents",
                "contract-test-node",
                "parents",
            ),
            WorkflowEdge(
                "lineage-source",
                "references",
                "contract-test-node",
                "references",
            ),
            WorkflowEdge(
                "lineage-source",
                "parent_pairing",
                "contract-test-node",
                "parent_pairing",
            ),
        ),
    )
    concat_pairings_case = ModulePackageContractCase(
        case_id="collection-ops-concat-pairings",
        node_type_id="collection_ops.concat_pairings",
        node_type_version=CANDIDATE_NODE_VERSION,
        binding_id="collection_ops.concat_pairings.direct",
        binding_version=CANDIDATE_NODE_VERSION,
        node_parameters={},
        binding_parameters={},
        environment_values={},
        workflow_nodes=(lineage_source,),
        workflow_edges=(
            WorkflowEdge(
                "lineage-source",
                "parent_pairing",
                "contract-test-node",
                "pairing_a",
            ),
        ),
    )
    pair_case = ModulePackageContractCase(
        case_id="collection-ops-pair-siblings-by-parent",
        node_type_id="collection_ops.pair_siblings_by_parent",
        node_type_version=CANDIDATE_NODE_VERSION,
        binding_id="collection_ops.pair_siblings_by_parent.direct",
        binding_version=CANDIDATE_NODE_VERSION,
        node_parameters={},
        binding_parameters={},
        environment_values={},
        workflow_nodes=(lineage_source,),
        workflow_edges=(
            WorkflowEdge(
                "lineage-source",
                "subjects",
                "contract-test-node",
                "subjects",
            ),
            WorkflowEdge(
                "lineage-source",
                "references",
                "contract-test-node",
                "references",
            ),
        ),
    )
    select_children_case = ModulePackageContractCase(
        case_id="collection-ops-select-children-by-parent",
        node_type_id="collection_ops.select_children_by_parent",
        node_type_version=CANDIDATE_NODE_VERSION,
        binding_id="collection_ops.select_children_by_parent.direct",
        binding_version=CANDIDATE_NODE_VERSION,
        node_parameters={},
        binding_parameters={},
        environment_values={},
        workflow_nodes=(lineage_source,),
        workflow_edges=(
            WorkflowEdge(
                "lineage-source",
                "subjects",
                "contract-test-node",
                "candidates",
            ),
            WorkflowEdge(
                "lineage-source",
                "parents",
                "contract-test-node",
                "parents",
            ),
        ),
        expected_candidate_counts={"candidates": 2},
    )
    intersect_case = ModulePackageContractCase(
        case_id="collection-ops-intersect-candidates",
        node_type_id="collection_ops.intersect_candidates",
        node_type_version=CANDIDATE_NODE_VERSION,
        binding_id="collection_ops.intersect_candidates.direct",
        binding_version=CANDIDATE_NODE_VERSION,
        node_parameters={},
        binding_parameters={},
        environment_values={},
        workflow_nodes=(source_a,),
        workflow_edges=(
            WorkflowEdge(
                "source-a",
                "candidates",
                "contract-test-node",
                "candidates_a",
            ),
            WorkflowEdge(
                "source-a",
                "candidates",
                "contract-test-node",
                "candidates_b",
            ),
        ),
        expected_candidate_counts={"candidates": 1},
    )

    report = verify_module_package_contract(
        MODULE_PACKAGE,
        execution_cases=(
            candidate_case,
            score_case,
            concat_pairings_case,
            pair_case,
            rebind_case,
            take_case,
            select_children_case,
            intersect_case,
        ),
        supporting_registrations=(SOURCE_PACKAGE,),
        work_root=tmp_path,
    )

    assert [case.status for case in report.case_reports] == [
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
    ]


@pytest.mark.parametrize(
    (
        "subject_parent_ids",
        "include_surplus_reference",
        "expected_message",
    ),
    (
        (
            ["parent", "unexpected-parent"],
            False,
            "exactly one total parent",
        ),
        (["parent"], True, "not complete for all references"),
    ),
)
def test_pairing_rebinding_rejects_nonexact_lineage_and_reference_sets(
    subject_parent_ids: list[str],
    include_surplus_reference: bool,
    expected_message: str,
) -> None:
    catalog = build_frozen_catalog(module_registrations())
    sequence_codec = catalog.require_port_type("protein.sequence", "3.0.0")
    parent_data = ProteinSequence("AA")
    reference_data = ProteinSequence("CC")
    parent = Candidate("parent", parent_data)
    reference = Candidate("reference", reference_data)
    references = [reference]
    if include_surplus_reference:
        references.append(
            Candidate("surplus-reference", ProteinSequence("DD"))
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
            [parent],
        ),
        "references": CandidateCollection(
            "references",
            "protein.sequence",
            references,
        ),
        "parent_pairing": PairwiseCandidateMapping([
            PairwiseCandidateMatch(
                subject=CandidateDataReference(
                    candidate_id=parent.candidate_id,
                    data_type_id="protein.sequence",
                    content_digest=sequence_codec.content_digest(parent_data),
                ),
                reference=CandidateDataReference(
                    candidate_id=reference.candidate_id,
                    data_type_id="protein.sequence",
                    content_digest=sequence_codec.content_digest(
                        reference_data
                    ),
                ),
            )
        ]),
    }

    with pytest.raises(ValueError, match=expected_message):
        build_operation(
            catalog,
            "collection_ops.rebind_candidate_pairing.direct",
            None,
            binding_version=CANDIDATE_NODE_VERSION,
        ).execute(operation_call(
            catalog=catalog,
            binding_id="collection_ops.rebind_candidate_pairing.direct",
            binding_version=CANDIDATE_NODE_VERSION,
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
    operation_version = (
        SCORE_NODE_VERSION
        if operation == "merge_scores"
        else CANDIDATE_NODE_VERSION
    )
    collection_op = WorkflowNodeInstance(
        node_id="collection-op",
        node_type_id=f"collection_ops.{operation}",
        node_type_version=operation_version,
        binding_id=f"collection_ops.{operation}.direct",
        binding_version=operation_version,
        node_parameters={},
        binding_parameters={},
    )
    if operation == "pair_siblings_by_parent":
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
                "references",
                "collection-op",
                "references",
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
            edges=workflow_edges,
            contract_lock=(),
        )
        committed = client.post(
            f"/api/v2/projects/{project_id}/workflow:commit",
            json={
                "workflow": encode_workflow_document(workflow),
            },
        )
        assert committed.status_code == 200
        _assert_workflow_commit_owner(
            app,
            project_id,
            source_draft_revision=1,
            workflow_commit_revision=1,
        )

        def run(request_id: str) -> dict[str, object]:
            started = client.post(
                f"/api/v2/projects/{project_id}/runs",
                json={
                    "workflow_commit_id": committed.json()[
                        "workflow_commit_id"
                    ],
                    "client_request_id": request_id,
                },
            )
            assert started.status_code == 202
            return wait_for_testclient_run_terminal(
                client,
                project_id,
                started.json()["run_id"],
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


def test_public_pairing_uses_common_parent_not_collection_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, catalog, first, _, _ = _run_public_collection_workflow(
        tmp_path,
        monkeypatch,
        operation="pair_siblings_by_parent",
        counts=(2, 1),
    )
    decoded = _decoded_outputs(service, catalog, first)
    subjects = decoded[("lineage-source", "subjects")]
    references = decoded[("lineage-source", "references")]
    pairing = decoded[("collection-op", "pairing")]

    assert type(subjects) is CandidateCollection
    assert type(references) is CandidateCollection
    assert type(pairing) is PairwiseCandidateMapping
    reference_by_parent = {
        reference.parent_ids[0]: reference.candidate_id
        for reference in reversed(references.items)
    }
    assert [
        (
            entry.subject.candidate_id,
            entry.reference.candidate_id,
        )
        for entry in pairing.entries
    ] == [
        (
            subject.candidate_id,
            reference_by_parent[subject.parent_ids[0]],
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
        "protein.sequence",
        "3.0.0",
    )
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
            workflow_id=project_id,
            contract_lock=(),
        )
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
                source_draft_revision=1,
                workflow_commit_revision=1,
            )
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
            workflow_id=project_id,
            contract_lock=(),
        )
        committed = client.post(
            f"/api/v2/projects/{project_id}/workflow:commit",
            json={
                "workflow": encode_workflow_document(public_workflow),
            },
        )
        assert committed.status_code == 200
        _assert_workflow_commit_owner(
            app,
            project_id,
            source_draft_revision=1,
            workflow_commit_revision=1,
        )
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": committed.json()[
                    "workflow_commit_id"
                ],
                "client_request_id": "collection-ops-failure-case",
            },
        )
        assert started.status_code == 202
        run_id = started.json()["run_id"]
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
        node_type_version=SCORER_NODE_VERSION,
        binding_id=f"contract_test.collection_ops_scorer.{binding}",
        binding_version=SCORER_NODE_VERSION,
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
                node_type_version=SCORE_NODE_VERSION,
                binding_id="collection_ops.merge_scores.direct",
                binding_version=SCORE_NODE_VERSION,
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
        ),
        contract_lock=(),
    )


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
                node_type_version=CANDIDATE_NODE_VERSION,
                binding_id="collection_ops.concat_candidates.direct",
                binding_version=CANDIDATE_NODE_VERSION,
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
        ),
        contract_lock=(),
    )

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
                node_type_version=SCORE_NODE_VERSION,
                binding_id=(
                    "contract_test.collection_ops_legacy_scores.direct"
                ),
                binding_version=SCORE_NODE_VERSION,
                node_parameters={},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="merge",
                node_type_id="collection_ops.merge_scores",
                node_type_version=SCORE_NODE_VERSION,
                binding_id="collection_ops.merge_scores.direct",
                binding_version=SCORE_NODE_VERSION,
                node_parameters={},
                binding_parameters={},
            ),
        ),
        edges=(
            WorkflowEdge("legacy", "scores", "merge", "scores_a"),
        ),
        contract_lock=(),
    )

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
            "contract_test.collection_ops_value",
            VERSION,
        ).reference()
    )
    method = ExactContractReference(
        **catalog.require_contract(
            "method",
            "contract_test.collection_ops_scorer.method",
            VERSION,
        ).reference()
    )
    utility = ExactContractReference(
        **catalog.require_contract(
            "utility_transform",
            "contract_test.collection_ops_identity.a",
            VERSION,
        ).reference()
    )
    source_a = _source("a")
    source_b = _source("b")
    scorer_a = _scorer("a", "a")
    scorer_b = _scorer("b", "b")
    merge = WorkflowNodeInstance(
        node_id="merge",
        node_type_id="collection_ops.merge_scores",
        node_type_version=SCORE_NODE_VERSION,
        binding_id="collection_ops.merge_scores.direct",
        binding_version=SCORE_NODE_VERSION,
        node_parameters={},
        binding_parameters={},
    )
    select = WorkflowNodeInstance(
        node_id="select",
        node_type_id="selection.sort",
        node_type_version=SCORE_NODE_VERSION,
        binding_id="selection.sort.direct",
        binding_version=SCORE_NODE_VERSION,
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
        contract_lock=(),
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
        ),
        contract_lock=(),
    )
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
                node_type_version=SCORE_NODE_VERSION,
                binding_id="collection_ops.merge_scores.direct",
                binding_version=SCORE_NODE_VERSION,
                node_parameters={},
                binding_parameters={},
            ),
        ),
        edges=(
            WorkflowEdge("source-a", "candidates", "scorer-a", "candidates"),
            WorkflowEdge("source-b", "candidates", "scorer-b", "candidates"),
            WorkflowEdge("scorer-a", "scores", "merge", "scores_a"),
            WorkflowEdge("scorer-b", "scores", "merge", "scores_a"),
        ),
        contract_lock=(),
    )

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
                node_type_version=SCORE_NODE_VERSION,
                binding_id="collection_ops.merge_scores.direct",
                binding_version=SCORE_NODE_VERSION,
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
        ),
        contract_lock=(),
    )

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
