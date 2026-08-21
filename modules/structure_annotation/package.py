"""The single production registration for structure annotations."""

from __future__ import annotations

from collections.abc import Mapping
import json
import math
from typing import Any, cast

from core import (
    AvailabilityDeclaration,
    AvailabilityResult,
    BehaviorReference,
    ContractIdentity,
    DefinitionResource,
    ExecutionBindingDefinition,
    MethodDefinition,
    ModulePackageRegistration,
    OperationContext,
    PortTypeDefinition,
    ProducedObservationDefinition,
    ReadinessCheckInput,
    ReadinessDeclaration,
    ReadinessResult,
    ScientificOperation,
    ScientificOperationFactory,
    builtin_frozen_catalog,
)
from core.port_types import canonical_json_bytes
from datatypes import CandidateDataReference, ResidueLayout, ResidueTrack
from datatypes.protein import validate_residue_layout

from .adapter import (
    MKDSSP_BINARY,
    MKDSSP_SOURCE_ARCHIVE_SHA256,
    MKDSSP_SOURCE_REPOSITORY,
    MKDSSP_SOURCE_REVISION,
    MKDSSP_VERSION,
    MkdsspAdapter,
    mkdssp_provider_identity,
    mkdssp_readiness,
)
from .domain import DSSPAnnotation, StructureAnnotationTrack
from .implementation import (
    ApplySASAToPromptOperation,
    ApplySecondaryStructureToPromptOperation,
    DSSPComputeOperation,
    ExpectedSecondaryStructureFromPromptOperation,
    SASAComputeOperation,
    SecondaryStructureAgreementOperation,
    SecondaryStructureExtractOperation,
)


_PACKAGE_VERSION = "3.0.0"
_VERSION = "2.1.0"
_METHOD_VERSION = "2.2.0"
_PORT_VERSION = "4.0.0"
_METRIC_VERSION = "3.0.0"
_NODE_BINDING_VERSIONS = {
    "dssp_compute": "7.0.0",
    "secondary_structure_extract": "4.0.0",
    "sasa_compute": "4.0.0",
    "secondary_structure_agreement": "6.0.0",
    "apply_secondary_structure_to_prompt": "5.0.0",
    "apply_sasa_to_prompt": "5.0.0",
    "expected_secondary_structure_from_prompt": "6.0.0",
}
_METHOD_VERSIONS = {
    "dssp_compute": "3.0.0",
    "secondary_structure_extract": "3.0.0",
    "sasa_compute": "3.0.0",
    "secondary_structure_agreement": "3.0.0",
    "apply_secondary_structure_to_prompt": _METHOD_VERSION,
    "apply_sasa_to_prompt": _METHOD_VERSION,
    "expected_secondary_structure_from_prompt": "3.0.0",
}
_DSSP_READINESS_BEHAVIOR_VERSION = "2.2.0"
_OPERATIONS = (
    "dssp_compute",
    "secondary_structure_extract",
    "sasa_compute",
    "secondary_structure_agreement",
    "apply_secondary_structure_to_prompt",
    "apply_sasa_to_prompt",
    "expected_secondary_structure_from_prompt",
)
_DSSP_OPERATION = "dssp_compute"
_ANNOTATION_SECONDARY_SYMBOLS = frozenset("GHITEBSPC_")
_SECONDARY_SYMBOLS = frozenset("GHITEBSC_")
_BUILTINS = builtin_frozen_catalog()
_LAYOUT_CODEC = _BUILTINS.require_port_type("residue.layout", "3.0.0")
_TRACK_CODEC = _BUILTINS.require_port_type("residue.track", _VERSION)
_ABSOLUTE_SASA_QUANTITY_CONTRACT = {
    "quantity": "solvent_accessible_surface_area",
    "measure": "absolute",
    "unit": "angstrom_squared",
    "granularity": "per_residue",
    "normalization": "none",
}


def _wire_value(codec: PortTypeDefinition, value: object) -> object:
    return json.loads(codec.encode(value))["value"]


