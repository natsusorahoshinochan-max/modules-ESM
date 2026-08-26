"""Public seams for the cohesive SoluProt solubility package.

The pre-agreed seams are concrete local Adapters, production package
registration, exact catalog contracts, Binding readiness, and V2 Run
execution through typed Ports.
"""

from tests.support.ledger import public_run_events, public_run_projection

from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from core.project.manager import ProjectManager
from core.catalog.builder import (
    build_frozen_catalog,
)
from core.operation import (
    ReadinessResult,
)
from core.execution.environment import admit_environment_configuration
from core.execution.node_attempt import NodeAttemptFactory
from core.execution.runtime import V2RunService
from tests.support.result_store import result_store
from tests.support.contract_test_kit import (
    ModulePackageContractCase,
    verify_module_package_contract,
)
from core.workflow.authoring import WorkflowAuthoringService
from core.workflow.document import (
    WorkflowDocument,
    WorkflowNodeInstance,
)
from core.workflow.document import WorkflowEdge
from core.scoring.observation_plan import IntrinsicContextProfile


def _prepare_soluprot_fixture(**kwargs: Any) -> tuple[tuple[str, ...], Path]:
    staging_directory = kwargs["staging_directory"]
    (staging_directory / "input.fasta").write_text(
        "".join(
            f">candidate_{index}\n{sequence}\n"
            for index, sequence in enumerate(kwargs["sequences"])
        )
    )
    mode_flag = "--tmhmm" if kwargs["mode"] == "full" else "--no_tmhmm"
    return (
        ("fixture-soluprot", mode_flag),
        staging_directory / "output.csv",
    )


def _prepare_protein_sol_fixture(
    **kwargs: Any,
) -> tuple[tuple[str, ...], Path]:
    staging_directory = kwargs["staging_directory"]
    (staging_directory / "input.fasta").write_text(
        "".join(
            f">candidate_{index}\n{sequence}\n"
            for index, sequence in enumerate(kwargs["sequences"])
        )
    )
    return (
        ("fixture-protein-sol",),
        staging_directory / "seq_prediction.txt",
    )


def _soluprot_admitted_environment(
    *,
    private_runtime_path: str,
    include_tm: bool,
) -> dict[str, Any]:
    private_root = Path(private_runtime_path)
    environment = {
        "python_executable": private_root / "python",
        "site_packages_root": private_root / "site-packages",
        "usearch_executable": private_root / "usearch",
    }
    if include_tm:
        environment.update({
            "perl_executable": private_root / "perl",
        })
    return environment


def _protein_sol_admitted_environment(
    *,
    private_runtime_path: str,
) -> dict[str, Any]:
    private_root = Path(private_runtime_path)
    return {
        "source_root": private_root / "source",
        "bash_executable": private_root / "bash",
        "perl_executable": private_root / "perl",
    }


@pytest.mark.parametrize(
    "banner",
    (
        "usearch v12.0 [7412f73], 17.2Gb RAM, 10 cores",
        "usearch v12.0, 528Gb RAM, 128 cores",
    ),
)
def test_soluprot_readiness_accepts_official_usearch_12_banners(
    tmp_path: Path,
    banner: str,
) -> None:
    import modules.solubility.soluprot as adapter

    executable = tmp_path / "usearch"
    executable.write_text(
        f"#!/bin/sh\nprintf '%s\\n' '{banner}'\n",
        encoding="ascii",
    )
    executable.chmod(0o755)

    assert adapter._validate_usearch_runtime(executable) == executable


def test_soluprot_readiness_rejects_another_usearch_version(
    tmp_path: Path,
) -> None:
    import modules.solubility.soluprot as adapter

    executable = tmp_path / "usearch"
    executable.write_text(
        "#!/bin/sh\nprintf '%s\\n' 'usearch v12.1, changed'\n",
        encoding="ascii",
    )
    executable.chmod(0o755)

    with pytest.raises(
        adapter.SolubilityReadinessUnavailable,
        match="version changed",
    ):
        adapter._validate_usearch_runtime(executable)


