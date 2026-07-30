"""Public seams for the cohesive SoluProt solubility package.

The pre-agreed seams are production package registration, exact catalog
contracts, Binding readiness, and V2 Run execution through typed Ports.
"""

from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from core import (
    EnvironmentConfiguration,
    ModulePackageContractCase,
    ProjectManager,
    ReadinessResult,
    V2RunService,
    WorkflowAuthoringService,
    WorkflowDocument,
    WorkflowNodeInstance,
    build_discovered_frozen_catalog,
    build_frozen_catalog,
    parse_workflow_document,
    verify_module_package_contract,
)
from core.port_types import canonical_json_bytes
from core.workflow_v2 import WorkflowEdge


def test_soluprot_full_and_no_tm_are_exact_sibling_bindings() -> None:
    catalog = build_discovered_frozen_catalog()

    node = catalog.require_contract(
        "node_type",
        "solubility.score_sequence",
        "2.0.0",
    )
    full = catalog.require_contract(
        "binding",
        "solubility.soluprot_full.local",
        "2.0.0",
    )
    no_tm = catalog.require_contract(
        "binding",
        "solubility.soluprot_no_tm.local",
        "2.0.0",
    )

    assert node.descriptor["node_parameters"] == {}
    assert full.descriptor["binding_parameters"] == {}
    assert no_tm.descriptor["binding_parameters"] == {}
    assert full.descriptor["method"]["contract_id"] == (
        "solubility.soluprot_full.v1_1_0"
    )
    assert no_tm.descriptor["method"]["contract_id"] == (
        "solubility.soluprot_no_tm.v1_1_0"
    )
    assert full.descriptor["method"] != no_tm.descriptor["method"]
    assert full.descriptor["implementation_identity"]["mode"] == "full"
    assert no_tm.descriptor["implementation_identity"]["mode"] == "no_tm"
    assert "model_name" not in node.descriptor["node_parameters"]


def test_soluprot_methods_fix_source_features_scale_and_observation_identity() -> None:
    catalog = build_discovered_frozen_catalog()
    metric = catalog.require_contract(
        "metric",
        "solubility.soluprot_probability",
        "2.0.0",
    )

    assert metric.descriptor["unit"] == "dimensionless_probability"
    assert metric.descriptor["direction"] == "higher_is_better"
    assert metric.descriptor["canonical_range"] == {
        "minimum": 0,
        "maximum": 1,
    }
    assert metric.descriptor["granularity"] == "candidate"
    assert metric.descriptor["validation_contract"] == {
        "finite": True,
        "minimum": 0,
        "maximum": 1,
    }

    methods = {
        mode: catalog.require_contract(
            "method",
            f"solubility.soluprot_{mode}.v1_1_0",
            "2.0.0",
        )
        for mode in ("full", "no_tm")
    }
    assert methods["full"].descriptor["source_identity"] == (
        methods["no_tm"].descriptor["source_identity"]
    )
    assert (
        methods["full"].descriptor["checkpoint_identity"]
        != methods["no_tm"].descriptor["checkpoint_identity"]
    )
    assert methods["full"].descriptor["algorithm_identity"][
        "transmembrane_features"
    ] is True
    assert methods["no_tm"].descriptor["algorithm_identity"][
        "transmembrane_features"
    ] is False
    assert isinstance(
        methods["full"].descriptor["featurization_identity"]["tmhmm"],
        Mapping,
    )
    assert methods["no_tm"].descriptor["featurization_identity"][
        "tmhmm"
    ] == "not-used-or-probed"
    assert methods["full"].descriptor["scale_contract"] == (
        methods["no_tm"].descriptor["scale_contract"]
    )
    assert methods["full"].descriptor["scale_contract"][
        "provider_postprocessing"
    ] == {
        "rounding_decimal_places": 4,
        "clipping_range": (0, 1),
    }
    assert methods["full"].descriptor["scale_contract"][
        "adapter_clamping"
    ] == "forbidden"

    for mode in ("full", "no_tm"):
        binding = catalog.require_contract(
            "binding",
            f"solubility.soluprot_{mode}.local",
            "2.0.0",
        )
        produced = binding.descriptor["produced_observations"]
        assert len(produced) == 1
        assert produced[0]["metric"]["contract_id"] == (
            "solubility.soluprot_probability"
        )
        assert produced[0]["context_profile"] == {"kind": "intrinsic"}
        assert produced[0]["subject_direction"] == "input"
        assert produced[0]["subject_port"] == "sequence_candidates"
        assert produced[0]["guaranteed_multiplicity"] == "one"
        assert produced[0]["output_partition"] == f"soluprot_{mode}"


