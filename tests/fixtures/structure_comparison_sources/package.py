"""Independent Candidate-associated source for comparison conformance."""

from __future__ import annotations

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
    ReadinessDeclaration,
    ReadinessResult,
    ScientificOperationFactory,
)
from datatypes import (
    Candidate,
    CandidateCollection,
    ProteinStructure,
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


MODULE_PACKAGE = ModulePackageRegistration(
    schema_version="2.1.0",
    package_id="contract_test.structure_comparison_sources",
    package_version=_VERSION,
    package_module=__package__,
    node_definitions=(DefinitionResource("definition.yaml"),),
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
    ),
)
