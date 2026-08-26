"""Project-scoped in-process and restart registry for Run Runtime."""

from __future__ import annotations

from core.execution._run_runtime_models import _RunRecord
from core.execution.ledger import (
    Ledger,
    LedgerStore,
    RunCursor,
    V2RunError,
    run_cursor,
)
from core.project.manager import ProjectManager
from core.project.storage import StoragePathError


class _RunRegistry:
    """Own Run identity, restart classification, and active records."""

    def __init__(
        self,
        *,
        projects: ProjectManager,
        ledger_store: LedgerStore | None,
    ) -> None:
        self._projects = projects
        self._ledger_store = ledger_store
        self._runs: dict[tuple[str, str], _RunRecord] = {}
        self._damaged_runs: dict[tuple[str, str], RunCursor] = {}
        self._load_persisted_runs()

    def _load_persisted_runs(self) -> None:
        for project_id in self._projects.stored_project_ids():
            for run_id in self._projects.stored_run_ids(project_id):
                try:
                    self._load_persisted_run(project_id, run_id)
                except (
                    OSError,
                    RuntimeError,
                    StoragePathError,
                    V2RunError,
                ):
                    self._damaged_runs[(project_id, run_id)] = run_cursor(
                        0,
                        project_id=project_id,
                        run_id=run_id,
                    )

    def _load_persisted_run(
        self,
        project_id: str,
        run_id: str,
    ) -> None:
        ledger = Ledger.load(
            self._projects,
            project_id,
            run_id,
            self._ledger_store,
        )
        if ledger is None or not ledger.admitted:
            return
        ledger.reconcile_restart()
        record = _RunRecord(compiled=None, ledger=ledger)
        if ledger.terminal:
            record.mark_worker_completed()
        self.register(project_id, run_id, record)

    def register(
        self,
        project_id: str,
        run_id: str,
        record: _RunRecord,
    ) -> None:
        self._runs[(project_id, run_id)] = record

    def require_record(self, project_id: str, run_id: str) -> _RunRecord:
        try:
            return self._runs[(project_id, run_id)]
        except KeyError as error:
            damaged_cursor = self._damaged_runs.get((project_id, run_id))
            if damaged_cursor is not None:
                raise V2RunError(
                    "evidence_unavailable",
                    "Required Run evidence is damaged and unavailable",
                    details={"last_durable_cursor": damaged_cursor.value},
                ) from error
            raise V2RunError(
                "run_not_found",
                "Run was not found",
                details={"resource_kind": "run", "resource_id": run_id},
            ) from error
