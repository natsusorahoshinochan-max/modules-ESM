"""Public v2 contracts for the cohesive ProteinMPNN Module Package."""

from __future__ import annotations

from tests.support.ledger import public_run_events, public_run_projection

from protein_workbench_public.bootstrap import module_registrations

from contextlib import nullcontext
from dataclasses import replace
import hashlib
from pathlib import Path
from typing import Any

import pytest

from core.project.manager import ProjectManager
from core.catalog.builder import (
    build_frozen_catalog,
)
from core.catalog.builtins import (
    builtin_frozen_catalog,
)
from core.catalog.declarations import (
    ContractIdentity,
)
from core.catalog.errors import CatalogBuildError
from core.operation import (
    BindingEnvironment,
    OperationCall,
)
from core.execution.environment import (
    EnvironmentConfiguration,
    admit_environment_configuration,
)
from core.execution.node_attempt import NodeAttemptFactory
from core.execution.runtime import (
    V2RunService,
)
from tests.support.result_store import result_store
from tests.support.contract_test_kit import (
    ModulePackageContractCase,
    ModulePackagePortCase,
    verify_module_package_contract,
)
from core.workflow.authoring import WorkflowAuthoringService
from core.workflow.document import (
    WorkflowDocument,
    WorkflowNodeInstance,
)
from core.catalog.canonical import canonical_json_bytes
from core.workflow.compiler import (
    CompilationRequest,
    compile,
    lock_workflow,
)
from core.workflow.errors import WorkflowCompileError
from core.workflow.document import WorkflowEdge
from datatypes.candidate import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
)
from datatypes.exact_reference import (
    ExactContractReference,
    ResidueAxisReference,
)
from datatypes.observation import (
    IntrinsicObservationContext,
    ScoreCollection,
    ScoreObservation,
)
from datatypes.residue import (
    ModifiedResidueNormalizationCollection,
    ResidueLayout,
)
from datatypes.sequence import ProteinSequence
from datatypes.structure import (
    ProteinStructure,
    ResolvedStructureResidueAxis,
    StructureAtomCoordinate,
    StructureAxisSegment,
    StructureResidueCoordinates,
)
from modules.proteinmpnn.domain import ProteinMPNNConstraints
from modules.proteinmpnn.adapter import (
    LocalProteinMPNNAdapter,
)
from modules.structure_transform.package import (
    MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
)
from modules.structure_transform.domain import (
    CandidateResolvedResidueAxisAssociation,
    CandidateResolvedResidueAxisAssociations,
)
from modules.structure_transform.residue_axis import resolve_residue_axis
from modules.structure_transform.port_types import RESOLVED_AXIS_PORT_TYPE
from tests.fixtures.proteinmpnn_sources.package import _fixture_structure
from tests.fixtures.scientific_operation import admitted_port_fixture


TARGET_LAYOUT = ResidueLayout(
    "A,B",
    5,
    ["A:1", "A:2", "B:1", "B:2", "B:3"],
)


def _resolved_axis(
    *,
    structure: ProteinStructure | None = None,
    layout: ResidueLayout = TARGET_LAYOUT,
    sequence: str = "AGSTW",
) -> ResolvedStructureResidueAxis:
    """Build the exact axis authority required by direct Adapter tests."""
    residue_name_by_letter = {
        "A": "ALA",
        "C": "CYS",
        "D": "ASP",
        "E": "GLU",
        "F": "PHE",
        "G": "GLY",
        "H": "HIS",
        "I": "ILE",
        "K": "LYS",
        "L": "LEU",
        "M": "MET",
        "N": "ASN",
        "P": "PRO",
        "Q": "GLN",
        "R": "ARG",
        "S": "SER",
        "T": "THR",
        "V": "VAL",
        "W": "TRP",
        "Y": "TYR",
    }
    residue_ids = tuple(layout.residue_ids or ())
    segments: list[StructureAxisSegment] = []
    for residue_id in residue_ids:
        chain_id = residue_id.split(":", 1)[0]
        if not segments or segments[-1].chain_id != chain_id:
            segments.append(
                StructureAxisSegment(len(segments), chain_id, (residue_id,))
            )
        else:
            segments[-1] = replace(
                segments[-1],
                residue_ids=(*segments[-1].residue_ids, residue_id),
            )
    coordinates = tuple(
        StructureResidueCoordinates(
            residue_id,
            tuple(
                StructureAtomCoordinate(
                    atom_name,
                    (float(index), float(atom_index), float(index + atom_index)),
                )
                for atom_index, atom_name in enumerate(("N", "CA", "C", "O"))
            ),
        )
        for index, residue_id in enumerate(residue_ids, start=1)
    )
    return ResolvedStructureResidueAxis(
        structure=structure or ProteinStructure("MODEL\nEND\n"),
        layout=layout,
        sequence=sequence,
        residue_names=tuple(
            residue_name_by_letter[letter] for letter in sequence
        ),
        segments=tuple(segments),
        component_dispositions=(),
        modified_residue_normalizations=(
            ModifiedResidueNormalizationCollection()
        ),
        residue_coordinates=coordinates,
        ca_coordinate_mask=tuple(True for _ in range(layout.length)),
        complete_backbone_mask=tuple(True for _ in range(layout.length)),
    )


def _structure_candidate_references(
    candidates: tuple[Candidate, ...],
) -> tuple[CandidateDataReference, ...]:
    structure_port = builtin_frozen_catalog().require_port_type(
        "protein.structure",
        "4.0.0",
    )
    return tuple(
        CandidateDataReference(
            candidate_id=candidate.candidate_id,
            data_type_id="protein.structure",
            content_digest=structure_port.content_digest(candidate.data),
        )
        for candidate in candidates
    )


def _admitted_structure_axis_inputs(
    candidates: tuple[Candidate, ...],
    associations: CandidateResolvedResidueAxisAssociations,
) -> dict[str, Any]:
    references = _structure_candidate_references(candidates)
    axis_contract = ExactContractReference(
        contract_kind="port_type",
        contract_id=RESOLVED_AXIS_PORT_TYPE.type_id,
        contract_version=RESOLVED_AXIS_PORT_TYPE.version,
        contract_digest=RESOLVED_AXIS_PORT_TYPE.contract_digest,
    )
    return {
        "structure_candidates": admitted_port_fixture(
            CandidateCollection(
                "admitted-structure-candidates",
                "protein.structure",
                candidates,
            ),
            port_type_id="candidate.collection",
            value_content_digests=("sha256:" + "1" * 64,),
            candidate_data=references,
        ),
        "structure_residue_axes": admitted_port_fixture(
            associations,
            port_type_id=(
                "structure_transform."
                "candidate_resolved_residue_axis_associations"
            ),
            value_content_digests=("sha256:" + "2" * 64,),
            candidate_data=tuple(
                entry.subject for entry in associations.entries
            ),
            scientific_axes=tuple(
                ResidueAxisReference(
                    axis_kind="resolved_structure",
                    axis_contract=axis_contract,
                    axis_content_digest=(
                        RESOLVED_AXIS_PORT_TYPE.content_digest(
                            entry.residue_axis
                        )
                    ),
                    source=entry.subject,
                    layout=entry.residue_axis.layout,
                )
                for entry in associations.entries
            ),
        ),
    }
def test_proteinmpnn_is_one_package_with_four_independent_nodes() -> None:
    registrations = {
        registration.package_id: registration
        for registration in module_registrations()
    }

    registration = registrations["proteinmpnn"]
    assert registration.package_module == "modules.proteinmpnn"
    assert registration.package_version == "7.0.0"
    assert {
        resource.resource for resource in registration.node_definitions
    } == {
        "definitions/constraints.yaml",
        "definitions/random_fixed_positions.yaml",
        "definitions/design.yaml",
        "definitions/score.yaml",
    }

    catalog = build_frozen_catalog(module_registrations())
    owned_nodes = {
        (contract.contract_id, contract.contract_version)
        for contract in catalog.contracts
        if contract.contract_kind == "node_type"
        and contract.contract_id.startswith("proteinmpnn.")
    }
    assert owned_nodes == {
        ("proteinmpnn.constraints", "4.0.0"),
        ("proteinmpnn.random_fixed_positions", "4.0.0"),
        ("proteinmpnn.design", "10.0.0"),
        ("proteinmpnn.score", "7.0.0"),
    }
    unchanged_v3_methods = {
        ("method", "proteinmpnn.constraints.repository_owned"),
        (
            "method",
            "proteinmpnn.random_fixed_positions.repository_owned",
        ),
    }
    for kind, contract_id in unchanged_v3_methods:
        assert catalog.get_contract(kind, contract_id, "3.0.0") is not None
    for contract_id in (
        "proteinmpnn.design.v_48_020_8907e667",
        "proteinmpnn.score.v_48_020_8907e667",
    ):
        assert catalog.get_contract("method", contract_id, "6.0.0") is not None
        assert catalog.get_contract("method", contract_id, "5.0.0") is None

    active_v4_contracts = {
        ("port_type", "proteinmpnn.constraints"),
        ("node_type", "proteinmpnn.constraints"),
        ("node_type", "proteinmpnn.random_fixed_positions"),
        ("binding", "proteinmpnn.constraints.local"),
        ("binding", "proteinmpnn.random_fixed_positions.local"),
    }
    for kind, contract_id in active_v4_contracts:
        assert catalog.get_contract(kind, contract_id, "4.0.0") is not None
        assert catalog.get_contract(kind, contract_id, "3.0.0") is None
    assert catalog.get_contract(
        "node_type", "proteinmpnn.design", "10.0.0"
    ) is not None
    assert catalog.get_contract(
        "binding", "proteinmpnn.design.local", "11.0.0"
    ) is not None
    assert catalog.get_contract(
        "binding", "proteinmpnn.design.local", "9.0.0"
    ) is None
    assert catalog.get_contract(
        "node_type", "proteinmpnn.score", "7.0.0"
    ) is not None
    assert catalog.get_contract(
        "binding", "proteinmpnn.score.local", "8.0.0"
    ) is not None
    assert catalog.get_contract(
        "binding", "proteinmpnn.score.local", "6.0.0"
    ) is None


def test_scoring_binding_fixes_exact_method_metric_and_observation_scope() -> None:
    from modules.proteinmpnn.package import (
        MODULE_PACKAGE as PROTEINMPNN_PACKAGE,
    )
    catalog = build_frozen_catalog(
        (PROTEINMPNN_PACKAGE, STRUCTURE_TRANSFORM_PACKAGE)
    )
    node = catalog.require_contract(
        "node_type",
        "proteinmpnn.score",
        "7.0.0",
    )
    binding = catalog.require_contract(
        "binding",
        "proteinmpnn.score.local",
        "8.0.0",
    )
    method = catalog.require_contract(
        "method",
        "proteinmpnn.score.v_48_020_8907e667",
        "6.0.0",
    )
    metric = catalog.require_contract(
        "metric",
        "proteinmpnn.native_sequence_nll",
        "3.0.0",
    )
    residue_metric = catalog.require_contract(
        "metric",
        "proteinmpnn.native_residue_nll",
        "3.0.0",
    )

    assert node.descriptor["node_parameters"] == {}
    assert binding.descriptor["binding_parameters"] == {}
    assert {
        "model",
        "model_name",
        "model_path",
        "checkpoint_path",
        "device",
        "runtime_directory",
        "temp_dir",
    }.isdisjoint(node.descriptor["node_parameters"])
    assert method.descriptor["model_identity"] == {
        "model": "v_48_020",
        "architecture": "ProteinMPNN",
        "source": "dauparas/ProteinMPNN",
    }
    assert method.descriptor["checkpoint_identity"] == {
        "relative_path": "vanilla_model_weights/v_48_020.pt",
        "sha256": (
            "c9cb4a671d79604111231f8dbfc7c590e06f1197453b7a6854ac6661a642f5bd"
        ),
    }
    assert method.descriptor["source_identity"]["source_revision"] == (
        "8907e6671bfbfc92303b5f79c4b5e6ce47cdef57"
    )
    assert binding.descriptor["implementation_identity"]["name"] == (
        "proteinmpnn.score.local-adapter"
    )
    assert binding.descriptor["implementation_identity"][
        "seed_control"
    ] == "fixed_scoring_seed_42"
    assert binding.descriptor["implementation_identity"][
        "structure_projection"
    ] == "resolved-axis-segment-provider-native-staging-v2"
    assert method.descriptor["featurization_identity"] == {
        "structure": (
            "resolved-axis deterministic N-CA-C-O provider PDB "
            "then ProteinMPNN parse_PDB"
        ),
        "residue_projection": (
            "resolved-axis-segment-to-provider-safe-chain;"
            "canonical-identity-to-segment-local-continuous-"
            "one-based-position"
        ),
        "missing_backbone": (
            "axis-selected-coordinate-or-provider-NaN-mask"
        ),
        "sequence": "canonical-20-amino-acid exact target layout",
        "tensorization": "ProteinMPNN tied_featurize all chains designed",
        "mask": "provider mask multiplied by chain_M and chain_M_pos",
        "reduction": "provider _scores masked mean",
        "decoding_order_seed": 42,
    }
    assert metric.descriptor["value_shape"] == "scalar"
    assert metric.descriptor["unit"] == "nats_per_designed_residue"
    assert metric.descriptor["direction"] == "lower_is_better"
    assert metric.descriptor["canonical_range"] == {
        "minimum": 0,
        "maximum": 3.4028234663852886e38,
    }
    assert metric.descriptor["validation_contract"] == {
        "finite": True,
        "numeric_format": "binary32",
        "exact_round_trip": True,
    }
    assert metric.descriptor["granularity"] == "candidate"
    assert metric.descriptor["aggregation_semantics"] == {
        "kind": "provider_masked_mean",
        "source_metric": "proteinmpnn.native_residue_nll@3.0.0",
        "included_values": "mask * chain_M * chain_M_pos",
    }
    assert residue_metric.descriptor["value_shape"] == "per_residue"
    assert residue_metric.descriptor["unit"] == "nats"
    assert residue_metric.descriptor["granularity"] == "residue"
    assert residue_metric.descriptor["aggregation_semantics"] == {
        "kind": "none"
    }
    produced = binding.descriptor["produced_observations"]
    assert len(produced) == 1
    assert produced[0] == {
        "output_port": "scores",
        "output_partition": "default",
        "metric": produced[0]["metric"],
        "context_profile": {"kind": "intrinsic"},
        "subject_grain": "candidate",
        "source_role": "subject",
        "subject_direction": "input",
        "subject_port": "sequence_candidates",
        "reference_direction": None,
        "reference_port": None,
        "pairing_direction": None,
        "pairing_port": None,
        "axis_direction": "input",
        "axis_port": "structure_residue_axes",
        "method_direction": None,
        "method_port": None,
        "guaranteed_multiplicity": "one",
    }
    assert produced[0]["metric"] == {
        "contract_kind": "metric",
        "contract_id": "proteinmpnn.native_sequence_nll",
        "contract_version": "3.0.0",
        "contract_digest": produced[0]["metric"]["contract_digest"],
    }
    assert produced[0]["metric"]["contract_digest"].startswith("sha256:")


