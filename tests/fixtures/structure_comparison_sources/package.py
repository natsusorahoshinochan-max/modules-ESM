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
    serial = 1
    for index, (amino_acid, coordinate) in enumerate(
        zip(sequence, base, strict=True),
        start=1,
    ):
        x = coordinate[0] + translation[0]
        y = coordinate[1] + translation[1]
        z = coordinate[2] + translation[2]
        for atom_name, dx, dy, element in (
            ("N", -1.2, 0.0, "N"),
            ("CA", 0.0, 0.0, "C"),
            ("C", 1.2, 0.0, "C"),
            ("O", 1.2, 2.2, "O"),
        ):
            line = (
                f"ATOM  {serial:5d} {atom_name:^4s} "
                f"{_RESIDUE_NAMES[amino_acid]} {chain_id}{index:4d}    "
                f"{x + dx:8.3f}{y + dy:8.3f}{z:8.3f}"
                f"  1.00 20.00          {element:>2s}"
            )
            lines.append(line.ljust(80))
            serial += 1
    return ProteinStructure("\n".join((*lines, "TER", "END", "")))


def _inserted_loop_structure(*, with_loop: bool) -> ProteinStructure:
    sequence = "AGAST" if with_loop else "AGST"
    ca_coordinates = (
        (
            (0.0, 0.0, 0.0),
            (3.8, 0.0, 0.0),
            (9.4, 4.0, 0.0),
            (15.0, 0.0, 0.0),
            (18.8, 0.0, 0.0),
        )
        if with_loop
        else (
            (0.0, 0.0, 0.0),
            (3.8, 0.0, 0.0),
            (15.0, 0.0, 0.0),
            (18.8, 0.0, 0.0),
        )
    )
    lines: list[str] = []
    serial = 1
    for index, (amino_acid, ca) in enumerate(
        zip(sequence, ca_coordinates, strict=True),
        start=1,
    ):
        if with_loop and index == 3:
            atoms = (
                ("N", (6.35, 0.0, 0.0), "N"),
                ("CA", ca, "C"),
                ("C", (12.45, 0.0, 0.0), "C"),
                ("O", (11.5, 2.5, 0.0), "O"),
            )
        else:
            atoms = (
                ("N", (ca[0] - 1.2, ca[1], ca[2]), "N"),
                ("CA", ca, "C"),
                ("C", (ca[0] + 1.2, ca[1], ca[2]), "C"),
                ("O", (ca[0] + 1.2, ca[1] + 2.2, ca[2]), "O"),
            )
        for atom_name, coordinate, element in atoms:
            line = (
                f"ATOM  {serial:5d} {atom_name:^4s} "
                f"{_RESIDUE_NAMES[amino_acid]} A{index:4d}    "
                f"{coordinate[0]:8.3f}{coordinate[1]:8.3f}"
                f"{coordinate[2]:8.3f}  1.00 20.00          {element:>2s}"
            )
            lines.append(line.ljust(80))
            serial += 1
    return ProteinStructure("\n".join((*lines, "TER", "END", "")))


