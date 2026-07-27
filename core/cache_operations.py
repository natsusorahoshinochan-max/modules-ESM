"""Project-scoped public Cache inspection and clearing."""

from __future__ import annotations

from typing import Any

from core.cache_store import CacheStore
from core.project import ProjectManager
from core.recovery import RunRecoveryError
from core.storage import validate_identifier


class CacheService:
    """List or clear contained Cache entries without reading payloads."""

    def __init__(self, project_manager: ProjectManager) -> None:
        self.project_manager = project_manager

    def _require_project(self, project_id: str) -> str:
        safe_project_id = validate_identifier(project_id, "project_id")
        if self.project_manager.load_meta(safe_project_id) is None:
            raise RunRecoveryError(
                "project_not_found",
                "Project was not found",
                status_code=404,
            )
        return safe_project_id

    def _cache_node_ids(self, project_id: str) -> list[str]:
        cache_root = self.project_manager.cache_dir(project_id)
        if not cache_root.exists():
            return []
        node_ids = []
        for child in sorted(cache_root.iterdir(), key=lambda path: path.name):
            if child.name == ".integrity-key":
                continue
            if child.is_symlink():
                raise RunRecoveryError(
                    "invalid_cache_namespace",
                    "Project Cache contains an unsafe Node namespace",
                    status_code=409,
                )
            if not child.is_dir():
                continue
            try:
                node_id = validate_identifier(child.name, "node_id")
            except ValueError:
                continue
            node_ids.append(node_id)
        return node_ids

    def _resolve_scope(
        self,
        project_id: str,
        node_id: str | None,
    ) -> tuple[str, str | None, list[str]]:
        safe_project_id = self._require_project(project_id)
        cached_node_ids = self._cache_node_ids(safe_project_id)
        if node_id is None:
            return safe_project_id, None, cached_node_ids
        safe_node_id = validate_identifier(node_id, "node_id")
        workflow = self.project_manager.load_workflow(safe_project_id)
        if safe_node_id not in workflow.nodes:
            raise RunRecoveryError(
                "node_not_found",
                "Node was not found in the current Workflow",
                status_code=404,
                node_id=safe_node_id,
            )
        selected = (
            [safe_node_id]
            if safe_node_id in cached_node_ids
            else []
        )
        return safe_project_id, safe_node_id, selected

    def entries(
        self,
        project_id: str,
        node_id: str | None = None,
    ) -> dict[str, Any]:
        safe_project_id, safe_node_id, node_ids = self._resolve_scope(
            project_id,
            node_id,
        )
        cache_root = self.project_manager.cache_dir(safe_project_id)
        entries = []
        for cache_node_id in node_ids:
            with CacheStore(cache_root, cache_node_id) as cache:
                entries.extend(cache.entries())
        result: dict[str, Any] = {
            "project_id": safe_project_id,
            "entries": entries,
        }
        if safe_node_id is not None:
            result["node_id"] = safe_node_id
        return result

    def clear(
        self,
        project_id: str,
        node_id: str | None = None,
    ) -> dict[str, Any]:
        safe_project_id, safe_node_id, node_ids = self._resolve_scope(
            project_id,
            node_id,
        )
        cache_root = self.project_manager.cache_dir(safe_project_id)
        removed = 0
        for cache_node_id in node_ids:
            with CacheStore(cache_root, cache_node_id) as cache:
                removed += cache.clear_entries()
        result: dict[str, Any] = {
            "project_id": safe_project_id,
            "status": "cleared",
            "removed": removed,
        }
        if safe_node_id is not None:
            result["node_id"] = safe_node_id
        return result