def test_soluprot_startup_is_lazy_and_keeps_unavailable_siblings_visible() -> None:
    catalog = build_discovered_frozen_catalog()
    availability = {
        item["binding"]["contract_id"]: item
        for item in catalog.availability
    }

    for mode in ("full", "no_tm"):
        binding = catalog.require_contract(
            "binding",
            f"solubility.soluprot_{mode}.local",
            "2.0.0",
        )
        del binding
        snapshot = availability[f"solubility.soluprot_{mode}.local"]
        assert snapshot["available"] is True
        assert "reason" not in snapshot


def test_soluprot_requires_no_core_dispatch_or_readiness_branch() -> None:
    project_root = Path(__file__).resolve().parent.parent
    core_source = "\n".join(
        path.read_text()
        for path in sorted((project_root / "core").glob("*.py"))
    ).lower()

    assert "soluprot" not in core_source


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            b"runtime_id,fa_id,soluble\n0,candidate_0,nan\n",
            "outside its declared range",
        ),
        (
            b"runtime_id,fa_id,soluble\n0,candidate_0,1.01\n",
            "outside its declared range",
        ),
        (
            b"runtime_id,fa_id,soluble\n0,candidate_0,0.12345\n",
            "precision does not match",
        ),
        (
            b"runtime_id,fa_id,soluble\n0,wrong,0.5\n",
            "identity or ordering",
        ),
        (
            b"fa_id,soluble\ncandidate_0,0.5\n",
            "columns do not match",
        ),
        (
            b"runtime_id,fa_id,soluble\n",
            "row count is incomplete",
        ),
    ],
)
def test_soluprot_output_contract_fails_closed(
    payload: bytes,
    message: str,
) -> None:
    from modules.solubility.adapter import parse_soluprot_output

    with pytest.raises(ValueError, match=message):
        parse_soluprot_output(payload, expected_count=1)


@pytest.mark.parametrize(
    "sequence",
    (
        "ACDEFGHIKLMNPQRSTVWX",
        "acdefghiklmnpqrstvwy",
        "ACDEFGHIKLMNPQRSTVW",
        "",
    ),
)
def test_soluprot_invalid_sequences_fail_before_provider(
    sequence: str,
) -> None:
    from modules.solubility.adapter import validate_sequences

    with pytest.raises(ValueError, match="canonical protein sequences"):
        validate_sequences([sequence])


def test_soluprot_provider_failure_does_not_retain_stderr_or_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.solubility.adapter as adapter

    class FailedProcess:
        pid = 12345
        returncode = 7

        def communicate(self, timeout: int) -> tuple[bytes, bytes]:
            assert timeout == 300
            return b"", b"secret-token /private/provider/path"

        def kill(self) -> None:
            raise AssertionError("kill is not required")

    class Resources:
        @contextmanager
        def cancellable_process_group(
            self,
            process_group: int,
            *,
            fallback: Any,
        ):
            assert process_group == 12345
            assert callable(fallback)
            yield

    monkeypatch.setattr(
        adapter,
        "validate_soluprot_environment",
        lambda environment, *, mode: {
            "python_executable": Path("/private/python"),
            "model_json": Path("/private/model.json"),
            "usearch_executable": Path("/private/usearch"),
            "reference_database": Path("/private/database.fa"),
            "tmhmm_executable": None,
        },
    )
    monkeypatch.setattr(
        adapter.subprocess,
        "Popen",
        lambda *args, **kwargs: FailedProcess(),
    )

    with pytest.raises(
        adapter.SoluProtProviderNonzeroExit,
        match="failed safely",
    ) as rejected:
        adapter.invoke_soluprot(
            sequences=["ACDEFGHIKLMNPQRSTVWY"],
            mode="no_tm",
            staging_directory=tmp_path,
            environment={},
            run_resources=Resources(),
        )

    assert "secret-token" not in str(rejected.value)
    assert "/private/" not in str(rejected.value)