def test_local_soluprot_adapter_uses_readiness_admitted_environment_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.solubility.soluprot as adapter
    from datatypes.candidate import CandidateDataReference
    from datatypes.sequence import ProteinSequence
    from modules.solubility.domain import SequenceSolubilitySubject

    events: list[str] = []
    staging_directory = tmp_path / "staging"
    staging_directory.mkdir()
    site_packages_root = tmp_path / "site-packages"
    python_executable = tmp_path / "python"
    usearch_executable = tmp_path / "usearch"
    tmhmm_root = site_packages_root / "soluprot_assets/tmhmm-2.0d"

    class Resources:
        @staticmethod
        @contextmanager
        def local_provider(provider_id: str):
            assert provider_id == "soluprot"
            events.append("provider-entered")
            yield {}

        @contextmanager
        def temporary_directory(self, *, prefix: str):
            assert prefix == "soluprot-full-"
            yield staging_directory

        @contextmanager
        def engine_invocation(
            self,
            *,
            engine_role: str,
        ):
            assert engine_role == "soluprot_full"
            events.append("engine-started")
            yield "invocation-1"
            events.append("engine-succeeded")

    def run_process(**kwargs: Any) -> int:
        assert kwargs["command"] == (
            str(python_executable),
            "-I",
            "-X",
            f"pycache_prefix={staging_directory / 'bytecode-cache'}",
            "-m",
            "soluprot_core.cli",
            "--i_fa",
            str(staging_directory / "input.fasta"),
            "--o_csv",
            str(staging_directory / "output.csv"),
            "--tmp_dir",
            str(staging_directory / "provider-work"),
            "--model",
            str(
                site_packages_root
                / "data/models/grad_clf_v1_tc/model.json"
            ),
            "--usearch",
            str(usearch_executable),
            "--pdb",
            str(
                site_packages_root
                / "data/Ecoli_xray_nmr_pdb_no_nesg.fa"
            ),
            "--check_unknown",
            "--no_proc",
            "1",
            "--tmhmm",
            str(tmhmm_root / "bin/tmhmm"),
        )
        assert kwargs["path_entries"] == (tmp_path,)
        events.append("provider-invoked")
        output_path = kwargs["staging_directory"] / "output.csv"
        output_path.write_bytes(
            b"runtime_id,fa_id,soluble\n"
            b"0,candidate_0,0.331\n"
        )
        return 0

    monkeypatch.setattr(adapter, "_run_local_process", run_process)
    local = adapter.LocalSoluProtAdapter(
        mode="full",
        environment={
            "python_executable": python_executable,
            "site_packages_root": site_packages_root,
            "usearch_executable": usearch_executable,
            "perl_executable": tmp_path / "perl",
        },
        resources=Resources(),
    )

    subject = CandidateDataReference(
        "candidate-a",
        "protein.sequence",
        f"sha256:{'a' * 64}",
    )
    predictions = local.predict(
        (
            SequenceSolubilitySubject(
                subject,
                ProteinSequence("ACDEFGHIKLMNPQRSTVWY"),
            ),
        )
    )

    assert predictions == (
        adapter.SoluProtPrediction(
            subject=subject,
            soluble_probability=0.331,
        ),
    )
    assert events == [
        "provider-entered",
        "engine-started",
        "provider-invoked",
        "engine-succeeded",
    ]
    with pytest.raises(FrozenInstanceError):
        local.mode = "no_tm"


