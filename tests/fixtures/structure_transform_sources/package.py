"""Independent source and sink used by structure-transform acceptance."""

from __future__ import annotations

from typing import Any, Mapping

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
)
from datatypes import Candidate, CandidateCollection, ProteinStructure


def _atom(
    serial: int,
    atom_name: str,
    residue_name: str,
    chain_id: str,
    residue_number: int,
    *,
    x: float,
    altloc: str = " ",
    occupancy: float = 1.0,
    record: str = "ATOM",
) -> str:
    element = atom_name[0]
    return (
        f"{record:<6}{serial:5d} {atom_name:^4}{altloc}"
        f"{residue_name:>3} {chain_id}{residue_number:4d}    "
        f"{x:8.3f}{2.0:8.3f}{3.0:8.3f}"
        f"{occupancy:6.2f}{20.0:6.2f}          {element:>2}"
    )


def _residue(
    serial: int,
    residue_name: str,
    chain_id: str,
    residue_number: int,
    *,
    include_oxygen: bool = True,
    sidechain: bool = True,
) -> tuple[list[str], int]:
    atoms = ["N", "CA", "C"]
    if include_oxygen:
        atoms.append("O")
    if sidechain:
        atoms.append("CB")
    lines = [
        _atom(
            serial + index,
            atom_name,
            residue_name,
            chain_id,
            residue_number,
            x=float(serial + index),
        )
        for index, atom_name in enumerate(atoms)
    ]
    return lines, serial + len(atoms)


def _canonical() -> str:
    first, serial = _residue(1, "ALA", "A", 1)
    second, serial = _residue(serial, "GLY", "B", 5)
    return "\n".join(
        [
            "REMARK private-source-label-must-not-be-public",
            *first,
            "TER",
            *second,
            _atom(
                serial,
                "ZN",
                "ZN",
                "B",
                900,
                x=99.0,
                record="HETATM",
            ),
            "TER",
            "END",
            "",
        ]
    )


def _alternate_locations() -> str:
    lines = [
        _atom(1, "N", "ALA", "A", 1, x=1.0),
        _atom(
            2,
            "CA",
            "ALA",
            "A",
            1,
            x=20.0,
            altloc="B",
            occupancy=0.9,
        ),
        _atom(
            3,
            "CA",
            "ALA",
            "A",
            1,
            x=10.0,
            altloc="A",
            occupancy=0.1,
        ),
        _atom(4, "C", "ALA", "A", 1, x=4.0),
        _atom(5, "O", "ALA", "A", 1, x=5.0),
        "TER",
        "END",
        "",
    ]
    return "\n".join(lines)


def _missing_backbone() -> str:
    lines, _ = _residue(
        1,
        "ALA",
        "A",
        1,
        include_oxygen=False,
    )
    return "\n".join([*lines, "TER", "END", ""])


def _multi_model() -> str:
    first, _ = _residue(1, "ALA", "A", 1, sidechain=False)
    second, _ = _residue(10, "GLY", "A", 1, sidechain=False)
    return "\n".join(
        [
            "MODEL        1",
            *first,
            "ENDMDL",
            "MODEL        2",
            *second,
            "ENDMDL",
            "END",
            "",
        ]
    )


def _residue_name_conflict() -> str:
    lines = [
        _atom(1, "N", "ALA", "A", 1, x=1.0),
        _atom(2, "CA", "GLY", "A", 1, x=2.0),
        _atom(3, "C", "ALA", "A", 1, x=3.0),
        _atom(4, "O", "ALA", "A", 1, x=4.0),
        "TER",
        "END",
        "",
    ]
    return "\n".join(lines)


def _sequence_edge_cases() -> str:
    first, serial = _residue(1, "ALA", "A", 1, sidechain=False)
    unknown, serial = _residue(serial, "UNK", "A", 2, sidechain=False)
    non_protein, serial = _residue(
        serial,
        "MSE",
        "A",
        3,
        sidechain=False,
    )
    non_protein = [
        line.replace("ATOM  ", "HETATM", 1)
        for line in non_protein
    ]
    second_chain, _ = _residue(
        serial,
        "GLY",
        "B",
        5,
        sidechain=False,
    )
    return "\n".join(
        [
            *first,
            *unknown,
            *non_protein,
            "TER",
            *second_chain,
            "TER",
            "END",
            "",
        ]
    )