def test_soluprot_runtime_probe_rejects_transitive_dependency_tree_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json
    from types import SimpleNamespace

    import modules.solubility.adapter as adapter

    python_executable = tmp_path / "python"
    python_executable.write_bytes(b"locked python")
    python_executable.chmod(0o700)
    site_packages_root = tmp_path / "site-packages"
    site_packages_root.mkdir()
    monkeypatch.setattr(
        adapter,
        "_regular_file_sha256",
        lambda path, *, executable=False: adapter.SOLUPROT_PYTHON_SHA256,
    )
    identity = {
        "python": adapter.SOLUPROT_PYTHON_VERSION,
        "site": str(site_packages_root),
        "distributions": {
            name: {
                "version": expected["version"],
                "tree_sha256": (
                    "0" * 64
                    if name == "python-dateutil"
                    else expected["tree_sha256"]
                ),
            }
            for name, expected in (
                adapter.SOLUPROT_RUNTIME_DISTRIBUTIONS.items()
            )
        },
    }
    monkeypatch.setattr(
        adapter.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout=json.dumps(identity),
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="Python identity changed",
    ):
        adapter._validate_python_runtime(
            python_executable,
            site_packages_root=site_packages_root,
        )


def test_full_readiness_failure_does_not_block_no_tm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.solubility.adapter as adapter

    observed: list[str] = []

    def validate(environment: Any, *, mode: str) -> dict[str, Any]:
        del environment
        observed.append(mode)
        if mode == "full":
            raise FileNotFoundError("TMHMM is absent")
        return {"mode": mode}

    monkeypatch.setattr(adapter, "validate_soluprot_environment", validate)

    full = adapter.soluprot_readiness({}, mode="full")
    no_tm = adapter.soluprot_readiness({}, mode="no_tm")

    assert full == ReadinessResult(
        False,
        proof_source="direct-observation",
        reason_code="soluprot_full_runtime_unavailable",
    )
    assert no_tm == ReadinessResult(
        True,
        proof_source="direct-observation",
    )
    assert observed == ["full", "no_tm"]


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


