"""Explicit one-time preparation of completed Run readings on a data-root copy."""

from pathlib import Path

from core.execution.ledger import Ledger
from core.execution.recorded_run import RecordedRun, preserve_run_reading
from core.project.manager import ProjectManager
from protein_workbench_public.application_environment import application_storage_roots


def prepare_historical_reading(data_root: Path) -> tuple[tuple[str, str], ...]:
    """Prepare a quiescent isolated data-root copy before retiring old executors.

    Original Commit, Run transactions, inputs and result objects are retained.
    The caller owns copying, verification and the whole-root switch; this
    operation does not select or change the application's active data root.
    """
    storage = application_storage_roots({"PROTEIN_WORKBENCH_DATA_ROOT": str(data_root)})
    projects = ProjectManager(root_dir=storage.projects, cache_root=storage.cache,
                              output_root=storage.outputs, run_root=storage.runs)
    prepared = []
    pending = []
    for project_id in projects.stored_project_ids():
        for run_id in projects.stored_run_ids(project_id):
            if RecordedRun.load(projects, project_id, run_id) is not None:
                prepared.append((project_id, run_id))
                continue
            ledger = Ledger.load(projects, project_id, run_id)
            if ledger is None or not ledger.admitted:
                continue
            if not ledger.terminal:
                raise RuntimeError("Historical reading preparation requires completed Runs")
            pending.append(ledger)
            prepared.append((project_id, run_id))
    for ledger in pending:
        preserve_run_reading(projects, ledger.projection(), ledger.events())
    return tuple(prepared)
