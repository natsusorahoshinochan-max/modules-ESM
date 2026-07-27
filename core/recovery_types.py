"""Typed recovery intent passed from API planning into run provenance."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class RecoveryAction(str, Enum):
    """One supported Node recovery operation."""

    RETRY = "retry"
    FORCE_RERUN = "force_rerun"


@dataclass(frozen=True)
class RecoveryProvenance:
    """Immutable facts explaining why a recovery run bypassed Cache."""

    source_run_id: str
    action: RecoveryAction
    selected_node_id: str
    forced_node_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        descendants = (
            "cache_bypassed"
            if self.action is RecoveryAction.FORCE_RERUN
            else "cache_eligible"
        )
        return {
            "source_run_id": self.source_run_id,
            "action": self.action.value,
            "selected_node_id": self.selected_node_id,
            "forced_node_ids": list(self.forced_node_ids),
            "dependency_semantics": {
                "ancestors": "cache_eligible",
                "selected": "cache_bypassed",
                "descendants": descendants,
                "unrelated": "cache_eligible",
            },
        }


@dataclass(frozen=True)
class RecoveryPlan:
    """Validated seed and Cache bypass set for a new recovery run."""

    seed: int
    force_rerun_nodes: tuple[str, ...]
    provenance: RecoveryProvenance
