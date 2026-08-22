"""Public-projection acceptance for Result Identity and the v2 Cache."""

from __future__ import annotations

from tests.support.ledger import public_run_events

from datetime import datetime, timezone
import json
from typing import Any

from fastapi.testclient import TestClient
import pytest

from core.catalog.builtins import (
    builtin_frozen_catalog,
)
from core.catalog.declarations import (
    EffectiveRandomnessResolver,
    EnvironmentFieldDeclaration,
    ReadinessDeclaration,
    ScientificOperationFactory,
)
from core.catalog.model import (
    FrozenCatalog,
)
from core.catalog.port_contract import (
    BehaviorReference,
    canonical_sha256,
)
from core.operation import (
    OperationCall,
    OperationContext,
    ReadinessResult,
)
from core.execution.node_attempt import (
    ExecutionTermination,
    result_contract_metadata,
    result_identity_descriptor,
)
from core.execution.results import ProjectReplayIndex
from protein_workbench_public.bootstrap import create_application
from datatypes.candidate import (
    Candidate,
    CandidateCollection,
)
from datatypes.sequence import ProteinSequence
from tests.fixtures.public_v2 import (
    retrieve_typed_output_values,
    wait_for_testclient_run_terminal,
)
from tests.test_run_runtime import (
    _artifact_catalog,
    _commit_artifact_node,
    _commit_one_node,
    _commit_pipeline,
    _commit_public_workflow,
    _contract,
    _direct_catalog,
    _pipeline_catalog,
)
from core.execution._run_runtime_evidence import plan_evidence


