"""Retain already-validated public Run evidence for installed gates."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import json
import os
from pathlib import Path
from typing import Any

from protein_workbench_public import bundle_bytes, validate_event, validate_response


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.staging")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o600,
    )
    try:
        written = 0
        while written < len(payload):
            written += os.write(descriptor, payload[written:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _configured_root() -> Path | None:
    configured = os.environ.get("PROTEIN_WORKBENCH_FRESH_EVIDENCE_STAGING")
    tier = os.environ.get("PROTEIN_WORKBENCH_VERIFICATION_TIER")
    if configured is None and tier is None:
        return None
    if configured is None or tier is None:
        raise AssertionError("retained evidence configuration is incomplete")
    return Path(configured)


def _write_shared_documents(root: Path, catalog_bytes: bytes) -> None:
    documents = {
        "catalog-snapshot.json": catalog_bytes,
        "public-protocol.json": bundle_bytes(),
    }
    for name, payload in documents.items():
        path = root / name
        if path.exists():
            assert path.read_bytes() == payload
        else:
            _write(path, payload)


def _retain_run(
    run_label: str,
    *,
    catalog_bytes: bytes,
    projection: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    typed_value_reader: Callable[
        [Mapping[str, Any], int], tuple[Mapping[str, Any], bytes]
    ],
    artifact_reader: Callable[
        [Mapping[str, Any]], tuple[Mapping[str, Any], bytes]
    ],
) -> None:
    configured = _configured_root()
    if configured is None:
        return
    root = configured
    _write_shared_documents(root, catalog_bytes)

    run_root = root / "runs" / run_label
    run_root.mkdir(parents=True)
    (run_root / "values").mkdir()
    (run_root / "artifacts").mkdir()
    projection_document = dict(projection)
    _write(run_root / "projection.json", _canonical_bytes(projection_document))
    _write(run_root / "events.json", _canonical_bytes(list(events)))

    values = []
    for output in projection_document["outputs"]:
        for value_index in range(output["value_count"]):
            metadata, payload = typed_value_reader(output, value_index)
            relative_path = f"values/{len(values):06d}.bin"
            _write(run_root / relative_path, payload)
            values.append({
                "descriptor": metadata["typed_value"],
                "payload": relative_path,
            })
    _write(run_root / "typed-values.json", _canonical_bytes(values))

    artifacts = []
    for artifact in projection_document["artifact_index"]:
        descriptor, payload = artifact_reader(artifact)
        relative_path = f"artifacts/{len(artifacts):06d}.bin"
        _write(run_root / relative_path, payload)
        artifacts.append({
            "descriptor": dict(descriptor),
            "payload": relative_path,
        })
    _write(run_root / "artifacts.json", _canonical_bytes(artifacts))


def retain_service_run(
    run_label: str,
    *,
    catalog: Any,
    service: Any,
    projection: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
) -> None:
    """Retain one service-backed Run after its acceptance assertions pass."""
    validate_response("run_projection", 200, projection)
    for event in events:
        validate_event(event)
    project_id = projection["project_id"]
    run_id = projection["run_id"]

    def read_value(
        output: Mapping[str, Any],
        value_index: int,
    ) -> tuple[Mapping[str, Any], bytes]:
        return service.typed_value(
            project_id,
            run_id,
            output["node_id"],
            output["output_port"],
            value_index,
        )

    def read_artifact(
        artifact: Mapping[str, Any],
    ) -> tuple[Mapping[str, Any], bytes]:
        return service.artifact(
            project_id,
            run_id,
            artifact["artifact_reference"],
        )

    _retain_run(
        run_label,
        catalog_bytes=catalog.catalog_descriptor_bytes,
        projection=projection,
        events=events,
        typed_value_reader=read_value,
        artifact_reader=read_artifact,
    )


def retain_rest_run(
    run_label: str,
    *,
    catalog: Any,
    client: Any,
    projection: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
) -> None:
    """Retain one REST-backed Run after its acceptance assertions pass."""
    project_id = projection["project_id"]
    run_id = projection["run_id"]

    def read_value(
        output: Mapping[str, Any],
        value_index: int,
    ) -> tuple[Mapping[str, Any], bytes]:
        return client.typed_value(
            {
                "project_id": project_id,
                "run_id": run_id,
                "node_id": output["node_id"],
                "output_port": output["output_port"],
                "value_index": value_index,
            },
            dict(output),
        )

    def read_artifact(
        artifact: Mapping[str, Any],
    ) -> tuple[Mapping[str, Any], bytes]:
        payload = client.artifact(
            {
                "project_id": project_id,
                "run_id": run_id,
                "artifact_reference": artifact["artifact_reference"],
            },
            dict(artifact),
        )
        return artifact, payload

    _retain_run(
        run_label,
        catalog_bytes=catalog.catalog_descriptor_bytes,
        projection=projection,
        events=events,
        typed_value_reader=read_value,
        artifact_reader=read_artifact,
    )


def retain_proteinmpnn_lifecycle(
    *,
    load_count: int,
    release: str | None = None,
) -> None:
    """Retain the directly observed ProteinMPNN lifecycle facts."""
    configured = _configured_root()
    if configured is None:
        return
    receipt: dict[str, object] = {
        "model": "proteinmpnn",
        "load_count": load_count,
    }
    if release is not None:
        receipt["release"] = release
    _write(
        configured / "model-lifecycle.json",
        _canonical_bytes(receipt),
    )


def require_retained_evidence(
    root: Path,
    *,
    required_runs: tuple[str, ...],
    lifecycle_required: bool = False,
) -> None:
    """Require the exact lightweight file inventory for one acceptance tier."""
    expected_root_entries = {
        "catalog-snapshot.json",
        "public-protocol.json",
        "runs",
    }
    if lifecycle_required:
        expected_root_entries.add("model-lifecycle.json")
    assert {path.name for path in root.iterdir()} == expected_root_entries
    assert (root / "catalog-snapshot.json").is_file()
    assert (root / "public-protocol.json").is_file()
    assert tuple(path.name for path in sorted((root / "runs").iterdir())) == (
        tuple(sorted(required_runs))
    )

    for run_label in required_runs:
        run_root = root / "runs" / run_label
        assert (run_root / "values").is_dir()
        assert (run_root / "artifacts").is_dir()
        projection = json.loads((run_root / "projection.json").read_bytes())
        json.loads((run_root / "events.json").read_bytes())
        values = json.loads((run_root / "typed-values.json").read_bytes())
        artifacts = json.loads((run_root / "artifacts.json").read_bytes())
        assert len(values) == sum(
            output["value_count"] for output in projection["outputs"]
        )
        assert len(artifacts) == len(projection["artifact_index"])
        for retained in (*values, *artifacts):
            assert (run_root / retained["payload"]).is_file()

    if lifecycle_required:
        assert (root / "model-lifecycle.json").is_file()
