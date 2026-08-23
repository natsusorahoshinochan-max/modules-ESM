"""Public contracts for the cohesive structure-transform Module Package."""

from __future__ import annotations

from protein_workbench_public.bootstrap import module_registrations

from contextlib import nullcontext
from dataclasses import replace
import json
from pathlib import Path

import pytest

from core.catalog.builder import (
    build_frozen_catalog,
)
from core.catalog.builtins import (
    builtin_frozen_catalog,
)
from core.catalog.errors import PortValueError
from core.catalog.canonical import canonical_json_bytes
from core.operation import (
    OperationCall,
)
from tests.support.contract_test_kit import (
    ModulePackageContractCase,
    ModulePackagePortCase,
    verify_module_package_contract,
)
from core.workflow.compiler import (
    CompilationRequest,
    compile,
    lock_workflow,
)
from core.workflow.errors import WorkflowCompileError
from core.workflow.document import (
    WorkflowDocument,
    WorkflowNodeInstance,
)
from core.workflow.document import WorkflowEdge
from datatypes.candidate import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
)
from datatypes.residue import (
    ModifiedResidueAtomMapping,
    ModifiedResidueNormalization,
    ModifiedResidueNormalizationCollection,
    ResidueLayout,
)
from datatypes.sequence import ProteinSequence
from datatypes.structure import (
    ProteinStructure,
    ResolvedStructureResidueAxis,
    StructureAtomCoordinate,
    StructureAxisSegment,
    StructureComponentDisposition,
    StructureResidueCoordinates,
)
from modules.structure_transform.domain import (
    CandidateNormalizationFact,
    CandidateNormalizationFactCollection,
    CandidateModifiedResidueNormalizationAssociation,
    CandidateModifiedResidueNormalizationAssociations,
    CandidateResolvedResidueAxisAssociation,
    CandidateResolvedResidueAxisAssociations,
    normalization_key,
)
from modules.structure_transform.port_types import (
    MODIFIED_RESIDUE_NORMALIZATIONS_PORT_TYPE,
)
from modules.structure_transform.package import MODULE_PACKAGE
from modules.structure_transform.candidate_transforms import (
    ExtractSequenceCandidatesImplementation,
    SelectCandidateChainsImplementation,
)
from modules.structure_transform.projections import (
    extract_backbone,
    extract_sequence,
    select_chains,
)
from modules.structure_transform.residue_axis import resolve_residue_axis
from tests.fixtures.scientific_operation import admitted_port_fixture
from tests.fixtures.structure_transform_sources.package import (
    MODULE_PACKAGE as SOURCE_PACKAGE,
)


VERSION = "2.1.0"
CANDIDATE_COLLECTION_VERSION = "4.0.0"
CANDIDATE_NODE_VERSION = "4.0.0"
STRUCTURE_VERSION = "4.0.0"
NORMALIZE_CSH_VERSION = "5.0.0"
CANDIDATE_AXIS_VERSION = "6.0.0"
SOURCE_VERSION = "6.0.0"
BACKBONE_VERSION = "4.0.0"
BACKBONE_METHOD_VERSION = "4.0.0"
NORMALIZATION_VERSION = "3.0.0"
_SOURCE = WorkflowNodeInstance(
    node_id="source",
    node_type_id="contract_test.structure_transform_source",
    node_type_version=SOURCE_VERSION,
    binding_id="contract_test.structure_transform_source.direct",
    binding_version=SOURCE_VERSION,
    node_parameters={"fixture": "canonical"},
    binding_parameters={},
)
_SOURCE_EDGE = WorkflowEdge(
    "source",
    "structure",
    "contract-test-node",
    "structure",
)
_BACKBONE = ProteinStructure(
    pdb_string=(
        "ATOM      1  N   ALA A   1       1.000   2.000   3.000"
        "  1.00 20.00           N  \n"
        "ATOM      2  CA  ALA A   1       2.000   2.000   3.000"
        "  1.00 20.00           C  \n"
        "ATOM      3  C   ALA A   1       3.000   2.000   3.000"
        "  1.00 20.00           C  \n"
        "ATOM      4  O   ALA A   1       4.000   2.000   3.000"
        "  1.00 20.00           O  \n"
        "TER\nEND\n"
    ),
)
_MID_RESIDUE_BREAK = ProteinStructure(
    pdb_string=_BACKBONE.pdb_string.replace(
        "\nATOM      2  CA",
        "\nTER\nATOM      2  CA",
    ),
)
_MISSING_CHAIN_BREAK = ProteinStructure(
    pdb_string=(
        _BACKBONE.pdb_string.removesuffix("TER\nEND\n")
        + "ATOM      5  N   GLY B   1       5.000   2.000   3.000"
        "  1.00 20.00           N  \n"
        "ATOM      6  CA  GLY B   1       6.000   2.000   3.000"
        "  1.00 20.00           C  \n"
        "ATOM      7  C   GLY B   1       7.000   2.000   3.000"
        "  1.00 20.00           C  \n"
        "ATOM      8  O   GLY B   1       8.000   2.000   3.000"
        "  1.00 20.00           O  \n"
        "TER\nEND\n"
    ),
)
_RESOLVED_AXIS = ResolvedStructureResidueAxis(
    structure=_BACKBONE,
    layout=ResidueLayout("A", 1, ("A:1",)),
    sequence="A",
    residue_names=("ALA",),
    segments=(StructureAxisSegment(0, "A", ("A:1",)),),
    component_dispositions=(
        StructureComponentDisposition(
            "ALA",
            "A:1",
            "ATOM",
            "polymer",
            "included",
            ("A:1",),
            "A",
            None,
        ),
    ),
    modified_residue_normalizations=ModifiedResidueNormalizationCollection(),
    residue_coordinates=(
        StructureResidueCoordinates(
            "A:1",
            (
                StructureAtomCoordinate("N", (1.0, 2.0, 3.0)),
                StructureAtomCoordinate("CA", (2.0, 2.0, 3.0)),
                StructureAtomCoordinate("C", (3.0, 2.0, 3.0)),
                StructureAtomCoordinate("O", (4.0, 2.0, 3.0)),
            ),
        ),
    ),
    ca_coordinate_mask=(True,),
    complete_backbone_mask=(True,),
)
_RESOLVED_AXIS_SUBJECT = CandidateDataReference(
    candidate_id="resolved-axis-subject",
    data_type_id="protein.structure",
    content_digest=builtin_frozen_catalog()
    .require_port_type("protein.structure", STRUCTURE_VERSION)
    .content_digest(_BACKBONE),
)
_CANDIDATE_NORMALIZATIONS = CandidateModifiedResidueNormalizationAssociations(
    entries=(
        CandidateModifiedResidueNormalizationAssociation(
            subject=_RESOLVED_AXIS_SUBJECT,
            normalizations=ModifiedResidueNormalizationCollection(),
        ),
    )
)
_CANDIDATE_RESOLVED_AXES = CandidateResolvedResidueAxisAssociations(
    entries=(
        CandidateResolvedResidueAxisAssociation(
            subject=_RESOLVED_AXIS_SUBJECT,
            residue_axis=_RESOLVED_AXIS,
        ),
    )
)
_CSH_NORMALIZATIONS = ModifiedResidueNormalizationCollection(entries=(
    ModifiedResidueNormalization(
        component_id="CSH",
        observed_residue_id="A:66",
        parent_residue_ids=("A:65", "A:66", "A:67"),
        parent_sequence="SHG",
        atom_mappings=(
            ModifiedResidueAtomMapping("CA1", "A:65", "CA"),
            ModifiedResidueAtomMapping("CA2", "A:66", "CA"),
            ModifiedResidueAtomMapping("CA3", "A:67", "CA"),
        ),
    ),
))
_NORMALIZATION_FACTS = CandidateNormalizationFactCollection(entries=(
    CandidateNormalizationFact(
        normalization_key=normalization_key(
            output_role="structure_candidates",
            output_slot=0,
            structure_content_digest=_RESOLVED_AXIS_SUBJECT.content_digest,
            normalizations_content_digest=(
                MODIFIED_RESIDUE_NORMALIZATIONS_PORT_TYPE.content_digest(
                    _CSH_NORMALIZATIONS
                )
            ),
        ),
        structure_content_digest=_RESOLVED_AXIS_SUBJECT.content_digest,
        normalizations=_CSH_NORMALIZATIONS,
    ),
))