@pytest.mark.parametrize(
    ("mismatch", "expected_message"),
    (
        ("metric", "dangling contract reference"),
        ("context", "does not satisfy Metric observation_context_schema"),
        ("scope", "references unknown subject input Port"),
    ),
)
def test_scoring_metric_context_and_scope_mismatches_fail_catalog_build(
    mismatch: str,
    expected_message: str,
) -> None:
    from modules.proteinmpnn.package import (
        MODULE_PACKAGE as PROTEINMPNN_PACKAGE,
    )
    scoring = next(
        binding
        for binding in PROTEINMPNN_PACKAGE.bindings
        if binding.binding_id == "proteinmpnn.score.local"
    )
    produced = scoring.produced_observations[0]
    if mismatch == "metric":
        invalid_produced = replace(
            produced,
            metric=ContractIdentity(
                "metric",
                "proteinmpnn.undeclared_metric",
                "2.1.0",
            ),
        )
    elif mismatch == "context":
        invalid_produced = replace(
            produced,
            context_profile={
                "kind": "intrinsic",
                "normalization": "dataset-relative",
            },
        )
    else:
        invalid_produced = replace(
            produced,
            subject_port="undeclared_subjects",
        )
    invalid_binding = replace(
        scoring,
        produced_observations=(invalid_produced,),
    )
    invalid_package = replace(
        PROTEINMPNN_PACKAGE,
        bindings=tuple(
            invalid_binding if binding is scoring else binding
            for binding in PROTEINMPNN_PACKAGE.bindings
        ),
    )

    with pytest.raises(CatalogBuildError, match=expected_message):
        build_frozen_catalog(
            (invalid_package, STRUCTURE_TRANSFORM_PACKAGE)
        )


def test_scoring_method_mismatch_fails_compilation_before_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.proteinmpnn.package import (
        MODULE_PACKAGE as PROTEINMPNN_PACKAGE,
    )
    from tests.fixtures.proteinmpnn_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    provider = _ControlledProteinMPNNProvider()
    _install_test_provider(monkeypatch, provider)
    nodes, edges = _score_workflow()
    score = nodes[-1]
    nodes = (
        *nodes[:-1],
        WorkflowNodeInstance(
            node_id=score.node_id,
            node_type_id=score.node_type_id,
            node_type_version=score.node_type_version,
            binding_id="proteinmpnn.design.local",
            binding_version="11.0.0",
            node_parameters={},
            binding_parameters={},
        ),
    )
    catalog = build_frozen_catalog(
        (
            PROTEINMPNN_PACKAGE,
            SOURCE_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        )
    )
    workflow = lock_workflow(
        WorkflowDocument(
            schema_version="2.1.0",
            workflow_id="proteinmpnn-method-mismatch",
            nodes=nodes,
            edges=edges,
            contract_lock=(),
        ),
        catalog,
    )

    with pytest.raises(
        WorkflowCompileError,
        match="Selected Binding does not belong",
    ):
        compile(
            CompilationRequest(
                workflow,
                1,
            ),
            catalog,
        )
    assert provider.parsed == []
    assert provider.requests == []


def _decode_output(
    catalog: Any,
    service: V2RunService,
    projection: dict[str, Any],
    output: dict[str, Any],
) -> Any:
    from tests.fixtures.public_v2 import decode_service_typed_output_value

    return decode_service_typed_output_value(
        service,
        catalog,
        projection,
        output,
    )


def _run(
    tmp_path: Path,
    *,
    nodes: tuple[WorkflowNodeInstance, ...],
    edges: tuple[WorkflowEdge, ...],
    registrations: tuple[Any, ...],
    environment: Any | None = None,
) -> tuple[Any, V2RunService, dict[str, Any], tuple[dict[str, Any], ...]]:
    catalog = build_frozen_catalog(registrations)
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create("ProteinMPNN v2")
    authoring = WorkflowAuthoringService(projects, catalog)
    committed = authoring.commit(
        project.id,
        workflow=WorkflowDocument(
            schema_version="2.1.0",
            workflow_id=project.id,
            nodes=nodes,
            edges=edges,
            contract_lock=(),
        ),
    )
    admitted_environment = (
        environment
        if isinstance(environment, EnvironmentConfiguration)
        else admit_environment_configuration(catalog, environment or {})
    )
    service = V2RunService(
        projects,
        catalog,
        authoring,
        NodeAttemptFactory(
            projects,
            admitted_environment,
            result_store(projects),
        ),
        result_store(projects),
    )
    try:
        receipt = service.start_background(
            project.id,
            workflow_commit_id=committed.workflow_commit_id,
            client_request_id="proteinmpnn-v2",
        )
        service.shutdown()
        return (
            catalog,
            service,
            public_run_projection(service, project.id, receipt["run_id"]),
            public_run_events(service, project.id, receipt["run_id"]),
        )
    finally:
        service.shutdown()


def test_constraint_authoring_validates_and_publishes_the_complete_contract(
    tmp_path: Path,
) -> None:
    from modules.prompt_authoring.package import (
        MODULE_PACKAGE as PROMPT_AUTHORING_PACKAGE,
    )
    from modules.proteinmpnn.package import (
        MODULE_PACKAGE as PROTEINMPNN_PACKAGE,
    )

    layout = WorkflowNodeInstance(
        node_id="layout",
        node_type_id="prompt_authoring.build_residue_layout",
        node_type_version="3.0.0",
        binding_id="prompt_authoring.build_residue_layout.direct",
        binding_version="3.0.0",
        node_parameters={
            "chains": [
                {"chain_id": "A", "length": 2},
                {"chain_id": "B", "length": 3},
            ]
        },
        binding_parameters={},
    )
    constraints = WorkflowNodeInstance(
        node_id="constraints",
        node_type_id="proteinmpnn.constraints",
        node_type_version="4.0.0",
        binding_id="proteinmpnn.constraints.local",
        binding_version="4.0.0",
        node_parameters={
            "designable_residue_ids": ["A:1", "B:1", "B:3"],
            "fixed_residue_ids": ["A:2", "B:2"],
            "designed_chains": ["A", "B"],
            "fixed_chains": [],
            "omit_amino_acids": ["C", "M"],
            "tied_residue_groups": [["A:1", "B:1"]],
            "bias_by_residue": [
                {"residue_id": "B:3", "amino_acid": "A", "bias": 1.5},
                {"residue_id": "B:3", "amino_acid": "G", "bias": -0.25},
            ],
        },
        binding_parameters={},
    )

    catalog, service, projection, events = _run(
        tmp_path,
        nodes=(layout, constraints),
        edges=(WorkflowEdge("layout", "layout", "constraints", "layout"),),
        registrations=(
            PROMPT_AUTHORING_PACKAGE,
            PROTEINMPNN_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        ),
    )

    assert projection["status"] == "succeeded", events
    output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "constraints"
        and item["output_port"] == "constraints"
    )
    assert _decode_output(
        catalog,
        service,
        projection,
        output,
    ) == ProteinMPNNConstraints(
        layout=TARGET_LAYOUT,
        designable_residue_ids=["A:1", "B:1", "B:3"],
        fixed_residue_ids=["A:2", "B:2"],
        designed_chains=["A", "B"],
        fixed_chains=None,
        omit_amino_acids=["C", "M"],
        tied_residue_groups=[["A:1", "B:1"]],
        bias_by_residue={"B:3": {"A": 1.5, "G": -0.25}},
    )
    assert output["result_identity"].startswith("sha256:")
    assert any(
        item["event"]["type"] == "engine_invocation_terminal"
        and item["event"]["status"] == "succeeded"
        for item in events
    )


def test_constraints_v4_canonical_value_and_contract_identity_golden() -> None:
    from modules.proteinmpnn.package import (
        MODULE_PACKAGE as PROTEINMPNN_PACKAGE,
    )

    constraints = ProteinMPNNConstraints(
        layout=ResidueLayout(
            "A,B",
            6,
            ["A:1", "A:2", "A:3", "A:4", "B:1", "B:2"],
        ),
        designable_residue_ids=["A:1", "A:2", "A:3"],
        fixed_residue_ids=["A:4"],
        designed_chains=["A"],
        fixed_chains=["B"],
        omit_amino_acids=["C", "M"],
        tied_residue_groups=[["A:1", "A:2"]],
        bias_by_residue={"A:3": {"Y": -0.25, "G": 1.5}},
    )
    port_type = build_frozen_catalog(
        (PROTEINMPNN_PACKAGE, STRUCTURE_TRANSFORM_PACKAGE)
    ).require_port_type("proteinmpnn.constraints", "4.0.0")

    assert port_type.encode(constraints) == (
        b'{"port_type_id":"proteinmpnn.constraints","port_type_version"'
        b':"4.0.0","schema_namespace":"protein-workbench-port-value/v2",'
        b'"value":{"bias_by_residue":[["A:3",{"G":1.5,"Y":-0.25}]],'
        b'"designable_residue_ids":["A:1","A:2","A:3"],'
        b'"designed_chains":["A"],"fixed_chains":["B"],'
        b'"fixed_residue_ids":["A:4"],"layout":{"chain_id":"A,B",'
        b'"length":6,"residue_ids":["A:1","A:2","A:3","A:4","B:1",'
        b'"B:2"]},"omit_amino_acids":["C","M"],'
        b'"tied_residue_groups":[["A:1","A:2"]]}}'
    )
    assert port_type.content_digest(constraints) == (
        "sha256:7ceca89abf591eb6452a9e587cf1c7cfaaa3348d53d553a54c5d2f55e7dc0134"
    )
    assert port_type.contract_digest == (
        "sha256:f6192bbd9db3539413c6a99e320af04ff5d2c9155b10221c70469cab6c746417"
    )


def test_constraints_cut_nested_aliases_and_keep_json_array_wire_projection() -> None:
    from modules.proteinmpnn.package import (
        MODULE_PACKAGE as PROTEINMPNN_PACKAGE,
    )

    fixed = ["A:2"]
    tied = [["A:1", "B:1"]]
    bias = {"B:3": {"A": 1.5}}
    constraints = ProteinMPNNConstraints(
        layout=TARGET_LAYOUT,
        fixed_residue_ids=fixed,
        tied_residue_groups=tied,
        bias_by_residue=bias,
    )
    fixed.append("B:2")
    tied[0].append("B:3")
    bias["B:3"]["G"] = -0.25

    assert constraints.fixed_residue_ids == ("A:2",)
    assert constraints.tied_residue_groups == (("A:1", "B:1"),)
    assert dict(constraints.bias_by_residue["B:3"]) == {"A": 1.5}

    port_type = build_frozen_catalog(
        (PROTEINMPNN_PACKAGE, STRUCTURE_TRANSFORM_PACKAGE)
    ).require_port_type("proteinmpnn.constraints", "4.0.0")
    encoded = port_type.encode(constraints)

    assert b'"$tuple"' not in encoded
    assert b'"fixed_residue_ids":["A:2"]' in encoded
    assert b'"tied_residue_groups":[["A:1","B:1"]]' in encoded
    assert port_type.decode(encoded) == constraints


@pytest.mark.parametrize(
    "parameter_override",
    (
        {"fixed_residue_ids": ["B:4"]},
        {"designed_chains": ["C"]},
        {
            "designable_residue_ids": ["A:1", "A:2"],
            "fixed_residue_ids": [],
            "designed_chains": ["A"],
            "fixed_chains": ["B"],
            "tied_residue_groups": [["A:1", "B:1"]],
        },
    ),
)
def test_constraint_authoring_fails_closed_on_layout_or_chain_contradictions(
    tmp_path: Path,
    parameter_override: dict[str, Any],
) -> None:
    from modules.prompt_authoring.package import (
        MODULE_PACKAGE as PROMPT_AUTHORING_PACKAGE,
    )
    from modules.proteinmpnn.package import (
        MODULE_PACKAGE as PROTEINMPNN_PACKAGE,
    )

    parameters = {
        "designable_residue_ids": [],
        "fixed_residue_ids": [],
        "designed_chains": [],
        "fixed_chains": [],
        "omit_amino_acids": [],
        "tied_residue_groups": [],
        "bias_by_residue": [],
        **parameter_override,
    }
    nodes = (
        WorkflowNodeInstance(
            node_id="layout",
            node_type_id="prompt_authoring.build_residue_layout",
            node_type_version="3.0.0",
            binding_id="prompt_authoring.build_residue_layout.direct",
            binding_version="3.0.0",
            node_parameters={
                "chains": [
                    {"chain_id": "A", "length": 2},
                    {"chain_id": "B", "length": 3},
                ]
            },
            binding_parameters={},
        ),
        WorkflowNodeInstance(
            node_id="constraints",
            node_type_id="proteinmpnn.constraints",
            node_type_version="4.0.0",
            binding_id="proteinmpnn.constraints.local",
            binding_version="4.0.0",
            node_parameters=parameters,
            binding_parameters={},
        ),
    )

    catalog, _, projection, events = _run(
        tmp_path,
        nodes=nodes,
        edges=(WorkflowEdge("layout", "layout", "constraints", "layout"),),
        registrations=(
            PROMPT_AUTHORING_PACKAGE,
            PROTEINMPNN_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        ),
    )

    assert projection["status"] == "failed"
    assert all(
        output["node_id"] != "constraints"
        for output in projection["outputs"]
    )
    assert any(
        event["event"]["type"] == "node_attempt_terminal"
        and event["event"]["status"] == "failed"
        for event in events
    )


def test_constraint_parameter_schema_rejects_public_x_bias() -> None:
    from modules.prompt_authoring.package import (
        MODULE_PACKAGE as PROMPT_AUTHORING_PACKAGE,
    )
    from modules.proteinmpnn.package import (
        MODULE_PACKAGE as PROTEINMPNN_PACKAGE,
    )

    catalog = build_frozen_catalog(
        (
            PROMPT_AUTHORING_PACKAGE,
            PROTEINMPNN_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        )
    )
    workflow = WorkflowDocument(
        schema_version="2.1.0",
        workflow_id="proteinmpnn-x-bias",
        nodes=(
            WorkflowNodeInstance(
                node_id="layout",
                node_type_id="prompt_authoring.build_residue_layout",
                node_type_version="3.0.0",
                binding_id="prompt_authoring.build_residue_layout.direct",
                binding_version="3.0.0",
                node_parameters={
                    "chains": [{"chain_id": "A", "length": 1}]
                },
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="constraints",
                node_type_id="proteinmpnn.constraints",
                node_type_version="4.0.0",
                binding_id="proteinmpnn.constraints.local",
                binding_version="4.0.0",
                node_parameters={
                    "designable_residue_ids": [],
                    "fixed_residue_ids": [],
                    "designed_chains": [],
                    "fixed_chains": [],
                    "omit_amino_acids": [],
                    "tied_residue_groups": [],
                    "bias_by_residue": [
                        {
                            "residue_id": "A:1",
                            "amino_acid": "X",
                            "bias": 1.0,
                        }
                    ],
                },
                binding_parameters={},
            ),
        ),
        edges=(WorkflowEdge("layout", "layout", "constraints", "layout"),),
        contract_lock=(),
    )

    locked = lock_workflow(workflow, catalog)
    with pytest.raises(WorkflowCompileError) as rejected:
        compile(
            CompilationRequest(
                locked,
                1,
            ),
            catalog,
        )

    assert rejected.value.field_path[-3:] == (
        "bias_by_residue",
        0,
        "amino_acid",
    )


