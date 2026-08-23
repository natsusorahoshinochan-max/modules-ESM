"""Canonical codecs for Candidate-bound transform facts and associations."""

from __future__ import annotations

from typing import Any, cast

from core.catalog.port_contract import (
    BehaviorReference,
    PortTypeDefinition,
    _candidate_data_reference_from_canonical,
    _candidate_data_reference_to_canonical,
)
from core.operation import (
    CandidateMetadataIdentity,
    EncodedOutputIdentities,
    OutputIdentityIntent,
    OutputIdentitySource,
    ResolvedOutputIdentity,
)
from datatypes.candidate import CandidateDataReference
from datatypes.exact_reference import (
    ExactContractReference,
    ResidueAxisReference,
)
from ._normalization_codec import (
    MODIFIED_RESIDUE_NORMALIZATIONS_PORT_TYPE,
    NORMALIZATION_VERSION,
    normalizations_from_wire,
    normalizations_to_wire,
    validate_normalizations,
)
from ._resolved_axis_codec import (
    RESOLVED_AXIS_PORT_TYPE,
    RESOLVED_AXIS_VERSION,
    _STRUCTURE_CODEC,
    _axis_from_wire,
    _axis_to_wire,
    validate_resolved_axis,
)
from .domain import (
    CandidateNormalizationFact,
    CandidateNormalizationFactCollection,
    CandidateModifiedResidueNormalizationAssociation,
    CandidateModifiedResidueNormalizationAssociations,
    CandidateResolvedResidueAxisAssociation,
    CandidateResolvedResidueAxisAssociations,
    PendingCandidateNormalizationFact,
    PendingCandidateNormalizationFactCollection,
    materialize_candidate_normalization_fact,
)


CANDIDATE_ASSOCIATION_VERSION = "6.0.0"
NORMALIZATION_FACTS_VERSION = "1.0.0"


def _validate_structure_subject(value: object) -> CandidateDataReference:
    if (
        type(value) is not CandidateDataReference
        or value.data_type_id != "protein.structure"
    ):
        raise ValueError(
            "Candidate association subject must be an exact protein.structure "
            "CandidateDataReference"
        )
    return value


def _validate_unique_candidate_subjects(
    subjects: tuple[CandidateDataReference, ...],
) -> None:
    if not subjects:
        raise ValueError("Candidate association collection must be nonempty")
    candidate_ids = [subject.candidate_id for subject in subjects]
    if len(set(candidate_ids)) != len(candidate_ids):
        raise ValueError(
            "Candidate association collection contains a duplicate Candidate"
        )


def validate_candidate_normalization_associations(value: object) -> None:
    """Validate reference-addressed normalization sets without index pairing."""
    if type(value) is not CandidateModifiedResidueNormalizationAssociations:
        raise ValueError(
            "Candidate modified-residue normalizations have the wrong type"
        )
    subjects: list[CandidateDataReference] = []
    for entry in value.entries:
        if type(entry) is not CandidateModifiedResidueNormalizationAssociation:
            raise ValueError(
                "Candidate normalization association has the wrong type"
            )
        subjects.append(_validate_structure_subject(entry.subject))
        validate_normalizations(
            entry.normalizations,
            require_nonempty=False,
        )
    _validate_unique_candidate_subjects(tuple(subjects))


def _candidate_normalizations_to_wire(
    value: CandidateModifiedResidueNormalizationAssociations,
) -> object:
    return {
        "entries": [
            {
                "subject": _candidate_data_reference_to_canonical(entry.subject),
                "normalizations": normalizations_to_wire(
                    entry.normalizations
                ),
            }
            for entry in value.entries
        ]
    }


def _candidate_normalizations_from_wire(value: object) -> object:
    return CandidateModifiedResidueNormalizationAssociations(
        **{
            **value,
            "entries": tuple(
                CandidateModifiedResidueNormalizationAssociation(
                    **{
                        **item,
                        "subject": _candidate_data_reference_from_canonical(
                            item["subject"]
                        ),
                        "normalizations": normalizations_from_wire(
                            item["normalizations"]
                        ),
                    }
                )
                for item in value["entries"]
            ),
        }
    )


