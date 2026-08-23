"""Repository-owned built-in nominal Port contracts."""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from datatypes.candidate import CandidateDataReference
from datatypes.observation import (
    PairwiseObservationContext,
)

from .model import FrozenCatalog
from core.catalog.errors import PortValueError
from .port_contract import (
    PORT_TYPE_VERSION,
    PORT_VALUE_NAMESPACE,
    BehaviorReference,
    PortTypeDefinition,
    _BUILTIN_PORT_TYPE_VERSIONS,
)


_BUILTIN_VALUE_KINDS = (
    ("candidate.collection", "candidate_collection"),
    ("candidate.pairing", "pairwise_candidate_mapping"),
    ("protein.sequence", "protein_sequence"),
    ("protein.structure", "protein_structure"),
    ("residue.layout", "residue_layout"),
    ("residue.map", "residue_map"),
    ("residue.track", "residue_track"),
    ("residue.track.sasa", "sasa_residue_track"),
    (
        "residue.track.secondary_structure",
        "secondary_structure_residue_track",
    ),
    ("score.collection", "score_collection"),
    ("text", "text"),
)


def _candidate_collection_data_references(
    value: Any,
    candidate_data_port_types: Mapping[str, PortTypeDefinition],
) -> tuple[CandidateDataReference, ...]:
    try:
        data_port_type = candidate_data_port_types[value.item_type]
    except KeyError as error:
        raise PortValueError(
            f"Candidate collection uses unavailable data Port Type "
            f"{value.item_type!r}"
        ) from error
    return tuple(
        CandidateDataReference(
            candidate_id=candidate.candidate_id,
            data_type_id=value.item_type,
            content_digest=data_port_type.content_digest(candidate.data),
        )
        for candidate in value.items
    )


def _candidate_pairing_data_references(
    value: Any,
    _candidate_data_port_types: Mapping[str, PortTypeDefinition],
) -> tuple[CandidateDataReference, ...]:
    return tuple(
        reference
        for entry in value.entries
        for reference in (entry.subject, entry.reference)
    )


def _score_collection_data_references(
    value: Any,
    _candidate_data_port_types: Mapping[str, PortTypeDefinition],
) -> tuple[CandidateDataReference, ...]:
    references: list[CandidateDataReference] = []
    for observation in value.entries:
        references.append(observation.subject)
        if isinstance(observation.context, PairwiseObservationContext):
            references.extend(
                (
                    observation.context.subject.candidate,
                    observation.context.reference.candidate,
                )
            )
        if (
            observation.residue_axis is not None
            and type(observation.residue_axis.source) is CandidateDataReference
        ):
            references.append(observation.residue_axis.source)
    return tuple(references)


def _builtin_port_type(
    type_id: str,
    value_kind: str,
    *,
    version: str = PORT_TYPE_VERSION,
) -> PortTypeDefinition:
    behavior_prefix = f"protein-workbench.port-type/{type_id}"
    validator_parameters: dict[str, Any] = {
        "accepted_value_kind": value_kind,
        "complete_values_only": True,
    }
    codec_parameters: dict[str, Any] = {
        "canonicalization": "RFC 8785",
        "character_encoding": "UTF-8",
        "envelope_namespace": PORT_VALUE_NAMESPACE,
        "value_kind": value_kind,
    }
    if type_id == "protein.sequence":
        validator_parameters["sequence_invariants"] = {
            "alphabet": "ACDEFGHIKLMNPQRSTVWYBXZJUO",
            "nonempty": True,
            "residue_ids": {
                "cardinality": "absent-or-sequence-length",
                "chain_boundary_constraint": "none",
                "item_contract": "canonical-residue-identity",
                "unique": True,
            },
        }
    if type_id == "candidate.collection":
        validator_parameters["candidate_invariants"] = {
            "candidate_id": "canonical-identifier",
            "parent_ids": {
                "item_contract": "canonical-identifier",
                "ordered": True,
                "unique": True,
            },
            "internal_lineage": {
                "acyclic": True,
                "external_parents": "allowed",
                "self_parent": "rejected",
            },
        }
    if type_id == "candidate.pairing":
        participant_fields = [
            "candidate_id",
            "data_type_id",
            "content_digest",
        ]
        validator_parameters["association_contract"] = {
            "entry_fields": ["subject", "reference"],
            "participant": "CandidateDataReference",
            "participant_fields": participant_fields,
            "cardinality": "one-to-one",
        }
        codec_parameters["entry_wire_shape"] = {
            "subject": participant_fields,
            "reference": participant_fields,
        }
    candidate_projection = {
        "candidate.collection": _candidate_collection_data_references,
        "candidate.pairing": _candidate_pairing_data_references,
        "score.collection": _score_collection_data_references,
    }.get(type_id)
    return PortTypeDefinition(
        type_id=type_id,
        version=version,
        validator=BehaviorReference(
            behavior_id=f"{behavior_prefix}/validate",
            behavior_version=version,
            parameters=validator_parameters,
        ),
        codec=BehaviorReference(
            behavior_id=f"{behavior_prefix}/canonical-json-codec",
            behavior_version=version,
            parameters=codec_parameters,
        ),
        content_identity=BehaviorReference(
            behavior_id=f"{behavior_prefix}/content-sha256",
            behavior_version=version,
            parameters={
                "digest_algorithm": "SHA-256",
                "digest_input": "canonical_codec_bytes",
                "digest_representation": (
                    "sha256:<64 lowercase hexadecimal digits>"
                ),
            },
        ),
        candidate_data_projection=(
            BehaviorReference(
                behavior_id=f"{behavior_prefix}/candidate-data-projection",
                behavior_version=version,
                parameters={
                    "projection": "all-exact-Candidate-Data-References",
                },
            )
            if candidate_projection is not None
            else None
        ),
        runtime_candidate_data_projection=candidate_projection,
    )


@lru_cache(maxsize=1)
def builtin_port_types() -> tuple[PortTypeDefinition, ...]:
    """Return the repository-owned built-in Port Type declarations."""
    return tuple(
        _builtin_port_type(
            type_id,
            value_kind,
            version=_BUILTIN_PORT_TYPE_VERSIONS.get(
                type_id,
                PORT_TYPE_VERSION,
            ),
        )
        for type_id, value_kind in _BUILTIN_VALUE_KINDS
    )


@lru_cache(maxsize=1)
def builtin_frozen_catalog() -> FrozenCatalog:
    """Build and cache the repository-owned built-in Port Type Catalog."""
    from .builder import build_frozen_catalog

    return build_frozen_catalog((), builtin_port_types=builtin_port_types())
