"""Canonical codecs for Candidate-bound transform facts and associations."""

from __future__ import annotations

from typing import Any, cast

from core.catalog.port_contract import (
    BehaviorReference,
    PortTypeDefinition,
    _candidate_data_reference_from_canonical,
    _candidate_data_reference_to_canonical,
)
from datatypes.candidate import CandidateDataReference
from datatypes.exact_reference import (
    ExactContractReference,
    ResidueAxisReference,
)
from datatypes.structure import ResolvedStructureResidueAxis

from ._normalization_codec import (
    NORMALIZATION_VERSION,
    normalizations_from_wire,
    normalizations_to_wire,
    validate_normalizations,
)
from ._resolved_axis_codec import (
    RESOLVED_AXIS_PORT_TYPE,
    RESOLVED_AXIS_VERSION,
    _STRUCTURE_CODEC,
    _closed_dict,
    _decode_value,
    _wire_value,
    validate_resolved_axis,
)
from .domain import (
    CandidateNormalizationFact,
    CandidateNormalizationFactCollection,
    CandidateModifiedResidueNormalizationAssociation,
    CandidateModifiedResidueNormalizationAssociations,
    CandidateResolvedResidueAxisAssociation,
    CandidateResolvedResidueAxisAssociations,
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


def _candidate_normalizations_to_wire(value: object) -> object:
    assert type(value) is CandidateModifiedResidueNormalizationAssociations
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
    decoded = _closed_dict(
        value,
        {"entries"},
        subject="Candidate normalization associations",
    )
    if not isinstance(decoded["entries"], list):
        raise ValueError(
            "Candidate normalization association entries must be a list"
        )
    entries: list[CandidateModifiedResidueNormalizationAssociation] = []
    for item in decoded["entries"]:
        item = _closed_dict(
            item,
            {"subject", "normalizations"},
            subject="Candidate normalization association",
        )
        entries.append(
            CandidateModifiedResidueNormalizationAssociation(
                subject=_candidate_data_reference_from_canonical(item["subject"]),
                normalizations=normalizations_from_wire(
                    item["normalizations"],
                    require_nonempty=False,
                ),
            )
        )
    result = CandidateModifiedResidueNormalizationAssociations(
        entries=tuple(entries)
    )
    validate_candidate_normalization_associations(result)
    return result


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


def _candidate_axes_to_wire(value: object) -> object:
    assert type(value) is CandidateResolvedResidueAxisAssociations
    return {
        "entries": [
            {
                "subject": _candidate_data_reference_to_canonical(entry.subject),
                "residue_axis": _wire_value(
                    RESOLVED_AXIS_PORT_TYPE,
                    entry.residue_axis,
                ),
            }
            for entry in value.entries
        ]
    }


def _candidate_axes_from_wire(value: object) -> object:
    decoded = _closed_dict(
        value,
        {"entries"},
        subject="Candidate residue-axis associations",
    )
    if not isinstance(decoded["entries"], list):
        raise ValueError("Candidate residue-axis entries must be a list")
    entries: list[CandidateResolvedResidueAxisAssociation] = []
    for item in decoded["entries"]:
        item = _closed_dict(
            item,
            {"subject", "residue_axis"},
            subject="Candidate residue-axis association",
        )
        residue_axis = _decode_value(
            RESOLVED_AXIS_PORT_TYPE,
            item["residue_axis"],
        )
        if type(residue_axis) is not ResolvedStructureResidueAxis:
            raise ValueError("Candidate residue axis has the wrong runtime type")
        entries.append(
            CandidateResolvedResidueAxisAssociation(
                subject=_candidate_data_reference_from_canonical(item["subject"]),
                residue_axis=residue_axis,
            )
        )
    return CandidateResolvedResidueAxisAssociations(entries=tuple(entries))


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
    normalized = CandidateNormalizationFactCollection(value.entries)
    if normalized != value:
        raise ValueError("candidate normalization facts are not canonical")


def _normalization_facts_to_wire(value: object) -> object:
    assert type(value) is CandidateNormalizationFactCollection
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
    decoded = _closed_dict(
        value,
        {"entries"},
        subject="candidate normalization facts",
    )
    if not isinstance(decoded["entries"], list):
        raise ValueError("candidate normalization fact entries must be a list")
    entries: list[CandidateNormalizationFact] = []
    for item in decoded["entries"]:
        item = _closed_dict(
            item,
            {
                "normalization_key",
                "structure_content_digest",
                "normalizations",
            },
            subject="candidate normalization fact",
        )
        if (
            type(item["normalization_key"]) is not str
            or type(item["structure_content_digest"]) is not str
        ):
            raise ValueError("candidate normalization fact fields are invalid")
        entries.append(
            CandidateNormalizationFact(
                normalization_key=item["normalization_key"],
                structure_content_digest=item["structure_content_digest"],
                normalizations=normalizations_from_wire(item["normalizations"]),
            )
        )
    keys = [entry.normalization_key for entry in entries]
    if len(set(keys)) != len(keys) or keys != sorted(keys):
        raise ValueError(
            "candidate normalization fact entries are not canonically ordered"
        )
    result = CandidateNormalizationFactCollection(tuple(entries))
    _validate_normalization_facts(result)
    return result


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
