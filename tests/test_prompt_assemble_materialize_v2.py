"""Decompose/assemble layout closure, materialize_sequence, observed->conditioning,
and recipe document end-to-end (spec §9.3, §9.4, §9.5, §9.6, §14).

Covers: prompt_authoring.decompose/assemble carry one authoritative layout;
assemble fails on layout mismatch; residue_data.materialize_sequence requires
complete single-chain sequence conditioning; structure_annotation
observed_to_conditioning drops the Candidate subject; and the single
apply_prompt_recipe path from blank document through edits and seeded random
masking.
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any

from datatypes.candidate import CandidateDataReference
from datatypes.prompt import (
    FunctionAnnotation,
    FunctionAnnotationTrack,
    ProteinPrompt,
)
from datatypes.residue import (
    CandidateResidueTrack,
    ResidueLayout,
    ResidueTrack,
)
from datatypes.structure import NamedAtomCoordinates
from modules.prompt_authoring.package import (
    _AssembleOperation,
    _DecomposeOperation,
)
from modules.prompt_authoring.recipe import apply_prompt_recipe
from modules.residue_data.implementation import MaterializeSequenceImplementation
from modules.structure_annotation.implementation import (
    ObservedToConditioningOperation,
)


@dataclass(frozen=True, slots=True)
class _Value:
    value: Any
    canonical_bytes: bytes = b""
    content_digest: str = "x"
    candidate_data: tuple[Any, ...] = ()
    scientific_axes: tuple[Any, ...] = ()
    observation_methods: tuple[Any, ...] = ()


@dataclass(frozen=True, slots=True)
class _Port:
    port_type: Any
    multiplicity: str
    values: tuple[_Value, ...]
    content_digest: str = "x"

    @property
    def value(self) -> Any:
        return self.values[0].value

    def __bool__(self) -> bool:
        return bool(self.values)


@dataclass(frozen=True, slots=True)
class _Call:
    inputs: dict[str, _Port]
    node_parameters: dict[str, Any] = field(default_factory=dict)
    binding_parameters: dict[str, Any] = field(default_factory=dict)
    effective_randomness: dict[str, Any] = field(default_factory=dict)


class _Resources:
    def engine_invocation(self, **_kwargs: Any) -> Any:
        return nullcontext()


def _layout_a() -> ResidueLayout:
    return ResidueLayout(("A:1", "A:2", "A:3"))


def _prompt_port(layout: ResidueLayout, prompt: ProteinPrompt) -> _Port:
    return _Port("protein.prompt", "one", (_Value(value=prompt),))


def _sequence_port(layout: ResidueLayout, values: tuple[Any, ...]) -> _Port:
    return _Port(
        "residue.condition.sequence",
        "one",
        (_Value(value=ResidueTrack(layout, values)),),
    )


def _coordinates_track_port(
    layout: ResidueLayout, values: tuple[Any, ...]
) -> _Port:
    return _Port(
        "residue.condition.coordinates",
        "one",
        (_Value(value=ResidueTrack(layout, values)),),
    )


def _function_annotation_port(
    layout: ResidueLayout,
    annotations: tuple[FunctionAnnotation, ...],
) -> _Port:
    return _Port(
        "residue.condition.function_annotations",
        "one",
        (_Value(value=FunctionAnnotationTrack(layout, annotations)),),
    )


def test_assemble_closure_requires_exact_layout() -> None:
    layout = _layout_a()
    call = _Call(
        inputs={
            "sequence": _sequence_port(layout, ("M", "K", "G")),
            "coordinates": _coordinates_track_port(layout, (None, None, None)),
            "function_annotations": _function_annotation_port(
                layout,
                (
                    FunctionAnnotation(
                        label="site",
                        start_residue_id="A:1",
                        end_residue_id="A:2",
                    ),
                ),
            ),
        }
    )
    prompt = _AssembleOperation().execute(call)["protein_prompt"]
    assert prompt.layout == layout
    assert prompt.sequence == ("M", "K", "G")
    assert prompt.function_annotations[0].label == "site"


def test_assemble_fails_on_layout_mismatch() -> None:
    layout = _layout_a()
    other = ResidueLayout(("A:1", "A:2", "B:1"))
    call = _Call(
        inputs={
            "sequence": _sequence_port(layout, ("M", "K", "G")),
            "coordinates": _coordinates_track_port(other, (None, None, None)),
            "function_annotations": _function_annotation_port(layout, ()),
        }
    )
    try:
        _AssembleOperation().execute(call)
    except ValueError:
        pass
    else:
        raise AssertionError("assemble must reject a mismatched track layout")


def test_decompose_carries_authoritative_layout() -> None:
    layout = _layout_a()
    prompt = ProteinPrompt(
        layout=layout,
        sequence=("M", "K", "G"),
        coordinates=(None, None, None),
        secondary_structure=("H", "E", None),
    )
    call = _Call(inputs={"protein_prompt": _prompt_port(layout, prompt)})
    outputs = _DecomposeOperation().execute(call)
    assert outputs["sequence"].layout == layout
    assert outputs["sequence"].values == ("M", "K", "G")
    assert outputs["coordinates"].layout == layout
    assert outputs["secondary_structure"].layout == layout
    assert outputs["secondary_structure"].values == ("H", "E", None)


def test_materialize_sequence_requires_complete_conditioning() -> None:
    layout = ResidueLayout(("A:1", "A:2"))
    complete = ResidueTrack(layout, ("M", "K"))
    impl = MaterializeSequenceImplementation()
    result = impl.execute(
        _Call(
            inputs={
                "sequence": _Port(
                    "residue.condition.sequence",
                    "one",
                    (_Value(complete),),
                )
            }
        )
    )
    sequence: Any = result["sequence"]
    assert sequence.residue_ids == ("A:1", "A:2")
    assert sequence.sequence == "MK"
    candidates = result["sequence_candidates"]
    assert len(candidates.items) == 1


def test_materialize_sequence_rejects_missing_residue() -> None:
    layout = ResidueLayout(("A:1", "A:2"))
    impl = MaterializeSequenceImplementation()
    try:
        impl.execute(
            _Call(
                inputs={
                    "sequence": _Port(
                        "residue.condition.sequence",
                        "one",
                        (_Value(ResidueTrack(layout, ("M", None))),),
                    )
                }
            )
        )
    except ValueError:
        pass
    else:
        raise AssertionError("materialize_sequence must reject a missing residue")


def test_materialize_sequence_rejects_multi_chain() -> None:
    layout = ResidueLayout(("A:1", "B:1"))
    impl = MaterializeSequenceImplementation()
    try:
        impl.execute(
            _Call(
                inputs={
                    "sequence": _Port(
                        "residue.condition.sequence",
                        "one",
                        (_Value(ResidueTrack(layout, ("M", "K"))),),
                    )
                }
            )
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            "materialize_sequence must reject multi-chain conditioning"
        )


def test_observed_to_conditioning_drops_subject() -> None:
    layout = ResidueLayout(("A:1", "A:2"))
    subject = CandidateDataReference(
        candidate_id="c1",
        data_type_id="protein.structure",
        content_digest="sha256:" + "1" * 64,
    )
    observed = CandidateResidueTrack(
        subject=subject,
        track=ResidueTrack(layout, ("H", "E")),
    )
    call = _Call(
        inputs={
            "secondary_structure": _Port(
                "structure_annotation.secondary_structure.observed",
                "one",
                (_Value(observed),),
            ),
            "sasa": _Port(
                "structure_annotation.sasa.observed",
                "one",
                (),
            ),
        }
    )
    result = ObservedToConditioningOperation(_Resources()).execute(call)
    track = result["secondary_structure"]
    assert isinstance(track, ResidueTrack)
    assert track.layout == layout
    assert track.values == ("H", "E")
    assert not hasattr(track, "subject")


def test_recipe_document_blank_then_edit_then_seeded_mask() -> None:
    document = {"chains": [{"chain_id": "A", "length": 4}]}
    blank = apply_prompt_recipe(
        sequence_source=None,
        structure_source=None,
        prompt_source=None,
        merge_sources=(),
        document=document,
    )
    assert blank.layout.residue_ids == (
        "A:1",
        "A:2",
        "A:3",
        "A:4",
    )
    assert blank.sequence == (None, None, None, None)

    edited = apply_prompt_recipe(
        document={
            **document,
            "track_edits": [
                {
                    "track": "sequence",
                    "action": "replace",
                    "residue_id": "A:2",
                    "value": "G",
                }
            ],
        },
        sequence_source=None,
        structure_source=None,
        prompt_source=None,
        merge_sources=(),
    )
    assert edited.sequence == (None, "G", None, None)

    assigned_edits = [
        {
            "track": "sequence",
            "action": "replace",
            "residue_id": "A:2",
            "value": "G",
        },
        {
            "track": "sequence",
            "action": "replace",
            "residue_id": "A:3",
            "value": "K",
        },
    ]
    masked_once = apply_prompt_recipe(
        document={
            **document,
            "track_edits": assigned_edits,
            "random_operations": [
                {
                    "kind": "mask",
                    "seed": 7,
                    "count": 1,
                    "track": "sequence",
                }
            ],
        },
        sequence_source=None,
        structure_source=None,
        prompt_source=None,
        merge_sources=(),
    )
    # seeded masking is deterministic and only clears one assigned position
    masked_again = apply_prompt_recipe(
        document={
            **document,
            "track_edits": assigned_edits,
            "random_operations": [
                {
                    "kind": "mask",
                    "seed": 7,
                    "count": 1,
                    "track": "sequence",
                }
            ],
        },
        sequence_source=None,
        structure_source=None,
        prompt_source=None,
        merge_sources=(),
    )
    assert masked_once.sequence == masked_again.sequence
    # exactly one of the two assigned positions was masked; A:1 stays missing
    assert masked_once.sequence.count(None) == 3
    assert masked_once.sequence[1] == "G" or masked_once.sequence[2] == "K"
