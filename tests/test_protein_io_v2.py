"""Public v2 contracts for the cohesive protein I/O Module Package."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from core import (
    ArtifactPayload,
    BehaviorReference,
    CatalogBuildError,
    DefinitionResource,
    EnvironmentConfiguration,
    ModulePackageContractCase,
    ModulePackagePortCase,
    OperationCall,
    PortValueError,
    ProjectInputIntegrityError,
    ProjectManager,
    V2RunError,
    V2RunService,
    WorkflowAuthoringService,
    WorkflowAuthoringError,
    WorkflowDocument,
    WorkflowNodeInstance,
    build_discovered_frozen_catalog,
    build_frozen_catalog,
    discover_module_packages,
    verify_module_package_contract,
)
from core.parameter_contract import (
    ParameterContractDefinitionError,
    validate_parameter_declarations,
)
from core.workflow_v2 import WorkflowEdge
from datatypes import (
    Candidate,
    CandidateCollection,
    ProteinSequence,
    ProteinStructure,
)
from modules.protein_io.implementation import StructureExportImplementation
from modules.protein_io.package import MODULE_PACKAGE as PROTEIN_IO_PACKAGE
from tests.fixtures.protein_io_sources.package import (
    MODULE_PACKAGE as STRUCTURE_SOURCE_PACKAGE,
)


_SEQUENCE_SOURCE = WorkflowNodeInstance(
    node_id="source",
    node_type_id="contract_test.protein_sequence",
    node_type_version="3.0.0",
    binding_id="contract_test.protein_sequence.direct",
    binding_version="3.0.0",
    node_parameters={},
    binding_parameters={},
)
_STRUCTURE_SOURCE = WorkflowNodeInstance(
    node_id="source",
    node_type_id="contract_test.protein_structure",
    node_type_version="4.0.0",
    binding_id="contract_test.protein_structure.direct",
    binding_version="4.0.0",
    node_parameters={},
    binding_parameters={},
)
_CTK_CASES = (
    ModulePackageContractCase(
        case_id="protein-io-import-sequence",
        node_type_id="protein_io.import_sequence",
        node_type_version="5.0.0",
        binding_id="protein_io.import_sequence.direct",
        binding_version="5.0.0",
        node_parameters={"project_input_ref": "sequence-input"},
        binding_parameters={},
        environment_values={},
        safe_environment_fingerprint="protein-io-provider-free-v1",
        invalidation_token="protein-io-import-sequence-v1",
        project_inputs={"sequence-input": b">ctk\nACDEFG\n"},
    ),
    ModulePackageContractCase(
        case_id="protein-io-import-structure",
        node_type_id="protein_io.import_structure",
        node_type_version="5.0.0",
        binding_id="protein_io.import_structure.direct",
        binding_version="5.0.0",
        node_parameters={"project_input_ref": "structure-input"},
        binding_parameters={},
        environment_values={},
        safe_environment_fingerprint="protein-io-provider-free-v1",
        invalidation_token="protein-io-import-structure-v1",
        project_inputs={
            "structure-input": (
                b"ATOM      1  CA  GLY A   1       "
                b"1.000   2.000   3.000  1.00 20.00           C  \nEND\n"
            )
        },
    ),
    ModulePackageContractCase(
        case_id="protein-io-export-sequence",
        node_type_id="protein_io.export_sequence",
        node_type_version="3.0.0",
        binding_id="protein_io.export_sequence.direct",
        binding_version="3.0.0",
        node_parameters={},
        binding_parameters={},
        environment_values={},
        safe_environment_fingerprint="protein-io-provider-free-v1",
        invalidation_token="protein-io-export-sequence-v1",
        workflow_nodes=(_SEQUENCE_SOURCE,),
        workflow_edges=(
            WorkflowEdge(
                "source",
                "sequence",
                "contract-test-node",
                "sequence",
            ),
        ),
        expected_artifacts={
            "standalone_artifact": (
                b">protein-workbench-sequence\nACDEFG\n"
            )
        },
    ),
    ModulePackageContractCase(
        case_id="protein-io-export-structure",
        node_type_id="protein_io.export_structure",
        node_type_version="5.0.0",
        binding_id="protein_io.export_structure.direct",
        binding_version="5.0.0",
        node_parameters={},
        binding_parameters={},
        environment_values={},
        safe_environment_fingerprint="protein-io-provider-free-v1",
        invalidation_token="protein-io-export-structure-v1",
        workflow_nodes=(_STRUCTURE_SOURCE,),
        workflow_edges=(
            WorkflowEdge(
                "source",
                "structure",
                "contract-test-node",
                "structure",
            ),
        ),
        expected_artifacts={
            "standalone_artifact": (
                b"REMARK contract-test-provider-native\n"
                b"ATOM      1  CA  GLY A   1       "
                b"1.000   2.000   3.000  1.00 20.00           C  \n"
                b"END\n"
            )
        },
    ),
)
_CTK_PORT_CASE = ModulePackagePortCase(
    type_id="protein_io.artifact_payload",
    version="2.1.0",
    valid_value=ArtifactPayload(
        body=b">ctk\nACD\n",
        media_type="text/x-fasta",
        filename="ctk.fasta",
    ),
    invalid_values=(7,),
)


@pytest.mark.parametrize(
    "candidate_id",
    (
        "candidate:alpha",
        "candidate/alpha",
        "candidate+alpha",
    ),
)
def test_artifact_payload_preserves_an_admitted_candidate_identifier(
    candidate_id: str,
) -> None:
    artifact_port = build_frozen_catalog(
        (PROTEIN_IO_PACKAGE,)
    ).require_port_type("protein_io.artifact_payload", "2.1.0")
    payload = ArtifactPayload(
        body=b"END\n",
        media_type="chemical/x-pdb",
        filename="structure-0000.pdb",
        candidate_id=candidate_id,
    )

    assert artifact_port.decode(artifact_port.encode(payload)) == payload
    with pytest.raises(PortValueError, match="artifact metadata is invalid"):
        artifact_port.encode(
            replace(payload, filename=f"{candidate_id}.pdb")
        )


def test_candidate_artifact_filenames_are_deterministic_ordinal_components(
) -> None:
    class Resources:
        @staticmethod
        def engine_invocation():
            return nullcontext()

    structure = ProteinStructure(
        pdb_string=(
            "ATOM      1  CA  GLY A   1       "
            "1.000   2.000   3.000  1.00 20.00           C  \n"
            "END\n"
        )
    )
    candidates = CandidateCollection(
        collection_id="artifact-filename-contract",
        item_type="protein.structure",
        items=(
            Candidate("candidate:alpha", structure),
            Candidate("candidate/alpha", structure),
            Candidate("candidate+alpha", structure),
        ),
    )
    operation = StructureExportImplementation(Resources())  # type: ignore[arg-type]
    call = OperationCall(
        inputs={"structures": candidates},
        node_parameters={},
        binding_parameters={},
        input_content_digests={},
    )

    first = operation.execute(call)["candidate_artifacts"]
    second = operation.execute(call)["candidate_artifacts"]

    assert [artifact.filename for artifact in first] == [
        "structure-0000.pdb",
        "structure-0001.pdb",
        "structure-0002.pdb",
    ]
    assert len({artifact.filename for artifact in first}) == len(first)
    assert [artifact.candidate_id for artifact in first] == [
        "candidate:alpha",
        "candidate/alpha",
        "candidate+alpha",
    ]
    assert first == second


def test_protein_io_is_one_package_with_four_independent_nodes() -> None:
    registrations = {
        registration.package_id: registration
        for registration in discover_module_packages()
    }

    registration = registrations["protein_io"]
    assert registration.package_module == "modules.protein_io"
    assert {
        resource.resource for resource in registration.node_definitions
    } == {
        "definitions/sequence_import.yaml",
        "definitions/structure_import.yaml",
        "definitions/sequence_export.yaml",
        "definitions/structure_export.yaml",
    }

    catalog = build_discovered_frozen_catalog()
    owned_nodes = {
        (contract_id, version)
        for kind, contract_id, version in catalog.owners
        if kind == "node_type"
        and "protein_io" in catalog.owners[(kind, contract_id, version)]
    }
    assert owned_nodes == {
        ("protein_io.import_sequence", "5.0.0"),
        ("protein_io.import_structure", "5.0.0"),
        ("protein_io.export_sequence", "3.0.0"),
        ("protein_io.export_structure", "5.0.0"),
    }
    generations = {
        "import_sequence": ("5.0.0", ("2.1.0", "3.0.0", "4.0.0")),
        "import_structure": ("5.0.0", ("2.1.0", "3.0.0", "4.0.0")),
        "export_sequence": ("3.0.0", ("2.1.0",)),
        "export_structure": ("5.0.0", ("2.1.0", "3.0.0", "4.0.0")),
    }
    for operation, (active_version, inactive_versions) in generations.items():
        for kind, contract_id in (
            ("node_type", f"protein_io.{operation}"),
            ("binding", f"protein_io.{operation}.direct"),
        ):
            assert (
                catalog.get_contract(kind, contract_id, active_version)
                is not None
            )
            for inactive_version in inactive_versions:
                assert (
                    catalog.get_contract(kind, contract_id, inactive_version)
                    is None
                )
    assert catalog.get_contract(
        "method",
        "protein_io.import_sequence.method",
        "4.0.0",
    ) is not None
    assert catalog.get_contract(
        "method",
        "protein_io.import_sequence.method",
        "3.0.0",
    ) is None


def test_protein_io_passes_the_shared_contract_test_kit(
    tmp_path: Path,
) -> None:
    report = verify_module_package_contract(
        PROTEIN_IO_PACKAGE,
        execution_cases=_CTK_CASES,
        port_cases=(_CTK_PORT_CASE,),
        supporting_registrations=(STRUCTURE_SOURCE_PACKAGE,),
        work_root=tmp_path,
    )

    assert report.package_id == "protein_io"
    assert [case.status for case in report.case_reports] == [
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
    ]
    assert {
        port
        for case in report.case_reports
        for port in case.artifact_ports
    } == {"standalone_artifact"}


def test_artifact_output_requires_a_nominal_publication_contract() -> None:
    artifact_port = PROTEIN_IO_PACKAGE.port_types[0]
    malformed_port = replace(
        artifact_port,
        validator=BehaviorReference(
            "protein_io.artifact_payload/validate",
            "2.1.0",
            {"accepted_value_kind": "artifact_payload"},
        ),
    )
    malformed_package = replace(
        PROTEIN_IO_PACKAGE,
        port_types=(malformed_port,),
    )

    with pytest.raises(
        CatalogBuildError,
        match="generic artifact publication contract",
    ):
        build_frozen_catalog((malformed_package,))


def test_project_resource_parameters_must_be_required() -> None:
    with pytest.raises(
        ParameterContractDefinitionError,
        match="must be required",
    ):
        validate_parameter_declarations(
            {
                "project_input_ref": {
                    "parameter_scope": "scientific",
                    "scientific_meaning": "Optional Project input.",
                    "resource_kind": "project_input",
                    "value_contract": {"type": "string"},
                    "required": False,
                }
            },
            path="$.node_parameters",
        )


def test_artifact_media_contract_rejects_malformed_type_subtype() -> None:
    malformed_package = replace(
        PROTEIN_IO_PACKAGE,
        package_id="malformed-media",
        package_module="tests.fixtures.protein_io_sources",
        node_definitions=(
            DefinitionResource("malformed_media.yaml"),
        ),
        methods=(),
        bindings=(),
        port_types=(),
    )

    with pytest.raises(CatalogBuildError, match="artifact_media_type"):
        build_frozen_catalog((malformed_package,))


def test_structure_export_xor_is_rejected_during_commit(
    tmp_path: Path,
) -> None:
    catalog = build_frozen_catalog(
        (PROTEIN_IO_PACKAGE, STRUCTURE_SOURCE_PACKAGE)
    )
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create("missing structure input")
    authoring = WorkflowAuthoringService(projects, catalog)
    workflow = WorkflowDocument(
        schema_version="2.1.0",
        workflow_id=project.id,
        nodes=(
            WorkflowNodeInstance(
                node_id="export",
                node_type_id="protein_io.export_structure",
                node_type_version="5.0.0",
                binding_id="protein_io.export_structure.direct",
                binding_version="5.0.0",
                node_parameters={},
                binding_parameters={},
            ),
        ),
        edges=(),
        contract_lock=(),
    )

    with pytest.raises(WorkflowAuthoringError) as rejected:
        authoring.commit(
            project.id,
            expected_draft_revision=0,
            workflow=workflow,
        )

    assert rejected.value.code == "compile_rejected"
    assert (
        rejected.value.details["issues"][0]["code"]
        == "input_constraint_unsatisfied"
    )


def _run_single_node(
    tmp_path: Path,
    *,
    operation: str,
    node_parameters: dict[str, Any],
    project_inputs: dict[str, bytes] | None = None,
    project_input_filenames: dict[str, str] | None = None,
    catalog: Any | None = None,
) -> tuple[Any, V2RunService, dict[str, Any], tuple[dict[str, Any], ...]]:
    catalog = catalog or build_discovered_frozen_catalog()
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create(f"protein I/O {operation}")
    for reference, payload in (project_inputs or {}).items():
        projects.publish_input(
            project.id,
            reference,
            payload,
            filename=(project_input_filenames or {}).get(
                reference,
                f"{operation}.input",
            ),
        )
    authoring = WorkflowAuthoringService(projects, catalog)
    workflow = WorkflowDocument(
        schema_version="2.1.0",
        workflow_id=project.id,
        nodes=(
            WorkflowNodeInstance(
                node_id="protein-io",
                node_type_id=f"protein_io.{operation}",
                node_type_version={
                    "import_sequence": "5.0.0",
                    "import_structure": "5.0.0",
                    "export_sequence": "3.0.0",
                    "export_structure": "5.0.0",
                }[operation],
                binding_id=f"protein_io.{operation}.direct",
                binding_version={
                    "import_sequence": "5.0.0",
                    "import_structure": "5.0.0",
                    "export_sequence": "3.0.0",
                    "export_structure": "5.0.0",
                }[operation],
                node_parameters=node_parameters,
                binding_parameters={},
            ),
        ),
        edges=(),
        contract_lock=(),
    )
    committed = authoring.commit(
        project.id,
        expected_draft_revision=0,
        workflow=workflow,
    )
    compiled = authoring.require_compiled(
        project.id,
        workflow_commit_id=committed.workflow_commit_id,
    )
    assert (
        compiled.execution_plan.workflow_commit_revision
        == committed.workflow_commit_revision
    )
    service = V2RunService(
        projects,
        catalog,
        authoring,
        EnvironmentConfiguration({}),
    )
    receipt = service.start_background(
        project.id,
        workflow_commit_id=committed.workflow_commit_id,
        client_request_id=f"protein-io-{operation}",
    )
    service.shutdown()
    projection = service.projection(project.id, receipt["run_id"])
    events = service.public_events(project.id, receipt["run_id"])
    return (catalog, service, projection, events)


def test_sequence_import_reads_only_one_project_scoped_reference(
    tmp_path: Path,
) -> None:
    catalog, service, projection, events = _run_single_node(
        tmp_path,
        operation="import_sequence",
        node_parameters={"project_input_ref": "input-sequence-1"},
        project_inputs={
            "input-sequence-1": b">protein\r\nacD e\r\n",
        },
    )

    assert projection["status"] == "succeeded"
    output = next(
        item
        for item in projection["outputs"]
        if item["output_port"] == "sequence"
    )
    from tests.fixtures.public_v2 import decode_service_typed_output_value

    port_type = catalog.require_port_type("protein.sequence", "3.0.0")
    sequence = decode_service_typed_output_value(
        service,
        catalog,
        projection,
        output,
    )
    assert sequence == ProteinSequence(sequence="ACDE")
    assert output["content_digest"] == port_type.content_digest(sequence)
    candidate_output = next(
        item
        for item in projection["outputs"]
        if item["output_port"] == "sequence_candidates"
    )
    candidates = decode_service_typed_output_value(
        service,
        catalog,
        projection,
        candidate_output,
    )
    assert type(candidates) is CandidateCollection
    assert candidates.item_type == "protein.sequence"
    assert len(candidates.items) == 1
    assert candidates.items[0].data == sequence
    assert candidates.items[0].parent_ids == ()
    assert {
        event["event"]["type"] for event in events
    } >= {
        "engine_invocation_started",
        "engine_invocation_terminal",
    }
    assert not any(
        "input-sequence-1" in str(event.get("event"))
        for event in events
    )


def test_sequence_import_rejects_multi_fasta_instead_of_concatenating_records(
    tmp_path: Path,
) -> None:
    _, _, projection, _ = _run_single_node(
        tmp_path,
        operation="import_sequence",
        node_parameters={"project_input_ref": "multi-fasta"},
        project_inputs={
            "multi-fasta": b">first\nACD\n>second\nEFG\n",
        },
    )

    assert projection["status"] == "failed"
    assert projection["outputs"] == []


def test_project_input_identity_uses_content_not_opaque_locator(
    tmp_path: Path,
) -> None:
    _, _, first, first_events = _run_single_node(
        tmp_path / "first",
        operation="import_sequence",
        node_parameters={"project_input_ref": "first-reference"},
        project_inputs={"first-reference": b">protein\nACD\n"},
        project_input_filenames={"first-reference": "source-one.fasta"},
    )
    _, _, second, second_events = _run_single_node(
        tmp_path / "second",
        operation="import_sequence",
        node_parameters={"project_input_ref": "renamed-reference"},
        project_inputs={"renamed-reference": b">protein\nACD\n"},
        project_input_filenames={"renamed-reference": "renamed-source.fa"},
    )
    _, _, changed, _ = _run_single_node(
        tmp_path / "changed",
        operation="import_sequence",
        node_parameters={"project_input_ref": "renamed-reference"},
        project_inputs={"renamed-reference": b">protein\nACE\n"},
    )

    first_identity = first["outputs"][0]["result_identity"]
    second_identity = second["outputs"][0]["result_identity"]
    changed_identity = changed["outputs"][0]["result_identity"]
    assert first_identity == second_identity
    assert (
        second_identity
        != changed_identity
    )
    first_invocation = next(
        event["event"]
        for event in first_events
        if event["event"]["type"] == "engine_invocation_started"
    )
    second_invocation = next(
        event["event"]
        for event in second_events
        if event["event"]["type"] == "engine_invocation_started"
    )
    assert first_invocation["invocation_provenance"] == {
        "project_input_filename": "source-one.fasta"
    }
    assert second_invocation["invocation_provenance"] == {
        "project_input_filename": "renamed-source.fa"
    }


def test_cacheable_project_inputs_are_resolved_before_cache_identity(
    tmp_path: Path,
) -> None:
    cacheable_package = replace(
        PROTEIN_IO_PACKAGE,
        bindings=tuple(
            (
                replace(binding, cacheable=True)
                if binding.binding_id == "protein_io.import_sequence.direct"
                else binding
            )
            for binding in PROTEIN_IO_PACKAGE.bindings
        ),
    )
    catalog = build_frozen_catalog((cacheable_package,))
    _, _, first, _ = _run_single_node(
        tmp_path / "first",
        operation="import_sequence",
        node_parameters={"project_input_ref": "same-reference"},
        project_inputs={"same-reference": b">protein\nACD\n"},
        catalog=catalog,
    )
    _, _, second, _ = _run_single_node(
        tmp_path / "second",
        operation="import_sequence",
        node_parameters={"project_input_ref": "same-reference"},
        project_inputs={"same-reference": b">protein\nACE\n"},
        catalog=catalog,
    )

    assert (
        first["outputs"][0]["result_identity"]
        != second["outputs"][0]["result_identity"]
    )


def test_structure_import_parses_then_port_admits_canonical_project_pdb(
    tmp_path: Path,
) -> None:
    catalog, service, projection, _ = _run_single_node(
        tmp_path,
        operation="import_structure",
        node_parameters={"project_input_ref": "input-structure-1"},
        project_inputs={
            "input-structure-1": (
                b"ATOM      1  CA  GLY A   1       "
                b"1.000   2.000   3.000  1.00 20.00           C  \r\n"
                b"END\r\n"
            ),
        },
    )

    assert projection["status"] == "succeeded"
    output = projection["outputs"][0]
    port_type = catalog.require_port_type("protein.structure", "4.0.0")
    from tests.fixtures.public_v2 import decode_service_typed_output_value

    structure = decode_service_typed_output_value(
        service,
        catalog,
        projection,
        output,
    )
    assert structure == ProteinStructure(
        pdb_string=(
            "ATOM      1  CA  GLY A   1       "
            "1.000   2.000   3.000  1.00 20.00           C  \n"
            "END\n"
        ),
    )
    assert output["content_digest"] == port_type.content_digest(structure)


@pytest.mark.parametrize(
    ("operation", "payload"),
    (
        ("import_sequence", b">empty\n"),
        ("import_sequence", b">invalid\nACD?\n"),
        ("import_sequence", "mßa\n".encode("utf-8")),
        ("import_structure", b"HEADER no atoms\nEND\n"),
        (
            "import_structure",
            b"ATOM      X malformed coordinate record\nEND\n",
        ),
    ),
)
def test_import_port_admission_rejects_noncanonical_sequence_or_structure(
    tmp_path: Path,
    operation: str,
    payload: bytes,
) -> None:
    _, _, projection, events = _run_single_node(
        tmp_path,
        operation=operation,
        node_parameters={"project_input_ref": "malformed-input"},
        project_inputs={"malformed-input": payload},
    )

    assert projection["status"] == "failed"
    assert projection["outputs"] == []
    assert projection["artifact_index"] == []
    invocation_terminal = next(
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_terminal"
    )
    operation_terminal = next(
        event["event"]
        for event in events
        if event["event"]["type"] == "operation_attempt_terminal"
    )
    assert invocation_terminal["status"] == "succeeded"
    assert operation_terminal["status"] == "failed"
    assert not any(
        str(tmp_path) in str(event)
        or "malformed-input" in str(event.get("event"))
        for event in events
    )


def test_import_rejects_private_paths_and_cross_project_references(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        WorkflowAuthoringError,
        match="project_input_ref must match",
    ) as rejected:
        _run_single_node(
            tmp_path / "private-path",
            operation="import_sequence",
            node_parameters={
                "project_input_ref": "/private/host/sequence.fasta"
            },
        )
    assert rejected.value.code == "compile_rejected"

    _, _, projection, events = _run_single_node(
        tmp_path / "cross-project",
        operation="import_sequence",
        node_parameters={"project_input_ref": "belongs-to-another-project"},
    )
    assert projection["status"] == "failed"
    assert projection["outputs"] == []
    node_terminal = next(
        event["event"]
        for event in events
        if event["event"]["type"] == "node_attempt_terminal"
    )
    assert node_terminal["failure_origin"] == "operation"
    assert node_terminal["error"]["code"] == "node_execution_failed"
    assert any(
        event["event"]["type"] == "operation_attempt_terminal"
        and event["event"]["status"] == "failed"
        for event in events
    )


def test_project_input_snapshot_rejects_symlink_aliases(
    tmp_path: Path,
) -> None:
    projects = ProjectManager(tmp_path / "projects")
    project = projects.create("input symlink containment")
    projects.publish_input(
        project.id,
        "trusted-input",
        b">p\nACD\n",
        filename="trusted-input.fasta",
    )
    managed = projects.input_path(project.id, "trusted-input")
    managed.unlink()
    outside = tmp_path / "outside.fasta"
    outside.write_bytes(b">outside\nW\n")
    managed.symlink_to(outside)

    with pytest.raises(ProjectInputIntegrityError) as rejected:
        projects.read_input(project.id, "trusted-input")
    assert rejected.value.project_input_ref == "trusted-input"
