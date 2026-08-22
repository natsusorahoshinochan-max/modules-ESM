"""Private exact Contract Lock implementation."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from typing import Any

from core.catalog.model import FrozenCatalog
from core.catalog.port_contract import (
    CatalogBuildError,
    ContractResolutionError,
    InactiveContractGenerationError,
    PortTypeDefinition,
    UnknownContractError,
)
from core.scoring.selection import SelectionObjective
from core.workflow.compiler import WorkflowCompileError
from core.workflow.document import (
    ContractLockEntry,
    WorkflowDocument,
)
from datatypes.exact_reference import ExactContractReference


def _require_workflow_contract(
    catalog: FrozenCatalog,
    contract_kind: str,
    contract_id: str,
    contract_version: str,
    *,
    identity_path: tuple[str | int, ...],
    version_path: tuple[str | int, ...],
    node_id: str | None = None,
) -> Any:
    try:
        return catalog.require_contract(
            contract_kind,
            contract_id,
            contract_version,
        )
    except InactiveContractGenerationError as error:
        raise WorkflowCompileError(
            "inactive_generation",
            (
                "Workflow requested exact contract version "
                f"{contract_kind}:{contract_id}@{contract_version}, which is "
                "not active; "
                f"the active Catalog generation publishes {error.active_version}"
            ),
            node_id=node_id,
            field_path=version_path,
        ) from error
    except UnknownContractError as error:
        raise WorkflowCompileError(
            "unknown_contract",
            (
                "Workflow references unknown contract "
                f"{contract_kind}:{contract_id}@{contract_version}"
            ),
            node_id=node_id,
            field_path=identity_path,
        ) from error

def _workflow_contract_references(
    workflow: WorkflowDocument,
) -> tuple[
    tuple[
        str,
        ExactContractReference,
        tuple[str | int, ...],
        tuple[str | int, ...],
    ],
    ...,
]:
    references: list[
        tuple[
            str,
            ExactContractReference,
            tuple[str | int, ...],
            tuple[str | int, ...],
        ]
    ] = []
    for collection_name, selectors in (
        ("observation_selectors", workflow.observation_selectors),
        ("selection_objectives", workflow.selection_objectives),
    ):
        for index, selector in enumerate(selectors):
            fields = [
                ("metric", "metric", selector.metric),
                ("method", "method", selector.method),
            ]
            if isinstance(selector, SelectionObjective):
                fields.append(
                    (
                        "utility_transform",
                        "utility_transform",
                        selector.utility_transform,
                    )
                )
            for field_name, contract_kind, reference in fields:
                field_path = (collection_name, index, field_name)
                if reference.contract_kind != contract_kind:
                    raise WorkflowCompileError(
                        "contract_kind_mismatch",
                        (
                            f"Workflow {field_name} requires an exact "
                            f"{contract_kind} contract reference, received "
                            f"{reference.contract_kind}"
                        ),
                        field_path=(*field_path, "contract_kind"),
                    )
                references.append(
                    (
                        contract_kind,
                        reference,
                        (*field_path, "contract_id"),
                        (*field_path, "contract_version"),
                    )
                )
    return tuple(references)

def _reference_from_value(value: Any) -> ContractLockEntry | None:
    if not isinstance(value, Mapping):
        return None
    required = {
        "contract_kind",
        "contract_id",
        "contract_version",
        "contract_digest",
    }
    if set(value) != required:
        return None
    return ContractLockEntry.from_canonical(value)

def _reachable_contract_lock(
    workflow: WorkflowDocument,
    catalog: FrozenCatalog,
) -> tuple[ContractLockEntry, ...]:
    pending: deque[ContractLockEntry] = deque()
    for index, node in enumerate(workflow.nodes):
        for kind, contract_id, version, field_prefix in (
            (
                "node_type",
                node.node_type_id,
                node.node_type_version,
                "node_type",
            ),
            (
                "binding",
                node.binding_id,
                node.binding_version,
                "binding",
            ),
        ):
            contract = _require_workflow_contract(
                catalog,
                kind,
                contract_id,
                version,
                identity_path=("nodes", index, f"{field_prefix}_id"),
                version_path=("nodes", index, f"{field_prefix}_version"),
                node_id=node.node_id,
            )
            pending.append(
                ContractLockEntry.from_canonical(contract.reference())
            )
    for kind, reference, identity_path, version_path in (
        _workflow_contract_references(workflow)
    ):
        contract = _require_workflow_contract(
            catalog,
            kind,
            reference.contract_id,
            reference.contract_version,
            identity_path=identity_path,
            version_path=version_path,
        )
        if reference.contract_digest != contract.contract_digest:
            raise WorkflowCompileError(
                "contract_digest_mismatch",
                (
                    "Workflow exact contract reference digest does not match "
                    "the active Catalog contract"
                ),
                field_path=(*version_path[:-1], "contract_digest"),
            )
        pending.append(
            ContractLockEntry.from_canonical(contract.reference())
        )

    reachable: dict[tuple[str, str, str], ContractLockEntry] = {}
    while pending:
        reference = pending.popleft()
        if reference.key in reachable:
            continue
        contract = catalog.require_contract(*reference.key)
        observed = ContractLockEntry.from_canonical(contract.reference())
        reachable[observed.key] = observed
        descriptor = (
            contract.descriptor()
            if type(contract) is PortTypeDefinition
            else contract.descriptor
        )
        nested: deque[Any] = deque([descriptor])
        while nested:
            value = nested.popleft()
            nested_reference = _reference_from_value(value)
            if nested_reference is not None:
                pending.append(nested_reference)
            elif isinstance(value, Mapping):
                nested.extend(value.values())
            elif isinstance(value, tuple):
                nested.extend(value)
            elif isinstance(value, list):
                nested.extend(value)
    return tuple(sorted(reachable.values()))

def _require_matching_lock(
    workflow: WorkflowDocument,
    catalog: FrozenCatalog,
) -> tuple[ContractLockEntry, ...]:
    try:
        expected = _reachable_contract_lock(workflow, catalog)
    except (CatalogBuildError, ContractResolutionError) as error:
        raise WorkflowCompileError(
            "contract_digest_mismatch",
            "Workflow references a contract absent from the current Catalog",
            field_path=("contract_lock",),
        ) from error
    if workflow.contract_lock != expected:
        raise WorkflowCompileError(
            "contract_digest_mismatch",
            "Workflow Contract Lock does not equal the reachable Catalog closure",
            field_path=("contract_lock",),
        )
    return expected
