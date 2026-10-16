"""Prompt module JSON projections for its editing actions."""
from typing import Any
from datatypes.i_json import thaw_i_json
from .authoring import PromptAuthoringPreview, PromptAuthoringSnapshot


def encode_prompt_snapshot(
    snapshot: PromptAuthoringSnapshot,
) -> dict[str, Any]:
    return {
        "document": thaw_i_json(snapshot.document),
        "draft_revision": snapshot.draft_revision,
        "tool_projections": [thaw_i_json(item) for item in snapshot.tool_projections],
        "merge_targets": [thaw_i_json(item) for item in snapshot.merge_targets],
        "residues": [thaw_i_json(item) for item in snapshot.residues],
        "tracks": {
            name: {
                "present": bool(projection["present"]),
                "values": [
                    thaw_i_json(item) for item in projection["values"]
                ],
            }
            for name, projection in snapshot.tracks.items()
        },
        "function_annotations": [
            thaw_i_json(item) for item in snapshot.function_annotations
        ],
        "source": thaw_i_json(snapshot.source),
        "baseline_diagnostics": [item.projection() for item in snapshot.baseline_diagnostics],
        "random_selections": [thaw_i_json(item) for item in snapshot.random_selections],
    }


def encode_prompt_preview(
    preview: PromptAuthoringPreview,
) -> dict[str, Any]:
    return {
        "normalized_document": thaw_i_json(preview.normalized_document),
        "tool_projections": [thaw_i_json(item) for item in preview.tool_projections],
        "merge_targets": [thaw_i_json(item) for item in preview.merge_targets],
        "baseline_diagnostics": [item.projection() for item in preview.baseline_diagnostics],
        "residues": [thaw_i_json(item) for item in preview.residues],
        "tracks": {
            name: {
                "present": bool(projection["present"]),
                "values": [
                    thaw_i_json(item) for item in projection["values"]
                ],
            }
            for name, projection in preview.tracks.items()
        },
        "function_annotations": [
            thaw_i_json(item) for item in preview.function_annotations
        ],
        "changes": [thaw_i_json(item) for item in preview.changes],
        "random_selections": [
            thaw_i_json(item) for item in preview.random_selections
        ],
        "source_merges": [
            thaw_i_json(item) for item in preview.source_merges
        ],
        "diagnostics": [
            diagnostic.projection() for diagnostic in preview.diagnostics
        ],
        "summary": thaw_i_json(preview.summary),
    }