class _RunResources:
    @staticmethod
    def engine_invocation(**kwargs):
        del kwargs
        return nullcontext()


def _coordinate_line(
    serial: int,
    atom_name: str,
    residue_name: str,
    chain_id: str,
    residue_number: int,
    *,
    record: str = "ATOM",
) -> str:
    element = "SE" if atom_name == "SE" else atom_name[0]
    return (
        f"{record:<6}{serial:5d} {atom_name:^4} "
        f"{residue_name:>3} {chain_id}{residue_number:4d}    "
        f"{float(serial):8.3f}{2.0:8.3f}{3.0:8.3f}"
        f"{1.0:6.2f}{20.0:6.2f}          {element:>2}  "
    )


def _residue_lines(
    serial: int,
    residue_name: str,
    chain_id: str,
    residue_number: int,
    *,
    record: str = "ATOM",
    include_se: bool = False,
) -> tuple[list[str], int]:
    atom_names = ["N", "CA", "C", "O"]
    if include_se:
        atom_names.append("SE")
    return (
        [
            _coordinate_line(
                serial + index,
                atom_name,
                residue_name,
                chain_id,
                residue_number,
                record=record,
            )
            for index, atom_name in enumerate(atom_names)
        ],
        serial + len(atom_names),
    )


def _modres_mse(chain_id: str, residue_number: int) -> str:
    fields = [" "] * 80
    fields[0:6] = "MODRES"
    fields[7:11] = "TEST"
    fields[12:15] = "MSE"
    fields[16] = chain_id
    fields[18:22] = f"{residue_number:4d}"
    fields[24:27] = "MET"
    fields[29:45] = "SELENOMETHIONINE"
    return "".join(fields).rstrip()


def _declared_mse_multichain_structure() -> ProteinStructure:
    ala, serial = _residue_lines(1, "ALA", "A", 1)
    mse, serial = _residue_lines(
        serial,
        "MSE",
        "A",
        2,
        record="HETATM",
        include_se=True,
    )
    gly_a, serial = _residue_lines(serial, "GLY", "A", 3)
    gly_b, _ = _residue_lines(serial, "GLY", "B", 1)
    return ProteinStructure(
        "\n".join(
            [
                "SEQRES   1 A    3  ALA MSE GLY",
                "SEQRES   1 B    1  GLY",
                _modres_mse("A", 2),
                *ala,
                *mse,
                *gly_a,
                "TER",
                *gly_b,
                "TER",
                "END",
                "",
            ]
        )
    )


def test_standard_parent_component_is_polymer_independent_of_pdb_record_type(
) -> None:
    ala, _ = _residue_lines(1, "ALA", "A", 1, record="HETATM")
    axis = resolve_residue_axis(
        ProteinStructure("\n".join([*ala, "TER", "END", ""]))
    )

    assert axis.sequence == "A"
    assert axis.layout.residue_ids == ("A:1",)
    assert axis.component_dispositions[0].component_role == "polymer"
    assert axis.component_dispositions[0].record_type == "HETATM"
    axis_type = build_frozen_catalog((MODULE_PACKAGE,)).require_port_type(
        "structure_transform.resolved_residue_axis",
        STRUCTURE_VERSION,
    )
    assert axis_type.decode(axis_type.encode(axis)) == axis
    with pytest.raises(PortValueError, match="contradicts its sequence letter"):
        axis_type.encode(
            replace(axis, sequence="X", residue_names=("UNK",))
        )