def test_random_fixed_positions_replays_and_randomness_changes_identity(
    tmp_path: Path,
) -> None:
    from modules.prompt_authoring.package import (
        MODULE_PACKAGE as PROMPT_AUTHORING_PACKAGE,
    )
    from modules.proteinmpnn.package import (
        MODULE_PACKAGE as PROTEINMPNN_PACKAGE,
    )

    catalog = build_frozen_catalog(
        (PROTEINMPNN_PACKAGE, STRUCTURE_TRANSFORM_PACKAGE)
    )
    binding = catalog.require_contract(
        "binding",
        "proteinmpnn.random_fixed_positions.local",
        "4.0.0",
    )
    assert binding.descriptor["effective_randomness_parameters"] == (
        "effective_seed",
        "fraction",
    )
    assert binding.descriptor["implementation_identity"][
        "process_global_randomness"
    ] == "forbidden"

    def run(seed: int) -> tuple[str, ProteinMPNNConstraints]:
        nodes = (
            WorkflowNodeInstance(
                node_id="layout",
                node_type_id="prompt_authoring.build_residue_layout",
                node_type_version="3.0.0",
                binding_id="prompt_authoring.build_residue_layout.direct",
                binding_version="3.0.0",
                node_parameters={
                    "chains": [{"chain_id": "A", "length": 20}]
                },
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="random-fixed",
                node_type_id="proteinmpnn.random_fixed_positions",
                node_type_version="4.0.0",
                binding_id="proteinmpnn.random_fixed_positions.local",
                binding_version="4.0.0",
                node_parameters={
                    "effective_seed": seed,
                    "fraction": 0.3,
                },
                binding_parameters={},
            ),
        )
        run_catalog, service, projection, events = _run(
            tmp_path,
            nodes=nodes,
            edges=(
                WorkflowEdge(
                    "layout",
                    "layout",
                    "random-fixed",
                    "layout",
                ),
            ),
            registrations=(
                PROMPT_AUTHORING_PACKAGE,
                PROTEINMPNN_PACKAGE,
                STRUCTURE_TRANSFORM_PACKAGE,
            ),
        )
        assert projection["status"] == "succeeded", events
        output = next(
            item
            for item in projection["outputs"]
            if item["node_id"] == "random-fixed"
        )
        return output["result_identity"], _decode_output(
            run_catalog,
            service,
            projection,
            output,
        )

    first_identity, first = run(1603)
    replay_identity, replay = run(1603)
    changed_identity, changed = run(1604)

    assert first.fixed_residue_ids is not None
    assert len(first.fixed_residue_ids) == 6
    assert len(set(first.fixed_residue_ids)) == 6
    assert (first_identity, first) == (replay_identity, replay)
    assert changed_identity != first_identity
    assert changed.fixed_residue_ids != first.fixed_residue_ids


class _AdapterResources:
    def __init__(self) -> None:
        self.invocations: list[dict[str, Any]] = []

    @staticmethod
    def temporary_directory(*, prefix: str):
        del prefix
        return nullcontext(Path.cwd())

    @staticmethod
    def local_provider(provider_id: str):
        assert provider_id == "proteinmpnn"
        return nullcontext({})

    def engine_invocation(self, **kwargs: Any):
        self.invocations.append(kwargs)
        return nullcontext()

    @property
    def public_invocations(self) -> list[dict[str, Any]]:
        plain: list[dict[str, Any]] = []
        for invocation in self.invocations:
            item = dict(invocation)
            provenance = item.get("invocation_provenance")
            if provenance is not None:
                public: dict[str, Any] = {}
                randomness = provenance.effective_randomness
                if randomness is not None:
                    public_randomness: dict[str, Any] = {
                        "control": randomness.control,
                    }
                    if randomness.effective_seed is not None:
                        public_randomness["effective_seed"] = (
                            randomness.effective_seed
                        )
                    public["effective_randomness"] = public_randomness
                projection = provenance.provider_residue_projection
                if projection is not None:
                    public["provider_residue_projection"] = {
                        "position_semantics": projection.position_semantics,
                        "workbench_chain_order": list(
                            projection.workbench_chain_order
                        ),
                        "provider_structure_chain_order": list(
                            projection.provider_structure_chain_order
                        ),
                        "provider_chain_order": list(
                            projection.provider_chain_order
                        ),
                        "entries": [
                            {
                                "residue_id": entry.residue_id,
                                "segment_index": entry.segment_index,
                                "provider_chain_id": entry.provider_chain_id,
                                "provider_position": entry.provider_position,
                            }
                            for entry in projection.entries
                        ],
                    }
                item["invocation_provenance"] = public
            plain.append(item)
        return plain


class _ControlledProteinMPNNProvider:
    """Controlled provider injected through LocalProteinMPNNAdapter."""

    def __init__(self) -> None:
        self.parsed: list[str] = []
        self.requests: list[Any] = []

    def parse_structure(self, pdb_string: str) -> list[dict[str, Any]]:
        self.parsed.append(pdb_string)
        return [
            {
                "name": "target",
                "seq": "AGSTW",
                "seq_chain_A": "AG",
                "seq_chain_B": "STW",
            }
        ]

    def design(self, request: Any) -> list[ProteinSequence]:
        self.requests.append(request)
        alphabet = "ACDEFGHIKLMNPQRSTVWY"
        return [
            ProteinSequence(
                "AGST" + alphabet[(request.seed + index) % len(alphabet)]
            )
            for index in range(request.num_sequences)
        ]

    def score(self, request: Any, sequence: ProteinSequence) -> float:
        self.requests.append((request, sequence))
        return 2.75


def _controlled_adapter(
    provider: _ControlledProteinMPNNProvider,
    *,
    resources: _AdapterResources | None = None,
) -> LocalProteinMPNNAdapter:
    class ControlledAdapter(LocalProteinMPNNAdapter):
        def _provider(
            self,
            staging_directory: Path,
            resident_models: dict[object, object],
        ) -> Any:
            del staging_directory, resident_models
            return provider

    return ControlledAdapter(
        environment={},
        resources=resources or _AdapterResources(),
    )


def test_design_operation_joins_axes_by_full_reference_not_collection_order(
) -> None:
    from modules.proteinmpnn.implementation import (
        ProteinMPNNDesignImplementation,
    )
    structures = (
        _fixture_structure(0),
        _fixture_structure(1),
    )
    candidates = (
        Candidate("z-parent", structures[0]),
        Candidate("a-parent", structures[1]),
    )
    references = _structure_candidate_references(candidates)
    associations = CandidateResolvedResidueAxisAssociations(
        (
            CandidateResolvedResidueAxisAssociation(
                references[1],
                resolve_residue_axis(structures[1]),
            ),
            CandidateResolvedResidueAxisAssociation(
                references[0],
                resolve_residue_axis(structures[0]),
            ),
        )
    )
    def call(
        supplied: CandidateResolvedResidueAxisAssociations,
    ) -> OperationCall:
        return OperationCall(
            inputs=_admitted_structure_axis_inputs(candidates, supplied),
            node_parameters={
                "effective_seed": 1603,
                "num_sequences": 1,
                "temperature": 0.1,
                "backbone_noise": 0.0,
            },
            binding_parameters={},
            effective_randomness={
                "effective_seed": 1603,
                "num_sequences": 1,
                "temperature": 0.1,
                "backbone_noise": 0.0,
            },
        )

    class RecordingAdapter:
        def __init__(self) -> None:
            self.structures: list[ProteinStructure] = []

        def design(self, **kwargs: Any) -> tuple[ProteinSequence, ...]:
            residue_axis = kwargs["residue_axis"]
            self.structures.append(residue_axis.structure)
            return (
                ProteinSequence(
                    "A" * residue_axis.layout.length,
                    residue_axis.layout.residue_ids,
                ),
            )

    adapter = RecordingAdapter()
    operation = ProteinMPNNDesignImplementation(adapter=adapter)
    output = operation.execute(call(associations))["sequence_candidates"]

    assert adapter.structures == list(structures)
    assert [candidate.parent_ids for candidate in output.items] == [
        ("z-parent",),
        ("a-parent",),
    ]
    mismatched_reference = CandidateDataReference(
        candidate_id=references[0].candidate_id,
        data_type_id=references[0].data_type_id,
        content_digest="sha256:" + "0" * 64,
    )
    with pytest.raises(ValueError, match="cover exact structure references"):
        operation.execute(
            call(
                CandidateResolvedResidueAxisAssociations(
                    (
                        CandidateResolvedResidueAxisAssociation(
                            mismatched_reference,
                            resolve_residue_axis(structures[0]),
                        ),
                        associations.entries[0],
                    )
                )
            )
        )


def _install_test_provider(
    monkeypatch: pytest.MonkeyPatch,
    provider: Any,
) -> None:
    monkeypatch.setattr(
        "modules.proteinmpnn.adapter._LocalProteinMPNNProvider",
        lambda **_kwargs: provider,
    )


def _proteinmpnn_provider_root() -> Path:
    return (
        Path(__file__).resolve().parent.parent
        / "repositories"
        / "ProteinMPNN"
    )


def _proteinmpnn_environment(
    catalog: Any | None = None,
) -> Any:
    raw = {
            (binding_id, version): {
                "values": {
                    "device": "cpu",
                    "provider_root": _proteinmpnn_provider_root(),
                },
            }
            for binding_id, version in (
                ("proteinmpnn.design.local", "11.0.0"),
                ("proteinmpnn.score.local", "8.0.0"),
            )
        }
    if catalog is None:
        return raw
    return admit_environment_configuration(catalog, raw)


def _score_workflow() -> tuple[
    tuple[WorkflowNodeInstance, ...],
    tuple[WorkflowEdge, ...],
]:
    return (
        (
            WorkflowNodeInstance(
                node_id="source",
                node_type_id="contract_test.proteinmpnn_source",
                node_type_version="5.0.0",
                binding_id="contract_test.proteinmpnn_source.direct",
                binding_version="5.0.0",
                node_parameters={"parent_count": 1},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="sequence-source",
                node_type_id="contract_test.proteinmpnn_sequence_source",
                node_type_version="4.0.0",
                binding_id=(
                    "contract_test.proteinmpnn_sequence_source.direct"
                ),
                binding_version="4.0.0",
                node_parameters={},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="resolve-axes",
                node_type_id=(
                    "structure_transform.resolve_candidate_residue_axes"
                ),
                node_type_version="6.0.0",
                binding_id=(
                    "structure_transform."
                    "resolve_candidate_residue_axes.direct"
                ),
                binding_version="6.0.0",
                node_parameters={},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="score",
                node_type_id="proteinmpnn.score",
                node_type_version="7.0.0",
                binding_id="proteinmpnn.score.local",
                binding_version="8.0.0",
                node_parameters={},
                binding_parameters={},
            ),
        ),
        (
            WorkflowEdge(
                "source",
                "structure_candidates",
                "sequence-source",
                "structure_candidates",
            ),
            WorkflowEdge(
                "source",
                "structure_candidates",
                "resolve-axes",
                "structure_candidates",
            ),
            WorkflowEdge(
                "source",
                "structure_candidates",
                "score",
                "structure_candidates",
            ),
            WorkflowEdge(
                "resolve-axes",
                "residue_axes",
                "score",
                "structure_residue_axes",
            ),
            WorkflowEdge(
                "sequence-source",
                "sequence_candidates",
                "score",
                "sequence_candidates",
            ),
        ),
    )


def test_scoring_emits_one_exact_intrinsic_observation_with_real_attempts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.proteinmpnn.package import (
        MODULE_PACKAGE as PROTEINMPNN_PACKAGE,
    )
    from tests.fixtures.proteinmpnn_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    provider = _ControlledProteinMPNNProvider()
    _install_test_provider(monkeypatch, provider)
    nodes, edges = _score_workflow()
    catalog, service, projection, events = _run(
        tmp_path,
        nodes=nodes,
        edges=edges,
        registrations=(
            PROTEINMPNN_PACKAGE,
            SOURCE_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        ),
        environment=_proteinmpnn_environment(),
    )

    assert projection["status"] == "succeeded", events
    output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "score"
    )
    scores = _decode_output(catalog, service, projection, output)
    subject_output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "sequence-source"
    )
    subjects = _decode_output(catalog, service, projection, subject_output)
    assert type(scores) is ScoreCollection
    assert len(scores.entries) == 1
    observation = scores.entries[0]
    assert type(observation) is ScoreObservation
    assert observation.candidate_id == subjects.items[0].candidate_id
    assert observation.metric.contract_id == (
        "proteinmpnn.native_sequence_nll"
    )
    assert observation.method.contract_id == (
        "proteinmpnn.score.v_48_020_8907e667"
    )
    assert observation.subject.candidate_id == subjects.items[0].candidate_id
    assert observation.subject.data_type_id == "protein.sequence"
    assert observation.residue_axis is not None
    assert observation.residue_axis.axis_kind == "resolved_structure"
    assert observation.residue_axis.source.candidate_id != (
        observation.subject.candidate_id
    )
    assert observation.residue_axis.source.data_type_id == "protein.structure"
    assert observation.residue_axis.layout == TARGET_LAYOUT
    assert observation.context == IntrinsicObservationContext()
    assert observation.value == 2.75
    assert len(provider.parsed) == 1
    assert len(provider.requests) == 1
    request, sequence = provider.requests[0]
    assert request.model_name == "v_48_020"
    assert request.seed == 42
    assert request.backbone_noise == 0
    assert sequence.sequence == "AGSTW"
    assert sequence.residue_ids == (
        "A:1",
        "A:2",
        "B:1",
        "B:2",
        "B:3",
    )
    public_events = [item["event"] for item in events]
    invocation = next(
        event
        for event in public_events
        if event["type"] == "engine_invocation_started"
        and event["engine_identity"] == observation.method.contract_digest
    )
    assert invocation["engine_role"] == "score_subject"
    assert any(
        event["type"] == "operation_attempt_started"
        and event["operation_attempt_id"]
        == invocation["operation_attempt_id"]
        for event in public_events
    )
    assert any(
        event["type"] == "engine_invocation_terminal"
        and event["invocation_id"] == invocation["invocation_id"]
        and event["status"] == "succeeded"
        for event in public_events
    )
    assert any(
        event["type"] == "operation_attempt_terminal"
        and event["operation_attempt_id"]
        == invocation["operation_attempt_id"]
        and event["status"] == "succeeded"
        for event in public_events
    )


def test_scoring_rejects_ambiguous_subjects_before_provider_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.proteinmpnn.package import (
        MODULE_PACKAGE as PROTEINMPNN_PACKAGE,
    )
    from tests.fixtures.proteinmpnn_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    provider = _ControlledProteinMPNNProvider()
    _install_test_provider(monkeypatch, provider)
    nodes, edges = _score_workflow()
    source = nodes[0]
    nodes = (
        WorkflowNodeInstance(
            node_id=source.node_id,
            node_type_id=source.node_type_id,
            node_type_version=source.node_type_version,
            binding_id=source.binding_id,
            binding_version=source.binding_version,
            node_parameters={"parent_count": 2},
            binding_parameters=source.binding_parameters,
        ),
        *nodes[1:],
    )
    catalog, _, projection, events = _run(
        tmp_path,
        nodes=nodes,
        edges=edges,
        registrations=(
            PROTEINMPNN_PACKAGE,
            SOURCE_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        ),
        environment=_proteinmpnn_environment(),
    )

    assert projection["status"] == "failed"
    assert provider.parsed == []
    assert provider.requests == []
    score_method_digest = catalog.require_contract(
        "method",
        "proteinmpnn.score.v_48_020_8907e667",
        "6.0.0",
    ).contract_digest
    assert all(
        event["event"]["type"] != "engine_invocation_started"
        or event["event"]["engine_identity"] != score_method_digest
        for event in events
    )


def test_scoring_rejects_sequence_residue_layout_drift_before_model_call() -> None:
    from modules.proteinmpnn.implementation import ProteinMPNNScoreImplementation

    class TrustingAdapter:
        def __init__(self) -> None:
            self.calls = 0

        def score(self, **kwargs: Any) -> float:
            del kwargs
            self.calls += 1
            return 2.75

    structure = _fixture_structure(0)
    structure_candidate = Candidate("score-parent", structure)
    structure_reference = _structure_candidate_references(
        (structure_candidate,)
    )[0]
    residue_axis = resolve_residue_axis(structure)
    structure_inputs = _admitted_structure_axis_inputs(
        (structure_candidate,),
        CandidateResolvedResidueAxisAssociations((
            CandidateResolvedResidueAxisAssociation(
                structure_reference,
                residue_axis,
            ),
        )),
    )
    sequence_candidate = Candidate(
        "score-sequence",
        ProteinSequence(
            "AGSTW",
            ["A:1", "A:2", "A:3", "B:1", "B:2"],
        ),
        (structure_candidate.candidate_id,),
    )
    sequence_reference = CandidateDataReference(
        "score-sequence",
        "protein.sequence",
        "sha256:" + "9" * 64,
    )
    adapter = TrustingAdapter()
    operation = ProteinMPNNScoreImplementation(
        adapter=adapter,
        method=ExactContractReference(
            "method",
            "proteinmpnn.score.fixture",
            "1.0.0",
            "sha256:" + "a" * 64,
        ),
        metric=ExactContractReference(
            "metric",
            "proteinmpnn.native-sequence-nll.fixture",
            "1.0.0",
            "sha256:" + "b" * 64,
        ),
    )

    with pytest.raises(
        ValueError,
        match="exact resolved residue axis",
    ):
        operation.execute(
            OperationCall(
                inputs={
                    **structure_inputs,
                    "sequence_candidates": admitted_port_fixture(
                        CandidateCollection(
                            "score-sequences",
                            "protein.sequence",
                            (sequence_candidate,),
                        ),
                        port_type_id="candidate.collection",
                        value_content_digests=("sha256:" + "e" * 64,),
                        candidate_data=(sequence_reference,),
                    ),
                },
                node_parameters={},
                binding_parameters={},
                effective_randomness={},
            )
        )
    assert adapter.calls == 0


