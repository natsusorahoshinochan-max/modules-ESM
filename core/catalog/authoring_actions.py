"""Module-owned read-only inspection and previews before publishing a Run."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from core.catalog.model import FrozenCatalog
    from core.project.manager import ProjectInputDescriptor, ProjectManager
    from core.workflow.authoring import WorkflowAuthoringService


@dataclass(frozen=True, slots=True)
class AuthoringActionContext:
    project_id: str
    projects: ProjectManager
    workflow_authoring: WorkflowAuthoringService
    catalog: FrozenCatalog
    read_input: Callable[[str], tuple[ProjectInputDescriptor, bytes]]


@dataclass(frozen=True, slots=True)
class AuthoringActionDefinition:
    """A module validates its parameters and returns a JSON inspection/preview.

    The handler must not publish data or run a scientific Provider. Prospective
    inputs are request-local; the caller explicitly adopts and saves edits.
    """
    action_id: str
    apply: Callable[[AuthoringActionContext, Mapping[str, Any]], dict[str, Any]]
