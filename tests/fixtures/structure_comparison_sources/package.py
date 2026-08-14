"""Independent Candidate-associated source for comparison conformance."""

from __future__ import annotations

import math

from core import (
    AvailabilityDeclaration,
    AvailabilityResult,
    BehaviorReference,
    CandidatePairingIntent,
    CandidatePairingIntentEntry,
    ContractIdentity,
    DefinitionResource,
    ExecutionBindingDefinition,
    MethodDefinition,
    ModulePackageRegistration,
    OperationCall,
    OperationContext,
    ProducedObservationDefinition,
    ReadinessDeclaration,
    ReadinessResult,
    ScientificOperationFactory,
)
from datatypes import (
    Candidate,
    CandidateCollection,
    IntrinsicObservationContext,
    ProteinSequence,
    ProteinStructure,
    ResidueLayout,
    ScoreCollection,
    ScoreObservation,
)
from modules.folding.package import MODULE_PACKAGE as FOLDING_PACKAGE
from modules.structure_prediction.domain import PredictionResidueAxis
from modules.structure_prediction.domain import (
    ConfidenceFact,
    ConfidenceFactCollection,
    prediction_key,
)
from modules.structure_prediction.port_types import (
    PREDICTION_RESIDUE_AXIS_PORT_TYPE,
    prediction_axis_reference,
)


_VERSION = "4.0.0"
_RESIDUE_NAMES = {
    "A": "ALA",
    "G": "GLY",
    "S": "SER",
    "T": "THR",
}


def _structure(
    sequence: str,
    *,
    chain_id: str,
    translation: tuple[float, float, float],
) -> ProteinStructure:
    base = (
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 2.0, 0.0),
        (0.0, 0.0, 3.0),
        (1.0, 2.0, 3.0),
    )
    lines = []
    for index, (amino_acid, coordinate) in enumerate(
        zip(sequence, base, strict=True),
        start=1,
    ):
        x = coordinate[0] + translation[0]
        y = coordinate[1] + translation[1]
        z = coordinate[2] + translation[2]
        line = (
            f"ATOM  {index:5d}  CA  {_RESIDUE_NAMES[amino_acid]} "
            f"{chain_id}{index:4d}    "
            f"{x:8.3f}{y:8.3f}{z:8.3f}"
            "  1.00 20.00           C"
        )
        lines.append(line.ljust(80))
    return ProteinStructure("\n".join((*lines, "TER", "END", "")))


def mse_structure_axis_fixture() -> ProteinStructure:
    """Return one MODRES-declared MSE with an admitted CA coordinate."""
    modres = [" "] * 80
    modres[0:6] = "MODRES"
    modres[7:11] = "TEST"
    modres[12:15] = "MSE"
    modres[16] = "A"
    modres[18:22] = f"{1:4d}"
    modres[24:27] = "MET"
    modres[29:45] = "SELENOMETHIONINE"
    ca = (
        f"HETATM{1:5d}  CA  MSE A{1:4d}    "
        f"{7.0:8.3f}{8.0:8.3f}{9.0:8.3f}"
        "  1.00 20.00           C"
    ).ljust(80)
    return ProteinStructure(
        "\n".join(
            (
                "SEQRES   1 A    1  MSE",
                "".join(modres).rstrip(),
                ca,
                "TER",
                "END",
                "",
            )
        )
    )


class _Source:
    def __init__(self, resources: object) -> None:
        self._resources = resources

    def execute(self, call: OperationCall) -> dict[str, object]:
        if (
            call.inputs
            or call.binding_parameters
            or set(call.node_parameters) != {"scenario"}
        ):
            raise ValueError("comparison source inputs are unresolved")
        scenario = call.node_parameters["scenario"]
        fixed = _structure(
            "AGSTA",
            chain_id="R",
            translation=(0.0, 0.0, 0.0),
        )
        alpha = _structure(
            "AGSTA",
            chain_id="A",
            translation=(2.0, -1.0, 3.0),
        )
        beta = _structure(
            "AGSTA",
            chain_id="B",
            translation=(-4.0, 5.0, 2.0),
        )
        other = _structure(
            "AGSTA",
            chain_id="S",
            translation=(1.0, 2.0, -3.0),
        )
        if scenario == "single":
            subject_values = (("alpha", alpha),)
            reference_values = (("fixed", fixed),)
            pairs = None
        elif scenario == "fixed_reference":
            subject_values = (("beta", beta), ("alpha", alpha))
            reference_values = (("fixed", fixed),)
            pairs = None
        elif scenario == "per_subject_counterpart":
            subject_values = (("beta", beta), ("alpha", alpha))
            reference_values = (("other", other), ("fixed", fixed))
            pairs = (("alpha", "fixed"), ("beta", "other"))
        else:
            raise ValueError("unknown comparison source scenario")
        subjects = CandidateCollection(
            collection_id=f"{scenario}-subjects",
            item_type="protein.structure",
            items=tuple(
                Candidate(candidate_id, structure)
                for candidate_id, structure in subject_values
            ),
        )
        references = CandidateCollection(
            collection_id=f"{scenario}-references",
            item_type="protein.structure",
            items=tuple(
                Candidate(candidate_id, structure)
                for candidate_id, structure in reference_values
            ),
        )
        with self._resources.engine_invocation():
            outputs: dict[str, object] = {
                "subjects": subjects,
                "references": references,
            }
            if pairs is not None:
                outputs["pairing"] = CandidatePairingIntent(
                    entries=tuple(
                        CandidatePairingIntentEntry(subject_id, reference_id)
                        for subject_id, reference_id in pairs
                    )
                )
            return outputs