def test_soluprot_adapter_translation_preserves_exact_subject_identity() -> None:
    from datatypes.candidate import CandidateDataReference
    from modules.solubility.soluprot import (
        SoluProtPrediction,
        parse_soluprot_output,
    )

    references = (
        CandidateDataReference(
            "candidate-a",
            "protein.sequence",
            f"sha256:{'a' * 64}",
        ),
        CandidateDataReference(
            "candidate-b",
            "protein.sequence",
            f"sha256:{'b' * 64}",
        ),
    )
    assert parse_soluprot_output(
        b"runtime_id,fa_id,soluble\n"
        b"1,candidate_1,0.9\n"
        b"0,candidate_0,0.1\n",
        staged_subjects={
            "candidate_0": references[0],
            "candidate_1": references[1],
        },
    ) == (
        SoluProtPrediction(references[1], 0.9),
        SoluProtPrediction(references[0], 0.1),
    )


def test_soluprot_operation_consumes_identity_associated_predictions(
) -> None:
    from core.operation import (
        OperationCall,
    )
    from core.scoring.observation_plan import ResolvedProducedObservation
    from datatypes.candidate import (
        Candidate,
        CandidateCollection,
        CandidateDataReference,
    )
    from datatypes.exact_reference import ExactContractReference
    from datatypes.sequence import ProteinSequence
    from modules.solubility.soluprot import SoluProtPrediction
    from modules.solubility.implementation import SoluProtImplementation
    from tests.fixtures.scientific_operation import admitted_port_fixture

    candidates = CandidateCollection(
        "soluprot-subjects",
        "protein.sequence",
        (
            Candidate(
                "candidate-a",
                ProteinSequence("ACDEFGHIKLMNPQRSTVWY"),
            ),
            Candidate(
                "candidate-b",
                ProteinSequence("YWVTSRQPNMLKIHGFEDCA"),
            ),
        ),
    )
    references = (
        CandidateDataReference(
            "candidate-a",
            "protein.sequence",
            f"sha256:{'a' * 64}",
        ),
        CandidateDataReference(
            "candidate-b",
            "protein.sequence",
            f"sha256:{'b' * 64}",
        ),
    )
    metric = ExactContractReference(
        "metric",
        "solubility.soluprot_probability",
        "2.1.0",
        f"sha256:{'c' * 64}",
    )
    method = ExactContractReference(
        "method",
        "solubility.soluprot_full.v1_1_0",
        "3.0.0",
        f"sha256:{'d' * 64}",
    )

    class AlignedAdapter:
        @staticmethod
        def predict(subjects: Any) -> tuple[SoluProtPrediction, ...]:
            assert len(subjects) == 2
            return (
                SoluProtPrediction(subjects[1].subject, 0.9),
                SoluProtPrediction(subjects[0].subject, 0.1),
            )

    implementation = SoluProtImplementation(
        adapter=AlignedAdapter(),
        method=method,
        produced_observation=ResolvedProducedObservation(
            output_port="scores",
            output_partition="soluprot_full",
            metric=metric,
            context_profile=IntrinsicContextProfile(),
            subject_grain="candidate",
            source_role="subject",
            subject_direction="input",
            subject_port="sequence_candidates",
            guaranteed_multiplicity="one",
        ),
    )

    call = OperationCall(
        inputs={
            "sequence_candidates": admitted_port_fixture(
                candidates,
                port_type_id="candidate.collection",
                value_content_digests=(f"sha256:{'e' * 64}",),
                candidate_data=tuple(reversed(references)),
            )
        },
        node_parameters={},
        binding_parameters={},
        effective_randomness={},
    )
    scores = implementation.execute(call)["scores"]

    assert [
        (observation.subject, observation.value)
        for observation in scores.entries
    ] == [(references[1], 0.9), (references[0], 0.1)]


