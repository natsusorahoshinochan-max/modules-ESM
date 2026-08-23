"""Shared deterministic ESM-3 generation test harness."""

from __future__ import annotations

from tests.support.ledger import public_run_events, public_run_projection

from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

from core.project.manager import ProjectManager
from core.catalog.builder import (
    build_frozen_catalog,
)
from core.catalog.model import (
    FrozenCatalog,
)
from core.execution.environment import admit_environment_configuration
from core.execution.node_attempt import NodeAttemptFactory
from core.execution.runtime import (
    V2RunService,
)
from tests.support.result_store import result_store
from core.workflow.authoring import WorkflowAuthoringService
from core.workflow.document import (
    WorkflowDocument,
    WorkflowNodeInstance,
)
from core.workflow.document import WorkflowEdge
from tests.fixtures.public_v2 import decode_service_typed_output_value


class ProviderResponse:
    def __init__(
        self,
        sequence: str,
        *,
        coordinates: Any = None,
        ptm: Any = None,
        plddt: Any = None,
        pae: Any = None,
        pdb_string: str | None = None,
    ) -> None:
        self.sequence = sequence
        self.coordinates = coordinates
        self.ptm = ptm
        self.plddt = plddt
        self.pae = pae
        self._pdb_string = pdb_string

    def to_pdb_string(self) -> str:
        if self._pdb_string is None:
            raise AssertionError("coordinate-free fixture cannot render a PDB")
        return self._pdb_string


class ProviderClient:
    def __init__(self, responses: list[ProviderResponse]) -> None:
        self._responses = iter(responses)
        self.calls: list[tuple[Any, Any]] = []

    def generate(self, protein: Any, config: Any) -> ProviderResponse:
        self.calls.append((protein, config))
        return next(self._responses)


@contextmanager
def _installed_test_client(binding_route: str, client: Any | None):
    with ExitStack() as stack:
        if client is not None:
            targets = (
                (
                    ("modules.esm3.local_adapter.load_local_esm3_client", client),
                    ("modules.esm3.local_adapter.release_local_esm3_client", None),
                )
                if binding_route == "local_open"
                else (("modules.esm3.adapter.build_biohub_esm3_client", client),)
            )
            for target, return_value in targets:
                stack.enter_context(patch(target, return_value=return_value))
        yield


def generation_catalog(*, include_protein_io: bool) -> FrozenCatalog:
    from modules.esm3.package import MODULE_PACKAGE as ESM3_PACKAGE
    from modules.prompt_authoring.package import (
        MODULE_PACKAGE as PROMPT_AUTHORING_PACKAGE,
    )
    from modules.protein_io.package import MODULE_PACKAGE as PROTEIN_IO_PACKAGE
    from modules.structure_prediction.package import (
        MODULE_PACKAGE as STRUCTURE_PREDICTION_PACKAGE,
    )
    from modules.structure_transform.package import (
        MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
    )

    packages = [
        ESM3_PACKAGE,
        PROMPT_AUTHORING_PACKAGE,
        STRUCTURE_PREDICTION_PACKAGE,
        STRUCTURE_TRANSFORM_PACKAGE,
    ]
    if include_protein_io:
        packages.append(PROTEIN_IO_PACKAGE)
    return build_frozen_catalog(tuple(packages))


def decode_output(
    service: Any,
    catalog: Any,
    projection: dict[str, Any],
    output: dict[str, Any],
) -> Any:
    return decode_service_typed_output_value(
        service,
        catalog,
        projection,
        output,
    )


