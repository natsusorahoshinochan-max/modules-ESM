"""Public-projection acceptance for Result Identity and the v2 Cache."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi.testclient import TestClient
import pytest

from core import (
    BehaviorReference,
    ExecutionTermination,
    FrozenCatalog,
    LazyImplementationFactory,
    ReadinessDeclaration,
    ResultReplaySource,
    builtin_frozen_catalog,
)
from core.server import create_app
from datatypes import Candidate, CandidateCollection, ProteinSequence
from tests.test_run_execution_v2 import (
    _artifact_catalog,
    _compile_artifact_node,
    _compile_one_node,
    _contract,
    _direct_catalog,
)


def _start_run(
    client: TestClient,
    project_id: str,
    compiled: dict[str, object],
    request_id: str,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    started = client.post(
        f"/api/v2/projects/{project_id}/runs",
        json={
            "workflow_revision": compiled["workflow_revision"],
            "compile_id": compiled["compile_id"],
            "client_request_id": request_id,
        },
    )
    assert started.status_code == 202
    run_id = started.json()["run_id"]
    projection = client.get(
        f"/api/v2/projects/{project_id}/runs/{run_id}"
    ).json()
    events = client.app.state.run_execution_v2.public_events(
        project_id,
        run_id,
    )
    return projection, events


def _candidate_catalog(
    calls: list[str],
    *,
    duplicate_output_ids: bool = False,
) -> FrozenCatalog:
    builtin = builtin_frozen_catalog()
    candidates = builtin.require_port_type("candidate.collection", "2.0.0")
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
        "2.0.0",
        {},
    )
    readiness_behavior = BehaviorReference(
        "test.candidate/readiness",
        "2.0.0",
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
                    "behavior_version": "2.0.0",
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

        def execute(self, **kwargs: Any) -> dict[str, Any]:
            assert kwargs["inputs"] == {}
            calls.append(self._resources.run_id)
            with self._resources.engine_invocation():
                pass
            produced = Candidate(
                candidate_id=f"candidate-{self._resources.run_id}",
                data=ProteinSequence("ACDE"),
                parent_ids=[self._resources.node_id],
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
                                    parent_ids=[self._resources.node_id],
                                )
                            ]
                            if duplicate_output_ids
                            else []
                        ),
                    ],
                )
            }

    def factory(**kwargs: Any) -> CandidateImplementation:
        return CandidateImplementation(kwargs["run_resources"])

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
            ("test.candidate.direct", "2.0.0"): LazyImplementationFactory(
                behavior=factory_behavior,
                build=factory,
            )
        },
        readiness_declarations={
            ("test.candidate.direct", "2.0.0"): ReadinessDeclaration(
                behavior=readiness_behavior,
                prerequisites={},
                check=lambda environment: True,
            )
        },
    )


def _compile_candidate_node(
    client: TestClient,
) -> tuple[str, dict[str, Any]]:
    project_id = client.post(
        "/api/projects",
        json={"name": "v2 Candidate identity"},
    ).json()["id"]
    workflow = {
        "schema_version": "2.0.0",
        "workflow_id": project_id,
        "nodes": [
            {
                "node_id": "candidate-producer",
                "node_type_id": "test.candidate",
                "node_type_version": "2.0.0",
                "binding_id": "test.candidate.direct",
                "binding_version": "2.0.0",
                "node_parameters": {},
                "binding_parameters": {},
            }
        ],
        "edges": [],
        "contract_lock": [],
    }
    assert client.put(
        f"/api/v2/projects/{project_id}/workflow",
        json={"expected_workflow_revision": 0, "workflow": workflow},
    ).status_code == 200
    relocked = client.post(
        f"/api/v2/projects/{project_id}/workflow:relock",
        json={"workflow_revision": 1},
    )
    compiled = client.post(
        f"/api/v2/projects/{project_id}/workflow:compile",
        json={
            "workflow_revision": 2,
            "workflow": relocked.json()["workflow"],
        },
    )
    assert compiled.status_code == 200
    return project_id, compiled.json()


def _candidate_id(projection: dict[str, Any]) -> str:
    return projection["outputs"][0]["values"][0]["fields"]["items"][0][
        "fields"
    ]["candidate_id"]


def test_deterministic_result_replays_from_project_cache_after_readiness(
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
    app = create_app(
        frozen_catalog_override=_direct_catalog(calls, cacheable=True),
        v2_environment_configuration={
            ("test.direct.local", "2.0.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _compile_one_node(client)
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
        "readiness:test.direct.local",
    ]
    replay_event_types = {
        item["event"]["type"] for item in second_events
    }
    assert "operation_attempt_started" not in replay_event_types
    assert "engine_invocation_started" not in replay_event_types


def test_replay_without_identity_bound_producer_provenance_is_rejected(
    tmp_path,
    monkeypatch,
) -> None:
    class AmbiguousReplay(ResultReplaySource):
        def lookup(self, **_kwargs: Any):
            return {"text": "AMBIGUOUS"}

    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROJECT_ROOT",
        str(tmp_path / "projects"),
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    app = create_app(
        frozen_catalog_override=_direct_catalog([], cacheable=True),
        v2_result_replay_source=AmbiguousReplay(),
        v2_environment_configuration={
            ("test.direct.local", "2.0.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _compile_one_node(client)
        projection, events = _start_run(
            client,
            project_id,
            compiled,
            "ambiguous-replay",
        )

    terminal = next(
        item["event"]
        for item in events
        if item["event"]["type"] == "node_attempt_terminal"
    )
    assert projection["status"] == "failed"
    assert projection["outputs"] == []
    assert terminal["error"]["code"] == "cache_identity_conflict"
    assert not any(
        item["event"]["type"] == "operation_attempt_started"
        for item in events
    )


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
    app = create_app(frozen_catalog_override=_candidate_catalog(calls))

    with TestClient(app) as client:
        project_id, compiled = _compile_candidate_node(client)
        source, _ = _start_run(client, project_id, compiled, "candidate-a")
        forced = client.post(
            f"/api/v2/projects/{project_id}/runs:derive",
            json={
                "source_run_id": source["run_id"],
                "compile_id": compiled["compile_id"],
                "policy": "force_selected",
                "node_ids": ["candidate-producer"],
                "client_request_id": "candidate-force",
            },
        )
        assert forced.status_code == 202
        forced_projection = client.get(
            f"/api/v2/projects/{project_id}/runs/{forced.json()['run_id']}"
        ).json()
        replayed, _ = _start_run(
            client,
            project_id,
            compiled,
            "candidate-replay",
        )

    candidate_id = _candidate_id(source)
    assert candidate_id.startswith("candidate-")
    assert _candidate_id(forced_projection) == candidate_id
    assert _candidate_id(replayed) == candidate_id
    candidate_fields = source["outputs"][0]["values"][0]["fields"]["items"][0][
        "fields"
    ]
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
    app = create_app(
        frozen_catalog_override=_candidate_catalog(
            [],
            duplicate_output_ids=True,
        )
    )

    with TestClient(app) as client:
        project_id, compiled = _compile_candidate_node(client)
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
    app = create_app(
        frozen_catalog_override=_direct_catalog(calls, cacheable=True),
        v2_environment_configuration={
            ("test.direct.local", "2.0.0"): {
                "values": {
                    "credential": "credential-value",
                    "runtime_path": str(tmp_path / "private-runtime"),
                },
                "safe_fingerprint": "runtime-a",
            }
        },
    )

    with TestClient(app) as client:
        first_project, first_compiled = _compile_one_node(client)
        second_project, second_compiled = _compile_one_node(client)
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
        len(list((cache_root / first_project / "v2").rglob("*.json")))
        == 1
    )
    assert (
        len(list((cache_root / second_project / "v2").rglob("*.json")))
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
    readiness = {"test.direct.local": lambda environment: bool(environment)}
    first_calls: list[str] = []
    with TestClient(
        create_app(
            frozen_catalog_override=_direct_catalog(
                first_calls,
                cacheable=True,
                readiness_checks=readiness,
            ),
            v2_environment_configuration={
                ("test.direct.local", "2.0.0"): {
                    "values": {
                        "credential": "secret-a",
                        "runtime_path": str(tmp_path / "private-a"),
                        "device": "cpu",
                    },
                    "safe_fingerprint": "environment-a",
                }
            },
        )
    ) as first_client:
        project_id, compiled = _compile_one_node(first_client)
        first, _ = _start_run(
            first_client,
            project_id,
            compiled,
            "environment-a",
        )

    second_calls: list[str] = []
    with TestClient(
        create_app(
            frozen_catalog_override=_direct_catalog(
                second_calls,
                cacheable=True,
                readiness_checks=readiness,
            ),
            v2_environment_configuration={
                ("test.direct.local", "2.0.0"): {
                    "values": {
                        "credential": "secret-b",
                        "runtime_path": str(tmp_path / "private-b"),
                        "device": "accelerator-7",
                    },
                    "safe_fingerprint": "environment-b",
                }
            },
        )
    ) as second_client:
        loaded = second_client.get(
            f"/api/v2/projects/{project_id}/workflow"
        ).json()
        compiled_again = second_client.post(
            f"/api/v2/projects/{project_id}/workflow:compile",
            json={
                "workflow_revision": loaded["workflow_revision"],
                "workflow": loaded["workflow"],
            },
        ).json()
        second, _ = _start_run(
            second_client,
            project_id,
            compiled_again,
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


def test_changed_implementation_identity_misses_the_existing_project_cache(
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
        ("test.direct.local", "2.0.0"): {
            "values": {"credential": "credential-value"},
        }
    }
    first_calls: list[str] = []
    with TestClient(
        create_app(
            frozen_catalog_override=_direct_catalog(
                first_calls,
                cacheable=True,
                implementation_variant="algorithm-a",
            ),
            v2_environment_configuration=environment,
        )
    ) as first_client:
        project_id, compiled = _compile_one_node(first_client)
        first, _ = _start_run(
            first_client,
            project_id,
            compiled,
            "algorithm-a",
        )

    second_calls: list[str] = []
    with TestClient(
        create_app(
            frozen_catalog_override=_direct_catalog(
                second_calls,
                cacheable=True,
                execution_output="READY-B",
                implementation_variant="algorithm-b",
            ),
            v2_environment_configuration=environment,
        )
    ) as second_client:
        loaded = second_client.get(
            f"/api/v2/projects/{project_id}/workflow"
        ).json()
        unlocked = loaded["workflow"]
        unlocked["contract_lock"] = []
        saved = second_client.put(
            f"/api/v2/projects/{project_id}/workflow",
            json={
                "expected_workflow_revision": loaded["workflow_revision"],
                "workflow": unlocked,
            },
        ).json()
        relocked = second_client.post(
            f"/api/v2/projects/{project_id}/workflow:relock",
            json={"workflow_revision": saved["workflow_revision"]},
        ).json()
        compiled_b = second_client.post(
            f"/api/v2/projects/{project_id}/workflow:compile",
            json={
                "workflow_revision": relocked["workflow_revision"],
                "workflow": relocked["workflow"],
            },
        ).json()
        second, _ = _start_run(
            second_client,
            project_id,
            compiled_b,
            "algorithm-b",
        )

    assert first["outputs"][0]["values"] == ["READY"]
    assert second["outputs"][0]["values"] == ["READY-B"]
    assert (
        first["outputs"][0]["result_identity"]
        != second["outputs"][0]["result_identity"]
    )
    assert second["node_dispositions"][0]["resolution"] == "executed"
    assert "execute:test.direct.local" in second_calls


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
    app = create_app(
        frozen_catalog_override=_direct_catalog(
            calls,
            cacheable=True,
            node_parameter_declarations={
                "scientific_label": {
                    "parameter_scope": "scientific",
                    "scientific_meaning": (
                        "A result-affecting scientific fixture label"
                    ),
                    "type": "string",
                    "default": "alpha",
                }
            },
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.0.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _compile_one_node(client)
        first, _ = _start_run(client, project_id, compiled, "parameter-alpha")
        loaded = client.get(
            f"/api/v2/projects/{project_id}/workflow"
        ).json()
        changed = loaded["workflow"]
        changed["nodes"][0]["node_parameters"] = {
            "scientific_label": "beta"
        }
        saved = client.put(
            f"/api/v2/projects/{project_id}/workflow",
            json={
                "expected_workflow_revision": loaded["workflow_revision"],
                "workflow": changed,
            },
        ).json()
        compiled_beta = client.post(
            f"/api/v2/projects/{project_id}/workflow:compile",
            json={
                "workflow_revision": saved["workflow_revision"],
                "workflow": saved["workflow"],
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
    assert len(list((cache_root / project_id / "v2").rglob("*.json"))) == 2


def test_typed_codec_corruption_never_replays_or_overwrites(
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
    app = create_app(
        frozen_catalog_override=_direct_catalog(calls, cacheable=True),
        v2_environment_configuration={
            ("test.direct.local", "2.0.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _compile_one_node(client)
        _start_run(client, project_id, compiled, "populate")
        entry = next(
            (cache_root / project_id / "v2").rglob("*.json")
        )
        entry.write_bytes(b'{"not":"a typed codec entry"}')
        second, _ = _start_run(client, project_id, compiled, "corrupt")

    assert second["node_dispositions"][0]["resolution"] == "executed"
    assert [
        item for item in calls if item == "execute:test.direct.local"
    ] == [
        "execute:test.direct.local",
        "execute:test.direct.local",
    ]
    assert entry.read_bytes() == b'{"not":"a typed codec entry"}'


@pytest.mark.parametrize(
    ("termination", "expected_status"),
    (
        ("failed", "failed"),
        ("cancelled", "cancelled"),
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
    app = create_app(
        frozen_catalog_override=_direct_catalog(
            [],
            cacheable=True,
            execution_action=terminate,
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.0.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _compile_one_node(client)
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
    app = create_app(
        frozen_catalog_override=_direct_catalog(
            calls,
            cacheable=True,
            deterministic=False,
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.0.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _compile_one_node(client)
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
    app = create_app(
        frozen_catalog_override=_direct_catalog(
            calls,
            cacheable=True,
            source_identity={"kind": "unresolved"},
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.0.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _compile_one_node(client)
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


def test_standalone_path_outputs_are_never_stored_or_replayed(
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
    app = create_app(
        frozen_catalog_override=_artifact_catalog(
            calls,
            cacheable=True,
        )
    )

    with TestClient(app) as client:
        project_id, compiled = _compile_artifact_node(client)
        first, _ = _start_run(client, project_id, compiled, "artifact-a")
        second, _ = _start_run(client, project_id, compiled, "artifact-b")

    assert first["artifact_index"]
    assert second["artifact_index"]
    assert first["outputs"] == []
    assert second["outputs"] == []
    assert calls == ["workspace:True", "workspace:True"]
    assert not list((cache_root / project_id).rglob("*.json"))


def test_conflicting_output_for_one_result_identity_fails_without_overwrite(
    tmp_path,
    monkeypatch,
) -> None:
    state = {"value": "READY"}
    project_root = tmp_path / "projects"
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    app = create_app(
        frozen_catalog_override=_direct_catalog(
            [],
            cacheable=True,
            execution_output=lambda: state["value"],
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.0.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _compile_one_node(client)
        source, _ = _start_run(client, project_id, compiled, "source")
        original_entry = next(
            (cache_root / project_id / "v2").rglob("*.json")
        )
        original_bytes = original_entry.read_bytes()
        state["value"] = "CONFLICT"
        forced = client.post(
            f"/api/v2/projects/{project_id}/runs:derive",
            json={
                "source_run_id": source["run_id"],
                "compile_id": compiled["compile_id"],
                "policy": "force_selected",
                "node_ids": ["direct"],
                "client_request_id": "force-conflict",
            },
        )
        assert forced.status_code == 202
        forced_run_id = forced.json()["run_id"]
        projection = client.get(
            f"/api/v2/projects/{project_id}/runs/{forced_run_id}"
        ).json()
        events = client.app.state.run_execution_v2.public_events(
            project_id,
            forced_run_id,
        )

    terminal = next(
        item["event"]
        for item in events
        if item["event"]["type"] == "node_attempt_terminal"
    )
    assert projection["status"] == "failed"
    assert projection["outputs"] == []
    assert terminal["error"]["code"] == "cache_identity_conflict"
    assert original_entry.read_bytes() == original_bytes