def test_sequence_and_backbone_are_projections_of_the_resolved_axis() -> None:
    axis = resolve_residue_axis(_declared_mse_multichain_structure())

    sequence = extract_sequence(axis)
    backbone = extract_backbone(axis)

    assert sequence == ProteinSequence("AMGG", ("A:1", "A:2", "A:3", "B:1"))
    ca_lines = [
        line
        for line in backbone.pdb_string.splitlines()
        if line.startswith("ATOM  ") and line[12:16].strip() == "CA"
    ]
    assert [line[17:20] for line in ca_lines] == ["ALA", "MET", "GLY", "GLY"]
    assert [f"{line[21]}:{line[22:26].strip()}" for line in ca_lines] == [
        "A:1",
        "A:2",
        "A:3",
        "B:1",
    ]
    assert not any(
        line.startswith("HETATM") for line in backbone.pdb_string.splitlines()
    )


def test_chain_selection_preserves_polymer_declarations_and_resolved_axis(
) -> None:
    structure = _declared_mse_multichain_structure()
    original_axis = resolve_residue_axis(structure)

    selected = select_chains(structure, ["A"])
    selected_axis = resolve_residue_axis(selected)

    selected_lines = selected.pdb_string.splitlines()
    assert "SEQRES   1 A    3  ALA MSE GLY" in selected_lines
    assert "SEQRES   1 B    1  GLY" not in selected_lines
    assert _modres_mse("A", 2) in selected_lines
    assert selected_axis.sequence == "AMG"
    assert selected_axis.layout.residue_ids == ("A:1", "A:2", "A:3")
    assert selected_axis.modified_residue_normalizations == (
        original_axis.modified_residue_normalizations
    )


def test_candidate_transforms_share_axis_projection_and_header_preservation(
) -> None:
    structure = _declared_mse_multichain_structure()
    subject = CandidateDataReference(
        candidate_id="subject",
        data_type_id="protein.structure",
        content_digest=builtin_frozen_catalog()
        .require_port_type("protein.structure", STRUCTURE_VERSION)
        .content_digest(structure),
    )
    residue_axes = CandidateResolvedResidueAxisAssociations(
        entries=(
            CandidateResolvedResidueAxisAssociation(
                subject=subject,
                residue_axis=resolve_residue_axis(structure),
            ),
        )
    )
    structure_candidates = CandidateCollection(
        "structures",
        "protein.structure",
        (Candidate("subject", structure),),
    )

    sequence_output = ExtractSequenceCandidatesImplementation(
        _RunResources()
    ).execute(
        OperationCall(
            inputs={
                "structure_candidates": admitted_port_fixture(
                    structure_candidates,
                    port_type_id="candidate.collection",
                    value_content_digests=("sha256:" + ("e" * 64),),
                    candidate_data=(subject,),
                ),
                "residue_axes": admitted_port_fixture(
                    residue_axes,
                    port_type_id="structure_transform.residue_axes",
                    value_content_digests=("sha256:" + ("f" * 64),),
                ),
            },
            node_parameters={},
            binding_parameters={},
            effective_randomness={},
        )
    )["sequence_candidates"]
    selected_output = SelectCandidateChainsImplementation(
        _RunResources()
    ).execute(
        OperationCall(
            inputs={
                "structure_candidates": admitted_port_fixture(
                    structure_candidates,
                    port_type_id="candidate.collection",
                    value_content_digests=("sha256:" + ("e" * 64),),
                )
            },
            node_parameters={"chain_ids": ["A"]},
            binding_parameters={},
            effective_randomness={},
        )
    )["structure_candidates"]

    assert sequence_output.items[0].data == ProteinSequence(
        "AMGG",
        ("A:1", "A:2", "A:3", "B:1"),
    )
    assert sequence_output.items[0].parent_ids == ("subject",)
    selected_axis = resolve_residue_axis(selected_output.items[0].data)
    assert selected_axis.sequence == "AMG"
    assert selected_axis.modified_residue_normalizations.entries

    mismatched_axes = CandidateResolvedResidueAxisAssociations(
        entries=(
            CandidateResolvedResidueAxisAssociation(
                subject=replace(subject, candidate_id="other-subject"),
                residue_axis=residue_axes.entries[0].residue_axis,
            ),
        )
    )
    with pytest.raises(ValueError, match="complete exact Candidate references"):
        ExtractSequenceCandidatesImplementation(_RunResources()).execute(
            OperationCall(
                inputs={
                    "structure_candidates": admitted_port_fixture(
                        structure_candidates,
                        port_type_id="candidate.collection",
                        value_content_digests=("sha256:" + ("e" * 64),),
                        candidate_data=(subject,),
                    ),
                    "residue_axes": admitted_port_fixture(
                        mismatched_axes,
                        port_type_id="structure_transform.residue_axes",
                        value_content_digests=("sha256:" + ("f" * 64),),
                    ),
                },
                node_parameters={},
                binding_parameters={},
                effective_randomness={},
            )
        )


def test_backbone_wire_is_content_only_and_rejects_source_bearing_shape() -> None:
    port_type = build_frozen_catalog((MODULE_PACKAGE,)).require_port_type(
        "structure_transform.backbone_structure",
        BACKBONE_VERSION,
    )

    encoded = port_type.encode(_BACKBONE)
    assert b'"source"' not in encoded
    legacy_wire = canonical_json_bytes({
        "schema_namespace": "protein-workbench-port-value/v2",
        "port_type_id": "structure_transform.backbone_structure",
        "port_type_version": BACKBONE_VERSION,
        "value": {
            "pdb_string": _BACKBONE.pdb_string,
            "source": "structure_transform.extract_backbone",
        },
    })
    with pytest.raises(PortValueError, match="could not decode"):
        port_type.decode(legacy_wire)


