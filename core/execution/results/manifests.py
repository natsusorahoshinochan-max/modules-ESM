"""Private canonical codecs for immutable Result Store manifests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import re
from typing import Any, Literal, cast

from core.catalog.port_contract import canonical_json_bytes
from core.project.objects import StoredObject
from datatypes.exact_reference import ExactContractReference
from datatypes.i_json import freeze_i_json, thaw_i_json


PORT_VALUE_MANIFEST_NAMESPACE = "protein-workbench-port-value-manifest/v2"
NODE_RESULT_MANIFEST_NAMESPACE = "protein-workbench-node-result-manifest/v3"

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,127}$")


@dataclass(frozen=True, slots=True)
class _PortValueManifest:
    port_type: ExactContractReference
    multiplicity: Literal["one", "many"]
    content_digest: str
    values: tuple[StoredObject, ...]

    def canonical_projection(self) -> dict[str, Any]:
        return {
            "schema_namespace": PORT_VALUE_MANIFEST_NAMESPACE,
            "port_type": _reference_projection(self.port_type),
            "multiplicity": self.multiplicity,
            "content_digest": self.content_digest,
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
    result_identity: str
    result_contract_metadata: Mapping[str, Any]
    outputs: tuple[_NodeOutput, ...]
    artifacts: tuple[_NodeArtifact, ...]

    def canonical_projection(self) -> dict[str, Any]:
        return {
            "schema_namespace": NODE_RESULT_MANIFEST_NAMESPACE,
            "result_identity": self.result_identity,
            "result_contract_metadata": thaw_i_json(
                self.result_contract_metadata
            ),
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
        or set(value) != {"content_digest", "size"}
        or type(value["size"]) is not int
        or value["size"] < 0
    ):
        raise ValueError("immutable object reference is invalid")
    return StoredObject(
        _require_digest(value["content_digest"], "content_digest"),
        value["size"],
    )


def _reference_projection(reference: ExactContractReference) -> dict[str, str]:
    return {
        "contract_kind": reference.contract_kind,
        "contract_id": reference.contract_id,
        "contract_version": reference.contract_version,
        "contract_digest": reference.contract_digest,
    }


def _exact_reference(value: object) -> ExactContractReference:
    fields = {
        "contract_kind",
        "contract_id",
        "contract_version",
        "contract_digest",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError("exact Contract reference is invalid")
    return ExactContractReference(
        cast(str, value["contract_kind"]),
        cast(str, value["contract_id"]),
        cast(str, value["contract_version"]),
        cast(str, value["contract_digest"]),
    )


def _decode_json(encoded: bytes, *, error_message: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(encoded)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError(error_message) from error
    if not isinstance(payload, Mapping) or encoded != canonical_json_bytes(payload):
        raise ValueError(error_message)
    return payload


def _decode_port_manifest(encoded: bytes) -> _PortValueManifest:
    payload = _decode_json(encoded, error_message="Port Value Manifest is invalid")
    if set(payload) != {
        "schema_namespace",
        "port_type",
        "multiplicity",
        "content_digest",
        "values",
    } or payload["schema_namespace"] != PORT_VALUE_MANIFEST_NAMESPACE:
        raise ValueError("Port Value Manifest is invalid")
    multiplicity = payload["multiplicity"]
    values = payload["values"]
    if (
        multiplicity not in {"one", "many"}
        or not isinstance(values, list)
        or (multiplicity == "one" and len(values) != 1)
    ):
        raise ValueError("Port Value Manifest is invalid")
    return _PortValueManifest(
        port_type=_exact_reference(payload["port_type"]),
        multiplicity=multiplicity,
        content_digest=_require_digest(
            payload["content_digest"], "content_digest"
        ),
        values=tuple(_stored_object(value) for value in values),
    )


def _decode_node_manifest(encoded: bytes) -> _NodeResultManifest:
    payload = _decode_json(encoded, error_message="Node Result Manifest is invalid")
    if set(payload) != {
        "schema_namespace",
        "result_identity",
        "result_contract_metadata",
        "outputs",
        "artifacts",
    } or payload["schema_namespace"] != NODE_RESULT_MANIFEST_NAMESPACE:
        raise ValueError("Node Result Manifest is invalid")
    outputs = payload["outputs"]
    artifacts = payload["artifacts"]
    if (
        type(payload["result_contract_metadata"]) is not dict
        or not isinstance(outputs, list)
        or not isinstance(artifacts, list)
    ):
        raise ValueError("Node Result Manifest is invalid")
    decoded_outputs: list[_NodeOutput] = []
    seen_ports: set[str] = set()
    for output in outputs:
        if not isinstance(output, Mapping) or set(output) != {
            "output_port",
            "value_manifest",
        }:
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
        artifact_fields = set(artifact) if isinstance(artifact, Mapping) else set()
        if (
            not isinstance(artifact, Mapping)
            or (
                artifact_fields != required
                and artifact_fields != required | {"candidate_id"}
            )
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
        result_identity=_require_digest(
            payload["result_identity"], "result_identity"
        ),
        result_contract_metadata=freeze_i_json(
            payload["result_contract_metadata"]
        ),
        outputs=tuple(decoded_outputs),
        artifacts=tuple(decoded_artifacts),
    )


__all__: list[str] = []