def _decode_value(codec: PortTypeDefinition, value: object) -> object:
    return codec.decode(
        canonical_json_bytes(
            {
                "schema_namespace": "protein-workbench-port-value/v2",
                "port_type_id": codec.type_id,
                "port_type_version": codec.version,
                "value": value,
            }
        )
    )


def _validate_layout(layout: object) -> ResidueLayout:
    return validate_residue_layout(layout, subject="annotation layout")


def _validate_subject(subject: object) -> CandidateDataReference:
    if type(subject) is not CandidateDataReference:
        raise ValueError(
            "annotation subject must be a CandidateDataReference"
        )
    return subject


def _validate_secondary(
    values: object,
    *,
    length: int,
    symbols: frozenset[str] = _SECONDARY_SYMBOLS,
) -> tuple[str, ...]:
    if (
        not isinstance(values, tuple)
        or len(values) != length
        or any(
            type(value) is not str or value not in symbols
            for value in values
        )
    ):
        raise ValueError(
            "secondary-structure values use an unsupported alphabet"
        )
    return values


def _validate_sasa(
    values: object,
    *,
    length: int,
) -> tuple[float | None, ...]:
    if not isinstance(values, tuple) or len(values) != length:
        raise ValueError("SASA values must match the exact residue layout")
    for value in values:
        if value is None:
            continue
        if (
            type(value) not in {int, float}
            or not math.isfinite(float(value))
            or float(value) < 0
        ):
            raise ValueError("SASA values must be nullable non-negative numbers")
    return tuple(
        None if value is None else float(value)
        for value in values
    )


def _validate_annotation(value: object) -> None:
    if type(value) is not DSSPAnnotation:
        raise ValueError("DSSP annotation has the wrong runtime type")
    _validate_subject(value.subject)
    layout = _validate_layout(value.layout)
    _validate_secondary(
        value.secondary_structure,
        length=layout.length,
        symbols=_ANNOTATION_SECONDARY_SYMBOLS,
    )
    _validate_sasa(value.sasa, length=layout.length)


def _annotation_to_wire(value: object) -> object:
    assert type(value) is DSSPAnnotation
    return {
        "subject": value.subject.to_public(),
        "layout": _wire_value(_LAYOUT_CODEC, value.layout),
        "secondary_structure": list(value.secondary_structure),
        "sasa": list(value.sasa),
    }


def _annotation_from_wire(value: object) -> object:
    if (
        not isinstance(value, dict)
        or set(value)
        != {"subject", "layout", "secondary_structure", "sasa"}
        or not isinstance(value["secondary_structure"], list)
        or not isinstance(value["sasa"], list)
    ):
        raise ValueError("DSSP annotation wire value is not closed")
    layout = _decode_value(_LAYOUT_CODEC, value["layout"])
    annotation = DSSPAnnotation(
        subject=CandidateDataReference.from_public(value["subject"]),
        layout=layout,
        secondary_structure=tuple(value["secondary_structure"]),
        sasa=_validate_sasa(tuple(value["sasa"]), length=layout.length),
    )
    return annotation


def _validate_secondary_track(value: object) -> None:
    if type(value) is not StructureAnnotationTrack:
        raise ValueError("secondary-structure track has the wrong runtime type")
    _validate_subject(value.subject)
    layout = _validate_layout(value.layout)
    _validate_secondary(value.values, length=layout.length)


def _validate_sasa_track(value: object) -> None:
    if type(value) is not StructureAnnotationTrack:
        raise ValueError("SASA track has the wrong runtime type")
    _validate_subject(value.subject)
    layout = _validate_layout(value.layout)
    _validate_sasa(value.values, length=layout.length)


def _track_to_wire(kind: str):
    def encode(value: object) -> object:
        assert type(value) is StructureAnnotationTrack
        return {
            "subject": value.subject.to_public(),
            "layout": _wire_value(_LAYOUT_CODEC, value.layout),
            "track": _wire_value(
                _TRACK_CODEC,
                ResidueTrack(list(value.values), None),
            ),
        }

    return encode