def test_scoring_uses_identity_complete_sequence_layout_for_provider_mapping() -> None:
    provider = _ControlledProteinMPNNProvider()
    resources = _AdapterResources()
    layout = ResidueLayout(
        "A,B",
        5,
        ["A:6", "A:7", "B:20", "B:21", "B:22"],
    )
    score = _controlled_adapter(provider, resources=resources).score(
        residue_axis=_resolved_axis(layout=layout),
        sequence=ProteinSequence(
            "AGSTW",
            ["A:6", "A:7", "B:20", "B:21", "B:22"],
        ),
    )
    request, sequence = provider.requests[0]

    assert score == 2.75
    assert sequence.residue_ids == request.target_layout.residue_ids
    assert request.target_layout.residue_ids == (
        "A:6",
        "A:7",
        "B:20",
        "B:21",
        "B:22",
    )
    assert request.residue_identity_mapping == (
        ("A:6", 0, "A", 1),
        ("A:7", 0, "A", 2),
        ("B:20", 1, "B", 1),
        ("B:21", 1, "B", 2),
        ("B:22", 1, "B", 3),
    )
    assert resources.public_invocations == [
        {
            "engine_role": "score_subject",
            "invocation_provenance": {
                "effective_randomness": {
                    "control": "exact_seed",
                    "effective_seed": 42,
                },
                "provider_residue_projection": {
                    "position_semantics": "one_based_chain_local",
                    "workbench_chain_order": ["A", "B"],
                    "provider_structure_chain_order": ["A", "B"],
                    "provider_chain_order": ["A", "B"],
                    "entries": [
                        {
                            "residue_id": "A:6",
                            "segment_index": 0,
                            "provider_chain_id": "A",
                            "provider_position": 1,
                        },
                        {
                            "residue_id": "A:7",
                            "segment_index": 0,
                            "provider_chain_id": "A",
                            "provider_position": 2,
                        },
                        {
                            "residue_id": "B:20",
                            "segment_index": 1,
                            "provider_chain_id": "B",
                            "provider_position": 1,
                        },
                        {
                            "residue_id": "B:21",
                            "segment_index": 1,
                            "provider_chain_id": "B",
                            "provider_position": 2,
                        },
                        {
                            "residue_id": "B:22",
                            "segment_index": 1,
                            "provider_chain_id": "B",
                            "provider_position": 3,
                        },
                    ],
                }
            },
        }
    ]


def test_design_projects_canonical_axis_into_provider_safe_structure(
    tmp_path: Path,
) -> None:
    from modules.proteinmpnn.provider_request import (
        _sequence_in_provider_chain_order,
    )
    from modules.proteinmpnn.provider_runtime import _parse_structure

    class ParsingProvider(_ControlledProteinMPNNProvider):
        def parse_structure(self, pdb_string: str) -> list[dict[str, Any]]:
            self.parsed.append(pdb_string)
            return _parse_structure(
                pdb_string,
                temp_dir=tmp_path,
                provider_root=(Path("repositories/ProteinMPNN").resolve()),
            )

        def design(self, request: Any) -> list[ProteinSequence]:
            self.requests.append(request)
            return [ProteinSequence("YYYYAC")]

    layout = ResidueLayout(
        "B,A",
        6,
        ["B:-2", "B:+1A", "A:6", "A:8", "A:8A", "A:10"],
    )
    unsplit_axis = _resolved_axis(layout=layout, sequence="ACDEFG")
    axis = replace(
        unsplit_axis,
        segments=(
            StructureAxisSegment(0, "B", ("B:-2", "B:+1A")),
            StructureAxisSegment(1, "A", ("A:6", "A:8")),
            StructureAxisSegment(2, "A", ("A:8A", "A:10")),
        ),
    )
    constraints = ProteinMPNNConstraints(
        layout=layout,
        designable_residue_ids=["A:6", "A:8A", "A:10"],
        fixed_residue_ids=["A:8"],
        designed_chains=["A"],
        fixed_chains=["B"],
        tied_residue_groups=[["A:6", "A:8A"]],
        bias_by_residue={"A:10": {"Y": 1.25}},
    )
    resources = _AdapterResources()
    provider = ParsingProvider()

    result = _controlled_adapter(provider, resources=resources).design(
        residue_axis=axis,
        num_sequences=1,
        temperature=0.1,
        backbone_noise=0,
        seed=1603,
        constraints=constraints,
        reference_sequence=ProteinSequence("ACDEFG", layout.residue_ids),
        engine_role="design_parent_0",
    )

    request = provider.requests[0]
    target_name = request.pdb_dict_list[0]["name"]
    assert request.pdb_dict_list[0]["seq_chain_A"] == "AC"
    assert request.pdb_dict_list[0]["seq_chain_B"] == "DE"
    assert request.pdb_dict_list[0]["seq_chain_C"] == "FG"
    assert request.target_layout == layout
    assert request.residue_identity_mapping == (
        ("B:-2", 0, "A", 1),
        ("B:+1A", 0, "A", 2),
        ("A:6", 1, "B", 1),
        ("A:8", 1, "B", 2),
        ("A:8A", 2, "C", 1),
        ("A:10", 2, "C", 2),
    )
    assert request.workbench_chain_order == ("B", "A")
    assert request.provider_structure_chain_order == ("A", "B", "C")
    assert request.provider_chain_order == ("B", "C", "A")
    assert request.chain_dict == {target_name: (["B", "C"], ["A"])}
    assert request.fixed_position_dict == {
        target_name: {"A": [], "B": [2], "C": []}
    }
    assert request.tied_positions_dict == {
        target_name: [{"B": [1], "C": [1]}]
    }
    assert request.reference_sequences == {"A": "AC", "B": "DE", "C": "FG"}
    assert request.bias_by_res_dict is not None
    assert request.bias_by_res_dict[target_name]["C"][1][19] == 1.25
    assert _sequence_in_provider_chain_order("ACDEFG", request) == "DEFGAC"
    assert result == (ProteinSequence("ACYYYY", layout.residue_ids),)
    assert resources.public_invocations == [
        {
            "engine_role": "design_parent_0",
            "invocation_provenance": {
                "effective_randomness": {
                    "control": "exact_seed",
                    "effective_seed": 1603,
                },
                "provider_residue_projection": {
                    "position_semantics": "one_based_chain_local",
                    "workbench_chain_order": ["B", "A"],
                    "provider_structure_chain_order": ["A", "B", "C"],
                    "provider_chain_order": ["B", "C", "A"],
                    "entries": [
                        {
                            "residue_id": "B:-2",
                            "segment_index": 0,
                            "provider_chain_id": "A",
                            "provider_position": 1,
                        },
                        {
                            "residue_id": "B:+1A",
                            "segment_index": 0,
                            "provider_chain_id": "A",
                            "provider_position": 2,
                        },
                        {
                            "residue_id": "A:6",
                            "segment_index": 1,
                            "provider_chain_id": "B",
                            "provider_position": 1,
                        },
                        {
                            "residue_id": "A:8",
                            "segment_index": 1,
                            "provider_chain_id": "B",
                            "provider_position": 2,
                        },
                        {
                            "residue_id": "A:8A",
                            "segment_index": 2,
                            "provider_chain_id": "C",
                            "provider_position": 1,
                        },
                        {
                            "residue_id": "A:10",
                            "segment_index": 2,
                            "provider_chain_id": "C",
                            "provider_position": 2,
                        },
                    ],
                },
            },
        }
    ]


def test_scoring_stages_numbering_gaps_and_preserves_backbone_mask(
    tmp_path: Path,
) -> None:
    import torch

    from modules.proteinmpnn.provider_runtime import (
        _featurize,
        _parse_structure,
    )

    class FeaturizingProvider(_ControlledProteinMPNNProvider):
        def __init__(self) -> None:
            super().__init__()
            self.batch: dict[str, Any] | None = None

        def parse_structure(self, pdb_string: str) -> list[dict[str, Any]]:
            self.parsed.append(pdb_string)
            return _parse_structure(
                pdb_string,
                temp_dir=tmp_path,
                provider_root=(Path("repositories/ProteinMPNN").resolve()),
            )

        def score(self, request: Any, sequence: ProteinSequence) -> float:
            self.requests.append((request, sequence))
            self.batch = _featurize(
                request,
                torch.device("cpu"),
                Path("repositories/ProteinMPNN").resolve(),
            )
            return 1.5

    layout = ResidueLayout("A", 2, ["A:6", "A:8"])
    complete_axis = _resolved_axis(layout=layout, sequence="AG")
    incomplete_second = replace(
        complete_axis.residue_coordinates[1],
        atom_coordinates=tuple(
            atom
            for atom in complete_axis.residue_coordinates[1].atom_coordinates
            if atom.atom_name != "O"
        ),
    )
    axis = replace(
        complete_axis,
        residue_coordinates=(
            complete_axis.residue_coordinates[0],
            incomplete_second,
        ),
        complete_backbone_mask=(True, False),
    )
    resources = _AdapterResources()
    provider = FeaturizingProvider()

    score = _controlled_adapter(provider, resources=resources).score(
        residue_axis=axis,
        sequence=ProteinSequence("AG", layout.residue_ids),
    )

    request, sequence = provider.requests[0]
    assert score == 1.5
    assert sequence == ProteinSequence("AG", layout.residue_ids)
    assert request.pdb_dict_list[0]["seq_chain_A"] == "AG"
    assert request.residue_identity_mapping == (
        ("A:6", 0, "A", 1),
        ("A:8", 0, "A", 2),
    )
    assert provider.batch is not None
    assert provider.batch["mask"].tolist() == [[1.0, 0.0]]
    assert provider.batch["chain_M"].tolist() == [[1.0, 1.0]]
    assert provider.batch["chain_M_pos"].tolist() == [[1.0, 1.0]]
    assert resources.public_invocations[0]["invocation_provenance"][
        "provider_residue_projection"
    ] == {
        "position_semantics": "one_based_chain_local",
        "workbench_chain_order": ["A"],
        "provider_structure_chain_order": ["A"],
        "provider_chain_order": ["A"],
        "entries": [
            {
                "residue_id": "A:6",
                "segment_index": 0,
                "provider_chain_id": "A",
                "provider_position": 1,
            },
            {
                "residue_id": "A:8",
                "segment_index": 0,
                "provider_chain_id": "A",
                "provider_position": 2,
            },
        ],
    }


def test_design_and_score_preserve_same_chain_segment_topology(
    tmp_path: Path,
) -> None:
    import torch

    from modules.proteinmpnn.provider_request import (
        _sequence_in_provider_chain_order,
    )
    from modules.proteinmpnn.provider_runtime import _featurize, _parse_structure

    class SegmentProvider(_ControlledProteinMPNNProvider):
        def __init__(self) -> None:
            super().__init__()
            self.score_sequence: str | None = None
            self.score_batch: dict[str, Any] | None = None

        def parse_structure(self, pdb_string: str) -> list[dict[str, Any]]:
            self.parsed.append(pdb_string)
            return _parse_structure(
                pdb_string,
                temp_dir=tmp_path,
                provider_root=Path("repositories/ProteinMPNN").resolve(),
            )

        def design(self, request: Any) -> list[ProteinSequence]:
            self.requests.append(request)
            return [ProteinSequence("VWYFLC")]

        def score(self, request: Any, sequence: ProteinSequence) -> float:
            self.requests.append((request, sequence))
            self.score_sequence = _sequence_in_provider_chain_order(
                sequence.sequence,
                request,
            )
            self.score_batch = _featurize(
                request,
                torch.device("cpu"),
                Path("repositories/ProteinMPNN").resolve(),
            )
            return 1.25

    layout = ResidueLayout(
        "A",
        6,
        ["A:1", "A:2", "A:3", "A:4", "A:5", "A:6"],
    )
    unsplit_axis = _resolved_axis(layout=layout, sequence="AGSTWY")
    axis = replace(
        unsplit_axis,
        segments=(
            StructureAxisSegment(0, "A", ("A:1", "A:2", "A:3")),
            StructureAxisSegment(1, "A", ("A:4", "A:5", "A:6")),
        ),
    )
    constraints = ProteinMPNNConstraints(
        layout=layout,
        designed_chains=["A"],
        designable_residue_ids=["A:1", "A:3", "A:4", "A:6"],
        fixed_residue_ids=["A:2", "A:5"],
        tied_residue_groups=[["A:1", "A:4"]],
        bias_by_residue={"A:6": {"Y": 1.5}},
    )
    provider = SegmentProvider()
    resources = _AdapterResources()
    adapter = _controlled_adapter(provider, resources=resources)

    designed = adapter.design(
        residue_axis=axis,
        num_sequences=1,
        temperature=0.1,
        backbone_noise=0,
        seed=1603,
        constraints=constraints,
        reference_sequence=ProteinSequence("AGSTWY", layout.residue_ids),
        engine_role="design_parent_0",
    )
    score = adapter.score(
        residue_axis=axis,
        sequence=ProteinSequence("AGSTWY", layout.residue_ids),
    )

    design_request = provider.requests[0]
    score_request, score_input = provider.requests[1]
    target_name = design_request.pdb_dict_list[0]["name"]
    assert design_request.pdb_dict_list[0]["seq_chain_A"] == "AGS"
    assert design_request.pdb_dict_list[0]["seq_chain_B"] == "TWY"
    assert design_request.residue_identity_mapping == (
        ("A:1", 0, "A", 1),
        ("A:2", 0, "A", 2),
        ("A:3", 0, "A", 3),
        ("A:4", 1, "B", 1),
        ("A:5", 1, "B", 2),
        ("A:6", 1, "B", 3),
    )
    assert design_request.workbench_chain_order == ("A",)
    assert design_request.provider_structure_chain_order == ("A", "B")
    assert design_request.provider_chain_order == ("A", "B")
    assert design_request.chain_dict == {target_name: (["A", "B"], [])}
    assert design_request.fixed_position_dict == {
        target_name: {"A": [2], "B": [2]}
    }
    assert design_request.tied_positions_dict == {
        target_name: [{"A": [1], "B": [1]}]
    }
    assert design_request.reference_sequences == {"A": "AGS", "B": "TWY"}
    assert design_request.bias_by_res_dict is not None
    assert design_request.bias_by_res_dict[target_name]["B"][2][19] == 1.5
    assert designed == (ProteinSequence("VWYFLC", layout.residue_ids),)
    assert score == 1.25
    assert score_input == ProteinSequence("AGSTWY", layout.residue_ids)
    assert provider.score_sequence == "AGSTWY"
    assert score_request.provider_structure_chain_order == ("A", "B")
    assert provider.score_batch is not None
    assert provider.score_batch["residue_idx"].tolist() == [
        [0, 1, 2, 103, 104, 105]
    ]
    expected_projection = {
        "position_semantics": "one_based_chain_local",
        "workbench_chain_order": ["A"],
        "provider_structure_chain_order": ["A", "B"],
        "provider_chain_order": ["A", "B"],
        "entries": [
            {
                "residue_id": "A:1",
                "segment_index": 0,
                "provider_chain_id": "A",
                "provider_position": 1,
            },
            {
                "residue_id": "A:2",
                "segment_index": 0,
                "provider_chain_id": "A",
                "provider_position": 2,
            },
            {
                "residue_id": "A:3",
                "segment_index": 0,
                "provider_chain_id": "A",
                "provider_position": 3,
            },
            {
                "residue_id": "A:4",
                "segment_index": 1,
                "provider_chain_id": "B",
                "provider_position": 1,
            },
            {
                "residue_id": "A:5",
                "segment_index": 1,
                "provider_chain_id": "B",
                "provider_position": 2,
            },
            {
                "residue_id": "A:6",
                "segment_index": 1,
                "provider_chain_id": "B",
                "provider_position": 3,
            },
        ],
    }
    assert resources.public_invocations[0]["invocation_provenance"][
        "provider_residue_projection"
    ] == expected_projection
    assert resources.public_invocations[1]["invocation_provenance"][
        "provider_residue_projection"
    ] == expected_projection