def test_resolved_axis_wire_is_closed_and_identity_associated() -> None:
    port_type = build_frozen_catalog((MODULE_PACKAGE,)).require_port_type(
        "structure_transform.resolved_residue_axis",
        STRUCTURE_VERSION,
    )

    encoded = port_type.encode(_RESOLVED_AXIS)
    assert port_type.decode(encoded) == _RESOLVED_AXIS
    source_bearing = json.loads(encoded)
    source_bearing["value"]["source"] = "guessed-provenance"
    with pytest.raises(PortValueError, match="could not decode"):
        port_type.decode(canonical_json_bytes(source_bearing))
    with pytest.raises(PortValueError, match="coordinate masks"):
        port_type.encode(
            replace(
                _RESOLVED_AXIS,
                complete_backbone_mask=(False,),
            )
        )
def test_normalization_codec_runtime_and_wire_domains_are_closed() -> None:
    port_type = build_frozen_catalog((MODULE_PACKAGE,)).require_port_type(
        "structure_transform.modified_residue_normalizations",
        NORMALIZATION_VERSION,
    )
    valid = ModifiedResidueNormalizationCollection(entries=(
        ModifiedResidueNormalization(
            component_id="MSE",
            observed_residue_id="A:2",
            parent_residue_ids=("A:2",),
            parent_sequence="M",
            atom_mappings=(
                ModifiedResidueAtomMapping("SE", "A:2", "SD"),
            ),
        ),
    ))

    assert port_type.decode(port_type.encode(valid)) == valid
    duplicate_target = ModifiedResidueNormalizationCollection(entries=(
        replace(
            valid.entries[0],
            atom_mappings=(
                ModifiedResidueAtomMapping("SE", "A:2", "SD"),
                ModifiedResidueAtomMapping("S1", "A:2", "SD"),
            ),
        ),
    ))
    non_string = ModifiedResidueNormalizationCollection(entries=(
        replace(
            valid.entries[0],
            parent_sequence=["M"],  # type: ignore[arg-type]
        ),
    ))
    with pytest.raises(PortValueError, match="atom mapping"):
        port_type.encode(duplicate_target)
    with pytest.raises(PortValueError, match="normalization entry"):
        port_type.encode(non_string)


def test_structure_transform_publishes_all_exact_transforms_and_bridge() -> None:
    registrations = {
        registration.package_id: registration
        for registration in module_registrations()
    }

    registration = registrations["structure_transform"]
    assert registration.package_module == "modules.structure_transform"
    assert {
        resource.resource for resource in registration.node_definitions
    } == {
        "definitions/select_chains.yaml",
        "definitions/select_candidate_chains.yaml",
        "definitions/extract_backbone.yaml",
        "definitions/extract_sequence.yaml",
        "definitions/extract_sequence_candidates.yaml",
        "definitions/normalize_csh_parent_span.yaml",
        "definitions/normalize_csh_parent_span_candidates.yaml",
        "definitions/materialize_candidate_normalizations.yaml",
        "definitions/project_single_residue_axis.yaml",
        "definitions/resolve_residue_axis.yaml",
        "definitions/resolve_candidate_residue_axes.yaml",
        "definitions/backbone_to_structure.yaml",
    }
    catalog = build_frozen_catalog(module_registrations())
    assert catalog.get_port_type(
        "structure_transform.backbone_structure",
        "3.0.0",
    ) is None
    assert catalog.get_contract(
        "method",
        "structure_transform.backbone_to_structure.method",
        "3.0.0",
    ) is None
    assert catalog.require_contract(
        "method",
        "structure_transform.backbone_to_structure.method",
        BACKBONE_METHOD_VERSION,
    ).descriptor["algorithm_identity"]["input_contract"] == (
        f"structure_transform.backbone_structure@{BACKBONE_VERSION}"
    )
    assert {
        (contract.contract_id, contract.contract_version)
        for contract in catalog.contracts
        if contract.contract_kind == "node_type"
        and contract.contract_id.startswith("structure_transform.")
    } == {
        ("structure_transform.select_chains", STRUCTURE_VERSION),
        (
            "structure_transform.select_candidate_chains",
            CANDIDATE_NODE_VERSION,
        ),
        ("structure_transform.extract_backbone", STRUCTURE_VERSION),
        ("structure_transform.extract_sequence", STRUCTURE_VERSION),
        (
            "structure_transform.extract_sequence_candidates",
            CANDIDATE_NODE_VERSION,
        ),
        (
            "structure_transform.normalize_csh_parent_span",
            NORMALIZE_CSH_VERSION,
        ),
        (
            "structure_transform.normalize_csh_parent_span_candidates",
            "2.0.0",
        ),
        (
            "structure_transform.materialize_candidate_normalizations",
            "2.0.0",
        ),
        (
            "structure_transform.project_single_residue_axis",
            "2.0.0",
        ),
        ("structure_transform.resolve_residue_axis", STRUCTURE_VERSION),
        (
            "structure_transform.resolve_candidate_residue_axes",
            CANDIDATE_AXIS_VERSION,
        ),
        ("structure_transform.backbone_to_structure", STRUCTURE_VERSION),
    }


