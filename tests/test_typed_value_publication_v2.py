"""Public contracts for immutable Typed Output value publication."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
import pytest

from core import ProjectManager
from core.project_objects import ProjectObjectStore
from core.server import create_app
from protein_workbench_public import validate_error
from tests.fixtures.public_v2 import (
    retrieve_service_typed_output_canonical_bytes,
    wait_for_testclient_run_terminal,
)
from tests.test_run_execution_v2 import _commit_pipeline, _pipeline_catalog


def _start_pipeline(client: TestClient) -> tuple[str, str, dict[str, object]]:
    project_id, committed = _commit_pipeline(client)
    started = client.post(
        f"/api/v2/projects/{project_id}/runs",
        json={
            "workflow_commit_id": committed["workflow_commit_id"],
            "client_request_id": "typed-value-publication",
        },
    )
    assert started.status_code == 202
    run_id = started.json()["run_id"]
    projection = wait_for_testclient_run_terminal(client, project_id, run_id)
    return project_id, run_id, projection


def test_run_projection_publishes_bounded_descriptors_and_exact_values(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        monkeypatch.setenv(
            f"PROTEIN_WORKBENCH_{name}_ROOT",
            str(tmp_path / name.lower()),
        )
    app = create_app(frozen_catalog_override=_pipeline_catalog(calls))

    with TestClient(app) as client:
        project_id, run_id, projection = _start_pipeline(client)

        assert projection["status"] == "succeeded"
        assert len(projection["outputs"]) == 2
        for descriptor in projection["outputs"]:
            assert set(descriptor) == {
                "node_id",
                "output_port",
                "port_type",
                "content_digest",
                "value_count",
                "value_manifest_reference",
                "result_identity",
                "materialization",
                "producer_provenance",
            }
            assert descriptor["value_count"] == 1
            assert "values" not in descriptor

            response = client.get(
                "/api/v2/projects/"
                f"{project_id}/runs/{run_id}/outputs/"
                f"{descriptor['node_id']}/{descriptor['output_port']}/values/0"
            )
            assert response.status_code == 200
            assert response.content == (
                b'{"port_type_id":"test.canonical_text",'
                b'"port_type_version":"2.1.0",'
                b'"schema_namespace":"protein-workbench-port-value/v2",'
                b'"value":"ready"}'
            )
            assert response.headers["content-type"] == "application/json"
            assert response.headers["content-length"] == str(
                len(response.content)
            )
            assert response.headers["digest"].startswith("sha256:")
            assert response.headers["etag"] == (
                f'"{response.headers["digest"]}"'
            )
            assert response.headers["x-port-content-digest"] == descriptor[
                "content_digest"
            ]
            assert response.headers["x-port-type-kind"] == descriptor[
                "port_type"
            ]["contract_kind"]
            assert response.headers["x-port-type-id"] == descriptor[
                "port_type"
            ]["contract_id"]
            assert response.headers["x-port-type-version"] == descriptor[
                "port_type"
            ]["contract_version"]
            assert response.headers["x-port-type-digest"] == descriptor[
                "port_type"
            ]["contract_digest"]
            assert response.headers["x-value-manifest-reference"] == (
                descriptor["value_manifest_reference"]
            )
            assert response.headers["x-value-index"] == "0"
            assert response.headers["x-value-count"] == "1"
            encoded_manifest = (
                app.state.run_execution_v2._object_store.read(
                    project_id,
                    descriptor["value_manifest_reference"],
                )
            )
            manifest = json.loads(encoded_manifest)
            assert manifest == {
                "schema_namespace": (
                    "protein-workbench-port-value-manifest/v1"
                ),
                "port_type": descriptor["port_type"],
                "multiplicity": "one",
                "content_digest": descriptor["content_digest"],
                "value_count": 1,
                "values": [
                    {
                        "index": 0,
                        "content_digest": response.headers["digest"],
                        "size": len(response.content),
                        "object": {
                            "content_digest": response.headers["digest"],
                            "size": len(response.content),
                        },
                    }
                ],
            }

        events = app.state.run_execution_v2.public_events(project_id, run_id)
        assert "ready" not in json.dumps(events)


def test_typed_value_retrieval_is_strictly_run_node_port_and_index_scoped(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        monkeypatch.setenv(
            f"PROTEIN_WORKBENCH_{name}_ROOT",
            str(tmp_path / name.lower()),
        )
    app = create_app(frozen_catalog_override=_pipeline_catalog([]))

    with TestClient(app) as client:
        project_id, run_id, projection = _start_pipeline(client)
        descriptor = projection["outputs"][0]
        suffixes = (
            f"missing/{descriptor['output_port']}/values/0",
            f"{descriptor['node_id']}/missing/values/0",
            (
                f"{descriptor['node_id']}/{descriptor['output_port']}"
                "/values/1"
            ),
        )
        for suffix in suffixes:
            response = client.get(
                f"/api/v2/projects/{project_id}/runs/{run_id}/outputs/{suffix}"
            )
            assert response.status_code == 404
            validate_error(response.json(), status=404)
            assert response.json()["error"]["code"] == (
                "typed_output_not_found"
            )


def test_project_object_store_deduplicates_exact_bytes(
    tmp_path: Path,
) -> None:
    projects = ProjectManager(
        tmp_path / "projects",
        output_root=tmp_path / "outputs",
    )
    project = projects.create("immutable object store")
    store = ProjectObjectStore(projects)
    payload = b"exact canonical value"

    first = store.put_exact(project.id, payload)
    repeated = store.put_exact(project.id, payload)

    assert repeated == first
    assert store.read(
        project.id,
        first.content_digest,
    ) == payload


def test_object_write_failure_closes_node_without_public_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        monkeypatch.setenv(
            f"PROTEIN_WORKBENCH_{name}_ROOT",
            str(tmp_path / name.lower()),
        )

    def fail_write(
        _store: ProjectObjectStore,
        _project_id: str,
        _payload: bytes,
    ) -> object:
        raise OSError("injected immutable object write failure")

    monkeypatch.setattr(ProjectObjectStore, "put_exact", fail_write)
    app = create_app(frozen_catalog_override=_pipeline_catalog([]))
    with TestClient(app) as client:
        project_id, run_id, projection = _start_pipeline(client)
        events = app.state.run_execution_v2.public_events(project_id, run_id)

    assert projection["status"] == "failed"
    assert projection["outputs"] == []
    assert {
        disposition["outcome"]
        for disposition in projection["node_dispositions"]
    } == {"failed", "blocked"}
    operation_terminal = next(
        item["event"]
        for item in events
        if item["event"]["type"] == "operation_attempt_terminal"
    )
    node_terminal = next(
        item["event"]
        for item in events
        if item["event"]["type"] == "node_attempt_terminal"
    )
    assert operation_terminal["status"] == "succeeded"
    assert "error" not in operation_terminal
    assert node_terminal["failure_origin"] == "publication"
    publication_error = dict(node_terminal["error"])
    assert publication_error.pop("correlation_id").startswith("incident-")
    assert publication_error == {
        "code": "node_publication_failed",
        "message": "Node result publication failed",
        "retryable": False,
        "details": {
            "node_id": "source",
            "publication_stage": "typed_value_object",
        },
    }


def _large_esm3_response(sequence: str, pae: object) -> object:
    import torch

    from tests.fixtures.esm3_generation import (
        ProviderResponse,
        three_residue_pdb,
    )

    length = len(sequence)
    return ProviderResponse(
        sequence,
        coordinates=torch.zeros((length, 37, 3), dtype=torch.float32),
        ptm=torch.tensor(0.75, dtype=torch.float32),
        plddt=torch.linspace(0.5, 0.9, length, dtype=torch.float32),
        pae=pae,
        pdb_string=three_residue_pdb(sequence),
    )


def test_registered_esm3_large_paired_values_round_trip_exactly(
    tmp_path: Path,
) -> None:
    import torch

    from tests.fixtures.esm3_generation import (
        ProviderClient,
        run_generation_from_prompt_fixture,
    )

    length = 291
    sequence = "A" * length
    pae = torch.linspace(
        0.0,
        31.75,
        length * length,
        dtype=torch.float32,
    ).reshape(length, length)
    responses = [
        _large_esm3_response(sequence, pae)
        for _ in range(4)
    ]
    service, catalog, projection, events = run_generation_from_prompt_fixture(
        tmp_path,
        operation="generate_paired",
        mode="coordinate_conditioned_291",
        client=ProviderClient(responses),
        num_samples=2,
    )

    assert projection["status"] == "succeeded"
    assert sequence not in json.dumps(events)
    outputs = {
        output["output_port"]: output
        for output in projection["outputs"]
        if output["node_id"] == "generate"
    }
    assert {
        "sequence_candidates",
        "structure_candidates",
        "counterpart_pairs",
        "confidence_facts",
        "sequence_reconstruction_candidates",
        "sequence_reconstruction_confidence_facts",
    } == set(outputs)
    retrieved_bytes = 0
    decoded: dict[str, Any] = {}
    for output_port, output in outputs.items():
        assert output["value_count"] == 1
        payload = retrieve_service_typed_output_canonical_bytes(
            service,
            projection,
            output,
            0,
        )
        reference = output["port_type"]
        codec = catalog.require_port_type(
            reference["contract_id"],
            reference["contract_version"],
        )
        value = codec.decode(payload)
        decoded[output_port] = value
        assert codec.encode(value) == payload
        assert codec.content_digest(value) == output["content_digest"]
        retrieved_bytes += len(payload)
    assert retrieved_bytes > 4 * 1024 * 1024
    assert len(
        retrieve_service_typed_output_canonical_bytes(
            service,
            projection,
            outputs["confidence_facts"],
            0,
        )
    ) > 3 * 1024 * 1024
    sequences = decoded["sequence_candidates"]
    structures = decoded["structure_candidates"]
    reconstructions = decoded["sequence_reconstruction_candidates"]
    pairs = decoded["counterpart_pairs"]
    confidence = decoded["confidence_facts"]
    reconstruction_confidence = decoded[
        "sequence_reconstruction_confidence_facts"
    ]
    assert len(sequences.items) == 2
    assert len(structures.items) == 2
    assert len(reconstructions.items) == 2
    assert len(pairs.entries) == 2
    assert len(confidence.entries) == 2
    assert len(reconstruction_confidence.entries) == 2
    assert [item.parent_ids for item in structures.items] == [
        (sequence_candidate.candidate_id,)
        for sequence_candidate in sequences.items
    ]
    assert [item.parent_ids for item in reconstructions.items] == [
        (sequence_candidate.candidate_id,)
        for sequence_candidate in sequences.items
    ]
    assert {
        item.metadata["prediction_key"] for item in structures.items
    } == {fact.prediction_key for fact in confidence.entries}
    assert {
        item.metadata["prediction_key"] for item in reconstructions.items
    } == {
        fact.prediction_key for fact in reconstruction_confidence.entries
    }
    for fact in (*confidence.entries, *reconstruction_confidence.entries):
        assert len(fact.plddt_per_residue) == length
        assert fact.pae is not None
        assert len(fact.pae) == length
        assert all(len(row) == length for row in fact.pae)
    assert len(
        retrieve_service_typed_output_canonical_bytes(
            service,
            projection,
            outputs["sequence_reconstruction_confidence_facts"],
            0,
        )
    ) > 3 * 1024 * 1024


def _generation_publication_transaction_size(
    tmp_path: Path,
    projection: dict[str, object],
) -> int:
    ledger = (
        tmp_path
        / "runs"
        / str(projection["project_id"])
        / str(projection["run_id"])
        / "ledger"
    )
    for path in sorted(ledger.glob("*.json")):
        transaction = json.loads(path.read_bytes())
        if any(
            fact["fact_type"] == "outputs_published"
            and fact["payload"]["node_id"] == "generate"
            for fact in transaction["facts"]
        ):
            return path.stat().st_size
    raise AssertionError("generate publication transaction was not committed")


def test_declared_hundred_samples_do_not_expand_ledger_transaction(
    tmp_path: Path,
) -> None:
    import torch

    from tests.fixtures.esm3_generation import (
        ProviderClient,
        ProviderResponse,
        run_generation,
    )

    def responses(count: int) -> list[object]:
        paired: list[object] = []
        for _ in range(count):
            paired.extend(
                [
                    ProviderResponse("ACD"),
                    ProviderResponse(
                        "ACD",
                        coordinates=torch.zeros((3, 37, 3)),
                        ptm=torch.tensor(0.75),
                        plddt=torch.tensor([0.7, 0.8, 0.9]),
                        pdb_string=(
                            "ATOM      1  CA  ALA A   1       "
                            "1.000   2.000   3.000  1.00 20.00           C  \n"
                            "ATOM      2  CA  CYS A   2       "
                            "2.000   3.000   4.000  1.00 20.00           C  \n"
                            "ATOM      3  CA  ASP A   3       "
                            "3.000   4.000   5.000  1.00 20.00           C  \n"
                            "TER\nEND\n"
                        ),
                    ),
                ]
            )
        return paired

    one_service, _, one, _ = run_generation(
        tmp_path / "one",
        operation="generate_paired",
        client=ProviderClient(responses(1)),
        num_samples=1,
    )
    hundred_service, _, hundred, _ = run_generation(
        tmp_path / "hundred",
        operation="generate_paired",
        client=ProviderClient(responses(100)),
        num_samples=100,
    )

    assert one["status"] == hundred["status"] == "succeeded"
    one_transaction_size = _generation_publication_transaction_size(
        tmp_path / "one",
        one,
    )
    hundred_transaction_size = _generation_publication_transaction_size(
        tmp_path / "hundred",
        hundred,
    )
    assert hundred_transaction_size <= one_transaction_size + 16
    assert hundred_transaction_size < 8 * 1024
    one_science_bytes = sum(
        len(
            retrieve_service_typed_output_canonical_bytes(
                one_service,
                one,
                output,
                value_index,
            )
        )
        for output in one["outputs"]
        if output["node_id"] == "generate"
        for value_index in range(output["value_count"])
    )
    hundred_science_bytes = sum(
        len(
            retrieve_service_typed_output_canonical_bytes(
                hundred_service,
                hundred,
                output,
                value_index,
            )
        )
        for output in hundred["outputs"]
        if output["node_id"] == "generate"
        for value_index in range(output["value_count"])
    )
    assert hundred_science_bytes > one_science_bytes * 50
