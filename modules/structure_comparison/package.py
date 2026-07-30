"""The single production registration for structure comparison."""

from __future__ import annotations

from importlib.metadata import version
import math
import re
from typing import Any, Mapping

from core import (
    AvailabilityDeclaration,
    AvailabilityResult,
    BehaviorReference,
    CatalogContract,
    ContractIdentity,
    DefinitionResource,
    ExecutionBindingDefinition,
    LazyImplementationFactory,
    MethodDefinition,
    ModulePackageRegistration,
    PortTypeDefinition,
    ProducedObservationDefinition,
    ReadinessDeclaration,
)
from datatypes import ExactContractReference, PairwiseParticipant

from .domain import (
    AlignmentAtomCorrespondence,
    StructureAlignmentEvidence,
    StructureAlignmentEvidenceCollection,
    StructureAlignmentNormalization,
    StructureAlignmentTransform,
)
from .implementation import StructureComparisonImplementation


_VERSION = "2.0.0"
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_NORMALIZATION = "ca-correspondence-mean-square-angstrom"
_TM_SCORE_NORMALIZATION = "standard-reference-residue-count"
_BIOPYTHON_VERSION = version("biopython")
_NUMPY_VERSION = version("numpy")
_TMTOOLS_VERSION = version("tmtools")


def _available() -> AvailabilityResult:
    return AvailabilityResult.available()


def _ready(environment: Mapping[str, Any]) -> bool:
    return isinstance(environment, Mapping)


def _build(operation: str, pairing_mode: str | None = None):
    def factory(**kwargs: object) -> object:
        return StructureComparisonImplementation(
            kwargs["run_resources"],
            kwargs["frozen_catalog"],
            operation,
            pairing_mode,
        )

    return factory


def _finite_vector(value: object, *, name: str) -> tuple[float, float, float]:
    if (
        type(value) is not tuple
        or len(value) != 3
        or any(
            isinstance(item, bool)
            or not isinstance(item, (int, float))
            or not math.isfinite(float(item))
            for item in value
        )
    ):
        raise ValueError(f"{name} must be one finite 3-vector")
    return tuple(float(item) for item in value)  # type: ignore[return-value]


def _participant(value: object, *, role: str) -> PairwiseParticipant:
    if (
        type(value) is not PairwiseParticipant
        or value.role != role
        or not value.candidate_id
        or _DIGEST.fullmatch(value.content_digest) is None
    ):
        raise ValueError(f"alignment {role} identity is invalid")
    return value


def _method(value: object) -> ExactContractReference:
    if (
        type(value) is not ExactContractReference
        or value.contract_kind != "method"
        or value.contract_id
        != "structure_comparison.ca_sequence_svd.method"
        or value.contract_version != _VERSION
        or value.contract_digest != _ALIGNMENT_METHOD_DIGEST
    ):
        raise ValueError("alignment Method identity is invalid")
    return value