def test_transform_ports_are_exact_and_backbone_is_nominal() -> None:
    catalog = build_frozen_catalog((MODULE_PACKAGE, SOURCE_PACKAGE))
    selection = catalog.require_contract(
        "node_type",
        "structure_transform.select_chains",
        STRUCTURE_VERSION,
    ).descriptor
    backbone = catalog.require_contract(
        "node_type",
        "structure_transform.extract_backbone",
        STRUCTURE_VERSION,
    ).descriptor
    sequence = catalog.require_contract(
        "node_type",
        "structure_transform.extract_sequence",
        STRUCTURE_VERSION,
    ).descriptor
    backbone_bridge = catalog.require_contract(
        "node_type",
        "structure_transform.backbone_to_structure",
        STRUCTURE_VERSION,
    ).descriptor
    residue_axis = catalog.require_contract(
        "node_type",
        "structure_transform.resolve_residue_axis",
        STRUCTURE_VERSION,
    ).descriptor
    candidate_residue_axes = catalog.require_contract(
        "node_type",
        "structure_transform.resolve_candidate_residue_axes",
        CANDIDATE_AXIS_VERSION,
    ).descriptor
    candidate_sequence = catalog.require_contract(
        "node_type",
        "structure_transform.extract_sequence_candidates",
        CANDIDATE_NODE_VERSION,
    ).descriptor

    assert selection["inputs"][0]["port_type"]["contract_id"] == (
        "protein.structure"
    )
    assert selection["outputs"][0]["port_type"]["contract_id"] == (
        "protein.structure"
    )
    assert backbone["inputs"][0]["port_type"]["contract_id"] == (
        "structure_transform.resolved_residue_axis"
    )
    assert backbone["outputs"][0]["port_type"]["contract_id"] == (
        "structure_transform.backbone_structure"
    )
    assert sequence["inputs"][0]["port_type"]["contract_id"] == (
        "structure_transform.resolved_residue_axis"
    )
    assert sequence["outputs"][0]["port_type"]["contract_id"] == (
        "protein.sequence"
    )
    assert backbone_bridge["inputs"][0]["port_type"]["contract_id"] == (
        "structure_transform.backbone_structure"
    )
    assert backbone_bridge["outputs"][0]["port_type"]["contract_id"] == (
        "protein.structure"
    )
    assert residue_axis["inputs"][0]["port_type"]["contract_id"] == (
        "protein.structure"
    )
    assert residue_axis["inputs"][0]["port_type"]["contract_version"] == (
        STRUCTURE_VERSION
    )
    assert residue_axis["outputs"][0]["port_type"]["contract_id"] == (
        "structure_transform.resolved_residue_axis"
    )
    assert residue_axis["outputs"][0]["port_type"]["contract_version"] == (
        STRUCTURE_VERSION
    )
    assert candidate_residue_axes["inputs"][0]["port_type"][
        "contract_id"
    ] == "candidate.collection"
    assert candidate_residue_axes["inputs"][0]["port_type"][
        "contract_version"
    ] == CANDIDATE_COLLECTION_VERSION
    assert candidate_residue_axes["inputs"][1]["port_type"][
        "contract_id"
    ] == (
        "structure_transform."
        "candidate_modified_residue_normalization_associations"
    )
    assert candidate_residue_axes["outputs"][0]["port_type"][
        "contract_id"
    ] == "structure_transform.candidate_resolved_residue_axis_associations"
    assert candidate_residue_axes["inputs"][1]["port_type"][
        "contract_version"
    ] == CANDIDATE_AXIS_VERSION
    assert candidate_residue_axes["outputs"][0]["port_type"][
        "contract_version"
    ] == CANDIDATE_AXIS_VERSION
    assert candidate_sequence["inputs"][0]["name"] == "structure_candidates"
    assert candidate_sequence["inputs"][0]["port_type"][
        "contract_id"
    ] == "candidate.collection"
    assert candidate_sequence["inputs"][1]["name"] == "residue_axes"
    assert candidate_sequence["inputs"][1]["port_type"][
        "contract_id"
    ] == "structure_transform.candidate_resolved_residue_axis_associations"
    assert candidate_sequence["inputs"][1]["port_type"][
        "contract_version"
    ] == CANDIDATE_AXIS_VERSION
    normalize_binding = catalog.require_contract(
        "binding",
        "structure_transform.normalize_csh_parent_span.direct",
        NORMALIZE_CSH_VERSION,
    ).descriptor
    axis_binding = catalog.require_contract(
        "binding",
        "structure_transform.resolve_residue_axis.direct",
        STRUCTURE_VERSION,
    ).descriptor
    unchanged_selection_binding = catalog.require_contract(
        "binding",
        "structure_transform.select_chains.direct",
        STRUCTURE_VERSION,
    ).descriptor
    backbone_extraction_binding = catalog.require_contract(
        "binding",
        "structure_transform.extract_backbone.direct",
        STRUCTURE_VERSION,
    ).descriptor
    sequence_extraction_binding = catalog.require_contract(
        "binding",
        "structure_transform.extract_sequence.direct",
        STRUCTURE_VERSION,
    ).descriptor
    candidate_selection_binding = catalog.require_contract(
        "binding",
        "structure_transform.select_candidate_chains.direct",
        CANDIDATE_NODE_VERSION,
    ).descriptor
    candidate_extraction_binding = catalog.require_contract(
        "binding",
        "structure_transform.extract_sequence_candidates.direct",
        CANDIDATE_NODE_VERSION,
    ).descriptor
    candidate_axis_binding = catalog.require_contract(
        "binding",
        "structure_transform.resolve_candidate_residue_axes.direct",
        CANDIDATE_AXIS_VERSION,
    ).descriptor
    assert normalize_binding["method"]["contract_version"] == "4.0.0"
    assert normalize_binding["node_type"]["contract_version"] == (
        NORMALIZE_CSH_VERSION
    )
    assert axis_binding["method"]["contract_version"] == "3.0.0"
    assert unchanged_selection_binding["method"]["contract_version"] == (
        "3.0.0"
    )
    assert backbone_extraction_binding["method"]["contract_version"] == (
        "3.0.0"
    )
    assert sequence_extraction_binding["method"]["contract_version"] == (
        "3.0.0"
    )
    assert candidate_selection_binding["method"]["contract_version"] == (
        "3.0.0"
    )
    assert candidate_extraction_binding["method"]["contract_version"] == (
        "3.0.0"
    )
    assert candidate_axis_binding["method"]["contract_version"] == "3.0.0"


