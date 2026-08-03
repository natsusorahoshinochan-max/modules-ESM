"""Independent source and sink used by structure-transform acceptance."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core import (
    AvailabilityDeclaration,
    AvailabilityResult,
    BehaviorReference,
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
from datatypes import Candidate, CandidateCollection, ProteinStructure


_PROJECT_ROOT = Path(__file__).resolve().parents[3]


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
    element: str | None = None,
) -> str:
    element_symbol = element or atom_name[0]
    return (
        f"{record:<6}{serial:5d} {atom_name:^4}{altloc}"
        f"{residue_name:>3} {chain_id}{residue_number:4d}    "
        f"{x:8.3f}{2.0:8.3f}{3.0:8.3f}"
        f"{occupancy:6.2f}{20.0:6.2f}          {element_symbol:>2}  "
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
    second, serial = _residue(serial, "VAL", "A", 2, sidechain=False)
    non_protein = [
        _atom(
            serial,
            "C1",
            "LIG",
            "A",
            3,
            x=float(serial),
            record="HETATM",
            element="C",
        )
    ]
    serial += 1
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
            *second,
            *non_protein,
            "TER",
            *second_chain,
            "TER",
            "END",
            "",
        ]
    )


def _mse_ligand_water() -> str:
    header = [" "] * 80
    header[0:6] = "MODRES"
    header[7:11] = "TEST"
    header[12:15] = "MSE"
    header[16] = "A"
    header[18:22] = f"{2:4d}"
    header[24:27] = "MET"
    header[29:45] = "SELENOMETHIONINE"

    first, serial = _residue(1, "ALA", "A", 1, sidechain=False)
    mse_atoms = ("N", "CA", "C", "O", "CB", "CG", "SE", "CE")
    mse = [
        _atom(
            serial + index,
            atom_name,
            "MSE",
            "A",
            2,
            x=float(serial + index),
            record="HETATM",
            element="SE" if atom_name == "SE" else None,
        )
        for index, atom_name in enumerate(mse_atoms)
    ]
    serial += len(mse)
    third, serial = _residue(serial, "GLY", "A", 3, sidechain=False)
    ligand = _atom(
        serial,
        "C1",
        "LIG",
        "Z",
        900,
        x=float(serial),
        record="HETATM",
        element="C",
    )
    water = _atom(
        serial + 1,
        "O",
        "HOH",
        "Z",
        901,
        x=float(serial + 1),
        record="HETATM",
        element="O",
    )
    return "\n".join([
        "SEQRES   1 A    3  ALA MSE GLY",
        "".join(header).rstrip(),
        *first,
        *mse,
        *third,
        "TER",
        ligand,
        water,
        "END",
        "",
    ])


def _unknown_modified_polymer() -> str:
    header = [" "] * 80
    header[0:6] = "MODRES"
    header[7:11] = "TEST"
    header[12:15] = "MLY"
    header[16] = "A"
    header[18:22] = f"{2:4d}"
    header[24:27] = "LYS"
    header[29:45] = "METHYLLYSINE"
    first, serial = _residue(1, "ALA", "A", 1, sidechain=False)
    modified, serial = _residue(
        serial,
        "MLY",
        "A",
        2,
        sidechain=False,
    )
    modified = [
        line.replace("ATOM  ", "HETATM", 1)
        for line in modified
    ]
    ligand = _atom(
        serial,
        "C1",
        "LIG",
        "Z",
        900,
        x=float(serial),
        record="HETATM",
    )
    return "\n".join([
        "SEQRES   1 A    2  ALA MLY",
        "".join(header).rstrip(),
        *first,
        *modified,
        "TER",
        ligand,
        "END",
        "",
    ])


def _unknown_atom_polymer() -> str:
    unknown, _ = _residue(1, "UNK", "A", 1, sidechain=False)
    return "\n".join([*unknown, "TER", "END", ""])


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


def _2emo() -> str:
    return (_PROJECT_ROOT / "pdbs" / "2EMO.pdb").read_text()


def _5g53() -> str:
    return (_PROJECT_ROOT / "pdbs" / "5G53.pdb").read_text()


_FIXTURES = {
    "canonical": _canonical,
    "alternate_locations": _alternate_locations,
    "missing_backbone": _missing_backbone,
    "multi_model": _multi_model,
    "residue_name_conflict": _residue_name_conflict,
    "sequence_edge_cases": _sequence_edge_cases,
    "mse_ligand_water": _mse_ligand_water,
    "unknown_modified_polymer": _unknown_modified_polymer,
    "unknown_atom_polymer": _unknown_atom_polymer,
    "csh": _csh,
    "2emo": _2emo,
    "5g53": _5g53,
}


class _Source:
    def __init__(self, resources: Any) -> None:
        self._resources = resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        node_parameters = call.node_parameters
        binding_parameters = call.binding_parameters
        if inputs or binding_parameters:
            raise ValueError("fixture source accepts no connected values")
        fixture = node_parameters["fixture"]
        with self._resources.engine_invocation():
            structure = ProteinStructure(
                pdb_string=_FIXTURES[fixture](),
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

    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        node_parameters = call.node_parameters
        binding_parameters = call.binding_parameters
        if node_parameters or binding_parameters or set(inputs) != {"backbone"}:
            raise ValueError("backbone sink requires one backbone")
        with self._resources.engine_invocation():
            return {"accepted": "accepted"}


def _build(operation: str):
    def factory(context: OperationContext) -> object:
        implementation = {
            "source": _Source,
            "backbone_sink": _BackboneSink,
        }[operation]
        return implementation(context.resources)

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
    node_version = "5.0.0" if operation == "source" else "4.0.0"
    return ExecutionBindingDefinition(
        binding_id=f"{node_id}.direct",
        version=node_version,
        node_type=ContractIdentity("node_type", node_id, node_version),
        method=ContractIdentity(
            "method",
            f"contract_test.structure_transform.{operation}.method",
            "2.1.0",
        ),
        binding_parameters={},
        execution_route="direct",
        factory=ScientificOperationFactory(
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
