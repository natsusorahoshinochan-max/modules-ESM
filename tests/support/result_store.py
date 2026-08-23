"""Construction helpers for the local-substitutable Result Store."""

from __future__ import annotations

from core.execution.results.cache import ProjectReplayIndex
from core.execution.results.store import ResultStore
from core.project.manager import ProjectManager
from core.project.objects import ProjectObjectStore


def result_store(
    projects: ProjectManager,
    replay_index: ProjectReplayIndex | None = None,
) -> ResultStore:
    """Build the exact Result Store composition used by no-model tests."""
    return ResultStore(
        ProjectObjectStore(projects),
        (
            replay_index
            if replay_index is not None
            else ProjectReplayIndex(projects)
        ),
    )