@pytest.mark.parametrize(
    "sequence",
    (
        None,
        "ACDEFGHIKLMNPQRSTVWX",
        "ACDEFGHIKLMNPQRSTVW",
    ),
)
def test_soluprot_operation_owns_its_sequence_population(
    sequence: str | None,
) -> None:
    from datatypes.candidate import (
        Candidate,
        CandidateCollection,
    )
    from datatypes.sequence import ProteinSequence
    from modules.solubility.implementation import SoluProtImplementation
    from modules.solubility.package import MODULE_PACKAGE
    from tests.fixtures.scientific_operation import (
        operation_call,
        operation_context,
    )

    class TrustingAdapter:
        @staticmethod
        def predict(sequences: Any) -> tuple[Any, ...]:
            raise AssertionError("invalid Method input reached the Adapter")

    catalog = build_frozen_catalog((MODULE_PACKAGE,))
    context = operation_context(
        catalog,
        "solubility.soluprot_full.local",
        object(),
        binding_version="5.0.0",
    )
    operation = SoluProtImplementation(
        adapter=TrustingAdapter(),
        method=context.method,
        produced_observation=context.produced_observations[0],
    )
    call = operation_call(
        catalog=catalog,
        binding_id="solubility.soluprot_full.local",
        binding_version="5.0.0",
        inputs={
            "sequence_candidates": CandidateCollection(
                "soluprot-method-inputs",
                "protein.sequence",
                (
                    ()
                    if sequence is None
                    else (Candidate("candidate-1", ProteinSequence(sequence)),)
                ),
            )
        },
    )

    with pytest.raises(
        ValueError,
        match="canonical protein sequences of at least 20 residues",
    ):
        operation.execute(call)


def test_soluprot_full_and_no_tm_are_exact_sibling_bindings() -> None:
    from modules.solubility.package import MODULE_PACKAGE

    catalog = build_frozen_catalog((MODULE_PACKAGE,))

    node = catalog.require_contract(
        "node_type",
        "solubility.score_sequence",
        "5.0.0",
    )
    full = catalog.require_contract(
        "binding",
        "solubility.soluprot_full.local",
        "5.0.0",
    )
    no_tm = catalog.require_contract(
        "binding",
        "solubility.soluprot_no_tm.local",
        "5.0.0",
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
    for binding in (full, no_tm):
        assert binding.descriptor["route_behavior"]["parameters"][
            "response_subject_join"
        ] == "staged-fasta-identity"
    assert "model_name" not in node.descriptor["node_parameters"]


def test_soluprot_methods_fix_source_features_scale_and_observation_identity() -> None:
    from modules.solubility.package import MODULE_PACKAGE

    catalog = build_frozen_catalog((MODULE_PACKAGE,))
    metric = catalog.require_contract(
        "metric",
        "solubility.soluprot_probability",
        "2.1.0",
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
            "3.0.0",
        )
        for mode in ("full", "no_tm")
    }
    assert methods["full"].descriptor["source_identity"] == (
        methods["no_tm"].descriptor["source_identity"]
    )
    source_identity = methods["full"].descriptor["source_identity"]
    installed_code = source_identity["installed_code_sha256"]
    assert {
        key: value
        for key, value in source_identity.items()
        if key != "installed_code_sha256"
    } == {
        "kind": "project_maintained_locked_port",
        "upstream_project": "SoluProt",
        "repository_path": "repositories/soluprot-next",
        "build_backend": "setuptools.build_meta",
        "port_distribution": "soluprot",
        "port_artifact_version": "1.1.0",
        "official_release_equivalence": "not_claimed",
    }
    assert set(installed_code) == {
        "feature_scripts/KMerF.py",
        "feature_scripts/__init__.py",
        "feature_scripts/blast6_to_max_id_csv.py",
        "feature_scripts/common/FastaChunk.py",
        "feature_scripts/common/__init__.py",
        "feature_scripts/common/clear_dir.py",
        "feature_scripts/common/get_abs_path.py",
        "feature_scripts/common/prefix.py",
        "feature_scripts/common/seq_count_fa.py",
        "feature_scripts/dimers_comb.py",
        "feature_scripts/physico_chemical.py",
        "soluprot_core/__init__.py",
        "soluprot_core/cli.py",
        "soluprot_core/exceptions.py",
        "soluprot_core/features.py",
        "soluprot_core/model.py",
        "soluprot_core/parsers.py",
        "soluprot_core/paths.py",
    }
    assert installed_code["soluprot_core/cli.py"] == (
        "dbc94f9fc512f1b4cca000520896d49e5bab38b307312fbe2da0fb1f4159dbf5"
    )
    assert installed_code["soluprot_core/features.py"] == (
        "4dd9252e10efcd033aa8f43d555c05615cf2e6bfa004f77e25277b89219c6281"
    )
    assert installed_code["soluprot_core/model.py"] == (
        "c15b914967f32a679fd5d99c93c5af8f110410f2a88624a0b28b8bb633d821e1"
    )
    assert methods["full"].descriptor["model_identity"] == {
        "provider": "Protein Workbench project-maintained SoluProt port",
        "port_artifact_version": "1.1.0",
        "upstream_model_family": "SoluProt",
        "model_variant": "grad_clf_v1_tc",
    }
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
            "5.0.0",
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
    from modules.solubility.package import MODULE_PACKAGE

    catalog = build_frozen_catalog((MODULE_PACKAGE,))
    availability = {
        item.binding.contract_id: item
        for item in catalog.availability
    }

    for mode in ("full", "no_tm"):
        binding = catalog.require_contract(
            "binding",
            f"solubility.soluprot_{mode}.local",
            "5.0.0",
        )
        del binding
        snapshot = availability[f"solubility.soluprot_{mode}.local"]
        assert snapshot.result.is_available is True