def _start_run(
    client: TestClient,
    project_id: str,
    compiled: dict[str, object],
    request_id: str,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    started = client.post(
        f"/api/v2/projects/{project_id}/runs",
        json={
            "workflow_commit_id": compiled["workflow_commit_id"],
            "client_request_id": request_id,
        },
    )
    assert started.status_code == 202
    run_id = started.json()["run_id"]
    projection = wait_for_testclient_run_terminal(client, project_id, run_id)
    events = public_run_events(
        client.app.state.run_runtime,
        project_id,
        run_id,
    )
    return projection, events


def test_one_plan_facts_projection_drives_identity_cache_and_ledger(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        monkeypatch.setenv(
            f"PROTEIN_WORKBENCH_{name}_ROOT",
            str(tmp_path / name.lower()),
        )
    app = create_application(frozen_catalog_override=_direct_catalog([]))

    with TestClient(app) as client:
        project_id, committed = _commit_one_node(client)
        compiled = app.state.workflow_authoring.require_verified_commit(
            project_id,
            workflow_commit_id=committed["workflow_commit_id"],
        )
        plan = compiled.execution_plan
        node = plan.nodes[0]
        plan_facts = node.result_identity_plan_facts
        facts_type = type(plan_facts)
        original_projection = facts_type.canonical_projection
        expected_projection = {
            **original_projection(plan_facts),
            "projection_probe": "shared-compiler-owned-projection",
        }
        observed_calls: list[object] = []

        def canonical_projection(self) -> dict[str, Any]:
            if self is plan_facts:
                observed_calls.append(self)
                return expected_projection
            return original_projection(self)

        monkeypatch.setattr(
            facts_type,
            "canonical_projection",
            canonical_projection,
        )
        descriptor = result_identity_descriptor(
            node,
            {},
        )
        cache_metadata = result_contract_metadata(node)
        ledger_plan_facts = plan_evidence(plan)[0]

    assert descriptor["result_identity_plan_facts"] == expected_projection
    assert cache_metadata == {
        "result_identity_plan_facts": expected_projection,
    }
    assert ledger_plan_facts.result_identity_plan_facts_digest == (
        canonical_sha256(expected_projection)
    )
    assert observed_calls == [plan_facts, plan_facts, plan_facts]


@pytest.mark.parametrize(
    "parameter_name",
    ("seed", "random_seed", "effective_seed"),
)
def test_undeclared_seed_like_parameter_remains_a_normalized_parameter(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    parameter_name: str,
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        monkeypatch.setenv(
            f"PROTEIN_WORKBENCH_{name}_ROOT",
            str(tmp_path / name.lower()),
        )
    catalog = _direct_catalog(
        [],
        node_parameter_declarations={
            parameter_name: {
                "parameter_scope": "scientific",
                "scientific_meaning": "Ordinary configured parameter.",
                "value_contract": {"type": "integer"},
                "default": 17,
            }
        },
    )
    app = create_application(frozen_catalog_override=catalog)

    with TestClient(app) as client:
        project_id, committed = _commit_one_node(client)
        compiled = app.state.workflow_authoring.require_verified_commit(
            project_id,
            workflow_commit_id=committed["workflow_commit_id"],
        )
        descriptor = result_identity_descriptor(
            compiled.execution_plan.nodes[0],
            {},
        )

    assert descriptor["node_parameters"] == {parameter_name: 17}
    assert descriptor["determinism"]["effective_randomness"] == {}


def _candidate_catalog(
    calls: list[str],
    *,
    duplicate_output_ids: bool = False,
    declare_root_node_as_parent: bool = False,
) -> FrozenCatalog:
    builtin = builtin_frozen_catalog()
    candidates = builtin.require_port_type("candidate.collection", "4.0.0")
    method = _contract(
        "method",
        "test.candidate.method",
        {
            "algorithm_identity": {"name": "stable-candidate"},
            "model_identity": {"kind": "none"},
            "checkpoint_identity": {"kind": "none"},
            "featurization_identity": {"kind": "none"},
            "source_identity": {"kind": "contract-test"},
            "scale_contract": {"kind": "identity"},
        },
    )
    node = _contract(
        "node_type",
        "test.candidate",
        {
            "title": "Candidate producer",
            "summary": "Produces one deterministic sequence Candidate.",
            "category": "contract_test",
            "inputs": [],
            "outputs": [
                {
                    "name": "candidates",
                    "port_type": candidates.reference(),
                    "required": True,
                    "multiplicity": "one",
                    "scientific_meaning": "One generated protein sequence",
                }
            ],
            "parameter_groups": [],
            "node_parameters": {},
        },
    )
    factory_behavior = BehaviorReference(
        "test.candidate/factory",
        "2.1.0",
        {},
    )
    readiness_behavior = BehaviorReference(
        "test.candidate/readiness",
        "2.1.0",
        {},
    )
    binding = _contract(
        "binding",
        "test.candidate.direct",
        {
            "node_type": node.reference(),
            "method": method.reference(),
            "binding_parameters": {},
            "execution_route": "direct",
            "route_behavior": factory_behavior.descriptor(),
            "availability_declaration": {
                "behavior": {
                    "behavior_id": "test.candidate/availability",
                    "behavior_version": "2.1.0",
                    "parameters": {},
                },
                "prerequisites": {},
            },
            "readiness_declaration": {
                "behavior": readiness_behavior.descriptor(),
                "prerequisites": {},
            },
            "deterministic": True,
            "cacheable": True,
            "implementation_identity": {
                "name": "test.candidate.direct",
                "factory": factory_behavior.descriptor(),
            },
            "produced_observations": [],
        },
    )

    class CandidateImplementation:
        def __init__(self, resources) -> None:
            self._resources = resources

        def execute(self, call: OperationCall) -> dict[str, Any]:
            assert call.inputs == {}
            calls.append(self._resources.run_id)
            with self._resources.engine_invocation():
                pass
            produced = Candidate(
                candidate_id=f"candidate-{self._resources.run_id}",
                data=ProteinSequence("ACDE"),
                parent_ids=(
                    [self._resources.node_id]
                    if declare_root_node_as_parent
                    else []
                ),
                metadata={
                    "run_id": self._resources.run_id,
                    "scientific_label": "fixture",
                },
            )
            return {
                "candidates": CandidateCollection(
                    collection_id=f"collection-{self._resources.run_id}",
                    item_type="protein.sequence",
                    items=[
                        produced,
                        *(
                            [
                                Candidate(
                                    candidate_id=produced.candidate_id,
                                    data=ProteinSequence("WXYZ"),
                                    parent_ids=list(produced.parent_ids),
                                )
                            ]
                            if duplicate_output_ids
                            else []
                        ),
                    ],
                )
            }

    def factory(context: OperationContext) -> CandidateImplementation:
        return CandidateImplementation(context.resources)

    observed_at = datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc)
    return FrozenCatalog(
        builtin.port_types,
        contracts=(method, node, binding),
        availability=(
            {
                "binding": binding.reference(),
                "observed_at": observed_at.isoformat(),
                "available": True,
            },
        ),
        availability_observed_at=observed_at,
        factories={
            ("test.candidate.direct", "2.1.0"): ScientificOperationFactory(
                behavior=factory_behavior,
                build=factory,
            )
        },
        readiness_declarations={
            ("test.candidate.direct", "2.1.0"): ReadinessDeclaration(
                behavior=readiness_behavior,
                prerequisites={},
                check=lambda environment: ReadinessResult(True),
            )
        },
    )


def _commit_candidate_node(
    client: TestClient,
) -> tuple[str, dict[str, Any]]:
    project_id = client.post(
        "/api/v2/projects",
        json={"name": "v2 Candidate identity"},
    ).json()["id"]
    workflow = {
        "schema_version": "2.1.0",
        "workflow_id": project_id,
        "nodes": [
            {
                "node_id": "candidate-producer",
                "node_type_id": "test.candidate",
                "node_type_version": "2.1.0",
                "binding_id": "test.candidate.direct",
                "binding_version": "2.1.0",
                "node_parameters": {},
                "binding_parameters": {},
            }
        ],
        "edges": [],
        "contract_lock": [],
    }
    return project_id, _commit_public_workflow(client, project_id, workflow)


def _candidate_value(
    client: TestClient,
    project_id: str,
    projection: dict[str, Any],
) -> dict[str, Any]:
    return retrieve_typed_output_values(
        client,
        project_id,
        projection["run_id"],
        projection["outputs"][0],
    )[0]


def test_deterministic_result_replays_without_rechecking_provider_readiness(
    tmp_path,
    monkeypatch,
) -> None:
    """The public projection exposes one stable identity and honest replay."""
    calls: list[str] = []
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROJECT_ROOT",
        str(tmp_path / "projects"),
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    app = create_application(
        frozen_catalog_override=_direct_catalog(calls, cacheable=True),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_one_node(client)
        first, _ = _start_run(client, project_id, compiled, "first")
        second, second_events = _start_run(
            client,
            project_id,
            compiled,
            "second",
        )

    first_output = first["outputs"][0]
    replayed_output = second["outputs"][0]
    assert first_output["result_identity"].startswith("sha256:")
    assert replayed_output["result_identity"] == first_output["result_identity"]
    assert first_output["producer_provenance"]["producer_run_id"] == first["run_id"]
    assert (
        replayed_output["producer_provenance"]["producer_run_id"]
        == first["run_id"]
    )
    assert replayed_output["materialization"] == {
        "run_id": second["run_id"],
        "resolution": "cache_replayed",
    }
    assert second["node_dispositions"][0]["resolution"] == "cache_replayed"
    assert calls == [
        "readiness:test.direct.local",
        "factory:test.direct.local",
        "execute:test.direct.local",
    ]
    replay_event_types = {
        item["event"]["type"] for item in second_events
    }
    assert "operation_attempt_started" not in replay_event_types
    assert "engine_invocation_started" not in replay_event_types


def test_node_instance_rename_reuses_the_same_scientific_result(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        monkeypatch.setenv(
            f"PROTEIN_WORKBENCH_{name}_ROOT",
            str(tmp_path / name.lower()),
        )
    app = create_application(
        frozen_catalog_override=_direct_catalog(calls, cacheable=True),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_one_node(client)
        first, _ = _start_run(client, project_id, compiled, "before-rename")
        renamed_workflow = client.get(
            f"/api/v2/projects/{project_id}/workflow/draft"
        ).json()["workflow"]
        renamed_workflow["nodes"][0]["node_id"] = "renamed"
        renamed = _commit_public_workflow(
            client,
            project_id,
            renamed_workflow,
        )
        replayed, _ = _start_run(
            client,
            project_id,
            renamed,
            "after-rename",
        )

    assert replayed["outputs"][0]["node_id"] == "renamed"
    assert replayed["outputs"][0]["result_identity"] == (
        first["outputs"][0]["result_identity"]
    )
    assert replayed["node_dispositions"][0]["resolution"] == (
        "cache_replayed"
    )
    assert [call for call in calls if call.startswith("execute:")] == [
        "execute:test.direct.local"
    ]


def test_cache_v4_is_reference_only_and_ledger_commits_node_result_manifest(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    cache_root = tmp_path / "cache"
    run_root = tmp_path / "runs"
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROJECT_ROOT",
        str(tmp_path / "projects"),
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(run_root))
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    app = create_application(
        frozen_catalog_override=_direct_catalog(calls, cacheable=True),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_one_node(client)
        first, _ = _start_run(client, project_id, compiled, "manifest-source")

    result_identity = first["outputs"][0]["result_identity"]
    digest = result_identity.removeprefix("sha256:")
    cache_path = cache_root / project_id / "v4" / "results" / f"{digest}.json"
    entry = json.loads(cache_path.read_bytes())
    assert entry == {
        "schema_namespace": "protein-workbench-cache-entry/v4",
        "result_identity": result_identity,
        "result_contract_metadata": entry["result_contract_metadata"],
        "producer": {
            "producer_run_id": first["run_id"],
            "producer_node_id": "direct",
        },
        "node_result_manifest": entry["node_result_manifest"],
        "outputs": entry["outputs"],
    }
    assert "encoded_values" not in json.dumps(entry)
    assert entry["outputs"] == [
        {
            "output_port": "text",
            "value_manifest": entry["outputs"][0]["value_manifest"],
        }
    ]

    publication = next(
        fact
        for transaction_path in sorted(
            (run_root / project_id / first["run_id"] / "ledger").glob("*.json")
        )
        for fact in json.loads(transaction_path.read_bytes())["facts"]
        if fact["fact_type"] == "outputs_published"
    )
    assert publication["payload"]["result_identity"] == result_identity
    assert publication["payload"]["node_result_manifest"] == entry[
        "node_result_manifest"
    ]


def test_cache_index_covers_ordinary_and_artifact_output_ports(
    tmp_path,
    monkeypatch,
) -> None:
    cache_root = tmp_path / "cache"
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROJECT_ROOT",
        str(tmp_path / "projects"),
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    app = create_application(
        frozen_catalog_override=_artifact_catalog(
            [],
            cacheable=True,
            include_ordinary_output=True,
        )
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_artifact_node(client)
        first, _ = _start_run(client, project_id, compiled, "artifact-source")
        replayed, _ = _start_run(client, project_id, compiled, "artifact-replay")

    entry_path = next((cache_root / project_id / "v4").rglob("*.json"))
    entry = json.loads(entry_path.read_bytes())
    assert [output["output_port"] for output in entry["outputs"]] == [
        "summary",
        "structure",
    ]
    assert [output["output_port"] for output in first["outputs"]] == [
        "summary"
    ]
    assert [artifact["output_port"] for artifact in first["artifact_index"]] == [
        "structure"
    ]
    assert replayed["node_dispositions"][0]["resolution"] == "cache_replayed"
    assert replayed["outputs"][0]["producer_provenance"][
        "producer_run_id"
    ] == first["run_id"]
    assert replayed["artifact_index"][0]["output_port"] == "structure"


def test_project_cache_reuses_admitted_canonical_bytes_without_reencoding(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROJECT_ROOT",
        str(tmp_path / "projects"),
    )
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_CACHE_ROOT",
        str(tmp_path / "cache"),
    )
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_RUN_ROOT",
        str(tmp_path / "runs"),
    )
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    app = create_application(
        frozen_catalog_override=_pipeline_catalog(
            calls,
            cacheable=True,
        )
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_pipeline(client)
        first, _ = _start_run(client, project_id, compiled, "admission-a")
        second, _ = _start_run(client, project_id, compiled, "admission-b")

    assert first["status"] == second["status"] == "succeeded"
    assert [
        item["resolution"] for item in second["node_dispositions"]
    ] == ["cache_replayed", "cache_replayed"]
    assert [item for item in calls if item.startswith("validate:")] == [
        "validate:'ready'",
        "validate:'ready'",
        "validate:'ready'",
        "validate:'ready'",
    ]


def test_cache_publication_failure_does_not_change_node_or_run_success(
    tmp_path,
    monkeypatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fail_index(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("fixture cache publication failure")

    monkeypatch.setattr(ProjectReplayIndex, "index", fail_index)

    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROJECT_ROOT",
        str(tmp_path / "projects"),
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    app = create_application(
        frozen_catalog_override=_direct_catalog([], cacheable=True),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_one_node(client)
        projection, events = _start_run(
            client,
            project_id,
            compiled,
            "cache-publication-failure",
        )

    public_events = [item["event"] for item in events]
    operation_terminal = next(
        item
        for item in public_events
        if item["type"] == "operation_attempt_terminal"
    )
    node_terminal = next(
        item
        for item in public_events
        if item["type"] == "node_attempt_terminal"
    )
    run_terminal = next(
        item for item in public_events if item["type"] == "run_terminal"
    )
    assert projection["status"] == "succeeded"
    assert len(projection["outputs"]) == 1
    assert operation_terminal["status"] == "succeeded"
    assert node_terminal["status"] == "succeeded"
    assert run_terminal["status"] == "succeeded"
    assert caplog.messages == [
        "Committed Result replay index publication is unavailable"
    ]


def test_candidate_identity_is_run_independent_and_preserved_on_replay(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROJECT_ROOT",
        str(tmp_path / "projects"),
    )
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_CACHE_ROOT",
        str(tmp_path / "cache"),
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    app = create_application(frozen_catalog_override=_candidate_catalog(calls))

    with TestClient(app) as client:
        project_id, compiled = _commit_candidate_node(client)
        source, _ = _start_run(client, project_id, compiled, "candidate-a")
        forced = client.post(
            f"/api/v2/projects/{project_id}/runs:derive",
            json={
                "source_run_id": source["run_id"],
                "policy": "force_selected",
                "node_ids": ["candidate-producer"],
                "client_request_id": "candidate-force",
            },
        )
        assert forced.status_code == 202
        forced_projection = wait_for_testclient_run_terminal(
            client,
            project_id,
            forced.json()["run_id"],
        )
        replayed, _ = _start_run(
            client,
            project_id,
            compiled,
            "candidate-replay",
        )

        source_value = _candidate_value(client, project_id, source)
        forced_value = _candidate_value(
            client,
            project_id,
            forced_projection,
        )
        replayed_value = _candidate_value(client, project_id, replayed)

    candidate_fields = source_value["fields"]["items"][0]["fields"]
    candidate_id = candidate_fields["candidate_id"]
    assert candidate_id.startswith("candidate-")
    assert forced_value["fields"]["items"][0]["fields"][
        "candidate_id"
    ] == candidate_id
    assert replayed_value["fields"]["items"][0]["fields"][
        "candidate_id"
    ] == candidate_id
    assert candidate_fields["parent_ids"] == []
    assert candidate_fields["metadata"]["$map"]
    assert calls == [source["run_id"], forced_projection["run_id"]]
    assert forced_projection["node_dispositions"][0]["resolution"] == "executed"
    assert replayed["node_dispositions"][0]["resolution"] == "cache_replayed"


def test_duplicate_candidate_producer_identity_fails_closed(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROJECT_ROOT",
        str(tmp_path / "projects"),
    )
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_CACHE_ROOT",
        str(tmp_path / "cache"),
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    app = create_application(
        frozen_catalog_override=_candidate_catalog(
            [],
            duplicate_output_ids=True,
        )
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_candidate_node(client)
        projection, events = _start_run(
            client,
            project_id,
            compiled,
            "duplicate-candidate",
        )

    terminal = next(
        item["event"]
        for item in events
        if item["event"]["type"] == "node_attempt_terminal"
    )
    assert projection["status"] == "failed"
    assert projection["outputs"] == []
    assert terminal["error"]["code"] == "node_execution_failed"
    assert terminal["error"]["details"]["exception_type"] == "PortValueError"


def test_root_candidate_cannot_declare_node_id_as_pseudo_parent(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROJECT_ROOT",
        str(tmp_path / "projects"),
    )
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_CACHE_ROOT",
        str(tmp_path / "cache"),
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    app = create_application(
        frozen_catalog_override=_candidate_catalog(
            [],
            declare_root_node_as_parent=True,
        )
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_candidate_node(client)
        projection, events = _start_run(
            client,
            project_id,
            compiled,
            "root-pseudo-parent",
        )

    terminal = next(
        item["event"]
        for item in events
        if item["event"]["type"] == "node_attempt_terminal"
    )
    assert projection["status"] == "failed"
    assert projection["outputs"] == []
    assert terminal["error"]["code"] == "node_execution_failed"
    assert terminal["error"]["details"]["exception_type"] == "PortValueError"


def test_same_result_identity_is_physically_isolated_between_projects(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    project_root = tmp_path / "projects"
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    app = create_application(
        frozen_catalog_override=_direct_catalog(
            calls,
            cacheable=True,
            binding_environment_fields=(
                EnvironmentFieldDeclaration(
                    "runtime_path",
                    "filesystem_path",
                ),
            ),
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {
                    "credential": "credential-value",
                    "runtime_path": str(tmp_path / "private-runtime"),
                },
            }
        },
    )

    with TestClient(app) as client:
        first_project, first_compiled = _commit_one_node(client)
        second_project, second_compiled = _commit_one_node(client)
        first, _ = _start_run(
            client,
            first_project,
            first_compiled,
            "project-a",
        )
        second, _ = _start_run(
            client,
            second_project,
            second_compiled,
            "project-b",
        )

    assert first_project != second_project
    assert (
        first["outputs"][0]["result_identity"]
        == second["outputs"][0]["result_identity"]
    )
    assert [
        item
        for item in calls
        if item == "execute:test.direct.local"
    ] == [
        "execute:test.direct.local",
        "execute:test.direct.local",
    ]
    assert (
            len(list((cache_root / first_project / "v4").rglob("*.json")))
        == 1
    )
    assert (
            len(list((cache_root / second_project / "v4").rglob("*.json")))
        == 1
    )


def test_runtime_credentials_paths_and_performance_choices_do_not_change_identity(
    tmp_path,
    monkeypatch,
) -> None:
    project_root = tmp_path / "projects"
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    readiness = {
        "test.direct.local": lambda check_input: ReadinessResult(
            bool(check_input.values)
        )
    }
    first_calls: list[str] = []
    with TestClient(
        create_application(
            frozen_catalog_override=_direct_catalog(
                first_calls,
                cacheable=True,
                readiness_checks=readiness,
                binding_environment_fields=(
                    EnvironmentFieldDeclaration(
                        "runtime_path",
                        "filesystem_path",
                    ),
                    EnvironmentFieldDeclaration("device", "json_value"),
                ),
            ),
            v2_environment_configuration={
                ("test.direct.local", "2.1.0"): {
                    "values": {
                        "credential": "secret-a",
                        "runtime_path": str(tmp_path / "private-a"),
                        "device": "cpu",
                    },
                }
            },
        )
    ) as first_client:
        project_id, compiled = _commit_one_node(first_client)
        first, _ = _start_run(
            first_client,
            project_id,
            compiled,
            "environment-a",
        )

    second_calls: list[str] = []
    with TestClient(
        create_application(
            frozen_catalog_override=_direct_catalog(
                second_calls,
                cacheable=True,
                readiness_checks=readiness,
                binding_environment_fields=(
                    EnvironmentFieldDeclaration(
                        "runtime_path",
                        "filesystem_path",
                    ),
                    EnvironmentFieldDeclaration("device", "json_value"),
                ),
            ),
            v2_environment_configuration={
                ("test.direct.local", "2.1.0"): {
                    "values": {
                        "credential": "secret-b",
                        "runtime_path": str(tmp_path / "private-b"),
                        "device": "accelerator-7",
                    },
                }
            },
        )
    ) as second_client:
        committed_again = second_client.get(
            f"/api/v2/projects/{project_id}/workflow/active-commit"
        )
        assert committed_again.status_code == 200
        second, _ = _start_run(
            second_client,
            project_id,
            committed_again.json(),
            "environment-b",
        )

    assert (
        first["outputs"][0]["result_identity"]
        == second["outputs"][0]["result_identity"]
    )
    assert first["node_dispositions"][0]["resolution"] == "executed"
    assert second["node_dispositions"][0]["resolution"] == "cache_replayed"
    assert "execute:test.direct.local" in first_calls
    assert "execute:test.direct.local" not in second_calls


def test_presentation_only_contract_change_runs_in_the_current_generation(
    tmp_path,
    monkeypatch,
) -> None:
    project_root = tmp_path / "projects"
    cache_root = tmp_path / "cache"
    run_root = tmp_path / "runs"
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(run_root))
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    environment = {
        ("test.direct.local", "2.1.0"): {
            "values": {"credential": "credential-value"},
        }
    }
    first_calls: list[str] = []
    producer_catalog = _direct_catalog(
        first_calls,
        cacheable=True,
        node_title="Scientific text producer",
    )
    with TestClient(
        create_application(
            frozen_catalog_override=producer_catalog,
            v2_environment_configuration=environment,
        )
    ) as first_client:
        project_id, compiled = _commit_one_node(first_client)
        first, _ = _start_run(
            first_client,
            project_id,
            compiled,
            "presentation-a",
        )
        producer_run_id = first["run_id"]

    producer_ledger = run_root / project_id / producer_run_id / "ledger"
    before = {
        path.name: path.read_bytes()
        for path in sorted(producer_ledger.glob("*.json"))
    }
    cache_entry = next((cache_root / project_id / "v4").rglob("*.json"))
    cache_entry.unlink()
    cache_entry.parent.rmdir()
    cache_entry.parent.parent.rmdir()
    cache_entry.parent.parent.parent.rmdir()

    second_calls: list[str] = []
    active_catalog = _direct_catalog(
        second_calls,
        cacheable=True,
        node_title="Renamed UI label",
        execution_output="READY",
    )
    assert producer_catalog.contract_digest != active_catalog.contract_digest
    with TestClient(
        create_application(
            frozen_catalog_override=active_catalog,
            v2_environment_configuration=environment,
        )
    ) as second_client:
        rejected = second_client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": compiled["workflow_commit_id"],
                "client_request_id": "presentation-contract-change",
            },
        )
        current_workflow = {
            "schema_version": "2.1.0",
            "workflow_id": project_id,
            "nodes": [
                {
                    "node_id": "direct",
                    "node_type_id": "test.direct",
                    "node_type_version": "2.1.0",
                    "binding_id": "test.direct.local",
                    "binding_version": "2.1.0",
                    "node_parameters": {},
                    "binding_parameters": {},
                }
            ],
            "edges": [],
            "contract_lock": [],
        }
        current = _commit_public_workflow(
            second_client,
            project_id,
            current_workflow,
        )
        current_run, _events = _start_run(
            second_client,
            project_id,
            current,
            "presentation-current",
        )

    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "contract_digest_mismatch"
    assert rejected.json()["error"]["details"]["issues"][0][
        "field_path"
    ] == ["contract_lock"]

    after = {
        path.name: path.read_bytes()
        for path in sorted(producer_ledger.glob("*.json"))
    }
    assert first["node_dispositions"][0]["resolution"] == "executed"
    assert "execute:test.direct.local" in first_calls
    assert current_run["status"] == "succeeded"
    assert current_run["node_dispositions"][0]["resolution"] == "executed"
    assert "execute:test.direct.local" in second_calls
    assert (cache_root / project_id).exists()
    assert before == after


def test_changed_implementation_identity_rejects_the_old_workflow_generation(
    tmp_path,
    monkeypatch,
) -> None:
    project_root = tmp_path / "projects"
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    environment = {
        ("test.direct.local", "2.1.0"): {
            "values": {"credential": "credential-value"},
        }
    }
    first_calls: list[str] = []
    with TestClient(
        create_application(
            frozen_catalog_override=_direct_catalog(
                first_calls,
                cacheable=True,
                implementation_variant="algorithm",
                implementation_label="algorithm-a",
            ),
            v2_environment_configuration=environment,
        )
    ) as first_client:
        project_id, compiled = _commit_one_node(first_client)
        first, _ = _start_run(
            first_client,
            project_id,
            compiled,
            "algorithm-a",
        )
        first_values = retrieve_typed_output_values(
            first_client,
            project_id,
            first["run_id"],
            first["outputs"][0],
        )

    second_calls: list[str] = []
    with TestClient(
        create_application(
            frozen_catalog_override=_direct_catalog(
                second_calls,
                cacheable=True,
                execution_output="READY-B",
                implementation_variant="algorithm",
                implementation_label="algorithm-b",
            ),
            v2_environment_configuration=environment,
        )
    ) as second_client:
        rejected = second_client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": compiled["workflow_commit_id"],
                "client_request_id": "implementation-identity-change",
            },
        )

    assert first_values == ["READY"]
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "contract_digest_mismatch"
    assert rejected.json()["error"]["details"]["issues"][0][
        "field_path"
    ] == ["contract_lock"]
    assert second_calls == []


def test_changed_scientific_parameter_changes_result_identity_and_misses(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    cache_root = tmp_path / "cache"
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROJECT_ROOT",
        str(tmp_path / "projects"),
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    app = create_application(
        frozen_catalog_override=_direct_catalog(
            calls,
            cacheable=True,
            node_parameter_declarations={
                "scientific_label": {
                    "parameter_scope": "scientific",
                    "scientific_meaning": (
                        "A result-affecting scientific fixture label"
                    ),
                    "value_contract": {"type": "string"},
                    "default": "alpha",
                }
            },
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_one_node(client)
        first, _ = _start_run(client, project_id, compiled, "parameter-alpha")
        loaded = client.get(
            f"/api/v2/projects/{project_id}/workflow/draft"
        ).json()
        changed = loaded["workflow"]
        changed["nodes"][0]["node_parameters"] = {
            "scientific_label": "beta"
        }
        compiled_beta = client.post(
            f"/api/v2/projects/{project_id}/workflow:commit",
            json={
                "workflow": changed,
            },
        ).json()
        second, _ = _start_run(
            client,
            project_id,
            compiled_beta,
            "parameter-beta",
        )

    assert (
        first["outputs"][0]["result_identity"]
        != second["outputs"][0]["result_identity"]
    )
    assert second["node_dispositions"][0]["resolution"] == "executed"
    assert "parameters:{'scientific_label': 'alpha'}" in calls
    assert "parameters:{'scientific_label': 'beta'}" in calls
    assert len(list((cache_root / project_id / "v4").rglob("*.json"))) == 2


@pytest.mark.parametrize(
    ("termination", "expected_status"),
    (
        ("failed", "failed"),
        ("interrupted", "interrupted"),
        ("outcome_unknown", "interrupted"),
    ),
)
def test_unsuccessful_or_unknown_outcomes_never_populate_cache(
    tmp_path,
    monkeypatch,
    termination: str,
    expected_status: str,
) -> None:
    failing = {"enabled": True}
    cache_root = tmp_path / "cache"

    def terminate(_resources) -> None:
        if not failing["enabled"]:
            return
        if termination == "failed":
            raise RuntimeError("fixture failure")
        raise ExecutionTermination(termination)

    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROJECT_ROOT",
        str(tmp_path / "projects"),
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    app = create_application(
        frozen_catalog_override=_direct_catalog(
            [],
            cacheable=True,
            execution_action=terminate,
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_one_node(client)
        failed, _ = _start_run(
            client,
            project_id,
            compiled,
            f"termination-{termination}",
        )
        assert not list((cache_root / project_id).rglob("*.json"))
        failing["enabled"] = False
        recovered, _ = _start_run(
            client,
            project_id,
            compiled,
            f"recovered-{termination}",
        )

    assert failed["status"] == expected_status
    assert failed["outputs"] == []
    assert recovered["node_dispositions"][0]["resolution"] == "executed"


def test_uncontrolled_stochastic_binding_never_looks_up_or_publishes(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    cache_root = tmp_path / "cache"
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROJECT_ROOT",
        str(tmp_path / "projects"),
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    app = create_application(
        frozen_catalog_override=_direct_catalog(
            calls,
            cacheable=True,
            deterministic=False,
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_one_node(client)
        first, _ = _start_run(client, project_id, compiled, "stochastic-a")
        second, _ = _start_run(client, project_id, compiled, "stochastic-b")

    assert first["node_dispositions"][0]["resolution"] == "executed"
    assert second["node_dispositions"][0]["resolution"] == "executed"
    assert [
        item for item in calls if item == "execute:test.direct.local"
    ] == [
        "execute:test.direct.local",
        "execute:test.direct.local",
    ]
    assert not list((cache_root / project_id).rglob("*.json"))


def test_unresolved_result_affecting_identity_disables_cross_run_cache(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    cache_root = tmp_path / "cache"
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROJECT_ROOT",
        str(tmp_path / "projects"),
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    app = create_application(
        frozen_catalog_override=_direct_catalog(
            calls,
            cacheable=True,
            source_identity={"kind": "unresolved"},
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_one_node(client)
        first, _ = _start_run(client, project_id, compiled, "unresolved-a")
        second, _ = _start_run(client, project_id, compiled, "unresolved-b")

    assert (
        first["outputs"][0]["result_identity"]
        == second["outputs"][0]["result_identity"]
    )
    assert first["node_dispositions"][0]["resolution"] == "executed"
    assert second["node_dispositions"][0]["resolution"] == "executed"
    assert [
        item for item in calls if item == "execute:test.direct.local"
    ] == [
        "execute:test.direct.local",
        "execute:test.direct.local",
    ]
    assert not list((cache_root / project_id).rglob("*.json"))


def test_unresolvable_declared_effective_seed_disables_cross_run_cache(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    cache_root = tmp_path / "cache"
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROJECT_ROOT",
        str(tmp_path / "projects"),
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    app = create_application(
        frozen_catalog_override=_direct_catalog(
            calls,
            cacheable=True,
            node_parameter_declarations={
                "effective_seed": {
                    "parameter_scope": "scientific",
                    "scientific_meaning": (
                        "Fixture seed whose effective value cannot be resolved."
                    ),
                    "value_contract": {
                        "type": "string",
                        "enum": ["unresolved"],
                    },
                    "default": "unresolved",
                },
            },
            effective_randomness_parameters=("effective_seed",),
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_one_node(client)
        first, _ = _start_run(client, project_id, compiled, "randomness-a")
        second, _ = _start_run(client, project_id, compiled, "randomness-b")

    assert (
        first["outputs"][0]["result_identity"]
        == second["outputs"][0]["result_identity"]
    )
    assert first["node_dispositions"][0]["resolution"] == "executed"
    assert second["node_dispositions"][0]["resolution"] == "executed"
    assert [
        item for item in calls if item == "execute:test.direct.local"
    ] == [
        "execute:test.direct.local",
        "execute:test.direct.local",
    ]
    assert not list((cache_root / project_id).rglob("*.json"))


def test_null_declared_effective_seed_disables_cross_run_cache(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    cache_root = tmp_path / "cache"
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROJECT_ROOT",
        str(tmp_path / "projects"),
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    app = create_application(
        frozen_catalog_override=_direct_catalog(
            calls,
            cacheable=True,
            node_parameter_declarations={
                "effective_seed": {
                    "parameter_scope": "scientific",
                    "scientific_meaning": (
                        "Fixture seed whose effective value is null."
                    ),
                    "value_contract": {"type": "null"},
                    "default": None,
                },
            },
            effective_randomness_parameters=("effective_seed",),
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_one_node(client)
        first, _ = _start_run(client, project_id, compiled, "randomness-null-a")
        second, _ = _start_run(client, project_id, compiled, "randomness-null-b")

    assert (
        first["outputs"][0]["result_identity"]
        == second["outputs"][0]["result_identity"]
    )
    assert first["node_dispositions"][0]["resolution"] == "executed"
    assert second["node_dispositions"][0]["resolution"] == "executed"
    assert [
        item for item in calls if item == "execute:test.direct.local"
    ] == [
        "execute:test.direct.local",
        "execute:test.direct.local",
    ]
    assert not list((cache_root / project_id).rglob("*.json"))


def test_effective_randomness_is_resolved_once_and_drives_execution(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    resolver_calls: list[int] = []
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROJECT_ROOT",
        str(tmp_path / "projects"),
    )
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_CACHE_ROOT",
        str(tmp_path / "cache"),
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )

    def resolve_randomness(
        *,
        inputs,
        node_parameters,
        binding_parameters,
    ):
        assert inputs == {}
        assert binding_parameters == {}
        resolver_calls.append(node_parameters["effective_seed"])
        return {"effective_seed": node_parameters["effective_seed"] + 1}

    resolver = EffectiveRandomnessResolver(
        behavior=BehaviorReference(
            "test.direct/effective-randomness",
            "2.1.0",
            {"normalization": "increment-fixture"},
        ),
        resolve=resolve_randomness,
    )
    app = create_application(
        frozen_catalog_override=_direct_catalog(
            calls,
            cacheable=True,
            node_parameter_declarations={
                "effective_seed": {
                    "parameter_scope": "scientific",
                    "scientific_meaning": "Fixture seed normalized before use.",
                    "value_contract": {"type": "integer"},
                    "default": 4,
                },
            },
            effective_randomness_parameters=("effective_seed",),
            effective_randomness_resolver=resolver,
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_one_node(client)
        first, _ = _start_run(client, project_id, compiled, "resolved-once-a")
        second, _ = _start_run(client, project_id, compiled, "resolved-once-b")

    assert resolver_calls == [4, 4]
    assert [item for item in calls if item.startswith("parameters:")] == [
        "parameters:{'effective_seed': 5}",
    ]
    assert (
        first["outputs"][0]["result_identity"]
        == second["outputs"][0]["result_identity"]
    )
    assert first["node_dispositions"][0]["resolution"] == "executed"
    assert second["node_dispositions"][0]["resolution"] == "cache_replayed"


def test_unresolved_port_behavior_identity_disables_cross_run_cache(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    cache_root = tmp_path / "cache"
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROJECT_ROOT",
        str(tmp_path / "projects"),
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    app = create_application(
        frozen_catalog_override=_pipeline_catalog(
            calls,
            cacheable=True,
            unresolved_port_identity=True,
        )
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_pipeline(client)
        first, _ = _start_run(client, project_id, compiled, "port-unresolved-a")
        second, _ = _start_run(
            client,
            project_id,
            compiled,
            "port-unresolved-b",
        )

    assert all(
        item["resolution"] == "executed"
        for item in first["node_dispositions"]
    )
    assert all(
        item["resolution"] == "executed"
        for item in second["node_dispositions"]
    )
    assert calls.count("execute:source") == 2
    assert calls.count("sink-input:ready") == 2
    assert not list((cache_root / project_id).rglob("*.json"))
