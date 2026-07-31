"""Independent source registration for structure-comparison acceptance."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from core import (
    AvailabilityDeclaration,
    AvailabilityResult,
    BehaviorReference,
    ContractIdentity,
    DefinitionResource,
    ExecutionBindingDefinition,
    LazyImplementationFactory,
    MethodDefinition,
    ModulePackageRegistration,
    ReadinessDeclaration,
    ReadinessResult,
    UtilityTransformDefinition,
)
from datatypes import (
    Candidate,
    CandidateCollection,
    PairwiseCandidateMapping,
    PairwiseCandidateMatch,
    ProteinStructure,
)


_VERSION = "2.1.0"
_TM_METRIC = ContractIdentity(
    "metric",
    "structure_comparison.tm_score",
    _VERSION,
)
_TM_METHOD = ContractIdentity(
    "method",
    "structure_comparison.tm_score.reference_normalized.method",
    _VERSION,
)
_RESIDUES = ("ALA", "GLY", "SER", "THR")
_RESIDUE_NAMES = {
    "A": "ALA",
    "G": "GLY",
    "S": "SER",
    "T": "THR",
}


def _pdb(
    coordinates: Sequence[tuple[float, float, float]],
    *,
    chain: str,
) -> ProteinStructure:
    lines = [
        (
            f"ATOM  {index:5d}  CA  {_RESIDUES[index - 1]} {chain}"
            f"{index:4d}    "
            f"{x:8.3f}{y:8.3f}{z:8.3f}"
            "  1.00 20.00           C"
        )
        for index, (x, y, z) in enumerate(coordinates, start=1)
    ]
    return ProteinStructure(
        pdb_string="\n".join((*lines, "TER", "END", "")),
        source="contract-test",
    )


def _sequence_pdb(sequence: str, *, chain: str) -> ProteinStructure:
    lines = [
        (
            f"ATOM  {index:5d}  CA  {_RESIDUE_NAMES[amino_acid]} {chain}"
            f"{index:4d}    "
            f"{index * 1.5:8.3f}{index % 3:8.3f}{index % 2:8.3f}"
            "  1.00 20.00           C"
        )
        for index, amino_acid in enumerate(sequence, start=1)
    ]
    return ProteinStructure(
        pdb_string="\n".join((*lines, "TER", "END", "")),
        source="contract-test",
    )


_REFERENCE_A = _pdb(
    ((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 3.0, 0.0)),
    chain="R",
)
_SUBJECT_A = _pdb(
    ((5.0, -2.0, 1.0), (7.0, -2.0, 1.0), (5.0, 1.0, 1.0)),
    chain="A",
)
_REFERENCE_B = _pdb(
    ((0.0, 0.0, 0.0), (3.0, 0.0, 0.0), (0.0, 2.0, 0.0)),
    chain="S",
)
_SUBJECT_B = _pdb(
    ((-4.0, 6.0, 2.0), (-1.0, 6.0, 2.0), (-4.0, 8.0, 2.0)),
    chain="B",
)
_FIXED_REFERENCE = _pdb(
    (
        (0.0, 0.0, 0.0),
        (2.0, 0.0, 0.0),
        (0.0, 3.0, 0.0),
        (2.0, 3.0, 1.0),
    ),
    chain="R",
)
_FIXED_SUBJECT_A = _pdb(
    ((5.0, -2.0, 1.0), (7.0, -2.0, 1.0), (5.0, 1.0, 1.0)),
    chain="A",
)
_FIXED_SUBJECT_B = _pdb(
    ((-4.0, 6.0, 2.0), (-2.0, 6.0, 2.0), (-4.0, 9.0, 2.0)),
    chain="B",
)
_INCOMPATIBLE = ProteinStructure(
    pdb_string="HEADER    NO COORDINATES\nEND\n",
    source="contract-test",
)
_AMBIGUOUS_REFERENCE = _sequence_pdb(
    "GTSAGTATSTSTGGSTGGGAGTAGTSGASGTGGGGSAATS",
    chain="R",
)
_AMBIGUOUS_SUBJECT = _sequence_pdb(
    "SATSGTTSSASAAGTAAASTTGSTSGSSSGTTTTTASAAGSGSS",
    chain="A",
)


class _Source:
    def __init__(self, run_resources: Any, catalog: Any) -> None:
        self._run_resources = run_resources
        self._catalog = catalog

    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        if (
            inputs
            or binding_parameters
            or set(node_parameters) != {"scenario"}
            or node_parameters["scenario"]
            not in {
                "single",
                "paired",
                "fixed_batch",
                "failing_pair",
                "conflicting_pairing",
                "ambiguous",
            }
        ):
            raise ValueError("structure comparison fixture is not resolved")
        scenario = node_parameters["scenario"]
        if scenario == "single":
            subject_values = (("subject-a", _SUBJECT_A),)
            reference_values = (("reference-a", _REFERENCE_A),)
            pairs = (("subject-a", "reference-a"),)
        elif scenario == "ambiguous":
            subject_values = (("subject-ambiguous", _AMBIGUOUS_SUBJECT),)
            reference_values = (
                ("reference-ambiguous", _AMBIGUOUS_REFERENCE),
            )
            pairs = (("subject-ambiguous", "reference-ambiguous"),)
        elif scenario == "fixed_batch":
            subject_values = (
                ("subject-fixed-a", _FIXED_SUBJECT_A),
                ("subject-fixed-b", _FIXED_SUBJECT_B),
            )
            reference_values = (
                ("reference-fixed", _FIXED_REFERENCE),
            )
            pairs = ()
        else:
            subject_values = (
                ("subject-a", _SUBJECT_A),
                (
                    "subject-b",
                    _SUBJECT_B
                    if scenario in {"paired", "conflicting_pairing"}
                    else _INCOMPATIBLE,
                ),
            )
            reference_values = (
                ("reference-b", _REFERENCE_B),
                ("reference-a", _REFERENCE_A),
            )
            pairs = (
                (
                    ("subject-a", "reference-a"),
                    ("subject-b", "reference-b"),
                )
                if scenario == "failing_pair"
                else (
                    ("subject-b", "reference-b"),
                    ("subject-a", "reference-a"),
                )
            )
        subjects = CandidateCollection(
            collection_id=f"fixture-{scenario}-subjects",
            item_type="protein.structure",
            items=[
                Candidate(
                    candidate_id=candidate_id,
                    data=structure,
                    metadata={"fixture_label": candidate_id},
                )
                for candidate_id, structure in subject_values
            ],
        )
        references = CandidateCollection(
            collection_id=f"fixture-{scenario}-references",
            item_type="protein.structure",
            items=[
                Candidate(
                    candidate_id=candidate_id,
                    data=structure,
                    metadata={"fixture_label": candidate_id},
                )
                for candidate_id, structure in reference_values
            ],
        )
        structures = {
            candidate.candidate_id: candidate.data
            for collection in (subjects, references)
            for candidate in collection.items
        }
        codec = self._catalog.require_port_type(
            "protein.structure",
            _VERSION,
        )
        pairing = PairwiseCandidateMapping(
            entries=[
                PairwiseCandidateMatch(
                    subject_candidate_id=subject_id,
                    subject_content_digest=(
                        "sha256:" + "f" * 64
                        if scenario == "conflicting_pairing"
                        and subject_id == "subject-b"
                        else codec.content_digest(structures[subject_id])
                    ),
                    reference_candidate_id=reference_id,
                    reference_content_digest=codec.content_digest(
                        structures[reference_id]
                    ),
                )
                for subject_id, reference_id in pairs
            ]
        )
        with self._run_resources.engine_invocation(
            engine_identity=(
                "contract_test.structure_comparison_source.method/2.1.0"
            ),
        ):
            return {
                "subjects": subjects,
                "references": references,
                "pairing": pairing,
            }


def _build(**kwargs: object) -> object:
    return _Source(
        kwargs["run_resources"],
        kwargs["frozen_catalog"],
    )


def _tm_identity(value: object, parameters: Mapping[str, Any]) -> float:
    if parameters:
        raise ValueError("TM-score identity Utility accepts no parameters")
    result = float(value)
    if not 0.0 <= result <= 1.0:
        raise ValueError("TM-score identity Utility requires [0, 1]")
    return result


def _tm_utility(
    transform_id: str,
    pairing_mode: str,
) -> UtilityTransformDefinition:
    return UtilityTransformDefinition(
        transform_id=transform_id,
        version=_VERSION,
        compatible_input_contract={
            "metric": _TM_METRIC,
            "method": _TM_METHOD,
            "context_profile": {
                "kind": "pairwise",
                "subject_role": "subject",
                "reference_role": "reference",
                "pairing_mode": pairing_mode,
                "normalization": "standard-reference-residue-count",
            },
        },
        parameters={},
        behavior=BehaviorReference(
            f"{transform_id}/transform",
            _VERSION,
            {"mapping": "identity"},
        ),
        transform=_tm_identity,
    )


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
            algorithm_identity={"name": "independent-literal-structures"},
            model_identity={"kind": "none"},
            checkpoint_identity={"kind": "none"},
            featurization_identity={"kind": "PDB-CA-fixtures"},
            source_identity={"kind": "contract-test-fixture"},
            scale_contract={"kind": "angstrom"},
        ),
    ),
    bindings=(
        ExecutionBindingDefinition(
            binding_id="contract_test.structure_comparison_source.direct",
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
            factory=LazyImplementationFactory(
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
                check=lambda environment: ReadinessResult(True),
            ),
            deterministic=True,
            cacheable=True,
            implementation_identity={
                "name": "contract_test.structure_comparison_source.direct",
                "source": "contract-test-fixture",
            },
        ),
    ),
    utility_transforms=(
        _tm_utility(
            "contract_test.tm_score.fixed_identity",
            "fixed_reference",
        ),
        _tm_utility(
            "contract_test.tm_score.paired_identity",
            "per_subject_counterpart",
        ),
    ),
)
