"""Immutable Node results, restore, replay, and published-value reads."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal
import uuid

from core.catalog.port_contract import canonical_json_bytes
from core.execution.ledger import (
    LedgerAcknowledgement,
    PublishedArtifact,
    PublishedOutput,
)
from core.execution.output_admission import (
    AdmittedNodeOutput,
    NodeOutputPlan,
    restore_node_output,
)
from core.execution.output_admission.port_values import restore_admitted_port
from core.execution.results.cache import (
    IndexedOutput,
    ProjectReplayIndex,
    ReplayIndexEntry,
)
from core.execution.results.manifests import (
    MAX_NODE_RESULT_MANIFEST_BYTES,
    MAX_PORT_VALUE_MANIFEST_BYTES,
    _NodeArtifact,
    _NodeOutput,
    _NodeResultManifest,
    _PortValueManifest,
    _StoredValue,
    _decode_node_manifest,
    _decode_port_manifest,
    _exact_reference,
)
from core.operation import AdmittedPort
from core.project.objects import (
    ObjectIntegrityError,
    ProjectObjectStore,
    StoredObject,
)
from core.project.storage import StoragePathError
from datatypes.exact_reference import ExactContractReference
from datatypes.i_json import freeze_i_json, i_json_values_equal


class ResultStoreWriteError(RuntimeError):
    """One immutable Result staging step failed before Ledger publication."""

    def __init__(
        self,
        stage: Literal["typed_value_object", "artifact_object", "manifest"],
    ) -> None:
        self.stage = stage
        super().__init__("Node result staging failed")


class ResultIntegrityError(RuntimeError):
    """A persisted Result closure is unavailable or internally inconsistent."""

    def __init__(
        self,
        content_digest: str,
        *,
        expected_size: int | None = None,
    ) -> None:
        self.content_digest = content_digest
        self.expected_size = expected_size
        super().__init__("Stored Result integrity verification failed")


@dataclass(frozen=True, slots=True)
class StoredOutput:
    """One stored Port result and its current materialization provenance."""

    node_id: str
    output_port: str
    port_type: ExactContractReference
    content_digest: str
    value_count: int
    value_manifest: StoredObject
    materialization_run_id: str
    resolution: Literal["executed", "cache_replayed"]
    producer_run_id: str
    published_as_typed_output: bool


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    """One stored raw artifact body ready for Ledger publication."""

    artifact_reference: str
    artifact_kind: Literal["candidate", "standalone"]
    node_id: str
    output_port: str
    media_type: str
    filename: str
    body: StoredObject
    candidate_id: str | None = None


@dataclass(frozen=True, slots=True)
class StoredNodeResult:
    """Unpublished immutable result closure produced or restored by the store."""

    project_id: str
    node_id: str
    result_identity: str
    materialization_run_id: str
    producer_run_id: str
    resolution: Literal["executed", "cache_replayed"]
    result_contract_metadata: Mapping[str, Any]
    admitted_output: AdmittedNodeOutput = field(repr=False, compare=False)
    node_result_manifest: StoredObject
    outputs: tuple[StoredOutput, ...]
    artifacts: tuple[StoredArtifact, ...]

    def __post_init__(self) -> None:
        if type(self.admitted_output) is not AdmittedNodeOutput:
            raise TypeError("stored result requires one admitted Node output")
        object.__setattr__(
            self,
            "result_contract_metadata",
            freeze_i_json(self.result_contract_metadata),
        )
        object.__setattr__(self, "outputs", tuple(self.outputs))
        object.__setattr__(self, "artifacts", tuple(self.artifacts))

    @property
    def published_outputs(self) -> tuple[StoredOutput, ...]:
        return tuple(
            output for output in self.outputs if output.published_as_typed_output
        )


@dataclass(frozen=True, slots=True)
class TypedValueRead:
    """One exact canonical value read through published Ledger evidence."""

    canonical_bytes: bytes
    content_digest: str
    size: int


class ResultStore:
    """The sole owner of Node/Port manifests and project replay restoration."""

    def __init__(
        self,
        object_store: ProjectObjectStore,
        replay_index: ProjectReplayIndex,
    ) -> None:
        self._objects = object_store
        self._index = replay_index

    def _store_bytes(
        self,
        project_id: str,
        payload: bytes,
        *,
        stage: Literal["typed_value_object", "artifact_object", "manifest"],
    ) -> StoredObject:
        try:
            return self._objects.store(project_id, payload)
        except (ObjectIntegrityError, OSError, StoragePathError, ValueError) as error:
            raise ResultStoreWriteError(stage) from error

    def _read_reference(
        self,
        project_id: str,
        reference: StoredObject,
        *,
        maximum_size: int | None = None,
    ) -> bytes:
        if maximum_size is not None and reference.size > maximum_size:
            raise ResultIntegrityError(
                reference.content_digest,
                expected_size=reference.size,
            )
        try:
            payload = self._objects.read(project_id, reference.content_digest)
        except (ObjectIntegrityError, OSError, StoragePathError, ValueError) as error:
            raise ResultIntegrityError(
                reference.content_digest,
                expected_size=reference.size,
            ) from error
        if len(payload) != reference.size:
            raise ResultIntegrityError(
                reference.content_digest,
                expected_size=reference.size,
            )
        return payload

    def _store_port(
        self,
        project_id: str,
        output_port: str,
        admitted: AdmittedPort,
    ) -> tuple[_NodeOutput, _PortValueManifest]:
        values: list[_StoredValue] = []
        for index, value in enumerate(admitted.values):
            stored = self._store_bytes(
                project_id,
                value.canonical_bytes,
                stage="typed_value_object",
            )
            if stored.content_digest != value.content_digest:
                raise ResultStoreWriteError("typed_value_object")
            values.append(_StoredValue(index, stored))
        manifest = _PortValueManifest(
            port_type=_exact_reference(admitted.port_type),
            multiplicity=admitted.multiplicity,
            content_digest=admitted.content_digest,
            values=tuple(values),
        )
        encoded = canonical_json_bytes(manifest.canonical_projection())
        if len(encoded) > MAX_PORT_VALUE_MANIFEST_BYTES:
            raise ResultStoreWriteError("manifest")
        manifest_object = self._store_bytes(
            project_id,
            encoded,
            stage="manifest",
        )
        return (
            _NodeOutput(output_port, manifest.port_type, manifest_object),
            manifest,
        )

    def store(
        self,
        *,
        project_id: str,
        materialization_run_id: str,
        admitted_output: AdmittedNodeOutput,
        result_contract_metadata: Mapping[str, Any],
    ) -> StoredNodeResult:
        """Stage one admitted result without creating visibility or an index."""
        node_outputs: list[_NodeOutput] = []
        stored_outputs: list[StoredOutput] = []
        artifact_ports = set(
            admitted_output.artifact_publication_plan.artifact_output_ports
        )
        descriptors = {
            descriptor.output_port: descriptor
            for descriptor in admitted_output.evidence_descriptors
        }
        for output_port, admitted in admitted_output.ports.items():
            node_output, port_manifest = self._store_port(
                project_id,
                output_port,
                admitted,
            )
            node_outputs.append(node_output)
            descriptor = descriptors[output_port]
            stored_outputs.append(
                StoredOutput(
                    node_id=admitted_output.node_id,
                    output_port=output_port,
                    port_type=node_output.port_type,
                    content_digest=descriptor.content_digest,
                    value_count=len(port_manifest.values),
                    value_manifest=node_output.value_manifest,
                    materialization_run_id=materialization_run_id,
                    resolution="executed",
                    producer_run_id=materialization_run_id,
                    published_as_typed_output=output_port not in artifact_ports,
                )
            )
        node_artifacts: list[_NodeArtifact] = []
        stored_artifacts: list[StoredArtifact] = []
        for index, publication in enumerate(
            admitted_output.artifact_publication_plan.publications
        ):
            body = self._store_bytes(
                project_id,
                publication.body,
                stage="artifact_object",
            )
            node_artifact = _NodeArtifact(
                index=index,
                artifact_kind=publication.artifact_kind,
                output_port=publication.output_port,
                media_type=publication.media_type,
                filename=publication.filename,
                body=body,
                candidate_id=publication.candidate_id,
            )
            node_artifacts.append(node_artifact)
            stored_artifacts.append(
                self._stored_artifact(admitted_output.node_id, node_artifact)
            )
        metadata = freeze_i_json(result_contract_metadata)
        manifest = _NodeResultManifest(
            result_identity=admitted_output.result_identity,
            result_contract_metadata=metadata,
            outputs=tuple(node_outputs),
            artifacts=tuple(node_artifacts),
        )
        encoded = canonical_json_bytes(manifest.canonical_projection())
        if len(encoded) > MAX_NODE_RESULT_MANIFEST_BYTES:
            raise ResultStoreWriteError("manifest")
        manifest_object = self._store_bytes(
            project_id,
            encoded,
            stage="manifest",
        )
        return StoredNodeResult(
            project_id=project_id,
            node_id=admitted_output.node_id,
            result_identity=admitted_output.result_identity,
            materialization_run_id=materialization_run_id,
            producer_run_id=materialization_run_id,
            resolution="executed",
            result_contract_metadata=metadata,
            admitted_output=admitted_output,
            node_result_manifest=manifest_object,
            outputs=tuple(stored_outputs),
            artifacts=tuple(stored_artifacts),
        )

    @staticmethod
    def _stored_artifact(node_id: str, artifact: _NodeArtifact) -> StoredArtifact:
        return StoredArtifact(
            artifact_reference=f"artifact-{uuid.uuid4().hex}",
            artifact_kind=artifact.artifact_kind,
            node_id=node_id,
            output_port=artifact.output_port,
            media_type=artifact.media_type,
            filename=artifact.filename,
            body=artifact.body,
            candidate_id=artifact.candidate_id,
        )

    def _load_node_manifest(
        self,
        project_id: str,
        reference: StoredObject,
    ) -> _NodeResultManifest:
        encoded = self._read_reference(
            project_id,
            reference,
            maximum_size=MAX_NODE_RESULT_MANIFEST_BYTES,
        )
        try:
            return _decode_node_manifest(encoded)
        except (TypeError, ValueError) as error:
            raise ResultIntegrityError(
                reference.content_digest,
                expected_size=reference.size,
            ) from error

    def _restore_port(
        self,
        *,
        project_id: str,
        node_plan: NodeOutputPlan,
        output: _NodeOutput,
    ) -> tuple[AdmittedPort, _PortValueManifest]:
        declaration = node_plan.output_ports[output.output_port]
        encoded = self._read_reference(
            project_id,
            output.value_manifest,
            maximum_size=MAX_PORT_VALUE_MANIFEST_BYTES,
        )
        try:
            manifest = _decode_port_manifest(encoded)
        except (TypeError, ValueError) as error:
            raise ResultIntegrityError(
                output.value_manifest.content_digest,
                expected_size=output.value_manifest.size,
            ) from error
        expected_reference = _exact_reference(declaration.port_type.reference())
        if (
            output.port_type != expected_reference
            or manifest.port_type != expected_reference
            or manifest.multiplicity != declaration.multiplicity
        ):
            raise ResultIntegrityError(output.value_manifest.content_digest)
        canonical_values = tuple(
            self._read_reference(project_id, value.object)
            for value in manifest.values
        )
        try:
            admitted = restore_admitted_port(
                port_type=declaration.port_type,
                multiplicity=declaration.multiplicity,
                canonical_values=canonical_values,
                candidate_data_port_types=node_plan.candidate_data_port_types,
            )
        except (TypeError, ValueError) as error:
            raise ResultIntegrityError(output.value_manifest.content_digest) from error
        if admitted.content_digest != manifest.content_digest:
            raise ResultIntegrityError(output.value_manifest.content_digest)
        return admitted, manifest

    def restore(
        self,
        *,
        project_id: str,
        materialization_run_id: str,
        producer_run_id: str,
        node_plan: NodeOutputPlan,
        result_identity: str,
        result_contract_metadata: Mapping[str, Any],
        node_result_manifest: StoredObject,
    ) -> StoredNodeResult:
        """Restore one persisted result through the current exact Port codecs."""
        manifest = self._load_node_manifest(project_id, node_result_manifest)
        expected_metadata = freeze_i_json(result_contract_metadata)
        if (
            manifest.result_identity != result_identity
            or not i_json_values_equal(
                manifest.result_contract_metadata,
                expected_metadata,
            )
        ):
            raise ResultIntegrityError(node_result_manifest.content_digest)
        declared_ports = node_plan.output_ports
        produced_ports = tuple(output.output_port for output in manifest.outputs)
        if (
            any(output_port not in declared_ports for output_port in produced_ports)
            or produced_ports
            != tuple(
                output_port
                for output_port in declared_ports
                if output_port in produced_ports
            )
            or any(
                declaration.required and output_port not in produced_ports
                for output_port, declaration in declared_ports.items()
            )
        ):
            raise ResultIntegrityError(node_result_manifest.content_digest)
        restored_ports: dict[str, AdmittedPort] = {}
        stored_outputs: list[StoredOutput] = []
        artifact_ports = {
            declaration.output_port for declaration in node_plan.artifact_outputs
        }
        for output in manifest.outputs:
            admitted, port_manifest = self._restore_port(
                project_id=project_id,
                node_plan=node_plan,
                output=output,
            )
            restored_ports[output.output_port] = admitted
            stored_outputs.append(
                StoredOutput(
                    node_id=node_plan.node_id,
                    output_port=output.output_port,
                    port_type=output.port_type,
                    content_digest=port_manifest.content_digest,
                    value_count=len(port_manifest.values),
                    value_manifest=output.value_manifest,
                    materialization_run_id=materialization_run_id,
                    resolution="cache_replayed",
                    producer_run_id=producer_run_id,
                    published_as_typed_output=(
                        output.output_port not in artifact_ports
                    ),
                )
            )
        admitted_output = restore_node_output(
            plan=node_plan,
            result_identity=result_identity,
            ports=restored_ports,
        )
        publications = admitted_output.artifact_publication_plan.publications
        if len(publications) != len(manifest.artifacts):
            raise ResultIntegrityError(node_result_manifest.content_digest)
        stored_artifacts: list[StoredArtifact] = []
        for publication, artifact in zip(
            publications,
            manifest.artifacts,
            strict=True,
        ):
            body = self._read_reference(project_id, artifact.body)
            if (
                publication.output_port != artifact.output_port
                or publication.artifact_kind != artifact.artifact_kind
                or publication.media_type != artifact.media_type
                or publication.filename != artifact.filename
                or publication.candidate_id != artifact.candidate_id
                or publication.body != body
            ):
                raise ResultIntegrityError(node_result_manifest.content_digest)
            stored_artifacts.append(
                self._stored_artifact(node_plan.node_id, artifact)
            )
        return StoredNodeResult(
            project_id=project_id,
            node_id=node_plan.node_id,
            result_identity=result_identity,
            materialization_run_id=materialization_run_id,
            producer_run_id=producer_run_id,
            resolution="cache_replayed",
            result_contract_metadata=expected_metadata,
            admitted_output=admitted_output,
            node_result_manifest=node_result_manifest,
            outputs=tuple(stored_outputs),
            artifacts=tuple(stored_artifacts),
        )

    def lookup_replay(
        self,
        *,
        project_id: str,
        materialization_run_id: str,
        node_plan: NodeOutputPlan,
        result_identity: str,
        result_contract_metadata: Mapping[str, Any],
    ) -> StoredNodeResult | None:
        entry = self._index.lookup(project_id, result_identity)
        if entry is None:
            return None
        expected_metadata = freeze_i_json(result_contract_metadata)
        if not i_json_values_equal(
            entry.result_contract_metadata,
            expected_metadata,
        ):
            raise ResultIntegrityError(entry.node_result_manifest.content_digest)
        restored = self.restore(
            project_id=project_id,
            materialization_run_id=materialization_run_id,
            producer_run_id=entry.producer_run_id,
            node_plan=node_plan,
            result_identity=result_identity,
            result_contract_metadata=expected_metadata,
            node_result_manifest=entry.node_result_manifest,
        )
        indexed_outputs = tuple(
            IndexedOutput(output.output_port, output.value_manifest)
            for output in restored.outputs
        )
        if indexed_outputs != entry.outputs:
            raise ResultIntegrityError(entry.node_result_manifest.content_digest)
        return restored

    def index_committed_result(
        self,
        stored_result: StoredNodeResult,
        acknowledgement: LedgerAcknowledgement,
    ) -> None:
        """Index only an exact result paired with its durable Ledger ack."""
        if type(stored_result) is not StoredNodeResult:
            raise TypeError("index requires an exact StoredNodeResult")
        if type(acknowledgement) is not LedgerAcknowledgement:
            raise TypeError("index requires a durable Ledger acknowledgement")
        if stored_result.resolution != "executed":
            raise ValueError("only newly executed committed results are indexed")
        self._index.index(
            stored_result.project_id,
            ReplayIndexEntry(
                result_identity=stored_result.result_identity,
                result_contract_metadata=(
                    stored_result.result_contract_metadata
                ),
                producer_run_id=stored_result.producer_run_id,
                producer_node_id=stored_result.node_id,
                node_result_manifest=stored_result.node_result_manifest,
                outputs=tuple(
                    IndexedOutput(output.output_port, output.value_manifest)
                    for output in stored_result.outputs
                ),
            ),
        )

    def read_typed_value(
        self,
        project_id: str,
        output: PublishedOutput,
        value_index: int,
    ) -> TypedValueRead:
        """Read one canonical value authorized by published Ledger evidence."""
        if (
            type(value_index) is not int
            or value_index < 0
            or value_index >= output.value_count
        ):
            raise IndexError("Typed Value index is outside the published output")
        try:
            encoded = self._objects.read(
                project_id,
                output.value_manifest_reference,
            )
            if len(encoded) > MAX_PORT_VALUE_MANIFEST_BYTES:
                raise ValueError("Port Value Manifest exceeds its bound")
            manifest = _decode_port_manifest(encoded)
            if (
                manifest.port_type != output.port_type
                or manifest.content_digest != output.content_digest
                or len(manifest.values) != output.value_count
            ):
                raise ValueError("Published Port Value Manifest diverged")
            value = manifest.values[value_index]
            payload = self._read_reference(project_id, value.object)
        except (
            IndexError,
            ObjectIntegrityError,
            OSError,
            StoragePathError,
            TypeError,
            ValueError,
        ) as error:
            raise ResultIntegrityError(output.value_manifest_reference) from error
        return TypedValueRead(
            canonical_bytes=payload,
            content_digest=value.object.content_digest,
            size=value.object.size,
        )

    def read_artifact(
        self,
        project_id: str,
        artifact: PublishedArtifact,
    ) -> bytes:
        """Read one raw artifact body authorized by published Ledger evidence."""
        return self._read_reference(
            project_id,
            StoredObject(artifact.content_digest, artifact.size),
        )
