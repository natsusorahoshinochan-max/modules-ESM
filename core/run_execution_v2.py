"""Readiness-gated direct execution and durable public Run projections."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable, Iterator, Mapping
from copy import deepcopy
from contextlib import contextmanager
from dataclasses import dataclass, field, fields, is_dataclass, replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import signal
import stat
import threading
import time
from types import MappingProxyType
from typing import Any, Literal, Protocol, cast
import uuid

from protein_workbench_public import (
    ProtocolValidationError,
    validate_event,
    validate_schema,
)

from core.artifacts import ArtifactPayload, is_valid_artifact_media_type
from core.operation import (
    InputContentDigests,
    OperationCall,
    OperationContext,
)
from core.port_types import (
    ContractResolutionError,
    FrozenCatalog,
    PortValueError,
    canonical_json_bytes,
    canonical_sha256,
)
from core.process_control import signal_process_group
from core.project import ProjectInputIntegrityError, ProjectManager
from core.project_objects import ObjectIntegrityError, ProjectObjectStore
from core.public_values import sanitize_public_value
from core.scoring_v2 import (
    SelectionError,
    resolve_structure_alignment_evidence_admission_facts,
    selection_objective_provenance_from_facts,
    validate_produced_score_collection_from_facts,
)
from core.storage import (
    StoragePathError,
    open_private_regular_file,
    remove_private_regular_file,
    replace_private_regular_file,
    validate_identifier,
    validate_relative_path,
    write_private_new_file,
)
from core.value_admission import (
    AdmittedPortValues,
    admitted_port_values,
    admitted_port_values_from_bytes,
    normalize_scientific_outputs,
    validate_candidate_input_identities,
)
from core.workflow_authoring_v2 import WorkflowAuthoringService
from core.workflow_v2 import (
    CONTRACT_LOCK_NAMESPACE,
    CompiledWorkflow,
    ExecutionPlan,
    ExecutionPlanNode,
)
from datatypes import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
    PairwiseCandidateMapping,
    PairwiseObservationContext,
    ProteinSequence,
    ProteinStructure,
    ScoreCollection,
    ScoreObservation,
    ExactContractReference,
    validate_canonical_identifier,
)
from datatypes.protein import residue_identity_chain


READINESS_ATTESTATION_NAMESPACE = (
    "protein-workbench-readiness-attestation/v2"
)
RESULT_IDENTITY_NAMESPACE = "protein-workbench-cache/v3"
RESULT_CACHE_ENTRY_NAMESPACE = "protein-workbench-cache-entry/v3"
PORT_VALUE_MANIFEST_NAMESPACE = (
    "protein-workbench-port-value-manifest/v1"
)
RUN_LEDGER_TRANSACTION_NAMESPACE = (
    "protein-workbench-run-ledger-transaction/v4"
)
RUN_LEDGER_SCHEMA_VERSION = "4.0.0"
MAX_ARTIFACTS_PER_RUN = 2_048
MAX_ARTIFACT_SIZE_BYTES = 64 * 1024 * 1024
MAX_ARTIFACT_BYTES_PER_RUN = 256 * 1024 * 1024
MAX_LEDGER_TRANSACTION_BYTES = 4 * 1024 * 1024
MAX_PORT_VALUE_MANIFEST_BYTES = 32 * 1024 * 1024
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


def _freeze_invocation_provenance(
    value: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Validate closed orthogonal provenance facts and freeze caller containers."""
    try:
        validate_schema("#/$defs/InvocationProvenance", value)
    except ProtocolValidationError as error:
        raise ValueError("Engine invocation provenance is malformed") from error

    frozen: dict[str, Any] = {}
    randomness = value.get("effective_randomness")
    if randomness is not None:
        frozen_randomness = {"control": randomness["control"]}
        if randomness["control"] == "exact_seed":
            frozen_randomness["effective_seed"] = randomness[
                "effective_seed"
            ]
        frozen["effective_randomness"] = MappingProxyType(
            frozen_randomness
        )

    project_input_filename = value.get("project_input_filename")
    if project_input_filename is not None:
        frozen["project_input_filename"] = project_input_filename

    projection = value.get("provider_residue_projection")
    if projection is None:
        return MappingProxyType(frozen)

    workbench_chain_order = tuple(projection["workbench_chain_order"])
    provider_structure_chain_order = tuple(
        projection["provider_structure_chain_order"]
    )
    provider_chain_order = tuple(projection["provider_chain_order"])
    if (
        len(set(workbench_chain_order)) != len(workbench_chain_order)
        or len(set(provider_structure_chain_order))
        != len(provider_structure_chain_order)
        or len(set(provider_chain_order)) != len(provider_chain_order)
        or set(provider_structure_chain_order) != set(provider_chain_order)
    ):
        raise ValueError("Engine invocation provenance chain order is malformed")

    frozen_entries: list[Mapping[str, Any]] = []
    residue_ids: set[str] = set()
    workbench_entry_chains: set[str] = set()
    provider_entry_chains: set[str] = set()
    provider_positions: set[tuple[str, int]] = set()
    workbench_segment_order: list[str] = []
    current_segment_index = -1
    current_provider_position = 0
    for entry in projection["entries"]:
        residue_id = entry["residue_id"]
        segment_index = entry["segment_index"]
        provider_chain_id = entry["provider_chain_id"]
        provider_position = entry["provider_position"]
        provider_coordinate = (provider_chain_id, provider_position)
        try:
            workbench_chain_id = residue_identity_chain(
                residue_id,
                subject="provider projection residue identity",
            )
        except ValueError as error:
            raise ValueError(
                "Engine invocation provenance entries are malformed"
            ) from error
        if (
            workbench_chain_id not in workbench_chain_order
            or provider_chain_id not in provider_chain_order
            or segment_index < current_segment_index
            or segment_index > current_segment_index + 1
            or segment_index >= len(provider_structure_chain_order)
            or provider_chain_id
            != provider_structure_chain_order[segment_index]
            or residue_id in residue_ids
            or provider_coordinate in provider_positions
        ):
            raise ValueError(
                "Engine invocation provenance entries are malformed"
            )
        if segment_index != current_segment_index:
            if provider_position != 1:
                raise ValueError(
                    "Engine invocation provenance entries are malformed"
                )
            current_segment_index = segment_index
            current_provider_position = 1
            workbench_segment_order.append(workbench_chain_id)
        else:
            if (
                provider_position != current_provider_position + 1
                or workbench_segment_order[-1] != workbench_chain_id
            ):
                raise ValueError(
                    "Engine invocation provenance entries are malformed"
                )
            current_provider_position = provider_position
        residue_ids.add(residue_id)
        workbench_entry_chains.add(workbench_chain_id)
        provider_entry_chains.add(provider_chain_id)
        provider_positions.add(provider_coordinate)
        frozen_entries.append(
            MappingProxyType(
                {
                    "residue_id": residue_id,
                    "segment_index": segment_index,
                    "provider_chain_id": provider_chain_id,
                    "provider_position": provider_position,
                }
            )
        )
    if (
        workbench_entry_chains != set(workbench_chain_order)
        or provider_entry_chains != set(provider_structure_chain_order)
        or current_segment_index
        != len(provider_structure_chain_order) - 1
        or tuple(
            chain
            for index, chain in enumerate(workbench_segment_order)
            if index == 0 or chain != workbench_segment_order[index - 1]
        ) != workbench_chain_order
    ):
        raise ValueError("Engine invocation provenance entries are malformed")

    frozen["provider_residue_projection"] = MappingProxyType(
        {
            "position_semantics": "one_based_chain_local",
            "workbench_chain_order": workbench_chain_order,
            "provider_structure_chain_order": (
                provider_structure_chain_order
            ),
            "provider_chain_order": provider_chain_order,
            "entries": tuple(frozen_entries),
        }
    )
    return MappingProxyType(frozen)


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
    if isinstance(error, V2RunError):
        return {
            "code": error.code,
            "message": str(error),
            "retryable": False,
            "correlation_id": f"incident-{uuid.uuid4().hex}",
            "details": sanitize_public_value(error.details),
        }
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


def _public_selection_failure(error: BaseException) -> dict[str, Any]:
    error_type = type(error).__name__
    if (
        len(error_type) > 128
        or _PUBLIC_IDENTIFIER.fullmatch(error_type) is None
    ):
        error_type = "Exception"
    details = (
        {"reason": str(error)}
        if isinstance(error, SelectionError)
        else {"exception_type": error_type}
    )
    return {
        "code": "selection_failed",
        "message": "Workflow selection failed safely",
        "retryable": False,
        "correlation_id": f"incident-{uuid.uuid4().hex}",
        "details": sanitize_public_value(details),
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
        "selection_terminal",
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


@dataclass(frozen=True, slots=True)
class ReadinessCheckInput:
    """Closed private checker input for one selected Binding."""

    values: Mapping[str, Any]
    reusable_proof: ReusableReadinessProof | None

    def __post_init__(self) -> None:
        if not isinstance(self.values, Mapping):
            raise TypeError("Readiness values must be a Mapping")
        object.__setattr__(
            self,
            "values",
            MappingProxyType(dict(self.values)),
        )


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
    """Project/Run-contained resources available to one Scientific Operation."""

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
    _project_inputs: Mapping[
        str,
        tuple[Mapping[str, Any], bytes],
    ] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )
    _project_input_identities: tuple[Mapping[str, Any], ...] = field(
        default=(),
        repr=False,
        compare=False,
    )

    def read_project_input(
        self,
        input_reference: str,
    ) -> tuple[Mapping[str, Any], bytes]:
        """Read one trusted input from this Run's exact Project scope."""
        try:
            descriptor, payload = self._project_inputs[input_reference]
        except KeyError as error:
            raise RuntimeError(
                "Project input access was not declared by the Node contract"
            ) from error
        return dict(descriptor), payload

    @property
    def result_identity_inputs(self) -> tuple[Mapping[str, Any], ...]:
        """Return path-free immutable resource identities observed by this Node."""
        return tuple(dict(identity) for identity in self._project_input_identities)

    def temporary_directory(self, *, prefix: str):
        """Delegate to the hardened private workspace primitive."""
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
        parent_invocation_id: str | None = None,
        invocation_provenance: Mapping[str, Any] | None = None,
    ):
        """Record one explicit crossing of a scientific engine boundary."""
        if self._invocation_recorder is None:
            raise RuntimeError("Engine Invocation is unavailable")
        frozen_provenance = (
            None
            if invocation_provenance is None
            else _freeze_invocation_provenance(invocation_provenance)
        )
        with self._invocation_recorder.invoke(
            engine_role=engine_role,
            parent_invocation_id=parent_invocation_id,
            invocation_provenance=frozen_provenance,
        ) as invocation_id:
            yield invocation_id


class ResultReplaySource:
    """Optional typed Result replay boundary."""

    def lookup(
        self,
        *,
        project_id: str,
        execution_plan: ExecutionPlan,
        node: ExecutionPlanNode,
        inputs: Mapping[str, Any],
        result_identity: str,
    ) -> ResultReplayHit | None:
        del project_id, execution_plan, node, inputs, result_identity
        return None

    def publish(
        self,
        *,
        project_id: str,
        execution_plan: ExecutionPlan,
        node: ExecutionPlanNode,
        result_identity: str,
        outputs: list[dict[str, Any]],
        producer_run_id: str,
        admitted_outputs: Mapping[
            tuple[str, str],
            AdmittedPortValues,
        ],
    ) -> Callable[[], None] | None:
        del (
            project_id,
            execution_plan,
            node,
            result_identity,
            outputs,
            producer_run_id,
            admitted_outputs,
        )
        return None

    def validate_publish(
        self,
        *,
        project_id: str,
        execution_plan: ExecutionPlan,
        node: ExecutionPlanNode,
        result_identity: str,
        outputs: list[dict[str, Any]],
        producer_run_id: str,
        admitted_outputs: Mapping[
            tuple[str, str],
            AdmittedPortValues,
        ],
    ) -> None:
        del (
            project_id,
            execution_plan,
            node,
            result_identity,
            outputs,
            producer_run_id,
            admitted_outputs,
        )


class RecoverableCacheMiss(RuntimeError):
    """Recognizable absent or corrupt raw cache storage safe to recompute."""


@dataclass(frozen=True, slots=True)
class ResultReplayHit:
    """One identity-bound canonical replay with durable producer provenance."""

    result_identity: str
    producer_run_id: str
    admitted_outputs: Mapping[
        tuple[str, str],
        AdmittedPortValues,
    ]

    def __post_init__(self) -> None:
        if not isinstance(self.admitted_outputs, Mapping) or any(
            not isinstance(key, tuple)
            or len(key) != 2
            or not all(isinstance(part, str) for part in key)
            or not isinstance(snapshot, AdmittedPortValues)
            for key, snapshot in self.admitted_outputs.items()
        ):
            raise TypeError(
                "Result replay admitted_outputs must contain canonical "
                "AdmittedPortValues snapshots"
            )
        object.__setattr__(
            self,
            "admitted_outputs",
            MappingProxyType(dict(self.admitted_outputs)),
        )


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
class ExecutedNodeSuccess:
    """One admitted executed result ready for Node finalization."""

    project_id: str
    run_id: str
    execution_plan: ExecutionPlan
    node: ExecutionPlanNode
    resources: RunResources
    node_attempt_id: str
    operation_attempt_id: str
    result_identity: str
    admitted_output_descriptors: tuple[Mapping[str, Any], ...]
    admitted_outputs: Mapping[tuple[str, str], AdmittedPortValues]
    cache_eligible: bool
    current_artifact_count: int
    current_artifact_bytes: int


@dataclass(frozen=True, slots=True)
class ExecutedNodeNonSuccess:
    """One executed or inspected Node Attempt that did not succeed."""

    node_id: str
    node_attempt_id: str
    operation_attempt_id: str | None
    status: Literal["failed"]
    public_error: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class CacheReplayNodeSuccess:
    """One identity-bound Cache replay ready for Node finalization."""

    project_id: str
    run_id: str
    execution_plan: ExecutionPlan
    node: ExecutionPlanNode
    resources: RunResources
    node_attempt_id: str
    result_identity: str
    producer_run_id: str
    admitted_output_descriptors: tuple[Mapping[str, Any], ...]
    admitted_outputs: Mapping[tuple[str, str], AdmittedPortValues]
    current_artifact_count: int
    current_artifact_bytes: int


@dataclass(frozen=True, slots=True)
class CancelledOrInterruptedNode:
    """One cancellation or interruption conclusion at its exact causal depth."""

    node_id: str
    status: Literal["cancelled", "interrupted", "outcome_unknown"]
    public_error: Mapping[str, Any] | None
    node_attempt_id: str | None = None
    operation_attempt_id: str | None = None
    resolution: Literal["executed", "cache_replayed"] = "executed"


@dataclass(frozen=True, slots=True)
class BlockedNode:
    """One unstarted Node blocked by concluded required dependencies."""

    node_id: str
    blocked_by: tuple[str, ...]


NodeFinalizationIntent = (
    ExecutedNodeSuccess
    | ExecutedNodeNonSuccess
    | CacheReplayNodeSuccess
    | CancelledOrInterruptedNode
)

@dataclass(frozen=True, slots=True)
class _NodeCompletionContext:
    node_id: str
    node_attempt_id: str
    operation_attempt_id: str | None
    resolution: Literal["executed", "cache_replayed"]
    resources: RunResources


@dataclass(frozen=True, slots=True)
class FinalizedNode:
    """The committed disposition and success materialization for one Node."""

    disposition: Literal[
        "succeeded",
        "failed",
        "cancelled",
        "interrupted",
        "blocked",
    ]
    admitted_outputs: Mapping[
        tuple[str, str],
        AdmittedPortValues,
    ] = field(default_factory=dict)
    artifacts: tuple[Mapping[str, Any], ...] = ()


class _ArtifactMaterializer(Protocol):
    def __call__(
        self,
        *,
        node: ExecutionPlanNode,
        resources: RunResources,
        admitted_output_descriptors: list[dict[str, Any]],
        runtime: Mapping[tuple[str, str], AdmittedPortValues],
        current_artifact_count: int,
        current_artifact_bytes: int,
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]: ...


@dataclass(frozen=True, slots=True)
class _PlanNodeEvidence:
    node_id: str
    dependencies: tuple[str, ...]
    required_dependencies: tuple[str, ...]
    result_identity_plan_facts_digest: str
    node_type: Mapping[str, Any] | None = None
    artifact_outputs: tuple[Mapping[str, Any], ...] = ()
    selection_consumer: bool = False

    def to_dict(self) -> dict[str, Any]:
        result = {
            "node_id": self.node_id,
            "dependencies": list(self.dependencies),
            "required_dependencies": list(self.required_dependencies),
            "result_identity_plan_facts_digest": (
                self.result_identity_plan_facts_digest
            ),
        }
        if self.node_type is not None:
            result["node_type"] = dict(self.node_type)
        if self.artifact_outputs:
            result["artifact_outputs"] = [
                {
                    **dict(output),
                    "port_type": dict(output["port_type"]),
                    "accepted_media_types": list(
                        output["accepted_media_types"]
                    ),
                }
                for output in self.artifact_outputs
            ]
        if self.selection_consumer:
            result["selection_consumer"] = True
        return result