def validate_candidate_resolved_axis_associations(value: object) -> None:
    """Validate axes against their exact Candidate structure references."""
    if type(value) is not CandidateResolvedResidueAxisAssociations:
        raise ValueError("Candidate resolved residue axes have the wrong type")
    subjects: list[CandidateDataReference] = []
    for entry in value.entries:
        if type(entry) is not CandidateResolvedResidueAxisAssociation:
            raise ValueError("Candidate residue-axis association has the wrong type")
        subject = _validate_structure_subject(entry.subject)
        validate_resolved_axis(entry.residue_axis)
        if (
            _STRUCTURE_CODEC.content_digest(entry.residue_axis.structure)
            != subject.content_digest
        ):
            raise ValueError(
                "Candidate residue axis contradicts its structure content digest"
            )
        subjects.append(subject)
    _validate_unique_candidate_subjects(tuple(subjects))


def _candidate_axes_to_wire(
    value: CandidateResolvedResidueAxisAssociations,
) -> object:
    return {
        "entries": [
            {
                "subject": _candidate_data_reference_to_canonical(entry.subject),
                "residue_axis": _axis_to_wire(entry.residue_axis),
            }
            for entry in value.entries
        ]
    }


def _candidate_axes_from_wire(value: object) -> object:
    return CandidateResolvedResidueAxisAssociations(
        **{
            **value,
            "entries": tuple(
                CandidateResolvedResidueAxisAssociation(
                    **{
                        **item,
                        "subject": _candidate_data_reference_from_canonical(
                            item["subject"]
                        ),
                        "residue_axis": _axis_from_wire(item["residue_axis"]),
                    }
                )
                for item in value["entries"]
            ),
        }
    )


def _candidate_axis_references(
    value: object,
) -> tuple[ResidueAxisReference, ...]:
    """Project independently identified scalar axes from one association set."""
    admitted = cast(CandidateResolvedResidueAxisAssociations, value)
    reference = RESOLVED_AXIS_PORT_TYPE.reference()
    axis_contract = ExactContractReference(
        contract_kind=reference["contract_kind"],
        contract_id=reference["contract_id"],
        contract_version=reference["contract_version"],
        contract_digest=reference["contract_digest"],
    )
    return tuple(
        ResidueAxisReference(
            axis_kind="resolved_structure",
            axis_contract=axis_contract,
            axis_content_digest=RESOLVED_AXIS_PORT_TYPE.content_digest(
                entry.residue_axis
            ),
            source=entry.subject,
            layout=entry.residue_axis.layout,
        )
        for entry in admitted.entries
    )


def _association_candidate_data_references(
    value: object,
    _candidate_data_port_types: object,
) -> tuple[CandidateDataReference, ...]:
    admitted = cast(Any, value)
    return tuple(entry.subject for entry in admitted.entries)


def _validate_normalization_facts(value: object) -> None:
    if type(value) is not CandidateNormalizationFactCollection:
        raise ValueError("candidate normalization facts have the wrong type")
    for entry in value.entries:
        validate_normalizations(entry.normalizations)


def _normalization_facts_to_wire(
    value: CandidateNormalizationFactCollection,
) -> object:
    return {
        "entries": [
            {
                "normalization_key": entry.normalization_key,
                "structure_content_digest": entry.structure_content_digest,
                "normalizations": normalizations_to_wire(entry.normalizations),
            }
            for entry in value.entries
        ]
    }


def _normalization_facts_from_wire(value: object) -> object:
    entries = tuple(
        CandidateNormalizationFact(
            **{
                **item,
                "normalizations": normalizations_from_wire(
                    item["normalizations"]
                ),
            }
        )
        for item in value["entries"]
    )
    keys = tuple(entry.normalization_key for entry in entries)
    if keys != tuple(sorted(keys)):
        raise ValueError(
            "candidate normalization fact entries are not canonically ordered"
        )
    return CandidateNormalizationFactCollection(**{**value, "entries": entries})


