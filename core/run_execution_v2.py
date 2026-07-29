"""Readiness-gated direct execution and durable public Run projections."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import threading
import time
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
from core.process_control import signal_process_group
from core.project import ProjectManager
from core.run_manifest import sanitize_public_value
from core.storage import (
    StoragePathError,
    open_private_regular_file,
    remove_private_regular_file,
    replace_private_regular_file,
    validate_identifier,
    validate_relative_path,
    write_private_new_file,
)
from core.workflow_authoring_v2 import WorkflowAuthoringService
from core.workflow_v2 import (
    CompiledWorkflow,
    ExecutionPlan,
    ExecutionPlanNode,
    parse_workflow_document,
)


READINESS_ATTESTATION_NAMESPACE = (
    "protein-workbench-readiness-attestation/v2"
)
RUN_LEDGER_SCHEMA_VERSION = "2.0.0"
MAX_ARTIFACTS_PER_RUN = 2_048
MAX_ARTIFACT_SIZE_BYTES = 64 * 1024 * 1024
MAX_ARTIFACT_BYTES_PER_RUN = 256 * 1024 * 1024
MAX_LEDGER_FACT_BYTES = 4 * 1024 * 1024
MAX_BACKGROUND_RUNS = 8
FAST_RUN_COMPLETION_GRACE_SECONDS = 0.25
CANCELLATION_TERM_GRACE_SECONDS = 0.25
CANCELLATION_KILL_GRACE_SECONDS = 0.25
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


def _cursor_fact_digest(fact: Mapping[str, Any] | None) -> str:
    if fact is None:
        return "origin"
    return canonical_sha256(dict(fact))


def run_cursor(
    sequence: int,
    *,
    project_id: str = "unavailable",
    run_id: str = "unavailable",
    fact: Mapping[str, Any] | None = None,
) -> str:
    """Encode a scope-bound durable position without exposing its structure."""
    payload = canonical_json_bytes(
        {
            "schema_namespace": "protein-workbench-run-cursor/v2",
            "scope_digest": canonical_sha256(
                {
                    "schema_namespace": "protein-workbench-run-scope/v2",
                    "project_id": project_id,
                    "run_id": run_id,
                }
            ),
            "sequence": sequence,
            "fact_digest": _cursor_fact_digest(fact),
        }
    )
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    return f"pw2.{encoded}"


def _decode_run_cursor(value: str) -> Mapping[str, Any]:
    if not isinstance(value, str) or not value.startswith("pw2."):
        raise ValueError("cursor prefix is invalid")
    encoded = value.removeprefix("pw2.")
    if not encoded or not re.fullmatch(r"[A-Za-z0-9_-]+", encoded):
        raise ValueError("cursor encoding is invalid")
    padding = "=" * (-len(encoded) % 4)
    try:
        decoded = base64.b64decode(
            encoded + padding,
            altchars=b"-_",
            validate=True,
        )
        payload = json.loads(decoded)
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("cursor encoding is invalid") from error
    if (
        not isinstance(payload, dict)
        or set(payload)
        != {
            "schema_namespace",
            "scope_digest",
            "sequence",
            "fact_digest",
        }
        or payload["schema_namespace"]
        != "protein-workbench-run-cursor/v2"
        or not isinstance(payload["scope_digest"], str)
        or type(payload["sequence"]) is not int
        or payload["sequence"] < 0
        or not isinstance(payload["fact_digest"], str)
    ):
        raise ValueError("cursor payload is invalid")
    return payload


def _safe_cursor_detail(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return "invalid"
    return value[:512]


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
        "cursor": run_cursor(
            fact["sequence"],
            project_id=project_id,
            run_id=run_id,
            fact=fact,
        ),
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


class _CancellationControl:
    """Thread-safe owner of active process groups for one Run."""

    def __init__(self) -> None:
        self._condition = threading.Condition(threading.RLock())
        self._cleanup_lock = threading.Lock()
        self._cleanup_complete = threading.Event()
        self._requested = False
        self._next_registration = 0
        self._cleanup_error: BaseException | None = None
        self._process_groups: dict[
            int,
            tuple[int, Callable[[], None] | None],
        ] = {}

    def register_process_group(
        self,
        process_group: int,
        *,
        fallback: Callable[[], None] | None,
    ) -> int:
        if type(process_group) is not int:
            raise ValueError("Process-group identity must be an integer")
        with self._condition:
            self._next_registration += 1
            registration = self._next_registration
            self._process_groups[registration] = (
                process_group,
                fallback,
            )
            requested = self._requested
            if requested:
                self._cleanup_complete.clear()
        if requested:
            threading.Thread(
                target=self.request,
                name=f"run-cancellation-cleanup-{registration}",
                daemon=True,
            ).start()
        return registration

    def unregister_process_group(self, registration: int) -> None:
        with self._condition:
            group = self._process_groups.get(registration)
            if group is None or not self._process_group_active(group[0]):
                self._process_groups.pop(registration, None)
            self._condition.notify_all()

    @staticmethod
    def _process_group_active(process_group: int) -> bool:
        if process_group <= 1 or process_group == os.getpgrp():
            return True
        try:
            os.killpg(process_group, 0)
        except ProcessLookupError:
            return False
        except (PermissionError, OSError):
            return True
        return True

    def _active_groups(
        self,
    ) -> tuple[tuple[int, int, Callable[[], None] | None], ...]:
        with self._condition:
            for registration, (process_group, _) in tuple(
                self._process_groups.items()
            ):
                if not self._process_group_active(process_group):
                    self._process_groups.pop(registration, None)
            return tuple(
                (registration, process_group, fallback)
                for registration, (process_group, fallback)
                in self._process_groups.items()
            )

    def _signal_all(self, process_signal: signal.Signals) -> None:
        for _, process_group, fallback in self._active_groups():
            try:
                signal_process_group(
                    process_group,
                    process_signal,
                    fallback=fallback,
                )
            except BaseException as error:
                with self._condition:
                    if self._cleanup_error is None:
                        self._cleanup_error = error

    def _wait_for_exit(self, timeout_seconds: float) -> bool:
        deadline = time.monotonic() + timeout_seconds
        with self._condition:
            while self._active_groups():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(min(remaining, 0.01))
            return True

    def request(self) -> None:
        with self._cleanup_lock:
            self._cleanup_complete.clear()
            try:
                with self._condition:
                    self._requested = True
                self._signal_all(signal.SIGTERM)
                if self._wait_for_exit(CANCELLATION_TERM_GRACE_SECONDS):
                    return
                self._signal_all(signal.SIGKILL)
                if self._wait_for_exit(CANCELLATION_KILL_GRACE_SECONDS):
                    return
                with self._condition:
                    if self._cleanup_error is None:
                        self._cleanup_error = RuntimeError(
                            "Run process-group cleanup could not be confirmed"
                        )
            finally:
                self._cleanup_complete.set()

    def wait_for_cleanup(self) -> None:
        """Wait until the cancellation owner reaches a bounded conclusion."""
        timeout = (
            CANCELLATION_TERM_GRACE_SECONDS
            + CANCELLATION_KILL_GRACE_SECONDS
            + 0.25
        )
        if self._cleanup_complete.wait(timeout):
            return
        with self._condition:
            if self._cleanup_error is None:
                self._cleanup_error = RuntimeError(
                    "Run cancellation cleanup did not reach a conclusion"
                )

    @property
    def cleanup_error(self) -> BaseException | None:
        with self._condition:
            return self._cleanup_error


@dataclass(frozen=True, slots=True)
class RunResources:
    """Project/Run-contained resources available to one lazy direct factory."""

    project_id: str
    run_id: str
    node_id: str
    _projects: ProjectManager = field(repr=False, compare=False)
    _invocation_recorder: "_OperationInvocationRecorder | None" = field(
        default=None,
        repr=False,
        compare=False,
    )
    _cancellation_control: "_CancellationControl | None" = field(
        default=None,
        repr=False,
        compare=False,
    )

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

    @contextmanager
    def cancellable_process_group(
        self,
        process_group: int,
        *,
        fallback: Callable[[], None] | None = None,
    ):
        """Register one isolated process group for Run cancellation."""
        if self._cancellation_control is None:
            raise RuntimeError("Run cancellation control is unavailable")
        registration = self._cancellation_control.register_process_group(
            process_group,
            fallback=fallback,
        )
        try:
            yield
        finally:
            self._cancellation_control.unregister_process_group(registration)

    @contextmanager
    def engine_invocation(
        self,
        *,
        engine_role: str = "primary",
        engine_identity: str | None = None,
    ):
        """Record one explicit crossing of a scientific engine boundary."""
        if self._invocation_recorder is None:
            raise RuntimeError("Engine Invocation is unavailable")
        with self._invocation_recorder.invoke(
            engine_role=engine_role,
            engine_identity=engine_identity,
        ) as invocation_id:
            yield invocation_id


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


@dataclass(frozen=True, slots=True)
class _PlanNodeEvidence:
    node_id: str
    dependencies: tuple[str, ...]
    required_dependencies: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "dependencies": list(self.dependencies),
            "required_dependencies": list(self.required_dependencies),
        }


class _RunEvidenceLedger:
    """Schema-checked, causally closed owner-only facts for one Run."""

    def __init__(
        self,
        projects: ProjectManager,
        project_id: str,
        run_id: str,
        plan_nodes: tuple[_PlanNodeEvidence, ...],
    ) -> None:
        run_dir = projects.run_dir(project_id, run_id)
        self._root = run_dir.parent
        self._project_id = project_id
        self._run_id = run_id
        self._facts: list[dict[str, Any]] = []
        self._plan_node_order = tuple(node.node_id for node in plan_nodes)
        self._plan_nodes = frozenset(self._plan_node_order)
        self._dependencies = {
            node.node_id: frozenset(node.dependencies)
            for node in plan_nodes
        }
        self._required_dependencies = {
            node.node_id: frozenset(node.required_dependencies)
            for node in plan_nodes
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
        self._cancellation_sequence: int | None = None
        self._restart_reconciled = False
        self._condition = threading.Condition(threading.RLock())
        self._projection_error: BaseException | None = None

    @property
    def facts(self) -> tuple[dict[str, Any], ...]:
        with self._condition:
            return tuple(json.loads(json.dumps(fact)) for fact in self._facts)

    @property
    def cursor(self) -> str:
        with self._condition:
            return self._cursor_at(len(self._facts))

    @property
    def terminal(self) -> bool:
        with self._condition:
            return self._run_terminal

    @property
    def started(self) -> bool:
        with self._condition:
            return self._run_started

    @property
    def cancellation_requested(self) -> bool:
        with self._condition:
            return self._cancellation_sequence is not None

    @property
    def plan_nodes(self) -> tuple[_PlanNodeEvidence, ...]:
        return tuple(
            _PlanNodeEvidence(
                node_id,
                tuple(sorted(self._dependencies[node_id])),
                tuple(sorted(self._required_dependencies[node_id])),
            )
            for node_id in self._plan_node_order
        )

    def _cursor_at(self, sequence: int) -> str:
        fact = self._facts[sequence - 1] if sequence else None
        return run_cursor(
            sequence,
            project_id=self._project_id,
            run_id=self._run_id,
            fact=fact,
        )

    def sequence_for_cursor(self, cursor: str | None) -> int:
        if cursor is None:
            return 0
        try:
            payload = _decode_run_cursor(cursor)
        except ValueError as error:
            raise V2RunError(
                "invalid_cursor",
                "Run Event Stream cursor is invalid",
                details={"after_sequence": _safe_cursor_detail(cursor)},
            ) from error
        sequence = payload["sequence"]
        with self._condition:
            expected = (
                self._cursor_at(sequence)
                if sequence <= len(self._facts)
                else None
            )
        if (
            payload["scope_digest"]
            != canonical_sha256(
                {
                    "schema_namespace": "protein-workbench-run-scope/v2",
                    "project_id": self._project_id,
                    "run_id": self._run_id,
                }
            )
            or expected != cursor
        ):
            raise V2RunError(
                "invalid_cursor",
                "Run Event Stream cursor is stale or belongs to another scope",
                details={"after_sequence": _safe_cursor_detail(cursor)},
            )
        return sequence

    def cursor_at(self, sequence: int) -> str:
        with self._condition:
            if sequence < 0 or sequence > len(self._facts):
                raise ValueError("Ledger cursor sequence is outside the Run")
            return self._cursor_at(sequence)

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
            if (
                self._facts
                or payload["project_id"] != self._project_id
                or payload["run_id"] != self._run_id
            ):
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
        if fact_type == "cancellation_requested":
            if (
                not self._run_started
                or self._cancellation_sequence is not None
            ):
                raise self._causal_error()
            return
        if fact_type == "restart_reconciliation_started":
            if (
                not self._run_started
                or self._run_terminal
                or self._restart_reconciled
            ):
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
            if child_operations:
                if fact_type == "outputs_published" and any(
                    self._operations[operation_id]["terminal"] != "succeeded"
                    for operation_id in child_operations
                ):
                    raise self._causal_error()
                if fact_type == "artifact_published" and any(
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
                        child_operations
                        or (
                            attempt["node_id"] not in self._outputs_published
                            and not (
                                self._cancellation_sequence is not None
                                and payload["status"] == "cancelled"
                            )
                        )
                        or (
                            payload["status"] != "succeeded"
                            and not (
                                self._restart_reconciled
                                and payload["status"]
                                in {"interrupted", "outcome_unknown"}
                            )
                            and not (
                                self._cancellation_sequence is not None
                                and payload["status"] == "cancelled"
                            )
                        )
                    )
                )
                or (
                    payload["resolution"] == "executed"
                    and payload["status"] == "succeeded"
                    and len(child_operations) != 1
                )
                or (
                    payload["resolution"] == "executed"
                    and child_operations
                    and child_operations[-1]["terminal"]
                    != payload["status"]
                    and not (
                        self._restart_reconciled
                        and payload["status"]
                        in {"interrupted", "outcome_unknown"}
                    )
                    and not (
                        self._cancellation_sequence is not None
                        and payload["status"] == "cancelled"
                    )
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
                if (
                    attempt is not None
                    or not blocked_by
                    or not blocked_by <= self._dependencies[node_id]
                    or any(
                        upstream not in self._dispositions
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
                "interrupted"
                if self._restart_reconciled
                else "failed"
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
                        "plan_nodes",
                    }
                ),
                frozenset({"derived_from"}),
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
            "cancellation_requested": (
                frozenset({"requested_at"}),
                frozenset(),
            ),
            "restart_reconciliation_started": (
                frozenset({"restarted_at"}),
                frozenset(),
            ),
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
        if fact_type == "run_scope_bound":
            plan_nodes = payload["plan_nodes"]
            def valid_plan_node(item: Any) -> bool:
                if (
                    not isinstance(item, Mapping)
                    or set(item)
                    != {
                        "node_id",
                        "dependencies",
                        "required_dependencies",
                    }
                    or item["node_id"] not in self._dependencies
                ):
                    return False
                node_id = item["node_id"]
                return (
                    item["dependencies"]
                    == sorted(self._dependencies[node_id])
                    and item["required_dependencies"]
                    == sorted(self._required_dependencies[node_id])
                )

            if (
                not isinstance(plan_nodes, list)
                or [
                    item.get("node_id")
                    for item in plan_nodes
                    if isinstance(item, Mapping)
                ]
                != list(self._plan_node_order)
                or any(not valid_plan_node(item) for item in plan_nodes)
            ):
                raise self._causal_error()
            derived_from = payload.get("derived_from")
            if derived_from is not None and (
                not isinstance(derived_from, Mapping)
                or set(derived_from)
                != {
                    "source_run_id",
                    "policy",
                    "selected_node_ids",
                    "forced_node_ids",
                }
                or derived_from["policy"]
                not in {"retry_failed", "force_selected"}
                or not isinstance(derived_from["source_run_id"], str)
                or not isinstance(derived_from["selected_node_ids"], list)
                or not isinstance(derived_from["forced_node_ids"], list)
                or not all(
                    isinstance(node_id, str)
                    for node_id in (
                        *derived_from["selected_node_ids"],
                        *derived_from["forced_node_ids"],
                    )
                )
            ):
                raise self._causal_error()
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
        elif fact_type == "cancellation_requested":
            self._cancellation_sequence = len(self._facts)
        elif fact_type == "restart_reconciliation_started":
            self._restart_reconciled = True
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

    def _projection(self) -> dict[str, Any]:
        if not self._facts or self._facts[0]["fact_type"] != "run_scope_bound":
            raise self._causal_error()
        scope = self._facts[0]["payload"]
        dispositions: list[dict[str, Any]] = []
        published_by_node: dict[
            str,
            tuple[list[dict[str, Any]], list[dict[str, Any]]],
        ] = {}
        status = "admitted"
        terminal_sequence: int | None = None
        for fact in self._facts:
            payload = fact["payload"]
            if fact["fact_type"] == "run_started":
                status = "running"
            elif fact["fact_type"] == "node_disposition":
                disposition = dict(payload)
                disposition["terminal_sequence"] = fact["sequence"]
                dispositions.append(disposition)
            elif fact["fact_type"] == "outputs_published":
                published_by_node[payload["node_id"]] = (
                    payload["outputs"],
                    payload["artifacts"],
                )
            elif fact["fact_type"] == "run_terminal":
                status = payload["status"]
                terminal_sequence = fact["sequence"]
        successful_nodes = {
            disposition["node_id"]
            for disposition in dispositions
            if disposition["outcome"] == "succeeded"
        }
        outputs = [
            output
            for node_id in self._plan_node_order
            if node_id in successful_nodes
            for output in published_by_node.get(node_id, ([], []))[0]
        ]
        artifacts = [
            artifact
            for node_id in self._plan_node_order
            if node_id in successful_nodes
            for artifact in published_by_node.get(node_id, ([], []))[1]
        ]
        projection = {
            "project_id": self._project_id,
            "run_id": self._run_id,
            "workflow_revision": scope["workflow_revision"],
            "workflow_digest": scope["workflow_digest"],
            "compile_id": scope["compile_id"],
            "status": status,
            "ledger_cursor": self._cursor_at(len(self._facts)),
            "node_dispositions": dispositions,
            "outputs": outputs,
            "artifact_index": artifacts,
        }
        if terminal_sequence is not None:
            projection["terminal_sequence"] = terminal_sequence
        derived_from = scope.get("derived_from")
        if isinstance(derived_from, Mapping):
            projection["derived_from_run_id"] = derived_from["source_run_id"]
        return projection

    def request_cancellation(
        self,
        after_cursor: str | None,
    ) -> dict[str, Any]:
        """Persist one cancellation decision under the Ledger ordering lock."""
        observed_sequence = self.sequence_for_cursor(after_cursor)
        with self._condition:
            if self._cancellation_sequence is not None:
                decision_sequence = self._cancellation_sequence
                return {
                    "outcome": "already_requested",
                    "decision_sequence": decision_sequence,
                    "cursor": self._cursor_at(decision_sequence),
                }
            if self._run_terminal:
                terminal_sequence = len(self._facts)
                return {
                    "outcome": (
                        "completed_before_cancel"
                        if (
                            after_cursor is not None
                            and observed_sequence < terminal_sequence
                        )
                        else "already_terminal"
                    ),
                    "decision_sequence": terminal_sequence,
                    "cursor": self._cursor_at(terminal_sequence),
                }
            if set(self._dispositions) == set(self._plan_nodes):
                decision_sequence = len(self._facts)
                return {
                    "outcome": "completed_before_cancel",
                    "decision_sequence": decision_sequence,
                    "cursor": self._cursor_at(decision_sequence),
                }
            fact = self.append(
                "cancellation_requested",
                {"requested_at": run_timestamp()},
            )
            return {
                "outcome": "cancellation_requested",
                "decision_sequence": fact["sequence"],
                "cursor": self._cursor_at(fact["sequence"]),
            }

    def projection(self) -> dict[str, Any]:
        with self._condition:
            self._ensure_projection_consistency()
            return json.loads(json.dumps(self._projection()))

    def _refresh_projections(self) -> None:
        manifest = canonical_json_bytes(self._projection())
        lifecycle = b"".join(
            canonical_json_bytes(event) + b"\n"
            for fact in self._facts
            if (
                event := _public_event_from_fact(
                    project_id=self._project_id,
                    run_id=self._run_id,
                    fact=fact,
                )
            )
            is not None
        )
        replace_private_regular_file(
            self._root,
            (self._run_id, "manifest.json"),
            manifest,
            field="run_manifest_projection",
        )
        replace_private_regular_file(
            self._root,
            (self._run_id, "lifecycle.jsonl"),
            lifecycle,
            field="run_lifecycle_projection",
        )

    def rebuild_projections(self) -> None:
        with self._condition:
            try:
                self._refresh_projections()
            except (OSError, StoragePathError) as error:
                self._projection_error = error
                raise
            else:
                self._projection_error = None

    def _ensure_projection_consistency(self) -> None:
        if self._projection_error is None:
            return
        try:
            self._refresh_projections()
        except (OSError, StoragePathError) as error:
            self._projection_error = error
            raise V2RunError(
                "evidence_unavailable",
                "Run projections are temporarily unavailable",
                details={"last_durable_cursor": self.cursor},
            ) from error
        self._projection_error = None

    def append(self, fact_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        with self._condition:
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
            if len(encoded) > MAX_LEDGER_FACT_BYTES:
                raise V2RunError(
                    "evidence_unavailable",
                    "Required Run evidence exceeds the durable fact bound",
                    details={"last_durable_cursor": self.cursor},
                )
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
            for _ in range(2):
                try:
                    self._refresh_projections()
                except (OSError, StoragePathError) as error:
                    self._projection_error = error
                else:
                    self._projection_error = None
                    break
            self._condition.notify_all()
            return json.loads(json.dumps(fact))

    def append_terminal_from_success(
        self,
        fact_type: str,
        identity: Mapping[str, Any],
    ) -> str:
        """Order successful completion against cancellation atomically."""
        with self._condition:
            status = (
                "cancelled"
                if self._cancellation_sequence is not None
                else "succeeded"
            )
            self.append(fact_type, {**identity, "status": status})
            return status

    def commit_node_publication(
        self,
        *,
        node_id: str,
        node_attempt_id: str,
        resolution: str,
        outputs: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        operation_attempt_id: str | None = None,
        cancel_cleanup: Callable[[], None] | None = None,
    ) -> str:
        """Commit one Node outcome atomically against Run cancellation."""
        with self._condition:
            if self._cancellation_sequence is not None:
                cleanup_error: BaseException | None = None
                if cancel_cleanup is not None:
                    try:
                        cancel_cleanup()
                    except BaseException as error:
                        cleanup_error = error
                terminal_status = (
                    "failed" if cleanup_error is not None else "cancelled"
                )
                terminal_payload: dict[str, Any] = {
                    "status": terminal_status,
                }
                if cleanup_error is not None:
                    terminal_payload["error"] = _public_failure(cleanup_error)
                if operation_attempt_id is not None:
                    self.append(
                        "operation_attempt_terminal",
                        {
                            "operation_attempt_id": operation_attempt_id,
                            **terminal_payload,
                        },
                    )
                self.append(
                    "node_attempt_terminal",
                    {
                        "node_attempt_id": node_attempt_id,
                        "resolution": resolution,
                        **terminal_payload,
                    },
                )
                outcome = (
                    "failed"
                    if terminal_status == "failed"
                    else "cancelled"
                )
                self.append(
                    "node_disposition",
                    {
                        "node_id": node_id,
                        "outcome": outcome,
                        "blocked_by": [],
                    },
                )
                return outcome
            if operation_attempt_id is not None:
                self.append(
                    "operation_attempt_terminal",
                    {
                        "operation_attempt_id": operation_attempt_id,
                        "status": "succeeded",
                    },
                )
            for artifact in artifacts:
                self.append(
                    "artifact_published",
                    {"artifact": artifact},
                )
            self.append(
                "outputs_published",
                {
                    "node_id": node_id,
                    "outputs": outputs,
                    "artifacts": artifacts,
                },
            )
            self.append(
                "node_attempt_terminal",
                {
                    "node_attempt_id": node_attempt_id,
                    "status": "succeeded",
                    "resolution": resolution,
                },
            )
            self.append(
                "node_disposition",
                {
                    "node_id": node_id,
                    "outcome": "succeeded",
                    "resolution": resolution,
                    "blocked_by": [],
                },
            )
            return "succeeded"

    def load_fact(self, fact: Mapping[str, Any], encoded: bytes) -> None:
        with self._condition:
            if (
                not isinstance(fact, Mapping)
                or set(fact)
                != {
                    "schema_version",
                    "sequence",
                    "recorded_at",
                    "fact_type",
                    "payload",
                }
                or fact["schema_version"] != RUN_LEDGER_SCHEMA_VERSION
                or fact["sequence"] != len(self._facts) + 1
                or not isinstance(fact["recorded_at"], str)
                or not isinstance(fact["fact_type"], str)
                or not isinstance(fact["payload"], Mapping)
                or canonical_json_bytes(dict(fact)) != encoded
            ):
                raise self._causal_error()
            fact_type = fact["fact_type"]
            payload = dict(fact["payload"])
            self._validate_schema(fact_type, payload)
            self._validate_causality(fact_type, payload)
            event = _public_event_from_fact(
                project_id=self._project_id,
                run_id=self._run_id,
                fact=fact,
            )
            if event is not None:
                validate_event(event)
            retained = json.loads(json.dumps(fact))
            self._facts.append(retained)
            self._apply(fact_type, payload)

    def public_events(
        self,
        *,
        after_sequence: int = 0,
        through_sequence: int | None = None,
    ) -> tuple[dict[str, Any], ...]:
        with self._condition:
            self._ensure_projection_consistency()
            upper = (
                len(self._facts)
                if through_sequence is None
                else min(through_sequence, len(self._facts))
            )
            return tuple(
                event
                for fact in self._facts[after_sequence:upper]
                if (
                    event := _public_event_from_fact(
                        project_id=self._project_id,
                        run_id=self._run_id,
                        fact=fact,
                    )
                )
                is not None
            )

    def replay_window(
        self,
        cursor: str | None,
    ) -> tuple[int, str, int, str, tuple[dict[str, Any], ...], bool]:
        after_sequence = self.sequence_for_cursor(cursor)
        with self._condition:
            through_sequence = len(self._facts)
            through_cursor = self._cursor_at(through_sequence)
            events = self.public_events(
                after_sequence=after_sequence,
                through_sequence=through_sequence,
            )
            return (
                after_sequence,
                self._cursor_at(after_sequence),
                through_sequence,
                through_cursor,
                events,
                self._run_terminal,
            )

    def wait_for_public_events(
        self,
        after_sequence: int,
        *,
        timeout_seconds: float,
    ) -> tuple[tuple[dict[str, Any], ...], int, bool]:
        with self._condition:
            if len(self._facts) <= after_sequence and not self._run_terminal:
                self._condition.wait(timeout_seconds)
            return (
                self.public_events(after_sequence=after_sequence),
                len(self._facts),
                self._run_terminal,
            )

    def reconcile_restart(self) -> None:
        with self._condition:
            if not self._run_started or self._run_terminal:
                return
        if not self._restart_reconciled:
            self.append(
                "restart_reconciliation_started",
                {"restarted_at": run_timestamp()},
            )
        restart_error = {
            "code": "node_execution_failed",
            "message": "Execution outcome is unavailable after backend restart",
            "retryable": False,
            "correlation_id": f"restart-{self._run_id}",
            "details": {"reason": "backend_restart"},
        }
        for invocation_id, invocation in tuple(self._invocations.items()):
            if invocation["terminal"] is None:
                self.append(
                    "engine_invocation_terminal",
                    {
                        "invocation_id": invocation_id,
                        "status": "outcome_unknown",
                        "error": restart_error,
                    },
                )
        for operation_id, operation in tuple(self._operations.items()):
            if operation["terminal"] is not None:
                continue
            child_statuses = [
                invocation["terminal"]
                for invocation in self._invocations.values()
                if invocation["operation_attempt_id"] == operation_id
            ]
            self.append(
                "operation_attempt_terminal",
                {
                    "operation_attempt_id": operation_id,
                    "status": (
                        "outcome_unknown"
                        if "outcome_unknown" in child_statuses
                        else "interrupted"
                    ),
                    "error": restart_error,
                },
            )
        for attempt_id, attempt in tuple(self._node_attempts.items()):
            if attempt["terminal"] is not None:
                continue
            child_statuses = [
                operation["terminal"]
                for operation in self._operations.values()
                if operation["node_attempt_id"] == attempt_id
            ]
            node_id = attempt["node_id"]
            resolution = (
                "cache_replayed"
                if node_id in self._outputs_published and not child_statuses
                else "executed"
            )
            self.append(
                "node_attempt_terminal",
                {
                    "node_attempt_id": attempt_id,
                    "status": (
                        "outcome_unknown"
                        if "outcome_unknown" in child_statuses
                        else "interrupted"
                    ),
                    "resolution": resolution,
                    "error": restart_error,
                },
            )
        for node_id in self._plan_node_order:
            if node_id in self._dispositions:
                continue
            attempt_id = self._node_attempt_by_node.get(node_id)
            if attempt_id is not None:
                attempt = self._node_attempts[attempt_id]
                terminal = attempt["terminal"]
                if terminal is None:
                    raise self._causal_error()
                outcome = {
                    "succeeded": "succeeded",
                    "failed": "failed",
                    "cancelled": "cancelled",
                    "interrupted": "interrupted",
                    "outcome_unknown": "interrupted",
                }[terminal]
                disposition = {
                    "node_id": node_id,
                    "outcome": outcome,
                    "blocked_by": [],
                }
                if outcome == "succeeded":
                    disposition["resolution"] = attempt["resolution"]
                self.append(
                    "node_disposition",
                    disposition,
                )
                continue
            blocked_by = sorted(
                dependency
                for dependency in self._required_dependencies[node_id]
                if self._dispositions.get(dependency, {}).get("outcome")
                != "succeeded"
            )
            self.append(
                "node_disposition",
                {
                    "node_id": node_id,
                    "outcome": "blocked" if blocked_by else "interrupted",
                    "blocked_by": blocked_by,
                },
            )
        self.append("run_terminal", {"status": "interrupted"})


@dataclass(frozen=True, slots=True)
class _OperationInvocationRecorder:
    ledger: _RunEvidenceLedger
    operation_attempt_id: str
    default_engine_identity: str

    @contextmanager
    def invoke(
        self,
        *,
        engine_role: str,
        engine_identity: str | None,
    ):
        invocation_id = f"invocation-{uuid.uuid4().hex}"
        self.ledger.append(
            "engine_invocation_started",
            {
                "invocation_id": invocation_id,
                "operation_attempt_id": self.operation_attempt_id,
                "engine_role": engine_role,
                "engine_identity": (
                    engine_identity or self.default_engine_identity
                ),
            },
        )
        try:
            yield invocation_id
        except BaseException as error:
            terminal_status = (
                "cancelled"
                if self.ledger.cancellation_requested
                else error.status
                if isinstance(error, ExecutionTermination)
                else "failed"
            )
            self.ledger.append(
                "engine_invocation_terminal",
                {
                    "invocation_id": invocation_id,
                    "status": terminal_status,
                    "error": _public_failure(error),
                },
            )
            raise
        else:
            terminal_status = self.ledger.append_terminal_from_success(
                "engine_invocation_terminal",
                {
                    "invocation_id": invocation_id,
                },
            )
            if terminal_status == "cancelled":
                raise ExecutionTermination("cancelled")


@dataclass(slots=True)
class _RunRecord:
    compiled: CompiledWorkflow | None
    ledger: _RunEvidenceLedger
    artifacts: dict[str, tuple[dict[str, Any], tuple[str, ...]]]
    cancellation: _CancellationControl = field(
        default_factory=_CancellationControl,
    )
    finished: threading.Event = field(default_factory=threading.Event)
    execution_error: BaseException | None = None


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
        self._damaged_runs: dict[tuple[str, str], str] = {}
        self._run_owners: dict[str, str] = {}
        self._worker_condition = threading.Condition(threading.RLock())
        self._workers: set[threading.Thread] = set()
        self._reserved_projects: set[str] = set()
        self._execution_lock = threading.Lock()
        self._closed = False
        self._proofs: dict[
            tuple[str, str, str, str],
            ReusableReadinessProof,
        ] = {}
        self._load_persisted_runs()

    def _plan_evidence(
        self,
        plan: ExecutionPlan,
    ) -> tuple[_PlanNodeEvidence, ...]:
        dependencies: dict[str, set[str]] = {
            node.node_id: set() for node in plan.nodes
        }
        required_dependencies: dict[str, set[str]] = {
            node.node_id: set() for node in plan.nodes
        }
        nodes = {node.node_id: node for node in plan.nodes}
        for edge in plan.edges:
            dependencies[edge.target_node_id].add(edge.source_node_id)
            target = nodes[edge.target_node_id]
            contract = self._catalog.require_contract(*target.node_type.key)
            ports = {
                port["name"]: port
                for port in contract.descriptor.get("inputs", ())
            }
            if ports[edge.target_port]["required"] is True:
                required_dependencies[edge.target_node_id].add(
                    edge.source_node_id
                )
        return tuple(
            _PlanNodeEvidence(
                node.node_id,
                tuple(sorted(dependencies[node.node_id])),
                tuple(sorted(required_dependencies[node.node_id])),
            )
            for node in plan.nodes
        )

    @staticmethod
    def _parse_plan_evidence(
        value: Any,
    ) -> tuple[_PlanNodeEvidence, ...]:
        if not isinstance(value, list):
            raise ValueError("Run plan evidence is invalid")
        parsed: list[_PlanNodeEvidence] = []
        seen: set[str] = set()
        for item in value:
            if (
                not isinstance(item, Mapping)
                or set(item)
                != {
                    "node_id",
                    "dependencies",
                    "required_dependencies",
                }
                or not isinstance(item["node_id"], str)
                or not isinstance(item["dependencies"], list)
                or not isinstance(item["required_dependencies"], list)
                or not all(
                    isinstance(dependency, str)
                    for dependency in (
                        *item["dependencies"],
                        *item["required_dependencies"],
                    )
                )
                or item["node_id"] in seen
            ):
                raise ValueError("Run plan evidence is invalid")
            node_id = validate_identifier(item["node_id"], "node_id")
            dependencies = tuple(sorted(set(item["dependencies"])))
            required = tuple(sorted(set(item["required_dependencies"])))
            if (
                list(dependencies) != item["dependencies"]
                or list(required) != item["required_dependencies"]
                or not set(required) <= set(dependencies)
            ):
                raise ValueError("Run plan evidence is invalid")
            seen.add(node_id)
            parsed.append(_PlanNodeEvidence(node_id, dependencies, required))
        if any(
            dependency not in seen
            for node in parsed
            for dependency in node.dependencies
        ):
            raise ValueError("Run plan evidence is invalid")
        return tuple(parsed)

    def _run_directories(self):
        for project in self._projects.list_projects():
            project_id = validate_identifier(project.id, "project_id")
            run_parent = (
                self._projects.run_root / project_id
                if self._projects.run_root is not None
                else self._projects.project_dir(project_id) / "runs"
            )
            if (
                not run_parent.is_dir()
                or run_parent.is_symlink()
            ):
                continue
            for run_dir in sorted(run_parent.iterdir()):
                if (
                    not run_dir.is_dir()
                    or run_dir.is_symlink()
                    or not (run_dir / "ledger").is_dir()
                    or (run_dir / "ledger").is_symlink()
                ):
                    continue
                try:
                    run_id = validate_identifier(run_dir.name, "run_id")
                except StoragePathError:
                    continue
                yield project_id, run_id, run_parent

    def _load_persisted_runs(self) -> None:
        for project_id, run_id, run_parent in self._run_directories():
            try:
                self._load_persisted_run(
                    project_id,
                    run_id,
                    run_parent,
                )
            except (
                KeyError,
                OSError,
                ProtocolValidationError,
                RuntimeError,
                StoragePathError,
                TypeError,
                V2RunError,
                ValueError,
            ):
                self._damaged_runs[(project_id, run_id)] = run_cursor(
                    0,
                    project_id=project_id,
                    run_id=run_id,
                )
                self._run_owners.setdefault(run_id, project_id)

    def _load_persisted_run(
        self,
        project_id: str,
        run_id: str,
        run_parent: Path,
    ) -> None:
        ledger_dir = run_parent / run_id / "ledger"
        fact_paths = sorted(ledger_dir.glob("*.json"))
        if not fact_paths:
            return
        encoded_facts: list[bytes] = []
        parsed_facts: list[Mapping[str, Any]] = []
        for expected_sequence, path in enumerate(fact_paths, start=1):
            if path.name != f"{expected_sequence:020d}.json":
                raise RuntimeError("Run Ledger sequence is not contiguous")
            encoded = _read_stable_private_file(
                run_parent,
                (run_id, "ledger", path.name),
                field="run_ledger",
                maximum_size=MAX_LEDGER_FACT_BYTES,
            )
            parsed = json.loads(encoded)
            if not isinstance(parsed, Mapping):
                raise RuntimeError("Run Ledger fact is invalid")
            encoded_facts.append(encoded)
            parsed_facts.append(parsed)
        first = parsed_facts[0]
        plan_nodes = self._parse_plan_evidence(
            first["payload"]["plan_nodes"]
        )
        ledger = _RunEvidenceLedger(
            self._projects,
            project_id,
            run_id,
            plan_nodes,
        )
        for fact, encoded in zip(
            parsed_facts,
            encoded_facts,
            strict=True,
        ):
            ledger.load_fact(fact, encoded)
        if not ledger.started:
            return
        if (
            run_id in self._run_owners
            and self._run_owners[run_id] != project_id
        ):
            raise RuntimeError("Run identity appears in multiple Projects")
        ledger.reconcile_restart()
        try:
            ledger.rebuild_projections()
        except (OSError, StoragePathError):
            pass
        artifacts: dict[
            str,
            tuple[dict[str, Any], tuple[str, ...]],
        ] = {}
        for descriptor in ledger.projection()["artifact_index"]:
            reference = descriptor["artifact_reference"]
            artifacts[reference] = (
                descriptor,
                ("published", reference),
            )
        record = _RunRecord(
            compiled=None,
            ledger=ledger,
            artifacts=artifacts,
        )
        if ledger.terminal:
            record.finished.set()
        self._runs[(project_id, run_id)] = record
        self._run_owners[run_id] = project_id

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
            damaged_cursor = self._damaged_runs.get((project_id, run_id))
            if damaged_cursor is not None:
                raise V2RunError(
                    "evidence_unavailable",
                    "Required Run evidence is damaged and unavailable",
                    details={"last_durable_cursor": damaged_cursor},
                ) from error
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
            node_contract = self._catalog.require_contract(
                *node.node_type.key,
            )
            port, port_type = _port_contract(
                self._catalog,
                node_contract,
                "inputs",
                edge.target_port,
            )
            source_values = values.get(
                (edge.source_node_id, edge.source_port),
                [],
            )
            if not source_values:
                continue
            for value in source_values:
                port_type.decode(port_type.encode(value))
            if port["multiplicity"] == "many":
                inputs.setdefault(edge.target_port, []).extend(source_values)
            else:
                inputs[edge.target_port] = source_values[0]
        return inputs

    def _required_input_blockers(
        self,
        plan: ExecutionPlan,
        node: ExecutionPlanNode,
        values: Mapping[tuple[str, str], list[Any]],
    ) -> list[str]:
        node_contract = self._catalog.require_contract(*node.node_type.key)
        required_ports = {
            port["name"]
            for port in node_contract.descriptor.get("inputs", ())
            if port.get("required") is True
        }
        blockers: set[str] = set()
        for port_name in required_ports:
            incoming = [
                edge
                for edge in plan.edges
                if edge.target_node_id == node.node_id
                and edge.target_port == port_name
            ]
            if any(
                values.get((edge.source_node_id, edge.source_port))
                for edge in incoming
            ):
                continue
            blockers.update(edge.source_node_id for edge in incoming)
        return sorted(blockers)

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
        return descriptor, stored_parts

    def _materialize_artifacts(
        self,
        *,
        node: ExecutionPlanNode,
        resources: RunResources,
        published: list[dict[str, Any]],
        runtime: Mapping[tuple[str, str], list[Any]],
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
        try:
            for output_port, relative_name in artifact_sources:
                descriptor, stored_parts = self._publish_artifact(
                    resources=resources,
                    node_id=node.node_id,
                    output_port=output_port,
                    relative_name=relative_name,
                    maximum_size=remaining_bytes,
                )
                remaining_bytes -= descriptor["size"]
                artifact_index.append(descriptor)
                artifacts[descriptor["artifact_reference"]] = (
                    descriptor,
                    stored_parts,
                )
        except BaseException as body_error:
            for _, stored_parts in artifacts.values():
                try:
                    remove_private_regular_file(
                        resources._output_root,
                        (resources.run_id, *stored_parts),
                        field="artifact_path",
                    )
                except BaseException as cleanup_error:
                    body_error.add_note(
                        "Artifact rollback also failed: "
                        f"{type(cleanup_error).__name__}"
                    )
            raise
        return typed_outputs, artifact_index, artifacts

    def start(
        self,
        project_id: str,
        *,
        workflow_revision: int,
        compile_id: str,
        client_request_id: str,
        _on_admitted: Callable[
            [dict[str, Any], _RunRecord],
            None,
        ]
        | None = None,
        _before_execute: Callable[[], None] | None = None,
        _derived_from: Mapping[str, Any] | None = None,
        _cache_bypass_nodes: frozenset[str] = frozenset(),
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
        plan_evidence = self._plan_evidence(plan)
        try:
            ledger = _RunEvidenceLedger(
                self._projects,
                project_id,
                run_id,
                plan_evidence,
            )
        except (OSError, StoragePathError) as error:
            raise V2RunError(
                "evidence_unavailable",
                "Required Run evidence workspace is unavailable",
                details={"last_durable_cursor": run_cursor(0)},
            ) from error
        scope_payload: dict[str, Any] = {
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
            "plan_nodes": [
                node.to_dict()
                for node in plan_evidence
            ],
        }
        if _derived_from is not None:
            scope_payload["derived_from"] = dict(_derived_from)
        ledger.append(
            "run_scope_bound",
            scope_payload,
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
        record = _RunRecord(
            compiled=compiled,
            ledger=ledger,
            artifacts=artifact_records,
        )

        def require_cancellation_cleanup() -> None:
            record.cancellation.wait_for_cleanup()
            cleanup_error = record.cancellation.cleanup_error
            if cleanup_error is not None:
                raise cleanup_error

        self._runs[(project_id, run_id)] = record
        self._run_owners[run_id] = project_id
        receipt = {
            "project_id": project_id,
            "run_id": run_id,
            "workflow_revision": workflow_revision,
            "compile_id": compile_id,
            "admitted_sequence": admitted["sequence"],
            "event_cursor": ledger.cursor_at(admitted["sequence"]),
        }
        if _on_admitted is not None:
            _on_admitted(receipt, record)
        if _before_execute is not None:
            _before_execute()
        values: dict[tuple[str, str], list[Any]] = {}
        disposition_outcomes: dict[str, str] = {}
        for node in plan.nodes:
            if ledger.cancellation_requested:
                record.cancellation.wait_for_cleanup()
                cancellation_outcome = (
                    "interrupted"
                    if record.cancellation.cleanup_error is not None
                    else "cancelled"
                )
                ledger.append(
                    "node_disposition",
                    {
                        "node_id": node.node_id,
                        "outcome": cancellation_outcome,
                        "blocked_by": [],
                    },
                )
                disposition_outcomes[node.node_id] = cancellation_outcome
                continue
            blocked_by = self._required_input_blockers(
                plan,
                node,
                values,
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
            node_inputs = self._inputs_for(plan, node, values)
            binding_contract = self._catalog.require_contract(
                *node.binding.key,
            )
            replayed_published: list[dict[str, Any]] | None = None
            replayed_runtime: dict[
                tuple[str, str],
                list[Any],
            ] | None = None
            if (
                binding_contract.descriptor.get("cacheable") is True
                and node.node_id not in _cache_bypass_nodes
            ):
                try:
                    replayed_outputs = self._result_replay_source.lookup(
                        project_id=project_id,
                        execution_plan=plan,
                        node=node,
                        inputs=node_inputs,
                    )
                    if replayed_outputs is not None:
                        candidate_published, candidate_runtime = (
                            self._validate_outputs(
                                node,
                                replayed_outputs,
                            )
                        )
                        if not any(
                            output["port_type"]["contract_id"]
                            in {"file.path", "file.path.collection"}
                            for output in candidate_published
                        ):
                            replayed_published = candidate_published
                            replayed_runtime = candidate_runtime
                except Exception:
                    replayed_published = None
                    replayed_runtime = None
            if replayed_published is not None and replayed_runtime is not None:
                if ledger.cancellation_requested:
                    record.cancellation.wait_for_cleanup()
                    cancellation_outcome = (
                        "interrupted"
                        if record.cancellation.cleanup_error is not None
                        else "cancelled"
                    )
                    ledger.append(
                        "node_disposition",
                        {
                            "node_id": node.node_id,
                            "outcome": cancellation_outcome,
                            "blocked_by": [],
                        },
                    )
                    disposition_outcomes[node.node_id] = (
                        cancellation_outcome
                    )
                    continue
                ledger.append(
                    "node_attempt_started",
                    {
                        "node_id": node.node_id,
                        "node_attempt_id": node_attempt_id,
                    },
                )
                outcome = ledger.commit_node_publication(
                    node_id=node.node_id,
                    node_attempt_id=node_attempt_id,
                    resolution="cache_replayed",
                    outputs=replayed_published,
                    artifacts=[],
                    cancel_cleanup=require_cancellation_cleanup,
                )
                if outcome == "succeeded":
                    values.update(replayed_runtime)
                disposition_outcomes[node.node_id] = outcome
                continue
            resources = RunResources(
                project_id,
                run_id,
                node.node_id,
                self._projects,
                _OperationInvocationRecorder(
                    ledger=ledger,
                    operation_attempt_id=operation_attempt_id,
                    default_engine_identity=node.method.contract_digest,
                ),
                record.cancellation,
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
                cancellation_outcome: str | None = None
                if ledger.cancellation_requested:
                    record.cancellation.wait_for_cleanup()
                    cancellation_outcome = (
                        "interrupted"
                        if record.cancellation.cleanup_error is not None
                        else "cancelled"
                    )
                try:
                    resources.cleanup_temporary_work()
                except BaseException as cleanup_error:
                    termination.add_note(
                        "Run workspace cleanup also failed: "
                        f"{type(cleanup_error).__name__}"
                    )
                    if cancellation_outcome is not None:
                        cancellation_outcome = "interrupted"
                disposition_outcome = (
                    cancellation_outcome or termination.outcome
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
            except BaseException as error:
                body_error = error
            if ledger.cancellation_requested:
                record.cancellation.wait_for_cleanup()
                cancellation_outcome = "cancelled"
                try:
                    resources.cleanup_temporary_work()
                except BaseException as cleanup_error:
                    cancellation_outcome = "interrupted"
                    if body_error is not None:
                        body_error.add_note(
                            "Run workspace cleanup also failed: "
                            f"{type(cleanup_error).__name__}"
                        )
                if record.cancellation.cleanup_error is not None:
                    cancellation_outcome = "interrupted"
                ledger.append(
                    "node_disposition",
                    {
                        "node_id": node.node_id,
                        "outcome": cancellation_outcome,
                        "blocked_by": [],
                    },
                )
                disposition_outcomes[node.node_id] = cancellation_outcome
                continue
            ledger.append(
                "node_attempt_started",
                {
                    "node_id": node.node_id,
                    "node_attempt_id": node_attempt_id,
                },
            )
            pending_runtime: dict[tuple[str, str], list[Any]] = {}
            pending_typed_outputs: list[dict[str, Any]] = []
            pending_artifacts: list[dict[str, Any]] = []
            pending_artifact_records: dict[
                str,
                tuple[dict[str, Any], tuple[str, ...]],
            ] = {}

            def cleanup_cancelled_publication() -> None:
                cleanup_error: BaseException | None = None
                if ledger.cancellation_requested:
                    record.cancellation.wait_for_cleanup()
                    cleanup_error = record.cancellation.cleanup_error
                for _, stored_parts in pending_artifact_records.values():
                    try:
                        remove_private_regular_file(
                            resources._output_root,
                            (run_id, *stored_parts),
                            field="artifact_path",
                        )
                    except BaseException as error:
                        if cleanup_error is None:
                            cleanup_error = error
                if cleanup_error is not None:
                    raise cleanup_error

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
                assert implementation is not None
                raw_outputs = implementation.execute(
                    inputs=node_inputs,
                    node_parameters=dict(node.node_parameters),
                    binding_parameters=dict(node.binding_parameters),
                )
                if ledger.cancellation_requested:
                    raise ExecutionTermination("cancelled")
                published, pending_runtime = self._validate_outputs(
                    node,
                    raw_outputs,
                )
                (
                    pending_typed_outputs,
                    pending_artifacts,
                    pending_artifact_records,
                ) = self._materialize_artifacts(
                    node=node,
                    resources=resources,
                    published=published,
                    runtime=pending_runtime,
                    current_artifact_count=len(all_artifacts),
                    current_artifact_bytes=sum(
                        artifact["size"]
                        for artifact in all_artifacts
                    ),
                )
                if ledger.cancellation_requested:
                    raise ExecutionTermination("cancelled")
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
                if body_error is not None or ledger.cancellation_requested:
                    try:
                        cleanup_cancelled_publication()
                    except BaseException as cleanup_error:
                        if body_error is not None:
                            cleanup_error.add_note(
                                "Execution also terminated before cleanup: "
                                f"{type(body_error).__name__}"
                            )
                        body_error = cleanup_error
                cancellation_cleanup_error = (
                    record.cancellation.cleanup_error
                )
                if cancellation_cleanup_error is not None:
                    if (
                        body_error is not None
                        and body_error is not cancellation_cleanup_error
                    ):
                        cancellation_cleanup_error.add_note(
                            "Execution also terminated before cleanup: "
                            f"{type(body_error).__name__}"
                        )
                    body_error = cancellation_cleanup_error
            if body_error is not None:
                if ledger.cancellation_requested:
                    record.cancellation.wait_for_cleanup()
                if (
                    isinstance(body_error, V2RunError)
                    and body_error.code == "evidence_unavailable"
                ):
                    raise body_error
                terminal_status = (
                    "failed"
                    if record.cancellation.cleanup_error is not None
                    else "cancelled"
                    if ledger.cancellation_requested
                    else body_error.status
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

            outcome = ledger.commit_node_publication(
                node_id=node.node_id,
                node_attempt_id=node_attempt_id,
                resolution="executed",
                outputs=pending_typed_outputs,
                artifacts=pending_artifacts,
                operation_attempt_id=operation_attempt_id,
                cancel_cleanup=cleanup_cancelled_publication,
            )
            if outcome == "succeeded":
                values.update(pending_runtime)
                all_artifacts.extend(pending_artifacts)
                artifact_records.update(pending_artifact_records)
            disposition_outcomes[node.node_id] = outcome
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
        record.finished.set()
        return receipt

    def start_background(
        self,
        project_id: str,
        *,
        workflow_revision: int,
        compile_id: str,
        client_request_id: str,
        _derived_from: Mapping[str, Any] | None = None,
        _cache_bypass_nodes: frozenset[str] = frozenset(),
    ) -> dict[str, Any]:
        """Admit synchronously, then execute without blocking event delivery."""
        admitted = threading.Event()
        state: dict[str, Any] = {}

        def on_admitted(
            receipt: dict[str, Any],
            record: _RunRecord,
        ) -> None:
            state["receipt"] = json.loads(json.dumps(receipt))
            state["record"] = record
            admitted.set()

        def execute() -> None:
            try:
                def acquire_execution_slot() -> None:
                    self._execution_lock.acquire()
                    state["execution_slot_acquired"] = True

                self.start(
                    project_id,
                    workflow_revision=workflow_revision,
                    compile_id=compile_id,
                    client_request_id=client_request_id,
                    _on_admitted=on_admitted,
                    _before_execute=acquire_execution_slot,
                    _derived_from=_derived_from,
                    _cache_bypass_nodes=_cache_bypass_nodes,
                )
            except BaseException as error:
                state["error"] = error
                record = state.get("record")
                if isinstance(record, _RunRecord):
                    record.execution_error = error
                    record.finished.set()
            finally:
                if state.get("execution_slot_acquired") is True:
                    self._execution_lock.release()
                with self._worker_condition:
                    self._workers.discard(threading.current_thread())
                    self._reserved_projects.discard(project_id)
                    self._worker_condition.notify_all()
                admitted.set()

        worker = threading.Thread(
            target=execute,
            name=f"v2-run-admission-{project_id}",
            daemon=False,
        )
        with self._worker_condition:
            if (
                self._closed
                or len(self._workers) >= MAX_BACKGROUND_RUNS
                or project_id in self._reserved_projects
            ):
                raise V2RunError(
                    "evidence_unavailable",
                    "Run execution admission is temporarily unavailable",
                    details={"last_durable_cursor": run_cursor(0)},
                )
            self._workers.add(worker)
            self._reserved_projects.add(project_id)
        try:
            worker.start()
        except BaseException:
            with self._worker_condition:
                self._workers.discard(worker)
                self._reserved_projects.discard(project_id)
                self._worker_condition.notify_all()
            raise
        admitted.wait()
        error = state.get("error")
        if "receipt" not in state:
            assert isinstance(error, BaseException)
            raise error
        record = state["record"]
        assert isinstance(record, _RunRecord)
        record.finished.wait(FAST_RUN_COMPLETION_GRACE_SECONDS)
        if record.finished.is_set() and record.execution_error is not None:
            raise record.execution_error
        return state["receipt"]

    @staticmethod
    def _forced_node_closure(
        plan: ExecutionPlan,
        selected_node_ids: frozenset[str],
    ) -> frozenset[str]:
        forced = set(selected_node_ids)
        changed = True
        while changed:
            changed = False
            for edge in plan.edges:
                if (
                    edge.source_node_id in forced
                    and edge.target_node_id not in forced
                ):
                    forced.add(edge.target_node_id)
                    changed = True
        return frozenset(forced)

    def start_derived_background(
        self,
        project_id: str,
        *,
        source_run_id: str,
        compile_id: str,
        policy: str,
        node_ids: list[str],
        client_request_id: str,
    ) -> dict[str, Any]:
        """Start a new Run from one immutable terminal source reference."""
        source = self._require_record(project_id, source_run_id)
        source_projection = source.ledger.projection()
        terminal_sequence = source_projection.get("terminal_sequence")
        if terminal_sequence is None:
            raise V2RunError(
                "malformed_request",
                "Start Derived Run requires a terminal source Run",
                details={"field_path": ["source_run_id"]},
            )
        if compile_id != source_projection["compile_id"]:
            raise V2RunError(
                "contract_digest_mismatch",
                "Start Derived Run requires the source compile identity",
                details={
                    "issues": [
                        {
                            "code": "source_compile_identity_mismatch",
                            "severity": "error",
                            "message": (
                                "Derived Run compile_id must equal the "
                                "immutable source Run compile_id"
                            ),
                            "field_path": ["compile_id"],
                        }
                    ]
                },
            )
        current = self._authoring.load(project_id)
        if (
            current["workflow_revision"]
            != source_projection["workflow_revision"]
            or current["workflow_digest"]
            != source_projection["workflow_digest"]
        ):
            raise V2RunError(
                "contract_digest_mismatch",
                "Saved Workflow no longer matches the source Run",
                details={
                    "issues": [
                        {
                            "code": "source_workflow_identity_mismatch",
                            "severity": "error",
                            "message": (
                                "Derived Run requires the exact persisted "
                                "source Workflow revision and digest"
                            ),
                            "field_path": ["source_run_id"],
                        }
                    ]
                },
            )
        compiled = self._authoring.compile(
            project_id,
            workflow_revision=current["workflow_revision"],
            workflow=parse_workflow_document(current["workflow"]),
        )
        if compiled.receipt["compile_id"] != compile_id:
            raise V2RunError(
                "contract_digest_mismatch",
                "Recompiled source Workflow identity does not match",
                details={
                    "issues": [
                        {
                            "code": "source_compile_reconstruction_mismatch",
                            "severity": "error",
                            "message": (
                                "The immutable source compile identity could "
                                "not be reconstructed from the saved Workflow"
                            ),
                            "field_path": ["compile_id"],
                        }
                    ]
                },
            )
        plan = compiled.execution_plan
        plan_node_ids = tuple(node.node_id for node in plan.nodes)
        selected = frozenset(node_ids)
        if (
            not node_ids
            or len(selected) != len(node_ids)
            or not selected <= frozenset(plan_node_ids)
        ):
            raise V2RunError(
                "compile_rejected",
                "Derived Run selection is not a closed Plan selection",
                details={
                    "issues": [
                        {
                            "code": "invalid_derived_node_selection",
                            "severity": "error",
                            "message": (
                                "node_ids must be unique Node Instances in "
                                "the immutable source Execution Plan"
                            ),
                            "field_path": ["node_ids"],
                        }
                    ]
                },
            )
        source_outcomes = {
            disposition["node_id"]: disposition["outcome"]
            for disposition in source_projection["node_dispositions"]
        }
        if policy == "retry_failed" and any(
            source_outcomes.get(node_id) != "failed"
            for node_id in selected
        ):
            raise V2RunError(
                "compile_rejected",
                "retry_failed may select only failed source Nodes",
                details={
                    "issues": [
                        {
                            "code": "retry_requires_failed_source_node",
                            "severity": "error",
                            "message": (
                                "retry_failed node_ids must identify failed "
                                "source Run Node Dispositions"
                            ),
                            "field_path": ["node_ids"],
                        }
                    ]
                },
            )
        forced = (
            selected
            if policy == "retry_failed"
            else self._forced_node_closure(plan, selected)
        )
        selected_in_plan_order = [
            node_id for node_id in plan_node_ids if node_id in selected
        ]
        forced_in_plan_order = [
            node_id for node_id in plan_node_ids if node_id in forced
        ]
        return self.start_background(
            project_id,
            workflow_revision=source_projection["workflow_revision"],
            compile_id=compile_id,
            client_request_id=client_request_id,
            _derived_from={
                "source_run_id": source_run_id,
                "policy": policy,
                "selected_node_ids": selected_in_plan_order,
                "forced_node_ids": forced_in_plan_order,
            },
            _cache_bypass_nodes=forced,
        )

    def cancel(
        self,
        project_id: str,
        run_id: str,
        *,
        after_cursor: str | None,
    ) -> dict[str, Any]:
        """Persist cancellation before signalling active work."""
        record = self._require_record(project_id, run_id)
        decision = record.ledger.request_cancellation(after_cursor)
        if decision["outcome"] in {
            "cancellation_requested",
            "already_requested",
        }:
            record.cancellation.request()
        return {
            "project_id": project_id,
            "run_id": run_id,
            **decision,
        }

    def shutdown(self) -> None:
        """Stop admission and wait until every tracked Run writer is closed."""
        with self._worker_condition:
            self._closed = True
            workers = tuple(self._workers)
        for worker in workers:
            worker.join()

    def projection(self, project_id: str, run_id: str) -> dict[str, Any]:
        record = self._require_record(project_id, run_id)
        return record.ledger.projection()

    def artifact(
        self,
        project_id: str,
        run_id: str,
        artifact_reference: str,
    ) -> tuple[dict[str, Any], bytes]:
        record = self._require_record(project_id, run_id)
        descriptor = next(
            (
                artifact
                for artifact in record.ledger.projection()["artifact_index"]
                if artifact["artifact_reference"] == artifact_reference
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
        stored_parts = ("published", artifact_reference)
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
        return record.ledger.public_events()

    def ledger_cursor(self, project_id: str, run_id: str) -> str:
        return self._require_record(project_id, run_id).ledger.cursor

    def replay_window(
        self,
        project_id: str,
        run_id: str,
        cursor: str | None,
    ) -> tuple[int, str, int, str, tuple[dict[str, Any], ...], bool]:
        return self._require_record(
            project_id,
            run_id,
        ).ledger.replay_window(cursor)

    def wait_for_public_events(
        self,
        project_id: str,
        run_id: str,
        after_sequence: int,
        *,
        timeout_seconds: float = 1.0,
    ) -> tuple[tuple[dict[str, Any], ...], int, bool]:
        return self._require_record(
            project_id,
            run_id,
        ).ledger.wait_for_public_events(
            after_sequence,
            timeout_seconds=timeout_seconds,
        )
