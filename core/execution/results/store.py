"""Immutable Node results, restore, replay, and published-value reads."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
import uuid

from core.catalog.canonical import canonical_json_bytes
from core.execution.ledger import (
    PublishedArtifact,
    PublishedOutput,
)
from core.execution.output_admission.admission import (
    AdmittedNodeOutput,
    NodeOutputPlan,
    restore_node_output,
)
from core.execution.output_admission.port_values import restore_admitted_port
from core.execution.results.cache import (
    ProjectReplayIndex,
    ReplayIndexEntry,
)
from core.execution.results.manifests import (
    _NodeArtifact,
    _NodeOutput,
    _NodeResultManifest,
    _PortValueManifest,
    _decode_node_manifest,
    _decode_port_manifest,
)
from core.operation import AdmittedPort
from core.project.objects import (
    ObjectIntegrityError,
    ProjectObjectStore,
    StoredObject,
)
from core.project.storage import StoragePathError


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
class StoredNodeResult:
    """Unpublished immutable result closure produced or restored by the store."""

    project_id: str
    result_identity: str
    producer_run_id: str
    admitted_output: AdmittedNodeOutput = field(repr=False, compare=False)
    node_result_manifest: StoredObject
    outputs: tuple[PublishedOutput, ...]
    artifacts: tuple[PublishedArtifact, ...]


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
        except (ObjectIntegrityError, OSError, StoragePathError) as error:
            raise ResultStoreWriteError(stage) from error

    def _read_reference(
        self,
        project_id: str,
        reference: StoredObject,
    ) -> bytes:
        try:
            payload = self._objects.read(project_id, reference.content_digest)
        except (ObjectIntegrityError, StoragePathError) as error:
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
    ) -> _NodeOutput:
        values: list[StoredObject] = []
        for value in admitted.values:
            stored = self._store_bytes(
                project_id,
                value.canonical_bytes,
                stage="typed_value_object",
            )
            values.append(stored)
        manifest = _PortValueManifest(
            values=tuple(values),
        )
        encoded = canonical_json_bytes(manifest.canonical_projection())
        manifest_object = self._store_bytes(
            project_id,
            encoded,
            stage="manifest",
        )
        return _NodeOutput(output_port, manifest_object)

    def store(
        self,
        *,
        project_id: str,
        materialization_run_id: str,
        admitted_output: AdmittedNodeOutput,
    ) -> StoredNodeResult:
        """Stage one admitted result without creating visibility or an index."""
        node_outputs: list[_NodeOutput] = []
        published_outputs: list[PublishedOutput] = []
        artifact_ports = set(
            admitted_output.artifact_publication_plan.artifact_output_ports
        )
        descriptors = {
            descriptor.output_port: descriptor
            for descriptor in admitted_output.evidence_descriptors
        }
        for output_port, admitted in admitted_output.ports.items():
            node_output = self._store_port(
                project_id,
                output_port,
                admitted,
            )
            node_outputs.append(node_output)
            descriptor = descriptors[output_port]
            if output_port not in artifact_ports:
                published_outputs.append(
                    PublishedOutput(
                        output_port=output_port,
                        port_type=admitted.port_type,
                        content_digest=descriptor.content_digest,
                        materialization={
                            "run_id": materialization_run_id,
                            "resolution": "executed",
                        },
                        producer_run_id=materialization_run_id,
                        value_count=len(admitted.values),
                        value_manifest_reference=(
                            node_output.value_manifest.content_digest
                        ),
                    )
                )
        node_artifacts: list[_NodeArtifact] = []
        published_artifacts: list[PublishedArtifact] = []
        for publication in (
            admitted_output.artifact_publication_plan.publications
        ):
            body = self._store_bytes(
                project_id,
                publication.body,
                stage="artifact_object",
            )
            node_artifact = _NodeArtifact(
                artifact_kind=publication.artifact_kind,
                output_port=publication.output_port,
                media_type=publication.media_type,
                filename=publication.filename,
                body=body,
                candidate_id=publication.candidate_id,
            )
            node_artifacts.append(node_artifact)
            published_artifacts.append(
                self._published_artifact(node_artifact)
            )
        manifest = _NodeResultManifest(
            outputs=tuple(node_outputs),
            artifacts=tuple(node_artifacts),
        )
        encoded = canonical_json_bytes(manifest.canonical_projection())
        manifest_object = self._store_bytes(
            project_id,
            encoded,
            stage="manifest",
        )
        return StoredNodeResult(
            project_id=project_id,
            result_identity=admitted_output.result_identity,
            producer_run_id=materialization_run_id,
            admitted_output=admitted_output,
            node_result_manifest=manifest_object,
            outputs=tuple(published_outputs),
            artifacts=tuple(published_artifacts),
        )

    @staticmethod
    def _published_artifact(
        artifact: _NodeArtifact,
    ) -> PublishedArtifact:
        return PublishedArtifact(
            artifact_reference=f"artifact-{uuid.uuid4().hex}",
            artifact_kind=artifact.artifact_kind,
            output_port=artifact.output_port,
            media_type=artifact.media_type,
            filename=artifact.filename,
            size=artifact.body.size,
            content_digest=artifact.body.content_digest,
            candidate_id=artifact.candidate_id,
        )

    def _load_node_manifest(
        self,
        project_id: str,
        reference: StoredObject,
    ) -> _NodeResultManifest:
        encoded = self._read_reference(project_id, reference)
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
    ) -> AdmittedPort:
        declaration = node_plan.output_ports[output.output_port]
        encoded = self._read_reference(project_id, output.value_manifest)
        try:
            manifest = _decode_port_manifest(encoded)
        except (TypeError, ValueError) as error:
            raise ResultIntegrityError(
                output.value_manifest.content_digest,
                expected_size=output.value_manifest.size,
            ) from error
        canonical_values = tuple(
            self._read_reference(project_id, value)
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
        return admitted

    def restore(
        self,
        *,
        project_id: str,
        materialization_run_id: str,
        producer_run_id: str,
        node_plan: NodeOutputPlan,
        result_identity: str,
        node_result_manifest: StoredObject,
    ) -> StoredNodeResult:
        """Restore one persisted result through the current exact Port codecs."""
        manifest = self._load_node_manifest(project_id, node_result_manifest)
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
        published_outputs: list[PublishedOutput] = []
        artifact_ports = {
            declaration.output_port for declaration in node_plan.artifact_outputs
        }
        for output in manifest.outputs:
            admitted = self._restore_port(
                project_id=project_id,
                node_plan=node_plan,
                output=output,
            )
            restored_ports[output.output_port] = admitted
            if output.output_port not in artifact_ports:
                published_outputs.append(
                    PublishedOutput(
                        output_port=output.output_port,
                        port_type=admitted.port_type,
                        content_digest=admitted.content_digest,
                        materialization={
                            "run_id": materialization_run_id,
                            "resolution": "cache_replayed",
                        },
                        producer_run_id=producer_run_id,
                        value_count=len(admitted.values),
                        value_manifest_reference=(
                            output.value_manifest.content_digest
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
        published_artifacts: list[PublishedArtifact] = []
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
            published_artifacts.append(
                self._published_artifact(artifact)
            )
        return StoredNodeResult(
            project_id=project_id,
            result_identity=result_identity,
            producer_run_id=producer_run_id,
            admitted_output=admitted_output,
            node_result_manifest=node_result_manifest,
            outputs=tuple(published_outputs),
            artifacts=tuple(published_artifacts),
        )

    def lookup_replay(
        self,
        *,
        project_id: str,
        materialization_run_id: str,
        node_plan: NodeOutputPlan,
        result_identity: str,
    ) -> StoredNodeResult | None:
        entry = self._index.lookup(project_id, result_identity)
        if entry is None:
            return None
        return self.restore(
            project_id=project_id,
            materialization_run_id=materialization_run_id,
            producer_run_id=entry.producer_run_id,
            node_plan=node_plan,
            result_identity=result_identity,
            node_result_manifest=entry.node_result_manifest,
        )

    def index_committed_result(
        self,
        stored_result: StoredNodeResult,
    ) -> None:
        """Index a freshly executed result after Ledger publication."""
        self._index.index(
            stored_result.project_id,
            ReplayIndexEntry(
                result_identity=stored_result.result_identity,
                producer_run_id=stored_result.producer_run_id,
                node_result_manifest=stored_result.node_result_manifest,
            ),
        )

    def read_typed_value(
        self,
        project_id: str,
        output: PublishedOutput,
        value_index: int,
    ) -> tuple[bytes, StoredObject]:
        """Read one canonical value authorized by published Ledger evidence."""
        try:
            encoded = self._objects.read(
                project_id,
                output.value_manifest_reference,
            )
            manifest = _decode_port_manifest(encoded)
            value = manifest.values[value_index]
            payload = self._read_reference(project_id, value)
        except (
            ObjectIntegrityError,
            OSError,
            StoragePathError,
            ValueError,
        ) as error:
            raise ResultIntegrityError(output.value_manifest_reference) from error
        return payload, value

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
