"""Random Insert Masked: randomly insert N sentinel values into a residue track."""

import random
from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import ResidueLayout, ResidueTrack


class RandomInsertMaskedModule(WorkflowModule):
    uses_seed = True

    def __init__(self) -> None:
        d = Path(__file__).parent / "definition.yaml"
        self._definition = ModuleDefinition.from_yaml(d)

    @property
    def definition(self) -> ModuleDefinition:
        return self._definition

    def run(
        self,
        inputs: dict[str, Any],
        parameters: dict[str, Any],
        context: RunContext,
    ) -> dict[str, Any]:
        track: ResidueTrack | None = inputs.get("track")
        secondary_structure_track: ResidueTrack | None = inputs.get(
            "secondary_structure_track"
        )
        layout: ResidueLayout | None = inputs.get("layout")

        if (track is None) == (secondary_structure_track is None):
            raise ValueError("exactly one track input is required")
        output_port = (
            "track"
            if track is not None
            else "secondary_structure_track"
        )
        track = (
            track
            if track is not None
            else secondary_structure_track
        )
        assert track is not None
        if layout is None:
            raise ValueError("layout input is required")

        count = int(parameters.get("count", 0))
        if count < 0:
            raise ValueError(f"count must be non-negative, got {count}")

        L = len(track)
        if count == 0:
            return {output_port: track, "layout": layout}

        # Select insertion positions: each is an index in [0, L] where a
        # sentinel is inserted *before* the element at that index.
        # Index L means append at the end.
        rng = random.Random(context.seed)
        positions = sorted(rng.sample(range(L + 1), count), reverse=True)

        # Insert sentinels from right to left so earlier indices stay valid
        new_values = list(track.values)
        for pos in positions:
            new_values.insert(pos, track.sentinel)

        new_track = ResidueTrack(values=new_values, sentinel=track.sentinel)

        # Update layout
        new_residue_ids = None
        if layout.residue_ids is not None:
            new_residue_ids = list(layout.residue_ids)
            for pos in positions:
                new_residue_ids.insert(pos, None)

        new_layout = ResidueLayout(
            chain_id=layout.chain_id,
            length=layout.length + count,
            residue_ids=new_residue_ids,
        )

        return {output_port: new_track, "layout": new_layout}
