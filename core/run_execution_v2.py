"""Readiness-gated direct execution and durable public Run projections."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from types import MappingProxyType
from typing import Any
import uuid

from protein_workbench_public import (
    ProtocolValidationError,
    validate_event,
)

from core.port_types import (
    FrozenCatalog,
    PortValueError,
    canonical_json_bytes,
    canonical_sha256,
)
from core.project import ProjectManager
from core.run_manifest import sanitize_public_value
from core.storage import (
    StoragePathError,
    open_private_regular_file,
    validate_relative_path,
    write_private_new_file,
)
from core.workflow_authoring_v2 import WorkflowAuthoringService
from core.workflow_v2 import CompiledWorkflow, ExecutionPlan, ExecutionPlanNode


READINESS_ATTESTATION_NAMESPACE = (
    "protein-workbench-readiness-attestation/v2"
)
RUN_LEDGER_SCHEMA_VERSION = "2.0.0"
MAX_ARTIFACTS_PER_RUN = 2_048
MAX_ARTIFACT_SIZE_BYTES = 64 * 1024 * 1024
MAX_ARTIFACT_BYTES_PER_RUN = 256 * 1024 * 1024
_PUBLIC_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/+-]*$")
_ATTEMPT_TERMINALS = frozenset(
    {
        "succeeded",
        "failed",
        "cancelled",
        "interrupted",
        "outcome_unknown",
    }
)
_DISPOSITION_OUTCOMES = frozenset(
    {"succeeded", "failed", "blocked", "cancelled", "interrupted"}
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def run_timestamp(value: datetime | None = None) -> str:
    observed = value or _utc_now()
    return observed.astimezone(timezone.utc).isoformat()


def run_cursor(sequence: int) -> str:
    return f"cursor-{sequence:020d}"


def _public_failure(error: BaseException) -> dict[str, Any]:
    error_type = type(error).__name__
    if (
        len(error_type) > 128
        or _PUBLIC_IDENTIFIER.fullmatch(error_type) is None
    ):
        error_type = "Exception"
    return {
        "code": "node_execution_failed",
        "message": "Node execution failed safely",
        "retryable": False,
        "correlation_id": f"incident-{uuid.uuid4().hex}",
        "details": {"exception_type": error_type},
    }


def _public_event_from_fact(
    *,
    project_id: str,
    run_id: str,
    fact: Mapping[str, Any],
) -> dict[str, Any] | None:
    fact_type = fact["fact_type"]
    public_fact_types = {
        "readiness_attested",
        "run_admitted",
        "run_started",
        "node_attempt_started",
        "operation_attempt_started",
        "engine_invocation_started",
        "engine_invocation_terminal",
        "operation_attempt_terminal",
        "node_attempt_terminal",
        "node_disposition",
        "run_terminal",
    }
    if fact_type not in public_fact_types:
        return None
    payload = dict(fact["payload"])
    if fact_type == "readiness_attested":
        event = {
            "type": fact_type,
            "binding": payload["binding"],
            "attestation_digest": payload["attestation_digest"],
            "observed_at": payload["observed_at"],
            "conclusion": payload["conclusion"],
            "proof_source": payload["proof_source"],
        }
    elif fact_type == "node_disposition":
        disposition = dict(payload)
        disposition["terminal_sequence"] = fact["sequence"]
        event = {"type": fact_type, "disposition": disposition}
    else:
        event = {"type": fact_type, **payload}
    return {
        "schema_namespace": "protein-workbench-public/v2",
        "project_id": project_id,
        "run_id": run_id,
        "sequence": fact["sequence"],
        "cursor": run_cursor(fact["sequence"]),
        "emitted_at": fact["recorded_at"],
        "event": event,
    }


@dataclass(frozen=True, slots=True)
class BindingEnvironment:
    """Trusted private values plus safe public comparison identities."""

    values: Mapping[str, Any]
    safe_fingerprint: str
    invalidation_token: str
    reusable_identity_configured: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.safe_fingerprint, str)
            or not self.safe_fingerprint
            or not isinstance(self.invalidation_token, str)
            or not self.invalidation_token
            or type(self.reusable_identity_configured) is not bool
        ):
            raise ValueError(
                "Environment Configuration requires safe fingerprint and "
                "invalidation token"
            )
        object.__setattr__(
            self,
            "values",
            MappingProxyType(dict(self.values)),
        )


class EnvironmentConfiguration:
    """Trusted Binding-scoped configuration excluded from public evidence."""

    def __init__(
        self,
        entries: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
    ) -> None:
        resolved: dict[tuple[str, str], Mapping[str, Any]] = {}
        for identity, entry in (entries or {}).items():
            if (
                not isinstance(identity, tuple)
                or len(identity) != 2
                or not all(isinstance(part, str) for part in identity)
                or not isinstance(entry, Mapping)
            ):
                raise ValueError(
                    "Environment Configuration must be keyed by exact Binding"
                )
            resolved[identity] = MappingProxyType(dict(entry))
        self._entries = MappingProxyType(resolved)

    def for_binding(
        self,
        binding_id: str,
        binding_version: str,
    ) -> BindingEnvironment:
        entry = self._entries.get((binding_id, binding_version), {})

        def resolve(name: str, default: Any) -> Any:
            value = entry.get(name, default)
            return value() if callable(value) else value

        return BindingEnvironment(
            values=resolve("values", {}),
            safe_fingerprint=resolve(
                "safe_fingerprint",
                f"binding-{binding_id}-{binding_version}",
            ),
            invalidation_token=resolve(
                "invalidation_token",
                f"binding-{binding_id}-{binding_version}",
            ),
            reusable_identity_configured=(
                "safe_fingerprint" in entry
                and "invalidation_token" in entry
            ),
        )


@dataclass(frozen=True, slots=True)
class ReusableReadinessProof:
    """A reusable immutable proof with every required trust boundary."""

    proof_identity: str
    proof_scope: str
    observed_at: datetime
    maximum_age_seconds: int
    configuration_fingerprint: str
    invalidation_token: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.proof_identity, str)
            or not self.proof_identity
            or not isinstance(self.proof_scope, str)
            or not self.proof_scope
            or not isinstance(self.observed_at, datetime)
            or self.observed_at.utcoffset() is None
            or type(self.maximum_age_seconds) is not int
            or self.maximum_age_seconds < 0
            or not isinstance(self.configuration_fingerprint, str)
            or not self.configuration_fingerprint
            or not isinstance(self.invalidation_token, str)
            or not self.invalidation_token
        ):
            raise ValueError(
                "Reusable readiness proof requires complete immutable scope"
            )

    def reusable_for(
        self,
        *,
        now: datetime,
        proof_identity: str,
        proof_scope: str,
        maximum_age_seconds: int,
        configuration_fingerprint: str,
        invalidation_token: str,
    ) -> bool:
        age = (now - self.observed_at).total_seconds()
        return (
            self.proof_identity == proof_identity
            and self.proof_scope == proof_scope
            and self.maximum_age_seconds == maximum_age_seconds
            and 0 <= age <= maximum_age_seconds
            and self.configuration_fingerprint
            == configuration_fingerprint
            and self.invalidation_token == invalidation_token
        )


class ReadinessCheckInput(Mapping[str, Any]):
    """Mapping-compatible private checker input with an optional valid proof."""

    def __init__(
        self,
        environment: BindingEnvironment,
        reusable_proof: ReusableReadinessProof | None,
    ) -> None:
        self._environment = environment
        self.reusable_proof = reusable_proof

    def __getitem__(self, key: str) -> Any:
        return self._environment.values[key]

    def __iter__(self):
        return iter(self._environment.values)

    def __len__(self) -> int:
        return len(self._environment.values)


@dataclass(frozen=True, slots=True)
class ReadinessResult:
    """One checker conclusion and optional newly observed immutable proof."""

    passing: bool
    proof_source: str = "direct-observation"
    reason_code: str = "prerequisite_unavailable"
    reusable_proof: ReusableReadinessProof | None = None


@dataclass(frozen=True, slots=True)
class RunResources:
    """Project/Run-contained resources available to one lazy direct factory."""

    project_id: str
    run_id: str
    node_id: str
    _projects: ProjectManager = field(repr=False, compare=False)

    @property
    def _output_root(self) -> Path:
        return self._projects.output_dir(self.project_id, self.run_id).parent

    def write_artifact(
        self,
        relative_name: str,
        payload: bytes,
    ) -> str:
        """Create one private no-follow artifact and return a private relative ref."""
        parts = validate_relative_path(relative_name, "artifact_name")
        write_private_new_file(
            self._output_root,
            (self.run_id, *parts),
            payload,
            field="artifact_name",
        )
        return "/".join(parts)

    def temporary_directory(self, *, prefix: str):
        """Delegate to the hardened legacy workspace primitive."""
        context = self._projects.run_context(
            self.project_id,
            self.run_id,
            self.node_id,
        )
        return context.temporary_directory(prefix=prefix)

    def cleanup_temporary_work(self) -> None:
        context = self._projects.run_context(
            self.project_id,
            self.run_id,
            self.node_id,
        )
        context.cleanup_temporary_work()


class ResultReplaySource:
    """Optional Cache boundary; Ticket 09 supplies durable v2 storage."""

    def lookup(
        self,
        *,
        project_id: str,
        execution_plan: ExecutionPlan,
        node: ExecutionPlanNode,
        inputs: Mapping[str, Any],
    ) -> Mapping[str, Any] | None:
        del project_id, execution_plan, node, inputs
        return None


class V2RunError(RuntimeError):
    """One public-safe v2 Run failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any],
    ) -> None:
        self.code = code
        self.details = dict(details)
        super().__init__(message)