def test_full_atom_structure_cannot_enter_a_backbone_port_implicitly() -> None:
    catalog = build_frozen_catalog((MODULE_PACKAGE, SOURCE_PACKAGE))
    workflow = WorkflowDocument(
        schema_version=VERSION,
        workflow_id="no-implicit-backbone-conversion",
        nodes=(
            _SOURCE,
            WorkflowNodeInstance(
                node_id="sink",
                node_type_id="contract_test.backbone_sink",
                node_type_version=BACKBONE_VERSION,
                binding_id="contract_test.backbone_sink.direct",
                binding_version=BACKBONE_VERSION,
                node_parameters={},
                binding_parameters={},
            ),
        ),
        edges=(
            WorkflowEdge("source", "structure", "sink", "backbone"),
        ),
        contract_lock=(),
    )

    with pytest.raises(WorkflowCompileError) as rejected:
        compile(
            CompilationRequest(
                lock_workflow(workflow, catalog),
                1,
            ),
            catalog,
        )

    assert rejected.value.code == "port_type_mismatch"


@pytest.mark.parametrize("operation", ["extract_backbone", "extract_sequence"])
def test_raw_structure_cannot_enter_resolved_axis_projection_nodes(
    operation: str,
) -> None:
    catalog = build_frozen_catalog((MODULE_PACKAGE, SOURCE_PACKAGE))
    workflow = WorkflowDocument(
        schema_version=VERSION,
        workflow_id=f"no-raw-structure-{operation}",
        nodes=(
            _SOURCE,
            WorkflowNodeInstance(
                node_id="projection",
                node_type_id=f"structure_transform.{operation}",
                node_type_version=STRUCTURE_VERSION,
                binding_id=f"structure_transform.{operation}.direct",
                binding_version=STRUCTURE_VERSION,
                node_parameters={},
                binding_parameters={},
            ),
        ),
        edges=(
            WorkflowEdge(
                "source",
                "structure",
                "projection",
                "residue_axis",
            ),
        ),
        contract_lock=(),
    )

    with pytest.raises(WorkflowCompileError) as rejected:
        compile(
            CompilationRequest(
                lock_workflow(workflow, catalog),
                1,
            ),
            catalog,
        )

    assert rejected.value.code == "port_type_mismatch"