def test_provider_staging_capacity_counts_segments_not_workbench_chains(
    tmp_path: Path,
) -> None:
    from modules.proteinmpnn.provider_runtime import _parse_structure

    class CapacityProvider(_ControlledProteinMPNNProvider):
        def parse_structure(self, pdb_string: str) -> list[dict[str, Any]]:
            self.parsed.append(pdb_string)
            return _parse_structure(
                pdb_string,
                temp_dir=tmp_path,
                provider_root=Path("repositories/ProteinMPNN").resolve(),
            )

        def design(self, request: Any) -> list[ProteinSequence]:
            self.requests.append(request)
            return [ProteinSequence("A" * request.target_length)]

    supported_layout = ResidueLayout(
        "A",
        62,
        [f"A:{position}" for position in range(1, 63)],
    )
    supported_unsplit = _resolved_axis(
        layout=supported_layout,
        sequence="A" * 62,
    )
    supported_axis = replace(
        supported_unsplit,
        segments=tuple(
            StructureAxisSegment(index, "A", (residue_id,))
            for index, residue_id in enumerate(
                supported_layout.residue_ids or ()
            )
        ),
    )
    supported_provider = CapacityProvider()

    result = _controlled_adapter(supported_provider).design(
        residue_axis=supported_axis,
        num_sequences=1,
        temperature=0.1,
        backbone_noise=0,
        seed=1603,
        constraints=ProteinMPNNConstraints(
            layout=supported_layout,
            designed_chains=["A"],
        ),
        reference_sequence=None,
        engine_role="design_parent_0",
    )

    assert result == (ProteinSequence("A" * 62, supported_layout.residue_ids),)
    assert supported_provider.requests[0].provider_structure_chain_order == (
        tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789")
    )

    layout = ResidueLayout(
        "A",
        63,
        [f"A:{position}" for position in range(1, 64)],
    )
    unsplit_axis = _resolved_axis(layout=layout, sequence="A" * 63)
    axis = replace(
        unsplit_axis,
        segments=tuple(
            StructureAxisSegment(index, "A", (residue_id,))
            for index, residue_id in enumerate(layout.residue_ids or ())
        ),
    )
    provider = _ControlledProteinMPNNProvider()

    with pytest.raises(ValueError, match="too many provider chains"):
        _controlled_adapter(provider).design(
            residue_axis=axis,
            num_sequences=1,
            temperature=0.1,
            backbone_noise=0,
            seed=1603,
            constraints=None,
            reference_sequence=None,
            engine_role="design_parent_0",
        )

    assert provider.parsed == []
    assert provider.requests == []


@pytest.mark.parametrize("operation", ("design", "score"))
def test_provider_residue_projection_starts_before_provider_failure(
    operation: str,
) -> None:
    resources = _AdapterResources()
    expected_projection = {
        "position_semantics": "one_based_chain_local",
        "workbench_chain_order": ["A", "B"],
        "provider_structure_chain_order": ["A", "B"],
        "provider_chain_order": ["A", "B"],
        "entries": [
            {
                "residue_id": "A:1",
                "segment_index": 0,
                "provider_chain_id": "A",
                "provider_position": 1,
            },
            {
                "residue_id": "A:2",
                "segment_index": 0,
                "provider_chain_id": "A",
                "provider_position": 2,
            },
            {
                "residue_id": "B:1",
                "segment_index": 1,
                "provider_chain_id": "B",
                "provider_position": 1,
            },
            {
                "residue_id": "B:2",
                "segment_index": 1,
                "provider_chain_id": "B",
                "provider_position": 2,
            },
            {
                "residue_id": "B:3",
                "segment_index": 1,
                "provider_chain_id": "B",
                "provider_position": 3,
            },
        ],
    }
    expected_provenance = {
        "provider_residue_projection": expected_projection,
    }
    if operation == "design":
        expected_provenance["effective_randomness"] = {
            "control": "exact_seed",
            "effective_seed": 1603,
        }
    else:
        expected_provenance["effective_randomness"] = {
            "control": "exact_seed",
            "effective_seed": 42,
        }

    class FailingProvider(_ControlledProteinMPNNProvider):
        def _fail(self) -> None:
            assert resources.public_invocations == [
                {
                    "engine_role": (
                        "design_parent_0"
                        if operation == "design"
                        else "score_subject"
                    ),
                    "invocation_provenance": expected_provenance,
                }
            ]
            raise RuntimeError("controlled provider failure")

        def design(self, request: Any) -> Any:
            self.requests.append(request)
            self._fail()

        def score(self, request: Any, sequence: ProteinSequence) -> Any:
            self.requests.append((request, sequence))
            self._fail()

    adapter = _controlled_adapter(
        FailingProvider(),
        resources=resources,
    )
    with pytest.raises(RuntimeError, match="controlled provider failure"):
        if operation == "design":
            adapter.design(
                residue_axis=_resolved_axis(),
                num_sequences=1,
                temperature=0.1,
                backbone_noise=0,
                seed=1603,
                constraints=None,
                reference_sequence=None,
                engine_role="design_parent_0",
            )
        else:
            adapter.score(
                residue_axis=_resolved_axis(),
                sequence=ProteinSequence(
                    "AGSTW",
                    ["A:1", "A:2", "B:1", "B:2", "B:3"],
                ),
            )


def test_provider_failure_keeps_durable_residue_projection_started_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.prompt_authoring.package import (
        MODULE_PACKAGE as PROMPT_AUTHORING_PACKAGE,
    )
    from modules.proteinmpnn.package import (
        MODULE_PACKAGE as PROTEINMPNN_PACKAGE,
    )
    from tests.fixtures.proteinmpnn_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    class Provider(_ControlledProteinMPNNProvider):
        def design(self, request: Any) -> Any:
            self.requests.append(request)
            raise RuntimeError("controlled provider failure")

    provider = Provider()
    _install_test_provider(monkeypatch, provider)
    nodes, edges = _design_workflow()
    _, _, projection, events = _run(
        tmp_path,
        nodes=nodes,
        edges=edges,
        registrations=(
            PROMPT_AUTHORING_PACKAGE,
            PROTEINMPNN_PACKAGE,
            SOURCE_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        ),
        environment=_proteinmpnn_environment(),
    )

    assert projection["status"] == "failed"
    invocation = next(
        item["event"]
        for item in events
        if item["event"]["type"] == "engine_invocation_started"
        and item["event"]["engine_role"] == "design_parent_0"
    )
    provenance = invocation["invocation_provenance"]
    assert provenance["provider_residue_projection"] == {
        "position_semantics": "one_based_chain_local",
        "workbench_chain_order": ["A", "B"],
        "provider_structure_chain_order": ["A", "B"],
        "provider_chain_order": ["A", "B"],
        "entries": [
            {
                "residue_id": "A:1",
                "segment_index": 0,
                "provider_chain_id": "A",
                "provider_position": 1,
            },
            {
                "residue_id": "A:2",
                "segment_index": 0,
                "provider_chain_id": "A",
                "provider_position": 2,
            },
            {
                "residue_id": "B:1",
                "segment_index": 1,
                "provider_chain_id": "B",
                "provider_position": 1,
            },
            {
                "residue_id": "B:2",
                "segment_index": 1,
                "provider_chain_id": "B",
                "provider_position": 2,
            },
            {
                "residue_id": "B:3",
                "segment_index": 1,
                "provider_chain_id": "B",
                "provider_position": 3,
            },
        ],
    }
    randomness = provenance["effective_randomness"]
    assert randomness["control"] == "exact_seed"
    assert type(randomness["effective_seed"]) is int
    assert any(
        item["event"]["type"] == "engine_invocation_terminal"
        and item["event"]["invocation_id"] == invocation["invocation_id"]
        and item["event"]["status"] == "failed"
        for item in events
    )


def test_scoring_replay_preserves_candidate_and_observation_identity_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.proteinmpnn.package import (
        MODULE_PACKAGE as PROTEINMPNN_PACKAGE,
    )
    from tests.fixtures.proteinmpnn_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    nodes, edges = _score_workflow()
    catalog = build_frozen_catalog(
        (
            PROTEINMPNN_PACKAGE,
            SOURCE_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        )
    )
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create("ProteinMPNN scoring replay")
    authoring = WorkflowAuthoringService(projects, catalog)
    committed = authoring.commit(
        project.id,
        workflow=WorkflowDocument(
            schema_version="2.1.0",
            workflow_id=project.id,
            nodes=nodes,
            edges=edges,
            contract_lock=(),
        ),
    )
    def run(provider: _ControlledProteinMPNNProvider) -> tuple[
        dict[str, Any],
        tuple[dict[str, Any], ...],
        ScoreCollection,
        CandidateCollection,
    ]:
        _install_test_provider(monkeypatch, provider)
        service = V2RunService(
            projects,
            catalog,
            authoring,
            NodeAttemptFactory(
                projects,
                _proteinmpnn_environment(catalog),
                result_store(projects),
            ),
            result_store(projects),
        )
        receipt = service.start_background(
            project.id,
            workflow_commit_id=committed.workflow_commit_id,
            client_request_id=f"score-replay-{id(provider)}",
        )
        service.shutdown()
        projection = public_run_projection(service, project.id, receipt["run_id"])
        events = public_run_events(service, project.id, receipt["run_id"])
        assert projection["status"] == "succeeded", events
        score_output = next(
            output
            for output in projection["outputs"]
            if output["node_id"] == "score"
        )
        subject_output = next(
            output
            for output in projection["outputs"]
            if output["node_id"] == "sequence-source"
        )
        return (
            score_output,
            events,
            _decode_output(catalog, service, projection, score_output),
            _decode_output(catalog, service, projection, subject_output),
        )

    first_provider = _ControlledProteinMPNNProvider()
    first_output, first_events, first_scores, first_subjects = run(
        first_provider
    )
    replay_provider = _ControlledProteinMPNNProvider()
    replay_output, replay_events, replay_scores, replay_subjects = run(
        replay_provider
    )

    assert first_output["result_identity"] == replay_output[
        "result_identity"
    ]
    assert first_subjects.items[0].candidate_id == (
        replay_subjects.items[0].candidate_id
    )
    first_observation = first_scores.entries[0]
    replay_observation = replay_scores.entries[0]
    assert type(first_observation) is ScoreObservation
    assert type(replay_observation) is ScoreObservation
    assert first_observation.identity == replay_observation.identity
    assert first_observation.value == replay_observation.value == 2.75
    assert len(first_provider.parsed) == len(first_provider.requests) == 1
    assert replay_provider.parsed == []
    assert replay_provider.requests == []

    def score_readiness(
        events: tuple[dict[str, Any], ...],
    ) -> list[dict[str, Any]]:
        return [
            item["event"]
            for item in events
            if item["event"]["type"] == "readiness_attested"
            and item["event"]["binding"]["contract_id"]
            == "proteinmpnn.score.local"
        ]

    assert len(score_readiness(first_events)) == 1
    assert score_readiness(replay_events) == []
    score_method_digest = catalog.require_contract(
        "method",
        "proteinmpnn.score.v_48_020_8907e667",
        "6.0.0",
    ).contract_digest
    assert all(
        item["event"]["type"] != "engine_invocation_started"
        or item["event"]["engine_identity"] != score_method_digest
        for item in replay_events
    )


def _design_workflow() -> tuple[
    tuple[WorkflowNodeInstance, ...],
    tuple[WorkflowEdge, ...],
]:
    nodes = (
        WorkflowNodeInstance(
            node_id="source",
            node_type_id="contract_test.proteinmpnn_source",
            node_type_version="5.0.0",
            binding_id="contract_test.proteinmpnn_source.direct",
            binding_version="5.0.0",
            node_parameters={"parent_count": 3},
            binding_parameters={},
        ),
        WorkflowNodeInstance(
            node_id="layout",
            node_type_id="prompt_authoring.build_residue_layout",
            node_type_version="3.0.0",
            binding_id="prompt_authoring.build_residue_layout.direct",
            binding_version="3.0.0",
            node_parameters={
                "chains": [
                    {"chain_id": "A", "length": 2},
                    {"chain_id": "B", "length": 3},
                ]
            },
            binding_parameters={},
        ),
        WorkflowNodeInstance(
            node_id="constraints",
            node_type_id="proteinmpnn.constraints",
            node_type_version="4.0.0",
            binding_id="proteinmpnn.constraints.local",
            binding_version="4.0.0",
            node_parameters={
                "designable_residue_ids": ["A:1", "B:1", "B:3"],
                "fixed_residue_ids": ["A:2", "B:2"],
                "designed_chains": ["A", "B"],
                "fixed_chains": [],
                "omit_amino_acids": ["C", "M"],
                "tied_residue_groups": [["A:1", "B:1"]],
                "bias_by_residue": [
                    {
                        "residue_id": "B:3",
                        "amino_acid": "A",
                        "bias": 1.5,
                    },
                ],
            },
            binding_parameters={},
        ),
        WorkflowNodeInstance(
            node_id="resolve-axes",
            node_type_id=(
                "structure_transform.resolve_candidate_residue_axes"
            ),
            node_type_version="6.0.0",
            binding_id=(
                "structure_transform.resolve_candidate_residue_axes.direct"
            ),
            binding_version="6.0.0",
            node_parameters={},
            binding_parameters={},
        ),
        WorkflowNodeInstance(
            node_id="design",
            node_type_id="proteinmpnn.design",
            node_type_version="10.0.0",
            binding_id="proteinmpnn.design.local",
            binding_version="11.0.0",
            node_parameters={
                "effective_seed": 1603,
                "num_sequences": 5,
                "temperature": 0.2,
                "backbone_noise": 0.1,
            },
            binding_parameters={},
        ),
    )
    edges = (
        WorkflowEdge("layout", "layout", "constraints", "layout"),
        WorkflowEdge(
            "source",
            "structure_candidates",
            "resolve-axes",
            "structure_candidates",
        ),
        WorkflowEdge(
            "source",
            "structure_candidates",
            "design",
            "structure_candidates",
        ),
        WorkflowEdge(
            "resolve-axes",
            "residue_axes",
            "design",
            "structure_residue_axes",
        ),
        WorkflowEdge("source", "sequence", "design", "sequence"),
        WorkflowEdge(
            "constraints",
            "constraints",
            "design",
            "constraints",
        ),
    )
    return nodes, edges