def _build(context: OperationContext) -> _Source:
    return _Source(context.resources)


def _acceptance_structure() -> ProteinStructure:
    lines: list[str] = []
    for index in range(1, 76):
        angle = index * 0.43
        x = 7.0 * math.cos(angle)
        y = 7.0 * math.sin(angle)
        z = index * 1.3
        lines.append(
            (
                f"ATOM  {index:5d}  CA  ALA A{index:4d}    "
                f"{x:8.3f}{y:8.3f}{z:8.3f}"
                "  1.00 20.00           C"
            ).ljust(80)
        )
    return ProteinStructure("\n".join((*lines, "TER", "END", "")))


class _ThreeWaySource:
    def __init__(self, resources: object) -> None:
        self._resources = resources

    def execute(self, call: OperationCall) -> dict[str, object]:
        if call.inputs or call.node_parameters or call.binding_parameters:
            raise ValueError("three-way source accepts no inputs or parameters")
        structure = _acceptance_structure()
        input_candidate = Candidate("input", structure)
        sequence_candidate = Candidate(
            "sequence",
            ProteinSequence(
                "A" * 75,
                residue_ids=tuple(f"A:{index}" for index in range(1, 76)),
            ),
            parent_ids=(input_candidate.candidate_id,),
        )
        esmfold2_candidate = Candidate(
            "esmfold2",
            structure,
            parent_ids=(sequence_candidate.candidate_id,),
        )
        simplefold_candidate = Candidate(
            "simplefold",
            structure,
            parent_ids=(sequence_candidate.candidate_id,),
        )
        with self._resources.engine_invocation():
            return {
                "input_structures": CandidateCollection(
                    "input-structures", "protein.structure", (input_candidate,)
                ),
                "sequence_parents": CandidateCollection(
                    "sequence-parents", "protein.sequence", (sequence_candidate,)
                ),
                "esmfold2_structures": CandidateCollection(
                    "esmfold2-structures",
                    "protein.structure",
                    (esmfold2_candidate,),
                ),
                "simplefold_structures": CandidateCollection(
                    "simplefold-structures",
                    "protein.structure",
                    (simplefold_candidate,),
                ),
            }


class _ConfidenceSource:
    def __init__(
        self,
        context: OperationContext,
    ) -> None:
        self._method = context.method
        self._metric = context.produced_observations[0].metric
        self._resources = context.resources

    def execute(self, call: OperationCall) -> dict[str, object]:
        if call.node_parameters or call.binding_parameters:
            raise ValueError("confidence source accepts no parameters")
        structures = call.inputs["structures"]
        facts = call.inputs["confidence_facts"]
        assert type(structures) is CandidateCollection
        assert type(facts) is ConfidenceFactCollection
        if len(structures.items) != 1 or len(facts.entries) != 1:
            raise ValueError("confidence source requires one structure and fact")
        structure_reference = call.input_content_digests[
            "structures"
        ].candidate_data[0]
        fact = facts.entries[0]
        if fact.structure_content_digest != structure_reference.content_digest:
            raise ValueError("confidence fact does not identify the structure")
        axis = prediction_axis_reference(fact.prediction_axis)
        observation = ScoreObservation(
            subject=structure_reference,
            metric=self._metric,
            method=self._method,
            context=IntrinsicObservationContext(),
            value=90.0,
            residue_axis=axis,
            source_partition="prediction_confidence",
        )
        with self._resources.engine_invocation():
            return {
                "observations": ScoreCollection(
                    "prediction-confidence", (observation,)
                )
            }