def _parse_plan_evidence(
    value: Any,
) -> tuple[_PlanNodeEvidence, ...]:
    if not isinstance(value, list):
        raise ValueError("Run plan evidence is invalid")
    parsed: list[_PlanNodeEvidence] = []
    seen: set[str] = set()
    for item in value:
        allowed_fields = {
            "node_id",
            "dependencies",
            "required_dependencies",
            "result_identity_plan_facts_digest",
        }
        if (
            not isinstance(item, Mapping)
            or not allowed_fields <= set(item)
            or set(item) - allowed_fields
            - {"node_type", "artifact_outputs", "selection_consumer"}
            or not isinstance(item["node_id"], str)
            or not isinstance(item["dependencies"], list)
            or not isinstance(item["required_dependencies"], list)
            or not isinstance(
                item["result_identity_plan_facts_digest"],
                str,
            )
            or re.fullmatch(
                r"sha256:[0-9a-f]{64}",
                item["result_identity_plan_facts_digest"],
            )
            is None
            or type(item.get("selection_consumer", False)) is not bool
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
        node_type = item.get("node_type")
        if node_type is not None:
            try:
                validate_schema("#/$defs/ContractReference", node_type)
            except ProtocolValidationError as error:
                raise ValueError("Run plan evidence is invalid") from error
            if node_type["contract_kind"] != "node_type":
                raise ValueError("Run plan evidence is invalid")
            node_type = dict(node_type)
        raw_artifact_outputs = item.get("artifact_outputs", [])
        if not isinstance(raw_artifact_outputs, list):
            raise ValueError("Run plan evidence is invalid")
        artifact_outputs: list[Mapping[str, Any]] = []
        artifact_output_names: set[str] = set()
        for artifact_output in raw_artifact_outputs:
            if (
                not isinstance(artifact_output, Mapping)
                or set(artifact_output)
                != {
                    "output_port",
                    "artifact_kind",
                    "artifact_media_type",
                    "port_type",
                    "accepted_media_types",
                }
                or artifact_output["artifact_kind"]
                not in {"candidate", "standalone"}
                or (
                    artifact_output["artifact_media_type"] is not None
                    and not is_valid_artifact_media_type(
                        artifact_output["artifact_media_type"]
                    )
                )
                or not isinstance(
                    artifact_output["accepted_media_types"],
                    list,
                )
            ):
                raise ValueError("Run plan evidence is invalid")
            output_port = validate_identifier(
                artifact_output["output_port"],
                "output_port",
            )
            media_types = tuple(
                artifact_output["accepted_media_types"]
            )
            if (
                output_port in artifact_output_names
                or not media_types
                or tuple(sorted(set(media_types))) != media_types
                or any(
                    not is_valid_artifact_media_type(media_type)
                    for media_type in media_types
                )
                or (
                    artifact_output["artifact_media_type"] is not None
                    and artifact_output["artifact_media_type"]
                    not in media_types
                )
            ):
                raise ValueError("Run plan evidence is invalid")
            try:
                validate_schema(
                    "#/$defs/ContractReference",
                    artifact_output["port_type"],
                )
            except ProtocolValidationError as error:
                raise ValueError("Run plan evidence is invalid") from error
            if artifact_output["port_type"]["contract_kind"] != "port_type":
                raise ValueError("Run plan evidence is invalid")
            artifact_output_names.add(output_port)
            artifact_outputs.append(
                {
                    "output_port": output_port,
                    "artifact_kind": artifact_output["artifact_kind"],
                    "artifact_media_type": artifact_output[
                        "artifact_media_type"
                    ],
                    "port_type": dict(artifact_output["port_type"]),
                    "accepted_media_types": media_types,
                }
            )
        seen.add(node_id)
        parsed.append(
            _PlanNodeEvidence(
                node_id,
                dependencies,
                required,
                item["result_identity_plan_facts_digest"],
                node_type,
                tuple(artifact_outputs),
                item.get("selection_consumer", False),
            )
        )
    if any(
        dependency not in seen
        for node in parsed
        for dependency in node.dependencies
    ):
        raise ValueError("Run plan evidence is invalid")
    return tuple(parsed)


@dataclass(frozen=True, slots=True)
class ProposedFact:
    """One typed logical fact proposed for a Ledger transaction."""

    fact_type: str
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class CommittedFactRange:
    """The acknowledged contiguous logical facts from one commit."""

    first_sequence: int
    last_sequence: int
    facts: tuple[Mapping[str, Any], ...]


class LedgerTransactionStore(Protocol):
    """Publish one already-canonical physical Ledger transaction."""

    def publish(
        self,
        *,
        root: Path,
        relative_parts: tuple[str, ...],
        payload: bytes,
    ) -> None: ...


class FilesystemLedgerTransactionStore:
    """Production owner-only atomic filesystem transaction publisher."""

    def publish(
        self,
        *,
        root: Path,
        relative_parts: tuple[str, ...],
        payload: bytes,
    ) -> None:
        write_private_new_file(
            root,
            relative_parts,
            payload,
            field="run_ledger",
        )


@dataclass(slots=True)
class _LedgerReducerState:
    facts: list[dict[str, Any]]
    node_attempts: dict[str, dict[str, Any]]
    node_attempt_by_node: dict[str, str]
    operations: dict[str, dict[str, Any]]
    invocations: dict[str, dict[str, Any]]
    dispositions: dict[str, dict[str, Any]]
    outputs_published: set[str]
    run_admitted: bool
    run_started: bool
    selection_required: bool
    expected_selection_terminal_keys: tuple[str, ...]
    selection_terminals: list[dict[str, Any]]
    selection_terminal_keys: set[str]
    run_terminal: bool
    cancellation_sequence: int | None
    restart_reconciled: bool

    def clone(self) -> _LedgerReducerState:
        """Stage from immutable retained facts and copied reducer indexes."""
        return _LedgerReducerState(
            facts=list(self.facts),
            node_attempts=deepcopy(self.node_attempts),
            node_attempt_by_node=dict(self.node_attempt_by_node),
            operations=deepcopy(self.operations),
            invocations=deepcopy(self.invocations),
            dispositions=deepcopy(self.dispositions),
            outputs_published=set(self.outputs_published),
            run_admitted=self.run_admitted,
            run_started=self.run_started,
            selection_required=self.selection_required,
            expected_selection_terminal_keys=(
                self.expected_selection_terminal_keys
            ),
            selection_terminals=deepcopy(self.selection_terminals),
            selection_terminal_keys=set(self.selection_terminal_keys),
            run_terminal=self.run_terminal,
            cancellation_sequence=self.cancellation_sequence,
            restart_reconciled=self.restart_reconciled,
        )


class _RunEvidenceLedger:
    """Schema-checked, causally closed owner-only facts for one Run."""

    def __init__(
        self,
        projects: ProjectManager,
        project_id: str,
        run_id: str,
        plan_nodes: tuple[_PlanNodeEvidence, ...],
        transaction_store: LedgerTransactionStore | None = None,
    ) -> None:
        self._projects = projects
        run_dir = projects.run_dir(project_id, run_id)
        self._root = run_dir.parent
        self._project_id = project_id
        self._run_id = run_id
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
        self._result_identity_plan_facts_digests = {
            node.node_id: node.result_identity_plan_facts_digest
            for node in plan_nodes
        }
        self._node_types = {
            node.node_id: (
                dict(node.node_type)
                if node.node_type is not None
                else None
            )
            for node in plan_nodes
        }
        self._artifact_outputs = {
            node.node_id: tuple(
                {
                    **dict(output),
                    "port_type": dict(output["port_type"]),
                    "accepted_media_types": tuple(
                        output["accepted_media_types"]
                    ),
                }
                for output in node.artifact_outputs
            )
            for node in plan_nodes
        }
        self._selection_consumer_ids = tuple(
            node.node_id for node in plan_nodes if node.selection_consumer
        )
        self._state = _LedgerReducerState(
            facts=[],
            node_attempts={},
            node_attempt_by_node={},
            operations={},
            invocations={},
            dispositions={},
            outputs_published=set(),
            run_admitted=False,
            run_started=False,
            selection_required=False,
            expected_selection_terminal_keys=(),
            selection_terminals=[],
            selection_terminal_keys=set(),
            run_terminal=False,
            cancellation_sequence=None,
            restart_reconciled=False,
        )
        self._transaction_count = 0
        self._committed_fact_count = 0
        self._transaction_store = (
            transaction_store or FilesystemLedgerTransactionStore()
        )
        self._condition = threading.Condition(threading.RLock())
        self._projection_error: BaseException | None = None

    def _capture_reducer_state(self) -> _LedgerReducerState:
        return self._state.clone()

    def _install_reducer_state(self, state: _LedgerReducerState) -> None:
        self._state = state

    @property
    def facts(self) -> tuple[dict[str, Any], ...]:
        with self._condition:
            return tuple(json.loads(json.dumps(fact)) for fact in self._state.facts)

    @property
    def cursor(self) -> str:
        with self._condition:
            return self._cursor_at(self._committed_fact_count)

    @property
    def terminal(self) -> bool:
        with self._condition:
            return self._state.run_terminal

    @property
    def started(self) -> bool:
        with self._condition:
            return self._state.run_started

    @property
    def cancellation_requested(self) -> bool:
        with self._condition:
            return self._state.cancellation_sequence is not None

    @property
    def plan_nodes(self) -> tuple[_PlanNodeEvidence, ...]:
        return tuple(
            _PlanNodeEvidence(
                node_id,
                tuple(sorted(self._dependencies[node_id])),
                tuple(sorted(self._required_dependencies[node_id])),
                self._result_identity_plan_facts_digests[node_id],
                self._node_types[node_id],
                self._artifact_outputs[node_id],
                node_id in self._selection_consumer_ids,
            )
            for node_id in self._plan_node_order
        )

    def _cursor_at(self, sequence: int) -> str:
        fact = self._state.facts[sequence - 1] if sequence else None
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
                if sequence <= len(self._state.facts)
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
            if sequence < 0 or sequence > len(self._state.facts):
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
        if self._state.run_terminal:
            raise self._causal_error()
        if fact_type == "run_scope_bound":
            try:
                workflow_commit_id = validate_identifier(
                    payload["workflow_commit_id"],
                    "workflow_commit_id",
                )
            except StoragePathError as error:
                raise self._causal_error() from error
            if (
                self._state.facts
                or payload["project_id"] != self._project_id
                or payload["run_id"] != self._run_id
                or workflow_commit_id != payload["workflow_commit_id"]
                or type(payload["workflow_commit_revision"]) is not int
                or payload["workflow_commit_revision"] < 1
            ):
                raise self._causal_error()
            return
        if (
            not self._state.facts
            or self._state.facts[0]["fact_type"] != "run_scope_bound"
        ):
            raise self._causal_error()
        if fact_type in {"availability_bound", "readiness_attested"}:
            if self._state.run_admitted:
                raise self._causal_error()
            return
        if fact_type == "run_admitted":
            scope = self._state.facts[0]["payload"]
            if (
                self._state.run_admitted
                or self._state.run_started
                or payload["workflow_commit_id"]
                != scope["workflow_commit_id"]
                or payload["workflow_commit_revision"]
                != scope["workflow_commit_revision"]
            ):
                raise self._causal_error()
            return
        if fact_type == "run_started":
            if not self._state.run_admitted or self._state.run_started:
                raise self._causal_error()
            return
        if fact_type == "cancellation_requested":
            if (
                not self._state.run_started
                or self._state.cancellation_sequence is not None
            ):
                raise self._causal_error()
            return
        if fact_type == "restart_reconciliation_started":
            if (
                not self._state.run_started
                or self._state.run_terminal
                or self._state.restart_reconciled
            ):
                raise self._causal_error()
            return
        if fact_type == "node_attempt_started":
            node_id = payload["node_id"]
            attempt_id = payload["node_attempt_id"]
            if (
                not self._state.run_started
                or node_id not in self._plan_nodes
                or node_id in self._state.node_attempt_by_node
                or node_id in self._state.dispositions
                or attempt_id in self._state.node_attempts
                or any(
                    upstream not in self._state.dispositions
                    for upstream in self._dependencies[node_id]
                )
            ):
                raise self._causal_error()
            return
        if fact_type == "operation_attempt_started":
            attempt_id = payload["node_attempt_id"]
            operation_id = payload["operation_attempt_id"]
            attempt = self._state.node_attempts.get(attempt_id)
            if (
                attempt is None
                or attempt["terminal"] is not None
                or operation_id in self._state.operations
                or any(
                    operation["node_attempt_id"] == attempt_id
                    for operation in self._state.operations.values()
                )
            ):
                raise self._causal_error()
            return
        if fact_type == "engine_invocation_started":
            operation_id = payload["operation_attempt_id"]
            invocation_id = payload["invocation_id"]
            parent_invocation_id = payload.get("parent_invocation_id")
            operation = self._state.operations.get(operation_id)
            parent = (
                self._state.invocations.get(parent_invocation_id)
                if parent_invocation_id is not None
                else None
            )
            if (
                operation is None
                or operation["terminal"] is not None
                or invocation_id in self._state.invocations
                or (
                    parent_invocation_id is not None
                    and (
                        parent is None
                        or parent["operation_attempt_id"] != operation_id
                        or parent["terminal"] != "succeeded"
                    )
                )
            ):
                raise self._causal_error()
            return
        if fact_type == "engine_invocation_terminal":
            invocation = self._state.invocations.get(payload["invocation_id"])
            if invocation is None or invocation["terminal"] is not None:
                raise self._causal_error()
            return
        if fact_type == "operation_attempt_terminal":
            operation_id = payload["operation_attempt_id"]
            operation = self._state.operations.get(operation_id)
            if (
                operation is None
                or operation["terminal"] is not None
                or any(
                    invocation["operation_attempt_id"] == operation_id
                    and invocation["terminal"] is None
                    for invocation in self._state.invocations.values()
                )
                or (
                    payload["status"] == "succeeded"
                    and any(
                        invocation["operation_attempt_id"] == operation_id
                        and invocation["terminal"] != "succeeded"
                        for invocation in self._state.invocations.values()
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
            attempt_id = self._state.node_attempt_by_node.get(node_id)
            attempt = (
                self._state.node_attempts.get(attempt_id)
                if attempt_id is not None
                else None
            )
            if (
                attempt is None
                or attempt["terminal"] is not None
                or node_id in self._state.dispositions
                or (
                    fact_type == "outputs_published"
                    and node_id in self._state.outputs_published
                )
            ):
                raise self._causal_error()
            child_operations = [
                operation_id
                for operation_id, operation in self._state.operations.items()
                if operation["node_attempt_id"] == attempt_id
            ]
            if child_operations:
                if fact_type == "outputs_published" and any(
                    self._state.operations[operation_id]["terminal"] != "succeeded"
                    for operation_id in child_operations
                ):
                    raise self._causal_error()
                if fact_type == "artifact_published" and any(
                    invocation["operation_attempt_id"] in child_operations
                    and invocation["terminal"] != "succeeded"
                    for invocation in self._state.invocations.values()
                ):
                    raise self._causal_error()
            return
        if fact_type == "node_attempt_terminal":
            attempt_id = payload["node_attempt_id"]
            attempt = self._state.node_attempts.get(attempt_id)
            child_operations = [
                operation
                for operation in self._state.operations.values()
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
                            payload["status"] == "succeeded"
                            and attempt["node_id"]
                            not in self._state.outputs_published
                        )
                        or (
                            payload["status"] == "cancelled"
                            and self._state.cancellation_sequence is None
                        )
                        or (
                            payload["status"] == "failed"
                            and attempt["node_id"]
                            in self._state.outputs_published
                        )
                        or (
                            payload["status"]
                            in {"interrupted", "outcome_unknown"}
                            and not self._state.restart_reconciled
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
                        self._state.restart_reconciled
                        and payload["status"]
                        in {"interrupted", "outcome_unknown"}
                    )
                    and not (
                        self._state.cancellation_sequence is not None
                        and payload["status"] == "cancelled"
                    )
                )
            ):
                raise self._causal_error()
            return
        if fact_type == "node_disposition":
            node_id = payload["node_id"]
            outcome = payload["outcome"]
            if node_id not in self._plan_nodes or node_id in self._state.dispositions:
                raise self._causal_error()
            attempt_id = self._state.node_attempt_by_node.get(node_id)
            attempt = (
                self._state.node_attempts.get(attempt_id)
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
                        upstream not in self._state.dispositions
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
        if fact_type == "selection_terminal":
            result = payload.get("result")
            selection_key = (
                result.get("selection_node_id")
                if isinstance(result, Mapping)
                else "__failed__"
            )
            if (
                not self._state.run_started
                or not self._state.selection_required
                or set(self._state.dispositions) != set(self._plan_nodes)
                or any(
                    disposition["outcome"] != "succeeded"
                    for disposition in self._state.dispositions.values()
                )
                or not isinstance(selection_key, str)
                or (
                    payload["status"] == "succeeded"
                    and (
                        selection_key
                        not in self._state.expected_selection_terminal_keys
                        or selection_key in self._state.selection_terminal_keys
                    )
                )
                or (
                    payload["status"] == "failed"
                    and self._state.selection_terminals
                )
                or (
                    payload["status"] == "succeeded"
                    and any(
                        terminal["status"] == "failed"
                        for terminal in self._state.selection_terminals
                    )
                )
            ):
                raise self._causal_error()
            return
        if fact_type == "run_terminal":
            outcomes = {
                disposition["outcome"]
                for disposition in self._state.dispositions.values()
            }
            expected_status = (
                "interrupted"
                if self._state.restart_reconciled
                else "failed"
                if "failed" in outcomes
                else "interrupted"
                if "interrupted" in outcomes
                else "cancelled"
                if "cancelled" in outcomes
                else "failed"
                if any(
                    terminal["status"] == "failed"
                    for terminal in self._state.selection_terminals
                )
                else "succeeded"
            )
            if (
                not self._state.run_started
                or set(self._state.dispositions) != set(self._plan_nodes)
                or any(
                    attempt["terminal"] is None
                    for attempt in self._state.node_attempts.values()
                )
                or any(
                    operation["terminal"] is None
                    for operation in self._state.operations.values()
                )
                or any(
                    invocation["terminal"] is None
                    for invocation in self._state.invocations.values()
                )
                or (
                    self._state.selection_required
                    and not self._state.restart_reconciled
                    and not outcomes.intersection(
                        {"failed", "interrupted", "cancelled"}
                    )
                    and payload["status"] == "succeeded"
                    and (
                        self._state.selection_terminal_keys
                        != set(self._state.expected_selection_terminal_keys)
                    )
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
                        "workflow_commit_id",
                        "workflow_commit_revision",
                        "workflow_digest",
                        "contract_lock_digest",
                        "execution_plan_digest",
                        "catalog_contract_digest",
                        "resolved_contracts",
                        "plan_nodes",
                        "selection_required",
                        "selection_terminal_keys",
                    }
                ),
                frozenset({"derived_from", "resolved_contract_roots"}),
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
                frozenset(
                    {"workflow_commit_id", "workflow_commit_revision"}
                ),
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
                frozenset(
                    {"parent_invocation_id", "invocation_provenance"}
                ),
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
            "selection_terminal": (
                frozenset({"status"}),
                frozenset({"result", "error"}),
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
            fact_type == "engine_invocation_started"
            and "invocation_provenance" in payload
        ):
            try:
                _freeze_invocation_provenance(
                    payload["invocation_provenance"]
                )
            except (TypeError, ValueError) as error:
                raise V2RunError(
                    "evidence_unavailable",
                    "Required Run evidence failed schema validation",
                    details={"last_durable_cursor": self.cursor},
                ) from error
        if fact_type == "run_scope_bound":
            plan_nodes = payload["plan_nodes"]
            def valid_plan_node(item: Any) -> bool:
                node_id = (
                    item.get("node_id")
                    if isinstance(item, Mapping)
                    else None
                )
                expected_node_type = self._node_types.get(node_id)
                expected_artifact_outputs = [
                    {
                        **dict(output),
                        "port_type": dict(output["port_type"]),
                        "accepted_media_types": list(
                            output["accepted_media_types"]
                        ),
                    }
                    for output in self._artifact_outputs.get(node_id, ())
                ]
                expected_fields = {
                    "node_id",
                    "dependencies",
                    "required_dependencies",
                    "result_identity_plan_facts_digest",
                }
                if expected_node_type is not None:
                    expected_fields.add("node_type")
                if expected_artifact_outputs:
                    expected_fields.add("artifact_outputs")
                if node_id in self._selection_consumer_ids:
                    expected_fields.add("selection_consumer")
                if (
                    not isinstance(item, Mapping)
                    or set(item) != expected_fields
                    or node_id not in self._dependencies
                ):
                    return False
                return (
                    item["dependencies"]
                    == sorted(self._dependencies[node_id])
                    and item["required_dependencies"]
                    == sorted(self._required_dependencies[node_id])
                    and item["result_identity_plan_facts_digest"]
                    == self._result_identity_plan_facts_digests[node_id]
                    and item.get("node_type") == expected_node_type
                    and item.get("artifact_outputs", [])
                    == expected_artifact_outputs
                    and item.get("selection_consumer", False)
                    == (node_id in self._selection_consumer_ids)
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
            selection_required = payload["selection_required"]
            expected_selection_terminal_keys = list(
                self._selection_consumer_ids
                if selection_required
                else ()
            )
            if (
                type(selection_required) is not bool
                or selection_required
                != bool(self._selection_consumer_ids)
                or payload["selection_terminal_keys"]
                != expected_selection_terminal_keys
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
        if fact_type == "outputs_published":
            if (
                not isinstance(payload["outputs"], list)
                or not isinstance(payload["artifacts"], list)
            ):
                raise self._causal_error()
            try:
                for output in payload["outputs"]:
                    validate_schema("#/$defs/TypedOutput", output)
                for artifact in payload["artifacts"]:
                    validate_schema("#/$defs/ArtifactDescriptor", artifact)
            except ProtocolValidationError as error:
                raise self._causal_error() from error
        if fact_type == "selection_terminal":
            status = payload["status"]
            if (
                status not in {"succeeded", "failed"}
                or (status == "succeeded")
                != ("result" in payload and "error" not in payload)
                or (status == "failed")
                != ("error" in payload and "result" not in payload)
            ):
                raise self._causal_error()
            try:
                validate_schema(
                    (
                        "#/$defs/SelectionResult"
                        if status == "succeeded"
                        else "#/$defs/StructuredError"
                    ),
                    payload["result" if status == "succeeded" else "error"],
                )
            except ProtocolValidationError as error:
                raise self._causal_error() from error

    def _apply(self, fact_type: str, payload: Mapping[str, Any]) -> None:
        if fact_type == "run_scope_bound":
            self._state.selection_required = payload["selection_required"]
            self._state.expected_selection_terminal_keys = tuple(
                payload["selection_terminal_keys"]
            )
        elif fact_type == "run_admitted":
            self._state.run_admitted = True
        elif fact_type == "run_started":
            self._state.run_started = True
        elif fact_type == "cancellation_requested":
            self._state.cancellation_sequence = len(self._state.facts)
        elif fact_type == "restart_reconciliation_started":
            self._state.restart_reconciled = True
        elif fact_type == "node_attempt_started":
            record = {
                "node_id": payload["node_id"],
                "terminal": None,
                "resolution": None,
            }
            self._state.node_attempts[payload["node_attempt_id"]] = record
            self._state.node_attempt_by_node[payload["node_id"]] = payload[
                "node_attempt_id"
            ]
        elif fact_type == "operation_attempt_started":
            self._state.operations[payload["operation_attempt_id"]] = {
                "node_attempt_id": payload["node_attempt_id"],
                "terminal": None,
            }
        elif fact_type == "engine_invocation_started":
            self._state.invocations[payload["invocation_id"]] = {
                "operation_attempt_id": payload["operation_attempt_id"],
                "parent_invocation_id": payload.get(
                    "parent_invocation_id"
                ),
                "terminal": None,
            }
        elif fact_type == "engine_invocation_terminal":
            self._state.invocations[payload["invocation_id"]]["terminal"] = payload[
                "status"
            ]
        elif fact_type == "operation_attempt_terminal":
            self._state.operations[payload["operation_attempt_id"]]["terminal"] = (
                payload["status"]
            )
        elif fact_type == "node_attempt_terminal":
            attempt = self._state.node_attempts[payload["node_attempt_id"]]
            attempt["terminal"] = payload["status"]
            attempt["resolution"] = payload["resolution"]
        elif fact_type == "outputs_published":
            self._state.outputs_published.add(payload["node_id"])
        elif fact_type == "node_disposition":
            self._state.dispositions[payload["node_id"]] = dict(payload)
        elif fact_type == "selection_terminal":
            terminal = dict(payload)
            result = terminal.get("result")
            selection_key = (
                result.get("selection_node_id")
                if isinstance(result, Mapping)
                else "__failed__"
            )
            self._state.selection_terminals.append(terminal)
            if terminal["status"] == "succeeded":
                self._state.selection_terminal_keys.add(selection_key)
        elif fact_type == "run_terminal":
            self._state.run_terminal = True

    def _projection(self) -> dict[str, Any]:
        if (
            not self._state.facts
            or self._state.facts[0]["fact_type"] != "run_scope_bound"
        ):
            raise self._causal_error()
        scope = self._state.facts[0]["payload"]
        dispositions: list[dict[str, Any]] = []
        published_by_node: dict[
            str,
            tuple[list[dict[str, Any]], list[dict[str, Any]]],
        ] = {}
        status = "admitted"
        selection_results: list[dict[str, Any]] = []
        selection_error: dict[str, Any] | None = None
        terminal_sequence: int | None = None
        for fact in self._state.facts:
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
            elif (
                fact["fact_type"] == "selection_terminal"
                and payload["status"] == "succeeded"
            ):
                selection_results.append(payload["result"])
            elif fact["fact_type"] == "selection_terminal":
                selection_error = payload["error"]
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
            "workflow_commit_id": scope["workflow_commit_id"],
            "workflow_commit_revision": scope[
                "workflow_commit_revision"
            ],
            "workflow_digest": scope["workflow_digest"],
            "status": status,
            "ledger_cursor": self._cursor_at(len(self._state.facts)),
            "node_dispositions": dispositions,
            "outputs": outputs,
            "artifact_index": artifacts,
        }
        if scope.get("selection_required", False):
            projection["selection_results"] = selection_results
        if selection_error is not None:
            projection["selection_error"] = selection_error
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
            if self._state.cancellation_sequence is not None:
                decision_sequence = self._state.cancellation_sequence
                return {
                    "outcome": "already_requested",
                    "decision_sequence": decision_sequence,
                    "cursor": self._cursor_at(decision_sequence),
                }
            if self._state.run_terminal:
                terminal_sequence = len(self._state.facts)
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
            if set(self._state.dispositions) == set(self._plan_nodes):
                decision_sequence = len(self._state.facts)
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
            for fact in self._state.facts
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
            field="run_projection",
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

    def _stage_facts(
        self,
        facts: tuple[dict[str, Any], ...],
    ) -> _LedgerReducerState:
        for fact in facts:
            self._validate_schema(fact["fact_type"], fact["payload"])
        self._validate_transaction_boundary(facts)
        prior_state = self._state
        staged_state = prior_state.clone()
        self._install_reducer_state(staged_state)
        try:
            for fact in facts:
                fact_type = fact["fact_type"]
                payload = fact["payload"]
                self._validate_causality(fact_type, payload)
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
                retained = deepcopy(fact)
                self._state.facts.append(retained)
                self._apply(fact_type, payload)
            return staged_state
        finally:
            self._install_reducer_state(prior_state)

    def _validate_transaction_boundary(
        self,
        facts: tuple[dict[str, Any], ...],
    ) -> None:
        operation_terminals = [
            fact
            for fact in facts
            if fact["fact_type"] == "operation_attempt_terminal"
        ]
        node_terminals = [
            fact
            for fact in facts
            if fact["fact_type"] == "node_attempt_terminal"
        ]
        publications = [
            fact
            for fact in facts
            if fact["fact_type"]
            in {"artifact_published", "outputs_published"}
        ]
        dispositions = [
            fact
            for fact in facts
            if fact["fact_type"] == "node_disposition"
        ]
        if not (operation_terminals or node_terminals or publications):
            return
        if (
            len(operation_terminals) > 1
            or len(node_terminals) != 1
            or len(dispositions) != 1
        ):
            raise self._causal_error()
        node_terminal = node_terminals[0]["payload"]
        attempt = self._state.node_attempts.get(
            node_terminal["node_attempt_id"]
        )
        if (
            attempt is None
            or dispositions[0]["payload"]["node_id"] != attempt["node_id"]
        ):
            raise self._causal_error()
        terminal_succeeded = node_terminal["status"] == "succeeded"
        output_publications = [
            fact
            for fact in publications
            if fact["fact_type"] == "outputs_published"
        ]
        publication_node_ids = {
            (
                fact["payload"]["node_id"]
                if fact["fact_type"] == "outputs_published"
                else fact["payload"]["artifact"]["node_id"]
            )
            for fact in publications
        }
        if (
            terminal_succeeded != (len(output_publications) == 1)
            or (not terminal_succeeded and publications)
            or publication_node_ids - {attempt["node_id"]}
        ):
            raise self._causal_error()
        artifact_publications = [
            fact["payload"]["artifact"]
            for fact in publications
            if fact["fact_type"] == "artifact_published"
        ]
        if output_publications and (
            output_publications[0]["payload"]["artifacts"]
            != artifact_publications
        ):
            raise self._causal_error()
        open_operations = [
            operation_id
            for operation_id, operation in self._state.operations.items()
            if (
                operation["node_attempt_id"]
                == node_terminal["node_attempt_id"]
                and operation["terminal"] is None
            )
        ]
        if (
            bool(open_operations) != bool(operation_terminals)
            or (
                operation_terminals
                and operation_terminals[0]["payload"][
                    "operation_attempt_id"
                ]
                not in open_operations
            )
        ):
            raise self._causal_error()
        expected_fact_types = [
            *(
                ("operation_attempt_terminal",)
                if operation_terminals
                else ()
            ),
            *(("outputs_published",) if terminal_succeeded else ()),
            *("artifact_published" for _ in artifact_publications),
            "node_attempt_terminal",
            "node_disposition",
        ]
        if [fact["fact_type"] for fact in facts] != expected_fact_types:
            raise self._causal_error()

    def commit(
        self,
        logical_facts: tuple[ProposedFact, ...],
    ) -> CommittedFactRange:
        """Validate and durably publish one atomic logical transition."""
        if not logical_facts:
            raise ValueError("Run Ledger transaction must contain facts")
        with self._condition:
            first_sequence = len(self._state.facts) + 1
            facts = tuple(
                {
                    "sequence": first_sequence + offset,
                    "recorded_at": run_timestamp(),
                    "fact_type": proposed.fact_type,
                    "payload": sanitize_public_value(dict(proposed.payload)),
                }
                for offset, proposed in enumerate(logical_facts)
            )
            staged_state = self._stage_facts(facts)
            transaction_sequence = self._transaction_count + 1
            transaction = {
                "schema_namespace": RUN_LEDGER_TRANSACTION_NAMESPACE,
                "schema_version": RUN_LEDGER_SCHEMA_VERSION,
                "project_id": self._project_id,
                "run_id": self._run_id,
                "transaction_sequence": transaction_sequence,
                "first_fact_sequence": first_sequence,
                "last_fact_sequence": facts[-1]["sequence"],
                "committed_at": run_timestamp(),
                "facts": list(facts),
            }
            encoded = canonical_json_bytes(transaction)
            if len(encoded) > MAX_LEDGER_TRANSACTION_BYTES:
                raise V2RunError(
                    "evidence_unavailable",
                    "Required Run evidence exceeds the durable transaction bound",
                    details={"last_durable_cursor": self.cursor},
                )
            try:
                self._transaction_store.publish(
                    root=self._root,
                    relative_parts=(
                        self._run_id,
                        "ledger",
                        f"{transaction_sequence:020d}.json",
                    ),
                    payload=encoded,
                )
            except (OSError, StoragePathError) as error:
                raise V2RunError(
                    "evidence_unavailable",
                    "Required Run evidence transaction could not be acknowledged",
                    details={"last_durable_cursor": self.cursor},
                ) from error
            try:
                self._install_reducer_state(staged_state)
            except RuntimeError:
                try:
                    reloaded = _read_run_evidence_ledger(
                        self._projects,
                        self._project_id,
                        self._run_id,
                        self._transaction_store,
                    )
                    if reloaded is None:
                        raise RuntimeError(
                            "Acknowledged Run evidence is absent"
                        )
                except (OSError, StoragePathError, RuntimeError) as reload_error:
                    raise V2RunError(
                        "evidence_unavailable",
                        "Acknowledged Run evidence could not be reloaded",
                        details={"last_durable_cursor": self.cursor},
                    ) from reload_error
                _RunEvidenceLedger._install_reducer_state(
                    self,
                    reloaded._capture_reducer_state(),
                )
                self._transaction_count = reloaded._transaction_count
                self._committed_fact_count = (
                    reloaded._committed_fact_count
                )
            else:
                self._transaction_count = transaction_sequence
                self._committed_fact_count = facts[-1]["sequence"]
            try:
                self._refresh_projections()
            except (OSError, StoragePathError) as error:
                self._projection_error = error
            else:
                self._projection_error = None
            self._condition.notify_all()
            retained = tuple(deepcopy(fact) for fact in facts)
            return CommittedFactRange(
                first_sequence=first_sequence,
                last_sequence=facts[-1]["sequence"],
                facts=retained,
            )

    def append(self, fact_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Commit one logical fact through the sole transaction interface."""
        committed = self.commit((ProposedFact(fact_type, payload),))
        return dict(committed.facts[0])

    @contextmanager
    def _ordered_append_scope(self) -> Iterator[None]:
        """Keep one caller-owned evidence sequence ordered with cancellation."""
        with self._condition:
            yield

    def append_terminal_from_success(
        self,
        fact_type: str,
        identity: Mapping[str, Any],
    ) -> str:
        """Order successful completion against cancellation atomically."""
        with self._condition:
            status = (
                "cancelled"
                if self._state.cancellation_sequence is not None
                else "succeeded"
            )
            self.append(fact_type, {**identity, "status": status})
            return status

    def load_transaction(
        self,
        transaction: Mapping[str, Any],
        encoded: bytes,
    ) -> None:
        with self._condition:
            if (
                not isinstance(transaction, Mapping)
                or set(transaction)
                != {
                    "schema_namespace",
                    "schema_version",
                    "project_id",
                    "run_id",
                    "transaction_sequence",
                    "first_fact_sequence",
                    "last_fact_sequence",
                    "committed_at",
                    "facts",
                }
                or transaction["schema_namespace"]
                != RUN_LEDGER_TRANSACTION_NAMESPACE
                or transaction["schema_version"] != RUN_LEDGER_SCHEMA_VERSION
                or transaction["project_id"] != self._project_id
                or transaction["run_id"] != self._run_id
                or type(transaction["transaction_sequence"]) is not int
                or transaction["transaction_sequence"]
                != self._transaction_count + 1
                or type(transaction["first_fact_sequence"]) is not int
                or transaction["first_fact_sequence"] != len(self._state.facts) + 1
                or type(transaction["last_fact_sequence"]) is not int
                or not isinstance(transaction["committed_at"], str)
                or not isinstance(transaction["facts"], list)
                or not transaction["facts"]
                or transaction["last_fact_sequence"]
                != transaction["first_fact_sequence"]
                + len(transaction["facts"])
                - 1
                or canonical_json_bytes(dict(transaction)) != encoded
            ):
                raise self._causal_error()
            facts: list[dict[str, Any]] = []
            for expected_sequence, fact in enumerate(
                transaction["facts"],
                start=transaction["first_fact_sequence"],
            ):
                if (
                    not isinstance(fact, Mapping)
                    or set(fact)
                    != {"sequence", "recorded_at", "fact_type", "payload"}
                    or type(fact["sequence"]) is not int
                    or fact["sequence"] != expected_sequence
                    or not isinstance(fact["recorded_at"], str)
                    or not isinstance(fact["fact_type"], str)
                    or not isinstance(fact["payload"], Mapping)
                ):
                    raise self._causal_error()
                facts.append(deepcopy(dict(fact)))
            staged_state = self._stage_facts(tuple(facts))
            self._install_reducer_state(staged_state)
            self._transaction_count = transaction["transaction_sequence"]
            self._committed_fact_count = transaction["last_fact_sequence"]

    def public_events(
        self,
        *,
        after_sequence: int = 0,
        through_sequence: int | None = None,
    ) -> tuple[dict[str, Any], ...]:
        with self._condition:
            self._ensure_projection_consistency()
            upper = (
                len(self._state.facts)
                if through_sequence is None
                else min(through_sequence, len(self._state.facts))
            )
            return tuple(
                event
                for fact in self._state.facts[after_sequence:upper]
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
            through_sequence = len(self._state.facts)
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
                self._state.run_terminal,
            )

    def wait_for_public_events(
        self,
        after_sequence: int,
        *,
        timeout_seconds: float,
    ) -> tuple[tuple[dict[str, Any], ...], int, bool]:
        with self._condition:
            if (
                len(self._state.facts) <= after_sequence
                and not self._state.run_terminal
            ):
                self._condition.wait(timeout_seconds)
            return (
                self.public_events(after_sequence=after_sequence),
                len(self._state.facts),
                self._state.run_terminal,
            )

    def reconcile_restart(self, finalizer: NodeAttemptFinalizer) -> None:
        with self._condition:
            if not self._state.run_started or self._state.run_terminal:
                return
        if not self._state.restart_reconciled:
            self.append(
                "restart_reconciliation_started",
                {"restarted_at": run_timestamp()},
            )
        restart_error = {
            "code": "node_execution_failed",
            "message": "Execution outcome is unavailable after backend restart",
            "retryable": False,
            "correlation_id": f"restart-{self._run_id}",
            "details": {"exception_type": "BackendRestart"},
        }
        for invocation_id, invocation in tuple(self._state.invocations.items()):
            if invocation["terminal"] is None:
                self.append(
                    "engine_invocation_terminal",
                    {
                        "invocation_id": invocation_id,
                        "status": "outcome_unknown",
                        "error": restart_error,
                    },
                )
        for attempt_id, attempt in tuple(self._state.node_attempts.items()):
            if attempt["terminal"] is not None:
                continue
            child_operations = [
                (operation_id, operation)
                for operation_id, operation in self._state.operations.items()
                if operation["node_attempt_id"] == attempt_id
            ]
            open_operation_id: str | None = None
            child_statuses: list[str] = []
            for operation_id, operation in child_operations:
                terminal = operation["terminal"]
                if terminal is None:
                    invocation_statuses = [
                        invocation["terminal"]
                        for invocation in self._state.invocations.values()
                        if invocation["operation_attempt_id"] == operation_id
                    ]
                    terminal = (
                        "outcome_unknown"
                        if "outcome_unknown" in invocation_statuses
                        else "interrupted"
                    )
                    open_operation_id = operation_id
                child_statuses.append(terminal)
            node_id = attempt["node_id"]
            resolution = (
                "cache_replayed"
                if node_id in self._state.outputs_published and not child_operations
                else "executed"
            )
            finalizer.finalize(
                CancelledOrInterruptedNode(
                    node_id=node_id,
                    status=(
                        "outcome_unknown"
                        if "outcome_unknown" in child_statuses
                        else "interrupted"
                    ),
                    public_error=restart_error,
                    node_attempt_id=attempt_id,
                    operation_attempt_id=open_operation_id,
                    resolution=resolution,
                )
            )
        for node_id in self._plan_node_order:
            if node_id in self._state.dispositions:
                continue
            if node_id in self._state.node_attempt_by_node:
                raise self._causal_error()
            blocked_by = sorted(
                dependency
                for dependency in self._required_dependencies[node_id]
                if self._state.dispositions.get(dependency, {}).get("outcome")
                != "succeeded"
            )
            if blocked_by:
                finalizer.conclude(
                    BlockedNode(
                        node_id=node_id,
                        blocked_by=tuple(blocked_by),
                    )
                )
            else:
                finalizer.finalize(
                    CancelledOrInterruptedNode(
                        node_id=node_id,
                        status="interrupted",
                        public_error=restart_error,
                    )
                )
        self.append("run_terminal", {"status": "interrupted"})


class NodeAttemptFinalizer:
    """The sole completion seam for one scheduled Node Execution Attempt."""

    def __init__(
        self,
        *,
        ledger: _RunEvidenceLedger,
        result_replay_source: ResultReplaySource,
        materialize_artifacts: _ArtifactMaterializer,
        object_store: ProjectObjectStore,
    ) -> None:
        self._ledger = ledger
        self._result_replay_source = result_replay_source
        self._materialize_artifacts = materialize_artifacts
        self._object_store = object_store

    def _publish_typed_outputs(
        self,
        *,
        project_id: str,
        node_id: str,
        descriptors: list[dict[str, Any]],
        admitted_outputs: Mapping[tuple[str, str], AdmittedPortValues],
    ) -> list[dict[str, Any]]:
        published: list[dict[str, Any]] = []
        for descriptor in descriptors:
            snapshot = admitted_outputs[(node_id, descriptor["output_port"])]
            value_entries: list[dict[str, Any]] = []
            for index, value in enumerate(snapshot.values):
                stored = self._object_store.put_exact(
                    project_id,
                    value.canonical_bytes,
                )
                if stored.content_digest != value.content_digest:
                    raise ObjectIntegrityError(stored.content_digest)
                value_entries.append(
                    {
                        "index": index,
                        "content_digest": value.content_digest,
                        "size": stored.size,
                        "object": stored.to_dict(),
                    }
                )
            manifest = {
                "schema_namespace": PORT_VALUE_MANIFEST_NAMESPACE,
                "port_type": dict(snapshot.port_type),
                "multiplicity": snapshot.multiplicity,
                "content_digest": snapshot.content_digest,
                "value_count": len(snapshot.values),
                "values": value_entries,
            }
            manifest_object = self._object_store.put_exact(
                project_id,
                canonical_json_bytes(manifest),
            )
            published.append(
                {
                    **descriptor,
                    "value_count": len(snapshot.values),
                    "value_manifest_reference": (
                        manifest_object.content_digest
                    ),
                }
            )
        return published

    @staticmethod
    def _disposition_for_status(
        status: Literal[
            "failed",
            "cancelled",
            "interrupted",
            "outcome_unknown",
        ],
    ) -> Literal["failed", "cancelled", "interrupted"]:
        return "interrupted" if status == "outcome_unknown" else status

    def _finalize_non_success(
        self,
        intent: ExecutedNodeNonSuccess,
        *,
        resolution: Literal["executed", "cache_replayed"],
    ) -> FinalizedNode:
        with self._ledger._ordered_append_scope():
            terminal_payload = {
                "status": intent.status,
                "error": dict(intent.public_error),
            }
            facts: list[ProposedFact] = []
            if intent.operation_attempt_id is not None:
                facts.append(
                    ProposedFact(
                        "operation_attempt_terminal",
                        {
                            "operation_attempt_id": (
                                intent.operation_attempt_id
                            ),
                            **terminal_payload,
                        },
                    )
                )
            disposition = self._disposition_for_status(intent.status)
            facts.extend(
                (
                    ProposedFact(
                        "node_attempt_terminal",
                        {
                            "node_attempt_id": intent.node_attempt_id,
                            "resolution": resolution,
                            **terminal_payload,
                        },
                    ),
                    ProposedFact(
                        "node_disposition",
                        {
                            "node_id": intent.node_id,
                            "outcome": disposition,
                            "blocked_by": [],
                        },
                    ),
                )
            )
            self._ledger.commit(tuple(facts))
            return FinalizedNode(disposition=disposition)

    def _finalize_termination(
        self,
        intent: CancelledOrInterruptedNode,
    ) -> FinalizedNode:
        with self._ledger._ordered_append_scope():
            disposition = self._disposition_for_status(intent.status)
            facts: list[ProposedFact] = []
            if intent.node_attempt_id is not None:
                terminal_payload: dict[str, Any] = {"status": intent.status}
                if intent.public_error is not None:
                    terminal_payload["error"] = dict(intent.public_error)
                if intent.operation_attempt_id is not None:
                    facts.append(
                        ProposedFact(
                            "operation_attempt_terminal",
                            {
                                "operation_attempt_id": (
                                    intent.operation_attempt_id
                                ),
                                **terminal_payload,
                            },
                        )
                    )
                facts.append(
                    ProposedFact(
                        "node_attempt_terminal",
                        {
                            "node_attempt_id": intent.node_attempt_id,
                            "resolution": intent.resolution,
                            **terminal_payload,
                        },
                    )
                )
            facts.append(
                ProposedFact(
                    "node_disposition",
                    {
                        "node_id": intent.node_id,
                        "outcome": disposition,
                        "blocked_by": [],
                    },
                )
            )
            self._ledger.commit(tuple(facts))
            return FinalizedNode(disposition=disposition)

    def _finalize_blocked(self, intent: BlockedNode) -> FinalizedNode:
        with self._ledger._ordered_append_scope():
            self._ledger.commit(
                (
                    ProposedFact(
                        "node_disposition",
                        {
                            "node_id": intent.node_id,
                            "outcome": "blocked",
                            "blocked_by": list(intent.blocked_by),
                        },
                    ),
                )
            )
            return FinalizedNode(disposition="blocked")

    def _finalize_preparation_failure(
        self,
        *,
        context: _NodeCompletionContext,
        error: BaseException,
    ) -> FinalizedNode:
        return self._finalize_non_success(
            ExecutedNodeNonSuccess(
                node_id=context.node_id,
                node_attempt_id=context.node_attempt_id,
                operation_attempt_id=context.operation_attempt_id,
                status="failed",
                public_error=_public_failure(error),
            ),
            resolution=context.resolution,
        )

    def _finalize_committed_cancellation(
        self,
        *,
        context: _NodeCompletionContext,
    ) -> FinalizedNode | None:
        if not self._ledger.cancellation_requested:
            return None
        cancellation = context.resources._cancellation_control
        if cancellation is not None:
            cancellation.wait_for_cleanup()
        if cancellation is not None and cancellation.cleanup_error is not None:
            return self._finalize_non_success(
                ExecutedNodeNonSuccess(
                    node_id=context.node_id,
                    node_attempt_id=context.node_attempt_id,
                    operation_attempt_id=context.operation_attempt_id,
                    status="failed",
                    public_error=_public_failure(cancellation.cleanup_error),
                ),
                resolution=context.resolution,
            )
        return self._finalize_termination(
            CancelledOrInterruptedNode(
                node_id=context.node_id,
                status="cancelled",
                public_error=None,
                node_attempt_id=context.node_attempt_id,
                operation_attempt_id=context.operation_attempt_id,
                resolution=context.resolution,
            )
        )

    def _materialize_success(
        self,
        intent: ExecutedNodeSuccess | CacheReplayNodeSuccess,
        *,
        producer_run_id: str,
        resolution: Literal["executed", "cache_replayed"],
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]:
        admitted_descriptors = [
            dict(output) for output in intent.admitted_output_descriptors
        ]
        cache_descriptors = _with_result_provenance(
            admitted_descriptors,
            result_identity=intent.result_identity,
            current_run_id=intent.run_id,
            producer_run_id=producer_run_id,
            resolution=resolution,
        )
        typed_descriptors, artifacts = (
            self._materialize_artifacts(
                node=intent.node,
                resources=intent.resources,
                admitted_output_descriptors=admitted_descriptors,
                runtime=intent.admitted_outputs,
                current_artifact_count=intent.current_artifact_count,
                current_artifact_bytes=intent.current_artifact_bytes,
            )
        )
        typed_descriptors = self._publish_typed_outputs(
            project_id=intent.project_id,
            node_id=intent.node.node_id,
            descriptors=typed_descriptors,
            admitted_outputs=intent.admitted_outputs,
        )
        return (
            _with_result_provenance(
                typed_descriptors,
                result_identity=intent.result_identity,
                current_run_id=intent.run_id,
                producer_run_id=producer_run_id,
                resolution=resolution,
            ),
            artifacts,
            cache_descriptors,
        )

    def _persist_success(
        self,
        *,
        context: _NodeCompletionContext,
        admitted_outputs: Mapping[tuple[str, str], AdmittedPortValues],
        typed_descriptors: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
    ) -> FinalizedNode:
        facts: list[ProposedFact] = []
        if context.operation_attempt_id is not None:
            facts.append(
                ProposedFact(
                    "operation_attempt_terminal",
                    {
                        "operation_attempt_id": context.operation_attempt_id,
                        "status": "succeeded",
                    },
                )
            )
        facts.append(
            ProposedFact(
                "outputs_published",
                {
                    "node_id": context.node_id,
                    "outputs": typed_descriptors,
                    "artifacts": artifacts,
                },
            )
        )
        facts.extend(
            ProposedFact("artifact_published", {"artifact": artifact})
            for artifact in artifacts
        )
        facts.extend(
            (
                ProposedFact(
                    "node_attempt_terminal",
                    {
                        "node_attempt_id": context.node_attempt_id,
                        "status": "succeeded",
                        "resolution": context.resolution,
                    },
                ),
                ProposedFact(
                    "node_disposition",
                    {
                        "node_id": context.node_id,
                        "outcome": "succeeded",
                        "resolution": context.resolution,
                        "blocked_by": [],
                    },
                ),
            )
        )
        self._ledger.commit(tuple(facts))
        return FinalizedNode(
            disposition="succeeded",
            admitted_outputs=admitted_outputs,
            artifacts=tuple(artifacts),
        )

    def _finalize_executed_success(
        self,
        intent: ExecutedNodeSuccess,
    ) -> FinalizedNode:
        context = _NodeCompletionContext(
            node_id=intent.node.node_id,
            node_attempt_id=intent.node_attempt_id,
            operation_attempt_id=intent.operation_attempt_id,
            resolution="executed",
            resources=intent.resources,
        )
        typed_descriptors: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []
        cache_descriptors: list[dict[str, Any]] = []
        preparation_error: BaseException | None = None
        try:
            (
                typed_descriptors,
                artifacts,
                cache_descriptors,
            ) = self._materialize_success(
                intent,
                producer_run_id=intent.run_id,
                resolution="executed",
            )
        except (
            ObjectIntegrityError,
            PortValueError,
            OSError,
            StoragePathError,
        ) as error:
            preparation_error = error
        if intent.cache_eligible and preparation_error is None:
            try:
                self._result_replay_source.validate_publish(
                    project_id=intent.project_id,
                    execution_plan=intent.execution_plan,
                    node=intent.node,
                    result_identity=intent.result_identity,
                    outputs=cache_descriptors,
                    producer_run_id=intent.run_id,
                    admitted_outputs=intent.admitted_outputs,
                )
            except V2RunError as error:
                if error.code != "cache_identity_conflict":
                    raise
                preparation_error = error
            except (OSError, StoragePathError) as error:
                preparation_error = error

        with self._ledger._ordered_append_scope():
            cancelled = self._finalize_committed_cancellation(
                context=context,
            )
            if cancelled is not None:
                return cancelled
            if preparation_error is not None:
                return self._finalize_preparation_failure(
                    context=context,
                    error=preparation_error,
                )
            rollback_cache: Callable[[], None] | None = None
            if intent.cache_eligible:
                try:
                    rollback_cache = self._result_replay_source.publish(
                        project_id=intent.project_id,
                        execution_plan=intent.execution_plan,
                        node=intent.node,
                        result_identity=intent.result_identity,
                        outputs=cache_descriptors,
                        producer_run_id=intent.run_id,
                        admitted_outputs=intent.admitted_outputs,
                    )
                except V2RunError as error:
                    if error.code != "cache_identity_conflict":
                        raise
                    return self._finalize_preparation_failure(
                        context=context,
                        error=error,
                    )
            persisted = False
            try:
                finalized = self._persist_success(
                    context=context,
                    admitted_outputs=intent.admitted_outputs,
                    typed_descriptors=typed_descriptors,
                    artifacts=artifacts,
                )
                persisted = True
                return finalized
            finally:
                if not persisted and rollback_cache is not None:
                    rollback_cache()

    def _finalize_cache_replay_success(
        self,
        intent: CacheReplayNodeSuccess,
    ) -> FinalizedNode:
        context = _NodeCompletionContext(
            node_id=intent.node.node_id,
            node_attempt_id=intent.node_attempt_id,
            operation_attempt_id=None,
            resolution="cache_replayed",
            resources=intent.resources,
        )
        typed_descriptors: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []
        preparation_error: BaseException | None = None
        try:
            (
                typed_descriptors,
                artifacts,
                _,
            ) = self._materialize_success(
                intent,
                producer_run_id=intent.producer_run_id,
                resolution="cache_replayed",
            )
        except (
            ObjectIntegrityError,
            PortValueError,
            OSError,
            StoragePathError,
        ) as error:
            preparation_error = error
        with self._ledger._ordered_append_scope():
            cancelled = self._finalize_committed_cancellation(
                context=context,
            )
            if cancelled is not None:
                return cancelled
            if preparation_error is not None:
                return self._finalize_preparation_failure(
                    context=context,
                    error=preparation_error,
                )
            return self._persist_success(
                context=context,
                admitted_outputs=intent.admitted_outputs,
                typed_descriptors=typed_descriptors,
                artifacts=artifacts,
            )

    def finalize(self, intent: NodeFinalizationIntent) -> FinalizedNode:
        """Commit the disposition implied by one closed finalization intent."""
        if isinstance(intent, ExecutedNodeSuccess):
            return self._finalize_executed_success(intent)
        if isinstance(intent, CacheReplayNodeSuccess):
            return self._finalize_cache_replay_success(intent)
        if isinstance(intent, ExecutedNodeNonSuccess):
            return self._finalize_non_success(intent, resolution="executed")
        if isinstance(intent, CancelledOrInterruptedNode):
            return self._finalize_termination(intent)
        raise TypeError("Node finalization intent is not current")

    def conclude(self, intent: BlockedNode) -> FinalizedNode:
        """Persist one closed disposition-only Node conclusion."""
        if isinstance(intent, BlockedNode):
            return self._finalize_blocked(intent)
        raise TypeError("Node disposition intent is not current")


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
        parent_invocation_id: str | None,
        invocation_provenance: Mapping[str, Any] | None,
    ):
        invocation_id = f"invocation-{uuid.uuid4().hex}"
        payload = {
            "invocation_id": invocation_id,
            "operation_attempt_id": self.operation_attempt_id,
            "engine_role": engine_role,
            "engine_identity": self.default_engine_identity,
        }
        if parent_invocation_id is not None:
            payload["parent_invocation_id"] = parent_invocation_id
        if invocation_provenance is not None:
            payload["invocation_provenance"] = invocation_provenance
        self.ledger.append(
            "engine_invocation_started",
            payload,
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
    cancellation: _CancellationControl = field(
        default_factory=_CancellationControl,
    )
    finished: threading.Event = field(default_factory=threading.Event)
    execution_error: BaseException | None = None


_RESOLVED_CONTRACT_FIELDS = frozenset(
    {
        "contract_kind",
        "contract_id",
        "contract_version",
        "contract_digest",
    }
)


def _execution_plan_contract_roots(
    plan: ExecutionPlan,
) -> list[dict[str, Any]]:
    """Persist the exact roots needed to reconstruct one Plan's Lock."""
    root_identities = {
        reference.key
        for node in plan.nodes
        for reference in (node.node_type, node.binding)
    }
    for resolved_selector in plan._runtime.observation_selectors:
        selector = resolved_selector.selector
        root_identities.update(
            {
                (
                    selector.metric.contract_kind,
                    selector.metric.contract_id,
                    selector.metric.contract_version,
                ),
                (
                    selector.method.contract_kind,
                    selector.method.contract_id,
                    selector.method.contract_version,
                ),
            }
        )
    for resolved_objective in plan._runtime.selection_objectives:
        objective = resolved_objective.objective
        root_identities.update(
            {
                (
                    objective.metric.contract_kind,
                    objective.metric.contract_id,
                    objective.metric.contract_version,
                ),
                (
                    objective.method.contract_kind,
                    objective.method.contract_id,
                    objective.method.contract_version,
                ),
                (
                    objective.utility_transform.contract_kind,
                    objective.utility_transform.contract_id,
                    objective.utility_transform.contract_version,
                ),
            }
        )
    lock_by_identity = {
        entry.key: entry for entry in plan.resolved_contracts
    }
    return [
        lock_by_identity[identity].to_public()
        for identity in sorted(root_identities)
    ]


def _reachable_contract_evidence(
    catalog: FrozenCatalog,
    roots: Any,
) -> list[dict[str, Any]]:
    """Rebuild the exact active Catalog closure from durable Plan roots."""
    if (
        not isinstance(roots, list)
        or any(
            not isinstance(entry, Mapping)
            or set(entry) != _RESOLVED_CONTRACT_FIELDS
            or not all(
                isinstance(entry[field], str)
                for field in _RESOLVED_CONTRACT_FIELDS
            )
            for entry in roots
        )
    ):
        raise RuntimeError("Run scope Contract roots are invalid")
    root_identities = [
        (
            entry["contract_kind"],
            entry["contract_id"],
            entry["contract_version"],
        )
        for entry in roots
    ]
    if (
        len(set(root_identities)) != len(root_identities)
        or root_identities != sorted(root_identities)
    ):
        raise RuntimeError("Run scope Contract roots are invalid")

    pending = [dict(entry) for entry in roots]
    reachable: dict[tuple[str, str, str], dict[str, Any]] = {}
    while pending:
        reference = pending.pop()
        identity = (
            reference["contract_kind"],
            reference["contract_id"],
            reference["contract_version"],
        )
        contract = catalog.require_contract(*identity)
        current_reference = contract.reference()
        if reference != current_reference:
            raise RuntimeError("Run scope Contract root is not active")
        if identity in reachable:
            continue
        reachable[identity] = current_reference
        nested_values: list[Any] = [contract.descriptor]
        while nested_values:
            value = nested_values.pop()
            if (
                isinstance(value, Mapping)
                and set(value) == _RESOLVED_CONTRACT_FIELDS
            ):
                pending.append(dict(value))
            elif isinstance(value, Mapping):
                nested_values.extend(value.values())
            elif isinstance(value, (list, tuple)):
                nested_values.extend(value)
    return [reachable[identity] for identity in sorted(reachable)]


def _validated_run_catalog_digest(
    ledger: _RunEvidenceLedger,
    catalog: FrozenCatalog,
) -> str:
    """Classify one validated Ledger and verify active-generation locks."""
    facts = ledger.facts
    if not facts or facts[0]["fact_type"] != "run_scope_bound":
        raise RuntimeError("Run scope evidence is missing")
    scope = facts[0]["payload"]
    persisted_catalog_digest = scope.get("catalog_contract_digest")
    if (
        not isinstance(persisted_catalog_digest, str)
        or re.fullmatch(
            r"sha256:[0-9a-f]{64}",
            persisted_catalog_digest,
        )
        is None
    ):
        raise RuntimeError("Run scope Catalog identity is invalid")
    if persisted_catalog_digest != catalog.contract_digest:
        return persisted_catalog_digest

    resolved_contracts = scope.get("resolved_contracts")
    persisted_lock_digest = scope.get("contract_lock_digest")
    if (
        not isinstance(resolved_contracts, list)
        or any(
            not isinstance(entry, Mapping)
            or set(entry) != _RESOLVED_CONTRACT_FIELDS
            or not all(
                isinstance(entry[field], str)
                for field in _RESOLVED_CONTRACT_FIELDS
            )
            for entry in resolved_contracts
        )
        or not isinstance(persisted_lock_digest, str)
        or persisted_lock_digest
        != canonical_sha256(
            {
                "schema_namespace": CONTRACT_LOCK_NAMESPACE,
                "entries": resolved_contracts,
            }
        )
    ):
        raise RuntimeError("Run scope Contract Lock evidence is invalid")
    expected_contracts = _reachable_contract_evidence(
        catalog,
        scope.get("resolved_contract_roots"),
    )
    if [dict(entry) for entry in resolved_contracts] != expected_contracts:
        raise RuntimeError("Run scope resolved Contracts are invalid")
    return persisted_catalog_digest


def _read_run_evidence_ledger(
    projects: ProjectManager,
    project_id: str,
    run_id: str,
    transaction_store: LedgerTransactionStore | None = None,
) -> _RunEvidenceLedger | None:
    """Load and causally validate one Run's physical transactions."""
    run_dir = projects.run_dir(project_id, run_id)
    ledger_dir = run_dir / "ledger"
    if (
        not ledger_dir.is_dir()
        or ledger_dir.is_symlink()
    ):
        return None
    transaction_paths = sorted(ledger_dir.glob("*.json"))
    if not transaction_paths:
        return None
    encoded_transactions: list[bytes] = []
    parsed_transactions: list[Mapping[str, Any]] = []
    for expected_sequence, path in enumerate(transaction_paths, start=1):
        if path.name != f"{expected_sequence:020d}.json":
            raise RuntimeError(
                "Run Ledger transaction sequence is not contiguous"
            )
        encoded = _read_stable_private_file(
            run_dir.parent,
            (run_id, "ledger", path.name),
            field="run_ledger",
            maximum_size=MAX_LEDGER_TRANSACTION_BYTES,
        )
        parsed = json.loads(encoded)
        if not isinstance(parsed, Mapping):
            raise RuntimeError("Run Ledger transaction is invalid")
        encoded_transactions.append(encoded)
        parsed_transactions.append(parsed)
    first = parsed_transactions[0]["facts"][0]
    plan_nodes = _parse_plan_evidence(
        first["payload"]["plan_nodes"]
    )
    ledger = _RunEvidenceLedger(
        projects,
        project_id,
        run_id,
        plan_nodes,
        transaction_store,
    )
    for transaction, encoded in zip(
        parsed_transactions,
        encoded_transactions,
        strict=True,
    ):
        ledger.load_transaction(transaction, encoded)
    return ledger


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


def _freeze_runtime_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({
            str(key): _freeze_runtime_json(item)
            for key, item in value.items()
        })
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_runtime_json(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class _EffectiveRandomnessSnapshot:
    effective_randomness: Mapping[str, Any]
    node_parameters: Mapping[str, Any]
    binding_parameters: Mapping[str, Any]


def _resolve_effective_randomness(
    node: ExecutionPlanNode,
    inputs: Mapping[str, Any],
) -> _EffectiveRandomnessSnapshot:
    binding_contract = node._runtime.binding_contract
    node_parameters = _plain_json(node.node_parameters)
    binding_parameters = _plain_json(node.binding_parameters)
    declared_randomness = tuple(
        binding_contract.descriptor.get(
            "effective_randomness_parameters",
            (),
        )
    )
    if declared_randomness:
        resolver = node._runtime.effective_randomness_resolver
        if resolver is None:
            resolved_randomness: Mapping[str, Any] = {
                parameter_name: (
                    node_parameters[parameter_name]
                    if parameter_name in node_parameters
                    and parameter_name not in binding_parameters
                    else (
                        binding_parameters[parameter_name]
                        if parameter_name in binding_parameters
                        and parameter_name not in node_parameters
                        else {"resolution": "unresolved"}
                    )
                )
                for parameter_name in declared_randomness
            }
        else:
            resolved_randomness = resolver.resolve(
                inputs=inputs,
                node_parameters=node_parameters,
                binding_parameters=binding_parameters,
            )
            if (
                not isinstance(resolved_randomness, Mapping)
                or set(resolved_randomness) != set(declared_randomness)
            ):
                raise ValueError(
                    "effective randomness resolver must return every "
                    "declared parameter exactly once"
                )
        effective_randomness = {}
        for parameter_name in declared_randomness:
            resolved_value = _plain_json(
                resolved_randomness[parameter_name]
            )
            effective_randomness[parameter_name] = (
                {"resolution": "unresolved"}
                if resolved_value is None
                else resolved_value
            )
            if (
                parameter_name in node_parameters
                and parameter_name not in binding_parameters
            ):
                node_parameters[parameter_name] = resolved_value
            elif (
                parameter_name in binding_parameters
                and parameter_name not in node_parameters
            ):
                binding_parameters[parameter_name] = resolved_value
    else:
        effective_randomness = {}
    canonical_json_bytes(
        {
            "effective_randomness": effective_randomness,
            "node_parameters": node_parameters,
            "binding_parameters": binding_parameters,
        }
    )
    return _EffectiveRandomnessSnapshot(
        effective_randomness=_freeze_runtime_json(effective_randomness),
        node_parameters=_freeze_runtime_json(node_parameters),
        binding_parameters=_freeze_runtime_json(binding_parameters),
    )


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


def _result_identity_descriptor(
    node: ExecutionPlanNode,
    inputs: Mapping[str, Any],
    *,
    input_content_digests: Mapping[str, InputContentDigests],
    resolved_resource_inputs: tuple[Mapping[str, Any], ...] = (),
    effective_randomness_snapshot: _EffectiveRandomnessSnapshot | None = None,
) -> dict[str, Any]:
    """Build the closed scientific identity of one resolved Node result."""
    binding_contract = node._runtime.binding_contract
    plan_facts = node.result_identity_plan_facts
    canonical_plan_facts = plan_facts.canonical_projection()
    static_facts = canonical_plan_facts["identity_facts"]
    declared_inputs = {
        port["input_port"]: port
        for port in static_facts["input_contracts"]
    }
    admitted_input_digests = input_content_digests
    input_identities: list[dict[str, Any]] = []
    for port_name in sorted(inputs):
        declaration = declared_inputs[port_name]
        digest_record = admitted_input_digests[port_name]
        input_identities.append(
            {
                "input_port": port_name,
                "port_type": declaration["port_type"],
                "multiplicity": declaration["multiplicity"],
                "value_content_digests": list(
                    digest_record.value_content_digests
                ),
            }
        )
    randomness_snapshot = (
        effective_randomness_snapshot
        if effective_randomness_snapshot is not None
        else _resolve_effective_randomness(node, inputs)
    )
    resolved_node_parameters = _plain_json(
        randomness_snapshot.node_parameters
    )
    resolved_binding_parameters = _plain_json(
        randomness_snapshot.binding_parameters
    )
    for parameter_name in plan_facts.node_parameter_indirections:
        resolved_node_parameters.pop(parameter_name, None)
    for parameter_name in node._runtime.project_input_parameters:
        resolved_node_parameters.pop(parameter_name, None)
    declared_randomness = binding_contract.descriptor.get(
        "effective_randomness_parameters"
    )
    if declared_randomness:
        effective_randomness = _plain_json(
            randomness_snapshot.effective_randomness
        )
        for parameter_name in declared_randomness:
            resolved_node_parameters.pop(parameter_name, None)
            resolved_binding_parameters.pop(parameter_name, None)
    else:
        effective_randomness = _plain_json(
            randomness_snapshot.effective_randomness
        )
    descriptor = {
        "schema_namespace": RESULT_IDENTITY_NAMESPACE,
        "result_identity_plan_facts": canonical_plan_facts,
        "inputs": input_identities,
        "node_parameters": resolved_node_parameters,
        "binding_parameters": resolved_binding_parameters,
        "determinism": {
            "deterministic": binding_contract.descriptor.get("deterministic"),
            "effective_randomness": effective_randomness,
        },
    }
    if resolved_resource_inputs:
        descriptor["resolved_resource_inputs"] = [
            _plain_json(identity)
            for identity in resolved_resource_inputs
        ]
    return descriptor


def _candidate_data_type_id(value: Any) -> str | None:
    return {
        ProteinSequence: "protein.sequence",
        ProteinStructure: "protein.structure",
    }.get(type(value))


def _active_content_digest(
    port_types: Mapping[str, Any],
    type_id: str,
    value: Any,
) -> str:
    try:
        port_type = port_types[type_id]
    except KeyError as error:
        raise PortValueError(
            f"Execution Plan lacks Candidate data Port Type {type_id!r}"
        ) from error
    return port_type.content_digest(value)


def _candidate_data_content_digest(
    port_types: Mapping[str, Any],
    candidate: Candidate,
) -> str:
    type_id = _candidate_data_type_id(candidate.data)
    if type_id is None:
        raise PortValueError(
            "Candidate data has no registered content identity"
        )
    return _active_content_digest(port_types, type_id, candidate.data)


def _exact_reference(reference: Any) -> ExactContractReference:
    return ExactContractReference(
        contract_kind=reference.contract_kind,
        contract_id=reference.contract_id,
        contract_version=reference.contract_version,
        contract_digest=reference.contract_digest,
    )


def _candidate_digests_for_value(
    port_types: Mapping[str, Any],
    value: Any,
) -> tuple[CandidateDataReference, ...]:
    if type(value) is Candidate:
        candidates = (value,)
    elif type(value) is CandidateCollection:
        candidates = tuple(value.items)
    else:
        return ()
    digests: list[CandidateDataReference] = []
    for candidate in candidates:
        type_id = _candidate_data_type_id(candidate.data)
        if type_id is None:
            continue
        digests.append(
            CandidateDataReference(
                candidate_id=candidate.candidate_id,
                data_type_id=type_id,
                content_digest=_active_content_digest(
                    port_types,
                    type_id,
                    candidate.data,
                ),
            )
        )
    return tuple(digests)


def _result_identity(
    node: ExecutionPlanNode,
    inputs: Mapping[str, Any],
    *,
    input_content_digests: Mapping[str, InputContentDigests],
    resolved_resource_inputs: tuple[Mapping[str, Any], ...] = (),
    effective_randomness_snapshot: _EffectiveRandomnessSnapshot | None = None,
) -> str:
    return canonical_sha256(
        _result_identity_descriptor(
            node,
            inputs,
            input_content_digests=input_content_digests,
            resolved_resource_inputs=resolved_resource_inputs,
            effective_randomness_snapshot=effective_randomness_snapshot,
        )
    )


def _selection_consumer_result(
    node: ExecutionPlanNode,
    values: Mapping[tuple[str, str], AdmittedPortValues],
) -> dict[str, Any] | None:
    """Project one declared selection Node's actual typed output."""
    resolved_objectives = node._runtime.selection_objectives
    resolved_selectors = node._runtime.observation_selectors
    if not resolved_objectives and not resolved_selectors:
        return None
    if resolved_selectors:
        selectors = tuple(item.selector for item in resolved_selectors)
        candidate_references = {
            selector.candidate_input for selector in selectors
        }
    else:
        objectives = tuple(item.objective for item in resolved_objectives)
        candidate_references = {
            objective.candidate_input for objective in objectives
        }
    if len(candidate_references) != 1:
        raise SelectionError(
            "Selection consumer objectives do not share one Candidate input"
        )
    output_port = node._runtime.selection_candidate_output_port
    resolved = (
        values.get((node.node_id, output_port), [])
        if isinstance(output_port, str)
        else []
    )
    if (
        len(resolved) != 1
        or type(resolved[0]) is not CandidateCollection
    ):
        raise SelectionError(
            "Selection consumer output did not resolve to one exact "
            "CandidateCollection"
        )
    selected = resolved[0]
    candidate_reference = next(iter(candidate_references))
    result = {
        "status": "succeeded",
        "selection_node_id": node.node_id,
        "selection_method": node.method.to_public(),
        "candidate_input": candidate_reference.to_public(),
        "selected_collection_id": selected.collection_id,
        "selected_candidate_ids": [
            candidate.candidate_id for candidate in selected.items
        ],
    }
    if resolved_selectors:
        result["observation_selectors"] = [
            selector.to_public() for selector in selectors
        ]
    else:
        provenance = selection_objective_provenance_from_facts(
            resolved_objectives
        )
        result["objectives"] = provenance["objectives"]
    return result


def _contains_unresolved_identity(value: Any) -> bool:
    if isinstance(value, Mapping):
        if value.get("identity_complete") is False:
            return True
        return any(
            _contains_unresolved_identity(item)
            for item in value.values()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_unresolved_identity(item) for item in value)
    if is_dataclass(value) and not isinstance(value, type):
        return any(
            _contains_unresolved_identity(getattr(value, item.name))
            for item in fields(value)
        )
    return (
        isinstance(value, str)
        and value.strip().lower()
        in {"unknown", "unresolved", "latest", "unspecified"}
    )


def _result_identity_is_cache_safe(
    node: ExecutionPlanNode,
    inputs: Mapping[str, Any],
    *,
    input_content_digests: Mapping[str, InputContentDigests],
    resolved_resource_inputs: tuple[Mapping[str, Any], ...] = (),
    effective_randomness_snapshot: _EffectiveRandomnessSnapshot | None = None,
) -> bool:
    if _contains_unresolved_identity(
        node.result_identity_plan_facts.canonical_projection()
    ):
        return False
    if _contains_unresolved_identity(inputs):
        return False
    if _contains_unresolved_identity(
        _result_identity_descriptor(
            node,
            inputs,
            input_content_digests=input_content_digests,
            resolved_resource_inputs=resolved_resource_inputs,
            effective_randomness_snapshot=effective_randomness_snapshot,
        )
    ):
        return False
    return all(
        not _contains_unresolved_identity(candidate.candidate_id)
        for value in inputs.values()
        for candidate in V2RunService._candidate_values(value)
    )


def _result_contract_metadata(
    node: ExecutionPlanNode,
) -> dict[str, Any]:
    return (
        node.result_identity_plan_facts.cache_contract_metadata()
    )


def _with_result_provenance(
    outputs: list[dict[str, Any]],
    *,
    result_identity: str,
    current_run_id: str,
    producer_run_id: str,
    resolution: str,
) -> list[dict[str, Any]]:
    return [
        {
            **output,
            "result_identity": result_identity,
            "materialization": {
                "run_id": current_run_id,
                "resolution": resolution,
            },
            "producer_provenance": {
                "producer_run_id": producer_run_id,
                "producer_result_identity": result_identity,
                "output_port": output["output_port"],
            },
        }
        for output in outputs
    ]


class _ProjectResultCache(ResultReplaySource):
    """Project-owned canonical Port-codec Result storage."""

    def __init__(
        self,
        projects: ProjectManager,
        catalog: FrozenCatalog,
    ) -> None:
        self._projects = projects
        self._catalog = catalog

    @staticmethod
    def _relative_parts(result_identity: str) -> tuple[str, ...]:
        prefix, separator, digest = result_identity.partition(":")
        if (
            prefix != "sha256"
            or separator != ":"
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise PortValueError("Result Identity is not a canonical digest")
        return ("v3", "results", f"{digest}.json")

    def _load_entry(
        self,
        project_id: str,
        result_identity: str,
    ) -> dict[str, Any] | None:
        root = self._projects.cache_dir(project_id)
        parts = self._relative_parts(result_identity)
        try:
            encoded = _read_stable_private_file(
                root,
                parts,
                field="result_cache_entry",
                maximum_size=MAX_ARTIFACT_BYTES_PER_RUN,
            )
        except FileNotFoundError:
            return None
        try:
            payload = json.loads(encoded)
            if encoded != canonical_json_bytes(payload):
                raise PortValueError("Cache entry is not canonical")
            if (
                not isinstance(payload, dict)
                or set(payload)
                != {
                    "schema_namespace",
                    "result_identity",
                    "contract_metadata",
                    "producer",
                    "outputs",
                }
                or payload["schema_namespace"] != RESULT_CACHE_ENTRY_NAMESPACE
                or payload["result_identity"] != result_identity
                or not isinstance(payload["contract_metadata"], dict)
                or not isinstance(payload["producer"], dict)
                or set(payload["producer"])
                != {"producer_run_id", "producer_node_id"}
                or not isinstance(payload["outputs"], list)
            ):
                raise PortValueError("Cache entry contract is invalid")
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            PortValueError,
            ValueError,
        ) as error:
            raise RecoverableCacheMiss(
                "Result cache entry storage is corrupt"
            ) from error
        return payload

    def _producer_node_succeeded(
        self,
        project_id: str,
        producer: Mapping[str, Any],
    ) -> bool:
        """Expose a provisional entry only after Ledger-proven Node success."""
        try:
            producer_run_id = validate_identifier(
                producer["producer_run_id"],
                "producer_run_id",
            )
            producer_node_id = validate_identifier(
                producer["producer_node_id"],
                "producer_node_id",
            )
            ledger = _read_run_evidence_ledger(
                self._projects,
                project_id,
                producer_run_id,
            )
            if ledger is None:
                return False
            producer_catalog_digest = _validated_run_catalog_digest(
                ledger,
                self._catalog,
            )
            if producer_catalog_digest != self._catalog.contract_digest:
                raise V2RunError(
                    "inactive_generation",
                    "Result Cache producer belongs to an inactive Catalog generation",
                    details={
                        "artifact_kind": "result_cache",
                        "expected_catalog_contract_digest": (
                            self._catalog.contract_digest
                        ),
                        "received_catalog_contract_digest": (
                            producer_catalog_digest
                        ),
                    },
                )
        except V2RunError as error:
            if error.code == "inactive_generation":
                raise
            return False
        except (
            FileNotFoundError,
            KeyError,
            OSError,
            ProtocolValidationError,
            RuntimeError,
            StoragePathError,
            TypeError,
            ValueError,
        ):
            return False
        return any(
            fact["fact_type"] == "node_disposition"
            and fact["payload"]["node_id"] == producer_node_id
            and fact["payload"]["outcome"] == "succeeded"
            for fact in ledger.facts
        )

    def lookup(
        self,
        *,
        project_id: str,
        execution_plan: ExecutionPlan,
        node: ExecutionPlanNode,
        inputs: Mapping[str, Any],
        result_identity: str,
    ) -> ResultReplayHit | None:
        del inputs
        entry = self._load_entry(project_id, result_identity)
        if entry is None:
            return None
        if entry["contract_metadata"] != _result_contract_metadata(
            node,
        ):
            raise V2RunError(
                "cache_identity_conflict",
                "Result Identity resolves to conflicting contract metadata",
                details={"result_identity": result_identity},
            )
        if not self._producer_node_succeeded(
            project_id,
            entry["producer"],
        ):
            raise V2RunError(
                "cache_identity_conflict",
                "Cache replay producer provenance is not durably successful",
                details={"result_identity": result_identity},
            )
        declarations = {
            name: port.declaration
            for name, port in node._runtime.output_ports.items()
        }
        admitted_outputs: dict[
            tuple[str, str],
            AdmittedPortValues,
        ] = {}
        seen_ports: set[str] = set()
        for output in entry["outputs"]:
            if (
                not isinstance(output, dict)
                or set(output)
                != {
                    "output_port",
                    "port_type",
                    "content_digest",
                    "encoded_values",
                }
                or output["output_port"] in seen_ports
                or output["output_port"] not in declarations
                or not isinstance(output["encoded_values"], list)
            ):
                raise RecoverableCacheMiss(
                    "Result cache output storage is corrupt"
                )
            seen_ports.add(output["output_port"])
            declaration = declarations[output["output_port"]]
            if output["port_type"] != declaration["port_type"]:
                raise RecoverableCacheMiss(
                    "Result cache output contract storage is corrupt"
                )
            port_type = node._runtime.output_ports[
                output["output_port"]
            ].port_type
            try:
                canonical_values = tuple(
                    base64.b64decode(item, validate=True)
                    for item in output["encoded_values"]
                    if isinstance(item, str)
                )
                admitted = admitted_port_values_from_bytes(
                    port_type=port_type,
                    multiplicity=declaration["multiplicity"],
                    canonical_values=canonical_values,
                    candidate_data=lambda value: (
                        _candidate_digests_for_value(
                            execution_plan._runtime.candidate_data_port_types,
                            value,
                        )
                    ),
                )
            except (binascii.Error, PortValueError, ValueError):
                raise RecoverableCacheMiss(
                    "Result cache encoded output storage is corrupt"
                )
            if len(canonical_values) != len(output["encoded_values"]):
                raise RecoverableCacheMiss(
                    "Result cache output cardinality storage is corrupt"
                )
            if admitted.content_digest != output["content_digest"]:
                raise RecoverableCacheMiss(
                    "Result cache content digest storage is corrupt"
                )
            admitted_outputs[(node.node_id, output["output_port"])] = (
                admitted
            )
        if any(
            declaration["required"] is True and port_name not in seen_ports
            for port_name, declaration in declarations.items()
        ):
            raise RecoverableCacheMiss(
                "Result cache required output storage is incomplete"
            )
        return ResultReplayHit(
            result_identity=result_identity,
            producer_run_id=entry["producer"]["producer_run_id"],
            admitted_outputs=MappingProxyType(admitted_outputs),
        )

    def _entry(
        self,
        *,
        execution_plan: ExecutionPlan,
        node: ExecutionPlanNode,
        result_identity: str,
        outputs: list[dict[str, Any]],
        producer_run_id: str,
        admitted_outputs: Mapping[
            tuple[str, str],
            AdmittedPortValues,
        ],
    ) -> dict[str, Any] | None:
        stored_outputs: list[dict[str, Any]] = []
        for output in outputs:
            admitted = admitted_outputs[
                (node.node_id, output["output_port"])
            ]
            if (
                dict(admitted.port_type) != output["port_type"]
                or admitted.content_digest != output["content_digest"]
            ):
                raise RuntimeError(
                    "Published output diverged from its admission snapshot"
                )
            canonical_values = tuple(
                value.canonical_bytes for value in admitted.values
            )
            stored_outputs.append(
                {
                    "output_port": output["output_port"],
                    "port_type": output["port_type"],
                    "content_digest": output["content_digest"],
                    "encoded_values": [
                        base64.b64encode(encoded).decode("ascii")
                        for encoded in canonical_values
                    ],
                }
            )
        return {
            "schema_namespace": RESULT_CACHE_ENTRY_NAMESPACE,
            "result_identity": result_identity,
            "contract_metadata": _result_contract_metadata(
                node,
            ),
            "producer": {
                "producer_run_id": producer_run_id,
                "producer_node_id": node.node_id,
            },
            "outputs": stored_outputs,
        }

    @staticmethod
    def _conflicts(
        existing: Mapping[str, Any],
        proposed: Mapping[str, Any],
    ) -> bool:
        return any(
            existing[field] != proposed[field]
            for field in (
                "schema_namespace",
                "result_identity",
                "contract_metadata",
                "outputs",
            )
        )

    def validate_publish(
        self,
        *,
        project_id: str,
        execution_plan: ExecutionPlan,
        node: ExecutionPlanNode,
        result_identity: str,
        outputs: list[dict[str, Any]],
        producer_run_id: str,
        admitted_outputs: Mapping[
            tuple[str, str],
            AdmittedPortValues,
        ],
    ) -> None:
        entry = self._entry(
            execution_plan=execution_plan,
            node=node,
            result_identity=result_identity,
            outputs=outputs,
            producer_run_id=producer_run_id,
            admitted_outputs=admitted_outputs,
        )
        if entry is None:
            return None
        try:
            existing = self._load_entry(project_id, result_identity)
        except RecoverableCacheMiss:
            return None
        if existing is not None and self._conflicts(existing, entry):
            raise V2RunError(
                "cache_identity_conflict",
                "Result Identity resolves to conflicting outputs",
                details={"result_identity": result_identity},
            )

    def publish(
        self,
        *,
        project_id: str,
        execution_plan: ExecutionPlan,
        node: ExecutionPlanNode,
        result_identity: str,
        outputs: list[dict[str, Any]],
        producer_run_id: str,
        admitted_outputs: Mapping[
            tuple[str, str],
            AdmittedPortValues,
        ],
    ) -> Callable[[], None] | None:
        entry = self._entry(
            execution_plan=execution_plan,
            node=node,
            result_identity=result_identity,
            outputs=outputs,
            producer_run_id=producer_run_id,
            admitted_outputs=admitted_outputs,
        )
        if entry is None:
            return None
        try:
            existing = self._load_entry(project_id, result_identity)
        except RecoverableCacheMiss:
            return None
        if existing is not None:
            if self._conflicts(existing, entry):
                raise V2RunError(
                    "cache_identity_conflict",
                    "Result Identity resolves to conflicting outputs",
                    details={"result_identity": result_identity},
                )
            return None
        root = self._projects.cache_dir(project_id)
        try:
            created_path = write_private_new_file(
                root,
                self._relative_parts(result_identity),
                canonical_json_bytes(entry),
                field="result_cache_entry",
            )
        except FileExistsError:
            winner = self._load_entry(project_id, result_identity)
            if winner is None:
                return None
            if self._conflicts(winner, entry):
                raise V2RunError(
                    "cache_identity_conflict",
                    "Result Identity publication conflicted",
                    details={"result_identity": result_identity},
                )
            return None
        except (OSError, StoragePathError):
            return None

        def rollback_created_entry() -> None:
            try:
                encoded = _read_stable_private_file(
                    root,
                    self._relative_parts(result_identity),
                    field="result_cache_entry",
                    maximum_size=MAX_ARTIFACT_BYTES_PER_RUN,
                )
                if (
                    created_path.is_file()
                    and encoded == canonical_json_bytes(entry)
                ):
                    remove_private_regular_file(
                        root,
                        self._relative_parts(result_identity),
                        field="result_cache_entry",
                    )
            except (FileNotFoundError, OSError, StoragePathError):
                return

        return rollback_created_entry


class V2RunService:
    """Execute compiled direct Nodes behind readiness and durable evidence."""

    def __init__(
        self,
        projects: ProjectManager,
        catalog: FrozenCatalog,
        authoring: WorkflowAuthoringService,
        environment: EnvironmentConfiguration,
        result_replay_source: ResultReplaySource | None = None,
        ledger_transaction_store: LedgerTransactionStore | None = None,
    ) -> None:
        self._projects = projects
        self._catalog = catalog
        self._authoring = authoring
        self._environment = environment
        self._result_replay_source = (
            result_replay_source
            or _ProjectResultCache(projects, catalog)
        )
        self._object_store = ProjectObjectStore(projects)
        self._ledger_transaction_store = ledger_transaction_store
        self._runs: dict[tuple[str, str], _RunRecord] = {}
        self._damaged_runs: dict[tuple[str, str], str] = {}
        self._inactive_runs: dict[tuple[str, str], str] = {}
        self._unsupported_runs: dict[tuple[str, str], str] = {}
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
        return tuple(
            _PlanNodeEvidence(
                node.node_id,
                node._runtime.dependencies,
                node._runtime.required_dependencies,
                node.result_identity_plan_facts.digest,
                node.node_type.to_public(),
                node._runtime.artifact_outputs,
                bool(
                    node._runtime.selection_objectives
                    or node._runtime.observation_selectors
                ),
            )
            for node in plan.nodes
        )

    def _run_directories(self):
        project_root = self._projects.root_dir
        if not project_root.is_dir() or project_root.is_symlink():
            return
        for project_dir in sorted(project_root.iterdir()):
            if not project_dir.is_dir() or project_dir.is_symlink():
                continue
            try:
                project_id = validate_identifier(
                    project_dir.name,
                    "project_id",
                )
            except StoragePathError:
                continue
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
                ):
                    continue
                ledger = run_dir / "ledger"
                manifest = run_dir / "manifest.json"
                if (
                    not (
                        ledger.is_dir()
                        and not ledger.is_symlink()
                    )
                    and not (
                        manifest.is_file()
                        and not manifest.is_symlink()
                    )
                ):
                    continue
                try:
                    run_id = validate_identifier(run_dir.name, "run_id")
                except StoragePathError:
                    continue
                yield project_id, run_id, run_parent

    @staticmethod
    def _unsupported_run_version(
        run_parent: Path,
        run_id: str,
    ) -> str | None:
        """Classify an old schema without using it as current Run evidence."""
        run_dir = run_parent / run_id
        ledger_files = sorted((run_dir / "ledger").glob("*.json"))
        candidate = (
            ledger_files[0]
            if ledger_files
            else run_dir / "manifest.json"
        )
        if not candidate.is_file() or candidate.is_symlink():
            return None
        try:
            encoded = candidate.read_bytes()
            if len(encoded) > MAX_LEDGER_TRANSACTION_BYTES:
                return None
            payload = json.loads(encoded)
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, Mapping):
            return None
        observed = payload.get("schema_version")
        if observed == RUN_LEDGER_SCHEMA_VERSION:
            return None
        if isinstance(observed, (str, int)):
            return str(observed)[:64]
        return None if ledger_files else "unknown"

    def _load_persisted_runs(self) -> None:
        for project_id, run_id, run_parent in self._run_directories():
            unsupported_version = self._unsupported_run_version(
                run_parent,
                run_id,
            )
            if unsupported_version is not None:
                self._unsupported_runs[(project_id, run_id)] = (
                    unsupported_version
                )
                self._run_owners.setdefault(run_id, project_id)
                continue
            try:
                self._load_persisted_run(
                    project_id,
                    run_id,
                )
            except (
                ContractResolutionError,
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
    ) -> None:
        ledger = _read_run_evidence_ledger(
            self._projects,
            project_id,
            run_id,
            self._ledger_transaction_store,
        )
        if ledger is None:
            return
        if not ledger.started:
            return
        if (
            run_id in self._run_owners
            and self._run_owners[run_id] != project_id
        ):
            raise RuntimeError("Run identity appears in multiple Projects")
        persisted_catalog_digest = _validated_run_catalog_digest(
            ledger,
            self._catalog,
        )
        if persisted_catalog_digest != self._catalog.contract_digest:
            self._inactive_runs[(project_id, run_id)] = (
                persisted_catalog_digest
            )
            self._run_owners[run_id] = project_id
            return
        ledger.reconcile_restart(
            NodeAttemptFinalizer(
                ledger=ledger,
                result_replay_source=self._result_replay_source,
                materialize_artifacts=self._materialize_artifacts,
                object_store=self._object_store,
            )
        )
        try:
            ledger.rebuild_projections()
        except (OSError, StoragePathError):
            pass
        record = _RunRecord(
            compiled=None,
            ledger=ledger,
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
            unsupported_version = self._unsupported_runs.get(
                (project_id, run_id)
            )
            if unsupported_version is not None:
                raise V2RunError(
                    "unsupported_schema_version",
                    "Run evidence is not a supported exact v2 artifact",
                    details={
                        "artifact_kind": "run_evidence",
                        "expected_schema_version": RUN_LEDGER_SCHEMA_VERSION,
                        "received_schema_version": unsupported_version,
                    },
                ) from error
            inactive_catalog_digest = self._inactive_runs.get(
                (project_id, run_id)
            )
            if inactive_catalog_digest is not None:
                raise V2RunError(
                    "inactive_generation",
                    "Run evidence belongs to an inactive Catalog generation",
                    details={
                        "artifact_kind": "run_evidence",
                        "expected_catalog_contract_digest": (
                            self._catalog.contract_digest
                        ),
                        "received_catalog_contract_digest": (
                            inactive_catalog_digest
                        ),
                    },
                ) from error
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

    def _availability(
        self,
        node: ExecutionPlanNode,
    ) -> Mapping[str, Any]:
        binding_id = node.binding.contract_id
        version = node.binding.contract_version
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
                "binding": node.binding.to_public(),
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
        declaration = node._runtime.readiness_declaration
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
                    ReadinessCheckInput(environment.values, reusable)
                )
            except Exception as error:
                del error
                observed = ReadinessResult(
                    False,
                    proof_source="checker-failure",
                    reason_code="readiness_check_failed",
                )
            if isinstance(observed, ReadinessResult):
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
        node: ExecutionPlanNode,
        values: Mapping[
            tuple[str, str],
            AdmittedPortValues,
        ],
    ) -> tuple[
        dict[str, Any],
        Mapping[str, InputContentDigests],
    ]:
        declarations = {
            name: port.declaration
            for name, port in node._runtime.input_ports.items()
        }
        admitted_inputs: dict[str, list[Any]] = {}
        for port_name, sources in node._runtime.input_sources.items():
            for source_reference in sources:
                source = values.get(
                    (
                        source_reference.node_id,
                        source_reference.output_port,
                    )
                )
                if source is None or not source.values:
                    continue
                admitted_inputs.setdefault(port_name, []).extend(
                    source.values
                )

        inputs: dict[str, Any] = {}
        digests: dict[str, InputContentDigests] = {}
        for port_name, admitted in admitted_inputs.items():
            declaration = declarations[port_name]
            if declaration["multiplicity"] == "many":
                inputs[port_name] = tuple(
                    value.runtime_value for value in admitted
                )
            else:
                if len(admitted) != 1:
                    raise RuntimeError(
                        "Execution Plan one-valued input Port "
                        f"{port_name!r} resolved to {len(admitted)} "
                        "admitted values"
                    )
                inputs[port_name] = admitted[0].runtime_value
            digests[port_name] = InputContentDigests(
                port_type_id=declaration["port_type"]["contract_id"],
                value_content_digests=tuple(
                    value.content_digest for value in admitted
                ),
                candidate_data=tuple(
                    digest
                    for value in admitted
                    for digest in value.candidate_data
                ),
            )
        validate_candidate_input_identities(inputs, digests)
        return inputs, MappingProxyType(digests)

    def _resolve_project_inputs(
        self,
        project_id: str,
        node: ExecutionPlanNode,
    ) -> tuple[
        dict[str, tuple[Mapping[str, Any], bytes]],
        tuple[Mapping[str, Any], ...],
    ]:
        """Resolve declared Project resources before Result Identity lookup."""
        resolved: dict[str, tuple[Mapping[str, Any], bytes]] = {}
        identities: list[Mapping[str, Any]] = []
        for parameter_name in node._runtime.project_input_parameters:
            reference = node.node_parameters.get(parameter_name)
            if not isinstance(reference, str):
                raise PortValueError(
                    f"Project input parameter {parameter_name!r} is invalid"
                )
            try:
                descriptor, payload = self._projects.read_input(
                    project_id,
                    reference,
                )
            except ProjectInputIntegrityError as error:
                raise V2RunError(
                    "artifact_integrity_mismatch",
                    "Project Input integrity verification failed",
                    details={"artifact_reference": error.project_input_ref},
                ) from error
            resolved[reference] = (descriptor, payload)
            identities.append(
                {
                    "resource_kind": "project_input",
                    "parameter_name": parameter_name,
                    "content_digest": descriptor["content_digest"],
                    "size": descriptor["size"],
                }
            )
        return resolved, tuple(identities)

    def _required_input_blockers(
        self,
        node: ExecutionPlanNode,
        values: Mapping[tuple[str, str], AdmittedPortValues],
    ) -> list[str]:
        blockers: set[str] = set()
        for sources in node._runtime.required_input_sources.values():
            if any(
                values.get((source.node_id, source.output_port))
                for source in sources
            ):
                continue
            blockers.update(source.node_id for source in sources)
        return sorted(blockers)

    @staticmethod
    def _candidate_values(value: Any) -> list[Candidate]:
        if type(value) is Candidate:
            return [value]
        if type(value) is CandidateCollection:
            return list(value.items)
        if isinstance(value, (list, tuple)):
            return [
                candidate
                for item in value
                for candidate in V2RunService._candidate_values(item)
            ]
        return []

    def _normalize_candidate_outputs(
        self,
        *,
        plan: ExecutionPlan,
        node: ExecutionPlanNode,
        result_identity: str,
        inputs: Mapping[str, Any],
        outputs: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return normalize_scientific_outputs(
            node_id=node.node_id,
            result_identity=result_identity,
            inputs=inputs,
            outputs=outputs,
            candidate_content_digest=lambda candidate: (
                _candidate_data_content_digest(
                    plan._runtime.candidate_data_port_types,
                    candidate,
                )
            ),
            observation_propagation=(
                node._runtime.binding_contract.descriptor.get(
                    "observation_propagation"
                )
            ),
        )

    def _published_outputs(
        self,
        node: ExecutionPlanNode,
        admitted: Mapping[
            tuple[str, str],
            AdmittedPortValues,
        ],
    ) -> list[dict[str, Any]]:
        return [
            {
                "node_id": node.node_id,
                "output_port": output_port,
                "port_type": dict(snapshot.port_type),
                "content_digest": snapshot.content_digest,
            }
            for (node_id, output_port), snapshot in admitted.items()
            if node_id == node.node_id
        ]

    def _admit_outputs(
        self,
        plan: ExecutionPlan,
        node: ExecutionPlanNode,
        outputs: Any,
        *,
        inputs: Mapping[str, Any],
        input_content_digests: Mapping[str, InputContentDigests],
    ) -> tuple[
        list[dict[str, Any]],
        dict[tuple[str, str], AdmittedPortValues],
    ]:
        if not isinstance(outputs, Mapping):
            raise PortValueError("Direct implementation output must be an object")
        declared = {
            name: port.declaration
            for name, port in node._runtime.output_ports.items()
        }
        if set(outputs) - set(declared):
            raise PortValueError("Direct implementation returned unknown outputs")

        admitted: dict[tuple[str, str], AdmittedPortValues] = {}
        for port_name, declaration in declared.items():
            if declaration["required"] is True and port_name not in outputs:
                raise PortValueError(
                    f"Required output Port {port_name!r} is missing"
                )
            if port_name not in outputs:
                continue
            supplied = outputs[port_name]
            if (
                declaration["multiplicity"] == "many"
                and not isinstance(supplied, (list, tuple))
            ):
                raise PortValueError(
                    f"Output Port {port_name!r} requires many values"
                )
            values = (
                tuple(supplied)
                if declaration["multiplicity"] == "many"
                else (supplied,)
            )
            port_type = node._runtime.output_ports[port_name].port_type
            snapshot = admitted_port_values(
                port_type=port_type,
                multiplicity=declaration["multiplicity"],
                values=values,
                candidate_data=lambda value: _candidate_digests_for_value(
                    plan._runtime.candidate_data_port_types,
                    value,
                ),
            )
            if (
                port_type.type_id != "score.collection"
                and port_type.observation_method_projection is not None
            ):
                producing_method = _exact_reference(node.method)
                projected_methods = tuple(
                    method
                    for value in snapshot.runtime_values
                    for method in port_type.observation_method_references(value)
                )
                if any(
                    method != producing_method
                    for method in projected_methods
                ):
                    raise PortValueError(
                        "Output Observation Method projection does not equal "
                        "the producing Binding Method"
                    )
            admitted[(node.node_id, port_name)] = snapshot

        canonical_outputs = {
            port_name: (
                snapshot.runtime_values
                if snapshot.multiplicity == "many"
                else snapshot.values[0].runtime_value
            )
            for (node_id, port_name), snapshot in admitted.items()
            if node_id == node.node_id
        }
        axis_references: dict[tuple[str, str], tuple[Any, ...]] = {}
        method_references: dict[tuple[str, str], tuple[Any, ...]] = {}
        alignment_evidence_references: dict[
            tuple[str, str],
            tuple[Any, ...],
        ] = {}
        candidate_references: dict[
            tuple[str, str],
            tuple[CandidateDataReference, ...],
        ] = {}
        for resolved_metric in node._runtime.produced_metric_facts.values():
            evidence_contract = resolved_metric.structure_alignment_evidence
            if evidence_contract is None:
                continue
            direction = evidence_contract["source_direction"]
            source_port = evidence_contract["source_port"]
            key = (direction, source_port)
            if key in alignment_evidence_references:
                continue
            if direction == "input":
                port = node._runtime.input_ports.get(source_port)
                digest_record = input_content_digests.get(source_port)
                if (
                    port is None
                    or source_port not in inputs
                    or digest_record is None
                ):
                    raise PortValueError(
                        "Produced Observation alignment evidence input lacks "
                        "admitted identity evidence"
                    )
                raw_value = inputs[source_port]
                values = (
                    tuple(raw_value)
                    if port.declaration["multiplicity"] == "many"
                    else (raw_value,)
                )
                content_digests = digest_record.value_content_digests
            elif direction == "output":
                snapshot = admitted.get((node.node_id, source_port))
                if snapshot is None:
                    raise PortValueError(
                        "Produced Observation alignment evidence output was "
                        "not admitted"
                    )
                values = snapshot.runtime_values
                content_digests = tuple(
                    value.content_digest for value in snapshot.values
                )
            else:
                raise PortValueError(
                    "Produced Observation alignment evidence source direction "
                    "is invalid"
                )
            alignment_evidence_references[key] = (
                resolve_structure_alignment_evidence_admission_facts(
                    values,
                    content_digests,
                )
            )
        for declaration in node._runtime.binding_contract.descriptor.get(
            "produced_observations",
            (),
        ):
            for projection_kind, direction, source_port in (
                (
                    "axis",
                    declaration.get("axis_direction"),
                    declaration.get("axis_port"),
                ),
                (
                    "method",
                    declaration.get("method_direction"),
                    declaration.get("method_port"),
                ),
            ):
                if direction not in {"input", "output"} or not isinstance(
                    source_port, str
                ):
                    continue
                target = (
                    axis_references
                    if projection_kind == "axis"
                    else method_references
                )
                key = (direction, source_port)
                if key in target:
                    continue
                if direction == "input":
                    port = node._runtime.input_ports.get(source_port)
                    if (
                        port is None
                        or source_port not in input_content_digests
                    ):
                        raise PortValueError(
                            f"Declared input {projection_kind} Port lacks "
                            "admitted identity evidence"
                        )
                    raw_value = inputs.get(source_port)
                else:
                    port = node._runtime.output_ports.get(source_port)
                    snapshot = admitted.get((node.node_id, source_port))
                    if port is None or snapshot is None:
                        raise PortValueError(
                            f"Declared output {projection_kind} Port was not "
                            "admitted"
                        )
                    raw_value = canonical_outputs.get(source_port)
                if raw_value is None:
                    target[key] = ()
                    continue
                values = (
                    tuple(raw_value)
                    if port.declaration["multiplicity"] == "many"
                    else (raw_value,)
                )
                projected = tuple(
                    reference
                    for value in values
                    for reference in (
                        port.port_type.scientific_axis_references(value)
                        if projection_kind == "axis"
                        else port.port_type.observation_method_references(value)
                    )
                )
                if len(projected) != len(set(projected)):
                    raise PortValueError(
                        f"Declared {projection_kind} Port projected duplicate "
                        "exact references"
                    )
                target[key] = projected
        for declaration in node._runtime.binding_contract.descriptor.get(
            "produced_observations",
            (),
        ):
            for direction_name, port_name_key in (
                ("subject_direction", "subject_port"),
                ("reference_direction", "reference_port"),
            ):
                direction = declaration.get(direction_name)
                source_port = declaration.get(port_name_key)
                if direction not in {"input", "output"} or not isinstance(
                    source_port, str
                ):
                    continue
                key = (direction, source_port)
                if key in candidate_references:
                    continue
                if direction == "input":
                    evidence = input_content_digests.get(source_port)
                    if evidence is None:
                        raise PortValueError(
                            "Produced Observation Candidate source lacks "
                            "admitted identity evidence"
                        )
                    candidate_references[key] = tuple(
                        evidence.candidate_data
                    )
                else:
                    snapshot = admitted.get((node.node_id, source_port))
                    if snapshot is None:
                        raise PortValueError(
                            "Produced Observation output Candidate source was "
                            "not admitted"
                        )
                    candidate_references[key] = tuple(
                        reference
                        for value in snapshot.values
                        for reference in value.candidate_data
                    )
        for (node_id, port_name), snapshot in admitted.items():
            if (
                node_id != node.node_id
                or snapshot.port_type["contract_id"] != "score.collection"
            ):
                continue
            for value in snapshot.runtime_values:
                validate_produced_score_collection_from_facts(
                    binding_descriptor=(
                        node._runtime.binding_contract.descriptor
                    ),
                    output_port=port_name,
                    collection=value,
                    inputs=inputs,
                    outputs=canonical_outputs,
                    metric_facts=node._runtime.produced_metric_facts,
                    axis_references=axis_references,
                    method_references=method_references,
                    candidate_references=candidate_references,
                    alignment_evidence_references=(
                        alignment_evidence_references
                    ),
                )
        return self._published_outputs(node, admitted), admitted

    def _publish_artifact_payload(
        self,
        *,
        resources: RunResources,
        node_id: str,
        output_port: str,
        artifact_kind: str,
        payload: ArtifactPayload,
        accepted_media_types: tuple[str, ...],
        maximum_size: int,
    ) -> dict[str, Any]:
        if type(payload) is not ArtifactPayload:
            raise PortValueError(
                "Artifact publication requires one validated ArtifactPayload"
            )
        if (
            type(payload.body) is not bytes
            or len(payload.body) > min(MAX_ARTIFACT_SIZE_BYTES, maximum_size)
        ):
            raise PortValueError("Artifact payload exceeds the public bound")
        validate_relative_path(
            payload.filename,
            "artifact_filename",
            allow_nested=False,
        )
        if (
            not is_valid_artifact_media_type(payload.media_type)
            or payload.media_type not in accepted_media_types
        ):
            raise PortValueError(
                "Artifact media type is outside its nominal Port contract"
            )
        if artifact_kind == "standalone":
            if payload.candidate_id is not None:
                raise PortValueError(
                    "Standalone artifact cannot claim a Candidate identity"
                )
        elif artifact_kind == "candidate":
            try:
                validate_canonical_identifier(
                    payload.candidate_id,
                    "candidate_id",
                )
            except ValueError as error:
                raise PortValueError(
                    "Candidate artifact identity is invalid"
                ) from error
        else:
            raise PortValueError("Artifact kind is invalid")
        reference = f"artifact-{uuid.uuid4().hex}"
        stored = self._object_store.put_exact(
            resources.project_id,
            payload.body,
        )
        descriptor = {
            "artifact_reference": reference,
            "artifact_kind": artifact_kind,
            "node_id": node_id,
            "output_port": output_port,
            "media_type": payload.media_type,
            "filename": payload.filename,
            "size": stored.size,
            "content_digest": stored.content_digest,
        }
        if payload.candidate_id is not None:
            descriptor["candidate_id"] = payload.candidate_id
        validate_schema("#/$defs/ArtifactDescriptor", descriptor)
        return descriptor

    def _materialize_artifacts(
        self,
        *,
        node: ExecutionPlanNode,
        resources: RunResources,
        admitted_output_descriptors: list[dict[str, Any]],
        runtime: Mapping[tuple[str, str], AdmittedPortValues],
        current_artifact_count: int,
        current_artifact_bytes: int,
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]:
        typed_outputs: list[dict[str, Any]] = []
        artifact_index: list[dict[str, Any]] = []
        port_declarations = {
            name: port.declaration
            for name, port in node._runtime.output_ports.items()
        }
        artifact_sources: list[
            tuple[str, str, ArtifactPayload, tuple[str, ...]]
        ] = []
        for output in admitted_output_descriptors:
            declaration = port_declarations[output["output_port"]]
            artifact_kind = declaration.get("artifact_kind")
            if artifact_kind is None:
                port_type = node._runtime.output_ports[
                    output["output_port"]
                ].port_type
                if port_type.artifact_media_types is not None:
                    raise PortValueError(
                        "Artifact-capable output requires explicit publication "
                        "intent"
                    )
                typed_outputs.append(output)
                continue
            decoded_values = runtime[
                (node.node_id, output["output_port"])
            ].runtime_values
            port_type = node._runtime.output_ports[
                output["output_port"]
            ].port_type
            accepted_media_types = port_type.artifact_media_types
            if accepted_media_types is None:
                raise PortValueError(
                    "Artifact Port lacks a publication media contract"
                )
            declared_media_type = declaration.get("artifact_media_type")
            if declared_media_type not in accepted_media_types:
                raise PortValueError(
                    "Artifact Port media contract is invalid"
                )
            accepted_media_types = (declared_media_type,)
            for payload in decoded_values:
                if type(payload) is not ArtifactPayload:
                    raise PortValueError(
                        "Artifact output must contain ArtifactPayload values"
                    )
                artifact_sources.append(
                    (
                        output["output_port"],
                        artifact_kind,
                        payload,
                        accepted_media_types,
                    )
                )
        if (
            current_artifact_count + len(artifact_sources)
            > MAX_ARTIFACTS_PER_RUN
        ):
            raise PortValueError("Run artifact count exceeds the public bound")
        remaining_bytes = (
            MAX_ARTIFACT_BYTES_PER_RUN - current_artifact_bytes
        )
        for (
            output_port,
            artifact_kind,
            source,
            accepted_media_types,
        ) in artifact_sources:
            descriptor = self._publish_artifact_payload(
                resources=resources,
                node_id=node.node_id,
                output_port=output_port,
                artifact_kind=artifact_kind,
                payload=source,
                accepted_media_types=accepted_media_types,
                maximum_size=remaining_bytes,
            )
            remaining_bytes -= descriptor["size"]
            artifact_index.append(descriptor)
        return typed_outputs, artifact_index

    def start(
        self,
        project_id: str,
        *,
        workflow_commit_id: str,
        client_request_id: str,
        _on_admitted: Callable[
            [dict[str, Any], _RunRecord],
            None,
        ]
        | None = None,
        _before_execute: Callable[[], None] | None = None,
        _derived_from: Mapping[str, Any] | None = None,
        _cache_bypass_nodes: frozenset[str] = frozenset(),
        _retained_compiled: CompiledWorkflow | None = None,
    ) -> dict[str, Any]:
        del client_request_id
        if _retained_compiled is None:
            compiled = self._authoring.require_compiled(
                project_id,
                workflow_commit_id=workflow_commit_id,
            )
        else:
            compiled = _retained_compiled
        plan = compiled.execution_plan
        workflow_commit_revision = plan.workflow_commit_revision
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
                            "field_path": ["workflow_commit_id"],
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
                self._ledger_transaction_store,
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
            "workflow_commit_id": workflow_commit_id,
            "workflow_commit_revision": workflow_commit_revision,
            "workflow_digest": plan.workflow_digest,
            "contract_lock_digest": plan.contract_lock_digest,
            "execution_plan_digest": plan.execution_plan_digest,
            "catalog_contract_digest": plan.catalog_contract_digest,
            "resolved_contract_roots": _execution_plan_contract_roots(plan),
            "resolved_contracts": [
                entry.to_public()
                for entry in plan.resolved_contracts
            ],
            "selection_required": any(
                node.selection_consumer for node in plan_evidence
            ),
            "selection_terminal_keys": list(
                node.node_id
                for node in plan_evidence
                if node.selection_consumer
            ),
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
        for node in distinct.values():
            availability = self._availability(node)
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
                "workflow_commit_id": workflow_commit_id,
                "workflow_commit_revision": workflow_commit_revision,
            },
        )
        ledger.append("run_started", {"started_at": run_timestamp()})

        all_artifacts: list[dict[str, Any]] = []
        record = _RunRecord(
            compiled=compiled,
            ledger=ledger,
        )
        finalizer = NodeAttemptFinalizer(
            ledger=ledger,
            result_replay_source=self._result_replay_source,
            materialize_artifacts=self._materialize_artifacts,
            object_store=self._object_store,
        )

        self._runs[(project_id, run_id)] = record
        self._run_owners[run_id] = project_id
        receipt = {
            "project_id": project_id,
            "run_id": run_id,
            "workflow_commit_id": workflow_commit_id,
            "workflow_commit_revision": workflow_commit_revision,
            "admitted_sequence": admitted["sequence"],
            "event_cursor": ledger.cursor_at(admitted["sequence"]),
        }
        if _on_admitted is not None:
            _on_admitted(receipt, record)
        if _before_execute is not None:
            _before_execute()
        values: dict[tuple[str, str], AdmittedPortValues] = {}
        disposition_outcomes: dict[str, str] = {}
        for node in plan.nodes:
            if ledger.cancellation_requested:
                record.cancellation.wait_for_cleanup()
                cancellation_outcome = (
                    "interrupted"
                    if record.cancellation.cleanup_error is not None
                    else "cancelled"
                )
                finalized = finalizer.finalize(
                    CancelledOrInterruptedNode(
                        node_id=node.node_id,
                        status=cancellation_outcome,
                        public_error=None,
                    )
                )
                disposition_outcomes[node.node_id] = finalized.disposition
                continue
            blocked_by = self._required_input_blockers(
                node,
                values,
            )
            if blocked_by:
                finalized = finalizer.conclude(
                    BlockedNode(
                        node_id=node.node_id,
                        blocked_by=tuple(blocked_by),
                    )
                )
                disposition_outcomes[node.node_id] = finalized.disposition
                continue
            node_attempt_id = f"node-attempt-{uuid.uuid4().hex}"
            operation_attempt_id = f"operation-{uuid.uuid4().hex}"
            node_inputs: dict[str, Any] = {}
            input_content_digests: Mapping[
                str,
                InputContentDigests,
            ] = MappingProxyType({})
            input_admission_error: PortValueError | None = None
            try:
                node_inputs, input_content_digests = self._inputs_for(
                    node,
                    values,
                )
            except PortValueError as error:
                input_admission_error = error
            binding_contract = node._runtime.binding_contract
            project_inputs: dict[
                str,
                tuple[Mapping[str, Any], bytes],
            ] = {}
            resource_identities: tuple[Mapping[str, Any], ...] = ()
            resource_resolution_error: BaseException | None = None
            if input_admission_error is None:
                try:
                    (
                        project_inputs,
                        resource_identities,
                    ) = self._resolve_project_inputs(project_id, node)
                except BaseException as error:
                    resource_resolution_error = error
            effective_randomness_snapshot: (
                _EffectiveRandomnessSnapshot | None
            ) = None
            randomness_resolution_error: BaseException | None = None
            if (
                input_admission_error is None
                and resource_resolution_error is None
            ):
                try:
                    effective_randomness_snapshot = (
                        _resolve_effective_randomness(
                            node,
                            node_inputs,
                        )
                    )
                except BaseException as error:
                    randomness_resolution_error = error
            result_identity: str | None = None
            cache_eligible = (
                input_admission_error is None
                and resource_resolution_error is None
                and randomness_resolution_error is None
                and effective_randomness_snapshot is not None
                and binding_contract.descriptor.get("cacheable") is True
                and binding_contract.descriptor.get("deterministic") is True
                and _result_identity_is_cache_safe(
                    node,
                    node_inputs,
                    input_content_digests=input_content_digests,
                    resolved_resource_inputs=resource_identities,
                    effective_randomness_snapshot=(
                        effective_randomness_snapshot
                    ),
                )
            )
            cache_lookup_eligible = (
                cache_eligible and node.node_id not in _cache_bypass_nodes
            )
            if cache_eligible:
                result_identity = _result_identity(
                    node,
                    node_inputs,
                    input_content_digests=input_content_digests,
                    resolved_resource_inputs=resource_identities,
                    effective_randomness_snapshot=(
                        effective_randomness_snapshot
                    ),
                )
            replayed_published: list[dict[str, Any]] | None = None
            replayed_runtime: dict[
                tuple[str, str],
                AdmittedPortValues,
            ] | None = None
            replay_producer_run_id: str | None = None
            cache_lookup_error: V2RunError | None = None
            if cache_lookup_eligible and result_identity is not None:
                try:
                    replayed = self._result_replay_source.lookup(
                        project_id=project_id,
                        execution_plan=plan,
                        node=node,
                        inputs=node_inputs,
                        result_identity=result_identity,
                    )
                    if isinstance(replayed, ResultReplayHit):
                        if replayed.result_identity != result_identity:
                            raise V2RunError(
                                "cache_identity_conflict",
                                "Cache replay returned a conflicting identity",
                                details={
                                    "result_identity": result_identity,
                                },
                            )
                        replayed_admitted = replayed.admitted_outputs
                        replay_producer_run_id = replayed.producer_run_id
                        try:
                            validate_identifier(
                                replay_producer_run_id,
                                "producer_run_id",
                            )
                        except StoragePathError as error:
                            raise V2RunError(
                                "cache_identity_conflict",
                                "Cache replay producer provenance is invalid",
                                details={
                                    "result_identity": result_identity,
                                },
                            ) from error
                    elif replayed is None:
                        replayed_admitted = None
                    else:
                        raise V2RunError(
                            "cache_identity_conflict",
                            "Cache replay lacks identity-bound provenance",
                            details={"result_identity": result_identity},
                        )
                    if replayed_admitted is not None:
                        candidate_runtime = dict(replayed_admitted)
                        replayed_published = self._published_outputs(
                            node,
                            candidate_runtime,
                        )
                        replayed_runtime = candidate_runtime
                except RecoverableCacheMiss:
                    replayed_published = None
                    replayed_runtime = None
                except V2RunError as error:
                    cache_lookup_error = error
                except Exception as error:
                    cache_lookup_error = V2RunError(
                        "node_execution_failed",
                        "Cache replay failed before Provider execution",
                        details={"exception_type": type(error).__name__},
                    )
            if cache_lookup_error is not None:
                ledger.append(
                    "node_attempt_started",
                    {
                        "node_id": node.node_id,
                        "node_attempt_id": node_attempt_id,
                    },
                )
                finalized = finalizer.finalize(
                    ExecutedNodeNonSuccess(
                        node_id=node.node_id,
                        node_attempt_id=node_attempt_id,
                        operation_attempt_id=None,
                        status="failed",
                        public_error=_public_failure(cache_lookup_error),
                    )
                )
                disposition_outcomes[node.node_id] = finalized.disposition
                continue
            if replayed_published is not None and replayed_runtime is not None:
                if ledger.cancellation_requested:
                    cancellation_outcome = (
                        "interrupted"
                        if record.cancellation.cleanup_error is not None
                        else "cancelled"
                    )
                    finalized = finalizer.finalize(
                        CancelledOrInterruptedNode(
                            node_id=node.node_id,
                            status=cancellation_outcome,
                            public_error=None,
                        )
                    )
                    disposition_outcomes[node.node_id] = finalized.disposition
                    continue
                ledger.append(
                    "node_attempt_started",
                    {
                        "node_id": node.node_id,
                        "node_attempt_id": node_attempt_id,
                    },
                )
                replay_resources = RunResources(
                    project_id=project_id,
                    run_id=run_id,
                    node_id=node.node_id,
                    _projects=self._projects,
                    _cancellation_control=record.cancellation,
                )
                finalized = finalizer.finalize(
                    CacheReplayNodeSuccess(
                        project_id=project_id,
                        run_id=run_id,
                        execution_plan=plan,
                        node=node,
                        resources=replay_resources,
                        node_attempt_id=node_attempt_id,
                        result_identity=result_identity,
                        producer_run_id=cast(str, replay_producer_run_id),
                        admitted_output_descriptors=tuple(replayed_published),
                        admitted_outputs=replayed_runtime,
                        current_artifact_count=len(all_artifacts),
                        current_artifact_bytes=sum(
                            artifact["size"] for artifact in all_artifacts
                        ),
                    )
                )
                if finalized.disposition == "succeeded":
                    values.update(finalized.admitted_outputs)
                    all_artifacts.extend(finalized.artifacts)
                disposition_outcomes[node.node_id] = finalized.disposition
                continue
            resources = RunResources(
                project_id=project_id,
                run_id=run_id,
                node_id=node.node_id,
                _projects=self._projects,
                _invocation_recorder=_OperationInvocationRecorder(
                    ledger=ledger,
                    operation_attempt_id=operation_attempt_id,
                    default_engine_identity=node.method.contract_digest,
                ),
                _cancellation_control=record.cancellation,
                _project_inputs=project_inputs,
                _project_input_identities=resource_identities,
            )
            body_error: BaseException | None = (
                input_admission_error
                or resource_resolution_error
                or randomness_resolution_error
            )
            implementation: Any | None = None
            operation_execute: Callable[[OperationCall], Mapping[str, Any]] | None = None
            operation_call: OperationCall | None = None
            try:
                if body_error is None:
                    assert effective_randomness_snapshot is not None
                    operation_call = OperationCall(
                        inputs=node_inputs,
                        node_parameters=(
                            effective_randomness_snapshot.node_parameters
                        ),
                        binding_parameters=(
                            effective_randomness_snapshot.binding_parameters
                        ),
                        input_content_digests=input_content_digests,
                    )
                    environment = self._environment.for_binding(
                        node.binding.contract_id,
                        node.binding.contract_version,
                    )
                    implementation = node._runtime.factory.build(
                        OperationContext(
                            method=_exact_reference(node.method),
                            produced_observations=(
                                node._runtime.produced_observations
                            ),
                            selection_objectives=(
                                node._runtime.selection_objectives
                            ),
                            observation_selectors=(
                                node._runtime.observation_selectors
                            ),
                            environment=environment.values,
                            resources=resources,
                        )
                    )
                    execute_candidate = getattr(implementation, "execute", None)
                    if not callable(execute_candidate):
                        raise TypeError(
                            "Scientific Operation factory must return an "
                            "object with callable execute(OperationCall)"
                        )
                    operation_execute = execute_candidate
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
                finalized = finalizer.finalize(
                    CancelledOrInterruptedNode(
                        node_id=node.node_id,
                        status=disposition_outcome,
                        public_error=None,
                    )
                )
                disposition_outcomes[node.node_id] = finalized.disposition
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
                finalized = finalizer.finalize(
                    CancelledOrInterruptedNode(
                        node_id=node.node_id,
                        status=cancellation_outcome,
                        public_error=None,
                    )
                )
                disposition_outcomes[node.node_id] = finalized.disposition
                continue
            ledger.append(
                "node_attempt_started",
                {
                    "node_id": node.node_id,
                    "node_attempt_id": node_attempt_id,
                },
            )
            pending_runtime: dict[
                tuple[str, str],
                AdmittedPortValues,
            ] = {}
            pending_published: list[dict[str, Any]] = []
            operation_started = False

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
                operation_started = True
                assert implementation is not None
                assert operation_execute is not None
                assert operation_call is not None
                assert effective_randomness_snapshot is not None
                raw_outputs = operation_execute(operation_call)
                if ledger.cancellation_requested:
                    raise ExecutionTermination("cancelled")
                if result_identity is None:
                    result_identity = _result_identity(
                        node,
                        node_inputs,
                        input_content_digests=input_content_digests,
                        resolved_resource_inputs=(
                            resources.result_identity_inputs
                        ),
                        effective_randomness_snapshot=(
                            effective_randomness_snapshot
                        ),
                    )
                if isinstance(raw_outputs, Mapping):
                    raw_outputs = self._normalize_candidate_outputs(
                        plan=plan,
                        node=node,
                        result_identity=result_identity,
                        inputs=node_inputs,
                        outputs=raw_outputs,
                    )
                pending_published, pending_runtime = self._admit_outputs(
                    plan,
                    node,
                    raw_outputs,
                    inputs=node_inputs,
                    input_content_digests=input_content_digests,
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
                public_error = _public_failure(body_error)
                if terminal_status == "failed":
                    intent: NodeFinalizationIntent = ExecutedNodeNonSuccess(
                        node_id=node.node_id,
                        node_attempt_id=node_attempt_id,
                        operation_attempt_id=(
                            operation_attempt_id if operation_started else None
                        ),
                        status=terminal_status,
                        public_error=public_error,
                    )
                else:
                    intent = CancelledOrInterruptedNode(
                        node_id=node.node_id,
                        status=terminal_status,
                        public_error=public_error,
                        node_attempt_id=node_attempt_id,
                        operation_attempt_id=(
                            operation_attempt_id if operation_started else None
                        ),
                    )
                finalized = finalizer.finalize(intent)
                disposition_outcomes[node.node_id] = finalized.disposition
                continue
            assert result_identity is not None
            finalized = finalizer.finalize(
                ExecutedNodeSuccess(
                    project_id=project_id,
                    run_id=run_id,
                    execution_plan=plan,
                    node=node,
                    resources=resources,
                    node_attempt_id=node_attempt_id,
                    operation_attempt_id=operation_attempt_id,
                    result_identity=result_identity,
                    admitted_output_descriptors=tuple(pending_published),
                    admitted_outputs=pending_runtime,
                    cache_eligible=cache_eligible,
                    current_artifact_count=len(all_artifacts),
                    current_artifact_bytes=sum(
                        artifact["size"] for artifact in all_artifacts
                    ),
                )
            )
            if finalized.disposition == "succeeded":
                values.update(finalized.admitted_outputs)
                all_artifacts.extend(finalized.artifacts)
            disposition_outcomes[node.node_id] = finalized.disposition
        selection_failed = False
        selection_consumers = tuple(
            node
            for node in plan.nodes
            if (
                node._runtime.selection_objectives
                or node._runtime.observation_selectors
            )
        )
        if (
            selection_consumers
            and all(
                outcome == "succeeded"
                for outcome in disposition_outcomes.values()
            )
        ):
            try:
                results = tuple(
                    _selection_consumer_result(node, values)
                    for node in selection_consumers
                )
                for result in results:
                    if result is None:
                        raise RuntimeError(
                            "Selection consumer lacks an exact result"
                        )
                    ledger.append(
                        "selection_terminal",
                        {
                            "status": "succeeded",
                            "result": result,
                        },
                    )
            except Exception as error:
                selection_failed = True
                ledger.append(
                    "selection_terminal",
                    {
                        "status": "failed",
                        "error": _public_selection_failure(error),
                    },
                )
        run_status = (
            "failed"
            if selection_failed or "failed" in disposition_outcomes.values()
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
        workflow_commit_id: str,
        client_request_id: str,
        _derived_from: Mapping[str, Any] | None = None,
        _cache_bypass_nodes: frozenset[str] = frozenset(),
        _retained_compiled: CompiledWorkflow | None = None,
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
                    workflow_commit_id=workflow_commit_id,
                    client_request_id=client_request_id,
                    _on_admitted=on_admitted,
                    _before_execute=acquire_execution_slot,
                    _derived_from=_derived_from,
                    _cache_bypass_nodes=_cache_bypass_nodes,
                    _retained_compiled=_retained_compiled,
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
            for node in plan.nodes:
                if (
                    node.node_id not in forced
                    and any(
                        dependency in forced
                        for dependency in node._runtime.dependencies
                    )
                ):
                    forced.add(node.node_id)
                    changed = True
        return frozenset(forced)

    def start_derived_background(
        self,
        project_id: str,
        *,
        source_run_id: str,
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
        compiled = source.compiled
        if compiled is None:
            raise V2RunError(
                "compile_rejected",
                "Derived Run source Execution Plan is unavailable",
                details={
                    "issues": [
                        {
                            "code": "source_execution_plan_unavailable",
                            "severity": "error",
                            "message": (
                                "Derived Run requires the exact in-memory "
                                "Execution Plan retained by its source Run"
                            ),
                            "field_path": ["source_run_id"],
                        }
                    ]
                },
            )
        plan = compiled.execution_plan
        source_scope = source.ledger.facts[0]["payload"]
        if (
            plan.workflow_commit_revision
            != source_projection["workflow_commit_revision"]
            or plan.workflow_digest
            != source_projection["workflow_digest"]
            or source_scope["workflow_commit_id"]
            != source_projection["workflow_commit_id"]
            or plan.contract_lock_digest
            != source_scope["contract_lock_digest"]
            or plan.execution_plan_digest
            != source_scope["execution_plan_digest"]
            or plan.catalog_contract_digest
            != source_scope["catalog_contract_digest"]
        ):
            raise V2RunError(
                "contract_digest_mismatch",
                "Retained Execution Plan no longer matches the source Run",
                details={
                    "issues": [
                        {
                            "code": "source_execution_plan_identity_mismatch",
                            "severity": "error",
                            "message": (
                                "Derived Run requires the exact immutable "
                                "source Execution Plan identity"
                            ),
                            "field_path": ["source_run_id"],
                        }
                    ]
                },
            )
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
            workflow_commit_id=source_projection["workflow_commit_id"],
            client_request_id=client_request_id,
            _derived_from={
                "source_run_id": source_run_id,
                "policy": policy,
                "selected_node_ids": selected_in_plan_order,
                "forced_node_ids": forced_in_plan_order,
            },
            _cache_bypass_nodes=forced,
            _retained_compiled=compiled,
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

    @staticmethod
    def _typed_value_integrity_error(
        descriptor: Mapping[str, Any],
        value_index: int,
        *,
        expected_digest: str,
        expected_size: int | None = None,
    ) -> V2RunError:
        details: dict[str, Any] = {
            "node_id": descriptor["node_id"],
            "output_port": descriptor["output_port"],
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
        """Resolve one exact canonical value through committed Run evidence."""
        record = self._require_record(project_id, run_id)
        descriptor = next(
            (
                output
                for output in record.ledger.projection()["outputs"]
                if output["node_id"] == node_id
                and output["output_port"] == output_port
            ),
            None,
        )
        if (
            descriptor is None
            or type(value_index) is not int
            or value_index < 0
            or value_index >= descriptor["value_count"]
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
        manifest_reference = descriptor["value_manifest_reference"]
        try:
            encoded_manifest = self._object_store.read_bounded(
                project_id,
                manifest_reference,
                maximum_size=MAX_PORT_VALUE_MANIFEST_BYTES,
            )
            manifest = json.loads(encoded_manifest)
            if encoded_manifest != canonical_json_bytes(manifest):
                raise ValueError("Port Value Manifest is not canonical")
            if (
                not isinstance(manifest, Mapping)
                or set(manifest)
                != {
                    "schema_namespace",
                    "port_type",
                    "multiplicity",
                    "content_digest",
                    "value_count",
                    "values",
                }
                or manifest["schema_namespace"]
                != PORT_VALUE_MANIFEST_NAMESPACE
                or manifest["port_type"] != descriptor["port_type"]
                or manifest["content_digest"]
                != descriptor["content_digest"]
                or manifest["value_count"] != descriptor["value_count"]
                or not isinstance(manifest["values"], list)
                or len(manifest["values"]) != descriptor["value_count"]
            ):
                raise ValueError("Port Value Manifest contract is invalid")
            entry = manifest["values"][value_index]
            if (
                not isinstance(entry, Mapping)
                or set(entry)
                != {
                    "index",
                    "content_digest",
                    "size",
                    "object",
                }
                or entry["index"] != value_index
                or type(entry["size"]) is not int
                or entry["size"] < 0
                or not isinstance(entry["object"], Mapping)
                or dict(entry["object"])
                != {
                    "content_digest": entry["content_digest"],
                    "size": entry["size"],
                }
            ):
                raise ValueError("Port Value Manifest entry is invalid")
        except (
            ObjectIntegrityError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ) as error:
            raise self._typed_value_integrity_error(
                descriptor,
                value_index,
                expected_digest=manifest_reference,
            ) from error
        try:
            payload = self._object_store.read_exact(
                project_id,
                entry["content_digest"],
                size=entry["size"],
            )
        except ObjectIntegrityError as error:
            raise self._typed_value_integrity_error(
                descriptor,
                value_index,
                expected_digest=entry["content_digest"],
                expected_size=entry["size"],
            ) from error
        metadata = {
            "typed_value": {
                "node_id": node_id,
                "output_port": output_port,
                "port_type": descriptor["port_type"],
                "port_content_digest": descriptor["content_digest"],
                "value_manifest_reference": manifest_reference,
                "value_index": value_index,
                "value_count": descriptor["value_count"],
                "value_content_digest": entry["content_digest"],
                "size": entry["size"],
            }
        }
        return json.loads(json.dumps(metadata)), payload

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
        try:
            payload = self._object_store.read_exact(
                project_id,
                descriptor["content_digest"],
                size=descriptor["size"],
            )
        except ObjectIntegrityError as error:
            raise V2RunError(
                "artifact_integrity_mismatch",
                "Artifact integrity validation failed",
                details={"artifact_reference": artifact_reference},
            ) from error
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
