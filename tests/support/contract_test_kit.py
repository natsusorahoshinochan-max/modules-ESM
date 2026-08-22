"""Test-only executable conformance contracts for v2 Module Packages."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from types import MappingProxyType
from typing import Any

from core.catalog.builder import (
    build_frozen_catalog,
)
from core.catalog.declarations import (
    ModulePackageRegistration,
)
from core.catalog.port_contract import (
    CatalogBuildError,
    PortValueError,
)
from core.project.manager import ProjectManager
from core.scoring.selection import ObservationSelector, SelectionObjective
from core.execution.environment import admit_environment_configuration
from core.execution.ledger import PublishedOutput
from protein_workbench_public.ledger_codec import (
    encode_event,
    encode_run_projection,
)
from core.execution.node_attempt import NodeAttemptFactory
from core.execution.runtime import (
    V2RunError,
    V2RunService,
)
from tests.support.result_store import result_store
from core.workflow.authoring import (
    WorkflowAuthoringError,
    WorkflowAuthoringService,
)
from core.workflow.document import (
    WorkflowDocument,
    WorkflowEdge,
    WorkflowNodeInstance,
)
from datatypes.candidate import CandidateCollection
from datatypes.observation import (
    ScoreCollection,
    ScoreObservation,
)


_CANONICAL_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_CASE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class ModulePackageConformanceError(AssertionError):
    """A production registration failed one shared maintainer contract."""


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(value))


@dataclass(frozen=True, slots=True)
class ModulePackagePortCase:
    """Independent representative values for one package-owned Port Type."""

    type_id: str
    version: str
    valid_value: Any = field(compare=False)
    invalid_values: tuple[Any, ...] = field(default=(), compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "invalid_values", tuple(self.invalid_values))


@dataclass(frozen=True, slots=True)
class ModulePackageContractCase:
    """One minimal Workflow supplied separately from production registration."""

    case_id: str
    node_type_id: str
    node_type_version: str
    binding_id: str
    binding_version: str
    node_parameters: Mapping[str, Any]
    binding_parameters: Mapping[str, Any]
    environment_values: Mapping[str, Any]
    workflow_nodes: tuple[WorkflowNodeInstance, ...] = ()
    workflow_edges: tuple[WorkflowEdge, ...] = ()
    observation_selectors: tuple[ObservationSelector, ...] = ()
    selection_objectives: tuple[SelectionObjective, ...] = ()
    project_inputs: Mapping[str, bytes] = field(default_factory=dict)
    expected_scalar_outputs: Mapping[str, Any] = field(default_factory=dict)
    expected_candidate_counts: Mapping[str, int] = field(default_factory=dict)
    expected_observation_counts: Mapping[str, int] = field(default_factory=dict)
    expected_artifacts: Mapping[str, bytes] = field(default_factory=dict)
    forbidden_public_fragments: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.case_id, str)
            or _CASE_IDENTIFIER.fullmatch(self.case_id) is None
        ):
            raise ModulePackageConformanceError(
                "case_id must be one safe path segment"
            )
        for name in (
            "node_parameters",
            "binding_parameters",
            "environment_values",
            "project_inputs",
            "expected_scalar_outputs",
            "expected_candidate_counts",
            "expected_observation_counts",
            "expected_artifacts",
        ):
            value = getattr(self, name)
            if not isinstance(value, Mapping):
                raise ModulePackageConformanceError(
                    f"{name} must be an independent mapping"
                )
            object.__setattr__(self, name, _freeze_mapping(value))
        object.__setattr__(
            self,
            "observation_selectors",
            tuple(self.observation_selectors),
        )
        object.__setattr__(
            self,
            "forbidden_public_fragments",
            tuple(self.forbidden_public_fragments),
        )
        object.__setattr__(self, "workflow_nodes", tuple(self.workflow_nodes))
        object.__setattr__(self, "workflow_edges", tuple(self.workflow_edges))
        object.__setattr__(
            self,
            "selection_objectives",
            tuple(self.selection_objectives),
        )
        if any(
            not isinstance(node, WorkflowNodeInstance)
            for node in self.workflow_nodes
        ) or any(
            not isinstance(edge, WorkflowEdge)
            for edge in self.workflow_edges
        ) or any(
            not isinstance(selector, ObservationSelector)
            for selector in self.observation_selectors
        ) or any(
            not isinstance(objective, SelectionObjective)
            for objective in self.selection_objectives
        ):
            raise ModulePackageConformanceError(
                "workflow Nodes, Edges, Observation Selectors, and Selection "
                "Objectives must use "
                "v2 Workflow types"
            )
        if any(
            not isinstance(reference, str) or type(payload) is not bytes
            for reference, payload in self.project_inputs.items()
        ):
            raise ModulePackageConformanceError(
                "project_inputs must map opaque references to bytes"
            )


@dataclass(frozen=True, slots=True)
class ModulePackageCaseReport:
    """Bounded safe evidence for one executed conformance case."""

    case_id: str
    status: str
    result_identities: tuple[str, ...]
    output_ports: tuple[str, ...]
    artifact_ports: tuple[str, ...]
    event_sequences: tuple[int, ...]
    event_types: tuple[str, ...]

    def to_public(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "status": self.status,
            "result_identities": list(self.result_identities),
            "output_ports": list(self.output_ports),
            "artifact_ports": list(self.artifact_ports),
            "event_sequences": list(self.event_sequences),
            "event_types": list(self.event_types),
        }


@dataclass(frozen=True, slots=True)
class ModulePackageContractReport:
    """Safe summary proving one registration against the shared kit."""

    package_id: str
    package_version: str
    catalog_contract_digest: str
    case_reports: tuple[ModulePackageCaseReport, ...]
    verified_port_types: tuple[str, ...]

    def to_public(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id,
            "package_version": self.package_version,
            "catalog_contract_digest": self.catalog_contract_digest,
            "case_reports": [
                report.to_public() for report in self.case_reports
            ],
            "verified_port_types": list(self.verified_port_types),
        }


def _decode_published_value(
    catalog: Any,
    output: PublishedOutput,
    canonical_bytes: bytes,
) -> Any:
    reference = output.port_type
    port_type = catalog.require_port_type(
        reference.contract_id,
        reference.contract_version,
    )
    return port_type.decode(canonical_bytes)


def _verify_port_cases(
    catalog: Any,
    registration: ModulePackageRegistration,
    cases: Sequence[ModulePackagePortCase],
) -> tuple[str, ...]:
    owned = {
        (definition.type_id, definition.version)
        for definition in registration.port_types
    }
    supplied = {(case.type_id, case.version) for case in cases}
    if len(supplied) != len(cases) or supplied != owned:
        raise ModulePackageConformanceError(
            "Port cases must cover every package-owned Port Type exactly once"
        )
    verified: list[str] = []
    for case in cases:
        identity = (case.type_id, case.version)
        if identity not in owned:
            raise ModulePackageConformanceError(
                f"Port case references a type not owned by {registration.package_id}"
            )
        port_type = catalog.require_port_type(*identity)
        try:
            encoded = port_type.encode(case.valid_value)
            decoded = port_type.decode(encoded)
            if decoded != case.valid_value or port_type.encode(decoded) != encoded:
                raise ModulePackageConformanceError(
                    f"{case.type_id}@{case.version} codec is not canonical "
                    "and round-trippable"
                )
            for invalid in case.invalid_values:
                try:
                    port_type.encode(invalid)
                except PortValueError:
                    continue
                raise ModulePackageConformanceError(
                    f"{case.type_id}@{case.version} accepted an invalid value"
                )
        except (CatalogBuildError, PortValueError) as error:
            raise ModulePackageConformanceError(
                f"{case.type_id}@{case.version} codec conformance failed"
            ) from error
        verified.append(f"{case.type_id}@{case.version}")
    return tuple(sorted(verified))


def _verify_execution_case_coverage(
    catalog: Any,
    registration: ModulePackageRegistration,
    cases: Sequence[ModulePackageContractCase],
) -> None:
    owned_keys = {
        key
        for key, owners in catalog.owners.items()
        if registration.package_id in owners
    }
    expected_nodes = {
        (contract_id, version)
        for kind, contract_id, version in owned_keys
        if kind == "node_type"
    }
    expected_bindings = {
        (contract_id, version)
        for kind, contract_id, version in owned_keys
        if kind == "binding"
    }
    covered_nodes = {
        (case.node_type_id, case.node_type_version)
        for case in cases
    }
    covered_bindings = {
        (case.binding_id, case.binding_version)
        for case in cases
    }
    if covered_nodes != expected_nodes:
        raise ModulePackageConformanceError(
            "Execution cases must cover every package-owned Node Definition"
        )
    if covered_bindings != expected_bindings:
        raise ModulePackageConformanceError(
            "Execution cases must cover every package-owned Binding"
        )


def _availability_is_green(
    catalog: Any,
    binding_id: str,
    binding_version: str,
) -> bool:
    return any(
        snapshot.binding.contract_id == binding_id
        and snapshot.binding.contract_version == binding_version
        and snapshot.result.is_available
        for snapshot in catalog.availability
    )


def _verify_case(
    *,
    catalog: Any,
    case: ModulePackageContractCase,
    root: Path,
) -> ModulePackageCaseReport:
    if not _availability_is_green(
        catalog,
        case.binding_id,
        case.binding_version,
    ):
        raise ModulePackageConformanceError(
            f"{case.case_id} selected an unavailable Binding"
        )
    project_manager = ProjectManager(
        root / "projects",
        cache_root=root / "cache",
        output_root=root / "outputs",
        run_root=root / "runs",
    )
    project = project_manager.create(f"Contract Test Kit: {case.case_id}")
    for reference, payload in case.project_inputs.items():
        project_manager.publish_input(
            project.id,
            reference,
            payload,
            filename=reference,
        )
    authoring = WorkflowAuthoringService(project_manager, catalog)
    workflow = WorkflowDocument(
        schema_version="2.1.0",
        workflow_id=project.id,
        nodes=(
            *case.workflow_nodes,
            WorkflowNodeInstance(
                node_id="contract-test-node",
                node_type_id=case.node_type_id,
                node_type_version=case.node_type_version,
                binding_id=case.binding_id,
                binding_version=case.binding_version,
                node_parameters=case.node_parameters,
                binding_parameters=case.binding_parameters,
            ),
        ),
        edges=case.workflow_edges,
        contract_lock=(),
        observation_selectors=case.observation_selectors,
        selection_objectives=case.selection_objectives,
    )
    committed = authoring.commit(
        project.id,
        workflow=workflow,
    )
    service = V2RunService(
        project_manager,
        catalog,
        authoring,
        NodeAttemptFactory(
            project_manager,
            admit_environment_configuration(
                catalog,
                {
                    (case.binding_id, case.binding_version): {
                        "values": dict(case.environment_values),
                    }
                },
            ),
            result_store(project_manager),
        ),
        result_store(project_manager),
    )
    try:
        receipt = service.start_background(
            project.id,
            workflow_commit_id=committed.workflow_commit_id,
            client_request_id=f"ctk-{case.case_id}",
        )
        service.shutdown()
        projection = service.projection(project.id, receipt["run_id"])
        replay = service.replay(project.id, receipt["run_id"], None)
        if not replay.terminal:
            raise ModulePackageConformanceError(
                f"{case.case_id} replay did not reach the durable terminal fact"
            )
        if projection.status != "succeeded":
            raise ModulePackageConformanceError(
                f"{case.case_id} execution did not succeed"
            )
        outputs = {
            output.output_port: output
            for output in projection.outputs
            if output.node_id == "contract-test-node"
        }
        canonical_values = {
            port_name: tuple(
                service.typed_value(
                    project.id,
                    receipt["run_id"],
                    output.node_id,
                    output.output_port,
                    value_index,
                )[1]
                for value_index in range(output.value_count)
            )
            for port_name, output in outputs.items()
        }
        for port_name, expected in case.expected_scalar_outputs.items():
            output = outputs.get(port_name)
            values = canonical_values.get(port_name, ())
            if (
                output is None
                or len(values) != 1
                or json.loads(values[0])["value"] != expected
            ):
                raise ModulePackageConformanceError(
                    f"{case.case_id} output {port_name!r} did not match"
                )
        for port_name, expected_count in case.expected_candidate_counts.items():
            output = outputs.get(port_name)
            values = canonical_values.get(port_name, ())
            if output is None or len(values) != 1:
                raise ModulePackageConformanceError(
                    f"{case.case_id} Candidate output {port_name!r} is missing"
                )
            decoded = _decode_published_value(
                catalog,
                output,
                values[0],
            )
            if (
                not isinstance(decoded, CandidateCollection)
                or len(decoded.items) != expected_count
                or any(
                    not candidate.candidate_id.startswith("candidate-")
                    for candidate in decoded.items
                )
            ):
                raise ModulePackageConformanceError(
                    f"{case.case_id} Candidate output {port_name!r} is invalid"
                )
        for port_name, expected_count in (
            case.expected_observation_counts.items()
        ):
            output = outputs.get(port_name)
            values = canonical_values.get(port_name, ())
            if output is None or len(values) != 1:
                raise ModulePackageConformanceError(
                    f"{case.case_id} Observation output {port_name!r} is missing"
                )
            decoded = _decode_published_value(
                catalog,
                output,
                values[0],
            )
            if (
                not isinstance(decoded, ScoreCollection)
                or len(decoded.entries) != expected_count
                or any(
                    not isinstance(entry, ScoreObservation)
                    for entry in decoded.entries
                )
            ):
                raise ModulePackageConformanceError(
                    f"{case.case_id} Observation output {port_name!r} is invalid"
                )
        artifacts_by_port = {
            artifact.output_port: artifact
            for artifact in projection.artifacts
            if artifact.node_id == "contract-test-node"
        }
        for port_name, expected_body in case.expected_artifacts.items():
            artifact = artifacts_by_port.get(port_name)
            if artifact is None:
                raise ModulePackageConformanceError(
                    f"{case.case_id} artifact {port_name!r} is missing"
                )
            _, body = service.artifact(
                project.id,
                receipt["run_id"],
                artifact.artifact_reference,
            )
            if body != expected_body:
                raise ModulePackageConformanceError(
                    f"{case.case_id} artifact {port_name!r} did not match"
                )
        result_identities = tuple(
            sorted({output.result_identity for output in outputs.values()})
        )
        if (
            (outputs and len(result_identities) != 1)
            or any(
                _CANONICAL_DIGEST.fullmatch(identity) is None
                for identity in result_identities
            )
            or any(
                output.producer_provenance
                != {
                    "producer_run_id": receipt["run_id"],
                    "producer_result_identity": output.result_identity,
                    "output_port": output.output_port,
                }
                for output in outputs.values()
            )
        ):
            raise ModulePackageConformanceError(
                f"{case.case_id} Result Identity or provenance is incomplete"
            )
        sequences = tuple(fact.sequence for fact in replay.events)
        if (
            tuple(sorted(sequences)) != sequences
            or len(sequences) != len(set(sequences))
        ):
            raise ModulePackageConformanceError(
                f"{case.case_id} replay contains gaps in ordering or duplicates"
            )
        public_events = tuple(
            encode_event(
                project_id=project.id,
                run_id=receipt["run_id"],
                fact=fact,
            )
            for fact in replay.events
        )
        event_types = tuple(
            event["event"]["type"] for event in public_events
        )
        required_events = {
            "node_attempt_started",
            "operation_attempt_started",
            "engine_invocation_started",
            "engine_invocation_terminal",
            "operation_attempt_terminal",
            "node_attempt_terminal",
            "node_disposition",
            "run_terminal",
        }
        binding = catalog.require_contract(
            "binding",
            case.binding_id,
            case.binding_version,
        )
        if binding.descriptor["execution_route"] == "adapter":
            required_events.add("readiness_attested")
        if not required_events <= set(event_types):
            raise ModulePackageConformanceError(
                f"{case.case_id} replay lacks execution provenance"
            )
        public_evidence = json.dumps(
            {
                "projection": encode_run_projection(projection),
                "events": public_events,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        for fragment in (*case.forbidden_public_fragments, str(root)):
            if fragment and fragment in public_evidence:
                raise ModulePackageConformanceError(
                    f"{case.case_id} published unsafe diagnostic material"
                )
        return ModulePackageCaseReport(
            case_id=case.case_id,
            status=projection.status,
            result_identities=result_identities,
            output_ports=tuple(sorted(outputs)),
            artifact_ports=tuple(sorted(artifacts_by_port)),
            event_sequences=sequences,
            event_types=event_types,
        )
    finally:
        service.shutdown()


def verify_module_package_contract(
    registration: ModulePackageRegistration,
    *,
    execution_cases: Sequence[ModulePackageContractCase],
    port_cases: Sequence[ModulePackagePortCase] = (),
    supporting_registrations: Sequence[ModulePackageRegistration] = (),
    work_root: str | Path | None = None,
) -> ModulePackageContractReport:
    """Validate and execute one exact production registration in isolation."""
    if not isinstance(registration, ModulePackageRegistration):
        raise ModulePackageConformanceError(
            "Contract Test Kit requires one production ModulePackageRegistration"
        )
    case_tuple = tuple(execution_cases)
    port_case_tuple = tuple(port_cases)
    if not case_tuple:
        raise ModulePackageConformanceError(
            "Contract Test Kit requires at least one independent execution case"
        )
    try:
        support = tuple(supporting_registrations)
        if any(
            not isinstance(item, ModulePackageRegistration)
            for item in support
        ):
            raise ModulePackageConformanceError(
                "supporting_registrations must contain Module Packages"
            )
        catalog = build_frozen_catalog((registration, *support))
        _verify_execution_case_coverage(
            catalog,
            registration,
            case_tuple,
        )
        verified_port_types = _verify_port_cases(
            catalog,
            registration,
            port_case_tuple,
        )
        parent = Path(work_root) if work_root is not None else None
        if parent is not None:
            parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(
            prefix="protein-workbench-ctk-",
            dir=parent,
        ) as temporary:
            temporary_root = Path(temporary)
            reports = tuple(
                _verify_case(
                    catalog=catalog,
                    case=case,
                    root=temporary_root / case.case_id,
                )
                for case in case_tuple
            )
    except ModulePackageConformanceError:
        raise
    except (
        CatalogBuildError,
        PortValueError,
        V2RunError,
        WorkflowAuthoringError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
    ) as error:
        raise ModulePackageConformanceError(
            f"{registration.package_id} failed shared conformance"
        ) from error
    return ModulePackageContractReport(
        package_id=registration.package_id,
        package_version=registration.package_version,
        catalog_contract_digest=catalog.contract_digest,
        case_reports=reports,
        verified_port_types=verified_port_types,
    )
