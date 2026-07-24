"""Run context passed to each module during execution."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import uuid


@dataclass
class RunContext:
    """Execution context for a single node run.

    project_dir: root directory of the project being executed.
    node_id: the executing node's ID.
    run_id: unique identifier for this execution run.
    seed: random seed for reproducibility.
    temp_dir: temporary working directory for this node.
    """

    project_dir: str
    node_id: str
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    seed: int = 42
    temp_dir: Optional[str] = None

    def __post_init__(self) -> None:
        if self.temp_dir is None:
            self.temp_dir = str(Path(self.project_dir) / "temp" / self.node_id)