def _track_from_wire(kind: str):
    def decode(value: object) -> object:
        if (
            not isinstance(value, dict)
            or set(value) != {"subject", "layout", "track"}
        ):
            raise ValueError("annotation track wire value is not closed")
        track = _decode_value(_TRACK_CODEC, value["track"])
        if type(track) is not ResidueTrack or track.sentinel is not None:
            raise ValueError("annotation track must use null semantics")
        layout = _decode_value(_LAYOUT_CODEC, value["layout"])
        values = tuple(track.values)
        if kind == "sasa":
            values = _validate_sasa(values, length=layout.length)
        annotation_track = StructureAnnotationTrack(
            subject=CandidateDataReference.from_public(value["subject"]),
            layout=layout,
            values=values,
        )
        return annotation_track

    return decode


def _available() -> AvailabilityResult:
    return AvailabilityResult.available()


def _dssp_ready(check_input: ReadinessCheckInput) -> ReadinessResult:
    return mkdssp_readiness(check_input.values)


def _ready(check_input: ReadinessCheckInput) -> ReadinessResult:
    del check_input
    return ReadinessResult(True)


def _build(operation: str):
    def factory(context: OperationContext) -> ScientificOperation:
        if operation == "dssp_compute":
            return DSSPComputeOperation(
                MkdsspAdapter(
                    environment=context.environment,
                    resources=context.resources,
                )
            )
        if operation == "secondary_structure_extract":
            return SecondaryStructureExtractOperation(context.resources)
        if operation == "sasa_compute":
            return SASAComputeOperation(context.resources)
        if operation == "secondary_structure_agreement":
            return SecondaryStructureAgreementOperation(
                resources=context.resources,
                method=context.method,
                produced_observations=context.produced_observations,
            )
        if operation == "apply_secondary_structure_to_prompt":
            return ApplySecondaryStructureToPromptOperation(context.resources)
        if operation == "apply_sasa_to_prompt":
            return ApplySASAToPromptOperation(context.resources)
        if operation == "expected_secondary_structure_from_prompt":
            return ExpectedSecondaryStructureFromPromptOperation(
                context.resources
            )
        raise RuntimeError("unknown structure annotation operation")

    return factory