def _csh() -> str:
    atom_names = (
        "CA1",
        "CA2",
        "CA3",
        "CB1",
        "CB2",
        "CG",
        "OG2",
        "CD2",
        "ND1",
        "CE1",
        "NE2",
        "C1",
        "N1",
        "C2",
        "N2",
        "O2",
        "C3",
        "N3",
        "O3",
    )
    return "\n".join([
        *(
            _atom(
                index,
                atom_name,
                "CSH",
                "A",
                66,
                x=float(index),
                record="HETATM",
            )
            for index, atom_name in enumerate(atom_names, start=1)
        ),
        "TER",
        "END",
        "",
    ])


_FIXTURES = {
    "canonical": _canonical,
    "alternate_locations": _alternate_locations,
    "missing_backbone": _missing_backbone,
    "multi_model": _multi_model,
    "residue_name_conflict": _residue_name_conflict,
    "sequence_edge_cases": _sequence_edge_cases,
    "csh": _csh,
}


class _Source:
    def __init__(self, resources: Any) -> None:
        self._resources = resources

    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        if inputs or binding_parameters:
            raise ValueError("fixture source accepts no connected values")
        fixture = node_parameters["fixture"]
        with self._resources.engine_invocation(
            engine_identity="contract_test.structure_transform_source/2.1.0",
        ):
            structure = ProteinStructure(
                pdb_string=_FIXTURES[fixture](),
                source="contract-test",
            )
            return {
                "structure": structure,
                "structure_candidates": CandidateCollection(
                    "fixture-structure-candidates",
                    "protein.structure",
                    [Candidate("fixture-structure", structure)],
                ),
            }


class _BackboneSink:
    def __init__(self, resources: Any) -> None:
        self._resources = resources

    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        if node_parameters or binding_parameters or set(inputs) != {"backbone"}:
            raise ValueError("backbone sink requires one backbone")
        with self._resources.engine_invocation(
            engine_identity="contract_test.backbone_sink/2.1.0",
        ):
            return {"accepted": "accepted"}


def _build(operation: str):
    def factory(**kwargs: object) -> object:
        implementation = {
            "source": _Source,
            "backbone_sink": _BackboneSink,
        }[operation]
        return implementation(kwargs["run_resources"])

    return factory


def _method(operation: str) -> MethodDefinition:
    return MethodDefinition(
        method_id=f"contract_test.structure_transform.{operation}.method",
        version="2.1.0",
        algorithm_identity={"name": f"deterministic-{operation}"},
        model_identity={"kind": "none"},
        checkpoint_identity={"kind": "none"},
        featurization_identity={"kind": "pdb-v3.3"},
        source_identity={"kind": "contract-test"},
        scale_contract={"kind": "identity"},
    )


def _binding(operation: str) -> ExecutionBindingDefinition:
    node_id = (
        "contract_test.structure_transform_source"
        if operation == "source"
        else "contract_test.backbone_sink"
    )
    return ExecutionBindingDefinition(
        binding_id=f"{node_id}.direct",
        version="2.1.0",
        node_type=ContractIdentity("node_type", node_id, "2.1.0"),
        method=ContractIdentity(
            "method",
            f"contract_test.structure_transform.{operation}.method",
            "2.1.0",
        ),
        binding_parameters={},
        execution_route="direct",
        factory=LazyImplementationFactory(
            behavior=BehaviorReference(
                f"{node_id}/factory",
                "2.1.0",
                {},
            ),
            build=_build(operation),
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                f"{node_id}/availability",
                "2.1.0",
                {},
            ),
            prerequisites={},
            check=AvailabilityResult.available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                f"{node_id}/readiness",
                "2.1.0",
                {},
            ),
            prerequisites={},
            check=lambda environment: ReadinessResult(True),
        ),
        deterministic=True,
        cacheable=True,
        implementation_identity={
            "name": f"{node_id}.direct",
            "source": "contract-test",
        },
    )


MODULE_PACKAGE = ModulePackageRegistration(
    schema_version="2.1.0",
    package_id="contract_test.structure_transform_sources",
    package_version="2.1.0",
    package_module=__package__,
    node_definitions=(
        DefinitionResource("source.yaml"),
        DefinitionResource("backbone_sink.yaml"),
    ),
    methods=tuple(_method(operation) for operation in ("source", "backbone_sink")),
    bindings=tuple(_binding(operation) for operation in ("source", "backbone_sink")),
)