def test_all_nodes_pass_the_shared_contract_test_kit(
    tmp_path: Path,
) -> None:
    selection_case = ModulePackageContractCase(
        case_id="structure-transform-select_chains",
        node_type_id="structure_transform.select_chains",
        node_type_version=STRUCTURE_VERSION,
        binding_id="structure_transform.select_chains.direct",
        binding_version=STRUCTURE_VERSION,
        node_parameters={"chain_ids": ["A"]},
        binding_parameters={},
        environment_values={},
        workflow_nodes=(_SOURCE,),
        workflow_edges=(_SOURCE_EDGE,),
    )
    resolve_axis_node = WorkflowNodeInstance(
        node_id="resolve-axis",
        node_type_id="structure_transform.resolve_residue_axis",
        node_type_version=STRUCTURE_VERSION,
        binding_id="structure_transform.resolve_residue_axis.direct",
        binding_version=STRUCTURE_VERSION,
        node_parameters={},
        binding_parameters={},
    )
    axis_projection_cases = tuple(
        ModulePackageContractCase(
            case_id=f"structure-transform-{operation}",
            node_type_id=f"structure_transform.{operation}",
            node_type_version=STRUCTURE_VERSION,
            binding_id=f"structure_transform.{operation}.direct",
            binding_version=STRUCTURE_VERSION,
            node_parameters={},
            binding_parameters={},
            environment_values={},
            workflow_nodes=(_SOURCE, resolve_axis_node),
            workflow_edges=(
                WorkflowEdge(
                    "source",
                    "structure",
                    "resolve-axis",
                    "structure",
                ),
                WorkflowEdge(
                    "resolve-axis",
                    "residue_axis",
                    "contract-test-node",
                    "residue_axis",
                ),
            ),
        )
        for operation in (
            "extract_backbone",
            "extract_sequence",
        )
    )
    candidate_selection_case = ModulePackageContractCase(
        case_id="structure-transform-select_candidate_chains",
        node_type_id="structure_transform.select_candidate_chains",
        node_type_version=CANDIDATE_NODE_VERSION,
        binding_id="structure_transform.select_candidate_chains.direct",
        binding_version=CANDIDATE_NODE_VERSION,
        node_parameters={"chain_ids": ["A"]},
        binding_parameters={},
        environment_values={},
        workflow_nodes=(_SOURCE,),
        workflow_edges=(WorkflowEdge(
            "source",
            "structure_candidates",
            "contract-test-node",
            "structure_candidates",
        ),),
    )
    resolve_candidate_axes_node = WorkflowNodeInstance(
        node_id="resolve-candidate-axes",
        node_type_id="structure_transform.resolve_candidate_residue_axes",
        node_type_version=CANDIDATE_AXIS_VERSION,
        binding_id=(
            "structure_transform.resolve_candidate_residue_axes.direct"
        ),
        binding_version=CANDIDATE_AXIS_VERSION,
        node_parameters={},
        binding_parameters={},
    )
    candidate_extraction_case = ModulePackageContractCase(
        case_id="structure-transform-extract_sequence_candidates",
        node_type_id="structure_transform.extract_sequence_candidates",
        node_type_version=CANDIDATE_NODE_VERSION,
        binding_id="structure_transform.extract_sequence_candidates.direct",
        binding_version=CANDIDATE_NODE_VERSION,
        node_parameters={},
        binding_parameters={},
        environment_values={},
        workflow_nodes=(_SOURCE, resolve_candidate_axes_node),
        workflow_edges=(
            WorkflowEdge(
                "source",
                "structure_candidates",
                "contract-test-node",
                "structure_candidates",
            ),
            WorkflowEdge(
                "source",
                "structure_candidates",
                "resolve-candidate-axes",
                "structure_candidates",
            ),
            WorkflowEdge(
                "resolve-candidate-axes",
                "residue_axes",
                "contract-test-node",
                "residue_axes",
            ),
        ),
    )
    csh_source = WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.structure_transform_source",
        node_type_version=SOURCE_VERSION,
        binding_id="contract_test.structure_transform_source.direct",
        binding_version=SOURCE_VERSION,
        node_parameters={"fixture": "csh"},
        binding_parameters={},
    )
    normalization_case = ModulePackageContractCase(
        case_id="structure-transform-normalize-csh-parent-span",
        node_type_id="structure_transform.normalize_csh_parent_span",
        node_type_version=NORMALIZE_CSH_VERSION,
        binding_id=(
            "structure_transform.normalize_csh_parent_span.direct"
        ),
        binding_version=NORMALIZE_CSH_VERSION,
        node_parameters={},
        binding_parameters={},
        environment_values={},
        workflow_nodes=(csh_source,),
        workflow_edges=(WorkflowEdge(
            "source",
            "structure",
            "contract-test-node",
            "structure",
        ),),
    )
    candidate_normalization_case = ModulePackageContractCase(
        case_id="structure-transform-normalize-csh-parent-span-candidates",
        node_type_id=(
            "structure_transform.normalize_csh_parent_span_candidates"
        ),
        node_type_version="2.0.0",
        binding_id=(
            "structure_transform.normalize_csh_parent_span_candidates.direct"
        ),
        binding_version="2.0.0",
        node_parameters={},
        binding_parameters={},
        environment_values={},
        workflow_nodes=(csh_source,),
        workflow_edges=(WorkflowEdge(
            "source",
            "structure_candidates",
            "contract-test-node",
            "structure_candidates",
        ),),
    )
    normalize_candidates_node = WorkflowNodeInstance(
        node_id="normalize-candidates",
        node_type_id=(
            "structure_transform.normalize_csh_parent_span_candidates"
        ),
        node_type_version="2.0.0",
        binding_id=(
            "structure_transform.normalize_csh_parent_span_candidates.direct"
        ),
        binding_version="2.0.0",
        node_parameters={},
        binding_parameters={},
    )
    materialize_normalizations_case = ModulePackageContractCase(
        case_id="structure-transform-materialize-candidate-normalizations",
        node_type_id=(
            "structure_transform.materialize_candidate_normalizations"
        ),
        node_type_version="2.0.0",
        binding_id=(
            "structure_transform.materialize_candidate_normalizations.direct"
        ),
        binding_version="2.0.0",
        node_parameters={},
        binding_parameters={},
        environment_values={},
        workflow_nodes=(csh_source, normalize_candidates_node),
        workflow_edges=(
            WorkflowEdge(
                "source",
                "structure_candidates",
                "normalize-candidates",
                "structure_candidates",
            ),
            WorkflowEdge(
                "normalize-candidates",
                "structure_candidates",
                "contract-test-node",
                "structure_candidates",
            ),
            WorkflowEdge(
                "normalize-candidates",
                "normalization_facts",
                "contract-test-node",
                "normalization_facts",
            ),
        ),
    )
    backbone_node = WorkflowNodeInstance(
        node_id="extract-backbone",
        node_type_id="structure_transform.extract_backbone",
        node_type_version=STRUCTURE_VERSION,
        binding_id="structure_transform.extract_backbone.direct",
        binding_version=STRUCTURE_VERSION,
        node_parameters={},
        binding_parameters={},
    )
    bridge_case = ModulePackageContractCase(
        case_id="structure-transform-backbone-to-structure",
        node_type_id="structure_transform.backbone_to_structure",
        node_type_version=STRUCTURE_VERSION,
        binding_id="structure_transform.backbone_to_structure.direct",
        binding_version=STRUCTURE_VERSION,
        node_parameters={},
        binding_parameters={},
        environment_values={},
        workflow_nodes=(_SOURCE, resolve_axis_node, backbone_node),
        workflow_edges=(
            WorkflowEdge(
                "source",
                "structure",
                "resolve-axis",
                "structure",
            ),
            WorkflowEdge(
                "resolve-axis",
                "residue_axis",
                "extract-backbone",
                "residue_axis",
            ),
            WorkflowEdge(
                "extract-backbone",
                "backbone",
                "contract-test-node",
                "backbone",
            ),
        ),
    )
    residue_axis_case = ModulePackageContractCase(
        case_id="structure-transform-resolve-residue-axis",
        node_type_id="structure_transform.resolve_residue_axis",
        node_type_version=STRUCTURE_VERSION,
        binding_id="structure_transform.resolve_residue_axis.direct",
        binding_version=STRUCTURE_VERSION,
        node_parameters={},
        binding_parameters={},
        environment_values={},
        workflow_nodes=(_SOURCE,),
        workflow_edges=(WorkflowEdge(
            "source",
            "structure",
            "contract-test-node",
            "structure",
        ),),
    )
    candidate_residue_axis_case = ModulePackageContractCase(
        case_id="structure-transform-resolve-candidate-residue-axes",
        node_type_id="structure_transform.resolve_candidate_residue_axes",
        node_type_version=CANDIDATE_AXIS_VERSION,
        binding_id=(
            "structure_transform.resolve_candidate_residue_axes.direct"
        ),
        binding_version=CANDIDATE_AXIS_VERSION,
        node_parameters={},
        binding_parameters={},
        environment_values={},
        workflow_nodes=(_SOURCE,),
        workflow_edges=(WorkflowEdge(
            "source",
            "structure_candidates",
            "contract-test-node",
            "structure_candidates",
        ),),
    )
    project_single_axis_case = ModulePackageContractCase(
        case_id="structure-transform-project-single-residue-axis",
        node_type_id="structure_transform.project_single_residue_axis",
        node_type_version="2.0.0",
        binding_id="structure_transform.project_single_residue_axis.direct",
        binding_version="2.0.0",
        node_parameters={},
        binding_parameters={},
        environment_values={},
        workflow_nodes=(_SOURCE, resolve_candidate_axes_node),
        workflow_edges=(
            WorkflowEdge(
                "source",
                "structure_candidates",
                "resolve-candidate-axes",
                "structure_candidates",
            ),
            WorkflowEdge(
                "source",
                "structure_candidates",
                "contract-test-node",
                "structure_candidates",
            ),
            WorkflowEdge(
                "resolve-candidate-axes",
                "residue_axes",
                "contract-test-node",
                "residue_axes",
            ),
        ),
    )
    report = verify_module_package_contract(
        MODULE_PACKAGE,
        execution_cases=(
            selection_case,
            *axis_projection_cases,
            candidate_selection_case,
            candidate_extraction_case,
            normalization_case,
            candidate_normalization_case,
            materialize_normalizations_case,
            bridge_case,
            residue_axis_case,
            candidate_residue_axis_case,
            project_single_axis_case,
        ),
        port_cases=(
            ModulePackagePortCase(
                "structure_transform.backbone_structure",
                BACKBONE_VERSION,
                _BACKBONE,
                (
                    ProteinStructure(
                        pdb_string=_BACKBONE.pdb_string.replace(
                            "TER\n",
                            (
                                "ATOM      5  CB  ALA A   1       5.000"
                                "   2.000   3.000  1.00 20.00"
                                "           C  \nTER\n"
                            ),
                        ),
                    ),
                    ProteinStructure("END\n"),
                    _MID_RESIDUE_BREAK,
                    _MISSING_CHAIN_BREAK,
                ),
            ),
            ModulePackagePortCase(
                "structure_transform.modified_residue_normalizations",
                NORMALIZATION_VERSION,
                ModifiedResidueNormalizationCollection(entries=[
                    ModifiedResidueNormalization(
                        component_id="CSH",
                        observed_residue_id="A:66",
                        parent_residue_ids=("A:65", "A:66", "A:67"),
                        parent_sequence="SHG",
                        atom_mappings=(
                            ModifiedResidueAtomMapping(
                                source_atom_name="CA1",
                                parent_residue_id="A:65",
                                parent_atom_name="CA",
                            ),
                            ModifiedResidueAtomMapping(
                                source_atom_name="CA2",
                                parent_residue_id="A:66",
                                parent_atom_name="CA",
                            ),
                            ModifiedResidueAtomMapping(
                                source_atom_name="CA3",
                                parent_residue_id="A:67",
                                parent_atom_name="CA",
                            ),
                        ),
                    )
                ]),
                (object(), ModifiedResidueNormalizationCollection()),
            ),
            ModulePackagePortCase(
                "structure_transform.candidate_normalization_facts",
                "1.0.0",
                _NORMALIZATION_FACTS,
                (object(),),
            ),
            ModulePackagePortCase(
                "structure_transform.resolved_residue_axis",
                STRUCTURE_VERSION,
                _RESOLVED_AXIS,
                (
                    object(),
                    replace(
                        _RESOLVED_AXIS,
                        ca_coordinate_mask=(False,),
                    ),
                    replace(
                        _RESOLVED_AXIS,
                        segments=(
                            StructureAxisSegment(0, "B", ("A:1",)),
                        ),
                    ),
                    replace(
                        _RESOLVED_AXIS,
                        component_dispositions=(),
                    ),
                ),
            ),
            ModulePackagePortCase(
                (
                    "structure_transform."
                    "candidate_modified_residue_normalization_associations"
                ),
                CANDIDATE_AXIS_VERSION,
                _CANDIDATE_NORMALIZATIONS,
                (
                    object(),
                    CandidateModifiedResidueNormalizationAssociations(),
                    CandidateModifiedResidueNormalizationAssociations(
                        entries=(
                            _CANDIDATE_NORMALIZATIONS.entries[0],
                            _CANDIDATE_NORMALIZATIONS.entries[0],
                        )
                    ),
                ),
            ),
            ModulePackagePortCase(
                (
                    "structure_transform."
                    "candidate_resolved_residue_axis_associations"
                ),
                CANDIDATE_AXIS_VERSION,
                _CANDIDATE_RESOLVED_AXES,
                (
                    object(),
                    CandidateResolvedResidueAxisAssociations(),
                    CandidateResolvedResidueAxisAssociations(
                        entries=(
                            replace(
                                _CANDIDATE_RESOLVED_AXES.entries[0],
                                subject=replace(
                                    _RESOLVED_AXIS_SUBJECT,
                                    content_digest=(
                                        "sha256:" + ("f" * 64)
                                    ),
                                ),
                            ),
                        )
                    ),
                ),
            ),
        ),
        supporting_registrations=(SOURCE_PACKAGE,),
        work_root=tmp_path,
    )

    assert [case.status for case in report.case_reports] == [
        "succeeded"
    ] * 12
    assert report.verified_port_types == (
        "structure_transform.backbone_structure@4.0.0",
        (
            "structure_transform."
            "candidate_modified_residue_normalization_associations@6.0.0"
        ),
        "structure_transform.candidate_normalization_facts@1.0.0",
        (
            "structure_transform."
            "candidate_resolved_residue_axis_associations@6.0.0"
        ),
        "structure_transform.modified_residue_normalizations@3.0.0",
        "structure_transform.resolved_residue_axis@4.0.0",
    )