def candidate_normalization_output_identity_intent(
    pending_facts: tuple[PendingCandidateNormalizationFact, ...],
) -> OutputIdentityIntent:
    """Declare normalization identities without executable output callbacks."""
    relation = PendingCandidateNormalizationFactCollection(pending_facts)
    return OutputIdentityIntent(
        identity_sources=tuple(
            source
            for index, pending in enumerate(relation.entries)
            for source in (
                OutputIdentitySource(
                    identity_id=f"structure:{index}",
                    source_role="structure",
                    value=pending.structure,
                ),
                OutputIdentitySource(
                    identity_id=f"normalizations:{index}",
                    source_role="normalizations",
                    value=pending.normalizations,
                ),
            )
        ),
        relation=relation,
    )


def _materialize_candidate_normalization_output_identity(
    relation: object,
    identities: EncodedOutputIdentities,
) -> ResolvedOutputIdentity:
    pending_facts = cast(PendingCandidateNormalizationFactCollection, relation)
    materialized = tuple(
        materialize_candidate_normalization_fact(
            pending,
            structure_content_digest=identities.require(
                f"structure:{index}"
            ).content_digest,
            normalizations_content_digest=identities.require(
                f"normalizations:{index}"
            ).content_digest,
        )
        for index, pending in enumerate(pending_facts.entries)
    )
    return ResolvedOutputIdentity(
        value=CandidateNormalizationFactCollection(
            tuple(item.fact for item in materialized)
        ),
        candidate_metadata=tuple(
            CandidateMetadataIdentity(
                candidate_id=item.candidate_id,
                field_name="normalization_key",
                value=item.normalization_key,
            )
            for item in materialized
        ),
    )


_NORMALIZATION_OUTPUT_IDENTITY_MATERIALIZATION = BehaviorReference(
    (
        "structure_transform.candidate_normalization_facts/"
        "output_identity_materialization"
    ),
    NORMALIZATION_FACTS_VERSION,
    {
        "relation": "pending-candidate-normalization-facts",
        "source_roles": {
            "structure": _STRUCTURE_CODEC.reference(),
            "normalizations": (
                MODIFIED_RESIDUE_NORMALIZATIONS_PORT_TYPE.reference()
            ),
        },
    },
)


CANDIDATE_NORMALIZATION_FACTS_PORT_TYPE = PortTypeDefinition(
    type_id="structure_transform.candidate_normalization_facts",
    version=NORMALIZATION_FACTS_VERSION,
    validator=BehaviorReference(
        "structure_transform.candidate_normalization_facts/validate",
        NORMALIZATION_FACTS_VERSION,
        {
            "accepted_value_kind": "candidate_normalization_fact_collection",
            "candidate_identity": "materialized-only-after-admission",
            "entry_key": "normalization_key",
            "output_identity_materialization": (
                _NORMALIZATION_OUTPUT_IDENTITY_MATERIALIZATION.descriptor()
            ),
        },
    ),
    codec=BehaviorReference(
        "structure_transform.candidate_normalization_facts/codec",
        NORMALIZATION_FACTS_VERSION,
        {"canonicalization": "RFC 8785", "entry_order": "normalization_key"},
    ),
    content_identity=BehaviorReference(
        "structure_transform.candidate_normalization_facts/content",
        NORMALIZATION_FACTS_VERSION,
        {"digest": "SHA-256", "digest_input": "canonical_codec_bytes"},
    ),
    runtime_validator=_validate_normalization_facts,
    runtime_to_wire=_normalization_facts_to_wire,
    runtime_from_wire=_normalization_facts_from_wire,
    output_identity_materialization=(
        _NORMALIZATION_OUTPUT_IDENTITY_MATERIALIZATION
    ),
    runtime_output_identity_materializer=(
        _materialize_candidate_normalization_output_identity
    ),
    output_identity_source_port_types={
        "structure": _STRUCTURE_CODEC,
        "normalizations": MODIFIED_RESIDUE_NORMALIZATIONS_PORT_TYPE,
    },
)


