"""Canonical Candidate parent-lineage admission and normalization tests."""

from __future__ import annotations

import pytest

from core.catalog.builtins import (
    builtin_frozen_catalog,
)
from core.catalog.errors import PortValueError
from core.catalog.canonical import canonical_sha256
from core.execution.output_admission.admission import (
    NodeOutputPlan,
    OutputPortPlan,
    admit_node_output,
)
from core.operation import AdmittedPort
from core.scoring.observation_plan import ProducedObservationPlan
from tests.support.output_admission import (
    admit_fixture_port,
)
from datatypes.candidate import (
    Candidate,
    CandidateCollection,
)
from datatypes.exact_reference import ExactContractReference
from datatypes.sequence import ProteinSequence


_RESULT_IDENTITY = "sha256:" + ("c" * 64)
_BUILTINS = builtin_frozen_catalog()
_SEQUENCE_PORT_TYPE = _BUILTINS.require_port_type(
    "protein.sequence", "3.0.0"
)
_CANDIDATE_COLLECTION_PORT_TYPE = _BUILTINS.require_port_type(
    "candidate.collection", "4.0.0"
)
_METHOD = ExactContractReference(
    "method",
    "test.candidate-lineage.method",
    "1.0.0",
    "sha256:" + ("1" * 64),
)
_PARENT_DIGEST = _SEQUENCE_PORT_TYPE.content_digest(ProteinSequence("AA"))


def _admit_candidate_outputs(
    outputs: dict[str, CandidateCollection],
    *,
    inputs: dict[str, AdmittedPort] | None = None,
) -> None:
    admit_node_output(
        node_plan=NodeOutputPlan(
            node_id="producer",
            producing_method=_METHOD,
            output_ports={
                output_port: OutputPortPlan(
                    required=True,
                    multiplicity="one",
                    port_type=_CANDIDATE_COLLECTION_PORT_TYPE,
                )
                for output_port in outputs
            },
            candidate_data_port_types={
                "protein.sequence": _SEQUENCE_PORT_TYPE,
            },
            produced_observations=ProducedObservationPlan(
                binding_method=_METHOD,
            ),
        ),
        admitted_inputs=inputs or {},
        raw_outputs=outputs,
        result_identity=_RESULT_IDENTITY,
    )


@pytest.mark.parametrize(
    "parent_ids",
    (
        ("candidate parent",),
        ("candidate-parent", "candidate-parent"),
    ),
)
def test_candidate_collection_rejects_noncanonical_or_duplicate_parent_ids(
    parent_ids: tuple[str, ...],
) -> None:
    port_type = builtin_frozen_catalog().require_port_type(
        "candidate.collection",
        "4.0.0",
    )
    value = CandidateCollection(
        "collection",
        "protein.sequence",
        (
            Candidate(
                "candidate-child",
                ProteinSequence("MA"),
                parent_ids,
            ),
        ),
    )

    with pytest.raises(PortValueError, match="parent_ids|parent identit"):
        port_type.encode(value)


@pytest.mark.parametrize(
    "replacements",
    (
        ((b'"parent-aaaa"', b'"parent aaaa"'),),
        ((b'"parent-bbbb"', b'"parent-aaaa"'),),
    ),
)
def test_candidate_collection_codec_rejects_invalid_parent_ids(
    replacements: tuple[tuple[bytes, bytes], ...],
) -> None:
    port_type = builtin_frozen_catalog().require_port_type(
        "candidate.collection",
        "4.0.0",
    )
    canonical = port_type.encode(
        CandidateCollection(
            "collection",
            "protein.sequence",
            (
                Candidate(
                    "candidate-a",
                    ProteinSequence("MA"),
                    ("parent-aaaa", "parent-bbbb"),
                ),
            ),
        )
    )
    malformed = canonical
    for old, new in replacements:
        malformed = malformed.replace(old, new)

    with pytest.raises(PortValueError, match="parent_ids|parent identit"):
        port_type.decode(malformed)


@pytest.mark.parametrize(
    "items",
    (
        (
            Candidate(
                "candidate-a",
                ProteinSequence("MA"),
                ("candidate-a",),
            ),
        ),
        (
            Candidate(
                "candidate-a",
                ProteinSequence("MA"),
                ("candidate-b",),
            ),
            Candidate(
                "candidate-b",
                ProteinSequence("MG"),
                ("candidate-a",),
            ),
        ),
    ),
)
def test_candidate_collection_rejects_internal_lineage_cycles_on_encode(
    items: tuple[Candidate, ...],
) -> None:
    port_type = builtin_frozen_catalog().require_port_type(
        "candidate.collection",
        "4.0.0",
    )

    with pytest.raises(PortValueError, match="self-parent|contains a cycle"):
        port_type.encode(
            CandidateCollection("collection", "protein.sequence", items)
        )


@pytest.mark.parametrize(
    "replacements",
    (
        ((b'"parent-xxxx"', b'"candidate-a"'),),
        (
            (b'"parent-xxxx"', b'"candidate-b"'),
            (b'"parent-yyyy"', b'"candidate-a"'),
        ),
    ),
)
def test_candidate_collection_codec_rejects_internal_lineage_cycles(
    replacements: tuple[tuple[bytes, bytes], ...],
) -> None:
    port_type = builtin_frozen_catalog().require_port_type(
        "candidate.collection",
        "4.0.0",
    )
    canonical = port_type.encode(
        CandidateCollection(
            "collection",
            "protein.sequence",
            (
                Candidate(
                    "candidate-a",
                    ProteinSequence("MA"),
                    ("parent-xxxx",),
                ),
                Candidate(
                    "candidate-b",
                    ProteinSequence("MG"),
                    ("parent-yyyy",),
                ),
            ),
        )
    )
    malformed = canonical
    for old, new in replacements:
        malformed = malformed.replace(old, new)

    with pytest.raises(PortValueError, match="self-parent|contains a cycle"):
        port_type.decode(malformed)


def test_output_admission_rejects_parent_ids_that_converge() -> None:
    normalized_parent_id = "candidate-" + canonical_sha256(
        {
            "schema_namespace": "protein-workbench-candidate/v2",
            "producer_result_identity": _RESULT_IDENTITY,
            "output_port": "parents",
            "sample_slot": "0:0",
            "parent_candidate_identities": [],
            "content_digest": _PARENT_DIGEST,
        }
    ).removeprefix("sha256:")
    admitted_parent = Candidate(
        normalized_parent_id,
        ProteinSequence("AA"),
    )

    with pytest.raises(
        PortValueError,
        match="contains duplicate parent identities",
    ):
        _admit_candidate_outputs(
            {
                "parents": CandidateCollection(
                    "raw-parents",
                    "protein.sequence",
                    (Candidate("raw-parent", ProteinSequence("AA")),),
                ),
                "children": CandidateCollection(
                    "raw-children",
                    "protein.sequence",
                    (
                        Candidate(
                            "raw-child",
                            ProteinSequence("AT"),
                            ("raw-parent", normalized_parent_id),
                        ),
                    ),
                ),
            },
            inputs={
                "admitted_parents": admit_fixture_port(
                    port_type=_BUILTINS.require_port_type(
                        "candidate.collection", "4.0.0"
                    ),
                    multiplicity="one",
                    values=(
                        CandidateCollection(
                            "admitted-parents",
                            "protein.sequence",
                            (admitted_parent,),
                        ),
                    ),
                    candidate_data_port_types={
                        "protein.sequence": _SEQUENCE_PORT_TYPE,
                    },
                ),
            },
        )
