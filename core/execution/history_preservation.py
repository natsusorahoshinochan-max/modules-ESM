"""Explicit offline preparation of generic readings from recorded Run facts."""

import json
from pathlib import Path
from typing import Any

from core.execution.ledger import run_cursor
from core.execution.recorded_run import RecordedRun
from core.project.manager import ProjectManager
from core.project.storage import write_new_file_durable


_EVENT_KINDS = frozenset({
    "readiness_attested", "run_admitted", "run_started", "node_attempt_started",
    "operation_attempt_started", "engine_invocation_started", "engine_invocation_terminal",
    "operation_attempt_terminal", "node_attempt_terminal", "node_disposition", "run_terminal",
})


def _reading_from_transactions(project_id: str, run_id: str, directory: Path) -> dict[str, Any] | None:
    """Copy published facts; never interpret a retired plan or scientific rule."""
    facts = []
    for sequence, path in enumerate(sorted(directory.glob("*.json")), 1):
        transaction = json.loads(path.read_bytes())
        batch = transaction["facts"]
        if (path.name != f"{sequence:020d}.json" or transaction["transaction_sequence"] != sequence
                or transaction["project_id"] != project_id or transaction["run_id"] != run_id
                or transaction["first_fact_sequence"] != len(facts) + 1
                or transaction["last_fact_sequence"] != len(facts) + len(batch)
                or [fact["sequence"] for fact in batch] != list(range(len(facts) + 1, len(facts) + len(batch) + 1))):
            raise ValueError("Recorded Run transaction identity or sequence is invalid")
        facts.extend(batch)
    if not any(fact["fact_type"] == "run_admitted" for fact in facts):
        return None
    if facts[-1]["fact_type"] != "run_terminal":
        raise RuntimeError("Historical reading preparation requires completed Runs")
    scope = facts[0]["payload"]
    terminal = facts[-1]
    publications = {fact["payload"]["node_id"]: fact["payload"] for fact in facts
                    if fact["fact_type"] == "outputs_published"}
    order = [node["node_id"] for node in scope["plan_nodes"]]
    raw_scope = scope.get("execution_scope")
    execution_scope = ({key: value for key, value in raw_scope.items() if key != "out_of_scope_selection_ids"}
                       if raw_scope is not None else None)
    derived = scope.get("derived_from")
    diagnostic = next((fact["payload"]["error"] for fact in facts
                       if fact["fact_type"] == "selection_terminal" and fact["payload"].get("error") is not None), None)
    return {"schema_version": 1, "projection": {
        "project_id": project_id, "run_id": run_id,
        "workflow_commit_id": scope["workflow_commit_id"], "status": terminal["payload"]["status"],
        "ledger_cursor": run_cursor(terminal["sequence"], project_id=project_id, run_id=run_id).value,
        "terminal_sequence": terminal["sequence"],
        "node_dispositions": [{**fact["payload"], "resolution": fact["payload"].get("resolution"),
                               "blocked_by": fact["payload"].get("blocked_by", []), "terminal_sequence": fact["sequence"]}
                              for fact in facts if fact["fact_type"] == "node_disposition"],
        "publications": [publications[node_id] for node_id in order if node_id in publications],
        "execution_scope": execution_scope,
        "derived_from_run_id": (derived["source_run_id"] if derived else raw_scope.get("source_run_id") if raw_scope else None),
        "diagnostic": diagnostic,
    }, "events": [fact for fact in facts if fact["fact_type"] in _EVENT_KINDS]}


def prepare_historical_reading(data_root: Path) -> tuple[tuple[str, str], ...]:
    """Prepare a quiescent whole-root copy, leaving every original record intact.

    The caller owns copying, verification and the active-root switch. Raw record
    conversion is deliberately separate from current execution and never calls
    a retired Workflow parser, Ledger reducer or algorithm.
    """
    root = data_root.resolve()
    projects = ProjectManager(root / "projects", cache_root=root / "cache",
                              output_root=root / "outputs", run_root=root / "runs")
    prepared = []
    pending = []
    for project_id in projects.stored_project_ids():
        for run_id in projects.stored_run_ids(project_id):
            if RecordedRun.load(projects, project_id, run_id) is not None:
                prepared.append((project_id, run_id))
                continue
            directory = projects.run_storage_directory(project_id, run_id)
            reading = _reading_from_transactions(project_id, run_id, directory / "ledger")
            if reading is not None:
                pending.append((directory, reading))
                prepared.append((project_id, run_id))
    for directory, reading in pending:
        write_new_file_durable(directory, ("reading.json",),
            json.dumps(reading, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
    return tuple(prepared)
