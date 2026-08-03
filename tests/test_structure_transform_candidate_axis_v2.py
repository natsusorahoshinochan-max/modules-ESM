"""Candidate-associated resolved-axis contracts without positional pairing."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace

import pytest

from core import InputContentDigests, OperationCall, PortValueError
from datatypes import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
    ModifiedResidueNormalizationCollection,
    ProteinStructure,
)
from modules.structure_transform import (
    CandidateModifiedResidueNormalizationAssociation,
    CandidateModifiedResidueNormalizationAssociations,
    CandidateResolvedResidueAxisAssociation,
    CandidateResolvedResidueAxisAssociations,
)
from modules.structure_transform.implementation import (
    ResolveCandidateResidueAxesImplementation,
    normalize_csh_parent_span,
    resolve_residue_axis,
)
from modules.structure_transform.port_types import (
    CANDIDATE_NORMALIZATION_ASSOCIATIONS_PORT_TYPE,
    CANDIDATE_RESOLVED_AXIS_ASSOCIATIONS_PORT_TYPE,
)
from tests.fixtures.structure_transform_sources.package import _FIXTURES


class _RunResources:
    @staticmethod
    def engine_invocation(**kwargs):
        del kwargs
        return nullcontext()


def _structure_reference(
    candidate_id: str,
    structure: ProteinStructure,
) -> CandidateDataReference:
    from core import builtin_frozen_catalog

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
    call = OperationCall(
        inputs={
            "structure_candidates": candidates,
            "modified_residue_normalizations": normalizations,
        },
        node_parameters={},
        binding_parameters={},
        input_content_digests={
            "structure_candidates": InputContentDigests(
                port_type_id="candidate.collection",
                value_content_digests=("sha256:" + ("e" * 64),),
                # Deliberately not in CandidateCollection order.
                candidate_data=(standard_reference, csh_reference),
            ),
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
            OperationCall(
                inputs={
                    "structure_candidates": candidates,
                    "modified_residue_normalizations": normalizations,
                },
                node_parameters={},
                binding_parameters={},
                input_content_digests={
                    "structure_candidates": InputContentDigests(
                        port_type_id="candidate.collection",
                        value_content_digests=("sha256:" + ("e" * 64),),
                        candidate_data=(subject,),
                    ),
                },
            )
        )


@pytest.mark.parametrize("case", ["missing", "duplicate", "extra", "structure"])
def test_candidate_axis_operation_rejects_incomplete_or_conflicting_evidence(
    case: str,
) -> None:
    structure = _standard_structure(1)
    subject = _structure_reference("subject", structure)
    other = _structure_reference("other", structure)
    candidate_items = {
        "missing": (Candidate("subject", structure),),
        "duplicate": (Candidate("subject", structure),),
        "extra": (Candidate("subject", structure),),
        "structure": (Candidate("subject", _standard_structure(2)),),
    }[case]
    evidence = {
        "missing": (),
        "duplicate": (subject, subject),
        "extra": (subject, other),
        "structure": (subject,),
    }[case]

    with pytest.raises(ValueError, match="complete exact Candidate references"):
        ResolveCandidateResidueAxesImplementation(_RunResources()).execute(
            OperationCall(
                inputs={
                    "structure_candidates": CandidateCollection(
                        collection_id="structures",
                        item_type="protein.structure",
                        items=candidate_items,
                    )
                },
                node_parameters={},
                binding_parameters={},
                input_content_digests={
                    "structure_candidates": InputContentDigests(
                        port_type_id="candidate.collection",
                        value_content_digests=("sha256:" + ("e" * 64),),
                        candidate_data=evidence,
                    ),
                },
            )
        )
