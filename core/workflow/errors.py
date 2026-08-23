from __future__ import annotations

from typing import Any


class WorkflowCompileError(ValueError):
    """A Workflow failed static v2 compilation."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        node_id: str | None = None,
        field_path: tuple[str | int, ...] = (),
    ) -> None:
        self.code = code
        self.node_id = node_id
        self.field_path = field_path
        super().__init__(message)

    def issue(self) -> dict[str, Any]:
        issue: dict[str, Any] = {
            "code": self.code,
            "severity": "error",
            "message": str(self),
            "field_path": list(self.field_path),
        }
        if self.node_id is not None:
            issue["node_id"] = self.node_id
        return issue
