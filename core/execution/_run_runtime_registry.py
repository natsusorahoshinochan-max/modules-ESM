"""Project-scoped in-process and restart registry for Run Runtime."""

from __future__ import annotations

from core.catalog.model import FrozenCatalog
from core.catalog.errors import ContractResolutionError
from core.execution._run_runtime_evidence import _run_catalog_digest
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
        catalog: FrozenCatalog,
        ledger_store: LedgerStore | None,
    ) -> None:
        self._projects = projects
        self._catalog = catalog
        self._ledger_store = ledger_store
        self._runs: dict[tuple[str, str], _RunRecord] = {}
        self._damaged_runs: dict[tuple[str, str], RunCursor] = {}
        self._inactive_runs: dict[tuple[str, str], str] = {}
        self._run_owners: dict[str, str] = {}
        self._load_persisted_runs()

    def _load_persisted_runs(self) -> None:
        for project_id in self._projects.stored_project_ids():
            for run_id in self._projects.stored_run_ids(project_id):
                try:
                    self._load_persisted_run(project_id, run_id)
                except (
                    ContractResolutionError,
                    KeyError,
                    OSError,
                    RuntimeError,
                    StoragePathError,
                    TypeError,
                    V2RunError,
                    ValueError,
                ):
                    self._damaged_runs[(project_id, run_id)] = run_cursor(
                        0,
                        project_id=project_id,
                        run_id=run_id,
                    )
                    self._run_owners.setdefault(run_id, project_id)

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
        owner = self._run_owners.get(run_id)
        if owner is not None and owner != project_id:
            raise RuntimeError("Run identity appears in multiple Projects")
        persisted_catalog_digest = _run_catalog_digest(
            ledger,
            self._catalog,
        )
        if persisted_catalog_digest != self._catalog.contract_digest:
            self._inactive_runs[(project_id, run_id)] = (
                persisted_catalog_digest
            )
            self._run_owners[run_id] = project_id
            return
        ledger.reconcile_restart()
        record = _RunRecord(compiled=None, ledger=ledger)
        if ledger.terminal:
            record.finished.set()
        self.register(project_id, run_id, record)

    def register(
        self,
        project_id: str,
        run_id: str,
        record: _RunRecord,
    ) -> None:
        owner = self._run_owners.get(run_id)
        if owner is not None and owner != project_id:
            raise RuntimeError("Run identity appears in multiple Projects")
        self._runs[(project_id, run_id)] = record
        self._run_owners[run_id] = project_id

    def require_record(self, project_id: str, run_id: str) -> _RunRecord:
        owner = self._run_owners.get(run_id)
        if owner is not None and owner != project_id:
            raise V2RunError(
                "cross_scope_access_denied",
                "Run does not belong to the requested Project",
                details={
                    "requested_project_id": project_id,
                    "requested_run_id": run_id,
                },
            )
        try:
            return self._runs[(project_id, run_id)]
        except KeyError as error:
            inactive_catalog_digest = self._inactive_runs.get(
                (project_id, run_id)
            )
            if inactive_catalog_digest is not None:
                raise V2RunError(
                    "inactive_generation",
                    "Run evidence belongs to an inactive Catalog generation",
                    details={
                        "artifact_kind": "run_evidence",
                        "expected_catalog_contract_digest": (
                            self._catalog.contract_digest
                        ),
                        "received_catalog_contract_digest": (
                            inactive_catalog_digest
                        ),
                    },
                ) from error
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

    @staticmethod
    def require_available_evidence(record: _RunRecord) -> None:
        unavailable = record.evidence_unavailable
        if unavailable is not None:
            raise V2RunError(
                unavailable.code,
                str(unavailable),
                details=unavailable.details,
            ) from unavailable