def test_soluprot_requires_no_core_dispatch_or_readiness_branch() -> None:
    project_root = Path(__file__).resolve().parent.parent
    core_source = "\n".join(
        path.read_text()
        for path in sorted((project_root / "core").glob("*.py"))
    ).lower()

    assert "soluprot" not in core_source


def test_solubility_runtime_contracts_include_supported_target_assets() -> None:
    from modules.solubility.package import MODULE_PACKAGE

    catalog = build_frozen_catalog((MODULE_PACKAGE,))
    soluprot = catalog.require_contract(
        "binding",
        "solubility.soluprot_full.local",
        "5.0.0",
    ).descriptor
    protein_sol = catalog.require_contract(
        "binding",
        "solubility.protein_sol.local",
        "5.0.0",
    ).descriptor

    assert {
        field["name"] for field in soluprot["environment_fields"]
    } == {
        "python_executable",
        "site_packages_root",
        "usearch_executable",
        "perl_executable",
    }
    soluprot_prerequisites = soluprot["readiness_declaration"][
        "prerequisites"
    ]
    assert soluprot_prerequisites["python_runtime"] == {
        "minimum_version": "3.12",
        "soluprot_distribution_version": "1.1.0",
        "path_source": "trusted_environment_configuration",
    }
    assert soluprot_prerequisites["usearch"] == {
        "version": "12.0",
        "path_source": "trusted_environment_configuration",
    }
    assert soluprot_prerequisites["tmhmm"]["decoder"] == {
        "selection": "uname-system-and-machine",
        "identity": "executable-presence",
        "included": (
            "decodeanhmm.Darwin_arm64",
            "decodeanhmm.Linux_x86_64",
        ),
    }
    assert soluprot_prerequisites["tmhmm"]["bundled_asset_root"] == (
        "soluprot_assets/tmhmm-2.0d"
    )
    assert soluprot_prerequisites["tmhmm"]["path_source"] == (
        "installed_distribution"
    )

    protein_sol_prerequisites = protein_sol["readiness_declaration"][
        "prerequisites"
    ]
    assert protein_sol_prerequisites["bash"] == {
        "runtime_family": "GNU bash",
    }
    assert protein_sol_prerequisites["perl"] == {
        "minimum_major_version": 5,
    }
    runtime_contracts = repr(
        {
            "soluprot": soluprot_prerequisites,
            "protein_sol": protein_sol_prerequisites,
        }
    ).lower()
    assert "sha256" not in repr(
        soluprot_prerequisites["tmhmm"]["decoder"]
    ).lower()
    assert "macos" not in runtime_contracts


