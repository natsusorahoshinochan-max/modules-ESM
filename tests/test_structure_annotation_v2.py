"""Public v2 contracts for the cohesive structure-annotation package."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from core import (
    EnvironmentConfiguration,
    ModulePackageContractCase,
    ModulePackagePortCase,
    OperationCall,
    ProjectManager,
    PortValueError,
    ResultReplaySource,
    V2RunError,
    V2RunService,
    WorkflowAuthoringService,
    WorkflowDocument,
    WorkflowNodeInstance,
    build_frozen_catalog,
    build_discovered_frozen_catalog,
    discover_module_packages,
    parse_workflow_document,
    verify_module_package_contract,
)
from core.port_types import canonical_json_bytes
from core.workflow_v2 import WorkflowEdge
from datatypes import ProteinStructure, ResidueLayout
from modules.protein_io.package import MODULE_PACKAGE as PROTEIN_IO_PACKAGE
from modules.structure_annotation import (
    DSSPAnnotation,
    StructureAnnotationTrack,
)
from modules.structure_annotation.implementation import DSSPComputeOperation
from modules.structure_annotation.package import (
    MODULE_PACKAGE as STRUCTURE_ANNOTATION_PACKAGE,
)


def test_structure_annotation_is_one_package_with_four_nodes() -> None:
    registrations = {
        registration.package_id: registration
        for registration in discover_module_packages()
    }

    registration = registrations["structure_annotation"]
    assert registration.package_module == "modules.structure_annotation"
    assert {
        resource.resource for resource in registration.node_definitions
    } == {
        "definitions/dssp_compute.yaml",
        "definitions/secondary_structure_extract.yaml",
        "definitions/sasa_compute.yaml",
        "definitions/secondary_structure_agreement.yaml",
    }

    catalog = build_discovered_frozen_catalog()
    owned_nodes = {
        (contract_id, version)
        for kind, contract_id, version in catalog.owners
        if kind == "node_type"
        and "structure_annotation"
        in catalog.owners[(kind, contract_id, version)]
    }
    assert owned_nodes == {
        ("structure_annotation.dssp_compute", "3.0.0"),
        ("structure_annotation.secondary_structure_extract", "2.1.0"),
        ("structure_annotation.sasa_compute", "2.1.0"),
        ("structure_annotation.secondary_structure_agreement", "2.1.0"),
    }


def test_structure_annotation_publishes_one_active_contract_generation() -> None:
    catalog = build_frozen_catalog((STRUCTURE_ANNOTATION_PACKAGE,))

    methods = {
        (contract.contract_id, contract.contract_version)
        for contract in catalog.contracts
        if contract.contract_kind == "method"
        and contract.contract_id.startswith("structure_annotation.")
    }
    assert methods == {
        ("structure_annotation.dssp_compute.method", "2.2.0"),
        (
            "structure_annotation.secondary_structure_extract.method",
            "2.2.0",
        ),
        ("structure_annotation.sasa_compute.method", "2.2.0"),
        (
            "structure_annotation.secondary_structure_agreement.method",
            "2.2.0",
        ),
    }

    bindings = {
        (contract.contract_id, contract.contract_version): contract
        for contract in catalog.contracts
        if contract.contract_kind == "binding"
        and contract.contract_id.startswith("structure_annotation.")
    }
    assert set(bindings) == {
        ("structure_annotation.dssp_compute.mkdssp_local", "3.0.0"),
        (
            "structure_annotation.secondary_structure_extract.direct",
            "2.2.0",
        ),
        ("structure_annotation.sasa_compute.direct", "2.2.0"),
        (
            "structure_annotation.secondary_structure_agreement.direct",
            "2.2.0",
        ),
    }
    for binding_id, binding in bindings.items():
        assert binding.descriptor["node_type"]["contract_version"] == (
            "3.0.0"
            if binding_id[0] == "structure_annotation.dssp_compute.mkdssp_local"
            else "2.1.0"
        )
        assert binding.descriptor["method"]["contract_version"] == "2.2.0"


def test_annotation_ports_preserve_multichain_layout_missing_and_ss8() -> None:
    catalog = build_discovered_frozen_catalog()
    layout = ResidueLayout(
        chain_id="A,B",
        length=4,
        residue_ids=["A:4", "A:6", "B:1", "B:2"],
    )
    annotation = DSSPAnnotation(
        layout=layout,
        secondary_structure=("G", "_", "C", "E"),
        sasa=(14.5, None, 0.0, 91.25),
    )
    annotation_type = catalog.require_port_type(
        "structure_annotation.dssp_annotations",
        "2.1.0",
    )
    secondary_type = catalog.require_port_type(
        "structure_annotation.secondary_structure_track",
        "2.1.0",
    )

    assert annotation_type.decode(annotation_type.encode(annotation)) == annotation
    track = StructureAnnotationTrack(
        layout=layout,
        values=annotation.secondary_structure,
    )
    assert secondary_type.decode(secondary_type.encode(track)) == track
    wire = json.loads(secondary_type.encode(track))["value"]
    assert wire["track"]["fields"]["values"] == ["G", "_", "C", "E"]

    with pytest.raises(PortValueError, match="unsupported alphabet"):
        secondary_type.encode(
            StructureAnnotationTrack(layout=layout, values=("H", "-", "E", "C"))
        )


def test_dssp_operation_crosses_one_canonical_only_adapter_interface() -> None:
    structure = ProteinStructure(
        "ATOM      1  CA  GLY A   1       "
        "1.000   2.000   3.000  1.00 20.00           C\n"
        "TER\nEND\n"
    )
    annotation = DSSPAnnotation(
        layout=ResidueLayout(
            chain_id="A",
            length=1,
            residue_ids=["A:1"],
        ),
        secondary_structure=("C",),
        sasa=(10.0,),
    )

    class RecordingAdapter:
        def __init__(self) -> None:
            self.structures: list[ProteinStructure] = []

        def annotate(self, value: ProteinStructure) -> DSSPAnnotation:
            self.structures.append(value)
            return annotation

    adapter = RecordingAdapter()
    operation = DSSPComputeOperation(adapter)
    output = operation.execute(
        OperationCall(
            inputs={"structure": structure},
            node_parameters={},
            binding_parameters={},
            input_content_digests={},
        )
    )

    assert adapter.structures == [structure]
    assert output == {"annotations": annotation}


def test_dssp_binary_is_binding_environment_not_workflow_parameter() -> None:
    catalog = build_frozen_catalog((STRUCTURE_ANNOTATION_PACKAGE,))
    node = catalog.require_contract(
        "node_type",
        "structure_annotation.dssp_compute",
        "3.0.0",
    )
    binding = catalog.require_contract(
        "binding",
        "structure_annotation.dssp_compute.mkdssp_local",
        "3.0.0",
    )

    assert node.descriptor["node_parameters"] == {}
    assert binding.descriptor["binding_parameters"] == {}
    assert binding.descriptor["execution_route"] == "adapter"
    assert binding.descriptor["route_behavior"] == {
        "behavior_id": "structure_annotation.mkdssp_local/adapter",
        "behavior_version": "2.1.0",
        "parameters": {
            "binary": "mkdssp",
            "binary_version": "4.6.1",
            "provider_contract": "PDB-REDO/dssp@v4.6.1",
            "request_format": "PDB-v3.3-fixed-columns",
            "residue_reconciliation": "chain-residue-name-CA-coordinate",
            "response_format": "mkdssp-4.6.1-mmCIF",
            "source_archive_sha256": (
                "5ddb8274f03ac0338adffcd661989f515fffb95d40afca404cf2677024256ae3"
            ),
        },
    }
    provider_identity = binding.descriptor["implementation_identity"][
        "provider_identity"
    ]
    assert provider_identity == {
        "repository": "PDB-REDO/dssp",
        "source_revision": "v4.6.1",
        "source_archive_sha256": (
            "5ddb8274f03ac0338adffcd661989f515fffb95d40afca404cf2677024256ae3"
        ),
        "binary": "mkdssp",
        "binary_version": "4.6.1",
    }
    method_reference = binding.descriptor["method"]
    method = catalog.require_contract(
        method_reference["contract_kind"],
        method_reference["contract_id"],
        method_reference["contract_version"],
    )
    assert method.descriptor["source_identity"] == provider_identity
    prerequisites = binding.descriptor["readiness_declaration"][
        "prerequisites"
    ]
    assert prerequisites["binary"] == {
        "name": "mkdssp",
        "path_source": "trusted_environment_configuration",
        "required_version": "4.6.1",
    }
    assert binding.descriptor["availability_declaration"][
        "prerequisites"
    ] == {
        "binary_configuration": {
            "name": "mkdssp",
            "path_source": "trusted_environment_configuration",
        }
    }
    published = binding.descriptor_bytes.decode("utf-8")
    assert "dssp_binary" not in published
    assert "/opt/" not in published


def test_only_mkdssp_compute_crosses_an_adapter_route() -> None:
    catalog = build_frozen_catalog((STRUCTURE_ANNOTATION_PACKAGE,))
    bindings = {
        contract.contract_id: contract
        for contract in catalog.contracts
        if contract.contract_kind == "binding"
        and contract.contract_id.startswith("structure_annotation.")
    }

    assert set(bindings) == {
        "structure_annotation.dssp_compute.mkdssp_local",
        "structure_annotation.secondary_structure_extract.direct",
        "structure_annotation.sasa_compute.direct",
        "structure_annotation.secondary_structure_agreement.direct",
    }
    assert bindings[
        "structure_annotation.dssp_compute.mkdssp_local"
    ].descriptor["execution_route"] == "adapter"
    for binding_id in (
        "structure_annotation.secondary_structure_extract.direct",
        "structure_annotation.sasa_compute.direct",
        "structure_annotation.secondary_structure_agreement.direct",
    ):
        descriptor = bindings[binding_id].descriptor
        assert descriptor["execution_route"] == "direct"
        assert "adapter" not in descriptor["implementation_identity"]


def _fake_dssp_binary(
    path: Path,
    *,
    output: str | None,
    exit_code: int = 0,
    version: str = "4.6.1",
) -> Path:
    binary = path / "mkdssp-fixture"
    output_command = (
        "printf '\\377'\n"
        if output is None
        else "cat <<'DSSP_OUTPUT'\n" + output + "DSSP_OUTPUT\n"
    )
    binary.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"--version\" ]; then\n"
        f"  printf '%s\\n' 'mkdssp version {version}'\n"
        "  exit 0\n"
        "fi\n"
        f"{output_command}"
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    binary.chmod(0o755)
    return binary


def _decode_output(
    catalog: Any,
    output: dict[str, Any],
) -> Any:
    reference = output["port_type"]
    port_type = catalog.require_port_type(
        reference["contract_id"],
        reference["contract_version"],
    )
    return port_type.decode(
        canonical_json_bytes(
            {
                "schema_namespace": "protein-workbench-port-value/v2",
                "port_type_id": port_type.type_id,
                "port_type_version": port_type.version,
                "value": output["values"][0],
            }
        )
    )


def _run_dssp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    pdb_text: str,
    dssp_output: str | None,
    configured_binary: str | None = None,
    result_replay_source: ResultReplaySource | None = None,
    binary_version: str = "4.6.1",
) -> tuple[Any, dict[str, Any], tuple[dict[str, Any], ...], str]:
    binary = _fake_dssp_binary(
        tmp_path,
        output=dssp_output,
        version=binary_version,
    )
    catalog = build_frozen_catalog(
        (PROTEIN_IO_PACKAGE, STRUCTURE_ANNOTATION_PACKAGE)
    )
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create("structure annotation DSSP")
    projects.publish_input(
        project.id,
        "structure-input",
        pdb_text.encode("ascii"),
    )
    authoring = WorkflowAuthoringService(projects, catalog)
    workflow = WorkflowDocument(
        schema_version="2.1.0",
        workflow_id=project.id,
        nodes=(
            WorkflowNodeInstance(
                node_id="import",
                node_type_id="protein_io.import_structure",
                node_type_version="3.0.0",
                binding_id="protein_io.import_structure.direct",
                binding_version="3.0.0",
                node_parameters={"project_input_ref": "structure-input"},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="annotate",
                node_type_id="structure_annotation.dssp_compute",
                node_type_version="3.0.0",
                binding_id="structure_annotation.dssp_compute.mkdssp_local",
                binding_version="3.0.0",
                node_parameters={},
                binding_parameters={},
            ),
        ),
        edges=(
            WorkflowEdge("import", "structure", "annotate", "structure"),
        ),
        contract_lock=(),
    )
    saved = authoring.save(
        project.id,
        expected_workflow_revision=0,
        workflow=workflow,
    )
    relocked = authoring.relock(
        project.id,
        workflow_revision=saved["workflow_revision"],
    )
    compiled = authoring.compile(
        project.id,
        workflow_revision=relocked["workflow_revision"],
        workflow=parse_workflow_document(relocked["workflow"]),
    )
    service = V2RunService(
        projects,
        catalog,
        authoring,
        EnvironmentConfiguration(
            {
                (
                    "structure_annotation.dssp_compute.mkdssp_local",
                    "3.0.0",
                ): {
                    "values": {
                        "dssp_binary": configured_binary or str(binary)
                    },
                    "safe_fingerprint": "mkdssp-fixture-4.6.1",
                    "invalidation_token": "mkdssp-fixture-4.6.1",
                }
            }
        ),
        result_replay_source,
    )
    try:
        receipt = service.start_background(
            project.id,
            workflow_revision=relocked["workflow_revision"],
            compile_id=compiled.public_receipt()["compile_id"],
            client_request_id="structure-annotation-dssp",
        )
    except BaseException:
        service.shutdown()
        raise
    service.shutdown()
    projection = service.projection(project.id, receipt["run_id"])
    events = service.public_events(project.id, receipt["run_id"])
    return catalog, projection, events, str(binary)


def test_dssp_compute_reconciles_layout_shift_multichain_and_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdb_text = (
        "ATOM      1  CA  GLY A   4       1.000   2.000   3.000  1.00 20.00           C\n"
        "ATOM      2  CA  ALA A   6       2.000   3.000   4.000  1.00 20.00           C\n"
        "TER\n"
        "ATOM      3  CA  SER B   1       3.000   4.000   5.000  1.00 20.00           C\n"
        "ATOM      4  CA  THR B   2       4.000   5.000   6.000  1.00 20.00           C\n"
        "TER\nEND\n"
    )
    dssp_output = """\