class _ConfidenceFactSource:
    def __init__(self, context: OperationContext) -> None:
        self._method = context.method
        self._resources = context.resources

    def execute(self, call: OperationCall) -> dict[str, object]:
        if call.node_parameters or call.binding_parameters:
            raise ValueError("confidence-fact source accepts no parameters")
        structures = call.inputs["structures"]
        prediction_axis = call.inputs["prediction_axis"]
        assert type(structures) is CandidateCollection
        assert type(prediction_axis) is PredictionResidueAxis
        if len(structures.items) != 1:
            raise ValueError("confidence-fact source requires one structure")
        structure_reference = call.input_content_digests[
            "structures"
        ].candidate_data[0]
        axis_digest = PREDICTION_RESIDUE_AXIS_PORT_TYPE.content_digest(
            prediction_axis
        )
        fact = ConfidenceFact(
            prediction_key=prediction_key(
                output_role="structure_candidates",
                output_slot=0,
                structure_content_digest=structure_reference.content_digest,
                prediction_axis_content_digest=axis_digest,
            ),
            structure_content_digest=structure_reference.content_digest,
            prediction_axis=prediction_axis,
            plddt_per_residue=(90.0,) * 75,
            ptm=None,
            pae=None,
        )
        with self._resources.engine_invocation():
            return {
                "confidence_facts": ConfidenceFactCollection(
                    observation_method=self._method,
                    entries=(fact,),
                )
            }


class _PredictionAxisSource:
    def __init__(self, resources: object) -> None:
        self._resources = resources

    def execute(self, call: OperationCall) -> dict[str, object]:
        if call.node_parameters or call.binding_parameters:
            raise ValueError("prediction-axis source accepts no parameters")
        sequences = call.inputs["sequence_parents"]
        assert type(sequences) is CandidateCollection
        if len(sequences.items) != 1:
            raise ValueError("prediction-axis source requires one sequence")
        candidate = sequences.items[0]
        assert type(candidate.data) is ProteinSequence
        reference = call.input_content_digests[
            "sequence_parents"
        ].candidate_data[0]
        with self._resources.engine_invocation():
            return {
                "prediction_axis": PredictionResidueAxis(
                    source=reference,
                    layout=ResidueLayout(
                        "A",
                        75,
                        tuple(f"A:{index}" for index in range(1, 76)),
                    ),
                    sequence=candidate.data,
                )
            }


def _build_three_way_source(context: OperationContext) -> _ThreeWaySource:
    return _ThreeWaySource(context.resources)


def _build_prediction_axis_source(
    context: OperationContext,
) -> _PredictionAxisSource:
    return _PredictionAxisSource(context.resources)


def _build_esmfold2_confidence_source(
    context: OperationContext,
) -> _ConfidenceSource:
    return _ConfidenceSource(context)


def _build_simplefold_confidence_source(
    context: OperationContext,
) -> _ConfidenceSource:
    return _ConfidenceSource(context)


def _build_confidence_fact_source(
    context: OperationContext,
) -> _ConfidenceFactSource:
    return _ConfidenceFactSource(context)


def _fixture_binding(
    *,
    binding_id: str,
    node_type_id: str,
    method_id: str,
    factory_name: str,
    build,
    produced_observations: tuple[ProducedObservationDefinition, ...] = (),
) -> ExecutionBindingDefinition:
    return ExecutionBindingDefinition(
        binding_id=binding_id,
        version=_VERSION,
        node_type=ContractIdentity("node_type", node_type_id, _VERSION),
        method=ContractIdentity("method", method_id, "4.0.0"),
        binding_parameters={},
        execution_route="direct",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(factory_name, _VERSION, {}),
            build=build,
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(f"{binding_id}/availability", _VERSION, {}),
            prerequisites={},
            check=AvailabilityResult.available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(f"{binding_id}/readiness", _VERSION, {}),
            prerequisites={},
            check=lambda check_input: ReadinessResult(True),
        ),
        deterministic=True,
        cacheable=True,
        implementation_identity={
            "name": binding_id,
            "source": "contract-test-fixture",
        },
        produced_observations=produced_observations,
    )


