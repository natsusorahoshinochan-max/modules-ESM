"""Pure verifier for the repository-owned v2 example suite."""

from __future__ import annotations

from core.catalog.builder import build_frozen_catalog

from protein_workbench_public.bootstrap import module_registrations

import json
from pathlib import Path
from typing import Any

from core.workflow.compiler import (
    CompilationRequest,
    compile,
)
from protein_workbench_public.workflow_codec import decode_workflow_document


EXAMPLE_ROOT = Path(__file__).resolve().parent / "v2"
PRODUCTION_WORKFLOW_PATHS = tuple(
    sorted(EXAMPLE_ROOT.glob("*.workflow.json"))
)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain one JSON object")
    return value


def verify_repository_examples() -> dict[str, object]:
    """Compile every repository-owned example without executing a Binding."""
    catalog = build_frozen_catalog(module_registrations())
    if not PRODUCTION_WORKFLOW_PATHS:
        raise ValueError("repository v2 example suite is empty")
    for path in PRODUCTION_WORKFLOW_PATHS:
        workflow = decode_workflow_document(_load_json(path))
        compile(CompilationRequest(workflow), catalog)

    return {
        "workflow_count": len(PRODUCTION_WORKFLOW_PATHS),
    }


def main() -> int:
    print(json.dumps(verify_repository_examples(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