data_fixture
loop_
_dssp_struct_summary.entry_id
_dssp_struct_summary.label_asym_id
_dssp_struct_summary.label_seq_id
_dssp_struct_summary.label_comp_id
_dssp_struct_summary.secondary_structure
_dssp_struct_summary.accessibility
_dssp_struct_summary.x_ca
_dssp_struct_summary.y_ca
_dssp_struct_summary.z_ca
fixture A 1 GLY H 10.5 1.0 2.0 3.0
fixture B 1 SER . 20.0 3.0 4.0 5.0
fixture B 2 THR G . 4.0 5.0 6.0
#
"""

    catalog, projection, events, private_path = _run_dssp(
        tmp_path,
        monkeypatch,
        pdb_text=pdb_text,
        dssp_output=dssp_output,
    )

    assert projection["status"] == "succeeded"
    output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "annotate"
    )
    annotation = _decode_output(catalog, output)
    assert annotation == DSSPAnnotation(
        layout=ResidueLayout(
            chain_id="A,B",
            length=4,
            residue_ids=["A:4", "A:6", "B:1", "B:2"],
        ),
        secondary_structure=("H", "_", "C", "G"),
        sasa=(10.5, None, 20.0, None),
    )
    event_types = [event["event"]["type"] for event in events]
    assert event_types.count("engine_invocation_started") == 2
    assert event_types.count("engine_invocation_terminal") == 2
    assert private_path not in json.dumps(
        {"projection": projection, "events": events},
        sort_keys=True,
    )


def test_environment_only_binary_path_is_available_and_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, projection, _, _ = _run_dssp(
        tmp_path,
        monkeypatch,
        pdb_text=(
            "ATOM      1  CA  GLY A   1       "
            "1.000   2.000   3.000  1.00 20.00           C\n"
            "TER\nEND\n"
        ),
        dssp_output="""\
