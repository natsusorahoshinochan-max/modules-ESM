"""Compiler-plan and active-Catalog evidence used by Run Runtime."""

from __future__ import annotations

from core.catalog.model import FrozenCatalog
from core.catalog.port_contract import ContractResolutionError
from core.execution.ledger import (
    ArtifactOutputEvidence,
    Ledger,
    PlanNodeEvidence,
    PlanRequiredInputEvidence,
    PlanValueSourceEvidence,
)
from core.workflow.document import ContractLockEntry
from core.workflow.plan import ExecutionPlan
from datatypes.exact_reference import ExactContractReference


def _exact_contract_reference(
    entry: ContractLockEntry,
) -> ExactContractReference:
    return ExactContractReference(
        contract_kind=entry.contract_kind,
        contract_id=entry.contract_id,
        contract_version=entry.contract_version,
        contract_digest=entry.contract_digest,
    )


def _execution_plan_contract_roots(
    plan: ExecutionPlan,
) -> tuple[ExactContractReference, ...]:
    """Persist the exact roots needed to reconstruct one Plan's Lock."""
    root_identities = {
        reference.key
        for node in plan.nodes
        for reference in (node.node_type, node.binding)
    }
    for resolved_selector in (
        selector
        for node in plan.nodes
        for selector in node._runtime.observation_selectors
    ):
        root_identities.update(
            {
                (
                    resolved_selector.metric.contract_kind,
                    resolved_selector.metric.contract_id,
                    resolved_selector.metric.contract_version,
                ),
                (
                    resolved_selector.method.contract_kind,
                    resolved_selector.method.contract_id,
                    resolved_selector.method.contract_version,
                ),
            }
        )
    for resolved_objective in (
        objective
        for node in plan.nodes
        for objective in node._runtime.selection_objectives
    ):
        root_identities.update(
            {
                (
                    resolved_objective.metric.contract_kind,
                    resolved_objective.metric.contract_id,
                    resolved_objective.metric.contract_version,
                ),
                (
                    resolved_objective.method.contract_kind,
                    resolved_objective.method.contract_id,
                    resolved_objective.method.contract_version,
                ),
                (
                    resolved_objective.utility.reference.contract_kind,
                    resolved_objective.utility.reference.contract_id,
                    resolved_objective.utility.reference.contract_version,
                ),
            }
        )
    lock_by_identity = {
        entry.key: entry for entry in plan.resolved_contracts
    }
    return tuple(
        _exact_contract_reference(lock_by_identity[identity])
        for identity in sorted(root_identities)
    )


def _reachable_contract_evidence(
    catalog: FrozenCatalog,
    roots: tuple[ExactContractReference, ...],
) -> tuple[ExactContractReference, ...]:
    """Rebuild the exact active Catalog closure from durable Plan roots."""
    try:
        return catalog.resolve_contract_closure(roots)
    except ContractResolutionError as error:
        raise RuntimeError("Run scope Contract root is not active") from error


def _run_catalog_digest(
    ledger: Ledger,
    catalog: FrozenCatalog,
) -> str:
    """Classify one admitted Ledger against the active Catalog generation."""
    scope = ledger.run_scope
    if scope is None:
        raise RuntimeError("Run Ledger has no admitted scope")
    persisted_catalog_digest = scope.catalog_contract_digest
    if persisted_catalog_digest != catalog.contract_digest:
        return persisted_catalog_digest
    expected_contracts = _reachable_contract_evidence(
        catalog,
        scope.resolved_contract_roots,
    )
    if scope.resolved_contracts != expected_contracts:
        raise RuntimeError("Run scope resolved Contracts are invalid")
    return persisted_catalog_digest


def plan_evidence(plan: ExecutionPlan) -> tuple[PlanNodeEvidence, ...]:
    """Project one compiled Plan into Ledger admission evidence."""
    return tuple(
        PlanNodeEvidence(
            node_id=node.node_id,
            dependencies=node._runtime.dependencies,
            required_input_sources=tuple(
                PlanRequiredInputEvidence(
                    input_port=input_port,
                    sources=tuple(
                        sorted(
                            (
                                PlanValueSourceEvidence(
                                    source.node_id,
                                    source.output_port,
                                )
                                for source in sources
                            ),
                            key=lambda source: (
                                source.node_id,
                                source.output_port,
                            ),
                        )
                    ),
                )
                for input_port, sources in sorted(
                    node._runtime.required_input_sources.items()
                )
            ),
            result_identity_plan_facts_digest=(
                node.result_identity_plan_facts.digest
            ),
            binding=_exact_contract_reference(node.binding),
            execution_route=node._runtime.execution_route,
            node_type=_exact_contract_reference(node.node_type),
            artifact_outputs=tuple(
                ArtifactOutputEvidence(
                    output_port=output.output_port,
                    artifact_kind=output.artifact_kind,
                    artifact_media_type=output.artifact_media_type,
                    port_type=_exact_contract_reference(output.port_type),
                    accepted_media_types=output.accepted_media_types,
                )
                for output in node._runtime.artifact_outputs
            ),
            selection_consumer=bool(
                node._runtime.selection_objectives
                or node._runtime.observation_selectors
            ),
        )
        for node in plan.nodes
    )
