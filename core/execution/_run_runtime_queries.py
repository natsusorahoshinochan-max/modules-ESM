"""Read-only Run Runtime use cases over committed Ledger evidence."""

from __future__ import annotations

from typing import Any

from core.execution._run_runtime_registry import _RunRegistry
from core.execution.ledger import (
    Fact,
    PublishedOutput,
    ReplayWindow,
    RunCursor,
    RunProjection,
    V2RunError,
)
from core.execution.results.store import ResultIntegrityError, ResultStore


class _RunQueries:
    """Resolve committed projections and Result Store payloads."""

    def __init__(
        self,
        *,
        registry: _RunRegistry,
        result_store: ResultStore,
    ) -> None:
        self._registry = registry
        self._result_store = result_store

    def projection(self, project_id: str, run_id: str) -> RunProjection:
        record = self._registry.require_record(project_id, run_id)
        self._registry.require_available_evidence(record)
        return record.ledger.projection()

    @staticmethod
    def _typed_value_integrity_error(
        descriptor: PublishedOutput,
        value_index: int,
        *,
        expected_digest: str,
        expected_size: int | None = None,
    ) -> V2RunError:
        details: dict[str, Any] = {
            "node_id": descriptor.node_id,
            "output_port": descriptor.output_port,
            "value_index": value_index,
            "expected_digest": expected_digest,
        }
        if expected_size is not None:
            details["expected_size"] = expected_size
        return V2RunError(
            "typed_value_integrity_mismatch",
            "Typed Output value failed integrity verification",
            details=details,
        )

    def typed_value(
        self,
        project_id: str,
        run_id: str,
        node_id: str,
        output_port: str,
        value_index: int,
    ) -> tuple[dict[str, Any], bytes]:
        """Resolve one exact canonical value through committed evidence."""
        record = self._registry.require_record(project_id, run_id)
        descriptor = next(
            (
                output
                for output in record.ledger.projection().outputs
                if output.node_id == node_id
                and output.output_port == output_port
            ),
            None,
        )
        if (
            descriptor is None
            or type(value_index) is not int
            or value_index < 0
            or value_index >= descriptor.value_count
        ):
            raise V2RunError(
                "typed_output_not_found",
                "Typed Output value was not found",
                details={
                    "node_id": node_id,
                    "output_port": output_port,
                    "value_index": value_index,
                },
            )
        try:
            value_bytes, value_reference = self._result_store.read_typed_value(
                project_id,
                descriptor,
                value_index,
            )
        except ResultIntegrityError as error:
            raise self._typed_value_integrity_error(
                descriptor,
                value_index,
                expected_digest=error.content_digest,
                expected_size=error.expected_size,
            ) from error
        metadata = {
            "typed_value": {
                "node_id": node_id,
                "output_port": output_port,
                "port_type": {
                    "contract_kind": descriptor.port_type.contract_kind,
                    "contract_id": descriptor.port_type.contract_id,
                    "contract_version": descriptor.port_type.contract_version,
                    "contract_digest": descriptor.port_type.contract_digest,
                },
                "port_content_digest": descriptor.content_digest,
                "value_manifest_reference": (
                    descriptor.value_manifest_reference
                ),
                "value_index": value_index,
                "value_count": descriptor.value_count,
                "value_content_digest": value_reference.content_digest,
                "size": value_reference.size,
            }
        }
        return metadata, value_bytes

    def artifact(
        self,
        project_id: str,
        run_id: str,
        artifact_reference: str,
    ) -> tuple[dict[str, Any], bytes]:
        record = self._registry.require_record(project_id, run_id)
        descriptor = next(
            (
                artifact
                for artifact in record.ledger.projection().artifacts
                if artifact.artifact_reference == artifact_reference
            ),
            None,
        )
        if descriptor is None:
            raise V2RunError(
                "artifact_not_found",
                "Artifact was not found",
                details={
                    "resource_kind": "artifact",
                    "resource_id": artifact_reference,
                },
            )
        try:
            payload = self._result_store.read_artifact(
                project_id,
                descriptor,
            )
        except ResultIntegrityError as error:
            raise V2RunError(
                "artifact_integrity_mismatch",
                "Artifact integrity validation failed",
                details={"artifact_reference": artifact_reference},
            ) from error
        public_descriptor = {
            "artifact_reference": descriptor.artifact_reference,
            "artifact_kind": descriptor.artifact_kind,
            "node_id": descriptor.node_id,
            "output_port": descriptor.output_port,
            "media_type": descriptor.media_type,
            "filename": descriptor.filename,
            "size": descriptor.size,
            "content_digest": descriptor.content_digest,
        }
        if descriptor.candidate_id is not None:
            public_descriptor["candidate_id"] = descriptor.candidate_id
        return public_descriptor, payload

    def events(
        self,
        project_id: str,
        run_id: str,
    ) -> tuple[Fact, ...]:
        record = self._registry.require_record(project_id, run_id)
        self._registry.require_available_evidence(record)
        return record.ledger.events()

    def ledger_cursor(self, project_id: str, run_id: str) -> RunCursor:
        return self._registry.require_record(project_id, run_id).ledger.cursor

    def replay(
        self,
        project_id: str,
        run_id: str,
        cursor: RunCursor | None,
    ) -> ReplayWindow:
        record = self._registry.require_record(project_id, run_id)
        self._registry.require_available_evidence(record)
        return record.ledger.replay(cursor)

    def wait_for_events(
        self,
        project_id: str,
        run_id: str,
        after_sequence: int,
        *,
        timeout_seconds: float = 1.0,
    ) -> tuple[tuple[Fact, ...], int, bool]:
        record = self._registry.require_record(project_id, run_id)
        self._registry.require_available_evidence(record)
        observed = record.ledger.wait_for_events(
            after_sequence,
            timeout_seconds=timeout_seconds,
        )
        self._registry.require_available_evidence(record)
        return observed