class ExecutionTermination(RuntimeError):
    """A bounded terminal conclusion reported by a started engine seam."""

    def __init__(self, status: str) -> None:
        if status not in {
            "failed",
            "cancelled",
            "interrupted",
            "outcome_unknown",
        }:
            raise ValueError("Execution terminal status is invalid")
        self.status = status
        super().__init__("Execution terminated without public diagnostics")


class PreScheduleTermination(RuntimeError):
    """A scheduler conclusion that prevents a Node Attempt from starting."""

    def __init__(self, outcome: str) -> None:
        if outcome not in {"cancelled", "interrupted"}:
            raise ValueError("Pre-schedule disposition outcome is invalid")
        self.outcome = outcome
        super().__init__("Node was not scheduled")


class _RunEvidenceLedger:
    """Schema-checked, causally closed owner-only facts for one Run."""

    def __init__(
        self,
        projects: ProjectManager,
        project_id: str,
        run_id: str,
        plan: ExecutionPlan,
    ) -> None:
        run_dir = projects.run_dir(project_id, run_id)
        self._root = run_dir.parent
        self._project_id = project_id
        self._run_id = run_id
        self._facts: list[dict[str, Any]] = []
        self._plan_nodes = frozenset(node.node_id for node in plan.nodes)
        dependencies: dict[str, set[str]] = {
            node.node_id: set() for node in plan.nodes
        }
        for edge in plan.edges:
            dependencies[edge.target_node_id].add(edge.source_node_id)
        self._dependencies = {
            node_id: frozenset(upstream)
            for node_id, upstream in dependencies.items()
        }
        self._node_attempts: dict[str, dict[str, Any]] = {}
        self._node_attempt_by_node: dict[str, str] = {}
        self._operations: dict[str, dict[str, Any]] = {}
        self._invocations: dict[str, dict[str, Any]] = {}
        self._dispositions: dict[str, dict[str, Any]] = {}
        self._outputs_published: set[str] = set()
        self._run_admitted = False
        self._run_started = False
        self._run_terminal = False

    @property
    def facts(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(fact) for fact in self._facts)

    @property
    def cursor(self) -> str:
        return run_cursor(len(self._facts))

    def _require_fields(
        self,
        payload: Mapping[str, Any],
        *,
        required: frozenset[str],
        optional: frozenset[str] = frozenset(),
    ) -> None:
        fields = frozenset(payload)
        if not required <= fields or fields - required - optional:
            raise V2RunError(
                "evidence_unavailable",
                "Required Run evidence failed schema validation",
                details={"last_durable_cursor": self.cursor},
            )

    def _causal_error(self) -> V2RunError:
        return V2RunError(
            "evidence_unavailable",
            "Required Run evidence failed causal validation",
            details={"last_durable_cursor": self.cursor},
        )

    def _validate_causality(
        self,
        fact_type: str,
        payload: Mapping[str, Any],
    ) -> None:
        if self._run_terminal:
            raise self._causal_error()
        if fact_type == "run_scope_bound":
            if self._facts:
                raise self._causal_error()
            return
        if not self._facts or self._facts[0]["fact_type"] != "run_scope_bound":
            raise self._causal_error()
        if fact_type in {"availability_bound", "readiness_attested"}:
            if self._run_admitted:
                raise self._causal_error()
            return
        if fact_type == "run_admitted":
            if self._run_admitted or self._run_started:
                raise self._causal_error()
            return
        if fact_type == "run_started":
            if not self._run_admitted or self._run_started:
                raise self._causal_error()
            return
        if fact_type == "node_attempt_started":
            node_id = payload["node_id"]
            attempt_id = payload["node_attempt_id"]
            if (
                not self._run_started
                or node_id not in self._plan_nodes
                or node_id in self._node_attempt_by_node
                or node_id in self._dispositions
                or attempt_id in self._node_attempts
                or any(
                    upstream not in self._dispositions
                    or self._dispositions[upstream]["outcome"] != "succeeded"
                    for upstream in self._dependencies[node_id]
                )
            ):
                raise self._causal_error()
            return
        if fact_type == "operation_attempt_started":
            attempt_id = payload["node_attempt_id"]
            operation_id = payload["operation_attempt_id"]
            attempt = self._node_attempts.get(attempt_id)
            if (
                attempt is None
                or attempt["terminal"] is not None
                or operation_id in self._operations
                or any(
                    operation["node_attempt_id"] == attempt_id
                    for operation in self._operations.values()
                )
            ):
                raise self._causal_error()
            return
        if fact_type == "engine_invocation_started":
            operation_id = payload["operation_attempt_id"]
            invocation_id = payload["invocation_id"]
            operation = self._operations.get(operation_id)
            if (
                operation is None
                or operation["terminal"] is not None
                or invocation_id in self._invocations
            ):
                raise self._causal_error()
            return
        if fact_type == "engine_invocation_terminal":
            invocation = self._invocations.get(payload["invocation_id"])
            if invocation is None or invocation["terminal"] is not None:
                raise self._causal_error()
            return
        if fact_type == "operation_attempt_terminal":
            operation_id = payload["operation_attempt_id"]
            operation = self._operations.get(operation_id)
            if (
                operation is None
                or operation["terminal"] is not None
                or any(
                    invocation["operation_attempt_id"] == operation_id
                    and invocation["terminal"] is None
                    for invocation in self._invocations.values()
                )
                or (
                    payload["status"] == "succeeded"
                    and any(
                        invocation["operation_attempt_id"] == operation_id
                        and invocation["terminal"] != "succeeded"
                        for invocation in self._invocations.values()
                    )
                )
            ):
                raise self._causal_error()
            return
        if fact_type in {"artifact_published", "outputs_published"}:
            node_id = (
                payload["artifact"]["node_id"]
                if fact_type == "artifact_published"
                else payload["node_id"]
            )
            attempt_id = self._node_attempt_by_node.get(node_id)
            attempt = (
                self._node_attempts.get(attempt_id)
                if attempt_id is not None
                else None
            )
            if (
                attempt is None
                or attempt["terminal"] is not None
                or node_id in self._dispositions
                or (
                    fact_type == "outputs_published"
                    and node_id in self._outputs_published
                )
            ):
                raise self._causal_error()
            child_operations = [
                operation_id
                for operation_id, operation in self._operations.items()
                if operation["node_attempt_id"] == attempt_id
            ]
            if child_operations and any(
                invocation["operation_attempt_id"] in child_operations
                and invocation["terminal"] != "succeeded"
                for invocation in self._invocations.values()
            ):
                raise self._causal_error()
            return
        if fact_type == "node_attempt_terminal":
            attempt_id = payload["node_attempt_id"]
            attempt = self._node_attempts.get(attempt_id)
            child_operations = [
                operation
                for operation in self._operations.values()
                if operation["node_attempt_id"] == attempt_id
            ]
            if (
                attempt is None
                or attempt["terminal"] is not None
                or any(
                    operation["terminal"] is None
                    for operation in child_operations
                )
                or (
                    payload["resolution"] == "cache_replayed"
                    and (
                        payload["status"] != "succeeded"
                        or child_operations
                    )
                )
                or (
                    payload["resolution"] == "executed"
                    and child_operations
                    and child_operations[-1]["terminal"]
                    != payload["status"]
                )
            ):
                raise self._causal_error()
            return
        if fact_type == "node_disposition":
            node_id = payload["node_id"]
            outcome = payload["outcome"]
            if node_id not in self._plan_nodes or node_id in self._dispositions:
                raise self._causal_error()
            attempt_id = self._node_attempt_by_node.get(node_id)
            attempt = (
                self._node_attempts.get(attempt_id)
                if attempt_id is not None
                else None
            )
            if outcome == "blocked":
                blocked_by = frozenset(payload["blocked_by"])
                expected_blockers = frozenset(
                    upstream
                    for upstream in self._dependencies[node_id]
                    if upstream in self._dispositions
                    and self._dispositions[upstream]["outcome"]
                    != "succeeded"
                )
                if (
                    attempt is not None
                    or not blocked_by
                    or blocked_by != expected_blockers
                    or any(
                        upstream not in self._dispositions
                        or self._dispositions[upstream]["outcome"]
                        == "succeeded"
                        for upstream in blocked_by
                    )
                ):
                    raise self._causal_error()
                return
            if outcome in {"cancelled", "interrupted"} and attempt is None:
                return
            if attempt is None or attempt["terminal"] is None:
                raise self._causal_error()
            expected_outcome = {
                "succeeded": "succeeded",
                "failed": "failed",
                "cancelled": "cancelled",
                "interrupted": "interrupted",
                "outcome_unknown": "interrupted",
            }[attempt["terminal"]]
            if expected_outcome != outcome:
                raise self._causal_error()
            if outcome == "succeeded" and (
                payload.get("resolution") != attempt["resolution"]
            ):
                raise self._causal_error()
            return
        if fact_type == "run_terminal":
            outcomes = {
                disposition["outcome"]
                for disposition in self._dispositions.values()
            }
            expected_status = (
                "failed"
                if "failed" in outcomes
                else "interrupted"
                if "interrupted" in outcomes
                else "cancelled"
                if "cancelled" in outcomes
                else "succeeded"
            )
            if (
                not self._run_started
                or set(self._dispositions) != set(self._plan_nodes)
                or any(
                    attempt["terminal"] is None
                    for attempt in self._node_attempts.values()
                )
                or any(
                    operation["terminal"] is None
                    for operation in self._operations.values()
                )
                or any(
                    invocation["terminal"] is None
                    for invocation in self._invocations.values()
                )
                or payload["status"] != expected_status
            ):
                raise self._causal_error()

    def _validate_schema(
        self,
        fact_type: str,
        payload: Mapping[str, Any],
    ) -> None:
        schemas = {
            "run_scope_bound": (
                frozenset(
                    {
                        "project_id",
                        "run_id",
                        "workflow_revision",
                        "workflow_digest",
                        "contract_lock_digest",
                        "compile_id",
                        "execution_plan_digest",
                        "catalog_contract_digest",
                        "resolved_contracts",
                    }
                ),
                frozenset(),
            ),
            "availability_bound": (
                frozenset(
                    {"binding", "catalog_observed_at", "available"}
                ),
                frozenset(),
            ),
            "readiness_attested": (
                frozenset(
                    {
                        "binding",
                        "readiness_contract_digest",
                        "safe_environment_fingerprint",
                        "observed_at",
                        "conclusion",
                        "proof_source",
                        "attestation_digest",
                    }
                ),
                frozenset(
                    {"proof_reference", "refreshed_proof_reference"}
                ),
            ),
            "run_admitted": (
                frozenset({"workflow_revision", "compile_id"}),
                frozenset(),
            ),
            "run_started": (frozenset({"started_at"}), frozenset()),
            "node_attempt_started": (
                frozenset({"node_id", "node_attempt_id"}),
                frozenset(),
            ),
            "operation_attempt_started": (
                frozenset({"operation_attempt_id", "node_attempt_id"}),
                frozenset(),
            ),
            "engine_invocation_started": (
                frozenset(
                    {
                        "invocation_id",
                        "operation_attempt_id",
                        "engine_role",
                        "engine_identity",
                    }
                ),
                frozenset(),
            ),
            "engine_invocation_terminal": (
                frozenset({"invocation_id", "status"}),
                frozenset({"error"}),
            ),
            "artifact_published": (
                frozenset({"artifact"}),
                frozenset(),
            ),
            "outputs_published": (
                frozenset({"node_id", "outputs", "artifacts"}),
                frozenset(),
            ),
            "operation_attempt_terminal": (
                frozenset({"operation_attempt_id", "status"}),
                frozenset({"error"}),
            ),
            "node_attempt_terminal": (
                frozenset({"node_attempt_id", "status", "resolution"}),
                frozenset({"error"}),
            ),
            "node_disposition": (
                frozenset({"node_id", "outcome", "blocked_by"}),
                frozenset({"resolution"}),
            ),
            "run_terminal": (frozenset({"status"}), frozenset()),
        }
        try:
            required, optional = schemas[fact_type]
        except KeyError as error:
            raise V2RunError(
                "evidence_unavailable",
                "Required Run evidence has an unknown fact type",
                details={"last_durable_cursor": self.cursor},
            ) from error
        self._require_fields(
            payload,
            required=required,
            optional=optional,
        )
        if (
            fact_type.endswith("_terminal")
            and fact_type != "run_terminal"
            and payload["status"] not in _ATTEMPT_TERMINALS
        ):
            raise self._causal_error()
        if fact_type == "node_attempt_terminal" and payload["resolution"] not in {
            "executed",
            "cache_replayed",
        }:
            raise self._causal_error()
        if fact_type == "node_disposition":
            if payload["outcome"] not in _DISPOSITION_OUTCOMES:
                raise self._causal_error()
            if (
                payload["outcome"] == "succeeded"
            ) != ("resolution" in payload):
                raise self._causal_error()

    def _apply(self, fact_type: str, payload: Mapping[str, Any]) -> None:
        if fact_type == "run_admitted":
            self._run_admitted = True
        elif fact_type == "run_started":
            self._run_started = True
        elif fact_type == "node_attempt_started":
            record = {
                "node_id": payload["node_id"],
                "terminal": None,
                "resolution": None,
            }
            self._node_attempts[payload["node_attempt_id"]] = record
            self._node_attempt_by_node[payload["node_id"]] = payload[
                "node_attempt_id"
            ]
        elif fact_type == "operation_attempt_started":
            self._operations[payload["operation_attempt_id"]] = {
                "node_attempt_id": payload["node_attempt_id"],
                "terminal": None,
            }
        elif fact_type == "engine_invocation_started":
            self._invocations[payload["invocation_id"]] = {
                "operation_attempt_id": payload["operation_attempt_id"],
                "terminal": None,
            }
        elif fact_type == "engine_invocation_terminal":
            self._invocations[payload["invocation_id"]]["terminal"] = payload[
                "status"
            ]
        elif fact_type == "operation_attempt_terminal":
            self._operations[payload["operation_attempt_id"]]["terminal"] = (
                payload["status"]
            )
        elif fact_type == "node_attempt_terminal":
            attempt = self._node_attempts[payload["node_attempt_id"]]
            attempt["terminal"] = payload["status"]
            attempt["resolution"] = payload["resolution"]
        elif fact_type == "outputs_published":
            self._outputs_published.add(payload["node_id"])
        elif fact_type == "node_disposition":
            self._dispositions[payload["node_id"]] = dict(payload)
        elif fact_type == "run_terminal":
            self._run_terminal = True

    def append(self, fact_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        sequence = len(self._facts) + 1
        safe_payload = sanitize_public_value(dict(payload))
        fact = {
            "schema_version": RUN_LEDGER_SCHEMA_VERSION,
            "sequence": sequence,
            "recorded_at": run_timestamp(),
            "fact_type": fact_type,
            "payload": safe_payload,
        }
        self._validate_schema(fact_type, safe_payload)
        self._validate_causality(fact_type, safe_payload)
        event = _public_event_from_fact(
            project_id=self._project_id,
            run_id=self._run_id,
            fact=fact,
        )
        if event is not None:
            try:
                validate_event(event)
            except ProtocolValidationError as error:
                raise V2RunError(
                    "evidence_unavailable",
                    "Required Run evidence failed public schema validation",
                    details={"last_durable_cursor": self.cursor},
                ) from error
        encoded = canonical_json_bytes(fact)
        try:
            write_private_new_file(
                self._root,
                (
                    self._run_id,
                    "ledger",
                    f"{sequence:020d}.json",
                ),
                encoded,
                field="run_ledger",
            )
        except (OSError, StoragePathError) as error:
            raise V2RunError(
                "evidence_unavailable",
                "Required Run evidence could not be persisted safely",
                details={"last_durable_cursor": self.cursor},
            ) from error
        self._facts.append(fact)
        self._apply(fact_type, safe_payload)
        return fact


@dataclass(slots=True)
class _RunRecord:
    compiled: CompiledWorkflow
    ledger: _RunEvidenceLedger
    projection: dict[str, Any]
    artifacts: dict[str, tuple[dict[str, Any], tuple[str, ...]]]


def _port_contract(
    catalog: FrozenCatalog,
    node_contract: Any,
    direction: str,
    port_name: str,
) -> tuple[Mapping[str, Any], Any]:
    ports = {
        port["name"]: port
        for port in node_contract.descriptor.get(direction, ())
    }
    try:
        port = ports[port_name]
        reference = port["port_type"]
        port_type = catalog.require_port_type(
            reference["contract_id"],
            reference["contract_version"],
        )
    except (KeyError, TypeError) as error:
        raise PortValueError(
            f"Unknown {direction} Port {port_name!r}"
        ) from error
    if port_type.contract_digest != reference["contract_digest"]:
        raise PortValueError(
            f"{direction} Port {port_name!r} contract digest changed"
        )
    return port, port_type


def _wire_value(encoded: bytes) -> Any:
    payload = json.loads(encoded)
    return payload["value"]


def _plain_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _plain_json(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return [_plain_json(item) for item in value]
    if isinstance(value, list):
        return [_plain_json(item) for item in value]
    return value


def _read_stable_private_file(
    root: Path,
    parts: tuple[str, ...],
    *,
    field: str,
    maximum_size: int,
) -> bytes:
    file_descriptor: int | None = None
    try:
        file_descriptor = open_private_regular_file(
            root,
            parts,
            field=field,
        )
        metadata = os.fstat(file_descriptor)
        if (
            stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_size > maximum_size
        ):
            raise StoragePathError(field, f"Invalid {field}")
        chunks: list[bytes] = []
        remaining = metadata.st_size
        while remaining:
            chunk = os.read(
                file_descriptor,
                min(remaining, 1024 * 1024),
            )
            if not chunk:
                raise StoragePathError(field, f"Invalid {field}")
            chunks.append(chunk)
            remaining -= len(chunk)
        final_metadata = os.fstat(file_descriptor)
        if (
            final_metadata.st_dev,
            final_metadata.st_ino,
            final_metadata.st_size,
            final_metadata.st_mtime_ns,
        ) != (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
        ):
            raise StoragePathError(field, f"Invalid {field}")
        return b"".join(chunks)
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)


class V2RunService:
    """Execute compiled direct Nodes behind readiness and durable evidence."""

    def __init__(
        self,
        projects: ProjectManager,
        catalog: FrozenCatalog,
        authoring: WorkflowAuthoringService,
        environment: EnvironmentConfiguration,
        result_replay_source: ResultReplaySource | None = None,
    ) -> None:
        self._projects = projects
        self._catalog = catalog
        self._authoring = authoring
        self._environment = environment
        self._result_replay_source = (
            result_replay_source or ResultReplaySource()
        )
        self._runs: dict[tuple[str, str], _RunRecord] = {}
        self._run_owners: dict[str, str] = {}
        self._proofs: dict[
            tuple[str, str, str, str],
            ReusableReadinessProof,
        ] = {}

    def _require_record(
        self,
        project_id: str,
        run_id: str,
    ) -> _RunRecord:
        owner = self._run_owners.get(run_id)
        if owner is not None and owner != project_id:
            raise V2RunError(
                "cross_scope_access_denied",
                "Run does not belong to the requested Project",
                details={
                    "requested_project_id": project_id,
                    "requested_run_id": run_id,
                },
            )
        try:
            return self._runs[(project_id, run_id)]
        except KeyError as error:
            raise V2RunError(
                "run_not_found",
                "Run was not found",
                details={"resource_kind": "run", "resource_id": run_id},
            ) from error

    def _availability(self, binding_id: str, version: str) -> Mapping[str, Any]:
        for snapshot in self._catalog.availability:
            reference = snapshot["binding"]
            if (
                reference["contract_id"],
                reference["contract_version"],
            ) == (binding_id, version):
                return snapshot
        raise V2RunError(
            "binding_unavailable",
            "Selected Binding has no Availability snapshot",
            details={
                "binding": self._catalog.require_contract(
                    "binding",
                    binding_id,
                    version,
                ).reference(),
                "reason_code": "availability_missing",
            },
        )

    @staticmethod
    def _project_terminal_run(
        *,
        project_id: str,
        run_id: str,
        workflow_revision: int,
        compile_id: str,
        plan: ExecutionPlan,
        ledger: _RunEvidenceLedger,
    ) -> dict[str, Any]:
        dispositions: list[dict[str, Any]] = []
        outputs: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []
        terminal_status: str | None = None
        terminal_sequence: int | None = None
        for fact in ledger.facts:
            payload = fact["payload"]
            if fact["fact_type"] == "node_disposition":
                disposition = dict(payload)
                disposition["terminal_sequence"] = fact["sequence"]
                dispositions.append(disposition)
            elif fact["fact_type"] == "outputs_published":
                outputs.extend(payload["outputs"])
                artifacts.extend(payload["artifacts"])
            elif fact["fact_type"] == "run_terminal":
                terminal_status = payload["status"]
                terminal_sequence = fact["sequence"]
        if terminal_status is None or terminal_sequence is None:
            raise V2RunError(
                "evidence_unavailable",
                "Run projection requires a causally closed terminal Ledger",
                details={"last_durable_cursor": ledger.cursor},
            )
        return {
            "project_id": project_id,
            "run_id": run_id,
            "workflow_revision": workflow_revision,
            "workflow_digest": plan.workflow_digest,
            "compile_id": compile_id,
            "status": terminal_status,
            "terminal_sequence": terminal_sequence,
            "ledger_cursor": ledger.cursor,
            "node_dispositions": dispositions,
            "outputs": outputs,
            "artifact_index": artifacts,
        }

    @staticmethod
    def _proof_contract(
        declaration: Any,
        node: ExecutionPlanNode,
    ) -> tuple[str, str, int] | None:
        raw = declaration.prerequisites.get("reusable_proof")
        if raw is None:
            return None
        if (
            not isinstance(raw, Mapping)
            or set(raw) != {"identity", "scope", "maximum_age_seconds"}
            or not isinstance(raw["identity"], str)
            or not isinstance(raw["scope"], str)
            or type(raw["maximum_age_seconds"]) is not int
            or raw["maximum_age_seconds"] < 0
        ):
            raise V2RunError(
                "readiness_rejected",
                "Binding Readiness proof contract is invalid",
                details={
                    "binding": node.binding.to_public(),
                    "reason_code": "invalid_proof_contract",
                },
            )
        return (
            raw["identity"],
            raw["scope"],
            raw["maximum_age_seconds"],
        )

    @staticmethod
    def _proof_reference(
        proof: ReusableReadinessProof,
        *,
        reuse_kind: str,
    ) -> dict[str, Any]:
        return {
            "proof_identity": proof.proof_identity,
            "proof_scope": proof.proof_scope,
            "observed_at": run_timestamp(proof.observed_at),
            "maximum_age_seconds": proof.maximum_age_seconds,
            "reuse_kind": reuse_kind,
        }

    def _attest_readiness(
        self,
        *,
        node: ExecutionPlanNode,
        ledger: _RunEvidenceLedger,
    ) -> None:
        binding_id = node.binding.contract_id
        binding_version = node.binding.contract_version
        declaration = self._catalog.require_readiness_declaration(
            binding_id,
            binding_version,
        )
        environment = self._environment.for_binding(
            binding_id,
            binding_version,
        )
        now = _utc_now()
        reusable: ReusableReadinessProof | None = None
        proof_contract = self._proof_contract(declaration, node)
        if (
            proof_contract is not None
            and not environment.reusable_identity_configured
        ):
            result = ReadinessResult(
                False,
                proof_source="missing-environment-identity",
                reason_code="reusable_identity_not_configured",
            )
        else:
            result = None
        if proof_contract is not None and result is None:
            proof_identity, proof_scope, maximum_age = proof_contract
            candidate = self._proofs.get(
                (
                    binding_id,
                    binding_version,
                    proof_identity,
                    proof_scope,
                )
            )
            if candidate is not None and candidate.reusable_for(
                now=now,
                proof_identity=proof_identity,
                proof_scope=proof_scope,
                maximum_age_seconds=maximum_age,
                configuration_fingerprint=environment.safe_fingerprint,
                invalidation_token=environment.invalidation_token,
            ):
                reusable = candidate
        if result is None:
            try:
                observed = declaration.check(
                    ReadinessCheckInput(environment, reusable)
                )
            except Exception as error:
                del error
                observed = ReadinessResult(
                    False,
                    proof_source="checker-failure",
                    reason_code="readiness_check_failed",
                )
            if isinstance(observed, bool):
                result = ReadinessResult(observed)
            elif isinstance(observed, ReadinessResult):
                result = observed
            else:
                result = ReadinessResult(
                    False,
                    proof_source="invalid-conclusion",
                    reason_code="invalid_readiness_conclusion",
                )
        if (
            not isinstance(result.proof_source, str)
            or len(result.proof_source) > 128
            or _PUBLIC_IDENTIFIER.fullmatch(result.proof_source) is None
            or not isinstance(result.reason_code, str)
            or len(result.reason_code) > 128
            or _PUBLIC_IDENTIFIER.fullmatch(result.reason_code) is None
        ):
            result = ReadinessResult(
                False,
                proof_source="invalid-conclusion",
                reason_code="invalid_readiness_conclusion",
            )
        proof_to_cache: ReusableReadinessProof | None = None
        if result.passing and result.reusable_proof is not None:
            proof = result.reusable_proof
            if (
                proof_contract is None
                or not proof.reusable_for(
                    now=now,
                    proof_identity=proof_contract[0],
                    proof_scope=proof_contract[1],
                    maximum_age_seconds=proof_contract[2],
                    configuration_fingerprint=environment.safe_fingerprint,
                    invalidation_token=environment.invalidation_token,
                )
            ):
                result = ReadinessResult(
                    False,
                    proof_source="invalid-proof",
                    reason_code="invalid_readiness_proof",
                )
            else:
                proof_to_cache = proof
        readiness_digest = canonical_sha256(
            {
                "schema_namespace": "protein-workbench-readiness/v2",
                "binding": node.binding.to_public(),
                "declaration": _plain_json(declaration.descriptor()),
            }
        )
        attestation_payload = {
            "binding": node.binding.to_public(),
            "readiness_contract_digest": readiness_digest,
            "safe_environment_fingerprint": environment.safe_fingerprint,
            "observed_at": run_timestamp(now),
            "conclusion": "passing" if result.passing else "failing",
            "proof_source": result.proof_source,
        }
        if reusable is not None:
            attestation_payload["proof_reference"] = self._proof_reference(
                reusable,
                reuse_kind="reused",
            )
        if proof_to_cache is not None:
            reference_field = (
                "refreshed_proof_reference"
                if reusable is not None
                else "proof_reference"
            )
            attestation_payload[reference_field] = self._proof_reference(
                proof_to_cache,
                reuse_kind="newly-observed",
            )
        attestation_digest = canonical_sha256(
            {
                "schema_namespace": READINESS_ATTESTATION_NAMESPACE,
                **attestation_payload,
            }
        )
        ledger.append(
            "readiness_attested",
            {
                **attestation_payload,
                "attestation_digest": attestation_digest,
            },
        )
        if proof_to_cache is not None:
            self._proofs[
                (
                    binding_id,
                    binding_version,
                    proof_to_cache.proof_identity,
                    proof_to_cache.proof_scope,
                )
            ] = proof_to_cache
        if not result.passing:
            raise V2RunError(
                "readiness_rejected",
                "Selected Binding is not ready for this Run",
                details={
                    "binding": node.binding.to_public(),
                    "reason_code": result.reason_code,
                },
            )

    def _inputs_for(
        self,
        plan: ExecutionPlan,
        node: ExecutionPlanNode,
        values: Mapping[tuple[str, str], list[Any]],
    ) -> dict[str, Any]:
        inputs: dict[str, Any] = {}
        for edge in plan.edges:
            if edge.target_node_id != node.node_id:
                continue
            source_values = values[(edge.source_node_id, edge.source_port)]
            node_contract = self._catalog.require_contract(
                *node.node_type.key,
            )
            port, port_type = _port_contract(
                self._catalog,
                node_contract,
                "inputs",
                edge.target_port,
            )
            for value in source_values:
                port_type.decode(port_type.encode(value))
            if port["multiplicity"] == "many":
                inputs.setdefault(edge.target_port, []).extend(source_values)
            else:
                inputs[edge.target_port] = source_values[0]
        return inputs

    def _validate_outputs(
        self,
        node: ExecutionPlanNode,
        outputs: Any,
    ) -> tuple[list[dict[str, Any]], dict[tuple[str, str], list[Any]]]:
        if not isinstance(outputs, Mapping):
            raise PortValueError("Direct implementation output must be an object")
        node_contract = self._catalog.require_contract(*node.node_type.key)
        declared = {
            port["name"]: port
            for port in node_contract.descriptor.get("outputs", ())
        }
        if set(outputs) - set(declared):
            raise PortValueError("Direct implementation returned unknown outputs")
        published: list[dict[str, Any]] = []
        runtime: dict[tuple[str, str], list[Any]] = {}
        for port_name, declaration in declared.items():
            if declaration["required"] is True and port_name not in outputs:
                raise PortValueError(
                    f"Required output Port {port_name!r} is missing"
                )
            if port_name not in outputs:
                continue
            _, port_type = _port_contract(
                self._catalog,
                node_contract,
                "outputs",
                port_name,
            )
            supplied = outputs[port_name]
            values = (
                list(supplied)
                if declaration["multiplicity"] == "many"
                else [supplied]
            )
            if declaration["multiplicity"] == "many" and not isinstance(
                supplied,
                (list, tuple),
            ):
                raise PortValueError(
                    f"Output Port {port_name!r} requires many values"
                )
            encoded = [port_type.encode(value) for value in values]
            decoded = [
                port_type.decode(item)
                for item in encoded
            ]
            runtime[(node.node_id, port_name)] = decoded
            published.append(
                {
                    "node_id": node.node_id,
                    "output_port": port_name,
                    "port_type": port_type.reference(),
                    "content_digest": (
                        port_type.content_digest(decoded[0])
                        if len(decoded) == 1
                        else canonical_sha256(
                            {
                                "port_type": port_type.reference(),
                                "value_content_digests": [
                                    port_type.content_digest(value)
                                    for value in decoded
                                ],
                            }
                        )
                    ),
                    "values": [_wire_value(item) for item in encoded],
                }
            )
        return published, runtime

    @staticmethod
    def _artifact_media_type(relative_name: str) -> str:
        suffix = Path(relative_name).suffix.lower()
        return {
            ".pdb": "chemical/x-pdb",
            ".fasta": "text/x-fasta",
            ".fa": "text/x-fasta",
            ".json": "application/json",
        }.get(suffix, "application/octet-stream")

    def _publish_artifact(
        self,
        *,
        resources: RunResources,
        node_id: str,
        output_port: str,
        relative_name: str,
        ledger: _RunEvidenceLedger,
        maximum_size: int,
    ) -> tuple[dict[str, Any], tuple[str, ...]]:
        source_parts = validate_relative_path(
            relative_name,
            "artifact_path",
        )
        payload = _read_stable_private_file(
            resources._output_root,
            (resources.run_id, *source_parts),
            field="artifact_path",
            maximum_size=min(MAX_ARTIFACT_SIZE_BYTES, maximum_size),
        )
        reference = f"artifact-{uuid.uuid4().hex}"
        stored_parts = ("published", reference)
        write_private_new_file(
            resources._output_root,
            (resources.run_id, *stored_parts),
            payload,
            field="artifact_path",
        )
        descriptor = {
            "artifact_reference": reference,
            "artifact_kind": "standalone",
            "node_id": node_id,
            "output_port": output_port,
            "media_type": self._artifact_media_type(relative_name),
            "size": len(payload),
            "content_digest": (
                "sha256:" + hashlib.sha256(payload).hexdigest()
            ),
        }
        ledger.append(
            "artifact_published",
            {"artifact": descriptor},
        )
        return descriptor, stored_parts

    def _materialize_artifacts(
        self,
        *,
        node: ExecutionPlanNode,
        resources: RunResources,
        published: list[dict[str, Any]],
        runtime: Mapping[tuple[str, str], list[Any]],
        ledger: _RunEvidenceLedger,
        current_artifact_count: int,
        current_artifact_bytes: int,
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
        dict[str, tuple[dict[str, Any], tuple[str, ...]]],
    ]:
        typed_outputs: list[dict[str, Any]] = []
        artifact_index: list[dict[str, Any]] = []
        artifacts: dict[
            str,
            tuple[dict[str, Any], tuple[str, ...]],
        ] = {}
        node_contract = self._catalog.require_contract(*node.node_type.key)
        port_declarations = {
            port["name"]: port
            for port in node_contract.descriptor.get("outputs", ())
        }
        artifact_sources: list[tuple[str, str]] = []
        for output in published:
            port_type_id = output["port_type"]["contract_id"]
            if port_type_id not in {
                "file.path",
                "file.path.collection",
            }:
                typed_outputs.append(output)
                continue
            declaration = port_declarations[output["output_port"]]
            if declaration.get("artifact_kind") != "standalone":
                raise PortValueError(
                    "Artifact output Port requires explicit standalone opt-in"
                )
            decoded_values = runtime[
                (node.node_id, output["output_port"])
            ]
            if port_type_id == "file.path.collection":
                relative_names = [
                    relative_name
                    for collection in decoded_values
                    for relative_name in collection
                ]
            else:
                relative_names = decoded_values
            for relative_name in relative_names:
                if not isinstance(relative_name, str):
                    raise PortValueError(
                        "Artifact Port requires one private relative reference"
                    )
                artifact_sources.append(
                    (output["output_port"], relative_name)
                )
        if (
            current_artifact_count + len(artifact_sources)
            > MAX_ARTIFACTS_PER_RUN
        ):
            raise PortValueError("Run artifact count exceeds the public bound")
        remaining_bytes = (
            MAX_ARTIFACT_BYTES_PER_RUN - current_artifact_bytes
        )
        for output_port, relative_name in artifact_sources:
            descriptor, stored_parts = self._publish_artifact(
                resources=resources,
                node_id=node.node_id,
                output_port=output_port,
                relative_name=relative_name,
                ledger=ledger,
                maximum_size=remaining_bytes,
            )
            remaining_bytes -= descriptor["size"]
            artifact_index.append(descriptor)
            artifacts[descriptor["artifact_reference"]] = (
                descriptor,
                stored_parts,
            )
        return typed_outputs, artifact_index, artifacts

    def start(
        self,
        project_id: str,
        *,
        workflow_revision: int,
        compile_id: str,
        client_request_id: str,
    ) -> dict[str, Any]:
        del client_request_id
        compiled = self._authoring.require_compiled(
            project_id,
            workflow_revision=workflow_revision,
            compile_id=compile_id,
        )
        plan = compiled.execution_plan
        if plan.catalog_contract_digest != self._catalog.contract_digest:
            raise V2RunError(
                "contract_digest_mismatch",
                "Compiled FrozenCatalog identity is no longer current",
                details={
                    "issues": [
                        {
                            "code": "catalog_contract_digest_mismatch",
                            "severity": "error",
                            "message": (
                                "Start Run requires the FrozenCatalog used "
                                "during compilation"
                            ),
                            "field_path": ["compile_id"],
                        }
                    ]
                },
            )
        run_id = f"run-{uuid.uuid4().hex}"
        try:
            ledger = _RunEvidenceLedger(
                self._projects,
                project_id,
                run_id,
                plan,
            )
        except (OSError, StoragePathError) as error:
            raise V2RunError(
                "evidence_unavailable",
                "Required Run evidence workspace is unavailable",
                details={"last_durable_cursor": run_cursor(0)},
            ) from error
        ledger.append(
            "run_scope_bound",
            {
                "project_id": project_id,
                "run_id": run_id,
                "workflow_revision": workflow_revision,
                "workflow_digest": plan.workflow_digest,
                "contract_lock_digest": plan.contract_lock_digest,
                "compile_id": compile_id,
                "execution_plan_digest": plan.execution_plan_digest,
                "catalog_contract_digest": plan.catalog_contract_digest,
                "resolved_contracts": [
                    entry.to_public()
                    for entry in plan.resolved_contracts
                ],
            },
        )
        distinct: dict[tuple[str, str], ExecutionPlanNode] = {}
        for node in plan.nodes:
            distinct.setdefault(
                (
                    node.binding.contract_id,
                    node.binding.contract_version,
                ),
                node,
            )
        for identity, node in distinct.items():
            availability = self._availability(*identity)
            ledger.append(
                "availability_bound",
                {
                    "binding": node.binding.to_public(),
                    "catalog_observed_at": availability["observed_at"],
                    "available": availability["available"],
                },
            )
            if availability["available"] is not True:
                raise V2RunError(
                    "binding_unavailable",
                    "Selected Binding is unavailable",
                    details={
                        "binding": node.binding.to_public(),
                        "reason_code": availability["reason"]["code"],
                    },
                )
            self._attest_readiness(node=node, ledger=ledger)
        admitted = ledger.append(
            "run_admitted",
            {
                "workflow_revision": workflow_revision,
                "compile_id": compile_id,
            },
        )
        ledger.append("run_started", {"started_at": run_timestamp()})

        all_artifacts: list[dict[str, Any]] = []
        artifact_records: dict[
            str,
            tuple[dict[str, Any], tuple[str, ...]],
        ] = {}
        values: dict[tuple[str, str], list[Any]] = {}
        disposition_outcomes: dict[str, str] = {}
        for node in plan.nodes:
            blocked_by = sorted(
                {
                    edge.source_node_id
                    for edge in plan.edges
                    if edge.target_node_id == node.node_id
                    and disposition_outcomes.get(edge.source_node_id)
                    != "succeeded"
                }
            )
            if blocked_by:
                ledger.append(
                    "node_disposition",
                    {
                        "node_id": node.node_id,
                        "outcome": "blocked",
                        "blocked_by": blocked_by,
                    },
                )
                disposition_outcomes[node.node_id] = "blocked"
                continue
            node_attempt_id = f"node-attempt-{uuid.uuid4().hex}"
            operation_attempt_id = f"operation-{uuid.uuid4().hex}"
            invocation_id = f"invocation-{uuid.uuid4().hex}"
            node_inputs = self._inputs_for(plan, node, values)
            binding_contract = self._catalog.require_contract(
                *node.binding.key,
            )
            replayed_outputs = None
            if binding_contract.descriptor.get("cacheable") is True:
                replayed_outputs = self._result_replay_source.lookup(
                    project_id=project_id,
                    execution_plan=plan,
                    node=node,
                    inputs=node_inputs,
                )
            if replayed_outputs is not None:
                ledger.append(
                    "node_attempt_started",
                    {
                        "node_id": node.node_id,
                        "node_attempt_id": node_attempt_id,
                    },
                )
                published, runtime = self._validate_outputs(
                    node,
                    replayed_outputs,
                )
                if any(
                    output["port_type"]["contract_id"]
                    in {"file.path", "file.path.collection"}
                    for output in published
                ):
                    raise V2RunError(
                        "internal_error",
                        "Cache replay contained a path-valued result",
                        details={
                            "incident_id": f"incident-{uuid.uuid4().hex}"
                        },
                    )
                ledger.append(
                    "outputs_published",
                    {
                        "node_id": node.node_id,
                        "outputs": published,
                        "artifacts": [],
                    },
                )
                ledger.append(
                    "node_attempt_terminal",
                    {
                        "node_attempt_id": node_attempt_id,
                        "status": "succeeded",
                        "resolution": "cache_replayed",
                    },
                )
                ledger.append(
                    "node_disposition",
                    {
                        "node_id": node.node_id,
                        "outcome": "succeeded",
                        "resolution": "cache_replayed",
                        "blocked_by": [],
                    },
                )
                values.update(runtime)
                disposition_outcomes[node.node_id] = "succeeded"
                continue
            resources = RunResources(
                project_id,
                run_id,
                node.node_id,
                self._projects,
            )
            body_error: BaseException | None = None
            implementation: Any | None = None
            try:
                environment = self._environment.for_binding(
                    node.binding.contract_id,
                    node.binding.contract_version,
                )
                factory = self._catalog.require_factory(
                    node.binding.contract_id,
                    node.binding.contract_version,
                )
                implementation = factory.build(
                    execution_plan=plan,
                    frozen_catalog=self._catalog,
                    environment_configuration=environment.values,
                    run_resources=resources,
                )
            except PreScheduleTermination as termination:
                try:
                    resources.cleanup_temporary_work()
                except BaseException as cleanup_error:
                    termination.add_note(
                        "Run workspace cleanup also failed: "
                        f"{type(cleanup_error).__name__}"
                    )
                ledger.append(
                    "node_disposition",
                    {
                        "node_id": node.node_id,
                        "outcome": termination.outcome,
                        "blocked_by": [],
                    },
                )
                disposition_outcomes[node.node_id] = termination.outcome
                continue
            except BaseException as error:
                body_error = error
            ledger.append(
                "node_attempt_started",
                {
                    "node_id": node.node_id,
                    "node_attempt_id": node_attempt_id,
                },
            )
            try:
                if body_error is not None:
                    raise body_error
                ledger.append(
                    "operation_attempt_started",
                    {
                        "operation_attempt_id": operation_attempt_id,
                        "node_attempt_id": node_attempt_id,
                    },
                )
                ledger.append(
                    "engine_invocation_started",
                    {
                        "invocation_id": invocation_id,
                        "operation_attempt_id": operation_attempt_id,
                        "engine_role": "primary",
                        "engine_identity": node.method.contract_digest,
                    },
                )
                try:
                    assert implementation is not None
                    raw_outputs = implementation.execute(
                        inputs=node_inputs,
                        node_parameters=dict(node.node_parameters),
                        binding_parameters=dict(node.binding_parameters),
                    )
                except BaseException as error:
                    terminal_status = (
                        error.status
                        if isinstance(error, ExecutionTermination)
                        else "failed"
                    )
                    ledger.append(
                        "engine_invocation_terminal",
                        {
                            "invocation_id": invocation_id,
                            "status": terminal_status,
                            "error": _public_failure(error),
                        },
                    )
                    raise
                else:
                    ledger.append(
                        "engine_invocation_terminal",
                        {
                            "invocation_id": invocation_id,
                            "status": "succeeded",
                        },
                    )
                published, runtime = self._validate_outputs(
                    node,
                    raw_outputs,
                )
                (
                    typed_outputs,
                    node_artifacts,
                    node_artifact_records,
                ) = self._materialize_artifacts(
                    node=node,
                    resources=resources,
                    published=published,
                    runtime=runtime,
                    ledger=ledger,
                    current_artifact_count=len(all_artifacts),
                    current_artifact_bytes=sum(
                        artifact["size"]
                        for artifact in all_artifacts
                    ),
                )
                values.update(runtime)
                all_artifacts.extend(node_artifacts)
                artifact_records.update(node_artifact_records)
                ledger.append(
                    "outputs_published",
                    {
                        "node_id": node.node_id,
                        "outputs": typed_outputs,
                        "artifacts": node_artifacts,
                    },
                )
            except BaseException as error:
                body_error = error
            finally:
                try:
                    resources.cleanup_temporary_work()
                except BaseException as cleanup_error:
                    if body_error is not None:
                        body_error.add_note(
                            "Run workspace cleanup also failed: "
                            f"{type(cleanup_error).__name__}"
                        )
                    else:
                        body_error = cleanup_error
            if body_error is not None:
                if (
                    isinstance(body_error, V2RunError)
                    and body_error.code == "evidence_unavailable"
                ):
                    raise body_error
                terminal_status = (
                    body_error.status
                    if isinstance(body_error, ExecutionTermination)
                    else "failed"
                )
                disposition_outcome = (
                    "interrupted"
                    if terminal_status == "outcome_unknown"
                    else terminal_status
                )
                public_error = _public_failure(body_error)
                operation_started = any(
                    fact["fact_type"] == "operation_attempt_started"
                    and fact["payload"]["operation_attempt_id"]
                    == operation_attempt_id
                    for fact in ledger.facts
                )
                if operation_started:
                    ledger.append(
                        "operation_attempt_terminal",
                        {
                            "operation_attempt_id": operation_attempt_id,
                            "status": terminal_status,
                            "error": public_error,
                        },
                    )
                ledger.append(
                    "node_attempt_terminal",
                    {
                        "node_attempt_id": node_attempt_id,
                        "status": terminal_status,
                        "resolution": "executed",
                        "error": public_error,
                    },
                )
                ledger.append(
                    "node_disposition",
                    {
                        "node_id": node.node_id,
                        "outcome": disposition_outcome,
                        "blocked_by": [],
                    },
                )
                disposition_outcomes[node.node_id] = disposition_outcome
                continue
            ledger.append(
                "operation_attempt_terminal",
                {
                    "operation_attempt_id": operation_attempt_id,
                    "status": "succeeded",
                },
            )
            ledger.append(
                "node_attempt_terminal",
                {
                    "node_attempt_id": node_attempt_id,
                    "status": "succeeded",
                    "resolution": "executed",
                },
            )
            ledger.append(
                "node_disposition",
                {
                    "node_id": node.node_id,
                    "outcome": "succeeded",
                    "resolution": "executed",
                    "blocked_by": [],
                },
            )
            disposition_outcomes[node.node_id] = "succeeded"
        run_status = (
            "failed"
            if "failed" in disposition_outcomes.values()
            else "interrupted"
            if "interrupted" in disposition_outcomes.values()
            else "cancelled"
            if "cancelled" in disposition_outcomes.values()
            else "succeeded"
        )
        ledger.append("run_terminal", {"status": run_status})
        projection = self._project_terminal_run(
            project_id=project_id,
            run_id=run_id,
            workflow_revision=workflow_revision,
            compile_id=compile_id,
            plan=plan,
            ledger=ledger,
        )
        self._runs[(project_id, run_id)] = _RunRecord(
            compiled=compiled,
            ledger=ledger,
            projection=projection,
            artifacts=artifact_records,
        )
        self._run_owners[run_id] = project_id
        return {
            "project_id": project_id,
            "run_id": run_id,
            "workflow_revision": workflow_revision,
            "compile_id": compile_id,
            "admitted_sequence": admitted["sequence"],
            "event_cursor": run_cursor(admitted["sequence"]),
        }

    def projection(self, project_id: str, run_id: str) -> dict[str, Any]:
        record = self._require_record(project_id, run_id)
        return json.loads(json.dumps(record.projection))

    def artifact(
        self,
        project_id: str,
        run_id: str,
        artifact_reference: str,
    ) -> tuple[dict[str, Any], bytes]:
        record = self._require_record(project_id, run_id)
        try:
            descriptor, stored_parts = record.artifacts[artifact_reference]
        except KeyError as error:
            raise V2RunError(
                "artifact_not_found",
                "Artifact was not found",
                details={
                    "resource_kind": "artifact",
                    "resource_id": artifact_reference,
                },
            ) from error
        output_root = self._projects.output_dir(project_id, run_id).parent
        try:
            payload = _read_stable_private_file(
                output_root,
                (run_id, *stored_parts),
                field="artifact_reference",
                maximum_size=MAX_ARTIFACT_SIZE_BYTES,
            )
        except (OSError, StoragePathError) as error:
            raise V2RunError(
                "artifact_integrity_mismatch",
                "Artifact integrity validation failed",
                details={"artifact_reference": artifact_reference},
            ) from error
        observed_digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        if (
            len(payload) != descriptor["size"]
            or observed_digest != descriptor["content_digest"]
        ):
            raise V2RunError(
                "artifact_integrity_mismatch",
                "Artifact integrity validation failed",
                details={
                    "artifact_reference": artifact_reference,
                    "expected_digest": descriptor["content_digest"],
                    "observed_digest": observed_digest,
                    "observed_size": len(payload),
                },
            )
        return json.loads(json.dumps(descriptor)), payload

    def public_events(
        self,
        project_id: str,
        run_id: str,
    ) -> tuple[dict[str, Any], ...]:
        record = self._require_record(project_id, run_id)
        events: list[dict[str, Any]] = []
        for fact in record.ledger.facts:
            event = _public_event_from_fact(
                project_id=project_id,
                run_id=run_id,
                fact=fact,
            )
            if event is not None:
                events.append(event)
        return tuple(events)

    def ledger_cursor(self, project_id: str, run_id: str) -> str:
        return self._require_record(project_id, run_id).ledger.cursor
