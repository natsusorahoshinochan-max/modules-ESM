"""Candidate-associated resolved-axis contracts without positional pairing."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
import json

import pytest

from core.catalog.errors import PortValueError
from core.catalog.canonical import canonical_json_bytes
from core.execution.output_admission.admission import (
    NodeOutputPlan,
    OutputPortPlan,
    admit_node_output,
)
from core.operation import (
    OperationCall,
)
from core.scoring.observation_plan import ProducedObservationPlan
from datatypes.candidate import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
)
from datatypes.exact_reference import ExactContractReference
from datatypes.residue import ModifiedResidueNormalizationCollection
from datatypes.structure import ProteinStructure
from modules.structure_transform.domain import (
    CandidateNormalizationFactCollection,
    CandidateModifiedResidueNormalizationAssociation,
    CandidateModifiedResidueNormalizationAssociations,
    CandidateResolvedResidueAxisAssociation,
    CandidateResolvedResidueAxisAssociations,
)
from modules.structure_transform.candidate_transforms import (
    MaterializeCandidateNormalizationsImplementation,
    NormalizeCshParentSpanCandidatesImplementation,
    ResolveCandidateResidueAxesImplementation,
)
from modules.structure_transform.csh_normalization import normalize_csh_parent_span
from modules.structure_transform.residue_axis import resolve_residue_axis
from modules.structure_transform.port_types import (
    CANDIDATE_NORMALIZATION_ASSOCIATIONS_PORT_TYPE,
    CANDIDATE_NORMALIZATION_FACTS_PORT_TYPE,
    CANDIDATE_RESOLVED_AXIS_ASSOCIATIONS_PORT_TYPE,
)
from tests.fixtures.scientific_operation import admitted_port_fixture
from tests.fixtures.structure_transform_sources.package import _FIXTURES


def _operation_call(
    *,
    inputs,
    node_parameters,
    binding_parameters,
    candidate_data=None,
) -> OperationCall:
    references = {} if candidate_data is None else candidate_data
    return OperationCall(
        inputs={
            name: admitted_port_fixture(
                value,
                port_type_id=(
                    "candidate.collection"
                    if name == "structure_candidates"
                    else name
                ),
                value_content_digests=("sha256:" + ("e" * 64),),
                candidate_data=references.get(name, ()),
            )
            for name, value in inputs.items()
        },
        node_parameters=node_parameters,
        binding_parameters=binding_parameters,
        effective_randomness={},
    )


class _RunResources:
    @staticmethod
    def engine_invocation(**kwargs):
        del kwargs
        return nullcontext()


_NORMALIZATION_METHOD = ExactContractReference(
    "method",
    "structure-transform.normalize-csh.fixture",
    "1.0.0",
    "sha256:" + "d" * 64,
)


def _admit_normalization_outputs(
    *,
    call: OperationCall,
    raw_outputs: dict[str, object],
):
    from core.catalog.builtins import builtin_frozen_catalog

    builtins = builtin_frozen_catalog()
    structure_type = builtins.require_port_type("protein.structure", "4.0.0")
    return admit_node_output(
        node_plan=NodeOutputPlan(
            node_id="normalize-csh",
            producing_method=_NORMALIZATION_METHOD,
            output_ports={
                "structure_candidates": OutputPortPlan(
                    required=True,
                    multiplicity="one",
                    port_type=builtins.require_port_type(
                        "candidate.collection",
                        "4.0.0",
                    ),
                ),
                "normalization_facts": OutputPortPlan(
                    required=True,
                    multiplicity="one",
                    port_type=CANDIDATE_NORMALIZATION_FACTS_PORT_TYPE,
                ),
            },
            candidate_data_port_types={"protein.structure": structure_type},
            produced_observations=ProducedObservationPlan(
                binding_method=_NORMALIZATION_METHOD,
            ),
        ),
        admitted_inputs=call.inputs,
        raw_outputs=raw_outputs,
        result_identity="sha256:" + "c" * 64,
    )


def _structure_reference(
    candidate_id: str,
    structure: ProteinStructure,
) -> CandidateDataReference:
    from core.catalog.builtins import (
        builtin_frozen_catalog,
    )

    structure_type = builtin_frozen_catalog().require_port_type(
        "protein.structure",
        "4.0.0",
    )
    return CandidateDataReference(
        candidate_id=candidate_id,
        data_type_id="protein.structure",
        content_digest=structure_type.content_digest(structure),
    )


def _standard_structure(offset: int) -> ProteinStructure:
    return ProteinStructure(
        "ATOM      1  N   ALA A%4d       1.000   2.000   3.000"
        "  1.00 20.00           N  \n"
        "ATOM      2  CA  ALA A%4d       2.000   2.000   3.000"
        "  1.00 20.00           C  \n"
        "ATOM      3  C   ALA A%4d       3.000   2.000   3.000"
        "  1.00 20.00           C  \n"
        "ATOM      4  O   ALA A%4d       4.000   2.000   3.000"
        "  1.00 20.00           O  \n"
        "TER\nEND\n"
        % (offset, offset, offset, offset)
    )


def test_candidate_axis_port_binds_each_axis_to_exact_structure_content() -> None:
    alpha_structure = _standard_structure(1)
    beta_structure = _standard_structure(2)
    alpha = _structure_reference("alpha", alpha_structure)
    beta = _structure_reference("beta", beta_structure)
    associations = CandidateResolvedResidueAxisAssociations(
        entries=(
            CandidateResolvedResidueAxisAssociation(
                subject=beta,
                residue_axis=resolve_residue_axis(beta_structure),
            ),
            CandidateResolvedResidueAxisAssociation(
                subject=alpha,
                residue_axis=resolve_residue_axis(alpha_structure),
            ),
        )
    )

    assert tuple(entry.subject for entry in associations.entries) == (
        alpha,
        beta,
    )
    assert CANDIDATE_RESOLVED_AXIS_ASSOCIATIONS_PORT_TYPE.decode(
        CANDIDATE_RESOLVED_AXIS_ASSOCIATIONS_PORT_TYPE.encode(associations)
    ) == associations
    assert associations.axis_for(beta).structure == beta_structure

    with pytest.raises(PortValueError, match="structure content digest"):
        CANDIDATE_RESOLVED_AXIS_ASSOCIATIONS_PORT_TYPE.encode(
            CandidateResolvedResidueAxisAssociations(
                entries=(
                    replace(
                        associations.entries[0],
                        subject=replace(
                            alpha,
                            content_digest="sha256:" + ("f" * 64),
                        ),
                    ),
                )
            )
        )
    with pytest.raises(PortValueError, match="duplicate Candidate"):
        CANDIDATE_RESOLVED_AXIS_ASSOCIATIONS_PORT_TYPE.encode(
            CandidateResolvedResidueAxisAssociations(
                entries=(associations.entries[0], associations.entries[0])
            )
        )

def test_candidate_normalization_port_is_exact_and_not_position_addressed() -> None:
    structure = _standard_structure(1)
    alpha = _structure_reference("alpha", structure)
    beta = _structure_reference("beta", structure)
    associations = CandidateModifiedResidueNormalizationAssociations(
        entries=(
            CandidateModifiedResidueNormalizationAssociation(
                subject=beta,
                normalizations=ModifiedResidueNormalizationCollection(),
            ),
            CandidateModifiedResidueNormalizationAssociation(
                subject=alpha,
                normalizations=ModifiedResidueNormalizationCollection(),
            ),
        )
    )

    assert tuple(entry.subject for entry in associations.entries) == (
        alpha,
        beta,
    )
    assert CANDIDATE_NORMALIZATION_ASSOCIATIONS_PORT_TYPE.decode(
        CANDIDATE_NORMALIZATION_ASSOCIATIONS_PORT_TYPE.encode(associations)
    ) == associations
    assert associations.normalizations_for(beta) == (
        ModifiedResidueNormalizationCollection()
    )

    with pytest.raises(PortValueError, match="duplicate Candidate"):
        CANDIDATE_NORMALIZATION_ASSOCIATIONS_PORT_TYPE.encode(
            CandidateModifiedResidueNormalizationAssociations(
                entries=(associations.entries[0], associations.entries[0])
            )
        )


def test_candidate_csh_normalization_materializes_after_candidate_admission() -> None:
    raw_structure = ProteinStructure(_FIXTURES["csh"]())
    raw_reference = _structure_reference("raw-csh", raw_structure)
    candidates = CandidateCollection(
        collection_id="raw-structures",
        item_type="protein.structure",
        items=(Candidate("raw-csh", raw_structure),),
    )
    call = _operation_call(
        inputs={"structure_candidates": candidates},
        node_parameters={},
        binding_parameters={},
        candidate_data={"structure_candidates": (raw_reference,)},
    )
    raw_outputs = NormalizeCshParentSpanCandidatesImplementation(
        _RunResources()
    ).execute(call)
    admitted = _admit_normalization_outputs(
        call=call,
        raw_outputs=raw_outputs,
    )
    normalized = admitted.ports["structure_candidates"].value
    facts = admitted.ports["normalization_facts"].value

    assert len(normalized.items) == 1
    assert normalized.items[0].parent_ids == ("raw-csh",)
    assert type(facts) is CandidateNormalizationFactCollection
    assert facts.entries[0].normalizations.entries[0].parent_sequence == "SHG"
    assert facts.entries[0].normalizations.entries[0].parent_residue_ids == (
        "A:65",
        "A:66",
        "A:67",
    )

    admitted_candidate = replace(
        normalized.items[0],
        candidate_id="admitted-normalized-csh",
        metadata={
            **normalized.items[0].metadata,
            "output_port": "structure_candidates",
            "sample_slot": "0:0",
        },
    )
    admitted_reference = _structure_reference(
        admitted_candidate.candidate_id,
        admitted_candidate.data,
    )
    associations = MaterializeCandidateNormalizationsImplementation(
        _RunResources()
    ).execute(
        _operation_call(
            inputs={
                "structure_candidates": CandidateCollection(
                    collection_id=normalized.collection_id,
                    item_type=normalized.item_type,
                    items=(admitted_candidate,),
                ),
                "normalization_facts": facts,
            },
            node_parameters={},
            binding_parameters={},
            candidate_data={"structure_candidates": (admitted_reference,)},
        )
    )["modified_residue_normalizations"]

    assert associations.entries[0].subject == admitted_reference
    assert associations.entries[0].normalizations == facts.entries[0].normalizations


def test_candidate_normalization_facts_reject_noncanonical_wire_order() -> None:
    raw_structure = ProteinStructure(_FIXTURES["csh"]())
    raw_reference = _structure_reference("raw-csh", raw_structure)
    call = _operation_call(
        inputs={
            "structure_candidates": CandidateCollection(
                collection_id="raw-structures",
                item_type="protein.structure",
                items=(
                    Candidate("raw-csh-a", raw_structure),
                    Candidate("raw-csh-b", raw_structure),
                ),
            )
        },
        node_parameters={},
        binding_parameters={},
        candidate_data={
            "structure_candidates": (
                replace(raw_reference, candidate_id="raw-csh-a"),
                replace(raw_reference, candidate_id="raw-csh-b"),
            )
        },
    )
    raw_outputs = NormalizeCshParentSpanCandidatesImplementation(
        _RunResources()
    ).execute(call)
    outputs = _admit_normalization_outputs(
        call=call,
        raw_outputs=raw_outputs,
    )
    facts = outputs.ports["normalization_facts"].value
    wire = json.loads(
        CANDIDATE_NORMALIZATION_FACTS_PORT_TYPE.encode(facts)
    )
    wire["value"]["entries"].reverse()

    with pytest.raises(PortValueError, match="canonically ordered"):
        CANDIDATE_NORMALIZATION_FACTS_PORT_TYPE.decode(
            canonical_json_bytes(wire)
        )


def test_candidate_axis_operation_joins_references_and_normalizations_by_identity(
) -> None:
    csh_structure, csh_normalizations = normalize_csh_parent_span(
        ProteinStructure(_FIXTURES["csh"]())
    )
    standard_structure = _standard_structure(10)
    csh_reference = _structure_reference("z-csh", csh_structure)
    standard_reference = _structure_reference("a-standard", standard_structure)
    candidates = CandidateCollection(
        collection_id="structures",
        item_type="protein.structure",
        items=(
            Candidate("z-csh", csh_structure),
            Candidate("a-standard", standard_structure),
        ),
    )
    normalizations = CandidateModifiedResidueNormalizationAssociations(
        entries=(
            CandidateModifiedResidueNormalizationAssociation(
                subject=csh_reference,
                normalizations=csh_normalizations,
            ),
            CandidateModifiedResidueNormalizationAssociation(
                subject=standard_reference,
                normalizations=ModifiedResidueNormalizationCollection(),
            ),
        )
    )
    call = _operation_call(
        inputs={
            "structure_candidates": candidates,
            "modified_residue_normalizations": normalizations,
        },
        node_parameters={},
        binding_parameters={},
        candidate_data={
            # Deliberately not in CandidateCollection order.
            "structure_candidates": (standard_reference, csh_reference),
        },
    )

    output = ResolveCandidateResidueAxesImplementation(
        _RunResources()
    ).execute(call)["residue_axes"]

    assert tuple(entry.subject for entry in output.entries) == (
        standard_reference,
        csh_reference,
    )
    assert output.axis_for(csh_reference).sequence == "SHG"
    assert len(
        output.axis_for(csh_reference).modified_residue_normalizations.entries
    ) == 1
    assert not output.axis_for(
        standard_reference
    ).modified_residue_normalizations.entries


@pytest.mark.parametrize("case", ["missing", "extra", "digest_conflict"])
def test_candidate_axis_operation_rejects_nonclosed_normalization_association(
    case: str,
) -> None:
    structure = _standard_structure(1)
    subject = _structure_reference("subject", structure)
    other = _structure_reference("other", structure)
    candidates = CandidateCollection(
        collection_id="structures",
        item_type="protein.structure",
        items=(Candidate("subject", structure),),
    )
    association_subjects = {
        "missing": (),
        "extra": (subject, other),
        "digest_conflict": (
            replace(subject, content_digest="sha256:" + ("f" * 64)),
        ),
    }[case]
    normalizations = CandidateModifiedResidueNormalizationAssociations(
        entries=tuple(
            CandidateModifiedResidueNormalizationAssociation(
                association_subject,
                ModifiedResidueNormalizationCollection(),
            )
            for association_subject in association_subjects
        )
    )

    with pytest.raises(ValueError, match="complete exact Candidate references"):
        ResolveCandidateResidueAxesImplementation(_RunResources()).execute(
            _operation_call(
                inputs={
                    "structure_candidates": candidates,
                    "modified_residue_normalizations": normalizations,
                },
                node_parameters={},
                binding_parameters={},
                candidate_data={"structure_candidates": (subject,)},
            )
        )
