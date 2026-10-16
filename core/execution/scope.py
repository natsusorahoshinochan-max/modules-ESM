"""Immutable requested and admitted Run ranges."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

RunScopeMode = Literal["full", "to_node", "from_node"]


@dataclass(frozen=True, slots=True)
class RunScopeRequest:
    mode: RunScopeMode = "full"
    node_ids: tuple[str, ...] = ()
    source_run_id: str | None = None


@dataclass(frozen=True, slots=True)
class RunExecutionScope:
    mode: RunScopeMode
    selected_node_ids: tuple[str, ...]
    execution_node_ids: tuple[str, ...]
    reused_node_ids: tuple[str, ...]
    out_of_scope_node_ids: tuple[str, ...]
    source_run_id: str | None = None

    def projection(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "selected_node_ids": list(self.selected_node_ids),
            "execution_node_ids": list(self.execution_node_ids),
            "forced_node_ids": (
                list(self.execution_node_ids) if self.mode == "from_node" else []
            ),
            "reused_node_ids": list(self.reused_node_ids),
            "out_of_scope_node_ids": list(self.out_of_scope_node_ids),
            **({"source_run_id": self.source_run_id} if self.source_run_id else {}),
        }

    @classmethod
    def from_projection(cls, value: Mapping[str, Any]) -> RunExecutionScope:
        return cls(
            mode=value["mode"],
            selected_node_ids=tuple(value["selected_node_ids"]),
            execution_node_ids=tuple(value["execution_node_ids"]),
            reused_node_ids=tuple(value["reused_node_ids"]),
            out_of_scope_node_ids=tuple(value["out_of_scope_node_ids"]),
            source_run_id=value.get("source_run_id"),
        )