def run_generation(
    tmp_path: Path,
    *,
    operation: str,
    client: Any | None,
    num_samples: int,
    sequence: str | None = None,
    environment_overrides: dict[str, Any] | None = None,
    generation_parameters: dict[str, Any] | None = None,
    binding_route: str = "biohub_medium",
    sequence_mask_residue_ids: tuple[str, ...] = (),
    materialize_confidence: bool = False,
    catalog: FrozenCatalog | None = None,
) -> tuple[Any, Any, dict[str, Any], tuple[dict[str, Any], ...]]:
    nodes = [
        WorkflowNodeInstance(
            node_id="layout",
            node_type_id="prompt_authoring.build_residue_layout",
            node_type_version="3.0.0",
            binding_id="prompt_authoring.build_residue_layout.direct",
            binding_version="3.0.0",
            node_parameters={
                "chains": [
                    {
                        "chain_id": "A",
                        "length": len(sequence) if sequence is not None else 3,
                    }
                ]
            },
            binding_parameters={},
        ),
        WorkflowNodeInstance(
            node_id="assemble",
            node_type_id="prompt_authoring.assemble_protein_prompt",
            node_type_version="3.0.0",
            binding_id="prompt_authoring.assemble_protein_prompt.direct",
            binding_version="3.0.0",
            node_parameters={},
            binding_parameters={},
        ),
    ]
    edges = [
        WorkflowEdge("layout", "layout", "assemble", "layout"),
    ]
    project_inputs: dict[str, bytes] = {}
    prompt_source = "assemble"
    if sequence is not None:
        project_inputs["sequence-input"] = f">fixture\n{sequence}\n".encode()
        nodes.extend(
            [
                WorkflowNodeInstance(
                    node_id="import_sequence",
                    node_type_id="protein_io.import_sequence",
                    node_type_version="6.0.0",
                    binding_id="protein_io.import_sequence.direct",
                    binding_version="6.0.0",
                    node_parameters={"project_input_ref": "sequence-input"},
                    binding_parameters={},
                ),
                WorkflowNodeInstance(
                    node_id="update_sequence",
                    node_type_id="prompt_authoring.update_prompt_sequence",
                    node_type_version="3.0.0",
                    binding_id="prompt_authoring.update_prompt_sequence.direct",
                    binding_version="3.0.0",
                    node_parameters={},
                    binding_parameters={},
                ),
            ]
        )
        edges.extend(
            [
                WorkflowEdge(
                    "assemble",
                    "protein_prompt",
                    "update_sequence",
                    "protein_prompt",
                ),
                WorkflowEdge(
                    "import_sequence",
                    "sequence",
                    "update_sequence",
                    "sequence",
                ),
            ]
        )
        prompt_source = "update_sequence"
        if sequence_mask_residue_ids:
            nodes.append(
                WorkflowNodeInstance(
                    node_id="mask_sequence",
                    node_type_id="prompt_authoring.random_mask",
                    node_type_version="3.0.0",
                    binding_id="prompt_authoring.random_mask.direct",
                    binding_version="3.0.0",
                    node_parameters={
                        "effective_seed": 1603,
                        "count": len(sequence_mask_residue_ids),
                        "track": "sequence",
                        "eligible_residue_ids": list(
                            sequence_mask_residue_ids
                        ),
                    },
                    binding_parameters={},
                )
            )
            edges.append(
                WorkflowEdge(
                    "update_sequence",
                    "protein_prompt",
                    "mask_sequence",
                    "protein_prompt",
                )
            )
            prompt_source = "mask_sequence"
    resolved_generation_parameters = {
        "effective_seed": 1603,
        "num_samples": num_samples,
    }
    resolved_generation_parameters.update(generation_parameters or {})
    nodes.append(
        WorkflowNodeInstance(
            node_id="generate",
            node_type_id=f"esm3.{operation}",
            node_type_version="8.0.0",
            binding_id=f"esm3.{operation}.{binding_route}",
            binding_version="8.0.0",
            node_parameters=resolved_generation_parameters,
            binding_parameters={},
        )
    )
    edges.append(
        WorkflowEdge(
            prompt_source,
            "protein_prompt",
            "generate",
            "protein_prompt",
        )
    )
    if materialize_confidence:
        if operation != "generate_structure":
            raise ValueError(
                "confidence materialization fixture requires structure generation"
            )
        nodes.append(
            WorkflowNodeInstance(
                node_id="materialize-confidence",
                node_type_id=(
                    "structure_prediction.materialize_confidence"
                ),
                node_type_version="2.0.0",
                binding_id=(
                    "structure_prediction.materialize_confidence.direct"
                ),
                binding_version="2.0.0",
                node_parameters={},
                binding_parameters={},
            )
        )
        edges.extend(
            (
                WorkflowEdge(
                    "generate",
                    "structure_candidates",
                    "materialize-confidence",
                    "structure_candidates",
                ),
                WorkflowEdge(
                    "generate",
                    "confidence_facts",
                    "materialize-confidence",
                    "confidence_facts",
                ),
            )
        )

    if catalog is None:
        catalog = generation_catalog(include_protein_io=sequence is not None)
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create(f"ESM3 {operation}")
    for reference, payload in project_inputs.items():
        projects.publish_input(
            project.id,
            reference,
            payload,
            filename=reference,
        )
    authoring = WorkflowAuthoringService(projects, catalog)
    workflow = WorkflowDocument(
        schema_version="2.1.0",
        workflow_id=project.id,
        nodes=tuple(nodes),
        edges=tuple(edges),
        contract_lock=(),
    )
    committed = authoring.commit(
        project.id,
        workflow=workflow,
    )
    environment_values = (
        {}
        if binding_route == "local_open"
        else {
            "endpoint_id": "biohub",
            "credential_handle": "secret-must-never-publish",
        }
    )
    environment_values.update(environment_overrides or {})
    environment = admit_environment_configuration(
        catalog,
        {
            (f"esm3.{operation}.{binding_route}", "8.0.0"): {
                "values": environment_values,
            }
        }
    )
    service = V2RunService(
        projects,
        catalog,
        authoring,
        NodeAttemptFactory(
            projects,
            environment,
            result_store(projects),
        ),
        result_store(projects),
    )
    with _installed_test_client(binding_route, client):
        try:
            receipt = service.start_background(
                project.id,
                workflow_commit_id=committed.workflow_commit_id,
                client_request_id=f"esm3-{operation}",
            )
            service.shutdown()
            projection = public_run_projection(
                service,
                project.id,
                receipt["run_id"],
            )
            events = public_run_events(service, project.id, receipt["run_id"])
        finally:
            service.shutdown()
    return service, catalog, projection, events