def _run_soluprot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    mode: str,
    sequence: str = "ACDEFGHIKLMNPQRSTVWY",
    provider_payload: bytes | None = None,
    provider_error: BaseException | None = None,
) -> tuple[Any, dict[str, Any], tuple[dict[str, Any], ...]]:
    import modules.solubility.implementation as implementation
    import modules.solubility.package as package
    from modules.solubility.package import MODULE_PACKAGE
    from tests.fixtures.folding_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    monkeypatch.setattr(
        package,
        "soluprot_readiness",
        lambda environment, *, mode: ReadinessResult(
            bool(environment.get("fixture_ready")),
            proof_source="direct-observation",
            reason_code=f"soluprot_{mode}_runtime_unavailable",
        ),
    )
    monkeypatch.setattr(
        implementation,
        "validate_soluprot_environment",
        lambda environment, *, mode: {
            "resolved_runtime_fingerprint": f"sha256:{'a' * 64}",
            "mode": mode,
        },
    )
    calls: list[tuple[list[str], str]] = []

    def invoke(**kwargs: Any) -> bytes:
        calls.append((list(kwargs["sequences"]), kwargs["mode"]))
        if provider_error is not None:
            raise provider_error
        if provider_payload is not None:
            return provider_payload
        return (
            b"runtime_id,fa_id,soluble\n"
            + (
                b"0,candidate_0,0.331\n"
                if kwargs["mode"] == "full"
                else b"0,candidate_0,0.3465\n"
            )
        )

    monkeypatch.setattr(implementation, "invoke_soluprot", invoke)
    source = WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.folding_sequence_source",
        node_type_version="2.0.0",
        binding_id="contract_test.folding_sequence_source.direct",
        binding_version="2.0.0",
        node_parameters={"sequence": sequence},
        binding_parameters={},
    )
    score = WorkflowNodeInstance(
        node_id="score",
        node_type_id="solubility.score_sequence",
        node_type_version="2.0.0",
        binding_id=f"solubility.soluprot_{mode}.local",
        binding_version="2.0.0",
        node_parameters={},
        binding_parameters={},
    )
    catalog = build_frozen_catalog((MODULE_PACKAGE, SOURCE_PACKAGE))
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create(f"SoluProt {mode}")
    authoring = WorkflowAuthoringService(projects, catalog)
    saved = authoring.save(
        project.id,
        expected_workflow_revision=0,
        workflow=WorkflowDocument(
            schema_version="2.0.0",
            workflow_id=project.id,
            nodes=(source, score),
            edges=(
                WorkflowEdge(
                    "source",
                    "sequence_candidates",
                    "score",
                    "sequence_candidates",
                ),
            ),
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
        EnvironmentConfiguration(
            {
                (f"solubility.soluprot_{mode}.local", "2.0.0"): {
                    "values": {
                        "fixture_ready": True,
                        "private_runtime_path": "/must/not/publish",
                    },
                    "safe_fingerprint": f"soluprot-{mode}-fixture-v1",
                    "invalidation_token": f"soluprot-{mode}-fixture-v1",
                }
            }
        ),
    )
    try:
        receipt = service.start_background(
            project.id,
            workflow_revision=relocked["workflow_revision"],
            compile_id=compiled.public_receipt()["compile_id"],
            client_request_id=f"soluprot-{mode}",
        )
        service.shutdown()
        projection = service.projection(project.id, receipt["run_id"])
        events = service.public_events(project.id, receipt["run_id"])
    finally:
        service.shutdown()
    projection["_fixture_calls"] = calls
    return catalog, projection, events


@pytest.mark.parametrize(
    ("mode", "expected"),
    (("full", 0.331), ("no_tm", 0.3465)),
)
def test_each_soluprot_binding_runs_exact_method_and_formal_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    expected: float,
) -> None:
    catalog, projection, events = _run_soluprot(
        tmp_path,
        monkeypatch,
        mode=mode,
    )

    assert projection["status"] == "succeeded"
    assert projection["_fixture_calls"] == [
        (["ACDEFGHIKLMNPQRSTVWY"], mode),
    ]
    output = next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "score"
    )
    source_output = next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "source"
        and output["output_port"] == "sequence_candidates"
    )
    subjects = _decode_output(catalog, source_output)
    scores = _decode_output(catalog, output)
    assert len(scores.entries) == 1
    observation = scores.entries[0]
    assert observation.candidate_id == subjects.items[0].candidate_id
    assert observation.metric.contract_id == "solubility.soluprot_probability"
    assert observation.method.contract_id == (
        f"solubility.soluprot_{mode}.v1_1_0"
    )
    assert observation.context.kind == "intrinsic"
    assert observation.source_partition == f"soluprot_{mode}"
    assert observation.value == expected
    score_events = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_identity"].startswith(
            f"soluprot.{mode}.v1_1_0/"
        )
    ]
    assert len(score_events) == 1
    assert "/must/not/publish" not in str((projection, events))


def test_soluprot_method_and_asset_contracts_separate_result_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, full, _ = _run_soluprot(
        tmp_path / "full",
        monkeypatch,
        mode="full",
    )
    _, no_tm, _ = _run_soluprot(
        tmp_path / "no-tm",
        monkeypatch,
        mode="no_tm",
    )

    full_identity = next(
        output["result_identity"]
        for output in full["outputs"]
        if output["node_id"] == "score"
    )
    no_tm_identity = next(
        output["result_identity"]
        for output in no_tm["outputs"]
        if output["node_id"] == "score"
    )
    assert full_identity != no_tm_identity


def test_invalid_sequence_fails_before_soluprot_engine_invocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, projection, events = _run_soluprot(
        tmp_path,
        monkeypatch,
        mode="no_tm",
        sequence="ACDEFGHIKLMNPQRSTVW",
    )
    assert projection["status"] == "failed"
    assert projection["_fixture_calls"] == []
    assert not any(
        event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_identity"].startswith(
            "soluprot."
        )
        for event in events
    )