class _InsertedLoopSource:
    def __init__(self, resources: object) -> None:
        self._resources = resources

    def execute(self, call: OperationCall) -> dict[str, object]:
        if call.inputs or call.node_parameters or call.binding_parameters:
            raise ValueError("inserted-loop source accepts no inputs or parameters")
        reference = Candidate("reference", _inserted_loop_structure(with_loop=False))
        sequence = Candidate(
            "sequence",
            ProteinSequence(
                "AGAST",
                residue_ids=("A:1", "A:2", "A:loop", "A:3", "A:4"),
            ),
            parent_ids=(reference.candidate_id,),
        )
        subject = Candidate(
            "subject",
            _inserted_loop_structure(with_loop=True),
            parent_ids=(sequence.candidate_id,),
        )
        counterpart = Candidate(
            "counterpart",
            _inserted_loop_structure(with_loop=True),
            parent_ids=(sequence.candidate_id,),
        )
        with self._resources.engine_invocation():
            return {
                "subjects": CandidateCollection(
                    "inserted-loop-subjects", "protein.structure", (subject,)
                ),
                "references": CandidateCollection(
                    "inserted-loop-references", "protein.structure", (reference,)
                ),
                "counterparts": CandidateCollection(
                    "inserted-loop-counterparts",
                    "protein.structure",
                    (counterpart,),
                ),
                "sequence_parents": CandidateCollection(
                    "inserted-loop-sequences", "protein.sequence", (sequence,)
                ),
                "pairing": CandidatePairingIntent(
                    entries=(CandidatePairingIntentEntry("subject", "counterpart"),)
                ),
            }


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
        structures = call.inputs["structures"].value
        facts = call.inputs["confidence_facts"].value
        assert type(structures) is CandidateCollection
        assert type(facts) is ConfidenceFactCollection
        if len(structures.items) != 1 or len(facts.entries) != 1:
            raise ValueError("confidence source requires one structure and fact")
        structure_reference = call.inputs[
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


class _PerResidueConfidenceSource:
    def __init__(self, context: OperationContext) -> None:
        self._method = context.method
        self._metric = context.produced_observations[0].metric
        self._resources = context.resources

    def execute(self, call: OperationCall) -> dict[str, object]:
        if call.node_parameters or call.binding_parameters:
            raise ValueError("per-residue confidence source accepts no parameters")
        structures = call.inputs["structures"].value
        facts = call.inputs["confidence_facts"].value
        assert type(structures) is CandidateCollection
        assert type(facts) is ConfidenceFactCollection
        if len(structures.items) != 1 or len(facts.entries) != 1:
            raise ValueError("per-residue confidence source requires one prediction")
        subject = call.inputs["structures"].candidate_data[0]
        fact = facts.entries[0]
        if fact.structure_content_digest != subject.content_digest:
            raise ValueError("confidence fact does not identify the structure")
        with self._resources.engine_invocation():
            return {
                "observations": ScoreCollection(
                    "prediction-confidence",
                    (
                        ScoreObservation(
                            subject=subject,
                            metric=self._metric,
                            method=self._method,
                            context=IntrinsicObservationContext(),
                            value=tuple(fact.plddt_per_residue),
                            residue_axis=prediction_axis_reference(
                                fact.prediction_axis
                            ),
                            source_partition="prediction_confidence",
                        ),
                    ),
                )
            }


class _ConfidenceFactSource:
    def __init__(self, context: OperationContext) -> None:
        self._method = context.method
        self._resources = context.resources

    def execute(self, call: OperationCall) -> dict[str, object]:
        if call.binding_parameters:
            raise ValueError("confidence-fact source accepts no Binding parameters")
        structures = call.inputs["structures"].value
        prediction_axis = call.inputs["prediction_axis"].value
        assert type(structures) is CandidateCollection
        assert type(prediction_axis) is PredictionResidueAxis
        if len(structures.items) != 1:
            raise ValueError("confidence-fact source requires one structure")
        structure_reference = call.inputs[
            "structures"
        ].candidate_data[0]
        axis_digest = PREDICTION_RESIDUE_AXIS_PORT_TYPE.content_digest(
            prediction_axis
        )
        missing_loop = call.node_parameters["missing_loop_plddt"]
        plddt = tuple(
            None if missing_loop and residue_id == "A:loop" else 90.0
            for residue_id in prediction_axis.layout.residue_ids or ()
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
            plddt_per_residue=plddt,
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
        sequences = call.inputs["sequence_parents"].value
        assert type(sequences) is CandidateCollection
        if len(sequences.items) != 1:
            raise ValueError("prediction-axis source requires one sequence")
        candidate = sequences.items[0]
        assert type(candidate.data) is ProteinSequence
        residue_ids = tuple(candidate.data.residue_ids or ())
        if len(residue_ids) != len(candidate.data):
            raise ValueError("prediction-axis source requires exact residue identities")
        reference = call.inputs[
            "sequence_parents"
        ].candidate_data[0]
        with self._resources.engine_invocation():
            return {
                "prediction_axis": PredictionResidueAxis(
                    source=reference,
                    layout=ResidueLayout(
                        "A",
                        len(candidate.data),
                        residue_ids,
                    ),
                    sequence=candidate.data,
                )
            }


def _build_three_way_source(context: OperationContext) -> _ThreeWaySource:
    return _ThreeWaySource(context.resources)


def _build_inserted_loop_source(context: OperationContext) -> _InsertedLoopSource:
    return _InsertedLoopSource(context.resources)


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


def _build_inserted_loop_confidence_source(
    context: OperationContext,
) -> _PerResidueConfidenceSource:
    return _PerResidueConfidenceSource(context)


def _build_confidence_fact_source(
    context: OperationContext,
) -> _ConfidenceFactSource:
    return _ConfidenceFactSource(context)


def _fixture_binding(
    *,
    binding_id: str,
    node_type_id: str,
    method_id: str,
    method_version: str = _VERSION,
    factory_name: str,
    build,
    produced_observations: tuple[ProducedObservationDefinition, ...] = (),
) -> ExecutionBindingDefinition:
    return ExecutionBindingDefinition(
        binding_id=binding_id,
        version=_VERSION,
        node_type=ContractIdentity("node_type", node_type_id, _VERSION),
        method=ContractIdentity("method", method_id, method_version),
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
        DefinitionResource("inserted_loop_source.yaml"),
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
            binding_id="contract_test.inserted_loop_source.fixture",
            node_type_id="contract_test.inserted_loop_source",
            method_id="contract_test.structure_comparison_source.method",
            factory_name="contract_test.inserted_loop_source/factory",
            build=_build_inserted_loop_source,
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
            binding_id="contract_test.inserted_loop_confidence_source.fixture",
            node_type_id="contract_test.prediction_confidence_source",
            method_id="folding.fold.esmfold2_fast_biohub_2026_05",
            factory_name="contract_test.inserted_loop_confidence_source/factory",
            build=_build_inserted_loop_confidence_source,
            produced_observations=(
                ProducedObservationDefinition(
                    output_port="observations",
                    output_partition="prediction_confidence",
                    metric=ContractIdentity(
                        "metric", "structure.plddt.per_residue", "3.0.0"
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
            method_version="5.0.0",
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
            method_version="5.0.0",
            factory_name="contract_test.simplefold_confidence_fact_source/factory",
            build=_build_confidence_fact_source,
        ),
    ),
)
