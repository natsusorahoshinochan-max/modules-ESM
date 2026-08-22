"""Pure verifier for the repository-owned v2 example suite."""

from __future__ import annotations

from dataclasses import replace

from core.catalog.builder import build_frozen_catalog

from protein_workbench_public.bootstrap import module_registrations

import json
from pathlib import Path
from typing import Any

from core.workflow.compiler import (
    CompilationRequest,
    WorkflowCompileError,
    compile,
    lock_workflow,
)
from protein_workbench_public.workflow_codec import decode_workflow_document


EXAMPLE_ROOT = Path(__file__).resolve().parent / "v2"
CAPABILITY_INVENTORY_PATH = EXAMPLE_ROOT / "capability-inventory.json"
PRODUCTION_WORKFLOW_PATHS = tuple(
    sorted(EXAMPLE_ROOT.glob("*.workflow.json"))
)
INVENTORY_SCHEMA = "protein-workbench-capability-inventory/v2"


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain one JSON object")
    return value


def verify_repository_examples() -> dict[str, object]:
    """Verify exact locks and compilation without executing any Binding."""
    catalog = build_frozen_catalog(module_registrations())
    inventory = _load_json(CAPABILITY_INVENTORY_PATH)
    if inventory.get("schema_version") != INVENTORY_SCHEMA:
        raise ValueError("capability inventory has an unsupported schema")

    package_ids = sorted(
        package.package_id for package in module_registrations()
    )
    if inventory.get("package_ids") != package_ids:
        raise ValueError("capability inventory package set is stale")

    contract_references = [
        contract.reference()
        for contract in sorted(
            catalog.contracts,
            key=lambda item: (
                item.contract_kind,
                item.contract_id,
                item.contract_version,
            ),
        )
    ]
    if inventory.get("contracts") != contract_references:
        raise ValueError("capability inventory contract identities are stale")

    node_type_count = sum(
        reference["contract_kind"] == "node_type"
        for reference in contract_references
    )

    if not PRODUCTION_WORKFLOW_PATHS:
        raise ValueError("repository v2 example suite is empty")
    for path in PRODUCTION_WORKFLOW_PATHS:
        workflow = decode_workflow_document(_load_json(path))
        if not workflow.contract_lock:
            raise ValueError(f"{path.name} has an empty Contract Lock")
        if lock_workflow(
            replace(workflow, contract_lock=()),
            catalog,
        ) != workflow:
            raise ValueError(f"{path.name} has a stale Contract Lock")
        try:
            compiled = compile(
                           CompilationRequest(
                               workflow,
                               1,
                           ),
                           catalog,
                       )
        except WorkflowCompileError as error:
            # Static Workflow checks precede Availability in the compiler.
            # An installed artifact may intentionally lack the explicitly
            # selected provider, but the verifier must never choose another.
            if error.code != "binding_unavailable":
                raise
        else:
            plan = compiled
            if (
                plan.workflow_commit_revision != 1
                or plan.workflow_digest != workflow.digest
            ):
                raise ValueError(
                    f"{path.name} compiled to inconsistent Execution Plan facts"
                )

    return {
        "catalog_contract_digest": catalog.contract_digest,
        "package_count": len(package_ids),
        "node_type_count": node_type_count,
        "workflow_count": len(PRODUCTION_WORKFLOW_PATHS),
    }


def main() -> int:
    print(json.dumps(verify_repository_examples(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