@pytest.mark.parametrize(
    ("missing_position_fixed", "error_match"),
    (
        (True, None),
        (False, "complete backbone coordinates"),
    ),
)
def test_provider_decoding_requires_missing_backbone_residue_to_be_fixed(
    missing_position_fixed: bool,
    error_match: str | None,
) -> None:
    import torch

    import modules.proteinmpnn.provider_request as provider_request
    import modules.proteinmpnn.provider_runtime as provider_runtime

    class Model:
        def tied_sample(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            del args, kwargs
            return {
                "S": torch.tensor(
                    [[
                        provider_request._ALPHABET_DICT["A"],
                        provider_request._ALPHABET_DICT["C"],
                        provider_request._ALPHABET_DICT["D"],
                    ]],
                    dtype=torch.int64,
                )
            }

    batch = {
        "X": torch.zeros((1, 3, 4, 3)),
        "S": torch.tensor([[0, 1, 2]], dtype=torch.int64),
        "mask": torch.tensor([[1.0, 0.0, 1.0]]),
        "lengths": torch.tensor([3], dtype=torch.int64),
        "chain_M": torch.ones((1, 3)),
        "chain_encoding_all": torch.ones((1, 3)),
        "residue_idx": torch.arange(3).reshape(1, 3),
        "chain_M_pos": torch.tensor(
            [[1.0, 0.0 if missing_position_fixed else 1.0, 1.0]]
        ),
        "tied_pos_list_of_lists_list": [[]],
        "bias_by_res_all": torch.zeros((1, 3, 21)),
    }

    def run() -> list[ProteinSequence]:
        return provider_runtime._run_design(
            Model(),
            batch,
            num_sequences=1,
            temperature=0.2,
            device=torch.device("cpu"),
            omit_amino_acids=["X"],
        )

    if error_match is not None:
        with pytest.raises(RuntimeError, match=error_match):
            run()
        return

    assert run() == [ProteinSequence("ACD")]


def test_provider_scoring_uses_exact_backbone_and_designability_mask(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import torch

    import modules.proteinmpnn.provider_runtime as provider_runtime

    captured: dict[str, Any] = {}

    class ProviderModule:
        @staticmethod
        def _scores(
            sequence: Any,
            log_probs: Any,
            mask: Any,
        ) -> Any:
            del sequence, log_probs
            captured["mask"] = mask.clone()
            return torch.tensor([1.25], dtype=torch.float32)

    class Model:
        @staticmethod
        def forward(*args: Any) -> Any:
            del args
            return torch.zeros((1, 3, 21), dtype=torch.float32)

    monkeypatch.setattr(
        provider_runtime,
        "_provider_module",
        lambda _provider_root=None: ProviderModule(),
    )
    score = provider_runtime._compute_score(
        Model(),
        {
            "X": torch.zeros((1, 3, 4, 3)),
            "mask": torch.tensor([[1.0, 1.0, 0.0]]),
            "chain_M": torch.tensor([[1.0, 1.0, 1.0]]),
            "chain_M_pos": torch.tensor([[1.0, 0.0, 1.0]]),
            "chain_encoding_all": torch.ones((1, 3)),
            "residue_idx": torch.arange(3).reshape(1, 3),
        },
        "ACD",
        torch.device("cpu"),
        _proteinmpnn_provider_root(),
    )

    assert score == 1.25
    assert torch.equal(
        captured["mask"],
        torch.tensor([[1.0, 0.0, 0.0]]),
    )


def test_design_produces_canonical_three_parent_by_five_child_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.prompt_authoring.package import (
        MODULE_PACKAGE as PROMPT_AUTHORING_PACKAGE,
    )
    from modules.proteinmpnn.provider_request import _ALPHABET_DICT
    from modules.proteinmpnn.package import (
        MODULE_PACKAGE as PROTEINMPNN_PACKAGE,
    )
    from tests.fixtures.proteinmpnn_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    provider = _ControlledProteinMPNNProvider()
    _install_test_provider(monkeypatch, provider)
    nodes, edges = _design_workflow()
    catalog, service, projection, events = _run(
        tmp_path,
        nodes=nodes,
        edges=edges,
        registrations=(
            PROMPT_AUTHORING_PACKAGE,
            PROTEINMPNN_PACKAGE,
            SOURCE_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        ),
        environment=_proteinmpnn_environment(),
    )

    assert projection["status"] == "succeeded", events
    output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "design"
        and item["output_port"] == "sequence_candidates"
    )
    candidates = _decode_output(catalog, service, projection, output)
    assert isinstance(candidates, CandidateCollection)
    assert len(candidates.items) == 15
    parent_groups: dict[str, list[Any]] = {}
    for candidate in candidates.items:
        assert len(candidate.parent_ids) == 1
        parent_groups.setdefault(candidate.parent_ids[0], []).append(candidate)
        assert candidate.metadata["effective_seed"] == 1603
        assert "model" not in candidate.metadata
        assert "residue_identity_mapping" not in candidate.metadata
        assert candidate.metadata["constraint_digest"].startswith("sha256:")
        assert candidate.metadata["content_digest"].startswith("sha256:")
    assert len(parent_groups) == 3
    assert {
        tuple(child.metadata["sample_index"] for child in children)
        for children in parent_groups.values()
    } == {tuple(range(5))}
    assert len({child.candidate_id for child in candidates.items}) == 15
    assert len(provider.parsed) == len(provider.requests) == 3
    assert len({request.seed for request in provider.requests}) == 3
    assert {request.num_sequences for request in provider.requests} == {5}
    assert {request.temperature for request in provider.requests} == {0.2}
    assert {request.backbone_noise for request in provider.requests} == {0.1}
    assert all(
        request.chain_dict == {"target": (["A", "B"], [])}
        and request.fixed_position_dict
        == {"target": {"A": [2], "B": [2]}}
        and request.tied_positions_dict
        == {"target": [{"A": [1], "B": [1]}]}
        and request.omit_amino_acids == ["C", "M", "X"]
        and request.reference_sequences == {"A": "AG", "B": "STW"}
        and request.bias_by_res_dict is not None
        and request.bias_by_res_dict["target"]["B"][2][
            _ALPHABET_DICT["A"]
        ]
        == 1.5
        for request in provider.requests
    )
    design_method_digest = catalog.require_contract(
        "method",
        "proteinmpnn.design.v_48_020_8907e667",
        "6.0.0",
    ).contract_digest
    design_started = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_identity"] == design_method_digest
    ]
    design_terminal = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_terminal"
        and event["event"]["invocation_id"]
        in {item["invocation_id"] for item in design_started}
    ]
    assert len(design_started) == len(design_terminal) == 3
    assert {item["engine_role"] for item in design_started} == {
        "design_parent_0",
        "design_parent_1",
        "design_parent_2",
    }
    assert {item["status"] for item in design_terminal} == {"succeeded"}
    public_evidence = str({"projection": projection, "events": events})
    assert "proteinmpnn-secret-must-not-publish" not in public_evidence


def test_design_seed_depends_on_structure_content_and_parent_slot_not_result_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.proteinmpnn.package import (
        MODULE_PACKAGE as PROTEINMPNN_PACKAGE,
    )
    from modules.structure_transform.package import (
        MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
    )
    from tests.fixtures.proteinmpnn_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    def run(transform_depth: int) -> tuple[int, str, str, str]:
        class SingleChainProvider(_ControlledProteinMPNNProvider):
            def parse_structure(
                self,
                pdb_string: str,
            ) -> list[dict[str, Any]]:
                self.parsed.append(pdb_string)
                return [
                    {
                        "name": "target",
                        "seq": "AG",
                        "seq_chain_A": "AG",
                    }
                ]

            def design(
                self,
                request: Any,
            ) -> list[ProteinSequence]:
                self.requests.append(request)
                return [
                    ProteinSequence("AG")
                    for _ in range(request.num_sequences)
                ]

        provider = SingleChainProvider()
        _install_test_provider(monkeypatch, provider)
        source_node_id = "source"
        transform_nodes = tuple(
            WorkflowNodeInstance(
                node_id=f"select-{index}",
                node_type_id="structure_transform.select_candidate_chains",
                node_type_version="4.0.0",
                binding_id=(
                    "structure_transform.select_candidate_chains.direct"
                ),
                binding_version="4.0.0",
                node_parameters={"chain_ids": ["A"]},
                binding_parameters={},
            )
            for index in range(transform_depth)
        )
        nodes = (
            WorkflowNodeInstance(
                node_id=source_node_id,
                node_type_id="contract_test.proteinmpnn_source",
                node_type_version="5.0.0",
                binding_id="contract_test.proteinmpnn_source.direct",
                binding_version="5.0.0",
                node_parameters={"parent_count": 1},
                binding_parameters={},
            ),
            *transform_nodes,
            WorkflowNodeInstance(
                node_id="resolve-axes",
                node_type_id=(
                    "structure_transform.resolve_candidate_residue_axes"
                ),
                node_type_version="6.0.0",
                binding_id=(
                    "structure_transform."
                    "resolve_candidate_residue_axes.direct"
                ),
                binding_version="6.0.0",
                node_parameters={},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="design",
                node_type_id="proteinmpnn.design",
                node_type_version="10.0.0",
                binding_id="proteinmpnn.design.local",
                binding_version="11.0.0",
                node_parameters={
                    "effective_seed": 1603,
                    "num_sequences": 1,
                    "temperature": 0.2,
                    "backbone_noise": 0,
                },
                binding_parameters={},
            ),
        )
        transform_edges = tuple(
            WorkflowEdge(
                source_node_id if index == 0 else f"select-{index - 1}",
                "structure_candidates",
                f"select-{index}",
                "structure_candidates",
            )
            for index in range(transform_depth)
        )
        final_parent_node = f"select-{transform_depth - 1}"
        catalog, service, projection, events = _run(
            tmp_path / f"depth-{transform_depth}",
            nodes=nodes,
            edges=(
                *transform_edges,
                WorkflowEdge(
                    final_parent_node,
                    "structure_candidates",
                    "resolve-axes",
                    "structure_candidates",
                ),
                WorkflowEdge(
                    final_parent_node,
                    "structure_candidates",
                    "design",
                    "structure_candidates",
                ),
                WorkflowEdge(
                    "resolve-axes",
                    "residue_axes",
                    "design",
                    "structure_residue_axes",
                ),
            ),
            registrations=(
                PROTEINMPNN_PACKAGE,
                SOURCE_PACKAGE,
                STRUCTURE_TRANSFORM_PACKAGE,
            ),
            environment=_proteinmpnn_environment(),
        )
        assert projection["status"] == "succeeded", events
        source_output = next(
            output
            for output in projection["outputs"]
            if output["node_id"] == final_parent_node
            and output["output_port"] == "structure_candidates"
        )
        parents = _decode_output(
            catalog,
            service,
            projection,
            source_output,
        )
        assert len(provider.requests) == 1
        return (
            provider.requests[0].seed,
            parents.items[0].candidate_id,
            parents.items[0].data.pdb_string,
            catalog.require_port_type(
                "protein.structure",
                "4.0.0",
            ).content_digest(parents.items[0].data),
        )

    first_seed, first_parent_id, first_pdb, first_content_digest = run(1)
    second_seed, second_parent_id, second_pdb, second_content_digest = run(2)

    expected_seed = int.from_bytes(
        hashlib.sha256(
            (
                "protein-workbench-proteinmpnn-parent-seed/v2\0"
                "1603\0"
                "0\0"
                f"{first_content_digest}"
            ).encode()
        ).digest()[:7],
        "big",
    ) % 9_007_199_254_740_992

    assert first_parent_id != second_parent_id
    assert first_pdb == second_pdb
    assert first_content_digest == second_content_digest
    assert first_seed == second_seed == expected_seed


def test_2emo_identity_layout_maps_to_provider_invocation_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.prompt_authoring.package import (
        MODULE_PACKAGE as PROMPT_AUTHORING_PACKAGE,
    )
    from modules.proteinmpnn.package import (
        MODULE_PACKAGE as PROTEINMPNN_PACKAGE,
    )
    from modules.structure_transform.package import (
        MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
    )
    from tests.fixtures.prompt_authoring_sources.package import (
        MODULE_PACKAGE as PROMPT_SOURCE_PACKAGE,
    )
    from tests.fixtures.proteinmpnn_sources.package import (
        MODULE_PACKAGE as MPNN_SOURCE_PACKAGE,
    )

    class IdentityLayoutProvider(_ControlledProteinMPNNProvider):
        def parse_structure(self, pdb_string: str) -> list[dict[str, Any]]:
            self.parsed.append(pdb_string)
            return [{"name": "target", "seq_chain_A": "A" * 224}]

        def design(
            self,
            request: Any,
        ) -> list[ProteinSequence]:
            self.requests.append(request)
            return [
                ProteinSequence("A" * request.target_length)
                for _ in range(request.num_sequences)
            ]

    provider = IdentityLayoutProvider()
    _install_test_provider(monkeypatch, provider)
    nodes = (
        WorkflowNodeInstance(
            node_id="source",
            node_type_id="contract_test.prompt_authoring_values",
            node_type_version="4.0.0",
            binding_id="contract_test.prompt_authoring_values.direct",
            binding_version="4.0.0",
            node_parameters={"fixture": "2emo"},
            binding_parameters={},
        ),
        WorkflowNodeInstance(
            node_id="normalize",
            node_type_id="structure_transform.normalize_csh_parent_span",
            node_type_version="5.0.0",
            binding_id=(
                "structure_transform.normalize_csh_parent_span.direct"
            ),
            binding_version="5.0.0",
            node_parameters={},
            binding_parameters={},
        ),
        WorkflowNodeInstance(
            node_id="resolve-axis",
            node_type_id="structure_transform.resolve_residue_axis",
            node_type_version="4.0.0",
            binding_id="structure_transform.resolve_residue_axis.direct",
            binding_version="4.0.0",
            node_parameters={},
            binding_parameters={},
        ),
        WorkflowNodeInstance(
            node_id="prompt",
            node_type_id="prompt_authoring.prompt_from_structure",
            node_type_version="5.0.0",
            binding_id="prompt_authoring.prompt_from_structure.direct",
            binding_version="5.0.0",
            node_parameters={},
            binding_parameters={},
        ),
        WorkflowNodeInstance(
            node_id="constraints",
            node_type_id="proteinmpnn.constraints",
            node_type_version="4.0.0",
            binding_id="proteinmpnn.constraints.local",
            binding_version="4.0.0",
            node_parameters={
                "designable_residue_ids": [],
                "fixed_residue_ids": ["A:42", "A:65", "A:66", "A:67"],
                "designed_chains": [],
                "fixed_chains": [],
                "omit_amino_acids": [],
                "tied_residue_groups": [],
                "bias_by_residue": [],
            },
            binding_parameters={},
        ),
        WorkflowNodeInstance(
            node_id="candidateize",
            node_type_id=(
                "contract_test.proteinmpnn_structure_candidateize"
            ),
            node_type_version="2.0.0",
            binding_id=(
                "contract_test."
                "proteinmpnn_structure_candidateize.direct"
            ),
            binding_version="2.0.0",
            node_parameters={},
            binding_parameters={},
        ),
        WorkflowNodeInstance(
            node_id="resolve-candidate-axis",
            node_type_id=(
                "structure_transform.resolve_candidate_residue_axes"
            ),
            node_type_version="6.0.0",
            binding_id=(
                "structure_transform."
                "resolve_candidate_residue_axes.direct"
            ),
            binding_version="6.0.0",
            node_parameters={},
            binding_parameters={},
        ),
        WorkflowNodeInstance(
            node_id="design",
            node_type_id="proteinmpnn.design",
            node_type_version="10.0.0",
            binding_id="proteinmpnn.design.local",
            binding_version="11.0.0",
            node_parameters={
                "effective_seed": 1603,
                "num_sequences": 1,
                "temperature": 0.2,
                "backbone_noise": 0,
            },
            binding_parameters={},
        ),
    )
    catalog, service, projection, events = _run(
        tmp_path,
        nodes=nodes,
        edges=(
            WorkflowEdge("source", "structure", "normalize", "structure"),
            WorkflowEdge("normalize", "structure", "resolve-axis", "structure"),
            WorkflowEdge(
                "normalize",
                "modified_residue_normalizations",
                "resolve-axis",
                "modified_residue_normalizations",
            ),
            WorkflowEdge("resolve-axis", "residue_axis", "prompt", "residue_axis"),
            WorkflowEdge("prompt", "layout", "constraints", "layout"),
            WorkflowEdge(
                "normalize",
                "structure",
                "candidateize",
                "structure",
            ),
            WorkflowEdge(
                "candidateize",
                "structure_candidates",
                "resolve-candidate-axis",
                "structure_candidates",
            ),
            WorkflowEdge(
                "candidateize",
                "structure_candidates",
                "design",
                "structure_candidates",
            ),
            WorkflowEdge(
                "resolve-candidate-axis",
                "residue_axes",
                "design",
                "structure_residue_axes",
            ),
            WorkflowEdge(
                "constraints",
                "constraints",
                "design",
                "constraints",
            ),
        ),
        registrations=(
            PROMPT_AUTHORING_PACKAGE,
            PROMPT_SOURCE_PACKAGE,
            MPNN_SOURCE_PACKAGE,
            PROTEINMPNN_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        ),
        environment=_proteinmpnn_environment(),
    )

    assert projection["status"] == "succeeded", events
    assert len(provider.requests) == 1
    request = provider.requests[0]
    assert request.target_layout.length == 224
    assert request.target_layout.residue_ids[:2] == ("A:6", "A:7")
    assert request.target_layout.residue_ids[-1] == "A:229"
    assert request.fixed_position_dict == {
        "target": {"A": [37, 60, 61, 62]}
    }
    assert request.residue_identity_mapping[0] == ("A:6", 0, "A", 1)
    assert request.residue_identity_mapping[-1] == (
        "A:229",
        0,
        "A",
        224,
    )
    output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "design"
        and item["output_port"] == "sequence_candidates"
    )
    candidates = _decode_output(catalog, service, projection, output)
    candidate = candidates.items[0]
    assert candidate.data.residue_ids == request.target_layout.residue_ids
    assert "residue_identity_mapping" not in candidate.metadata
    assert "model" not in candidate.metadata
    invocation = next(
        item["event"]
        for item in events
        if item["event"]["type"] == "engine_invocation_started"
        and item["event"]["engine_role"] == "design_parent_0"
    )
    provenance = invocation["invocation_provenance"]
    projection_provenance = provenance["provider_residue_projection"]
    assert projection_provenance["position_semantics"] == (
        "one_based_chain_local"
    )
    assert projection_provenance["workbench_chain_order"] == ["A"]
    assert projection_provenance["provider_structure_chain_order"] == ["A"]
    assert projection_provenance["provider_chain_order"] == ["A"]
    assert projection_provenance["entries"][0] == {
        "residue_id": "A:6",
        "segment_index": 0,
        "provider_chain_id": "A",
        "provider_position": 1,
    }
    assert projection_provenance["entries"][-1] == {
        "residue_id": "A:229",
        "segment_index": 0,
        "provider_chain_id": "A",
        "provider_position": 224,
    }
    assert provenance["effective_randomness"] == {
        "control": "exact_seed",
        "effective_seed": candidate.metadata["effective_call_seed"],
    }


