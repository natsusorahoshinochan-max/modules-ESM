"""Project-scoped reference-only replay index for committed Results."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import cast

from core.catalog.canonical import canonical_json_bytes
from core.project.manager import ProjectManager
from core.project.objects import StoredObject
from core.project.storage import (
    validate_identifier,
    write_new_file,
)


RESULT_CACHE_ENTRY_NAMESPACE = "protein-workbench-cache-entry/v5"

_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
_I_JSON_INTEGER_LIMIT = 9_007_199_254_740_991


class ResultIndexError(RuntimeError):
    """A replay index entry violates the current durable contract."""


@dataclass(frozen=True, slots=True)
class ReplayIndexEntry:
    """Manifest locator for one committed Node Result."""

    result_identity: str
    producer_run_id: str
    node_result_manifest: StoredObject


def _stored_object_to_canonical(value: StoredObject) -> dict[str, object]:
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
    content_digest = value["content_digest"]
    size = value["size"]
    if (
        type(content_digest) is not str
        or _SHA256.fullmatch(content_digest) is None
        or type(size) is not int
        or not 0 <= size <= _I_JSON_INTEGER_LIMIT
    ):
        raise ResultIndexError(f"Replay index {field} is invalid")
    return StoredObject(content_digest=content_digest, size=size)


def _entry_to_canonical(entry: ReplayIndexEntry) -> dict[str, object]:
    return {
        "schema_namespace": RESULT_CACHE_ENTRY_NAMESPACE,
        "result_identity": entry.result_identity,
        "producer_run_id": entry.producer_run_id,
        "node_result_manifest": _stored_object_to_canonical(
            entry.node_result_manifest
        ),
    }


def _entry_from_canonical(
    value: object,
    *,
    requested_result_identity: str,
) -> ReplayIndexEntry:
    fields = {
        "schema_namespace",
        "result_identity",
        "producer_run_id",
        "node_result_manifest",
    }
    if (
        type(value) is not dict
        or set(value) != fields
        or value["schema_namespace"] != RESULT_CACHE_ENTRY_NAMESPACE
        or value["result_identity"] != requested_result_identity
    ):
        raise ResultIndexError("Replay index entry is invalid")

    return ReplayIndexEntry(
        result_identity=requested_result_identity,
        producer_run_id=validate_identifier(
            cast(str, value["producer_run_id"]),
            "producer_run_id",
        ),
        node_result_manifest=_stored_object_from_canonical(
            value["node_result_manifest"],
            "node_result_manifest",
        ),
    )


def _encode_entry(entry: ReplayIndexEntry) -> bytes:
    return canonical_json_bytes(_entry_to_canonical(entry))


def _decode_entry(
    encoded: bytes,
    *,
    requested_result_identity: str,
) -> ReplayIndexEntry:
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
            "v5",
            "results",
            f"{result_identity.removeprefix('sha256:')}.json",
        )

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
            encoded = path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as error:
            raise ResultIndexError("Replay index entry is unavailable") from error
        return _decode_entry(
            encoded,
            requested_result_identity=result_identity,
        )

    def index(self, project_id: str, entry: ReplayIndexEntry) -> None:
        """Publish references once while retaining the original producer."""
        encoded = _encode_entry(entry)
        root = self._projects.result_cache_storage_root(project_id)
        try:
            write_new_file(
                root,
                self._relative_parts(entry.result_identity),
                encoded,
            )
        except FileExistsError:
            return


__all__ = [
    "ProjectReplayIndex",
    "RESULT_CACHE_ENTRY_NAMESPACE",
    "ReplayIndexEntry",
    "ResultIndexError",
]