def _method(operation: str) -> MethodDefinition:
    algorithms: dict[str, dict[str, Any]] = {
        "dssp_compute": {
            "name": "mkdssp-residue-annotation",
            "binary": {
                "name": MKDSSP_BINARY,
                "version": MKDSSP_VERSION,
            },
            "residue_correspondence": (
                "dssp-summary-label-pair-via-atom-site-authored-chain-"
                "signed-residue-and-insertion-code-to-authoritative-axis"
            ),
            "missing_value": "_",
            "coil_conversion": "mkdssp mmCIF '.' to SS8 C",
            "secondary_absent_marker": "?",
            "accessibility_absent_markers": [".", "?"],
        },
        "secondary_structure_extract": {
            "name": "exact-DSSP-SS8-track-extraction",
            "alphabet": "GHITEBSC",
            "absent": "_",
            "coarse_conversion": "none",
        },
        "sasa_compute": {
            "name": "exact-DSSP-solvent-accessibility-extraction",
            "unit": "angstrom_squared",
            "missing_value": "null",
        },
        "secondary_structure_agreement": {
            "name": "exact-SS8-present-residue-agreement",
            "alphabet": "GHITEBSC",
            "absent_policy": "exclude",
            "coarse_conversion": "none",
        },
        "apply_secondary_structure_to_prompt": {
            "name": "exact-annotation-SS8-to-ProteinPrompt-conditioning",
            "source_alphabet": "GHITEBSC_",
            "target_alphabet": "GHITEBS-",
            "symbol_mapping": {
                "C": "-",
                "GHITEBS": "identity",
                "_": "null",
            },
            "source_missing_role": "annotation_unavailable",
            "target_missing_role": "prompt_unspecified",
            "layout": "exact_identity",
            "unaffected_prompt_fields": "byte-equivalent-canonical-values",
            "provenance_transition": (
                "observed_annotation_to_prompt_conditioning"
            ),
        },
        "apply_sasa_to_prompt": {
            "name": "exact-DSSP-SASA-to-ProteinPrompt-conditioning",
            "unit": "angstrom_squared",
            "numeric_mapping": "identity",
            "source_missing_role": "annotation_unavailable",
            "target_missing_role": "prompt_unspecified",
            "layout": "exact_identity",
            "unaffected_prompt_fields": "byte-equivalent-canonical-values",
            "provenance_transition": (
                "observed_annotation_to_prompt_conditioning"
            ),
        },
        "expected_secondary_structure_from_prompt": {
            "name": (
                "exact-ProteinPrompt-conditioning-to-expected-annotation-SS8"
            ),
            "source_alphabet": "GHITEBS-",
            "target_alphabet": "GHITEBSC_",
            "symbol_mapping": {
                "-": "C",
                "GHITEBS": "identity",
                "null": "_",
            },
            "source_missing_role": "prompt_unspecified",
            "target_missing_role": "expected_comparison_excluded",
            "layout": "exact_identity",
            "provenance_transition": (
                "prompt_conditioning_to_expected_annotation"
            ),
        },
    }
    return MethodDefinition(
        method_id=f"structure_annotation.{operation}.method",
        version=_METHOD_VERSIONS[operation],
        algorithm_identity=algorithms[operation],
        model_identity={"kind": "none"},
        checkpoint_identity={"kind": "none"},
        featurization_identity={
            "dssp_compute": {
                "input": (
                    "singleton ProteinStructure Candidate and authoritative "
                    "resolved residue axis joined by exact admitted "
                    "CandidateDataReference"
                ),
                "structure_format": "PDB-v3.3-fixed-columns",
                "provider_output_format": "mkdssp-4.6.1-mmCIF",
                "residue_mapping": (
                    "dssp_struct_summary-label-asym-and-seq-joined-through-"
                    "atom_site-auth-asym-auth-seq-and-PDB-ins-code-to-"
                    "exact-authoritative-axis-identity"
                ),
            },
            "secondary_structure_extract": {
                "input": "candidate-associated DSSP annotation",
                "projection": "secondary_structure",
                "P_conversion": "C",
                "subject": "preserve exact CandidateDataReference",
            },
            "sasa_compute": {
                "input": "candidate-associated DSSP annotation",
                "projection": "sasa",
                "unit": "angstrom_squared",
                "subject": "preserve exact CandidateDataReference",
            },
            "secondary_structure_agreement": {
                "inputs": "expected and observed candidate-associated SS8 tracks",
                "participant_binding": {
                    "observed": "exact admitted subject Candidate reference",
                    "expected": "exact admitted reference Candidate reference",
                },
                "layout": "exact_identity",
                "presence_mask": "both-values-not-underscore",
            },
            "apply_secondary_structure_to_prompt": {
                "inputs": [
                    "ProteinPrompt",
                    "candidate-associated secondary-structure track",
                ],
                "output": "ProteinPrompt",
                "track": "secondary_structure",
                "layout": "exact_identity",
                "candidate_attribution": "not copied into ProteinPrompt",
            },
            "apply_sasa_to_prompt": {
                "inputs": [
                    "ProteinPrompt",
                    "candidate-associated SASA track",
                ],
                "output": "ProteinPrompt",
                "track": "sasa",
                "unit": "angstrom_squared",
                "layout": "exact_identity",
                "candidate_attribution": "not copied into ProteinPrompt",
            },
            "expected_secondary_structure_from_prompt": {
                "inputs": ["ProteinPrompt", "singleton reference Candidate"],
                "output": "candidate-associated secondary-structure track",
                "track": "secondary_structure",
                "layout": "exact_identity",
                "output_role": "expected_comparison",
                "participant_binding": (
                    "exact admitted reference Candidate reference"
                ),
            },
        }[operation],
        source_identity=(
            mkdssp_provider_identity()
            if operation == _DSSP_OPERATION
            else {"kind": "repository-owned"}
        ),
        scale_contract={"kind": "identity"},
    )