def test_design_binding_fixes_model_source_checkpoint_and_runtime_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.proteinmpnn.provider_runtime as provider_runtime
    from modules.proteinmpnn.package import (
        MODULE_PACKAGE as PROTEINMPNN_PACKAGE,
    )

    def fail_if_loaded(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise AssertionError("catalog discovery must not load ProteinMPNN")

    monkeypatch.setattr(provider_runtime, "_load_model", fail_if_loaded)
    catalog = build_frozen_catalog(
        (PROTEINMPNN_PACKAGE, STRUCTURE_TRANSFORM_PACKAGE)
    )
    binding = catalog.require_contract(
        "binding",
        "proteinmpnn.design.local",
        "11.0.0",
    )
    node = catalog.require_contract(
        "node_type",
        "proteinmpnn.design",
        "10.0.0",
    )
    method_reference = binding.descriptor["method"]
    method = catalog.require_contract(
        method_reference["contract_kind"],
        method_reference["contract_id"],
        method_reference["contract_version"],
    )

    assert binding.descriptor["binding_parameters"] == {}
    assert {
        "model",
        "model_name",
        "model_path",
        "checkpoint_path",
        "device",
        "runtime_directory",
        "temp_dir",
    }.isdisjoint(node.descriptor["node_parameters"])
    assert binding.descriptor["implementation_identity"][
        "model"
    ] == "v_48_020"
    assert binding.descriptor["implementation_identity"][
        "device"
    ] == "cpu"
    assert binding.descriptor["implementation_identity"][
        "torch_version"
    ] == "2.13.0"
    assert binding.descriptor["implementation_identity"][
        "structure_projection"
    ] == "resolved-axis-segment-provider-native-staging-v2"
    assert method.descriptor["model_identity"] == {
        "model": "v_48_020",
        "architecture": "ProteinMPNN",
        "source": "dauparas/ProteinMPNN",
    }
    assert method.descriptor["checkpoint_identity"] == {
        "relative_path": "vanilla_model_weights/v_48_020.pt",
        "sha256": (
            "c9cb4a671d79604111231f8dbfc7c590e06f1197453b7a6854ac6661a642f5bd"
        ),
    }
    assert method.descriptor["source_identity"][
        "source_revision"
    ] == "8907e6671bfbfc92303b5f79c4b5e6ce47cdef57"
    assert method.descriptor["algorithm_identity"][
        "constraint_indexing"
    ] == (
        "canonical-residue-identity-to-provider-segment-chain-and-"
        "segment-local-continuous-one-based-position"
    )
    assert method.descriptor["algorithm_identity"]["call_seed"] == (
        "sha256-effective-seed-parent-structure-content-parent-slot"
    )
    assert method.descriptor["featurization_identity"] == {
        "structure": (
            "resolved-axis deterministic N-CA-C-O provider PDB "
            "then ProteinMPNN parse_PDB"
        ),
        "residue_projection": (
            "resolved-axis-segment-to-provider-safe-chain;"
            "canonical-identity-to-segment-local-continuous-"
            "one-based-position"
        ),
        "constraints": "ProteinMPNN tied_featurize",
        "reference_sequence": "exact-chain-layout",
        "sequence_decoding": "complete-parsed-target-layout",
        "incomplete_backbone": (
            "axis-selected-coordinate-or-provider-NaN-mask;"
            "fixed-residue-preserved-designable-residue-rejected"
        ),
    }
    assert binding.descriptor["availability_declaration"]["behavior"][
        "parameters"
    ]["model_load"] == "forbidden"
    assert binding.descriptor["readiness_declaration"]["behavior"][
        "parameters"
    ]["model_load"] == "forbidden"


def test_readiness_validates_the_exact_checkout_checkpoint_and_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.proteinmpnn.adapter import proteinmpnn_readiness

    provider_root = (
        Path(__file__).resolve().parent.parent
        / "repositories"
        / "ProteinMPNN"
    )
    monkeypatch.setattr(
        "modules.proteinmpnn.provider_runtime._load_model",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("readiness must not load the model")
        ),
    )
    environment = {
        "device": "cpu",
        "provider_root": provider_root,
    }

    assert proteinmpnn_readiness(
        BindingEnvironment(environment)
    ).passing is True
    assert proteinmpnn_readiness(
        BindingEnvironment({**environment, "device": "cuda"})
    ).passing is False


def test_design_operation_owns_reference_and_constraint_axis_closure() -> None:
    from modules.proteinmpnn.implementation import (
        ProteinMPNNDesignImplementation,
    )

    class TrustingAdapter:
        def __init__(self) -> None:
            self.calls = 0

        def design(self, **kwargs: Any) -> tuple[ProteinSequence, ...]:
            del kwargs
            self.calls += 1
            return (ProteinSequence("AGSTW", TARGET_LAYOUT.residue_ids),)

    structure = _fixture_structure(0)
    candidate = Candidate("exact-parent", structure)
    reference = _structure_candidate_references((candidate,))[0]
    residue_axis = resolve_residue_axis(structure)
    associations = CandidateResolvedResidueAxisAssociations(
        (
            CandidateResolvedResidueAxisAssociation(
                reference,
                residue_axis,
            ),
        )
    )
    base_inputs = _admitted_structure_axis_inputs((candidate,), associations)
    adapter = TrustingAdapter()
    operation = ProteinMPNNDesignImplementation(
        adapter=adapter,
    )

    def execute(extra_inputs: dict[str, Any]) -> None:
        operation.execute(
            OperationCall(
                inputs={**base_inputs, **extra_inputs},
                node_parameters={
                    "effective_seed": 1603,
                    "num_sequences": 1,
                    "temperature": 0.1,
                    "backbone_noise": 0.0,
                },
                binding_parameters={},
                effective_randomness={
                    "effective_seed": 1603,
                    "num_sequences": 1,
                    "temperature": 0.1,
                    "backbone_noise": 0.0,
                },
            )
        )

    with pytest.raises(
        ValueError,
        match="reference sequence must use the exact resolved residue axis",
    ):
        execute(
            {
                "sequence": admitted_port_fixture(
                    ProteinSequence(
                        "AGSTW",
                        ["B:3", "B:2", "B:1", "A:2", "A:1"],
                    ),
                    port_type_id="protein.sequence",
                    value_content_digests=("sha256:" + "5" * 64,),
                )
            }
        )

    changed_layout = ResidueLayout(
        "A,B",
        5,
        ["A:1", "A:2", "A:3", "B:1", "B:2"],
    )
    with pytest.raises(
        ValueError,
        match="constraints must use the exact resolved residue axis",
    ):
        execute(
            {
                "constraints": admitted_port_fixture(
                    ProteinMPNNConstraints(
                        layout=changed_layout,
                        designed_chains=["B"],
                    ),
                    port_type_id="proteinmpnn.constraints",
                    value_content_digests=("sha256:" + "6" * 64,),
                )
            }
        )

    assert adapter.calls == 0


def test_design_accepts_exact_immutable_reference_residue_layout() -> None:
    provider = _ControlledProteinMPNNProvider()
    result = _controlled_adapter(provider).design(
        residue_axis=_resolved_axis(
            structure=ProteinStructure("REMARK exact-layout\nEND\n")
        ),
        num_sequences=1,
        temperature=0.1,
        backbone_noise=0.0,
        seed=1603,
        constraints=None,
        reference_sequence=ProteinSequence(
            "AGSTW",
            ["A:1", "A:2", "B:1", "B:2", "B:3"],
        ),
        engine_role="design_parent_0",
    )

    assert len(result) == 1
    assert result[0].residue_ids == (
        "A:1",
        "A:2",
        "B:1",
        "B:2",
        "B:3",
    )


def test_design_restores_provider_designed_first_chain_order() -> None:
    class DesignedFirstProvider(_ControlledProteinMPNNProvider):
        def design(self, request: Any):
            self.requests.append(request)
            return [ProteinSequence("VVVAG")]

    provider = DesignedFirstProvider()
    result = _controlled_adapter(provider).design(
        residue_axis=_resolved_axis(
            structure=ProteinStructure("REMARK exact-layout\nEND\n")
        ),
        num_sequences=1,
        temperature=0.1,
        backbone_noise=0,
        seed=1603,
        constraints=ProteinMPNNConstraints(
            layout=TARGET_LAYOUT,
            designed_chains=["B"],
            fixed_chains=["A"],
        ),
        reference_sequence=None,
        engine_role="design_parent_0",
    )
    request = provider.requests[0]

    assert request.workbench_chain_order == ("A", "B")
    assert request.provider_structure_chain_order == ("A", "B")
    assert request.provider_chain_order == ("B", "A")
    assert result == (
        ProteinSequence(
            "AGVVV",
            ["A:1", "A:2", "B:1", "B:2", "B:3"],
        ),
    )


def test_design_canonicalizes_constraint_chain_sets_to_provider_order() -> None:
    provider = _ControlledProteinMPNNProvider()
    _controlled_adapter(provider).design(
        residue_axis=_resolved_axis(
            structure=ProteinStructure("REMARK exact-layout\nEND\n")
        ),
        num_sequences=1,
        temperature=0.1,
        backbone_noise=0,
        seed=1603,
        constraints=ProteinMPNNConstraints(
            layout=TARGET_LAYOUT,
            designed_chains=["B", "A"],
        ),
        reference_sequence=None,
        engine_role="design_parent_0",
    )
    request = provider.requests[0]

    assert request.chain_dict == {"target": (["A", "B"], [])}
    assert request.provider_chain_order == ("A", "B")


def test_design_requires_one_candidate_parent_and_preserves_its_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.proteinmpnn.package import (
        MODULE_PACKAGE as PROTEINMPNN_PACKAGE,
    )
    from tests.fixtures.proteinmpnn_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    provider = _ControlledProteinMPNNProvider()
    _install_test_provider(monkeypatch, provider)
    nodes = (
        WorkflowNodeInstance(
            node_id="source",
            node_type_id="contract_test.proteinmpnn_source",
            node_type_version="5.0.0",
            binding_id="contract_test.proteinmpnn_source.direct",
            binding_version="5.0.0",
            node_parameters={"parent_count": 1},
            binding_parameters={},
        ),
        WorkflowNodeInstance(
            node_id="resolve-axes",
            node_type_id=(
                "structure_transform.resolve_candidate_residue_axes"
            ),
            node_type_version="6.0.0",
            binding_id=(
                "structure_transform."
                "resolve_candidate_residue_axes.direct"
            ),
            binding_version="6.0.0",
            node_parameters={},
            binding_parameters={},
        ),
        WorkflowNodeInstance(
            node_id="design",
            node_type_id="proteinmpnn.design",
            node_type_version="10.0.0",
            binding_id="proteinmpnn.design.local",
            binding_version="11.0.0",
            node_parameters={
                "effective_seed": 1603,
                "num_sequences": 1,
                "temperature": 0.1,
                "backbone_noise": 0,
            },
            binding_parameters={},
        ),
    )
    catalog, service, projection, events = _run(
        tmp_path,
        nodes=nodes,
        edges=(
            WorkflowEdge(
                "source",
                "structure_candidates",
                "resolve-axes",
                "structure_candidates",
            ),
            WorkflowEdge(
                "source",
                "structure_candidates",
                "design",
                "structure_candidates",
            ),
            WorkflowEdge(
                "resolve-axes",
                "residue_axes",
                "design",
                "structure_residue_axes",
            ),
        ),
        registrations=(
            PROTEINMPNN_PACKAGE,
            SOURCE_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        ),
        environment=_proteinmpnn_environment(),
    )

    assert projection["status"] == "succeeded", events
    output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "design"
    )
    candidates = _decode_output(catalog, service, projection, output)
    assert len(candidates.items) == 1
    assert len(candidates.items[0].parent_ids) == 1
    assert len(provider.requests) == 1