CANDIDATE_NORMALIZATION_ASSOCIATIONS_PORT_TYPE = PortTypeDefinition(
    type_id=(
        "structure_transform."
        "candidate_modified_residue_normalization_associations"
    ),
    version=CANDIDATE_ASSOCIATION_VERSION,
    validator=BehaviorReference(
        (
            "structure_transform."
            "candidate_modified_residue_normalization_associations/validate"
        ),
        CANDIDATE_ASSOCIATION_VERSION,
        {
            "accepted_value_kind": (
                "candidate_modified_residue_normalization_associations"
            ),
            "association_key": "exact-CandidateDataReference",
            "entry_order": "canonical-only-not-correspondence",
            "candidate_coverage": "closed-by-consuming-Node",
            "embedded_normalization_contract": (
                "structure_transform.modified_residue_normalizations@"
                f"{NORMALIZATION_VERSION}"
            ),
        },
    ),
    codec=BehaviorReference(
        (
            "structure_transform."
            "candidate_modified_residue_normalization_associations/codec"
        ),
        CANDIDATE_ASSOCIATION_VERSION,
        {
            "canonicalization": "RFC 8785",
            "association_order": (
                "candidate-id-data-type-id-content-digest"
            ),
        },
    ),
    content_identity=BehaviorReference(
        (
            "structure_transform."
            "candidate_modified_residue_normalization_associations/content"
        ),
        CANDIDATE_ASSOCIATION_VERSION,
        {"digest": "SHA-256", "digest_input": "canonical_codec_bytes"},
    ),
    runtime_validator=validate_candidate_normalization_associations,
    runtime_to_wire=_candidate_normalizations_to_wire,
    runtime_from_wire=_candidate_normalizations_from_wire,
    candidate_data_projection=BehaviorReference(
        "structure_transform.candidate_modified_residue_normalization_"
        "associations/candidate_data_projection",
        CANDIDATE_ASSOCIATION_VERSION,
        {"fields": ["entries[].subject"]},
    ),
    runtime_candidate_data_projection=(
        _association_candidate_data_references
    ),
)


CANDIDATE_RESOLVED_AXIS_ASSOCIATIONS_PORT_TYPE = PortTypeDefinition(
    type_id="structure_transform.candidate_resolved_residue_axis_associations",
    version=CANDIDATE_ASSOCIATION_VERSION,
    validator=BehaviorReference(
        (
            "structure_transform."
            "candidate_resolved_residue_axis_associations/validate"
        ),
        CANDIDATE_ASSOCIATION_VERSION,
        {
            "accepted_value_kind": "candidate_resolved_residue_axis_associations",
            "association_key": "exact-CandidateDataReference",
            "entry_order": "canonical-only-not-correspondence",
            "structure_binding": "subject-content-digest-equals-embedded-structure",
            "embedded_axis_contract": (
                "structure_transform.resolved_residue_axis@"
                f"{RESOLVED_AXIS_VERSION}"
            ),
        },
    ),
    codec=BehaviorReference(
        "structure_transform.candidate_resolved_residue_axis_associations/codec",
        CANDIDATE_ASSOCIATION_VERSION,
        {
            "canonicalization": "RFC 8785",
            "association_order": (
                "candidate-id-data-type-id-content-digest"
            ),
        },
    ),
    content_identity=BehaviorReference(
        (
            "structure_transform."
            "candidate_resolved_residue_axis_associations/content"
        ),
        CANDIDATE_ASSOCIATION_VERSION,
        {"digest": "SHA-256", "digest_input": "canonical_codec_bytes"},
    ),
    runtime_validator=validate_candidate_resolved_axis_associations,
    runtime_to_wire=_candidate_axes_to_wire,
    runtime_from_wire=_candidate_axes_from_wire,
    candidate_data_projection=BehaviorReference(
        "structure_transform.candidate_resolved_residue_axis_associations/"
        "candidate_data_projection",
        CANDIDATE_ASSOCIATION_VERSION,
        {"fields": ["entries[].subject"]},
    ),
    runtime_candidate_data_projection=(
        _association_candidate_data_references
    ),
    scientific_axis_projection=BehaviorReference(
        (
            "structure_transform."
            "candidate_resolved_residue_axis_associations/"
            "scientific_axis_projection"
        ),
        CANDIDATE_ASSOCIATION_VERSION,
        {
            "association_key": "exact-CandidateDataReference",
            "projected_axis_contract": (
                "structure_transform.resolved_residue_axis@"
                f"{RESOLVED_AXIS_VERSION}"
            ),
            "projected_axis_identity": "independent-scalar-codec-digest",
        },
    ),
    runtime_scientific_axis_projection=_candidate_axis_references,
)