def _binding(operation: str) -> ExecutionBindingDefinition:
    method = ContractIdentity(
        "method",
        f"structure_annotation.{operation}.method",
        _METHOD_VERSIONS[operation],
    )
    produced = ()
    if operation == "secondary_structure_agreement":
        produced = (
            ProducedObservationDefinition(
                output_port="scores",
                metric=ContractIdentity(
                    "metric",
                    "structure_annotation.secondary_structure_agreement",
                    _METRIC_VERSION,
                ),
                context_profile={
                    "kind": "pairwise",
                    "subject_role": "subject",
                    "reference_role": "reference",
                    "pairing_mode": "fixed_reference",
                    "normalization": "exact-SS8-present-residue",
                },
                subject_grain="candidate",
                source_role="subject",
                subject_direction="input",
                subject_port="subjects",
                reference_direction="input",
                reference_port="references",
                axis_direction="input",
                axis_port="subject_residue_axes",
                guaranteed_multiplicity="one",
            ),
        )
    is_dssp = operation == _DSSP_OPERATION
    route = "mkdssp_local" if is_dssp else "direct"
    execution_route = "adapter" if is_dssp else "direct"
    binding_version = _NODE_BINDING_VERSIONS[operation]
    return ExecutionBindingDefinition(
        binding_id=f"structure_annotation.{operation}.{route}",
        version=binding_version,
        node_type=ContractIdentity(
            "node_type",
            f"structure_annotation.{operation}",
            binding_version,
        ),
        method=method,
        binding_parameters={},
        execution_route=execution_route,
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                f"structure_annotation.{operation}/factory",
                binding_version,
                {"execution_route": execution_route, "route": route},
            ),
            build=_build(operation),
        ),
        adapter_behavior=(
            BehaviorReference(
                "structure_annotation.mkdssp_local/adapter",
                binding_version,
                {
                    "provider_contract": (
                        f"{MKDSSP_SOURCE_REPOSITORY}@"
                        f"{MKDSSP_SOURCE_REVISION}"
                    ),
                    "source_archive_sha256": MKDSSP_SOURCE_ARCHIVE_SHA256,
                    "binary": MKDSSP_BINARY,
                    "binary_version": MKDSSP_VERSION,
                    "request_format": "PDB-v3.3-fixed-columns",
                    "response_format": "mkdssp-4.6.1-mmCIF",
                    "axis_source": (
                        "exact-candidate-associated-authoritative-"
                        "resolved-residue-axis"
                    ),
                    "residue_reconciliation": (
                        "dssp-summary-label-pair-via-atom-site-auth-fields-"
                        "to-authoritative-axis-exact-identity"
                    ),
                },
            )
            if is_dssp
            else None
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                f"structure_annotation.{operation}/availability",
                _VERSION,
                {"observation": "startup"},
            ),
            prerequisites=(
                {
                    "binary_configuration": {
                        "name": MKDSSP_BINARY,
                        "path_source": "trusted_environment_configuration",
                    }
                }
                if is_dssp
                else {}
            ),
            check=_available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                f"structure_annotation.{operation}/readiness",
                (
                    _DSSP_READINESS_BEHAVIOR_VERSION
                    if is_dssp
                    else _VERSION
                ),
                {
                    "observation": "per-run",
                    "path_source": (
                        "trusted_environment_configuration"
                        if is_dssp
                        else "none"
                    ),
                },
            ),
            prerequisites=(
                {
                    "binary": {
                        "name": MKDSSP_BINARY,
                        "required_version": MKDSSP_VERSION,
                        "path_source": "trusted_environment_configuration",
                    }
                }
                if is_dssp
                else {}
            ),
            check=_dssp_ready if is_dssp else _ready,
        ),
        deterministic=True,
        cacheable=True,
        implementation_identity=(
            {
                "name": (
                    "structure_annotation.dssp_compute."
                    "mkdssp-local-adapter"
                ),
                "provider_identity": mkdssp_provider_identity(),
                "runtime_directory_policy": (
                    "private-per-engine-invocation"
                ),
                "subprocess_boundary": "mkdssp-binary",
            }
            if is_dssp
            else {
                "name": f"structure_annotation.{operation}.direct",
                "source": "repository-owned",
            }
        ),
        produced_observations=produced,
    )