def test_candidate_design_seed_and_result_ignore_node_instance_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.proteinmpnn.package import (
        MODULE_PACKAGE as PROTEINMPNN_PACKAGE,
    )
    from tests.fixtures.proteinmpnn_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    def run(
        design_node_id: str,
        ) -> tuple[str, CandidateCollection, int, str]:
        provider = _ControlledProteinMPNNProvider()
        _install_test_provider(monkeypatch, provider)
        nodes = (
            WorkflowNodeInstance(
                node_id="source",
                node_type_id="contract_test.proteinmpnn_source",
                node_type_version="5.0.0",
                binding_id="contract_test.proteinmpnn_source.direct",
                binding_version="5.0.0",
                node_parameters={"parent_count": 1},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="resolve-axes",
                node_type_id=(
                    "structure_transform.resolve_candidate_residue_axes"
                ),
                node_type_version="6.0.0",
                binding_id=(
                    "structure_transform."
                    "resolve_candidate_residue_axes.direct"
                ),
                binding_version="6.0.0",
                node_parameters={},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id=design_node_id,
                node_type_id="proteinmpnn.design",
                node_type_version="10.0.0",
                binding_id="proteinmpnn.design.local",
                binding_version="11.0.0",
                node_parameters={
                    "effective_seed": 1603,
                    "num_sequences": 1,
                    "temperature": 0.1,
                    "backbone_noise": 0,
                },
                binding_parameters={},
            ),
        )
        catalog, service, projection, events = _run(
            tmp_path,
            nodes=nodes,
            edges=(
                WorkflowEdge(
                    "source",
                    "structure_candidates",
                    "resolve-axes",
                    "structure_candidates",
                ),
                WorkflowEdge(
                    "source",
                    "structure_candidates",
                    design_node_id,
                    "structure_candidates",
                ),
                WorkflowEdge(
                    "resolve-axes",
                    "residue_axes",
                    design_node_id,
                    "structure_residue_axes",
                ),
            ),
            registrations=(
                PROTEINMPNN_PACKAGE,
                SOURCE_PACKAGE,
                STRUCTURE_TRANSFORM_PACKAGE,
            ),
            environment=_proteinmpnn_environment(),
        )
        assert projection["status"] == "succeeded", events
        output = next(
            item
            for item in projection["outputs"]
            if item["node_id"] == design_node_id
        )
        structure_output = next(
            item
            for item in projection["outputs"]
            if item["node_id"] == "source"
            and item["output_port"] == "structure_candidates"
        )
        structure = _decode_output(
            catalog,
            service,
            projection,
            structure_output,
        ).items[0].data
        return (
            output["result_identity"],
            _decode_output(catalog, service, projection, output),
            provider.requests[0].seed,
            catalog.require_port_type(
                "protein.structure",
                "4.0.0",
            ).content_digest(structure),
        )

    original = run("design-original")
    renamed = run("design-renamed")

    assert original == renamed
    assert original[2] == int.from_bytes(
        hashlib.sha256(
            (
                "protein-workbench-proteinmpnn-parent-seed/v2\0"
                "1603\0"
                "0\0"
                f"{original[3]}"
            ).encode()
        ).digest()[:7],
        "big",
    ) % 9_007_199_254_740_992


def test_design_replay_is_stable_and_changed_seed_changes_result_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.prompt_authoring.package import (
        MODULE_PACKAGE as PROMPT_AUTHORING_PACKAGE,
    )
    from modules.proteinmpnn.package import (
        MODULE_PACKAGE as PROTEINMPNN_PACKAGE,
    )
    from tests.fixtures.proteinmpnn_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    def run(seed: int) -> tuple[str, CandidateCollection]:
        provider = _ControlledProteinMPNNProvider()
        _install_test_provider(monkeypatch, provider)
        nodes, edges = _design_workflow()
        design = nodes[-1]
        nodes = (
            *nodes[:-1],
            WorkflowNodeInstance(
                node_id=design.node_id,
                node_type_id=design.node_type_id,
                node_type_version=design.node_type_version,
                binding_id=design.binding_id,
                binding_version=design.binding_version,
                node_parameters={
                    **dict(design.node_parameters),
                    "effective_seed": seed,
                },
                binding_parameters=design.binding_parameters,
            ),
        )
        catalog, service, projection, events = _run(
            tmp_path,
            nodes=nodes,
            edges=edges,
            registrations=(
                PROMPT_AUTHORING_PACKAGE,
                PROTEINMPNN_PACKAGE,
                SOURCE_PACKAGE,
                STRUCTURE_TRANSFORM_PACKAGE,
            ),
            environment=_proteinmpnn_environment(),
        )
        assert projection["status"] == "succeeded", events
        output = next(
            item
            for item in projection["outputs"]
            if item["node_id"] == "design"
            and item["output_port"] == "sequence_candidates"
        )
        return output["result_identity"], _decode_output(
            catalog,
            service,
            projection,
            output,
        )

    first_identity, first = run(1603)
    replay_identity, replay = run(1603)
    changed_identity, changed = run(1604)

    assert first_identity == replay_identity
    assert first == replay
    assert changed_identity != first_identity
    assert [
        candidate.candidate_id for candidate in changed.items
    ] != [
        candidate.candidate_id for candidate in first.items
    ]


def test_proteinmpnn_passes_the_shared_contract_test_kit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.prompt_authoring.package import (
        MODULE_PACKAGE as PROMPT_AUTHORING_PACKAGE,
    )
    from modules.proteinmpnn.package import (
        MODULE_PACKAGE as PROTEINMPNN_PACKAGE,
    )
    from tests.fixtures.proteinmpnn_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    def layout_node(node_id: str) -> WorkflowNodeInstance:
        return WorkflowNodeInstance(
            node_id=node_id,
            node_type_id="prompt_authoring.build_residue_layout",
            node_type_version="3.0.0",
            binding_id="prompt_authoring.build_residue_layout.direct",
            binding_version="3.0.0",
            node_parameters={
                "chains": [
                    {"chain_id": "A", "length": 2},
                    {"chain_id": "B", "length": 3},
                ]
            },
            binding_parameters={},
        )

    source = WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.proteinmpnn_source",
        node_type_version="5.0.0",
        binding_id="contract_test.proteinmpnn_source.direct",
        binding_version="5.0.0",
        node_parameters={"parent_count": 3},
        binding_parameters={},
    )
    sequence_source = WorkflowNodeInstance(
        node_id="sequence-source",
        node_type_id="contract_test.proteinmpnn_sequence_source",
        node_type_version="4.0.0",
        binding_id="contract_test.proteinmpnn_sequence_source.direct",
        binding_version="4.0.0",
        node_parameters={},
        binding_parameters={},
    )
    score_source = WorkflowNodeInstance(
        node_id="score-source",
        node_type_id="contract_test.proteinmpnn_source",
        node_type_version="5.0.0",
        binding_id="contract_test.proteinmpnn_source.direct",
        binding_version="5.0.0",
        node_parameters={"parent_count": 1},
        binding_parameters={},
    )
    design_axis_resolver = WorkflowNodeInstance(
        node_id="design-axis-resolver",
        node_type_id=(
            "structure_transform.resolve_candidate_residue_axes"
        ),
        node_type_version="6.0.0",
        binding_id=(
            "structure_transform.resolve_candidate_residue_axes.direct"
        ),
        binding_version="6.0.0",
        node_parameters={},
        binding_parameters={},
    )
    score_axis_resolver = WorkflowNodeInstance(
        node_id="score-axis-resolver",
        node_type_id=(
            "structure_transform.resolve_candidate_residue_axes"
        ),
        node_type_version="6.0.0",
        binding_id=(
            "structure_transform.resolve_candidate_residue_axes.direct"
        ),
        binding_version="6.0.0",
        node_parameters={},
        binding_parameters={},
    )
    design_provider = _ControlledProteinMPNNProvider()
    _install_test_provider(monkeypatch, design_provider)
    cases = (
        ModulePackageContractCase(
            case_id="constraints",
            node_type_id="proteinmpnn.constraints",
            node_type_version="4.0.0",
            binding_id="proteinmpnn.constraints.local",
            binding_version="4.0.0",
            node_parameters={
                "designable_residue_ids": ["A:1", "B:1", "B:3"],
                "fixed_residue_ids": ["A:2", "B:2"],
                "designed_chains": ["A", "B"],
                "fixed_chains": [],
                "omit_amino_acids": ["C", "M"],
                "tied_residue_groups": [["A:1", "B:1"]],
                "bias_by_residue": [
                    {
                        "residue_id": "B:3",
                        "amino_acid": "A",
                        "bias": 1.5,
                    }
                ],
            },
            binding_parameters={},
            environment_values={},
            workflow_nodes=(layout_node("layout"),),
            workflow_edges=(
                WorkflowEdge(
                    "layout",
                    "layout",
                    "contract-test-node",
                    "layout",
                ),
            ),
        ),
        ModulePackageContractCase(
            case_id="random-fixed",
            node_type_id="proteinmpnn.random_fixed_positions",
            node_type_version="4.0.0",
            binding_id="proteinmpnn.random_fixed_positions.local",
            binding_version="4.0.0",
            node_parameters={"effective_seed": 1603, "fraction": 0.4},
            binding_parameters={},
            environment_values={},
            workflow_nodes=(layout_node("layout"),),
            workflow_edges=(
                WorkflowEdge(
                    "layout",
                    "layout",
                    "contract-test-node",
                    "layout",
                ),
            ),
        ),
        ModulePackageContractCase(
            case_id="design",
            node_type_id="proteinmpnn.design",
            node_type_version="10.0.0",
            binding_id="proteinmpnn.design.local",
            binding_version="11.0.0",
            node_parameters={
                "effective_seed": 1603,
                "num_sequences": 5,
                "temperature": 0.2,
                "backbone_noise": 0.1,
            },
            binding_parameters={},
            environment_values={
                    "device": "cpu",
                    "provider_root": _proteinmpnn_provider_root(),
            },
            workflow_nodes=(source, design_axis_resolver),
            workflow_edges=(
                WorkflowEdge(
                    "source",
                    "structure_candidates",
                    "contract-test-node",
                    "structure_candidates",
                ),
                WorkflowEdge(
                    "source",
                    "sequence",
                    "contract-test-node",
                    "sequence",
                ),
                WorkflowEdge(
                    "source",
                    "structure_candidates",
                    "design-axis-resolver",
                    "structure_candidates",
                ),
                WorkflowEdge(
                    "design-axis-resolver",
                    "residue_axes",
                    "contract-test-node",
                    "structure_residue_axes",
                ),
            ),
            expected_candidate_counts={"sequence_candidates": 15},
            forbidden_public_fragments=("ctk-proteinmpnn-secret",),
        ),
        ModulePackageContractCase(
            case_id="score",
            node_type_id="proteinmpnn.score",
            node_type_version="7.0.0",
            binding_id="proteinmpnn.score.local",
            binding_version="8.0.0",
            node_parameters={},
            binding_parameters={},
            environment_values={
                    "device": "cpu",
                    "provider_root": _proteinmpnn_provider_root(),
            },
            workflow_nodes=(
                score_source,
                sequence_source,
                score_axis_resolver,
            ),
            workflow_edges=(
                WorkflowEdge(
                    "score-source",
                    "structure_candidates",
                    "sequence-source",
                    "structure_candidates",
                ),
                WorkflowEdge(
                    "score-source",
                    "structure_candidates",
                    "contract-test-node",
                    "structure_candidates",
                ),
                WorkflowEdge(
                    "sequence-source",
                    "sequence_candidates",
                    "contract-test-node",
                    "sequence_candidates",
                ),
                WorkflowEdge(
                    "score-source",
                    "structure_candidates",
                    "score-axis-resolver",
                    "structure_candidates",
                ),
                WorkflowEdge(
                    "score-axis-resolver",
                    "residue_axes",
                    "contract-test-node",
                    "structure_residue_axes",
                ),
            ),
            expected_observation_counts={"scores": 1},
            forbidden_public_fragments=("ctk-proteinmpnn-secret",),
        ),
    )

    report = verify_module_package_contract(
        PROTEINMPNN_PACKAGE,
        execution_cases=cases,
        port_cases=(
            ModulePackagePortCase(
                type_id="proteinmpnn.constraints",
                version="4.0.0",
                valid_value=ProteinMPNNConstraints(
                    layout=ResidueLayout("A", 1, ["A:1"]),
                    fixed_residue_ids=["A:1"],
                ),
                invalid_values=(object(),),
            ),
        ),
        supporting_registrations=(
            PROMPT_AUTHORING_PACKAGE,
            SOURCE_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        ),
        work_root=tmp_path / "ctk",
    )

    assert [case.status for case in report.case_reports] == [
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
    ]


def test_local_provider_reuses_one_resident_model_for_exact_operation_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.proteinmpnn.provider_runtime as provider_runtime

    constructed: list[object] = []

    def load_model(
        model_name: str,
        backbone_noise: float,
        provider_root: Path | None,
    ) -> tuple[object, object]:
        model = object()
        constructed.append(model)
        return model, (model_name, backbone_noise, provider_root)

    monkeypatch.setattr(provider_runtime, "_load_model", load_model)
    provider = provider_runtime._LocalProteinMPNNProvider(
        provider_root=tmp_path,
        temp_dir=tmp_path,
        model_cache={},
    )
    first = provider._resident_model("v_48_020", 0.0)
    second = provider._resident_model("v_48_020", 0.0)

    assert first is second
    assert len(constructed) == 1


def test_exact_score_seed_is_independent_of_resident_model_load_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import torch

    import modules.proteinmpnn.provider_request as provider_request
    import modules.proteinmpnn.provider_runtime as provider_runtime

    class Request:
        seed = 42
        model_name = "v_48_020"
        backbone_noise = 0.0

    def load_model(*_args: object) -> tuple[object, torch.device]:
        # The pinned model constructor consumes Torch randomness before its
        # checkpoint replaces the randomly initialized parameters.
        torch.randn(17)
        return object(), torch.device("cpu")

    def compute_score(*_args: object) -> float:
        return float(torch.randn(()))

    monkeypatch.setattr(provider_runtime, "_load_model", load_model)
    monkeypatch.setattr(provider_runtime, "_featurize", lambda *_args: {})
    monkeypatch.setattr(
        provider_request,
        "_sequence_in_provider_chain_order",
        lambda *_args: "A",
    )
    monkeypatch.setattr(provider_runtime, "_compute_score", compute_score)

    cold_provider = provider_runtime._LocalProteinMPNNProvider(
        provider_root=_proteinmpnn_provider_root(),
        temp_dir=tmp_path,
        model_cache={},
    )
    cold_score = cold_provider.score(Request(), ProteinSequence("A"))
    warm_provider = provider_runtime._LocalProteinMPNNProvider(
        provider_root=_proteinmpnn_provider_root(),
        temp_dir=tmp_path,
        model_cache={},
    )
    warm_provider._resident_model("v_48_020", 0.0)
    first_warm_score = warm_provider.score(Request(), ProteinSequence("A"))
    second_warm_score = warm_provider.score(Request(), ProteinSequence("A"))

    assert cold_score == first_warm_score == second_warm_score


def test_exact_design_seed_is_independent_of_resident_model_load_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import torch

    import modules.proteinmpnn.provider_runtime as provider_runtime

    class Request:
        seed = 1603
        model_name = "v_48_020"
        backbone_noise = 0.0
        reference_sequences = None
        num_sequences = 1
        temperature = 0.1
        omit_amino_acids = ["X"]

    def load_model(*_args: object) -> tuple[object, torch.device]:
        torch.randn(17)
        return object(), torch.device("cpu")

    def run_design(*_args: object) -> list[ProteinSequence]:
        symbol = "A" if float(torch.randn(())) < 0 else "G"
        return [ProteinSequence(symbol)]

    monkeypatch.setattr(provider_runtime, "_load_model", load_model)
    monkeypatch.setattr(provider_runtime, "_featurize", lambda *_args: {})
    monkeypatch.setattr(provider_runtime, "_run_design", run_design)

    cold_provider = provider_runtime._LocalProteinMPNNProvider(
        provider_root=_proteinmpnn_provider_root(),
        temp_dir=tmp_path,
        model_cache={},
    )
    cold_design = cold_provider.design(Request())
    warm_provider = provider_runtime._LocalProteinMPNNProvider(
        provider_root=_proteinmpnn_provider_root(),
        temp_dir=tmp_path,
        model_cache={},
    )
    warm_provider._resident_model("v_48_020", 0.0)
    first_warm_design = warm_provider.design(Request())
    second_warm_design = warm_provider.design(Request())

    assert cold_design == first_warm_design == second_warm_design
