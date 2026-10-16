"""Private canonical codecs for immutable Result Store manifests."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any, Literal

from core.project.objects import StoredObject
from datatypes.candidate import CandidateDataReference


@dataclass(frozen=True, slots=True)
class _PortValueManifest:
    values: tuple[StoredObject, ...]
    candidate_data: tuple[tuple[CandidateDataReference, ...], ...]
    content_digest: str

    def canonical_projection(self) -> dict[str, Any]:
        return {
            "content_digest": self.content_digest,
            "values": [_object_projection(value) for value in self.values],
            "candidate_data": [[asdict(reference) for reference in values] for values in self.candidate_data],
        }


@dataclass(frozen=True, slots=True)
class _NodeOutput:
    output_port: str
    value_manifest: StoredObject

    def canonical_projection(self) -> dict[str, Any]:
        return {
            "output_port": self.output_port,
            "value_manifest": _object_projection(self.value_manifest),
        }


@dataclass(frozen=True, slots=True)
class _NodeArtifact:
    artifact_kind: Literal["candidate", "standalone"]
    output_port: str
    media_type: str
    filename: str
    body: StoredObject
    candidate_id: str | None

    def canonical_projection(self) -> dict[str, Any]:
        projected: dict[str, Any] = {
            "artifact_kind": self.artifact_kind,
            "output_port": self.output_port,
            "media_type": self.media_type,
            "filename": self.filename,
            "body": _object_projection(self.body),
        }
        if self.candidate_id is not None:
            projected["candidate_id"] = self.candidate_id
        return projected


@dataclass(frozen=True, slots=True)
class _NodeResultManifest:
    outputs: tuple[_NodeOutput, ...]
    artifacts: tuple[_NodeArtifact, ...]
    continuation_state: dict[str, Any] | None = None

    def canonical_projection(self) -> dict[str, Any]:
        return {
            **({"continuation_state": self.continuation_state}
               if self.continuation_state is not None else {}),
            "outputs": [output.canonical_projection() for output in self.outputs],
            "artifacts": [
                artifact.canonical_projection() for artifact in self.artifacts
            ],
        }


def _object_projection(value: StoredObject) -> dict[str, Any]:
    return asdict(value)


def _decode_port_manifest(encoded: bytes) -> _PortValueManifest:
    payload = json.loads(encoded)
    return _PortValueManifest(
        values=tuple(StoredObject(**value) for value in payload["values"]),
        candidate_data=tuple(tuple(CandidateDataReference(**reference) for reference in items)
                             for items in payload["candidate_data"]),
        content_digest=payload["content_digest"],
    )


def _decode_node_manifest(encoded: bytes) -> _NodeResultManifest:
    payload = json.loads(encoded)
    return _NodeResultManifest(
        continuation_state=payload.get("continuation_state"),
        outputs=tuple(_NodeOutput(item["output_port"], StoredObject(**item["value_manifest"]))
                      for item in payload["outputs"]),
        artifacts=tuple(_NodeArtifact(
            artifact_kind=item["artifact_kind"], output_port=item["output_port"],
            media_type=item["media_type"], filename=item["filename"],
            body=StoredObject(**item["body"]), candidate_id=item.get("candidate_id"),
        ) for item in payload["artifacts"]),
    )