def three_residue_pdb(sequence: str = "ACD") -> str:
    residue_names = {
        "A": "ALA",
        "C": "CYS",
        "D": "ASP",
    }
    lines: list[str] = []
    serial = 1
    for residue_index, symbol in enumerate(sequence, start=1):
        for atom_name, offset in (
            ("N", 0.0),
            ("CA", 0.3),
            ("C", 0.6),
            ("O", 0.9),
        ):
            x = residue_index * 3.0 + offset
            lines.append(
                f"ATOM  {serial:5d} {atom_name:^4s} "
                f"{residue_names[symbol]:>3s} A{residue_index:4d}    "
                f"{x:8.3f}{1.0:8.3f}{2.0:8.3f}"
                f"  1.00 20.00{'':10}{atom_name[0]:>2s}  "
            )
            serial += 1
    return "\n".join([*lines, "TER", "END", ""])


def three_residue_provider_pdb(sequence: str = "ACD") -> str:
    """Match the official ESM SDK serializer's ATOM-only PDB body."""
    return three_residue_pdb(sequence).removesuffix("TER\nEND\n")


def three_residue_translated_pdb(sequence: str = "ACD") -> str:
    """Translate the official SDK body to the canonical terminal record."""
    return f"{three_residue_provider_pdb(sequence)}END\n"


def run_generation_from_prompt_fixture(
    tmp_path: Path,
    *,
    operation: str,
    mode: str,
    client: ProviderClient,
    num_samples: int = 1,
    binding_route: str = "biohub_medium",
) -> tuple[Any, Any, dict[str, Any], tuple[dict[str, Any], ...]]:
    from modules.esm3.package import MODULE_PACKAGE as ESM3_PACKAGE
    from modules.prompt_authoring.package import (
        MODULE_PACKAGE as PROMPT_AUTHORING_PACKAGE,
    )
    from modules.structure_transform.package import (
        MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
    )
    from modules.structure_prediction.package import (
        MODULE_PACKAGE as STRUCTURE_PREDICTION_PACKAGE,
    )
    from tests.fixtures.esm3_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    catalog = build_frozen_catalog(
        (
            ESM3_PACKAGE,
            PROMPT_AUTHORING_PACKAGE,
            SOURCE_PACKAGE,
            STRUCTURE_PREDICTION_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        )
    )
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create(f"ESM3 {operation} fixture")
    authoring = WorkflowAuthoringService(projects, catalog)
    workflow = WorkflowDocument(
        schema_version="2.1.0",
        workflow_id=project.id,
        nodes=(
            WorkflowNodeInstance(
                node_id="source",
                node_type_id="contract_test.esm3_prompt_source",
                node_type_version="3.0.0",
                binding_id="contract_test.esm3_prompt_source.direct",
                binding_version="3.0.0",
                node_parameters={"mode": mode},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="generate",
                node_type_id=f"esm3.{operation}",
                node_type_version="8.0.0",
                binding_id=f"esm3.{operation}.{binding_route}",
                binding_version="8.0.0",
                node_parameters={
                    "effective_seed": 1603,
                    "num_samples": num_samples,
                },
                binding_parameters={},
            ),
        ),
        edges=(
            WorkflowEdge(
                "source",
                "protein_prompt",
                "generate",
                "protein_prompt",
            ),
        ),
        contract_lock=(),
    )
    committed = authoring.commit(
        project.id,
        workflow=workflow,
    )
    environment = admit_environment_configuration(
        catalog,
        {
            (f"esm3.{operation}.{binding_route}", "8.0.0"): {
                "values": {
                    "endpoint_id": "biohub",
                    "credential_handle": "fixture-secret-must-not-publish",
                },
            }
        }
    )
    service = V2RunService(
        projects,
        catalog,
        authoring,
        NodeAttemptFactory(
            projects,
            environment,
            result_store(projects),
        ),
        result_store(projects),
    )
    with _installed_test_client(binding_route, client):
        try:
            receipt = service.start_background(
                project.id,
                workflow_commit_id=committed.workflow_commit_id,
                client_request_id=f"esm3-{operation}-{mode}",
            )
            service.shutdown()
            projection = public_run_projection(
                service,
                project.id,
                receipt["run_id"],
            )
            events = public_run_events(service, project.id, receipt["run_id"])
        finally:
            service.shutdown()
    return service, catalog, projection, events
