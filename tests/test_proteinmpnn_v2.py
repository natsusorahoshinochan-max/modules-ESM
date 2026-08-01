"""Public v2 contracts for the cohesive ProteinMPNN Module Package."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
import hashlib
from pathlib import Path
from typing import Any

import pytest

from core import (
    CatalogBuildError,
    ContractIdentity,
    EnvironmentConfiguration,
    ModulePackageContractCase,
    ModulePackagePortCase,
    ProjectManager,
    ResultReplayHit,
    ResultReplaySource,
    V2RunService,
    WorkflowAuthoringService,
    WorkflowDocument,
    WorkflowNodeInstance,
    build_discovered_frozen_catalog,
    build_frozen_catalog,
    discover_module_packages,
    parse_workflow_document,
    verify_module_package_contract,
)
from core.port_types import canonical_json_bytes
from core.workflow_v2 import (
    WorkflowCompileError,
    WorkflowEdge,
    compile_workflow,
    relock_workflow,
)
from datatypes import (
    Candidate,
    CandidateCollection,
    ExactContractReference,
    IntrinsicObservationContext,
    ProteinMPNNConstraints,
    ProteinSequence,
    ProteinStructure,
    ResidueLayout,
    ScoreCollection,
    ScoreObservation,
)
from modules.proteinmpnn.adapter import (
    LocalProteinMPNNAdapter,
)
from tests.fixtures.result_replay_v2 import admitted_replay_outputs


TARGET_LAYOUT = ResidueLayout(
    "A,B",
    5,
    ["A:1", "A:2", "B:1", "B:2", "B:3"],
)


def test_proteinmpnn_is_one_package_with_four_independent_nodes() -> None:
    registrations = {
        registration.package_id: registration
        for registration in discover_module_packages()
    }

    registration = registrations["proteinmpnn"]
    assert registration.package_module == "modules.proteinmpnn"
    assert {
        resource.resource for resource in registration.node_definitions
    } == {
        "definitions/constraints.yaml",
        "definitions/random_fixed_positions.yaml",
        "definitions/design.yaml",
        "definitions/score.yaml",
    }

    catalog = build_discovered_frozen_catalog()
    owned_nodes = {
        (contract_id, version)
        for kind, contract_id, version in catalog.owners
        if kind == "node_type"
        and "proteinmpnn" in catalog.owners[(kind, contract_id, version)]
    }
    assert owned_nodes == {
        ("proteinmpnn.constraints", "3.0.0"),
        ("proteinmpnn.random_fixed_positions", "3.0.0"),
        ("proteinmpnn.design", "4.0.0"),
        ("proteinmpnn.score", "2.1.0"),
    }
    active_v3_contracts = {
        ("port_type", "proteinmpnn.constraints"),
        ("node_type", "proteinmpnn.constraints"),
        ("node_type", "proteinmpnn.random_fixed_positions"),
        ("method", "proteinmpnn.constraints.repository_owned"),
        (
            "method",
            "proteinmpnn.random_fixed_positions.repository_owned",
        ),
        ("method", "proteinmpnn.design.v_48_020_8907e667"),
        ("binding", "proteinmpnn.constraints.local"),
        ("binding", "proteinmpnn.random_fixed_positions.local"),
    }
    for kind, contract_id in active_v3_contracts:
        assert catalog.get_contract(kind, contract_id, "3.0.0") is not None
        assert catalog.get_contract(kind, contract_id, "2.1.0") is None
    for kind, contract_id in (
        ("node_type", "proteinmpnn.design"),
        ("binding", "proteinmpnn.design.local"),
    ):
        assert catalog.get_contract(kind, contract_id, "4.0.0") is not None
        assert catalog.get_contract(kind, contract_id, "3.0.0") is None


def test_scoring_binding_fixes_exact_method_metric_and_observation_scope() -> None:
    from modules.proteinmpnn.package import (
        MODULE_PACKAGE as PROTEINMPNN_PACKAGE,
    )
    catalog = build_frozen_catalog((PROTEINMPNN_PACKAGE,))
    node = catalog.require_contract(
        "node_type",
        "proteinmpnn.score",
        "2.1.0",
    )
    binding = catalog.require_contract(
        "binding",
        "proteinmpnn.score.local",
        "2.1.0",
    )
    method = catalog.require_contract(
        "method",
        "proteinmpnn.score.v_48_020_8907e667",
        "2.1.0",
    )
    metric = catalog.require_contract(
        "metric",
        "proteinmpnn.native_sequence_nll",
        "2.1.0",
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
    assert method.descriptor["featurization_identity"] == {
        "structure": "ProteinMPNN parse_PDB",
        "sequence": "canonical-20-amino-acid exact target layout",
        "tensorization": "ProteinMPNN tied_featurize all chains designed",
        "mask": "provider mask multiplied by chain_M",
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
        "guaranteed_multiplicity": "one",
    }
    assert produced[0]["metric"] == {
        "contract_kind": "metric",
        "contract_id": "proteinmpnn.native_sequence_nll",
        "contract_version": "2.1.0",
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
        build_frozen_catalog((invalid_package,))


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
            binding_version="4.0.0",
            node_parameters={},
            binding_parameters={},
        ),
    )
    catalog = build_frozen_catalog(
        (PROTEINMPNN_PACKAGE, SOURCE_PACKAGE)
    )
    workflow = relock_workflow(
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
        compile_workflow(
            workflow,
            workflow_revision=1,
            catalog=catalog,
        )
    assert provider.parsed == []
    assert provider.requests == []


def _decode_output(catalog: Any, output: dict[str, Any]) -> Any:
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


def _run(
    tmp_path: Path,
    *,
    nodes: tuple[WorkflowNodeInstance, ...],
    edges: tuple[WorkflowEdge, ...],
    registrations: tuple[Any, ...],
    environment: EnvironmentConfiguration | None = None,
    result_replay_source: ResultReplaySource | None = None,
) -> tuple[Any, dict[str, Any], tuple[dict[str, Any], ...]]:
    catalog = build_frozen_catalog(registrations)
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create("ProteinMPNN v2")
    authoring = WorkflowAuthoringService(projects, catalog)
    saved = authoring.save(
        project.id,
        expected_workflow_revision=0,
        workflow=WorkflowDocument(
            schema_version="2.1.0",
            workflow_id=project.id,
            nodes=nodes,
            edges=edges,
            contract_lock=(),
        ),
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
        environment or EnvironmentConfiguration({}),
        result_replay_source,
    )
    try:
        receipt = service.start_background(
            project.id,
            workflow_revision=relocked["workflow_revision"],
            compile_id=compiled.public_receipt()["compile_id"],
            client_request_id="proteinmpnn-v2",
        )
        service.shutdown()
        return (
            catalog,
            service.projection(project.id, receipt["run_id"]),
            service.public_events(project.id, receipt["run_id"]),
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
        node_type_version="2.1.0",
        binding_id="prompt_authoring.build_residue_layout.direct",
        binding_version="2.1.0",
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
        node_type_version="3.0.0",
        binding_id="proteinmpnn.constraints.local",
        binding_version="3.0.0",
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

    catalog, projection, events = _run(
        tmp_path,
        nodes=(layout, constraints),
        edges=(WorkflowEdge("layout", "layout", "constraints", "layout"),),
        registrations=(PROMPT_AUTHORING_PACKAGE, PROTEINMPNN_PACKAGE),
    )

    assert projection["status"] == "succeeded", events
    output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "constraints"
        and item["output_port"] == "constraints"
    )
    assert _decode_output(catalog, output) == ProteinMPNNConstraints(
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


def test_constraints_v3_canonical_value_and_contract_identity_golden() -> None:
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
        (PROTEINMPNN_PACKAGE,)
    ).require_port_type("proteinmpnn.constraints", "3.0.0")

    assert port_type.encode(constraints) == (
        b'{"port_type_id":"proteinmpnn.constraints","port_type_version"'
        b':"3.0.0","schema_namespace":"protein-workbench-port-value/v2",'
        b'"value":{"bias_by_residue":[["A:3",{"G":1.5,"Y":-0.25}]],'
        b'"designable_residue_ids":["A:1","A:2","A:3"],'
        b'"designed_chains":["A"],"fixed_chains":["B"],'
        b'"fixed_residue_ids":["A:4"],"layout":{"chain_id":"A,B",'
        b'"length":6,"residue_ids":["A:1","A:2","A:3","A:4","B:1",'
        b'"B:2"]},"omit_amino_acids":["C","M"],'
        b'"tied_residue_groups":[["A:1","A:2"]]}}'
    )
    assert port_type.content_digest(constraints) == (
        "sha256:4438b64b117bd01a800ec1d110031f0332d8c20f99d314d1561772f4dab7c0d4"
    )
    assert port_type.contract_digest == (
        "sha256:9051751355cc411a1395f320852c96979053e004226cb219516fd82acb33980e"
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
        (PROTEINMPNN_PACKAGE,)
    ).require_port_type("proteinmpnn.constraints", "3.0.0")
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
            node_type_version="2.1.0",
            binding_id="prompt_authoring.build_residue_layout.direct",
            binding_version="2.1.0",
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
            node_type_version="3.0.0",
            binding_id="proteinmpnn.constraints.local",
            binding_version="3.0.0",
            node_parameters=parameters,
            binding_parameters={},
        ),
    )

    catalog, projection, events = _run(
        tmp_path,
        nodes=nodes,
        edges=(WorkflowEdge("layout", "layout", "constraints", "layout"),),
        registrations=(PROMPT_AUTHORING_PACKAGE, PROTEINMPNN_PACKAGE),
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


def test_constraint_authoring_rejects_public_x_bias() -> None:
    from modules.proteinmpnn.domain import author_constraints

    with pytest.raises(ValueError, match="unsupported amino acid"):
        author_constraints(
            TARGET_LAYOUT,
            {
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
                    },
                ],
            },
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

    catalog = build_frozen_catalog((PROTEINMPNN_PACKAGE,))
    binding = catalog.require_contract(
        "binding",
        "proteinmpnn.random_fixed_positions.local",
        "3.0.0",
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
                node_type_version="2.1.0",
                binding_id="prompt_authoring.build_residue_layout.direct",
                binding_version="2.1.0",
                node_parameters={
                    "chains": [{"chain_id": "A", "length": 20}]
                },
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="random-fixed",
                node_type_id="proteinmpnn.random_fixed_positions",
                node_type_version="3.0.0",
                binding_id="proteinmpnn.random_fixed_positions.local",
                binding_version="3.0.0",
                node_parameters={
                    "effective_seed": seed,
                    "fraction": 0.3,
                },
                binding_parameters={},
            ),
        )
        run_catalog, projection, events = _run(
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

    def engine_invocation(self, **kwargs: Any):
        self.invocations.append(kwargs)
        return nullcontext()


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

    def design(self, request: Any) -> tuple[list[ProteinSequence], list[float]]:
        self.requests.append(request)
        alphabet = "ACDEFGHIKLMNPQRSTVWY"
        return (
            [
                ProteinSequence(
                    "AGST" + alphabet[(request.seed + index) % len(alphabet)]
                )
                for index in range(request.num_sequences)
            ],
            [-float(index + 1) for index in range(request.num_sequences)],
        )

    def score(self, request: Any, sequence: ProteinSequence) -> float:
        self.requests.append((request, sequence))
        return 2.75


def _controlled_adapter(
    provider: _ControlledProteinMPNNProvider,
    *,
    resources: _AdapterResources | None = None,
) -> LocalProteinMPNNAdapter:
    return LocalProteinMPNNAdapter(
        environment={},
        resources=resources or _AdapterResources(),
        provider_factory=lambda _environment, _directory: provider,
    )


def _install_test_provider(
    monkeypatch: pytest.MonkeyPatch,
    provider: Any,
) -> None:
    def build(**kwargs: Any) -> Any:
        return LocalProteinMPNNAdapter(
            environment=kwargs["environment"],
            resources=kwargs["resources"],
            provider_factory=lambda _environment, _directory: provider,
        )

    monkeypatch.setattr(
        "modules.proteinmpnn.package.LocalProteinMPNNAdapter",
        build,
    )


def _proteinmpnn_provider_root() -> Path:
    return (
        Path(__file__).resolve().parent.parent
        / "repositories"
        / "ProteinMPNN"
    )


def _proteinmpnn_environment(
) -> EnvironmentConfiguration:
    from modules.proteinmpnn.adapter import (
        configured_runtime_fingerprint,
    )

    fingerprint = configured_runtime_fingerprint()
    return EnvironmentConfiguration(
        {
            (binding_id, version): {
                "values": {
                    "device": "cpu",
                    "resolved_runtime_fingerprint": fingerprint,
                    "provider_root": _proteinmpnn_provider_root(),
                    "private_token": "proteinmpnn-secret-must-not-publish",
                },
                "safe_fingerprint": "proteinmpnn-fixture-v1",
                "invalidation_token": "proteinmpnn-fixture-v1",
            }
            for binding_id, version in (
                ("proteinmpnn.design.local", "4.0.0"),
                ("proteinmpnn.score.local", "2.1.0"),
            )
        }
    )


def _score_workflow() -> tuple[
    tuple[WorkflowNodeInstance, ...],
    tuple[WorkflowEdge, ...],
]:
    return (
        (
            WorkflowNodeInstance(
                node_id="source",
                node_type_id="contract_test.proteinmpnn_source",
                node_type_version="2.1.0",
                binding_id="contract_test.proteinmpnn_source.direct",
                binding_version="2.1.0",
                node_parameters={"parent_count": 1},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="sequence-source",
                node_type_id="contract_test.proteinmpnn_sequence_source",
                node_type_version="2.1.0",
                binding_id=(
                    "contract_test.proteinmpnn_sequence_source.direct"
                ),
                binding_version="2.1.0",
                node_parameters={},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="score",
                node_type_id="proteinmpnn.score",
                node_type_version="2.1.0",
                binding_id="proteinmpnn.score.local",
                binding_version="2.1.0",
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
                "score",
                "structure_candidates",
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
    catalog, projection, events = _run(
        tmp_path,
        nodes=nodes,
        edges=edges,
        registrations=(PROTEINMPNN_PACKAGE, SOURCE_PACKAGE),
        environment=_proteinmpnn_environment(),
    )

    assert projection["status"] == "succeeded", events
    output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "score"
    )
    scores = _decode_output(catalog, output)
    subject_output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "sequence-source"
    )
    subjects = _decode_output(catalog, subject_output)
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


@pytest.mark.parametrize(
    "raw_score",
    (
        -0.25,
        float("inf"),
        0,
        1e-100,
        1.0000000000000002,
        3.402823466385289e38,
    ),
)
def test_scoring_rejects_non_native_values_after_engine_without_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raw_score: object,
) -> None:
    from modules.proteinmpnn.package import (
        MODULE_PACKAGE as PROTEINMPNN_PACKAGE,
    )
    from tests.fixtures.proteinmpnn_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    class Provider(_ControlledProteinMPNNProvider):
        def score(
            self,
            request: Any,
            sequence: ProteinSequence,
        ) -> Any:
            self.requests.append((request, sequence))
            return raw_score

    class Replay(ResultReplaySource):
        def __init__(self) -> None:
            self.published: list[str] = []

        def publish(self, **kwargs: Any) -> None:
            self.published.append(kwargs["node"].node_id)

    provider = Provider()
    replay = Replay()
    _install_test_provider(monkeypatch, provider)
    nodes, edges = _score_workflow()
    catalog, projection, events = _run(
        tmp_path,
        nodes=nodes,
        edges=edges,
        registrations=(PROTEINMPNN_PACKAGE, SOURCE_PACKAGE),
        environment=_proteinmpnn_environment(),
        result_replay_source=replay,
    )

    assert projection["status"] == "failed"
    assert all(
        output["node_id"] != "score"
        for output in projection["outputs"]
    )
    assert "score" not in replay.published
    public_events = [item["event"] for item in events]
    method_digest = catalog.require_contract(
        "method",
        "proteinmpnn.score.v_48_020_8907e667",
        "2.1.0",
    ).contract_digest
    invocation = next(
        event
        for event in public_events
        if event["type"] == "engine_invocation_started"
        and event["engine_identity"] == method_digest
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
        and event["status"] == "failed"
        for event in public_events
    )


def test_scoring_replay_preserves_the_canonical_binary32_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.proteinmpnn.package import (
        MODULE_PACKAGE as PROTEINMPNN_PACKAGE,
    )
    from tests.fixtures.proteinmpnn_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    catalog = build_frozen_catalog(
        (PROTEINMPNN_PACKAGE, SOURCE_PACKAGE)
    )

    def reference(
        contract_kind: str,
        contract_id: str,
    ) -> ExactContractReference:
        contract = catalog.require_contract(
            contract_kind,
            contract_id,
            "2.1.0",
        )
        return ExactContractReference(
            contract_kind=contract_kind,
            contract_id=contract_id,
            contract_version="2.1.0",
            contract_digest=contract.contract_digest,
        )

    class Replay(ResultReplaySource):
        def lookup(self, **kwargs: Any) -> ResultReplayHit | None:
            if kwargs["node"].node_id != "score":
                return None
            subjects = kwargs["inputs"]["sequence_candidates"]
            assert type(subjects) is CandidateCollection
            outputs = {
                "scores": ScoreCollection(
                    "canonical-binary32-replay",
                    [
                        ScoreObservation(
                            candidate_id=subjects.items[0].candidate_id,
                            metric=reference(
                                "metric",
                                "proteinmpnn.native_sequence_nll",
                            ),
                            method=reference(
                                "method",
                                "proteinmpnn.score.v_48_020_8907e667",
                            ),
                            context=IntrinsicObservationContext(),
                            value=1.0,
                        )
                    ],
                )
            }
            return ResultReplayHit(
                result_identity=kwargs["result_identity"],
                producer_run_id="canonical-replay-provider",
                admitted_outputs=admitted_replay_outputs(
                    catalog=catalog,
                    node=kwargs["node"],
                    outputs=outputs,
                ),
            )

    provider = _ControlledProteinMPNNProvider()
    _install_test_provider(monkeypatch, provider)
    nodes, edges = _score_workflow()
    run_catalog, projection, events = _run(
        tmp_path,
        nodes=nodes,
        edges=edges,
        registrations=(PROTEINMPNN_PACKAGE, SOURCE_PACKAGE),
        environment=_proteinmpnn_environment(),
        result_replay_source=Replay(),
    )

    assert projection["status"] == "succeeded", events
    assert provider.parsed == []
    assert provider.requests == []
    score_output = next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "score"
    )
    scores = _decode_output(run_catalog, score_output)
    assert type(scores) is ScoreCollection
    assert scores.entries[0].value == 1.0
    score_disposition = next(
        disposition
        for disposition in projection["node_dispositions"]
        if disposition["node_id"] == "score"
    )
    assert score_disposition["outcome"] == "succeeded"
    assert score_disposition["resolution"] == "cache_replayed"


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
    catalog, projection, events = _run(
        tmp_path,
        nodes=nodes,
        edges=edges,
        registrations=(PROTEINMPNN_PACKAGE, SOURCE_PACKAGE),
        environment=_proteinmpnn_environment(),
    )

    assert projection["status"] == "failed"
    assert provider.parsed == []
    assert provider.requests == []
    score_method_digest = catalog.require_contract(
        "method",
        "proteinmpnn.score.v_48_020_8907e667",
        "2.1.0",
    ).contract_digest
    assert all(
        event["event"]["type"] != "engine_invocation_started"
        or event["event"]["engine_identity"] != score_method_digest
        for event in events
    )


def test_scoring_rejects_sequence_residue_layout_drift_before_model_call() -> None:
    provider = _ControlledProteinMPNNProvider()
    with pytest.raises(
        ValueError,
        match="residue layout does not match",
    ):
        _controlled_adapter(provider).score(
            structure=ProteinStructure("MODEL\nEND\n"),
            sequence=ProteinSequence(
                "AGSTW",
                ["A:1", "A:2", "A:3", "B:1", "B:2"],
            ),
        )
    assert provider.requests == []


def test_scoring_uses_identity_complete_sequence_layout_for_provider_mapping() -> None:
    provider = _ControlledProteinMPNNProvider()
    resources = _AdapterResources()
    score = _controlled_adapter(provider, resources=resources).score(
        structure=ProteinStructure("MODEL\nEND\n"),
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
        ("A:6", "A", 1),
        ("A:7", "A", 2),
        ("B:20", "B", 1),
        ("B:21", "B", 2),
        ("B:22", "B", 3),
    )
    assert resources.invocations == [
        {
            "engine_role": "score_subject",
            "invocation_provenance": {
                "provider_residue_projection": {
                    "position_semantics": "one_based_chain_local",
                    "workbench_chain_order": ["A", "B"],
                    "provider_chain_order": ["A", "B"],
                    "entries": [
                        {
                            "residue_id": "A:6",
                            "provider_chain_id": "A",
                            "provider_position": 1,
                        },
                        {
                            "residue_id": "A:7",
                            "provider_chain_id": "A",
                            "provider_position": 2,
                        },
                        {
                            "residue_id": "B:20",
                            "provider_chain_id": "B",
                            "provider_position": 1,
                        },
                        {
                            "residue_id": "B:21",
                            "provider_chain_id": "B",
                            "provider_position": 2,
                        },
                        {
                            "residue_id": "B:22",
                            "provider_chain_id": "B",
                            "provider_position": 3,
                        },
                    ],
                }
            },
        }
    ]


@pytest.mark.parametrize("operation", ("design", "score"))
def test_provider_residue_projection_starts_before_provider_failure(
    operation: str,
) -> None:
    resources = _AdapterResources()
    expected_projection = {
        "position_semantics": "one_based_chain_local",
        "workbench_chain_order": ["A", "B"],
        "provider_chain_order": ["A", "B"],
        "entries": [
            {
                "residue_id": "A:1",
                "provider_chain_id": "A",
                "provider_position": 1,
            },
            {
                "residue_id": "A:2",
                "provider_chain_id": "A",
                "provider_position": 2,
            },
            {
                "residue_id": "B:1",
                "provider_chain_id": "B",
                "provider_position": 1,
            },
            {
                "residue_id": "B:2",
                "provider_chain_id": "B",
                "provider_position": 2,
            },
            {
                "residue_id": "B:3",
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

    class FailingProvider(_ControlledProteinMPNNProvider):
        def _fail(self) -> None:
            assert resources.invocations == [
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
                structure=ProteinStructure("MODEL\nEND\n"),
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
                structure=ProteinStructure("MODEL\nEND\n"),
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
    _, projection, events = _run(
        tmp_path,
        nodes=nodes,
        edges=edges,
        registrations=(
            PROMPT_AUTHORING_PACKAGE,
            PROTEINMPNN_PACKAGE,
            SOURCE_PACKAGE,
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
        "provider_chain_order": ["A", "B"],
        "entries": [
            {
                "residue_id": "A:1",
                "provider_chain_id": "A",
                "provider_position": 1,
            },
            {
                "residue_id": "A:2",
                "provider_chain_id": "A",
                "provider_position": 2,
            },
            {
                "residue_id": "B:1",
                "provider_chain_id": "B",
                "provider_position": 1,
            },
            {
                "residue_id": "B:2",
                "provider_chain_id": "B",
                "provider_position": 2,
            },
            {
                "residue_id": "B:3",
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
        (PROTEINMPNN_PACKAGE, SOURCE_PACKAGE)
    )
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create("ProteinMPNN scoring replay")
    authoring = WorkflowAuthoringService(projects, catalog)
    saved = authoring.save(
        project.id,
        expected_workflow_revision=0,
        workflow=WorkflowDocument(
            schema_version="2.1.0",
            workflow_id=project.id,
            nodes=nodes,
            edges=edges,
            contract_lock=(),
        ),
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
            _proteinmpnn_environment(),
        )
        receipt = service.start_background(
            project.id,
            workflow_revision=relocked["workflow_revision"],
            compile_id=compiled.public_receipt()["compile_id"],
            client_request_id=f"score-replay-{id(provider)}",
        )
        service.shutdown()
        projection = service.projection(project.id, receipt["run_id"])
        events = service.public_events(project.id, receipt["run_id"])
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
            _decode_output(catalog, score_output),
            _decode_output(catalog, subject_output),
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
    assert len(score_readiness(replay_events)) == 1
    score_method_digest = catalog.require_contract(
        "method",
        "proteinmpnn.score.v_48_020_8907e667",
        "2.1.0",
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
            node_type_version="2.1.0",
            binding_id="contract_test.proteinmpnn_source.direct",
            binding_version="2.1.0",
            node_parameters={"parent_count": 3},
            binding_parameters={},
        ),
        WorkflowNodeInstance(
            node_id="layout",
            node_type_id="prompt_authoring.build_residue_layout",
            node_type_version="2.1.0",
            binding_id="prompt_authoring.build_residue_layout.direct",
            binding_version="2.1.0",
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
            node_type_version="3.0.0",
            binding_id="proteinmpnn.constraints.local",
            binding_version="3.0.0",
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
            node_id="design",
            node_type_id="proteinmpnn.design",
            node_type_version="4.0.0",
            binding_id="proteinmpnn.design.local",
            binding_version="4.0.0",
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
            "design",
            "structure_candidates",
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

    import modules.proteinmpnn.provider_runtime as provider_runtime

    class Model:
        def tied_sample(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            del args, kwargs
            return {
                "S": torch.tensor(
                    [[
                        provider_runtime._ALPHABET_DICT["A"],
                        provider_runtime._ALPHABET_DICT["C"],
                        provider_runtime._ALPHABET_DICT["D"],
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


def test_design_produces_canonical_three_parent_by_five_child_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.prompt_authoring.package import (
        MODULE_PACKAGE as PROMPT_AUTHORING_PACKAGE,
    )
    from modules.proteinmpnn.provider_runtime import _ALPHABET_DICT
    from modules.proteinmpnn.package import (
        MODULE_PACKAGE as PROTEINMPNN_PACKAGE,
    )
    from tests.fixtures.proteinmpnn_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    provider = _ControlledProteinMPNNProvider()
    _install_test_provider(monkeypatch, provider)
    nodes, edges = _design_workflow()
    catalog, projection, events = _run(
        tmp_path,
        nodes=nodes,
        edges=edges,
        registrations=(
            PROMPT_AUTHORING_PACKAGE,
            PROTEINMPNN_PACKAGE,
            SOURCE_PACKAGE,
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
    candidates = _decode_output(catalog, output)
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
        "3.0.0",
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
        provider = _ControlledProteinMPNNProvider()
        _install_test_provider(monkeypatch, provider)
        source_node_id = "source"
        transform_nodes = tuple(
            WorkflowNodeInstance(
                node_id=f"select-{index}",
                node_type_id="structure_transform.select_candidate_chains",
                node_type_version="2.1.0",
                binding_id=(
                    "structure_transform.select_candidate_chains.direct"
                ),
                binding_version="2.1.0",
                node_parameters={"chain_ids": ["A"]},
                binding_parameters={},
            )
            for index in range(transform_depth)
        )
        nodes = (
            WorkflowNodeInstance(
                node_id=source_node_id,
                node_type_id="contract_test.proteinmpnn_source",
                node_type_version="2.1.0",
                binding_id="contract_test.proteinmpnn_source.direct",
                binding_version="2.1.0",
                node_parameters={"parent_count": 1},
                binding_parameters={},
            ),
            *transform_nodes,
            WorkflowNodeInstance(
                node_id="design",
                node_type_id="proteinmpnn.design",
                node_type_version="4.0.0",
                binding_id="proteinmpnn.design.local",
                binding_version="4.0.0",
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
        catalog, projection, events = _run(
            tmp_path / f"depth-{transform_depth}",
            nodes=nodes,
            edges=(
                *transform_edges,
                WorkflowEdge(
                    final_parent_node,
                    "structure_candidates",
                    "design",
                    "structure_candidates",
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
        parents = _decode_output(catalog, source_output)
        assert len(provider.requests) == 1
        return (
            provider.requests[0].seed,
            parents.items[0].candidate_id,
            parents.items[0].data.pdb_string,
            catalog.require_port_type(
                "protein.structure",
                "3.0.0",
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

    class IdentityLayoutProvider(_ControlledProteinMPNNProvider):
        def parse_structure(self, pdb_string: str) -> list[dict[str, Any]]:
            self.parsed.append(pdb_string)
            return [{"name": "target", "seq_chain_A": "A" * 224}]

        def design(
            self,
            request: Any,
        ) -> tuple[list[ProteinSequence], list[float]]:
            self.requests.append(request)
            return (
                [
                    ProteinSequence("A" * request.target_length)
                    for _ in range(request.num_sequences)
                ],
                [-1.0 for _ in range(request.num_sequences)],
            )

    provider = IdentityLayoutProvider()
    _install_test_provider(monkeypatch, provider)
    nodes = (
        WorkflowNodeInstance(
            node_id="source",
            node_type_id="contract_test.prompt_authoring_values",
            node_type_version="3.0.0",
            binding_id="contract_test.prompt_authoring_values.direct",
            binding_version="3.0.0",
            node_parameters={"fixture": "2emo"},
            binding_parameters={},
        ),
        WorkflowNodeInstance(
            node_id="normalize",
            node_type_id="structure_transform.normalize_csh_parent_span",
            node_type_version="3.0.0",
            binding_id=(
                "structure_transform.normalize_csh_parent_span.direct"
            ),
            binding_version="3.0.0",
            node_parameters={},
            binding_parameters={},
        ),
        WorkflowNodeInstance(
            node_id="prompt",
            node_type_id="prompt_authoring.prompt_from_structure",
            node_type_version="3.0.0",
            binding_id="prompt_authoring.prompt_from_structure.direct",
            binding_version="3.0.0",
            node_parameters={},
            binding_parameters={},
        ),
        WorkflowNodeInstance(
            node_id="constraints",
            node_type_id="proteinmpnn.constraints",
            node_type_version="3.0.0",
            binding_id="proteinmpnn.constraints.local",
            binding_version="3.0.0",
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
            node_id="design",
            node_type_id="proteinmpnn.design",
            node_type_version="4.0.0",
            binding_id="proteinmpnn.design.local",
            binding_version="4.0.0",
            node_parameters={
                "effective_seed": 1603,
                "num_sequences": 1,
                "temperature": 0.2,
                "backbone_noise": 0,
            },
            binding_parameters={},
        ),
    )
    catalog, projection, events = _run(
        tmp_path,
        nodes=nodes,
        edges=(
            WorkflowEdge("source", "structure", "normalize", "structure"),
            WorkflowEdge("normalize", "structure", "prompt", "structure"),
            WorkflowEdge("prompt", "layout", "constraints", "layout"),
            WorkflowEdge("normalize", "structure", "design", "structure"),
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
    assert request.residue_identity_mapping[0] == ("A:6", "A", 1)
    assert request.residue_identity_mapping[-1] == ("A:229", "A", 224)
    output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "design"
        and item["output_port"] == "sequence_candidates"
    )
    candidates = _decode_output(catalog, output)
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
    assert projection_provenance["provider_chain_order"] == ["A"]
    assert projection_provenance["entries"][0] == {
        "residue_id": "A:6",
        "provider_chain_id": "A",
        "provider_position": 1,
    }
    assert projection_provenance["entries"][-1] == {
        "residue_id": "A:229",
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
    catalog = build_frozen_catalog((PROTEINMPNN_PACKAGE,))
    binding = catalog.require_contract(
        "binding",
        "proteinmpnn.design.local",
        "4.0.0",
    )
    node = catalog.require_contract(
        "node_type",
        "proteinmpnn.design",
        "4.0.0",
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
    assert binding.descriptor["availability_declaration"]["behavior"][
        "parameters"
    ]["model_load"] == "forbidden"
    assert binding.descriptor["readiness_declaration"]["behavior"][
        "parameters"
    ]["model_load"] == "forbidden"


def test_readiness_validates_the_exact_checkout_checkpoint_and_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.proteinmpnn.adapter import (
        configured_runtime_fingerprint,
        proteinmpnn_readiness,
    )

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
        "resolved_runtime_fingerprint": configured_runtime_fingerprint(),
        "provider_root": provider_root,
    }

    assert proteinmpnn_readiness(environment).passing is True
    assert proteinmpnn_readiness(
        {**environment, "device": "cuda"}
    ).passing is False
    assert proteinmpnn_readiness(
        {
            **environment,
            "resolved_runtime_fingerprint": "sha256:" + "0" * 64,
        }
    ).passing is False

    provider = _ControlledProteinMPNNProvider()
    provider.provider_contract_identity = "sha256:" + "0" * 64
    assert proteinmpnn_readiness(
        {
            "device": "cpu",
            "resolved_runtime_fingerprint": (
                configured_runtime_fingerprint()
            ),
            "provider_client": provider,
        }
    ).passing is False


def test_design_rejects_noncanonical_sampling_and_reference_layout_drift() -> None:
    provider = _ControlledProteinMPNNProvider()
    adapter = _controlled_adapter(provider)
    structure = ProteinStructure("REMARK exact-layout\nEND\n")

    with pytest.raises(ValueError, match="canonical amino acid"):
        adapter.design(
            structure=structure,
            num_sequences=1,
            temperature=0.1,
            backbone_noise=0,
            seed=1603,
            constraints=ProteinMPNNConstraints(
                layout=TARGET_LAYOUT,
                omit_amino_acids=list("ACDEFGHIKLMNPQRSTVWY"),
            ),
            reference_sequence=None,
            engine_role="design_parent_0",
        )

    with pytest.raises(ValueError, match="residue layout"):
        adapter.design(
            structure=structure,
            num_sequences=1,
            temperature=0.1,
            backbone_noise=0,
            seed=1603,
            constraints=None,
            reference_sequence=ProteinSequence(
                "AGSTW",
                ["B:3", "B:2", "B:1", "A:2", "A:1"],
            ),
            engine_role="design_parent_0",
        )

    adapter.design(
        structure=structure,
        num_sequences=1,
        temperature=0.1,
        backbone_noise=0,
        seed=1603,
        constraints=None,
        reference_sequence=ProteinSequence("AGSTW"),
        engine_role="design_parent_0",
    )
    request = provider.requests[-1]
    assert request.reference_sequences == {"A": "AG", "B": "STW"}

    changed_boundary_layout = ResidueLayout(
        "A,B",
        5,
        ["A:1", "A:2", "A:3", "B:1", "B:2"],
    )
    with pytest.raises(ValueError, match="constraint residue identity"):
        adapter.design(
            structure=structure,
            num_sequences=1,
            temperature=0.1,
            backbone_noise=0,
            seed=1603,
            constraints=ProteinMPNNConstraints(
                layout=changed_boundary_layout,
                designed_chains=["B"],
            ),
            reference_sequence=None,
            engine_role="design_parent_0",
        )


def test_design_accepts_exact_immutable_reference_residue_layout() -> None:
    provider = _ControlledProteinMPNNProvider()
    result = _controlled_adapter(provider).design(
        structure=ProteinStructure("REMARK exact-layout\nEND\n"),
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
            return [ProteinSequence("VVVAG")], [1.0]

    provider = DesignedFirstProvider()
    result = _controlled_adapter(provider).design(
        structure=ProteinStructure("REMARK exact-layout\nEND\n"),
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

    assert request.structure_chain_order == ("A", "B")
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
        structure=ProteinStructure("REMARK exact-layout\nEND\n"),
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


def test_design_normalizes_one_standalone_structure_without_inventing_a_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.proteinmpnn.package import (
        MODULE_PACKAGE as PROTEINMPNN_PACKAGE,
    )
    from tests.fixtures.protein_io_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    provider = _ControlledProteinMPNNProvider()
    _install_test_provider(monkeypatch, provider)
    nodes = (
        WorkflowNodeInstance(
            node_id="source",
            node_type_id="contract_test.protein_structure",
            node_type_version="3.0.0",
            binding_id="contract_test.protein_structure.direct",
            binding_version="3.0.0",
            node_parameters={},
            binding_parameters={},
        ),
        WorkflowNodeInstance(
            node_id="design",
            node_type_id="proteinmpnn.design",
            node_type_version="4.0.0",
            binding_id="proteinmpnn.design.local",
            binding_version="4.0.0",
            node_parameters={
                "effective_seed": 1603,
                "num_sequences": 1,
                "temperature": 0.1,
                "backbone_noise": 0,
            },
            binding_parameters={},
        ),
    )
    catalog, projection, events = _run(
        tmp_path,
        nodes=nodes,
        edges=(WorkflowEdge("source", "structure", "design", "structure"),),
        registrations=(PROTEINMPNN_PACKAGE, SOURCE_PACKAGE),
        environment=_proteinmpnn_environment(),
    )

    assert projection["status"] == "succeeded", events
    output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "design"
    )
    candidates = _decode_output(catalog, output)
    assert len(candidates.items) == 1
    assert candidates.items[0].parent_ids == ()
    assert len(provider.requests) == 1


def test_standalone_design_seed_and_result_ignore_node_instance_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.proteinmpnn.package import (
        MODULE_PACKAGE as PROTEINMPNN_PACKAGE,
    )
    from tests.fixtures.protein_io_sources.package import (
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
                node_type_id="contract_test.protein_structure",
                node_type_version="3.0.0",
                binding_id="contract_test.protein_structure.direct",
                binding_version="3.0.0",
                node_parameters={},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id=design_node_id,
                node_type_id="proteinmpnn.design",
                node_type_version="4.0.0",
                binding_id="proteinmpnn.design.local",
                binding_version="4.0.0",
                node_parameters={
                    "effective_seed": 1603,
                    "num_sequences": 1,
                    "temperature": 0.1,
                    "backbone_noise": 0,
                },
                binding_parameters={},
            ),
        )
        catalog, projection, events = _run(
            tmp_path,
            nodes=nodes,
            edges=(
                WorkflowEdge(
                    "source",
                    "structure",
                    design_node_id,
                    "structure",
                ),
            ),
            registrations=(PROTEINMPNN_PACKAGE, SOURCE_PACKAGE),
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
            and item["output_port"] == "structure"
        )
        structure = _decode_output(catalog, structure_output)
        return (
            output["result_identity"],
            _decode_output(catalog, output),
            provider.requests[0].seed,
            catalog.require_port_type(
                "protein.structure",
                "3.0.0",
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
        catalog, projection, events = _run(
            tmp_path,
            nodes=nodes,
            edges=edges,
            registrations=(
                PROMPT_AUTHORING_PACKAGE,
                PROTEINMPNN_PACKAGE,
                SOURCE_PACKAGE,
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
        return output["result_identity"], _decode_output(catalog, output)

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


@pytest.mark.parametrize(
    "raw_result",
    (
        (
            [ProteinSequence("AGSTW") for _ in range(4)],
            [-1.0 for _ in range(4)],
        ),
        (
            [ProteinSequence("AGSTW") for _ in range(5)],
            [-1.0 for _ in range(4)],
        ),
        (
            [
                ProteinSequence("AGSTW"),
                ProteinSequence("AGSTW"),
                ProteinSequence("AGS?W"),
                ProteinSequence("AGSTW"),
                ProteinSequence("AGSTW"),
            ],
            [-1.0 for _ in range(5)],
        ),
    ),
)
def test_partial_or_malformed_provider_results_fail_without_publication(
    tmp_path: Path,
    raw_result: tuple[list[ProteinSequence], list[float]],
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
        def design(
            self,
            request: Any,
        ) -> tuple[list[ProteinSequence], list[float]]:
            self.requests.append(request)
            return raw_result

    class Replay(ResultReplaySource):
        def __init__(self) -> None:
            self.published: list[str] = []

        def publish(self, **kwargs: Any) -> None:
            self.published.append(kwargs["node"].node_id)

    provider = Provider()
    _install_test_provider(monkeypatch, provider)
    replay = Replay()
    nodes, edges = _design_workflow()
    catalog, projection, events = _run(
        tmp_path,
        nodes=nodes,
        edges=edges,
        registrations=(
            PROMPT_AUTHORING_PACKAGE,
            PROTEINMPNN_PACKAGE,
            SOURCE_PACKAGE,
        ),
        environment=_proteinmpnn_environment(),
        result_replay_source=replay,
    )

    assert projection["status"] == "failed"
    assert all(
        output["node_id"] != "design"
        for output in projection["outputs"]
    )
    assert "design" not in replay.published
    design_method_digest = catalog.require_contract(
        "method",
        "proteinmpnn.design.v_48_020_8907e667",
        "3.0.0",
    ).contract_digest
    design_terminal = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_terminal"
        and any(
            started["event"]["type"] == "engine_invocation_started"
            and started["event"]["invocation_id"]
            == event["event"]["invocation_id"]
            and started["event"]["engine_identity"]
            == design_method_digest
            for started in events
        )
    ]
    assert design_terminal
    assert design_terminal[-1]["status"] == "succeeded"


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
    from modules.proteinmpnn.adapter import (
        configured_runtime_fingerprint,
    )
    from tests.fixtures.proteinmpnn_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    def layout_node(node_id: str) -> WorkflowNodeInstance:
        return WorkflowNodeInstance(
            node_id=node_id,
            node_type_id="prompt_authoring.build_residue_layout",
            node_type_version="2.1.0",
            binding_id="prompt_authoring.build_residue_layout.direct",
            binding_version="2.1.0",
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
        node_type_version="2.1.0",
        binding_id="contract_test.proteinmpnn_source.direct",
        binding_version="2.1.0",
        node_parameters={"parent_count": 3},
        binding_parameters={},
    )
    sequence_source = WorkflowNodeInstance(
        node_id="sequence-source",
        node_type_id="contract_test.proteinmpnn_sequence_source",
        node_type_version="2.1.0",
        binding_id="contract_test.proteinmpnn_sequence_source.direct",
        binding_version="2.1.0",
        node_parameters={},
        binding_parameters={},
    )
    score_source = WorkflowNodeInstance(
        node_id="score-source",
        node_type_id="contract_test.proteinmpnn_source",
        node_type_version="2.1.0",
        binding_id="contract_test.proteinmpnn_source.direct",
        binding_version="2.1.0",
        node_parameters={"parent_count": 1},
        binding_parameters={},
    )
    design_provider = _ControlledProteinMPNNProvider()
    _install_test_provider(monkeypatch, design_provider)
    cases = (
        ModulePackageContractCase(
            case_id="constraints",
            node_type_id="proteinmpnn.constraints",
            node_type_version="3.0.0",
            binding_id="proteinmpnn.constraints.local",
            binding_version="3.0.0",
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
            safe_environment_fingerprint="proteinmpnn-direct-v1",
            invalidation_token="proteinmpnn-direct-v1",
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
            node_type_version="3.0.0",
            binding_id="proteinmpnn.random_fixed_positions.local",
            binding_version="3.0.0",
            node_parameters={"effective_seed": 1603, "fraction": 0.4},
            binding_parameters={},
            environment_values={},
            safe_environment_fingerprint="proteinmpnn-direct-v1",
            invalidation_token="proteinmpnn-direct-v1",
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
            node_type_version="4.0.0",
            binding_id="proteinmpnn.design.local",
            binding_version="4.0.0",
            node_parameters={
                "effective_seed": 1603,
                "num_sequences": 5,
                "temperature": 0.2,
                "backbone_noise": 0.1,
            },
            binding_parameters={},
            environment_values={
                "device": "cpu",
                "resolved_runtime_fingerprint": (
                    configured_runtime_fingerprint()
                ),
                "provider_root": _proteinmpnn_provider_root(),
                "private_token": "ctk-proteinmpnn-secret",
            },
            safe_environment_fingerprint="proteinmpnn-fixture-v1",
            invalidation_token="proteinmpnn-fixture-v1",
            workflow_nodes=(source,),
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
            ),
            expected_candidate_counts={"sequence_candidates": 15},
            forbidden_public_fragments=("ctk-proteinmpnn-secret",),
        ),
        ModulePackageContractCase(
            case_id="score",
            node_type_id="proteinmpnn.score",
            node_type_version="2.1.0",
            binding_id="proteinmpnn.score.local",
            binding_version="2.1.0",
            node_parameters={},
            binding_parameters={},
            environment_values={
                "device": "cpu",
                "resolved_runtime_fingerprint": (
                    configured_runtime_fingerprint()
                ),
                "provider_root": _proteinmpnn_provider_root(),
                "private_token": "ctk-proteinmpnn-secret",
            },
            safe_environment_fingerprint="proteinmpnn-fixture-v1",
            invalidation_token="proteinmpnn-fixture-v1",
            workflow_nodes=(score_source, sequence_source),
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
                version="3.0.0",
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
        ),
        work_root=tmp_path / "ctk",
    )

    assert [case.status for case in report.case_reports] == [
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
    ]