def test_soluprot_provider_failure_does_not_retain_stderr_or_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.solubility._local_support as local_support
    import modules.solubility.soluprot as adapter

    class FailedProcess:
        pid = 12345
        returncode = 7

        def communicate(self, timeout: int) -> tuple[bytes, bytes]:
            assert timeout == 300
            return b"", b"secret-token /private/provider/path"

        def kill(self) -> None:
            raise AssertionError("kill is not required")

    class Resources:
        @staticmethod
        @contextmanager
        def local_provider(provider_id: str):
            assert provider_id == "soluprot"
            yield {}

        @contextmanager
        def temporary_directory(self, *, prefix: str):
            assert prefix == "soluprot-full-"
            yield tmp_path

        @contextmanager
        def engine_invocation(self, *, engine_role: str):
            assert engine_role == "soluprot_full"
            yield "invocation-1"

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
        local_support.subprocess,
        "Popen",
        lambda *args, **kwargs: FailedProcess(),
    )
    monkeypatch.setattr(
        adapter,
        "_trusted_soluprot_environment",
        lambda *_args, **_kwargs: SimpleNamespace(
            perl_executable=Path("/private/perl")
        ),
    )
    monkeypatch.setattr(
        adapter,
        "_prepare_soluprot_invocation",
        lambda **_kwargs: (
            (("/private/python", "--no_tmhmm")),
            tmp_path / "output.csv",
        ),
    )

    with pytest.raises(
        adapter.SoluProtProviderNonzeroExit,
        match="failed safely",
    ) as rejected:
        adapter.LocalSoluProtAdapter(
            mode="full",
            environment={},
            resources=Resources(),
        ).predict(())

    assert "secret-token" not in str(rejected.value)
    assert "/private/" not in str(rejected.value)


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


