"""Public v2 contracts for the cohesive ProteinMPNN Module Package."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from core import (
    CatalogBuildError,
    ContractIdentity,
    EnvironmentConfiguration,
    ModulePackageContractCase,
    ProjectManager,
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
    IntrinsicObservationContext,
    ProteinMPNNConstraints,
    ProteinSequence,
    ProteinStructure,
    ScoreCollection,
    ScoreObservation,
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
        ("proteinmpnn.constraints", "2.0.0"),
        ("proteinmpnn.random_fixed_positions", "2.0.0"),
        ("proteinmpnn.design", "2.0.0"),
        ("proteinmpnn.score", "2.0.0"),
    }


def test_scoring_binding_fixes_exact_method_metric_and_observation_scope() -> None:
    from modules.proteinmpnn.package import (
        MODULE_PACKAGE as PROTEINMPNN_PACKAGE,
    )

    catalog = build_frozen_catalog((PROTEINMPNN_PACKAGE,))
    node = catalog.require_contract(
        "node_type",
        "proteinmpnn.score",
        "2.0.0",
    )
    binding = catalog.require_contract(
        "binding",
        "proteinmpnn.score.local",
        "2.0.0",
    )
    method = catalog.require_contract(
        "method",
        "proteinmpnn.score.v_48_020_8907e667",
        "2.0.0",
    )
    metric = catalog.require_contract(
        "metric",
        "proteinmpnn.native_sequence_nll",
        "2.0.0",
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
        "contract_version": "2.0.0",
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
                "2.0.0",
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

    provider = _CapturingProteinMPNN()
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
            binding_version="2.0.0",
            node_parameters={},
            binding_parameters={},
        ),
    )
    catalog = build_frozen_catalog(
        (PROTEINMPNN_PACKAGE, SOURCE_PACKAGE)
    )
    workflow = relock_workflow(
        WorkflowDocument(
            schema_version="2.0.0",
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
            schema_version="2.0.0",
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
        node_type_version="2.0.0",
        binding_id="prompt_authoring.build_residue_layout.direct",
        binding_version="2.0.0",
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
        node_type_version="2.0.0",
        binding_id="proteinmpnn.constraints.local",
        binding_version="2.0.0",
        node_parameters={
            "designable_positions": [0, 2, 4],
            "fixed_positions": [1, 3],
            "designed_chains": ["A", "B"],
            "fixed_chains": [],
            "omit_amino_acids": ["C", "M"],
            "tied_positions": [[0, 2]],
            "bias_by_res": [
                {"position": 4, "amino_acid": "A", "bias": 1.5},
                {"position": 4, "amino_acid": "G", "bias": -0.25},
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
        designable_positions=[0, 2, 4],
        fixed_positions=[1, 3],
        designed_chains=["A", "B"],
        fixed_chains=None,
        omit_amino_acids=["C", "M"],
        tied_positions=[[0, 2]],
        bias_by_res={4: {"A": 1.5, "G": -0.25}},
    )
    assert output["result_identity"].startswith("sha256:")
    assert any(
        item["event"]["type"] == "engine_invocation_terminal"
        and item["event"]["status"] == "succeeded"
        for item in events
    )


@pytest.mark.parametrize(
    "parameter_override",
    (
        {"fixed_positions": [5]},
        {"designed_chains": ["C"]},
        {
            "designable_positions": [0, 1],
            "fixed_positions": [],
            "designed_chains": ["A"],
            "fixed_chains": ["B"],
            "tied_positions": [[0, 2]],
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
        "designable_positions": [],
        "fixed_positions": [],
        "designed_chains": [],
        "fixed_chains": [],
        "omit_amino_acids": [],
        "tied_positions": [],
        "bias_by_res": [],
        **parameter_override,
    }
    nodes = (
        WorkflowNodeInstance(
            node_id="layout",
            node_type_id="prompt_authoring.build_residue_layout",
            node_type_version="2.0.0",
            binding_id="prompt_authoring.build_residue_layout.direct",
            binding_version="2.0.0",
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
            node_type_version="2.0.0",
            binding_id="proteinmpnn.constraints.local",
            binding_version="2.0.0",
            node_parameters=parameters,
            binding_parameters={},
        ),
    )

    _, projection, events = _run(
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
        "2.0.0",
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
                node_type_version="2.0.0",
                binding_id="prompt_authoring.build_residue_layout.direct",
                binding_version="2.0.0",
                node_parameters={
                    "chains": [{"chain_id": "A", "length": 20}]
                },
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="random-fixed",
                node_type_id="proteinmpnn.random_fixed_positions",
                node_type_version="2.0.0",
                binding_id="proteinmpnn.random_fixed_positions.local",
                binding_version="2.0.0",
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

    assert first.fixed_positions is not None
    assert len(first.fixed_positions) == 6
    assert first.fixed_positions == sorted(set(first.fixed_positions))
    assert (first_identity, first) == (replay_identity, replay)
    assert changed_identity != first_identity
    assert changed.fixed_positions != first.fixed_positions


class _CapturingProteinMPNN:
    provider_identity = "fixture-proteinmpnn-v_48_020"

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

    def design(
        self,
        request: Any,
    ) -> tuple[list[ProteinSequence], list[float]]:
        self.requests.append(request)
        alphabet = "ACDEFGHIKLMNPQRSTVWY"
        return (
            [
                ProteinSequence(
                    "AGST" + alphabet[(request.seed + index) % len(alphabet)],
                    ["A:1", "A:2", "B:1", "B:2", "B:3"],
                )
                for index in range(request.num_sequences)
            ],
            [
                -float(index + 1)
                for index in range(request.num_sequences)
            ],
        )

    def score(
        self,
        request: Any,
        sequence: ProteinSequence,
    ) -> float:
        self.requests.append((request, sequence))
        return 2.75


def _install_test_provider(
    monkeypatch: pytest.MonkeyPatch,
    provider: Any,
) -> None:
    monkeypatch.setattr(
        "modules.proteinmpnn.implementation.provider_for_environment",
        lambda environment, *, staging_directory: provider,
    )


def _proteinmpnn_provider_root() -> Path:
    return (
        Path(__file__).resolve().parent.parent
        / "repositories"
        / "ProteinMPNN"
    )


def _proteinmpnn_environment(
) -> EnvironmentConfiguration:
    from modules.proteinmpnn.v2_adapter import (
        configured_runtime_fingerprint,
    )

    fingerprint = configured_runtime_fingerprint()
    return EnvironmentConfiguration(
        {
            (binding_id, "2.0.0"): {
                "values": {
                    "device": "cpu",
                    "resolved_runtime_fingerprint": fingerprint,
                    "provider_root": _proteinmpnn_provider_root(),
                    "private_token": "proteinmpnn-secret-must-not-publish",
                },
                "safe_fingerprint": "proteinmpnn-fixture-v1",
                "invalidation_token": "proteinmpnn-fixture-v1",
            }
            for binding_id in (
                "proteinmpnn.design.local",
                "proteinmpnn.score.local",
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
                node_type_version="2.0.0",
                binding_id="contract_test.proteinmpnn_source.direct",
                binding_version="2.0.0",
                node_parameters={"parent_count": 1},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="sequence-source",
                node_type_id="contract_test.proteinmpnn_sequence_source",
                node_type_version="2.0.0",
                binding_id=(
                    "contract_test.proteinmpnn_sequence_source.direct"
                ),
                binding_version="2.0.0",
                node_parameters={},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="score",
                node_type_id="proteinmpnn.score",
                node_type_version="2.0.0",
                binding_id="proteinmpnn.score.local",
                binding_version="2.0.0",
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

    provider = _CapturingProteinMPNN()
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
    public_events = [item["event"] for item in events]
    invocation = next(
        event
        for event in public_events
        if event["type"] == "engine_invocation_started"
        and event["engine_identity"].startswith(
            "proteinmpnn.score.local."
        )
    )
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

    class Provider(_CapturingProteinMPNN):
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
    _, projection, events = _run(
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
    invocation = next(
        event
        for event in public_events
        if event["type"] == "engine_invocation_started"
        and event["engine_identity"].startswith(
            "proteinmpnn.score.local."
        )
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

    provider = _CapturingProteinMPNN()
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
    _, projection, events = _run(
        tmp_path,
        nodes=nodes,
        edges=edges,
        registrations=(PROTEINMPNN_PACKAGE, SOURCE_PACKAGE),
        environment=_proteinmpnn_environment(),
    )

    assert projection["status"] == "failed"
    assert provider.parsed == []
    assert provider.requests == []
    assert all(
        event["event"].get("engine_identity", "").startswith(
            "proteinmpnn.score.local."
        )
        is False
        for event in events
    )


def test_scoring_rejects_sequence_residue_layout_drift_before_model_call() -> None:
    from modules.proteinmpnn.v2_adapter import prepare_scoring_request

    provider = _CapturingProteinMPNN()
    with pytest.raises(
        ValueError,
        match="residue layout does not match",
    ):
        prepare_scoring_request(
            provider=provider,
            structure=ProteinStructure("MODEL\nEND\n"),
            sequence=ProteinSequence(
                "AGSTW",
                ["A:1", "A:2", "B:1", "B:2", "B:99"],
            ),
        )
    assert provider.requests == []


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
            schema_version="2.0.0",
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

    def run(provider: _CapturingProteinMPNN) -> tuple[
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

    first_provider = _CapturingProteinMPNN()
    first_output, first_events, first_scores, first_subjects = run(
        first_provider
    )
    replay_provider = _CapturingProteinMPNN()
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
    assert all(
        not (
            item["event"]["type"] == "engine_invocation_started"
            and item["event"]["engine_identity"].startswith(
                "proteinmpnn.score.local."
            )
        )
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
            node_type_version="2.0.0",
            binding_id="contract_test.proteinmpnn_source.direct",
            binding_version="2.0.0",
            node_parameters={"parent_count": 3},
            binding_parameters={},
        ),
        WorkflowNodeInstance(
            node_id="layout",
            node_type_id="prompt_authoring.build_residue_layout",
            node_type_version="2.0.0",
            binding_id="prompt_authoring.build_residue_layout.direct",
            binding_version="2.0.0",
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
            node_type_version="2.0.0",
            binding_id="proteinmpnn.constraints.local",
            binding_version="2.0.0",
            node_parameters={
                "designable_positions": [0, 2, 4],
                "fixed_positions": [1, 3],
                "designed_chains": ["A", "B"],
                "fixed_chains": [],
                "omit_amino_acids": ["C", "M"],
                "tied_positions": [[0, 2]],
                "bias_by_res": [
                    {"position": 4, "amino_acid": "A", "bias": 1.5},
                ],
            },
            binding_parameters={},
        ),
        WorkflowNodeInstance(
            node_id="design",
            node_type_id="proteinmpnn.design",
            node_type_version="2.0.0",
            binding_id="proteinmpnn.design.local",
            binding_version="2.0.0",
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


def test_design_produces_canonical_three_parent_by_five_child_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.prompt_authoring.package import (
        MODULE_PACKAGE as PROMPT_AUTHORING_PACKAGE,
    )
    from modules.proteinmpnn.adapter import _ALPHABET_DICT
    from modules.proteinmpnn.package import (
        MODULE_PACKAGE as PROTEINMPNN_PACKAGE,
    )
    from tests.fixtures.proteinmpnn_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    provider = _CapturingProteinMPNN()
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
        assert candidate.metadata["model"] == "v_48_020"
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
    design_started = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_identity"].startswith(
            "proteinmpnn.design.local."
        )
    ]
    design_terminal = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_terminal"
        and event["event"]["invocation_id"]
        in {item["invocation_id"] for item in design_started}
    ]
    assert len(design_started) == len(design_terminal) == 3
    assert {item["status"] for item in design_terminal} == {"succeeded"}
    public_evidence = str({"projection": projection, "events": events})
    assert "proteinmpnn-secret-must-not-publish" not in public_evidence


def test_design_binding_fixes_model_source_checkpoint_and_runtime_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.proteinmpnn.adapter as legacy_adapter
    from modules.proteinmpnn.package import (
        MODULE_PACKAGE as PROTEINMPNN_PACKAGE,
    )

    def fail_if_loaded(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise AssertionError("catalog discovery must not load ProteinMPNN")

    monkeypatch.setattr(legacy_adapter, "_load_model", fail_if_loaded)
    catalog = build_frozen_catalog((PROTEINMPNN_PACKAGE,))
    binding = catalog.require_contract(
        "binding",
        "proteinmpnn.design.local",
        "2.0.0",
    )
    node = catalog.require_contract(
        "node_type",
        "proteinmpnn.design",
        "2.0.0",
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
    from modules.proteinmpnn.v2_adapter import (
        configured_runtime_fingerprint,
        proteinmpnn_readiness,
    )

    provider_root = (
        Path(__file__).resolve().parent.parent
        / "repositories"
        / "ProteinMPNN"
    )
    monkeypatch.setattr(
        "modules.proteinmpnn.adapter._load_model",
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

    provider = _CapturingProteinMPNN()
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
    from modules.proteinmpnn.v2_adapter import prepare_design_request

    provider = _CapturingProteinMPNN()
    structure = ProteinStructure("REMARK exact-layout\nEND\n")

    with pytest.raises(ValueError, match="canonical amino acid"):
        prepare_design_request(
            provider=provider,
            structure=structure,
            num_sequences=1,
            temperature=0.1,
            backbone_noise=0,
            seed=1603,
            constraints=ProteinMPNNConstraints(
                omit_amino_acids=list("ACDEFGHIKLMNPQRSTVWY"),
            ),
            reference_sequence=None,
        )

    with pytest.raises(ValueError, match="residue layout"):
        prepare_design_request(
            provider=provider,
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
        )

    request = prepare_design_request(
        provider=provider,
        structure=structure,
        num_sequences=1,
        temperature=0.1,
        backbone_noise=0,
        seed=1603,
        constraints=None,
        reference_sequence=ProteinSequence("AGSTW"),
    )
    assert request.reference_sequences == {"A": "AG", "B": "STW"}


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

    provider = _CapturingProteinMPNN()
    _install_test_provider(monkeypatch, provider)
    nodes = (
        WorkflowNodeInstance(
            node_id="source",
            node_type_id="contract_test.protein_structure",
            node_type_version="2.0.0",
            binding_id="contract_test.protein_structure.direct",
            binding_version="2.0.0",
            node_parameters={},
            binding_parameters={},
        ),
        WorkflowNodeInstance(
            node_id="design",
            node_type_id="proteinmpnn.design",
            node_type_version="2.0.0",
            binding_id="proteinmpnn.design.local",
            binding_version="2.0.0",
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
    assert candidates.items[0].parent_ids == []
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

    def run(design_node_id: str) -> tuple[str, CandidateCollection, int]:
        provider = _CapturingProteinMPNN()
        _install_test_provider(monkeypatch, provider)
        nodes = (
            WorkflowNodeInstance(
                node_id="source",
                node_type_id="contract_test.protein_structure",
                node_type_version="2.0.0",
                binding_id="contract_test.protein_structure.direct",
                binding_version="2.0.0",
                node_parameters={},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id=design_node_id,
                node_type_id="proteinmpnn.design",
                node_type_version="2.0.0",
                binding_id="proteinmpnn.design.local",
                binding_version="2.0.0",
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
        return (
            output["result_identity"],
            _decode_output(catalog, output),
            provider.requests[0].seed,
        )

    original = run("design-original")
    renamed = run("design-renamed")

    assert original == renamed


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
        provider = _CapturingProteinMPNN()
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

    class Provider(_CapturingProteinMPNN):
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
        result_replay_source=replay,
    )

    assert projection["status"] == "failed"
    assert all(
        output["node_id"] != "design"
        for output in projection["outputs"]
    )
    assert "design" not in replay.published
    design_terminal = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_terminal"
        and any(
            started["event"]["type"] == "engine_invocation_started"
            and started["event"]["invocation_id"]
            == event["event"]["invocation_id"]
            and started["event"]["engine_identity"].startswith(
                "proteinmpnn.design.local."
            )
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
    from modules.proteinmpnn.v2_adapter import (
        configured_runtime_fingerprint,
    )
    from tests.fixtures.proteinmpnn_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    def layout_node(node_id: str) -> WorkflowNodeInstance:
        return WorkflowNodeInstance(
            node_id=node_id,
            node_type_id="prompt_authoring.build_residue_layout",
            node_type_version="2.0.0",
            binding_id="prompt_authoring.build_residue_layout.direct",
            binding_version="2.0.0",
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
        node_type_version="2.0.0",
        binding_id="contract_test.proteinmpnn_source.direct",
        binding_version="2.0.0",
        node_parameters={"parent_count": 3},
        binding_parameters={},
    )
    sequence_source = WorkflowNodeInstance(
        node_id="sequence-source",
        node_type_id="contract_test.proteinmpnn_sequence_source",
        node_type_version="2.0.0",
        binding_id="contract_test.proteinmpnn_sequence_source.direct",
        binding_version="2.0.0",
        node_parameters={},
        binding_parameters={},
    )
    score_source = WorkflowNodeInstance(
        node_id="score-source",
        node_type_id="contract_test.proteinmpnn_source",
        node_type_version="2.0.0",
        binding_id="contract_test.proteinmpnn_source.direct",
        binding_version="2.0.0",
        node_parameters={"parent_count": 1},
        binding_parameters={},
    )
    design_provider = _CapturingProteinMPNN()
    _install_test_provider(monkeypatch, design_provider)
    cases = (
        ModulePackageContractCase(
            case_id="constraints",
            node_type_id="proteinmpnn.constraints",
            node_type_version="2.0.0",
            binding_id="proteinmpnn.constraints.local",
            binding_version="2.0.0",
            node_parameters={
                "designable_positions": [0, 2, 4],
                "fixed_positions": [1, 3],
                "designed_chains": ["A", "B"],
                "fixed_chains": [],
                "omit_amino_acids": ["C", "M"],
                "tied_positions": [[0, 2]],
                "bias_by_res": [
                    {"position": 4, "amino_acid": "A", "bias": 1.5}
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
            node_type_version="2.0.0",
            binding_id="proteinmpnn.random_fixed_positions.local",
            binding_version="2.0.0",
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
            node_type_version="2.0.0",
            binding_id="proteinmpnn.design.local",
            binding_version="2.0.0",
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
            node_type_version="2.0.0",
            binding_id="proteinmpnn.score.local",
            binding_version="2.0.0",
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
