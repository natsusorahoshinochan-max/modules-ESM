"""Startup ownership and collection for Project immutable objects."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import shutil
from typing import Any

from fastapi.testclient import TestClient
import pytest

from core.project import ProjectManager
from core.project_objects import ObjectIntegrityError, ProjectObjectStore
from core.server import create_app
from tests.fixtures.public_v2 import (
    retrieve_typed_output_values,
    wait_for_testclient_run_terminal,
)
from tests.test_run_execution_v2 import (
    _artifact_catalog,
    _commit_artifact_node,
    _commit_one_node,
    _direct_catalog,
    _object_path,
)


_ENVIRONMENT = {
    ("test.direct.local", "2.1.0"): {
        "values": {"credential": "credential-value"},
    }
}


def _configure_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Path]:
    roots = {
        name.lower(): tmp_path / name.lower()
        for name in ("PROJECT", "CACHE", "OUTPUT", "RUN")
    }
    for name, root in roots.items():
        monkeypatch.setenv(
            f"PROTEIN_WORKBENCH_{name.upper()}_ROOT",
            str(root),
        )
    return roots


def _start_one_run(
    client: TestClient,
    *,
    request_id: str,
) -> tuple[str, dict[str, Any]]:
    project_id, workflow_commit = _commit_one_node(client)
    started = client.post(
        f"/api/v2/projects/{project_id}/runs",
        json={
            "workflow_commit_id": workflow_commit["workflow_commit_id"],
            "client_request_id": request_id,
        },
    )
    assert started.status_code == 202
    projection = wait_for_testclient_run_terminal(
        client,
        project_id,
        started.json()["run_id"],
    )
    assert projection["status"] == "succeeded"
    return project_id, projection


def _restart_app(catalog):
    return create_app(
        frozen_catalog_override=catalog,
        v2_environment_configuration=_ENVIRONMENT,
    )


def test_startup_removes_orphan_objects_and_stale_staging_after_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots = _configure_roots(tmp_path, monkeypatch)
    catalog = _direct_catalog([], cacheable=True)

    with TestClient(_restart_app(catalog)) as client:
        project_id, projection = _start_one_run(
            client,
            request_id="gc-source",
        )
        orphan = client.app.state.run_execution_v2._object_store.put_exact(
            project_id,
            b"uncommitted publication bytes",
        )
        staging = client.app.state.project_manager.staging_dir(project_id)
        stale_writer = staging / "stale-writer"
        stale_writer.mkdir(parents=True)
        (stale_writer / "unfinished").write_bytes(b"private staging bytes")

    orphan_path = _object_path(
        roots["output"],
        project_id,
        orphan.content_digest,
    )
    assert orphan_path.is_file()
    assert stale_writer.is_dir()

    with TestClient(_restart_app(catalog)) as restarted:
        restored = restarted.get(
            f"/api/v2/projects/{project_id}/runs/{projection['run_id']}"
        )
        assert restored.status_code == 200
        assert restored.json()["status"] == "succeeded"
        assert retrieve_typed_output_values(
            restarted,
            project_id,
            projection["run_id"],
            projection["outputs"][0],
        ) == ["READY"]
        with pytest.raises(ObjectIntegrityError):
            restarted.app.state.run_execution_v2._object_store.read_exact(
                project_id,
                orphan.content_digest,
                size=orphan.size,
            )

    assert not orphan_path.exists()
    assert not stale_writer.exists()


def test_remaining_run_retains_content_shared_with_a_removed_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots = _configure_roots(tmp_path, monkeypatch)
    catalog = _direct_catalog([], cacheable=True)

    with TestClient(_restart_app(catalog)) as client:
        project_id, first = _start_one_run(
            client,
            request_id="shared-first",
        )
        active = client.get(
            f"/api/v2/projects/{project_id}/workflow/active-commit"
        ).json()
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": active["workflow_commit_id"],
                "client_request_id": "shared-second",
            },
        )
        second = wait_for_testclient_run_terminal(
            client,
            project_id,
            started.json()["run_id"],
        )
        assert second["node_dispositions"][0]["resolution"] == "cache_replayed"
        publication = next(
            fact
            for fact in client.app.state.run_execution_v2._runs[
                (project_id, second["run_id"])
            ].ledger.facts
            if fact["fact_type"] == "outputs_published"
        )
        manifest = publication["payload"]["node_result_manifest"]

    shutil.rmtree(roots["run"] / project_id / first["run_id"])
    shutil.rmtree(roots["cache"] / project_id)

    with TestClient(_restart_app(catalog)) as restarted:
        restored = restarted.get(
            f"/api/v2/projects/{project_id}/runs/{second['run_id']}"
        )
        assert restored.status_code == 200
        assert restored.json()["status"] == "succeeded"
        assert retrieve_typed_output_values(
            restarted,
            project_id,
            second["run_id"],
            second["outputs"][0],
        ) == ["READY"]
        assert restarted.app.state.run_execution_v2._object_store.read_exact(
            project_id,
            manifest["content_digest"],
            size=manifest["size"],
        )


def test_startup_retains_committed_artifact_and_its_node_manifests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots = _configure_roots(tmp_path, monkeypatch)
    catalog = _artifact_catalog([])

    with TestClient(_restart_app(catalog)) as client:
        project_id, workflow_commit = _commit_artifact_node(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": workflow_commit["workflow_commit_id"],
                "client_request_id": "artifact-owner",
            },
        )
        projection = wait_for_testclient_run_terminal(
            client,
            project_id,
            started.json()["run_id"],
        )
        artifact = projection["artifact_index"][0]
        orphan = client.app.state.run_execution_v2._object_store.put_exact(
            project_id,
            b"uncommitted artifact publication",
        )

    with TestClient(_restart_app(catalog)) as restarted:
        downloaded = restarted.get(
            f"/api/v2/projects/{project_id}/runs/{projection['run_id']}"
            f"/artifacts/{artifact['artifact_reference']}"
        )
        assert downloaded.status_code == 200
        assert downloaded.content == b"MODEL        1\nEND\n"

    assert not _object_path(
        roots["output"],
        project_id,
        orphan.content_digest,
    ).exists()


def test_active_writer_ownership_prevents_collection_until_released(
    tmp_path: Path,
) -> None:
    projects = ProjectManager(
        tmp_path / "projects",
        output_root=tmp_path / "outputs",
    )
    project_id = projects.create("active writer").id
    store = ProjectObjectStore(projects)

    with store.active_writer(project_id):
        owned = store.put_exact(project_id, b"active publication")
        store.collect_unreferenced(project_id, set())
        assert store.read_exact(
            project_id,
            owned.content_digest,
            size=owned.size,
        ) == b"active publication"

    store.collect_unreferenced(project_id, set())
    with pytest.raises(ObjectIntegrityError):
        store.read_exact(
            project_id,
            owned.content_digest,
            size=owned.size,
        )


@pytest.mark.parametrize("invalid_owner", ("ledger", "cache"))
def test_invalid_current_owner_blocks_collection_before_sweep(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid_owner: str,
) -> None:
    roots = _configure_roots(tmp_path, monkeypatch)
    catalog = _direct_catalog([], cacheable=True)

    with TestClient(_restart_app(catalog)) as client:
        project_id, projection = _start_one_run(
            client,
            request_id=f"invalid-{invalid_owner}",
        )
        orphan = client.app.state.run_execution_v2._object_store.put_exact(
            project_id,
            b"must survive unsafe collection",
        )

    if invalid_owner == "cache":
        invalid_path = next(
            (roots["cache"] / project_id / "v4" / "results").glob("*.json")
        )
    else:
        invalid_path = next(
            path
            for path in sorted(
                (roots["run"] / project_id / projection["run_id"] / "ledger").glob(
                    "*.json"
                )
            )
            if any(
                fact["fact_type"] == "outputs_published"
                for fact in json.loads(path.read_bytes())["facts"]
            )
        )
    invalid_path.write_bytes(b'{"damaged":"current owner"}')

    with TestClient(_restart_app(catalog)) as restarted:
        assert project_id in restarted.app.state.run_execution_v2.gc_failures
        assert restarted.app.state.run_execution_v2._object_store.read_exact(
            project_id,
            orphan.content_digest,
            size=orphan.size,
        ) == b"must survive unsafe collection"
        response = restarted.get(
            f"/api/v2/projects/{project_id}/runs/{projection['run_id']}"
        )
        if invalid_owner == "cache":
            assert response.status_code == 200
            assert response.json()["status"] == "succeeded"
        else:
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "evidence_unavailable"


def test_collection_failure_is_reported_without_rewriting_committed_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _configure_roots(tmp_path, monkeypatch)
    catalog = _direct_catalog([], cacheable=True)

    with TestClient(_restart_app(catalog)) as client:
        project_id, projection = _start_one_run(
            client,
            request_id="gc-failure",
        )

    def fail_collection(
        _store: ProjectObjectStore,
        _project_id: str,
        _roots: set[str],
    ) -> None:
        raise OSError("injected collection failure")

    monkeypatch.setattr(
        ProjectObjectStore,
        "collect_unreferenced",
        fail_collection,
    )
    caplog.set_level(logging.ERROR, logger="core.run_execution_v2")

    with TestClient(_restart_app(catalog)) as restarted:
        restored = restarted.get(
            f"/api/v2/projects/{project_id}/runs/{projection['run_id']}"
        )
        assert restored.status_code == 200
        assert restored.json()["status"] == "succeeded"
        assert retrieve_typed_output_values(
            restarted,
            project_id,
            projection["run_id"],
            projection["outputs"][0],
        ) == ["READY"]
        assert project_id in restarted.app.state.run_execution_v2.gc_failures

    assert any(
        record.message == "Project immutable-object collection failed"
        and record.project_id == project_id
        for record in caplog.records
    )