def _run_soluprot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    mode: str,
    sequence: str = "ACDEFGHIKLMNPQRSTVWY",
    provider_error: BaseException | None = None,
) -> tuple[Any, V2RunService, dict[str, Any], tuple[dict[str, Any], ...]]:
    import modules.solubility.soluprot as adapter
    import modules.solubility.package as package
    from modules.solubility.package import MODULE_PACKAGE
    from tests.fixtures.folding_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    monkeypatch.setattr(
        package,
        "soluprot_readiness",
        lambda environment, *, mode: ReadinessResult(
            True,
            proof_source="direct-observation",
            reason_code=f"soluprot_{mode}_runtime_unavailable",
        ),
    )
    monkeypatch.setattr(
        adapter,
        "_prepare_soluprot_invocation",
        _prepare_soluprot_fixture,
    )
    calls: list[tuple[list[str], str]] = []

    def run_process(**kwargs: Any) -> int:
        sequences = [
            line
            for line in (
                kwargs["staging_directory"] / "input.fasta"
            ).read_text().splitlines()
            if not line.startswith(">")
        ]
        mode = (
            "no_tm"
            if "--no_tmhmm" in kwargs["command"]
            else "full"
        )
        calls.append((sequences, mode))
        if provider_error is not None:
            raise provider_error
        payload = b"runtime_id,fa_id,soluble\n" + (
            b"0,candidate_0,0.331\n"
            if mode == "full"
            else b"0,candidate_0,0.3465\n"
        )
        output_path = kwargs["staging_directory"] / "output.csv"
        output_path.write_bytes(payload)
        return 0

    monkeypatch.setattr(adapter, "_run_local_process", run_process)
    source = WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.folding_sequence_source",
        node_type_version="4.0.0",
        binding_id="contract_test.folding_sequence_source.direct",
        binding_version="4.0.0",
        node_parameters={"sequence": sequence},
        binding_parameters={},
    )
    score = WorkflowNodeInstance(
        node_id="score",
        node_type_id="solubility.score_sequence",
        node_type_version="5.0.0",
        binding_id=f"solubility.soluprot_{mode}.local",
        binding_version="5.0.0",
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
    committed = authoring.commit(
        project.id,
        workflow=WorkflowDocument(
            schema_version="2.1.0",
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
    service = V2RunService(
        projects,
        catalog,
        authoring,
        NodeAttemptFactory(
            projects,
            admit_environment_configuration(
                catalog,
                {
                    (f"solubility.soluprot_{mode}.local", "5.0.0"): {
                        "values": _soluprot_admitted_environment(
                            private_runtime_path="/must/not/publish",
                            include_tm=mode == "full",
                        ),
                    }
                },
            ),
            result_store(projects),
        ),
        result_store(projects),
    )
    try:
        receipt = service.start_background(
            project.id,
            workflow_commit_id=committed.workflow_commit_id,
            client_request_id=f"soluprot-{mode}",
        )
        service.shutdown()
        projection = public_run_projection(service, project.id, receipt["run_id"])
        events = public_run_events(service, project.id, receipt["run_id"])
    finally:
        service.shutdown()
    projection["_fixture_calls"] = calls
    return catalog, service, projection, events


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
    catalog, service, projection, events = _run_soluprot(
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
    subjects = _decode_output(catalog, service, projection, source_output)
    scores = _decode_output(catalog, service, projection, output)
    assert len(scores.entries) == 1
    observation = scores.entries[0]
    subject = subjects.items[0]
    assert observation.subject.candidate_id == subject.candidate_id
    assert observation.subject.data_type_id == "protein.sequence"
    assert observation.subject.content_digest == catalog.require_port_type(
        "protein.sequence",
        "3.0.0",
    ).content_digest(subject.data)
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
        and event["event"]["engine_identity"]
        == observation.method.contract_digest
    ]
    assert len(score_events) == 1
    assert "/must/not/publish" not in str((projection, events))


@pytest.mark.parametrize("mode", ("full", "no_tm"))
def test_soluprot_binding_factory_injects_one_immutable_mode_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    import modules.solubility.soluprot as adapter
    import modules.solubility.package as package

    constructed_modes: list[str] = []
    exact_adapter = adapter.LocalSoluProtAdapter

    def build_adapter(**kwargs: Any) -> Any:
        constructed_modes.append(kwargs["mode"])
        return exact_adapter(**kwargs)

    monkeypatch.setattr(package, "LocalSoluProtAdapter", build_adapter)

    _, _, projection, _ = _run_soluprot(
        tmp_path,
        monkeypatch,
        mode=mode,
    )

    assert projection["status"] == "succeeded"
    assert constructed_modes == [mode]


def test_soluprot_method_and_asset_contracts_separate_result_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, full, _ = _run_soluprot(
        tmp_path / "full",
        monkeypatch,
        mode="full",
    )
    _, _, no_tm, _ = _run_soluprot(
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
    catalog, _, projection, events = _run_soluprot(
        tmp_path,
        monkeypatch,
        mode="no_tm",
        sequence="ACDEFGHIKLMNPQRSTVW",
    )
    assert projection["status"] == "failed"
    assert projection["_fixture_calls"] == []
    method_digest = catalog.require_contract(
        "method",
        "solubility.soluprot_no_tm.v1_1_0",
        "3.0.0",
    ).contract_digest
    assert not any(
        event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_identity"] == method_digest
        for event in events
    )


def test_provider_failure_retains_a_closed_safe_reason_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.solubility.soluprot import SoluProtProviderNonzeroExit

    catalog, _, projection, events = _run_soluprot(
        tmp_path,
        monkeypatch,
        mode="full",
        provider_error=SoluProtProviderNonzeroExit(
            "SoluProt provider invocation failed safely (exit status 7)"
        ),
    )

    assert projection["status"] == "failed"
    method_digest = catalog.require_contract(
        "method",
        "solubility.soluprot_full.v1_1_0",
        "3.0.0",
    ).contract_digest
    invocation_id = next(
        event["event"]["invocation_id"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_identity"] == method_digest
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


def test_all_solubility_methods_pass_the_shared_contract_test_kit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.solubility.protein_sol as protein_sol_adapter
    import modules.solubility.soluprot as soluprot_adapter
    import modules.solubility.package as package
    from modules.solubility.package import MODULE_PACKAGE
    from tests.fixtures.folding_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    monkeypatch.setattr(
        package,
        "soluprot_readiness",
        lambda environment, *, mode: ReadinessResult(
            True,
            proof_source="direct-observation",
            reason_code=f"soluprot_{mode}_runtime_unavailable",
        ),
    )
    monkeypatch.setattr(
        package,
        "protein_sol_readiness",
        lambda environment: ReadinessResult(
            True,
            proof_source="direct-observation",
            reason_code="protein_sol_runtime_unavailable",
        ),
    )
    monkeypatch.setattr(
        soluprot_adapter,
        "_prepare_soluprot_invocation",
        _prepare_soluprot_fixture,
    )

    def run_soluprot_fixture(**kwargs: Any) -> int:
        output_path = kwargs["staging_directory"] / "output.csv"
        mode = (
            "no_tm"
            if "--no_tmhmm" in kwargs["command"]
            else "full"
        )
        output_path.write_bytes(
            b"runtime_id,fa_id,soluble\n"
            + (
                b"0,candidate_0,0.331\n"
                if mode == "full"
                else b"0,candidate_0,0.3465\n"
            )
        )
        return 0

    monkeypatch.setattr(
        soluprot_adapter,
        "_run_local_process",
        run_soluprot_fixture,
    )
    monkeypatch.setattr(
        protein_sol_adapter,
        "_prepare_protein_sol_invocation",
        _prepare_protein_sol_fixture,
    )

    def run_protein_sol_fixture(**kwargs: Any) -> int:
        output_path = kwargs["staging_directory"] / "seq_prediction.txt"
        output_path.write_bytes(
            b"HEADERS PREDICTIONS LINE,ID,percent-sol,scaled-sol,"
            b"population-sol,pI\n"
            b"SEQUENCE PREDICTIONS,>candidate_0,32.419,0.252,"
            b"0.446,7.130\n"
        )
        return 0

    monkeypatch.setattr(
        protein_sol_adapter,
        "_run_local_process",
        run_protein_sol_fixture,
    )
    source = WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.folding_sequence_source",
        node_type_version="4.0.0",
        binding_id="contract_test.folding_sequence_source.direct",
        binding_version="4.0.0",
        node_parameters={"sequence": "ACDEFGHIKLMNPQRSTVWYA"},
        binding_parameters={},
    )
    cases = tuple(
        ModulePackageContractCase(
            case_id=f"soluprot-{mode}",
            node_type_id="solubility.score_sequence",
            node_type_version="5.0.0",
            binding_id=f"solubility.soluprot_{mode}.local",
            binding_version="5.0.0",
            node_parameters={},
            binding_parameters={},
            environment_values=_soluprot_admitted_environment(
                private_runtime_path="/secret/runtime",
                include_tm=mode == "full",
            ),
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
    ) + (
        ModulePackageContractCase(
            case_id="protein-sol",
            node_type_id="solubility.score_sequence",
            node_type_version="5.0.0",
            binding_id="solubility.protein_sol.local",
            binding_version="5.0.0",
            node_parameters={},
            binding_parameters={},
            environment_values=_protein_sol_admitted_environment(
                private_runtime_path="/secret/runtime"
            ),
            workflow_nodes=(source,),
            workflow_edges=(
                WorkflowEdge(
                    "source",
                    "sequence_candidates",
                    "contract-test-node",
                    "sequence_candidates",
                ),
            ),
            expected_observation_counts={"scores": 3},
            forbidden_public_fragments=("/secret/runtime",),
        ),
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
        "succeeded",
    ]