MODULE_PACKAGE = ModulePackageRegistration(
    schema_version="2.1.0",
    package_id="contract_test.structure_comparison_sources",
    package_version=_VERSION,
    package_module=__package__,
    node_definitions=(
        DefinitionResource("definition.yaml"),
        DefinitionResource("three_way_source.yaml"),
        DefinitionResource("prediction_axis_source.yaml"),
        DefinitionResource("prediction_confidence_fact_source.yaml"),
        DefinitionResource("prediction_confidence_source.yaml"),
    ),
    methods=(
        MethodDefinition(
            method_id="contract_test.structure_comparison_source.method",
            version=_VERSION,
            algorithm_identity={
                "name": "independent-structure-candidate-collections"
            },
            model_identity={"kind": "none"},
            checkpoint_identity={"kind": "none"},
            featurization_identity={"kind": "canonical-PDB-v3.3"},
            source_identity={"kind": "contract-test-fixture"},
            scale_contract={"coordinate_unit": "angstrom"},
        ),
        *tuple(
            method
            for method in FOLDING_PACKAGE.methods
            if method.method_id
            in {
                "folding.fold.esmfold2_fast_biohub_2026_05",
                "folding.fold.simplefold_100m_c7a5570",
            }
        ),
    ),
    bindings=(
        ExecutionBindingDefinition(
            binding_id="contract_test.structure_comparison_source.fixture",
            version=_VERSION,
            node_type=ContractIdentity(
                "node_type",
                "contract_test.structure_comparison_source",
                _VERSION,
            ),
            method=ContractIdentity(
                "method",
                "contract_test.structure_comparison_source.method",
                _VERSION,
            ),
            binding_parameters={},
            execution_route="direct",
            factory=ScientificOperationFactory(
                behavior=BehaviorReference(
                    "contract_test.structure_comparison_source/factory",
                    _VERSION,
                    {},
                ),
                build=_build,
            ),
            availability=AvailabilityDeclaration(
                behavior=BehaviorReference(
                    "contract_test.structure_comparison_source/availability",
                    _VERSION,
                    {},
                ),
                prerequisites={},
                check=AvailabilityResult.available,
            ),
            readiness=ReadinessDeclaration(
                behavior=BehaviorReference(
                    "contract_test.structure_comparison_source/readiness",
                    _VERSION,
                    {},
                ),
                prerequisites={},
                check=lambda check_input: ReadinessResult(True),
            ),
            deterministic=True,
            cacheable=True,
            implementation_identity={
                "name": "contract_test.structure_comparison_source.fixture",
                "source": "contract-test-fixture",
            },
        ),
        _fixture_binding(
            binding_id="contract_test.1pga_three_way_source.fixture",
            node_type_id="contract_test.1pga_three_way_source",
            method_id="contract_test.structure_comparison_source.method",
            factory_name="contract_test.1pga_three_way_source/factory",
            build=_build_three_way_source,
        ),
        _fixture_binding(
            binding_id="contract_test.prediction_axis_source.fixture",
            node_type_id="contract_test.prediction_axis_source",
            method_id="contract_test.structure_comparison_source.method",
            factory_name="contract_test.prediction_axis_source/factory",
            build=_build_prediction_axis_source,
        ),
        _fixture_binding(
            binding_id="contract_test.esmfold2_confidence_source.fixture",
            node_type_id="contract_test.prediction_confidence_source",
            method_id="folding.fold.esmfold2_fast_biohub_2026_05",
            factory_name="contract_test.esmfold2_confidence_source/factory",
            build=_build_esmfold2_confidence_source,
            produced_observations=(
                ProducedObservationDefinition(
                    output_port="observations",
                    output_partition="prediction_confidence",
                    metric=ContractIdentity(
                        "metric", "structure.plddt.mean_residue", "3.0.0"
                    ),
                    context_profile={"kind": "intrinsic"},
                    subject_grain="candidate",
                    source_role="subject",
                    subject_direction="input",
                    subject_port="structures",
                    axis_direction="input",
                    axis_port="confidence_facts",
                    guaranteed_multiplicity="one",
                ),
            ),
        ),
        _fixture_binding(
            binding_id="contract_test.simplefold_confidence_source.fixture",
            node_type_id="contract_test.prediction_confidence_source",
            method_id="folding.fold.simplefold_100m_c7a5570",
            factory_name="contract_test.simplefold_confidence_source/factory",
            build=_build_simplefold_confidence_source,
            produced_observations=(
                ProducedObservationDefinition(
                    output_port="observations",
                    output_partition="prediction_confidence",
                    metric=ContractIdentity(
                        "metric", "structure.plddt.mean_residue", "3.0.0"
                    ),
                    context_profile={"kind": "intrinsic"},
                    subject_grain="candidate",
                    source_role="subject",
                    subject_direction="input",
                    subject_port="structures",
                    axis_direction="input",
                    axis_port="confidence_facts",
                    guaranteed_multiplicity="one",
                ),
            ),
        ),
        _fixture_binding(
            binding_id="contract_test.esmfold2_confidence_fact_source.fixture",
            node_type_id="contract_test.prediction_confidence_fact_source",
            method_id="folding.fold.esmfold2_fast_biohub_2026_05",
            factory_name="contract_test.esmfold2_confidence_fact_source/factory",
            build=_build_confidence_fact_source,
        ),
        _fixture_binding(
            binding_id="contract_test.simplefold_confidence_fact_source.fixture",
            node_type_id="contract_test.prediction_confidence_fact_source",
            method_id="folding.fold.simplefold_100m_c7a5570",
            factory_name="contract_test.simplefold_confidence_fact_source/factory",
            build=_build_confidence_fact_source,
        ),
    ),
)
