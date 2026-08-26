"""Private canonical codecs for immutable Result Store manifests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import re
from typing import Any, Literal

from core.project.objects import StoredObject


_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,127}$")


@dataclass(frozen=True, slots=True)
class _PortValueManifest:
    values: tuple[StoredObject, ...]

    def canonical_projection(self) -> dict[str, Any]:
        return {
            "values": [_object_projection(value) for value in self.values],
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

    def canonical_projection(self) -> dict[str, Any]:
        return {
            "outputs": [output.canonical_projection() for output in self.outputs],
            "artifacts": [
                artifact.canonical_projection() for artifact in self.artifacts
            ],
        }


def _require_identifier(value: object, field_name: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{field_name} is not a canonical identifier")
    return value


def _require_digest(value: object, field_name: str) -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{field_name} is not a canonical digest")
    return value


def _object_projection(reference: StoredObject) -> dict[str, Any]:
    return {
        "content_digest": reference.content_digest,
        "size": reference.size,
    }


def _stored_object(value: object) -> StoredObject:
    if (
        not isinstance(value, Mapping)
        or not {"content_digest", "size"} <= value.keys()
        or type(value["size"]) is not int
        or value["size"] < 0
    ):
        raise ValueError("immutable object reference is invalid")
    return StoredObject(
        _require_digest(value["content_digest"], "content_digest"),
        value["size"],
    )


def _decode_json(encoded: bytes, *, error_message: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(encoded)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError(error_message) from error
    if not isinstance(payload, Mapping):
        raise ValueError(error_message)
    return payload


def _decode_port_manifest(encoded: bytes) -> _PortValueManifest:
    payload = _decode_json(encoded, error_message="Port Value Manifest is invalid")
    if "values" not in payload:
        raise ValueError("Port Value Manifest is invalid")
    values = payload["values"]
    if not isinstance(values, list):
        raise ValueError("Port Value Manifest is invalid")
    return _PortValueManifest(
        values=tuple(_stored_object(value) for value in values),
    )


def _decode_node_manifest(encoded: bytes) -> _NodeResultManifest:
    payload = _decode_json(encoded, error_message="Node Result Manifest is invalid")
    required = {"outputs", "artifacts"}
    if not required <= payload.keys():
        raise ValueError("Node Result Manifest is invalid")
    outputs = payload["outputs"]
    artifacts = payload["artifacts"]
    if (
        not isinstance(outputs, list)
        or not isinstance(artifacts, list)
    ):
        raise ValueError("Node Result Manifest is invalid")
    decoded_outputs: list[_NodeOutput] = []
    seen_ports: set[str] = set()
    for output in outputs:
        if not isinstance(output, Mapping) or not {
            "output_port",
            "value_manifest",
        } <= output.keys():
            raise ValueError("Node Result Manifest is invalid")
        output_port = _require_identifier(output["output_port"], "output_port")
        if output_port in seen_ports:
            raise ValueError("Node Result Manifest contains duplicate outputs")
        seen_ports.add(output_port)
        decoded_outputs.append(
            _NodeOutput(
                output_port,
                _stored_object(output["value_manifest"]),
            )
        )
    decoded_artifacts: list[_NodeArtifact] = []
    for artifact in artifacts:
        required = {
            "artifact_kind",
            "output_port",
            "media_type",
            "filename",
            "body",
        }
        if (
            not isinstance(artifact, Mapping)
            or not required <= artifact.keys()
            or artifact["artifact_kind"] not in {"candidate", "standalone"}
            or type(artifact["media_type"]) is not str
            or type(artifact["filename"]) is not str
            or (
                "candidate_id" in artifact
                and type(artifact["candidate_id"]) is not str
            )
        ):
            raise ValueError("Node Result Manifest artifact is invalid")
        decoded_artifacts.append(
            _NodeArtifact(
                artifact_kind=artifact["artifact_kind"],
                output_port=_require_identifier(
                    artifact["output_port"], "output_port"
                ),
                media_type=artifact["media_type"],
                filename=artifact["filename"],
                body=_stored_object(artifact["body"]),
                candidate_id=artifact.get("candidate_id"),
            )
        )
    return _NodeResultManifest(
        outputs=tuple(decoded_outputs),
        artifacts=tuple(decoded_artifacts),
    )


__all__: list[str] = []