def _port_type(
    *,
    type_id: str,
    kind: str,
    validator: Any,
    to_wire: Any,
    from_wire: Any,
    quantity_contract: Mapping[str, str] | None = None,
) -> PortTypeDefinition:
    def candidate_data_references(
        value: object,
        _candidate_data_port_types: object,
    ) -> tuple[CandidateDataReference, ...]:
        return (cast(Any, value).subject,)

    return PortTypeDefinition(
        type_id=type_id,
        version=_PORT_VERSION,
        validator=BehaviorReference(
            f"{type_id}/validate",
            _PORT_VERSION,
            {
                "accepted_value_kind": kind,
                "subject_reference_required": True,
                "layout_identity_required": True,
                "nullable_semantics": (
                    "underscore_absent"
                    if kind == "secondary_structure_track"
                    else "JSON null means unavailable"
                ),
                **(
                    {"quantity_contract": quantity_contract}
                    if quantity_contract is not None
                    else {}
                ),
            },
        ),
        codec=BehaviorReference(
            f"{type_id}/codec",
            _PORT_VERSION,
            {
                "canonicalization": "RFC 8785",
                "embedded_layout_contract": "residue.layout@3.0.0",
                "subject_wire": (
                    "exact CandidateDataReference candidate_id, "
                    "data_type_id, content_digest"
                ),
            },
        ),
        content_identity=BehaviorReference(
            f"{type_id}/content",
            _PORT_VERSION,
            {
                "digest": "SHA-256",
                "includes_subject_reference": True,
            },
        ),
        runtime_validator=validator,
        runtime_to_wire=to_wire,
        runtime_from_wire=from_wire,
        candidate_data_projection=BehaviorReference(
            f"{type_id}/candidate_data_projection",
            _PORT_VERSION,
            {"fields": ["subject"]},
        ),
        runtime_candidate_data_projection=candidate_data_references,
    )


MODULE_PACKAGE = ModulePackageRegistration(
    schema_version="2.1.0",
    package_id="structure_annotation",
    package_version=_PACKAGE_VERSION,
    package_module=__package__,
    node_definitions=tuple(
        DefinitionResource(f"definitions/{name}.yaml")
        for name in (
            "dssp_compute",
            "secondary_structure_extract",
            "sasa_compute",
            "secondary_structure_agreement",
            "apply_secondary_structure_to_prompt",
            "apply_sasa_to_prompt",
            "expected_secondary_structure_from_prompt",
        )
    ),
    metric_definitions=(
        DefinitionResource(
            "definitions/secondary_structure_agreement_metric.yaml"
        ),
        DefinitionResource(
            "definitions/secondary_structure_position_agreement_metric.yaml"
        ),
    ),
    methods=tuple(_method(operation) for operation in _OPERATIONS),
    bindings=tuple(_binding(operation) for operation in _OPERATIONS),
    port_types=(
        _port_type(
            type_id="structure_annotation.dssp_annotations",
            kind="dssp_annotation",
            validator=_validate_annotation,
            to_wire=_annotation_to_wire,
            from_wire=_annotation_from_wire,
        ),
        _port_type(
            type_id="structure_annotation.secondary_structure_track",
            kind="secondary_structure_track",
            validator=_validate_secondary_track,
            to_wire=_track_to_wire("secondary_structure"),
            from_wire=_track_from_wire("secondary_structure"),
        ),
        _port_type(
            type_id="structure_annotation.sasa_track",
            kind="sasa_track",
            validator=_validate_sasa_track,
            to_wire=_track_to_wire("sasa"),
            from_wire=_track_from_wire("sasa"),
            quantity_contract=_ABSOLUTE_SASA_QUANTITY_CONTRACT,
        ),
    ),
)