def _validate_transform(value: object) -> StructureAlignmentTransform:
    if (
        type(value) is not StructureAlignmentTransform
        or value.maps_from_role != "subject"
        or value.maps_to_role != "reference"
        or type(value.row_vector_rotation) is not tuple
        or len(value.row_vector_rotation) != 3
    ):
        raise ValueError(
            "alignment transform must map subject to reference"
        )
    rotation = tuple(
        _finite_vector(row, name="rotation row")
        for row in value.row_vector_rotation
    )
    _finite_vector(value.translation, name="translation")
    for left in range(3):
        for right in range(3):
            dot = math.fsum(
                rotation[index][left] * rotation[index][right]
                for index in range(3)
            )
            expected = 1.0 if left == right else 0.0
            if not math.isclose(dot, expected, rel_tol=0.0, abs_tol=1e-9):
                raise ValueError("alignment rotation is not orthonormal")
    determinant = (
        rotation[0][0]
        * (
            rotation[1][1] * rotation[2][2]
            - rotation[1][2] * rotation[2][1]
        )
        - rotation[0][1]
        * (
            rotation[1][0] * rotation[2][2]
            - rotation[1][2] * rotation[2][0]
        )
        + rotation[0][2]
        * (
            rotation[1][0] * rotation[2][1]
            - rotation[1][1] * rotation[2][0]
        )
    )
    if not math.isclose(determinant, 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError("alignment rotation must be a proper rotation")
    return value


def _validate_normalization(
    value: object,
    *,
    correspondence_count: int,
) -> StructureAlignmentNormalization:
    if (
        type(value) is not StructureAlignmentNormalization
        or value.atom_selection != "CA"
        or type(value.subject_residue_count) is not int
        or type(value.reference_residue_count) is not int
        or type(value.aligned_atom_count) is not int
        or value.subject_residue_count < correspondence_count
        or value.reference_residue_count < correspondence_count
        or value.aligned_atom_count != correspondence_count
        or value.coverage_denominator
        != "max(subject_residue_count,reference_residue_count)"
    ):
        raise ValueError("alignment normalization inputs are incomplete")
    return value


def _validate_alignment(value: object) -> None:
    if (
        type(value) is not StructureAlignmentEvidence
        or value.schema_version != _VERSION
    ):
        raise ValueError("alignment has the wrong nominal version")
    subject = _participant(value.subject, role="subject")
    reference = _participant(value.reference, role="reference")
    if subject.candidate_id == reference.candidate_id:
        raise ValueError("alignment Candidate identities conflict")
    transform = _validate_transform(value.transform)
    if (
        type(value.correspondence) is not tuple
        or not value.correspondence
    ):
        raise ValueError("alignment correspondence must be non-empty")
    subject_atoms: set[tuple[str, str]] = set()
    reference_atoms: set[tuple[str, str]] = set()
    for item in value.correspondence:
        if (
            type(item) is not AlignmentAtomCorrespondence
            or not item.subject_residue_id
            or not item.reference_residue_id
            or item.subject_atom_name != "CA"
            or item.reference_atom_name != "CA"
            or isinstance(item.residual_distance, bool)
            or not isinstance(item.residual_distance, (int, float))
            or not math.isfinite(float(item.residual_distance))
            or float(item.residual_distance) < 0
        ):
            raise ValueError("alignment atom correspondence is invalid")
        subject_coordinate = _finite_vector(
            item.subject_coordinate,
            name="subject coordinate",
        )
        reference_coordinate = _finite_vector(
            item.reference_coordinate,
            name="reference coordinate",
        )
        transformed = _finite_vector(
            item.transformed_subject_coordinate,
            name="transformed subject coordinate",
        )
        expected_transformed = tuple(
            math.fsum(
                subject_coordinate[index]
                * transform.row_vector_rotation[index][axis]
                for index in range(3)
            )
            + transform.translation[axis]
            for axis in range(3)
        )
        if any(
            not math.isclose(
                actual,
                expected,
                rel_tol=0.0,
                abs_tol=1e-8,
            )
            for actual, expected in zip(
                transformed,
                expected_transformed,
                strict=True,
            )
        ):
            raise ValueError(
                "transformed subject coordinate contradicts the transform"
            )
        expected_distance = math.sqrt(
            math.fsum(
                (reference_coordinate[index] - transformed[index]) ** 2
                for index in range(3)
            )
        )
        if not math.isclose(
            float(item.residual_distance),
            expected_distance,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            raise ValueError(
                "alignment residual contradicts its exact coordinates"
            )
        subject_atom = (item.subject_residue_id, item.subject_atom_name)
        reference_atom = (
            item.reference_residue_id,
            item.reference_atom_name,
        )
        if subject_atom in subject_atoms or reference_atom in reference_atoms:
            raise ValueError("alignment correspondence reuses an atom")
        subject_atoms.add(subject_atom)
        reference_atoms.add(reference_atom)
    normalization = _validate_normalization(
        value.normalization,
        correspondence_count=len(value.correspondence),
    )
    expected_rmsd = math.sqrt(
        math.fsum(
            float(item.residual_distance) ** 2
            for item in value.correspondence
        )
        / normalization.aligned_atom_count
    )
    expected_coverage = (
        normalization.aligned_atom_count
        / max(
            normalization.subject_residue_count,
            normalization.reference_residue_count,
        )
    )
    for name, actual, expected in (
        ("RMSD", value.rmsd, expected_rmsd),
        ("coverage", value.coverage, expected_coverage),
    ):
        if (
            isinstance(actual, bool)
            or not isinstance(actual, (int, float))
            or not math.isfinite(float(actual))
            or float(actual) < 0
            or not math.isclose(
                float(actual),
                expected,
                rel_tol=1e-9,
                abs_tol=1e-9,
            )
        ):
            raise ValueError(
                f"alignment {name} contradicts its exact correspondence"
            )
    if float(value.coverage) > 1:
        raise ValueError("alignment coverage must not exceed one")
    _method(value.method)


def _alignment_to_wire(value: object) -> object:
    assert type(value) is StructureAlignmentEvidence
    _validate_alignment(value)
    return {
        "schema_version": value.schema_version,
        "subject": value.subject.to_public(),
        "reference": value.reference.to_public(),
        "correspondence": [
            {
                "subject_residue_id": item.subject_residue_id,
                "subject_atom_name": item.subject_atom_name,
                "subject_coordinate": list(item.subject_coordinate),
                "reference_residue_id": item.reference_residue_id,
                "reference_atom_name": item.reference_atom_name,
                "reference_coordinate": list(item.reference_coordinate),
                "transformed_subject_coordinate": list(
                    item.transformed_subject_coordinate
                ),
                "residual_distance": item.residual_distance,
            }
            for item in value.correspondence
        ],
        "transform": {
            "maps_from_role": value.transform.maps_from_role,
            "maps_to_role": value.transform.maps_to_role,
            "row_vector_rotation": [
                list(row) for row in value.transform.row_vector_rotation
            ],
            "translation": list(value.transform.translation),
        },
        "normalization": {
            "atom_selection": value.normalization.atom_selection,
            "subject_residue_count": (
                value.normalization.subject_residue_count
            ),
            "reference_residue_count": (
                value.normalization.reference_residue_count
            ),
            "aligned_atom_count": value.normalization.aligned_atom_count,
            "coverage_denominator": (
                value.normalization.coverage_denominator
            ),
        },
        "rmsd": value.rmsd,
        "coverage": value.coverage,
        "method": {
            "contract_kind": value.method.contract_kind,
            "contract_id": value.method.contract_id,
            "contract_version": value.method.contract_version,
            "contract_digest": value.method.contract_digest,
        },
    }


def _closed(value: object, fields: set[str], *, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{name} wire value is not closed")
    return value


def _tuple3(value: object, *, name: str) -> tuple[float, float, float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{name} wire value is invalid")
    return tuple(value)  # type: ignore[return-value]


def _alignment_from_wire(value: object) -> object:
    raw = _closed(
        value,
        {
            "schema_version",
            "subject",
            "reference",
            "correspondence",
            "transform",
            "normalization",
            "rmsd",
            "coverage",
            "method",
        },
        name="alignment",
    )
    subject = _closed(
        raw["subject"],
        {"role", "candidate_id", "content_digest"},
        name="subject",
    )
    reference = _closed(
        raw["reference"],
        {"role", "candidate_id", "content_digest"},
        name="reference",
    )
    transform = _closed(
        raw["transform"],
        {
            "maps_from_role",
            "maps_to_role",
            "row_vector_rotation",
            "translation",
        },
        name="transform",
    )
    normalization = _closed(
        raw["normalization"],
        {
            "atom_selection",
            "subject_residue_count",
            "reference_residue_count",
            "aligned_atom_count",
            "coverage_denominator",
        },
        name="normalization",
    )
    method = _closed(
        raw["method"],
        {
            "contract_kind",
            "contract_id",
            "contract_version",
            "contract_digest",
        },
        name="method",
    )
    if (
        not isinstance(raw["correspondence"], list)
        or not isinstance(transform["row_vector_rotation"], list)
        or len(transform["row_vector_rotation"]) != 3
    ):
        raise ValueError("alignment wire arrays are invalid")
    correspondence = []
    for item in raw["correspondence"]:
        entry = _closed(
            item,
            {
                "subject_residue_id",
                "subject_atom_name",
                "subject_coordinate",
                "reference_residue_id",
                "reference_atom_name",
                "reference_coordinate",
                "transformed_subject_coordinate",
                "residual_distance",
            },
            name="correspondence",
        )
        correspondence.append(
            AlignmentAtomCorrespondence(
                subject_residue_id=entry["subject_residue_id"],
                subject_atom_name=entry["subject_atom_name"],
                subject_coordinate=_tuple3(
                    entry["subject_coordinate"],
                    name="subject coordinate",
                ),
                reference_residue_id=entry["reference_residue_id"],
                reference_atom_name=entry["reference_atom_name"],
                reference_coordinate=_tuple3(
                    entry["reference_coordinate"],
                    name="reference coordinate",
                ),
                transformed_subject_coordinate=_tuple3(
                    entry["transformed_subject_coordinate"],
                    name="transformed subject coordinate",
                ),
                residual_distance=entry["residual_distance"],
            )
        )
    alignment = StructureAlignmentEvidence(
        schema_version=raw["schema_version"],
        subject=PairwiseParticipant(**subject),
        reference=PairwiseParticipant(**reference),
        correspondence=tuple(correspondence),
        transform=StructureAlignmentTransform(
            maps_from_role=transform["maps_from_role"],
            maps_to_role=transform["maps_to_role"],
            row_vector_rotation=tuple(
                _tuple3(row, name="rotation row")
                for row in transform["row_vector_rotation"]
            ),
            translation=_tuple3(
                transform["translation"],
                name="translation",
            ),
        ),
        normalization=StructureAlignmentNormalization(**normalization),
        rmsd=raw["rmsd"],
        coverage=raw["coverage"],
        method=ExactContractReference(**method),
    )
    _validate_alignment(alignment)
    return alignment


def _validate_collection(value: object) -> None:
    if (
        type(value) is not StructureAlignmentEvidenceCollection
        or value.schema_version != _VERSION
        or (
            (
                value.pairing_source,
                value.accepted_cardinality,
            )
            not in {
                (
                    "candidate.pairing@2.0.0",
                    "one_to_one_complete",
                ),
                (
                    "fixed_reference.singleton@2.0.0",
                    "many_to_one_complete",
                ),
            }
        )
        or type(value.alignments) is not tuple
        or not value.alignments
    ):
        raise ValueError("alignment collection contract is incomplete")
    subjects: dict[str, str] = {}
    references: dict[str, str] = {}
    for alignment in value.alignments:
        _validate_alignment(alignment)
        subject_id = alignment.subject.candidate_id
        subject_digest = alignment.subject.content_digest
        reference_id = alignment.reference.candidate_id
        reference_digest = alignment.reference.content_digest
        if subject_id in subjects or (
            value.accepted_cardinality == "one_to_one_complete"
            and reference_id in references
        ):
            raise ValueError(
                "alignment collection is not complete one-to-one evidence"
            )
        subjects[subject_id] = subject_digest
        references[reference_id] = reference_digest
    if set(subjects).intersection(references):
        raise ValueError(
            "alignment collection reuses Candidate identities across roles"
        )
    if (
        value.accepted_cardinality == "many_to_one_complete"
        and len(references) != 1
    ):
        raise ValueError(
            "fixed-reference alignment collection requires one exact reference"
        )


def _collection_to_wire(value: object) -> object:
    assert type(value) is StructureAlignmentEvidenceCollection
    _validate_collection(value)
    return {
        "schema_version": value.schema_version,
        "pairing_source": value.pairing_source,
        "accepted_cardinality": value.accepted_cardinality,
        "alignments": [
            _alignment_to_wire(alignment)
            for alignment in value.alignments
        ],
    }


def _collection_from_wire(value: object) -> object:
    raw = _closed(
        value,
        {
            "schema_version",
            "pairing_source",
            "accepted_cardinality",
            "alignments",
        },
        name="alignment collection",
    )
    if not isinstance(raw["alignments"], list):
        raise ValueError("alignment collection wire value is invalid")
    collection = StructureAlignmentEvidenceCollection(
        schema_version=raw["schema_version"],
        pairing_source=raw["pairing_source"],
        accepted_cardinality=raw["accepted_cardinality"],
        alignments=tuple(
            _alignment_from_wire(item)
            for item in raw["alignments"]
        ),
    )
    _validate_collection(collection)
    return collection


def _method_definition(operation: str) -> MethodDefinition:
    if operation == "alignment":
        return MethodDefinition(
            method_id="structure_comparison.ca_sequence_svd.method",
            version=_VERSION,
            algorithm_identity={
                "name": "sequence-aware-CA-rigid-superposition",
                "sequence_alignment": {
                    "algorithm": "global-pairwise",
                    "substitution_matrix": "BLOSUM62",
                    "gap_open": -3,
                    "gap_extend": -0.5,
                    "end_gap_open": -2,
                    "end_gap_extend": -0.5,
                },
                "superposition": "Kabsch-SVD-row-vector",
                "tie_break": {
                    "bounded_sequence_alignments": (
                        "maximum-cardinality-then-lowest-fit-RMSD-"
                        "then-index-order"
                    ),
                    "high_ambiguity_threshold": 1024,
                    "high_ambiguity_engine": "tmtools.tm_align",
                    "tmtools_version": _TMTOOLS_VERSION,
                },
            },
            model_identity={"kind": "none"},
            checkpoint_identity={"kind": "none"},
            featurization_identity={
                "structure_format": "PDB-v3.3-fixed-columns",
                "atom_selection": "CA",
                "unknown_residue": "X",
            },
            source_identity={
                "kind": "repository-owned",
                "engine_api": (
                    "Bio.Align.PairwiseAligner+Bio.SVDSuperimposer"
                ),
                "biopython_version": _BIOPYTHON_VERSION,
                "numpy_version": _NUMPY_VERSION,
                "nested_engine_api": "tmtools.tm_align",
                "tmtools_version": _TMTOOLS_VERSION,
            },
            scale_contract={
                "coordinates": "angstrom",
                "transform": "subject-to-reference-row-vector",
            },
        )
    if operation == "rmsd":
        return MethodDefinition(
        method_id="structure_comparison.rmsd.method",
        version=_VERSION,
        algorithm_identity={
            "name": "validated-alignment-rmsd-projection",
            "source_field": "structure_comparison.alignment.rmsd",
            "validation_formula": (
                "sqrt(fsum(residual_distance^2)/aligned_atom_count)"
            ),
        },
        model_identity={"kind": "none"},
        checkpoint_identity={"kind": "none"},
        featurization_identity={
            "input": "structure_comparison.alignment@2.0.0",
            "atom_selection": "CA",
        },
        source_identity={"kind": "repository-owned"},
        scale_contract={"unit": "angstrom"},
        )
    return MethodDefinition(
        method_id="structure_comparison.tm_score.reference_normalized.method",
        version=_VERSION,
        algorithm_identity={
            "name": "standard-reference-normalized-tm-score",
            "correspondence": "structure_comparison.alignment@2.0.0",
            "optimization": "tmtools.tm_align-fixed-correspondence",
            "formula": "sum(1/(1+(distance/d0)^2))/reference_residue_count",
            "d0": "max(0.5,1.24*(reference_residue_count-15)^(1/3)-1.8)",
        },
        model_identity={"kind": "none"},
        checkpoint_identity={"kind": "none"},
        featurization_identity={
            "input": "structure_comparison.alignment@2.0.0",
            "atom_selection": "CA",
            "normalization": _TM_SCORE_NORMALIZATION,
        },
        source_identity={
            "kind": "repository-owned",
            "engine_api": "tmtools.tm_align",
            "tmtools_version": _TMTOOLS_VERSION,
        },
        scale_contract={
            "unit": "dimensionless",
            "canonical_range": [0, 1],
            "reference_normalization": "exact-reference-residue-count",
        },
    )


def _binding(
    operation: str,
    *,
    pairing_mode: str | None = None,
) -> ExecutionBindingDefinition:
    node_id = f"structure_comparison.{operation}"
    binding_suffix = (
        pairing_mode
        if operation
        in {"align_pairwise", "rmsd", "tm_score", "batch_tm_score"}
        and pairing_mode is not None
        else "direct"
    )
    method_id = (
        "structure_comparison.rmsd.method"
        if operation == "rmsd"
        else "structure_comparison.tm_score.reference_normalized.method"
        if operation in {"tm_score", "batch_tm_score"}
        else "structure_comparison.ca_sequence_svd.method"
    )
    produced = ()
    if operation in {"rmsd", "tm_score", "batch_tm_score"}:
        assert pairing_mode is not None
        partition = (
            "structure_comparison.rmsd"
            if operation == "rmsd"
            else "structure_comparison.tm_score.single"
            if operation == "tm_score"
            else f"structure_comparison.tm_score.{pairing_mode}"
        )
        produced = (
            ProducedObservationDefinition(
                output_port="scores",
                output_partition=partition,
                metric=ContractIdentity(
                    "metric",
                    (
                        "structure_comparison.rmsd"
                        if operation == "rmsd"
                        else "structure_comparison.tm_score"
                    ),
                    _VERSION,
                ),
                context_profile={
                    "kind": "pairwise",
                    "subject_role": "subject",
                    "reference_role": "reference",
                    "pairing_mode": pairing_mode,
                    "normalization": (
                        _NORMALIZATION
                        if operation == "rmsd"
                        else _TM_SCORE_NORMALIZATION
                    ),
                },
                subject_grain="candidate",
                source_role="subject",
                subject_direction="input",
                subject_port="subjects",
                reference_direction="input",
                reference_port="references",
                pairing_direction=(
                    "input"
                    if pairing_mode == "per_subject_counterpart"
                    else None
                ),
                pairing_port=(
                    "pairing"
                    if pairing_mode == "per_subject_counterpart"
                    else None
                ),
                guaranteed_multiplicity="one",
            ),
        )
    return ExecutionBindingDefinition(
        binding_id=f"{node_id}.{binding_suffix}",
        version=_VERSION,
        node_type=ContractIdentity("node_type", node_id, _VERSION),
        method=ContractIdentity("method", method_id, _VERSION),
        binding_parameters={},
        execution_route="direct",
        factory=LazyImplementationFactory(
            behavior=BehaviorReference(
                f"{node_id}.{binding_suffix}/factory",
                _VERSION,
                {"execution_route": "direct"},
            ),
            build=_build(operation, pairing_mode),
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                f"{node_id}.{binding_suffix}/availability",
                _VERSION,
                {"observation": "startup"},
            ),
            prerequisites={},
            check=_available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                f"{node_id}.{binding_suffix}/readiness",
                _VERSION,
                {"observation": "per-run"},
            ),
            prerequisites={},
            check=_ready,
        ),
        deterministic=True,
        cacheable=True,
        implementation_identity={
            "name": f"{node_id}.{binding_suffix}",
            "source": "repository-owned",
            **(
                {
                    "biopython_version": _BIOPYTHON_VERSION,
                    "numpy_version": _NUMPY_VERSION,
                    "tmtools_version": _TMTOOLS_VERSION,
                }
                if operation != "rmsd"
                else {}
            ),
        },
        produced_observations=produced,
    )


def _port_type(
    type_id: str,
    validator: Any,
    to_wire: Any,
    from_wire: Any,
) -> PortTypeDefinition:
    return PortTypeDefinition(
        type_id=type_id,
        version=_VERSION,
        validator=BehaviorReference(
            f"{type_id}/validate",
            _VERSION,
            {
                "accepted_value_kind": type_id.rsplit(".", 1)[-1],
                "identity_roles": ["subject", "reference"],
                "finite_coordinates_required": True,
                "accepted_alignment_method_digest": (
                    _ALIGNMENT_METHOD_DIGEST
                ),
            },
        ),
        codec=BehaviorReference(
            f"{type_id}/codec",
            _VERSION,
            {
                "canonicalization": "RFC 8785",
                "schema_version": _VERSION,
            },
        ),
        content_identity=BehaviorReference(
            f"{type_id}/content",
            _VERSION,
            {"digest": "SHA-256"},
        ),
        runtime_validator=validator,
        runtime_to_wire=to_wire,
        runtime_from_wire=from_wire,
    )


_ALIGNMENT_METHOD_DEFINITION = _method_definition("alignment")
_RMSD_METHOD_DEFINITION = _method_definition("rmsd")
_TM_SCORE_METHOD_DEFINITION = _method_definition("tm_score")
_ALIGNMENT_METHOD_DIGEST = CatalogContract(
    contract_kind="method",
    contract_id=_ALIGNMENT_METHOD_DEFINITION.method_id,
    contract_version=_ALIGNMENT_METHOD_DEFINITION.version,
    descriptor=_ALIGNMENT_METHOD_DEFINITION.descriptor_template(),
).contract_digest


MODULE_PACKAGE = ModulePackageRegistration(
    schema_version=_VERSION,
    package_id="structure_comparison",
    package_version=_VERSION,
    package_module=__package__,
    node_definitions=(
        DefinitionResource("definitions/align_single.yaml"),
        DefinitionResource("definitions/align_pairwise.yaml"),
        DefinitionResource("definitions/rmsd.yaml"),
        DefinitionResource("definitions/tm_score.yaml"),
        DefinitionResource("definitions/batch_tm_score.yaml"),
    ),
    metric_definitions=(
        DefinitionResource("definitions/rmsd_metric.yaml"),
        DefinitionResource("definitions/tm_score_metric.yaml"),
    ),
    methods=(
        _ALIGNMENT_METHOD_DEFINITION,
        _RMSD_METHOD_DEFINITION,
        _TM_SCORE_METHOD_DEFINITION,
    ),
    bindings=(
        _binding("align_single"),
        _binding("align_pairwise"),
        _binding("align_pairwise", pairing_mode="fixed_reference"),
        _binding("rmsd", pairing_mode="fixed_reference"),
        _binding("rmsd", pairing_mode="per_subject_counterpart"),
        _binding("tm_score", pairing_mode="fixed_reference"),
        _binding("batch_tm_score", pairing_mode="fixed_reference"),
        _binding(
            "batch_tm_score",
            pairing_mode="per_subject_counterpart",
        ),
    ),
    port_types=(
        _port_type(
            "structure_comparison.alignment",
            _validate_alignment,
            _alignment_to_wire,
            _alignment_from_wire,
        ),
        _port_type(
            "structure_comparison.alignment_collection",
            _validate_collection,
            _collection_to_wire,
            _collection_from_wire,
        ),
    ),
)
