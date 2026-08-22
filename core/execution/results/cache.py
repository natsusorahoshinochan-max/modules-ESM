"""Project-scoped reference-only replay index for committed Results."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from core.catalog.port_contract import canonical_json_bytes
from core.project.manager import ProjectManager
from core.project.objects import StoredObject
from core.project.storage import (
    StoragePathError,
    validate_identifier,
    write_new_file,
)
from datatypes.exact_reference import validate_canonical_identifier
from datatypes.i_json import freeze_i_json, thaw_i_json


RESULT_CACHE_ENTRY_NAMESPACE = "protein-workbench-cache-entry/v4"
MAX_RESULT_CACHE_ENTRY_BYTES = 4 * 1024 * 1024

_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
_I_JSON_INTEGER_LIMIT = 9_007_199_254_740_991


class ResultIndexError(RuntimeError):
    """A replay index entry violates the current durable contract."""


def _require_result_identity(value: object) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ResultIndexError("Result identity is not a canonical digest")
    return value


def _require_canonical_identifier(value: object, field: str) -> str:
    try:
        return validate_canonical_identifier(value, field)
    except ValueError as error:
        raise ResultIndexError(f"Replay index {field} is invalid") from error


def _require_storage_identifier(value: object, field: str) -> str:
    if type(value) is not str:
        raise ResultIndexError(f"Replay index {field} is invalid")
    try:
        return validate_identifier(value, field)
    except StoragePathError as error:
        raise ResultIndexError(f"Replay index {field} is invalid") from error


def _require_stored_object(
    value: object,
    field: str,
) -> StoredObject:
    if (
        type(value) is not StoredObject
        or type(value.content_digest) is not str
        or _SHA256.fullmatch(value.content_digest) is None
        or type(value.size) is not int
        or not 0 <= value.size <= _I_JSON_INTEGER_LIMIT
    ):
        raise ResultIndexError(f"Replay index {field} is invalid")
    return value


@dataclass(frozen=True, slots=True)
class IndexedOutput:
    """One output reference retained by the replay index."""

    output_port: str
    value_manifest: StoredObject


@dataclass(frozen=True, slots=True)
class ReplayIndexEntry:
    """Reference-only replay metadata for one committed Node Result."""

    result_identity: str
    result_contract_metadata: Mapping[str, Any]
    producer_run_id: str
    producer_node_id: str
    node_result_manifest: StoredObject
    outputs: tuple[IndexedOutput, ...]


def _stored_object_to_canonical(value: StoredObject) -> dict[str, Any]:
    return {
        "content_digest": value.content_digest,
        "size": value.size,
    }


def _stored_object_from_canonical(
    value: object,
    field: str,
) -> StoredObject:
    if type(value) is not dict or set(value) != {"content_digest", "size"}:
        raise ResultIndexError(f"Replay index {field} is invalid")
    stored = StoredObject(
        content_digest=value["content_digest"],
        size=value["size"],
    )
    return _require_stored_object(stored, field)


def _entry_to_canonical(entry: ReplayIndexEntry) -> dict[str, Any]:
    return {
        "schema_namespace": RESULT_CACHE_ENTRY_NAMESPACE,
        "result_identity": entry.result_identity,
        "result_contract_metadata": thaw_i_json(
            entry.result_contract_metadata
        ),
        "producer": {
            "producer_run_id": entry.producer_run_id,
            "producer_node_id": entry.producer_node_id,
        },
        "node_result_manifest": _stored_object_to_canonical(
            entry.node_result_manifest
        ),
        "outputs": [
            {
                "output_port": output.output_port,
                "value_manifest": _stored_object_to_canonical(
                    output.value_manifest
                ),
            }
            for output in entry.outputs
        ],
    }


def _entry_from_canonical(
    value: object,
    *,
    requested_result_identity: str,
) -> ReplayIndexEntry:
    fields = {
        "schema_namespace",
        "result_identity",
        "result_contract_metadata",
        "producer",
        "node_result_manifest",
        "outputs",
    }
    if (
        type(value) is not dict
        or set(value) != fields
        or value["schema_namespace"] != RESULT_CACHE_ENTRY_NAMESPACE
        or value["result_identity"] != requested_result_identity
        or type(value["result_contract_metadata"]) is not dict
        or type(value["producer"]) is not dict
        or set(value["producer"])
        != {"producer_run_id", "producer_node_id"}
        or type(value["outputs"]) is not list
    ):
        raise ResultIndexError("Replay index entry is invalid")

    try:
        metadata = freeze_i_json(value["result_contract_metadata"])
        _require_result_identity(value["result_identity"])
        producer = value["producer"]
        producer_run_id = _require_storage_identifier(
            producer["producer_run_id"],
            "producer_run_id",
        )
        producer_node_id = _require_storage_identifier(
            producer["producer_node_id"],
            "producer_node_id",
        )
    except (TypeError, ValueError) as error:
        raise ResultIndexError("Replay index entry is invalid") from error

    outputs: list[IndexedOutput] = []
    output_ports: set[str] = set()
    for raw_output in value["outputs"]:
        if (
            type(raw_output) is not dict
            or set(raw_output) != {"output_port", "value_manifest"}
        ):
            raise ResultIndexError("Replay index output is invalid")
        output_port = _require_canonical_identifier(
            raw_output["output_port"],
            "output_port",
        )
        if output_port in output_ports:
            raise ResultIndexError("Replay index output ports are not unique")
        output_ports.add(output_port)
        outputs.append(
            IndexedOutput(
                output_port=output_port,
                value_manifest=_stored_object_from_canonical(
                    raw_output["value_manifest"],
                    "value_manifest",
                ),
            )
        )

    return ReplayIndexEntry(
        result_identity=value["result_identity"],
        result_contract_metadata=metadata,
        producer_run_id=producer_run_id,
        producer_node_id=producer_node_id,
        node_result_manifest=_stored_object_from_canonical(
            value["node_result_manifest"],
            "node_result_manifest",
        ),
        outputs=tuple(outputs),
    )


def _encode_entry(entry: ReplayIndexEntry) -> bytes:
    encoded = canonical_json_bytes(_entry_to_canonical(entry))
    if len(encoded) > MAX_RESULT_CACHE_ENTRY_BYTES:
        raise ResultIndexError("Replay index entry exceeds its size contract")
    return encoded


def _decode_entry(
    encoded: bytes,
    *,
    requested_result_identity: str,
) -> ReplayIndexEntry:
    if len(encoded) > MAX_RESULT_CACHE_ENTRY_BYTES:
        raise ResultIndexError("Replay index entry exceeds its size contract")
    try:
        raw = json.loads(encoded)
        if canonical_json_bytes(raw) != encoded:
            raise ResultIndexError("Replay index entry is not canonical JSON")
        entry = _entry_from_canonical(
            raw,
            requested_result_identity=requested_result_identity,
        )
        return entry
    except ResultIndexError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError, UnicodeError) as error:
        raise ResultIndexError("Replay index entry is invalid") from error


class ProjectReplayIndex:
    """Filesystem replay index scoped by the owning Project Manager."""

    def __init__(self, projects: ProjectManager) -> None:
        self._projects = projects

    @staticmethod
    def _relative_parts(result_identity: str) -> tuple[str, ...]:
        return (
            "v4",
            "results",
            f"{result_identity.removeprefix('sha256:')}.json",
        )

    @staticmethod
    def _read(path: Path) -> bytes:
        try:
            with path.open("rb") as stream:
                encoded = stream.read(MAX_RESULT_CACHE_ENTRY_BYTES + 1)
        except FileNotFoundError:
            raise
        except OSError as error:
            raise ResultIndexError("Replay index entry is unavailable") from error
        if len(encoded) > MAX_RESULT_CACHE_ENTRY_BYTES:
            raise ResultIndexError(
                "Replay index entry exceeds its size contract"
            )
        return encoded

    def lookup(
        self,
        project_id: str,
        result_identity: str,
    ) -> ReplayIndexEntry | None:
        """Return the exact indexed references, or miss only when absent."""
        parts = self._relative_parts(result_identity)
        root = self._projects.result_cache_storage_root(project_id)
        path = root.joinpath(*parts)
        try:
            encoded = self._read(path)
        except FileNotFoundError:
            return None
        return _decode_entry(
            encoded,
            requested_result_identity=result_identity,
        )

    def index(self, project_id: str, entry: ReplayIndexEntry) -> None:
        """Publish references once while retaining the original producer."""
        encoded = _encode_entry(entry)
        existing = self.lookup(project_id, entry.result_identity)
        if existing is not None:
            return
        root = self._projects.result_cache_storage_root(project_id)
        try:
            write_new_file(
                root,
                self._relative_parts(entry.result_identity),
                encoded,
            )
        except FileExistsError:
            if self.lookup(project_id, entry.result_identity) is None:
                raise ResultIndexError(
                    "Replay index publication did not retain an entry"
                )


__all__ = [
    "IndexedOutput",
    "MAX_RESULT_CACHE_ENTRY_BYTES",
    "ProjectReplayIndex",
    "RESULT_CACHE_ENTRY_NAMESPACE",
    "ReplayIndexEntry",
    "ResultIndexError",
]
