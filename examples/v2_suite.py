"""Pure verifier for the repository-owned v2 example suite."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core import (
    WorkflowCompileError,
    build_discovered_frozen_catalog,
    compile_workflow,
    discover_module_packages,
    parse_workflow_document,
    relock_workflow,
)


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
    catalog = build_discovered_frozen_catalog()
    inventory = _load_json(CAPABILITY_INVENTORY_PATH)
    if inventory.get("schema_version") != INVENTORY_SCHEMA:
        raise ValueError("capability inventory has an unsupported schema")

    package_ids = sorted(
        package.package_id for package in discover_module_packages()
    )
    if inventory.get("package_ids") != package_ids:
        raise ValueError("capability inventory package set is stale")

    node_references = sorted(
        (
            {
                "contract_kind": "node_type",
                "contract_id": contract.contract_id,
                "contract_version": contract.contract_version,
                "contract_digest": contract.contract_digest,
            }
            for contract in catalog.contracts
            if contract.contract_kind == "node_type"
        ),
        key=lambda reference: (
            reference["contract_id"],
            reference["contract_version"],
        ),
    )
    if inventory.get("node_types") != node_references:
        raise ValueError("capability inventory Node Type identities are stale")

    if not PRODUCTION_WORKFLOW_PATHS:
        raise ValueError("repository v2 example suite is empty")
    for path in PRODUCTION_WORKFLOW_PATHS:
        workflow = parse_workflow_document(_load_json(path))
        if not workflow.contract_lock:
            raise ValueError(f"{path.name} has an empty Contract Lock")
        if relock_workflow(workflow, catalog) != workflow:
            raise ValueError(f"{path.name} has a stale Contract Lock")
        try:
            compile_workflow(
                workflow,
                workflow_revision=1,
                catalog=catalog,
            )
        except WorkflowCompileError as error:
            # Static Workflow checks precede Availability in the compiler.
            # An installed artifact may intentionally lack the explicitly
            # selected provider, but the verifier must never choose another.
            if error.code != "binding_unavailable":
                raise

    return {
        "catalog_contract_digest": catalog.contract_digest,
        "package_count": len(package_ids),
        "node_type_count": len(node_references),
        "workflow_count": len(PRODUCTION_WORKFLOW_PATHS),
    }


def main() -> int:
    print(json.dumps(verify_repository_examples(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
