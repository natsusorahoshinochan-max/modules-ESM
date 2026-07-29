"""Shared executable conformance contracts for v2 Module Packages."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from types import MappingProxyType
from typing import Any

from core.module_package import (
    ModulePackageRegistration,
    build_frozen_catalog,
)
from core.port_types import (
    PORT_VALUE_NAMESPACE,
    CatalogBuildError,
    PortValueError,
    canonical_json_bytes,
)
from core.project import ProjectManager
from core.run_execution_v2 import (
    EnvironmentConfiguration,
    V2RunError,
    V2RunService,
)
from core.workflow_authoring_v2 import (
    WorkflowAuthoringError,
    WorkflowAuthoringService,
)
from core.workflow_v2 import (
    WorkflowDocument,
    WorkflowNodeInstance,
    parse_workflow_document,
)
from datatypes import CandidateCollection, ScoreCollection, ScoreObservation


_CANONICAL_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


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
    safe_environment_fingerprint: str
    invalidation_token: str
    expected_scalar_outputs: Mapping[str, Any] = field(default_factory=dict)
    expected_candidate_counts: Mapping[str, int] = field(default_factory=dict)
    expected_observation_counts: Mapping[str, int] = field(default_factory=dict)
    expected_artifacts: Mapping[str, bytes] = field(default_factory=dict)
    forbidden_public_fragments: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "node_parameters",
            "binding_parameters",
            "environment_values",
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
            "forbidden_public_fragments",
            tuple(self.forbidden_public_fragments),
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
    output: Mapping[str, Any],
    wire_value: Any,
) -> Any:
    reference = output["port_type"]
    port_type = catalog.require_port_type(
        reference["contract_id"],
        reference["contract_version"],
    )
    return port_type.decode(
        canonical_json_bytes(
            {
                "schema_namespace": PORT_VALUE_NAMESPACE,
                "port_type_id": port_type.type_id,
                "port_type_version": port_type.version,
                "value": wire_value,
            }
        )
    )


def _verify_port_cases(
    catalog: Any,
    registration: ModulePackageRegistration,
    cases: Sequence[ModulePackagePortCase],
) -> tuple[str, ...]:
    owned = {
        (definition.type_id, definition.version)
        for definition in registration.port_types
    }
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


def _availability_is_green(
    catalog: Any,
    binding_id: str,
    binding_version: str,
) -> bool:
    return any(
        snapshot["binding"]["contract_id"] == binding_id
        and snapshot["binding"]["contract_version"] == binding_version
        and snapshot["available"] is True
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
    authoring = WorkflowAuthoringService(project_manager, catalog)
    workflow = WorkflowDocument(
        schema_version="2.0.0",
        workflow_id=project.id,
        nodes=(
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
        edges=(),
        contract_lock=(),
    )
    saved = authoring.save(
        project.id,
        expected_workflow_revision=0,
        workflow=workflow,
    )
    relocked = authoring.relock(
        project.id,
        workflow_revision=saved["workflow_revision"],
    )
    locked_workflow = parse_workflow_document(relocked["workflow"])
    compiled = authoring.compile(
        project.id,
        workflow_revision=relocked["workflow_revision"],
        workflow=locked_workflow,
    )
    service = V2RunService(
        project_manager,
        catalog,
        authoring,
        EnvironmentConfiguration(
            {
                (case.binding_id, case.binding_version): {
                    "values": dict(case.environment_values),
                    "safe_fingerprint": case.safe_environment_fingerprint,
                    "invalidation_token": case.invalidation_token,
                }
            }
        ),
    )
    try:
        receipt = service.start_background(
            project.id,
            workflow_revision=relocked["workflow_revision"],
            compile_id=compiled.public_receipt()["compile_id"],
            client_request_id=f"ctk-{case.case_id}",
        )
        service.shutdown()
        projection = service.projection(project.id, receipt["run_id"])
        (
            _,
            _,
            _,
            _,
            events,
            terminal,
        ) = service.replay_window(project.id, receipt["run_id"], None)
        if not terminal:
            raise ModulePackageConformanceError(
                f"{case.case_id} replay did not reach the durable terminal fact"
            )
        if projection["status"] != "succeeded":
            raise ModulePackageConformanceError(
                f"{case.case_id} execution did not succeed"
            )
        outputs = {
            output["output_port"]: output
            for output in projection["outputs"]
        }
        for port_name, expected in case.expected_scalar_outputs.items():
            output = outputs.get(port_name)
            if output is None or output["values"] != [expected]:
                raise ModulePackageConformanceError(
                    f"{case.case_id} output {port_name!r} did not match"
                )
        for port_name, expected_count in case.expected_candidate_counts.items():
            output = outputs.get(port_name)
            if output is None or len(output["values"]) != 1:
                raise ModulePackageConformanceError(
                    f"{case.case_id} Candidate output {port_name!r} is missing"
                )
            decoded = _decode_published_value(
                catalog,
                output,
                output["values"][0],
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
            if output is None or len(output["values"]) != 1:
                raise ModulePackageConformanceError(
                    f"{case.case_id} Observation output {port_name!r} is missing"
                )
            decoded = _decode_published_value(
                catalog,
                output,
                output["values"][0],
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
            artifact["output_port"]: artifact
            for artifact in projection["artifact_index"]
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
                artifact["artifact_reference"],
            )
            if body != expected_body:
                raise ModulePackageConformanceError(
                    f"{case.case_id} artifact {port_name!r} did not match"
                )
        result_identities = tuple(
            sorted({output["result_identity"] for output in outputs.values()})
        )
        if (
            len(result_identities) != 1
            or _CANONICAL_DIGEST.fullmatch(result_identities[0]) is None
            or any(
                output["producer_provenance"]
                != {
                    "producer_run_id": receipt["run_id"],
                    "producer_result_identity": output["result_identity"],
                    "output_port": output["output_port"],
                }
                for output in outputs.values()
            )
        ):
            raise ModulePackageConformanceError(
                f"{case.case_id} Result Identity or provenance is incomplete"
            )
        sequences = tuple(event["sequence"] for event in events)
        if (
            tuple(sorted(sequences)) != sequences
            or len(sequences) != len(set(sequences))
        ):
            raise ModulePackageConformanceError(
                f"{case.case_id} replay contains gaps in ordering or duplicates"
            )
        event_types = tuple(event["event"]["type"] for event in events)
        required_events = {
            "readiness_attested",
            "node_attempt_started",
            "operation_attempt_started",
            "engine_invocation_started",
            "engine_invocation_terminal",
            "operation_attempt_terminal",
            "node_attempt_terminal",
            "node_disposition",
            "run_terminal",
        }
        if not required_events <= set(event_types):
            raise ModulePackageConformanceError(
                f"{case.case_id} replay lacks execution provenance"
            )
        public_evidence = json.dumps(
            {"projection": projection, "events": events},
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
            status=projection["status"],
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
        catalog = build_frozen_catalog((registration,))
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