data_fixture
loop_
_dssp_struct_summary.entry_id
_dssp_struct_summary.label_asym_id
_dssp_struct_summary.label_seq_id
_dssp_struct_summary.label_comp_id
_dssp_struct_summary.secondary_structure
_dssp_struct_summary.accessibility
_dssp_struct_summary.x_ca
_dssp_struct_summary.y_ca
_dssp_struct_summary.z_ca
fixture A 1 GLY H 10.0 1.0 2.0 3.0
#
""",
    )

    assert projection["status"] == "succeeded"


def test_dssp_dot_is_coil_and_p_is_preserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog, projection, _, _ = _run_dssp(
        tmp_path,
        monkeypatch,
        pdb_text=(
            "ATOM      1  CA  GLY A   1       "
            "1.000   2.000   3.000  1.00 20.00           C\n"
            "ATOM      2  CA  ALA A   2       "
            "2.000   3.000   4.000  1.00 20.00           C\n"
            "TER\nEND\n"
        ),
        dssp_output="""\
data_fixture
loop_
_dssp_struct_summary.entry_id
_dssp_struct_summary.label_asym_id
_dssp_struct_summary.label_seq_id
_dssp_struct_summary.label_comp_id
_dssp_struct_summary.secondary_structure
_dssp_struct_summary.accessibility
_dssp_struct_summary.x_ca
_dssp_struct_summary.y_ca
_dssp_struct_summary.z_ca
fixture A 17 GLY . 10.0 1.0 2.0 3.0
fixture A 29 ALA P 20.0 2.0 3.0 4.0
#
""",
    )

    assert projection["status"] == "succeeded"
    output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "annotate"
    )
    annotation = _decode_output(catalog, output)
    assert annotation.secondary_structure == ("C", "P")


def test_dssp_readiness_rejects_version_prefix_collision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = type(
        "LookupRecorder",
        (ResultReplaySource,),
        {
            "lookups": 0,
            "lookup": lambda self, **kwargs: setattr(
                self,
                "lookups",
                self.lookups + 1,
            ),
        },
    )()

    with pytest.raises(V2RunError) as rejected:
        _run_dssp(
            tmp_path,
            monkeypatch,
            pdb_text=(
                "ATOM      1  CA  GLY A   1       "
                "1.000   2.000   3.000  1.00 20.00           C\n"
                "TER\nEND\n"
            ),
            dssp_output="unused\n",
            binary_version="4.6.10",
            result_replay_source=cache,
        )

    assert rejected.value.code == "readiness_rejected"
    assert cache.lookups == 0


@pytest.mark.parametrize(
    "dssp_output",
    (
        None,
        "this is not a DSSP mmCIF document\n",
        """\