def test_invalid_provider_output_fails_after_successful_engine_without_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, projection, events = _run_soluprot(
        tmp_path,
        monkeypatch,
        mode="full",
        provider_payload=(
            b"runtime_id,fa_id,soluble\n"
            b"0,candidate_0,Infinity\n"
        ),
    )

    assert projection["status"] == "failed"
    assert not any(
        output["node_id"] == "score"
        for output in projection["outputs"]
    )
    started = {
        event["event"]["invocation_id"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_identity"].startswith(
            "soluprot.full.v1_1_0/"
        )
    }
    terminal = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_terminal"
        and event["event"]["invocation_id"] in started
    ]
    assert len(terminal) == 1
    assert terminal[0]["status"] == "succeeded"


def test_provider_failure_retains_a_closed_safe_reason_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.solubility.adapter import SoluProtProviderNonzeroExit

    _, projection, events = _run_soluprot(
        tmp_path,
        monkeypatch,
        mode="full",
        provider_error=SoluProtProviderNonzeroExit(
            "SoluProt provider invocation failed safely (exit status 7)"
        ),
    )

    assert projection["status"] == "failed"
    invocation_id = next(
        event["event"]["invocation_id"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_identity"].startswith(
            "soluprot.full.v1_1_0/"
        )
    )
    terminal = next(
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_terminal"
        and event["event"]["invocation_id"] == invocation_id
    )
    assert terminal["status"] == "failed"
    assert terminal["error"]["details"] == {
        "exception_type": "SoluProtProviderNonzeroExit",
    }
    assert "exit status 7" not in str(terminal)


def test_both_soluprot_methods_pass_the_shared_contract_test_kit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.solubility.implementation as implementation
    import modules.solubility.package as package
    from modules.solubility.package import MODULE_PACKAGE
    from tests.fixtures.folding_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    monkeypatch.setattr(
        package,
        "soluprot_readiness",
        lambda environment, *, mode: ReadinessResult(
            environment.get("fixture_ready") is True,
            proof_source="direct-observation",
            reason_code=f"soluprot_{mode}_runtime_unavailable",
        ),
    )
    monkeypatch.setattr(
        implementation,
        "validate_soluprot_environment",
        lambda environment, *, mode: {
            "resolved_runtime_fingerprint": f"sha256:{'b' * 64}",
            "mode": mode,
        },
    )
    monkeypatch.setattr(
        implementation,
        "invoke_soluprot",
        lambda **kwargs: (
            b"runtime_id,fa_id,soluble\n"
            + (
                b"0,candidate_0,0.331\n"
                if kwargs["mode"] == "full"
                else b"0,candidate_0,0.3465\n"
            )
        ),
    )
    source = WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.folding_sequence_source",
        node_type_version="2.0.0",
        binding_id="contract_test.folding_sequence_source.direct",
        binding_version="2.0.0",
        node_parameters={"sequence": "ACDEFGHIKLMNPQRSTVWY"},
        binding_parameters={},
    )
    cases = tuple(
        ModulePackageContractCase(
            case_id=f"soluprot-{mode}",
            node_type_id="solubility.score_sequence",
            node_type_version="2.0.0",
            binding_id=f"solubility.soluprot_{mode}.local",
            binding_version="2.0.0",
            node_parameters={},
            binding_parameters={},
            environment_values={
                "fixture_ready": True,
                "private_runtime_path": "/secret/runtime",
            },
            safe_environment_fingerprint=f"soluprot-{mode}-fixture-v1",
            invalidation_token=f"soluprot-{mode}-fixture-v1",
            workflow_nodes=(source,),
            workflow_edges=(
                WorkflowEdge(
                    "source",
                    "sequence_candidates",
                    "contract-test-node",
                    "sequence_candidates",
                ),
            ),
            expected_observation_counts={"scores": 1},
            forbidden_public_fragments=("/secret/runtime",),
        )
        for mode in ("full", "no_tm")
    )

    report = verify_module_package_contract(
        MODULE_PACKAGE,
        execution_cases=cases,
        supporting_registrations=(SOURCE_PACKAGE,),
        work_root=tmp_path,
    )

    assert [case.status for case in report.case_reports] == [
        "succeeded",
        "succeeded",
    ]
