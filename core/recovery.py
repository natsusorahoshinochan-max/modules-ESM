"""Project/run-scoped recovery queries for backend clients."""

from __future__ import annotations

from collections.abc import Iterator
import hashlib
import os
import tempfile
from typing import Any, BinaryIO

from core.graph import Workflow
from core.project import ProjectManager
from core.run_manifest import read_run_manifest, workflow_sha256
from core.recovery_types import (
    RecoveryAction,
    RecoveryPlan,
    RecoveryProvenance,
)
from core.storage import (
    StoragePathError,
    open_private_regular_file,
    validate_identifier,
    validate_relative_path,
)


MAX_PUBLIC_ARTIFACTS = 2048
MAX_PUBLIC_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_PUBLIC_ARTIFACT_TOTAL_BYTES = 256 * 1024 * 1024


class RunRecoveryError(RuntimeError):
    """A safe structured failure at the public recovery boundary."""

    def __init__(
        self,
        kind: str,
        message: str,
        *,
        status_code: int,
        **details: Any,
    ) -> None:
        self.kind = kind
        self.status_code = status_code
        self.details = details
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": {
                "kind": self.kind,
                "message": str(self),
                **self.details,
            }
        }


class RunRecoveryService:
    """Read durable facts only from an explicitly selected project/run."""

    def __init__(self, project_manager: ProjectManager) -> None:
        self.project_manager = project_manager

    def _require_project(self, project_id: str) -> str:
        safe_project_id = validate_identifier(project_id, "project_id")
        if self.project_manager.load_meta(safe_project_id) is None:
            raise RunRecoveryError(
                "project_not_found",
                "Project was not found",
                status_code=404,
            )
        return safe_project_id

    def manifest(self, project_id: str, run_id: str) -> dict[str, Any]:
        safe_project_id = self._require_project(project_id)
        safe_run_id = validate_identifier(run_id, "run_id")
        run_dir = self.project_manager.run_dir(
            safe_project_id,
            safe_run_id,
        )
        if not run_dir.exists():
            raise RunRecoveryError(
                "run_not_found",
                "Run was not found in this project",
                status_code=404,
            )
        try:
            manifest = read_run_manifest(run_dir)
        except FileNotFoundError:
            raise RunRecoveryError(
                "run_not_found",
                "Run was not found in this project",
                status_code=404,
            ) from None
        except (OSError, ValueError, RecursionError):
            raise RunRecoveryError(
                "invalid_run_manifest",
                "Run manifest is not readable",
                status_code=409,
            ) from None
        if (
            manifest.get("project_id") != safe_project_id
            or manifest.get("run_id") != safe_run_id
        ):
            raise RunRecoveryError(
                "run_scope_mismatch",
                "Run manifest does not match the requested scope",
                status_code=409,
            )
        required_collections = (
            "modules",
            "node_states",
            "failures",
            "blocking_reasons",
            "artifacts",
        )
        if (
            not isinstance(manifest.get("status"), str)
            or not isinstance(manifest.get("workflow"), dict)
            or not isinstance(manifest.get("effective_seeds"), dict)
            or any(
                not isinstance(manifest.get(field_name), list)
                for field_name in required_collections
            )
            or (
                manifest.get("recovery") is not None
                and not isinstance(manifest["recovery"], dict)
            )
        ):
            raise RunRecoveryError(
                "invalid_run_manifest",
                "Run manifest has an invalid public shape",
                status_code=409,
            )
        return manifest

    def status(self, project_id: str, run_id: str) -> dict[str, Any]:
        manifest = self.manifest(project_id, run_id)
        return {
            "project_id": manifest["project_id"],
            "run_id": manifest["run_id"],
            "status": manifest.get("status", "unknown"),
            "updated_at": manifest.get("updated_at"),
            "effective_seeds": manifest.get("effective_seeds", {}),
            "node_states": manifest.get("node_states", []),
            "failures": manifest.get("failures", []),
            "blocking_reasons": manifest.get("blocking_reasons", []),
            "recovery": manifest.get("recovery"),
        }

    @staticmethod
    def _artifact_record(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise RunRecoveryError(
                "invalid_run_manifest",
                "Run manifest contains an invalid artifact",
                status_code=409,
            )
        try:
            node_id = validate_identifier(raw["node_id"], "node_id")
            reference = raw["reference"]
            validate_relative_path(reference, "artifact_reference")
            size = raw["size"]
            digest = raw["sha256"]
        except (KeyError, TypeError, ValueError):
            raise RunRecoveryError(
                "invalid_run_manifest",
                "Run manifest contains an invalid artifact",
                status_code=409,
            ) from None
        if (
            not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise RunRecoveryError(
                "invalid_run_manifest",
                "Run manifest contains an invalid artifact",
                status_code=409,
            )
        record = {
            "node_id": node_id,
            "reference": reference,
            "size": size,
            "sha256": digest,
        }
        try:
            record["output_port"] = validate_identifier(
                raw["output_port"],
                "output_port",
            )
        except (KeyError, TypeError, ValueError):
            raise RunRecoveryError(
                "invalid_run_manifest",
                "Run manifest contains an invalid artifact",
                status_code=409,
            ) from None
        candidate_id = raw.get("candidate_id")
        if candidate_id is None:
            if raw.get("artifact_kind") != "standalone":
                raise RunRecoveryError(
                    "invalid_run_manifest",
                    "Run manifest contains an invalid artifact",
                    status_code=409,
                )
            record["artifact_kind"] = "standalone"
        else:
            if raw.get("artifact_kind") is not None:
                raise RunRecoveryError(
                    "invalid_run_manifest",
                    "Run manifest contains an invalid artifact",
                    status_code=409,
                )
            try:
                record["candidate_id"] = validate_identifier(
                    candidate_id,
                    "candidate_id",
                )
            except (TypeError, ValueError):
                raise RunRecoveryError(
                    "invalid_run_manifest",
                    "Run manifest contains an invalid artifact",
                    status_code=409,
                ) from None
        if size > MAX_PUBLIC_ARTIFACT_BYTES:
            raise RunRecoveryError(
                "artifact_limit_exceeded",
                "Artifact exceeds the public retrieval limit",
                status_code=409,
                reference=reference,
            )
        return record

    def _artifact_records(
        self,
        manifest: dict[str, Any],
    ) -> list[dict[str, Any]]:
        raw_artifacts = manifest.get("artifacts", [])
        if len(raw_artifacts) > MAX_PUBLIC_ARTIFACTS:
            raise RunRecoveryError(
                "artifact_limit_exceeded",
                "Run declares too many public artifacts",
                status_code=409,
            )
        artifacts = [
            self._artifact_record(raw)
            for raw in raw_artifacts
        ]
        if len({artifact["reference"] for artifact in artifacts}) != len(
            artifacts
        ):
            raise RunRecoveryError(
                "invalid_run_manifest",
                "Run manifest contains duplicate artifact references",
                status_code=409,
            )
        if sum(artifact["size"] for artifact in artifacts) > (
            MAX_PUBLIC_ARTIFACT_TOTAL_BYTES
        ):
            raise RunRecoveryError(
                "artifact_limit_exceeded",
                "Run artifacts exceed the public retrieval limit",
                status_code=409,
            )
        return artifacts

    def _open_verified_artifact(
        self,
        project_id: str,
        run_id: str,
        record: dict[str, Any],
    ) -> BinaryIO:
        descriptor: int | None = None
        snapshot: BinaryIO | None = None
        try:
            reference_parts = validate_relative_path(
                record["reference"],
                "artifact_reference",
            )
            descriptor = open_private_regular_file(
                self.project_manager.output_dir(project_id, run_id),
                reference_parts,
                field="artifact_reference",
            )
            before = os.fstat(descriptor)
            if before.st_size != record["size"]:
                raise RunRecoveryError(
                    "artifact_integrity_mismatch",
                    "Artifact does not match its run manifest",
                    status_code=409,
                    reference=record["reference"],
                )
            digest = hashlib.sha256()
            snapshot = tempfile.SpooledTemporaryFile(
                max_size=8 * 1024 * 1024,
                mode="w+b",
            )
            with os.fdopen(descriptor, "rb", closefd=False) as artifact:
                while chunk := artifact.read(1024 * 1024):
                    digest.update(chunk)
                    snapshot.write(chunk)
            after = os.fstat(descriptor)
            stable_fields = (
                "st_dev",
                "st_ino",
                "st_size",
                "st_mtime_ns",
                "st_ctime_ns",
            )
            if (
                any(
                    getattr(before, field_name)
                    != getattr(after, field_name)
                    for field_name in stable_fields
                )
                or after.st_size != record["size"]
                or digest.hexdigest() != record["sha256"]
            ):
                raise RunRecoveryError(
                    "artifact_integrity_mismatch",
                    "Artifact does not match its run manifest",
                    status_code=409,
                    reference=record["reference"],
                )
            snapshot.seek(0)
            os.close(descriptor)
            descriptor = None
            return snapshot
        except FileNotFoundError:
            if snapshot is not None:
                snapshot.close()
            raise RunRecoveryError(
                "artifact_missing",
                "Artifact declared by the run manifest is missing",
                status_code=409,
                reference=record["reference"],
            ) from None
        except (OSError, StoragePathError):
            if descriptor is not None:
                os.close(descriptor)
            if snapshot is not None:
                snapshot.close()
            raise RunRecoveryError(
                "invalid_artifact",
                "Artifact is not a safe regular file",
                status_code=409,
                reference=record["reference"],
            ) from None
        except Exception:
            if descriptor is not None:
                os.close(descriptor)
            if snapshot is not None:
                snapshot.close()
            raise

    def outputs(self, project_id: str, run_id: str) -> dict[str, Any]:
        manifest = self.manifest(project_id, run_id)
        artifacts = self._artifact_records(manifest)
        for artifact in artifacts:
            snapshot = self._open_verified_artifact(
                manifest["project_id"],
                manifest["run_id"],
                artifact,
            )
            snapshot.close()
        return {
            "project_id": manifest["project_id"],
            "run_id": manifest["run_id"],
            "status": manifest.get("status", "unknown"),
            "artifacts": artifacts,
        }

    def artifact_chunks(
        self,
        project_id: str,
        run_id: str,
        reference: str,
    ) -> tuple[dict[str, Any], Iterator[bytes]]:
        manifest = self.manifest(project_id, run_id)
        validate_relative_path(reference, "artifact_reference")
        artifacts = self._artifact_records(manifest)
        matches = [
            artifact
            for artifact in artifacts
            if artifact["reference"] == reference
        ]
        if len(matches) != 1:
            raise RunRecoveryError(
                "artifact_not_found",
                "Artifact is not declared by this run",
                status_code=404,
            )
        record = matches[0]
        snapshot = self._open_verified_artifact(
            manifest["project_id"],
            manifest["run_id"],
            record,
        )

        def chunks() -> Iterator[bytes]:
            with snapshot as artifact:
                while chunk := artifact.read(1024 * 1024):
                    yield chunk

        return record, chunks()

    def recovery_plan(
        self,
        project_id: str,
        run_id: str,
        node_id: str,
        *,
        action: RecoveryAction,
        workflow: Workflow,
        requested_seed: Any = None,
    ) -> RecoveryPlan:
        manifest = self.manifest(project_id, run_id)
        safe_node_id = validate_identifier(node_id, "node_id")
        if safe_node_id not in workflow.nodes:
            raise RunRecoveryError(
                "node_not_found",
                "Node was not found in the current Workflow",
                status_code=404,
                node_id=safe_node_id,
            )
        if manifest.get("status") not in {
            "completed",
            "failed",
            "cancelled",
        }:
            raise RunRecoveryError(
                "run_not_terminal",
                "Only a terminal run can be recovered",
                status_code=409,
            )
        if manifest.get("workflow", {}).get("sha256") != workflow_sha256(
            workflow
        ):
            raise RunRecoveryError(
                "workflow_mismatch",
                "Current Workflow does not match the selected run",
                status_code=409,
            )
        seed = manifest.get("run_seed")
        if seed is None:
            effective_seeds = manifest["effective_seeds"]
            if not all(
                isinstance(inherited_node_id, str)
                and isinstance(value, int)
                and not isinstance(value, bool)
                for inherited_node_id, value in effective_seeds.items()
            ):
                raise RunRecoveryError(
                    "invalid_run_manifest",
                    "Run manifest has invalid effective seeds",
                    status_code=409,
                )
            inherited_seeds = {
                value
                for inherited_node_id, value in effective_seeds.items()
                if (
                    inherited_node_id in workflow.nodes
                    and workflow.nodes[
                        inherited_node_id
                    ].parameters.get("seed") is None
                )
            }
            if len(inherited_seeds) > 1:
                raise RunRecoveryError(
                    "recovery_seed_unavailable",
                    "Run manifest does not identify one recoverable run seed",
                    status_code=409,
                )
            seed = next(iter(inherited_seeds), 42)
        if requested_seed is not None:
            seed = requested_seed
        if (
            not isinstance(seed, int)
            or isinstance(seed, bool)
            or seed < 0
            or seed > 2**63 - 1
        ):
            raise RunRecoveryError(
                "invalid_recovery_seed",
                "Recovery seed must be a non-negative integer",
                status_code=422,
            )

        forced_nodes = {safe_node_id}
        if action is RecoveryAction.FORCE_RERUN:
            pending = [safe_node_id]
            while pending:
                current = pending.pop()
                for downstream in workflow.get_downstream_nodes(current):
                    if downstream not in forced_nodes:
                        forced_nodes.add(downstream)
                        pending.append(downstream)
        forced_node_ids = [
            candidate
            for candidate in workflow.topological_sort()
            if candidate in forced_nodes
        ]
        forced = tuple(forced_node_ids)
        return RecoveryPlan(
            seed=seed,
            force_rerun_nodes=forced,
            provenance=RecoveryProvenance(
                source_run_id=manifest["run_id"],
                action=action,
                selected_node_id=safe_node_id,
                forced_node_ids=forced,
            ),
        )