data_fixture
loop_
_dssp_struct_summary.entry_id
_dssp_struct_summary.label_asym_id
_dssp_struct_summary.label_seq_id
_dssp_struct_summary.label_comp_id
_dssp_struct_summary.secondary_structure
_dssp_struct_summary.accessibility
_dssp_struct_summary.x_ca
_dssp_struct_summary.y_ca
_dssp_struct_summary.z_ca
fixture Z 1 GLY H 10.0 1.0 2.0 3.0
#
""",
        """\
data_fixture
loop_
_dssp_struct_summary.entry_id
_dssp_struct_summary.label_asym_id
_dssp_struct_summary.label_seq_id
_dssp_struct_summary.label_comp_id
_dssp_struct_summary.secondary_structure
_dssp_struct_summary.accessibility
_dssp_struct_summary.x_ca
_dssp_struct_summary.y_ca
_dssp_struct_summary.z_ca
fixture A 1 ALA H 10.0 1.0 2.0 3.0
#
""",
    ),
)
def test_dssp_parse_or_postprocess_failure_fails_after_truthful_invocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dssp_output: str | None,
) -> None:
    _, projection, events, _ = _run_dssp(
        tmp_path,
        monkeypatch,
        pdb_text=(
            "ATOM      1  CA  GLY A   1       "
            "1.000   2.000   3.000  1.00 20.00           C\n"
            "TER\nEND\n"
        ),
        dssp_output=dssp_output,
    )

    assert projection["status"] == "failed"
    assert not any(
        output["node_id"] == "annotate"
        for output in projection["outputs"]
    )
    public_facts = [event["event"] for event in events]
    annotate_node_attempt = next(
        event["node_attempt_id"]
        for event in public_facts
        if event["type"] == "node_attempt_started"
        and event["node_id"] == "annotate"
    )
    annotate_operation = next(
        event["operation_attempt_id"]
        for event in public_facts
        if event["type"] == "operation_attempt_started"
        and event["node_attempt_id"] == annotate_node_attempt
    )
    annotate_invocation_ids = {
        event["invocation_id"]
        for event in public_facts
        if event["type"] == "engine_invocation_started"
        and event["operation_attempt_id"] == annotate_operation
    }
    annotate_invocations = [
        event
        for event in public_facts
        if event["type"] == "engine_invocation_terminal"
        and event["invocation_id"] in annotate_invocation_ids
    ]
    assert [event["status"] for event in annotate_invocations] == [
        "succeeded"
    ]
    annotate_operations = [
        event
        for event in public_facts
        if event["type"] == "operation_attempt_terminal"
        and event["operation_attempt_id"] == annotate_operation
    ]
    assert [event["status"] for event in annotate_operations] == ["failed"]


def test_unready_dssp_rejects_before_cache_lookup_or_invocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class LookupRecorder(ResultReplaySource):
        def __init__(self) -> None:
            self.lookups = 0

        def lookup(self, **kwargs: Any) -> None:
            del kwargs
            self.lookups += 1
            return None

    cache = LookupRecorder()
    with pytest.raises(V2RunError) as rejected:
        _run_dssp(
            tmp_path,
            monkeypatch,
            pdb_text=(
                "ATOM      1  CA  GLY A   1       "
                "1.000   2.000   3.000  1.00 20.00           C\n"
                "TER\nEND\n"
            ),
            dssp_output="unused\n",
            configured_binary=str(tmp_path / "missing-mkdssp"),
            result_replay_source=cache,
        )

    assert rejected.value.code == "readiness_rejected"
    assert cache.lookups == 0


def test_structure_annotation_passes_ctk_for_all_four_nodes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.fixtures.structure_annotation_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    dssp_output = """\
data_fixture
loop_
_dssp_struct_summary.entry_id
_dssp_struct_summary.label_asym_id
_dssp_struct_summary.label_seq_id
_dssp_struct_summary.label_comp_id
_dssp_struct_summary.secondary_structure
_dssp_struct_summary.accessibility
_dssp_struct_summary.x_ca
_dssp_struct_summary.y_ca
_dssp_struct_summary.z_ca
fixture A 1 GLY H 10.0 1.0 2.0 3.0
fixture A 2 ALA . 20.0 2.0 3.0 4.0
#
"""
    binary = _fake_dssp_binary(tmp_path, output=dssp_output)
    source = WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.structure_annotation_source",
        node_type_version="3.0.0",
        binding_id="contract_test.structure_annotation_source.direct",
        binding_version="3.0.0",
        node_parameters={},
        binding_parameters={},
    )
    cases = (
        ModulePackageContractCase(
            case_id="structure-annotation-dssp",
            node_type_id="structure_annotation.dssp_compute",
            node_type_version="3.0.0",
            binding_id="structure_annotation.dssp_compute.mkdssp_local",
            binding_version="3.0.0",
            node_parameters={},
            binding_parameters={},
            environment_values={"dssp_binary": str(binary)},
            safe_environment_fingerprint="mkdssp-fixture-4.6.1",
            invalidation_token="mkdssp-fixture-4.6.1",
            workflow_nodes=(source,),
            workflow_edges=(
                WorkflowEdge(
                    "source",
                    "structure",
                    "contract-test-node",
                    "structure",
                ),
            ),
            forbidden_public_fragments=(str(binary),),
        ),
        ModulePackageContractCase(
            case_id="structure-annotation-secondary",
            node_type_id="structure_annotation.secondary_structure_extract",
            node_type_version="2.1.0",
            binding_id=(
                "structure_annotation.secondary_structure_extract.direct"
            ),
            binding_version="2.2.0",
            node_parameters={},
            binding_parameters={},
            environment_values={},
            safe_environment_fingerprint="provider-free",
            invalidation_token="provider-free",
            workflow_nodes=(source,),
            workflow_edges=(
                WorkflowEdge(
                    "source",
                    "annotations",
                    "contract-test-node",
                    "annotations",
                ),
            ),
        ),
        ModulePackageContractCase(
            case_id="structure-annotation-sasa",
            node_type_id="structure_annotation.sasa_compute",
            node_type_version="2.1.0",
            binding_id="structure_annotation.sasa_compute.direct",
            binding_version="2.2.0",
            node_parameters={},
            binding_parameters={},
            environment_values={},
            safe_environment_fingerprint="provider-free",
            invalidation_token="provider-free",
            workflow_nodes=(source,),
            workflow_edges=(
                WorkflowEdge(
                    "source",
                    "annotations",
                    "contract-test-node",
                    "annotations",
                ),
            ),
        ),
        ModulePackageContractCase(
            case_id="structure-annotation-agreement",
            node_type_id=(
                "structure_annotation.secondary_structure_agreement"
            ),
            node_type_version="2.1.0",
            binding_id=(
                "structure_annotation.secondary_structure_agreement.direct"
            ),
            binding_version="2.2.0",
            node_parameters={},
            binding_parameters={},
            environment_values={},
            safe_environment_fingerprint="provider-free",
            invalidation_token="provider-free",
            workflow_nodes=(source,),
            workflow_edges=(
                WorkflowEdge(
                    "source",
                    "subjects",
                    "contract-test-node",
                    "subjects",
                ),
                WorkflowEdge(
                    "source",
                    "references",
                    "contract-test-node",
                    "references",
                ),
                WorkflowEdge(
                    "source",
                    "expected",
                    "contract-test-node",
                    "expected",
                ),
                WorkflowEdge(
                    "source",
                    "observed",
                    "contract-test-node",
                    "observed",
                ),
            ),
            expected_observation_counts={"scores": 1},
        ),
    )
    layout = ResidueLayout(
        chain_id="A",
        length=2,
        residue_ids=["A:1", "A:2"],
    )
    port_cases = (
        ModulePackagePortCase(
            type_id="structure_annotation.dssp_annotations",
            version="2.1.0",
            valid_value=DSSPAnnotation(
                layout=layout,
                secondary_structure=("H", "C"),
                sasa=(10.0, None),
            ),
            invalid_values=(7,),
        ),
        ModulePackagePortCase(
            type_id="structure_annotation.secondary_structure_track",
            version="2.1.0",
            valid_value=StructureAnnotationTrack(
                layout=layout,
                values=("H", "_"),
            ),
            invalid_values=(7,),
        ),
        ModulePackagePortCase(
            type_id="structure_annotation.sasa_track",
            version="2.1.0",
            valid_value=StructureAnnotationTrack(
                layout=layout,
                values=(10.0, None),
            ),
            invalid_values=(7,),
        ),
    )

    report = verify_module_package_contract(
        STRUCTURE_ANNOTATION_PACKAGE,
        execution_cases=cases,
        port_cases=port_cases,
        supporting_registrations=(SOURCE_PACKAGE,),
        work_root=tmp_path / "ctk",
    )

    assert [case.status for case in report.case_reports] == [
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
    ]


def test_agreement_emits_one_exact_subject_metric_method_observation(
    tmp_path: Path,
) -> None:
    from tests.fixtures.structure_annotation_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    catalog = build_frozen_catalog(
        (STRUCTURE_ANNOTATION_PACKAGE, SOURCE_PACKAGE)
    )
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create("structure annotation agreement")
    authoring = WorkflowAuthoringService(projects, catalog)
    workflow = WorkflowDocument(
        schema_version="2.1.0",
        workflow_id=project.id,
        nodes=(
            WorkflowNodeInstance(
                node_id="source",
                node_type_id="contract_test.structure_annotation_source",
                node_type_version="3.0.0",
                binding_id=(
                    "contract_test.structure_annotation_source.direct"
                ),
                binding_version="3.0.0",
                node_parameters={},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="agreement",
                node_type_id=(
                    "structure_annotation.secondary_structure_agreement"
                ),
                node_type_version="2.1.0",
                binding_id=(
                    "structure_annotation."
                    "secondary_structure_agreement.direct"
                ),
                binding_version="2.2.0",
                node_parameters={},
                binding_parameters={},
            ),
        ),
        edges=(
            WorkflowEdge("source", "subjects", "agreement", "subjects"),
            WorkflowEdge("source", "references", "agreement", "references"),
            WorkflowEdge("source", "expected", "agreement", "expected"),
            WorkflowEdge("source", "observed", "agreement", "observed"),
        ),
        contract_lock=(),
    )
    saved = authoring.save(
        project.id,
        expected_workflow_revision=0,
        workflow=workflow,
    )
    relocked = authoring.relock(
        project.id,
        workflow_revision=saved["workflow_revision"],
    )
    compiled = authoring.compile(
        project.id,
        workflow_revision=relocked["workflow_revision"],
        workflow=parse_workflow_document(relocked["workflow"]),
    )
    service = V2RunService(
        projects,
        catalog,
        authoring,
        EnvironmentConfiguration({}),
    )
    receipt = service.start(
        project.id,
        workflow_revision=relocked["workflow_revision"],
        compile_id=compiled.public_receipt()["compile_id"],
        client_request_id="structure-annotation-agreement",
    )
    projection = service.projection(project.id, receipt["run_id"])
    service.shutdown()

    subject_output = next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "source"
        and output["output_port"] == "subjects"
    )
    reference_output = next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "source"
        and output["output_port"] == "references"
    )
    score_output = next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "agreement"
    )
    subjects = _decode_output(catalog, subject_output)
    references = _decode_output(catalog, reference_output)
    scores = _decode_output(catalog, score_output)
    assert len(subjects.items) == 1
    assert len(scores.entries) == 1
    observation = scores.entries[0]
    assert observation.candidate_id == subjects.items[0].candidate_id
    assert observation.metric.contract_id == (
        "structure_annotation.secondary_structure_agreement"
    )
    assert observation.method.contract_id == (
        "structure_annotation.secondary_structure_agreement.method"
    )
    assert observation.context.to_public() == {
        "kind": "pairwise",
        "subject": {
            "role": "subject",
            "candidate_id": subjects.items[0].candidate_id,
            "content_digest": catalog.require_port_type(
                subjects.item_type,
                "3.0.0",
            ).content_digest(subjects.items[0].data),
        },
        "reference": {
            "role": "reference",
            "candidate_id": references.items[0].candidate_id,
            "content_digest": catalog.require_port_type(
                references.item_type,
                "3.0.0",
            ).content_digest(references.items[0].data),
        },
        "pairing_mode": "fixed_reference",
        "normalization": "exact-SS8-present-residue",
    }
    assert observation.value == 0.5
