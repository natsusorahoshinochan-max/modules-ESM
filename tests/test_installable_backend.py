"""Acceptance contract for the built, installed backend artifact."""

from __future__ import annotations

from collections import Counter
import importlib.util
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
import zipfile
from hashlib import sha256
from pathlib import Path

import pytest
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from core import build_discovered_frozen_catalog
from protein_workbench_public import (
    bundle_bytes,
    bundle_digest,
    prepare_run_event_stream_request,
    prepare_rest_request,
    validate_artifact_response,
    validate_event,
    validate_response,
)
from tests.fixtures.public_v2 import wait_for_network_run_terminal


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_PROTOCOL_BYTES = bundle_bytes()
SOURCE_PROTOCOL_DIGEST = bundle_digest()
SOURCE_PORT_CATALOG = build_discovered_frozen_catalog()
SOURCE_PORT_CATALOG_BYTES = SOURCE_PORT_CATALOG.catalog_descriptor_bytes
SOURCE_PORT_CATALOG_DIGEST = SOURCE_PORT_CATALOG.contract_digest
SOURCE_ZERO_CORE_CATALOG = build_discovered_frozen_catalog(
    "tests.fixtures.zero_core_packages"
)
SOURCE_ZERO_CORE_CATALOG_DIGEST = SOURCE_ZERO_CORE_CATALOG.contract_digest
SOURCE_PORT_TYPE_BYTES = {
    f"{definition.type_id}@{definition.version}": (
        definition.descriptor_bytes.hex()
    )
    for definition in SOURCE_PORT_CATALOG.port_types
}
SOURCE_PORT_TYPE_DIGESTS = {
    f"{definition.type_id}@{definition.version}": definition.contract_digest
    for definition in SOURCE_PORT_CATALOG.port_types
}
SOURCE_CONTRACT_REFERENCES = [
    contract.reference() for contract in SOURCE_PORT_CATALOG.contracts
]
EXPECTED_MODULE_IDS = {
    "compute.dssp",
    "convert.extract_backbone",
    "convert.extract_sequence",
    "convert.map_track",
    "convert.select_chains",
    "esm3.generate",
    "esm3.generate_sequence",
    "esm3.generate_structure",
    "esmfold2.fold",
    "export.sequence",
    "export.structure",
    "import.sequence",
    "import.structure",
    "prompt.add_function_annotation",
    "prompt.apply_residue_edits",
    "prompt.assemble_protein_prompt",
    "prompt.build_residue_layout",
    "prompt.compute_sasa",
    "prompt.compute_secondary_structure",
    "prompt.override_residue_track",
    "prompt.random_fixed_positions",
    "prompt.random_insert_masked",
    "prompt.random_mask",
    "proteinmpnn.constraints",
    "proteinmpnn.design",
    "proteinmpnn.score",
    "scoring.aggregate_confidence",
    "scoring.merge",
    "scoring.ss_agreement",
    "selection.concat",
    "selection.diversity",
    "selection.filter",
    "selection.pareto",
    "selection.sort",
    "selection.top_k",
    "selection.weighted_rank",
    "simplefold.evaluate",
    "simplefold.fold",
    "structure.align",
    "structure.batch_tm_score",
    "structure.pairwise_align",
    "structure.rmsd",
    "structure.tm_score",
    "stub.echo",
}


def _installed_direct_server_probe(port: int) -> str:
    """Start an installed backend with one externally discovered package."""
    return r'''
import os
from pathlib import Path
import sys
import uvicorn
from core.server import create_app

sys.path.insert(0, str(Path.cwd()))
app = create_app(
    module_packages_package="zero_core_packages",
    v2_environment_configuration={
        ("contract_test.synthetic_echo.direct", "2.0.0"): {
            "values": {
                "fixture_ready": True,
                "credential": "installed-secret-must-not-publish",
                "runtime_path": "/private/installed-runtime",
                "block_marker": os.environ[
                    "PROTEIN_WORKBENCH_INSTALLED_BLOCK_MARKER"
                ],
            },
            "safe_fingerprint": "installed-synthetic-echo-v1",
            "invalidation_token": "installed-synthetic-assets-v1",
        },
    },
)
uvicorn.run(app, host="127.0.0.1", port=__PORT__, log_level="warning")
'''.replace("__PORT__", str(port))


def _installed_collection_ops_server_probe(port: int) -> str:
    """Start installed collection operations with an external source package."""
    return r'''
from pathlib import Path
import sys
import uvicorn
from core import build_frozen_catalog
from core.server import create_app
from modules.collection_ops.package import MODULE_PACKAGE as COLLECTION_OPS

sys.path.insert(0, str(Path.cwd()))
from collection_ops_sources.package import MODULE_PACKAGE as SOURCES

app = create_app(
    frozen_catalog_override=build_frozen_catalog(
        (COLLECTION_OPS, SOURCES)
    ),
)
uvicorn.run(app, host="127.0.0.1", port=__PORT__, log_level="warning")
'''.replace("__PORT__", str(port))


def _installed_canonical_v2_server_probe(
    port: int,
    *,
    provider_site_packages: Path,
    esm_source_root: Path,
) -> str:
    """Start the installed backend with controlled provider boundaries."""
    return (
        r'''
from pathlib import Path
import sys

import core
import modules
import uvicorn
from core.server import create_app

source_root = Path("__SOURCE_ROOT__").resolve()
assert not Path(core.__file__).resolve().is_relative_to(source_root)
assert not Path(modules.__file__).resolve().is_relative_to(source_root)
sys.path.append(str(Path.cwd()))
sys.path.append("__PROVIDER_SITE_PACKAGES__")
sys.path.append("__ESM_SOURCE_ROOT__")

from canonical_3gb1_v2 import (
    ControlledESM3Client,
    ControlledFoldingClient,
    ControlledProteinMPNNProvider,
    controlled_catalog,
    controlled_environment,
)
import modules.proteinmpnn.implementation as proteinmpnn_implementation

esm3 = ControlledESM3Client()
folding = ControlledFoldingClient()
proteinmpnn = ControlledProteinMPNNProvider()
proteinmpnn_implementation.provider_for_environment = (
    lambda environment, *, staging_directory: proteinmpnn
)
app = create_app(
    frozen_catalog_override=controlled_catalog(),
    v2_environment_configuration=controlled_environment(esm3, folding),
)
uvicorn.run(app, host="127.0.0.1", port=__PORT__, log_level="warning")
'''
        .replace("__PORT__", str(port))
        .replace("__SOURCE_ROOT__", str(PROJECT_ROOT))
        .replace(
            "__PROVIDER_SITE_PACKAGES__",
            str(provider_site_packages),
        )
        .replace("__ESM_SOURCE_ROOT__", str(esm_source_root))
    )


def _build_artifacts(output_dir: Path) -> tuple[Path, Path]:
    subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "build_backend.py"),
            str(output_dir),
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )
    wheels = list(output_dir.glob("protein_workbench-*.whl"))
    sdists = list(output_dir.glob("protein_workbench-*.tar.gz"))
    assert len(wheels) == 1
    assert len(sdists) == 1
    return wheels[0], sdists[0]


@pytest.mark.installed_package
def test_built_artifacts_contain_backend_definitions_and_canonical_assets(
    tmp_path: Path,
) -> None:
    wheel, sdist = _build_artifacts(tmp_path / "dist")

    with zipfile.ZipFile(wheel) as archive:
        wheel_entries = archive.infolist()
        wheel_names = {entry.filename for entry in wheel_entries}
    with tarfile.open(sdist) as archive:
        sdist_entries = archive.getmembers()
        sdist_names = {
            name.split("/", 1)[1]
            for name in (entry.name for entry in sdist_entries)
            if "/" in name
        }

    required_names = {
        "examples/3gb1_pipeline.json",
        "examples/3gb1_pipeline_ui.json",
        "examples/v2/capability-inventory.json",
        "examples/v2/canonical-3gb1.workflow.json",
        "examples/v2/repository-capabilities.workflow.json",
        "examples/v2_suite.py",
        "modules/collection_ops/definitions/concat_candidates.yaml",
        "modules/collection_ops/definitions/merge_scores.yaml",
        "modules/collection_ops/definitions/rebind_candidate_pairing.yaml",
        "modules/collection_ops/definitions/take_candidates.yaml",
        "modules/esm3/definitions/generate_paired.yaml",
        "modules/esm3/definitions/generate_sequence.yaml",
        "modules/esm3/definitions/generate_structure.yaml",
        "modules/esm3/definitions/pae_metric.yaml",
        "modules/folding/definitions/fold.yaml",
        "modules/folding/definitions/pae_metric.yaml",
        "modules/folding/definitions/plddt_mean_residue_metric.yaml",
        "modules/folding/definitions/plddt_per_residue_metric.yaml",
        "modules/folding/definitions/ptm_metric.yaml",
        "modules/proteinmpnn/definitions/constraints.yaml",
        "modules/proteinmpnn/definitions/design.yaml",
        "modules/proteinmpnn/definitions/native_sequence_nll_metric.yaml",
        "modules/proteinmpnn/definitions/random_fixed_positions.yaml",
        "modules/proteinmpnn/definitions/score.yaml",
        "modules/prompt_authoring/definitions/override_protein_prompt_track.yaml",
        "modules/prompt_authoring/definitions/prompt_from_structure.yaml",
        "modules/selection/definitions/diversity.yaml",
        "modules/selection/definitions/pareto.yaml",
        "modules/selection/definitions/weighted_rank.yaml",
        "modules/solubility/definitions/score_sequence.yaml",
        "modules/solubility/definitions/protein_sol_percent_metric.yaml",
        "modules/solubility/definitions/protein_sol_scaled_metric.yaml",
        "modules/solubility/definitions/protein_sol_pi_metric.yaml",
        "modules/solubility/definitions/soluprot_probability_metric.yaml",
        "modules/structure_comparison/definitions/align_pairwise.yaml",
        "modules/structure_comparison/definitions/align_single.yaml",
        "modules/structure_comparison/definitions/batch_tm_score.yaml",
        "modules/structure_comparison/definitions/rmsd.yaml",
        "modules/structure_comparison/definitions/rmsd_metric.yaml",
        "modules/structure_comparison/definitions/tm_score.yaml",
        "modules/structure_comparison/definitions/tm_score_metric.yaml",
        "pdbs/3GB1.pdb",
        "protein_workbench_public/resources/v2/bundle.json",
    }
    required_names.update(
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in PROJECT_ROOT.glob("modules/**/definition*.yaml")
    )

    assert required_names <= wheel_names
    assert required_names <= sdist_names
    assert {
        "docs/backend-verification.md",
        "docs/provider-install-contract.md",
        "scripts/build_backend.py",
        "scripts/verify_backend.py",
        "uv.lock",
    } <= sdist_names
    assert not any(name.startswith(("keys/", "repositories/")) for name in wheel_names)
    assert not any(name.startswith(("keys/", "repositories/")) for name in sdist_names)
    assert not any(
        name.startswith("modules/")
        and {"test", "tests", "fixture", "fixtures"}.intersection(
            Path(name).parts
        )
        for name in wheel_names | sdist_names
    )
    assert not any(
        name.startswith("tests/fixtures/zero_core_packages/")
        for name in wheel_names
    )
    assert all(
        not name.startswith("/") and ".." not in Path(name).parts
        for name in wheel_names | sdist_names
    )
    assert all(
        not stat.S_ISLNK(entry.external_attr >> 16)
        and not ((entry.external_attr >> 16) & 0o002)
        for entry in wheel_entries
    )
    assert all(
        not entry.issym() and not entry.islnk() and not (entry.mode & 0o002)
        for entry in sdist_entries
    )


@pytest.mark.installed_package
def test_release_artifacts_are_reproducible(tmp_path: Path) -> None:
    first_wheel, first_sdist = _build_artifacts(tmp_path / "first")
    second_wheel, second_sdist = _build_artifacts(tmp_path / "second")

    assert sha256(first_wheel.read_bytes()).digest() == sha256(
        second_wheel.read_bytes()
    ).digest()
    assert sha256(first_sdist.read_bytes()).digest() == sha256(
        second_sdist.read_bytes()
    ).digest()


@pytest.mark.installed_package
def test_wheel_runs_discovery_canonical_validation_and_api_outside_source_tree(
    tmp_path: Path,
) -> None:
    wheel, _ = _build_artifacts(tmp_path / "dist")
    venv_dir = tmp_path / "installed"
    subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
    python = venv_dir / "bin" / "python"
    subprocess.run(
        [str(python), "-m", "pip", "install", str(wheel)],
        cwd=tmp_path,
        check=True,
    )

    run_dir = tmp_path / "outside-source"
    run_dir.mkdir()
    shutil.copytree(
        PROJECT_ROOT / "tests" / "fixtures" / "zero_core_packages",
        run_dir / "zero_core_packages",
        ignore=shutil.ignore_patterns("tests", "__pycache__", "*.pyc"),
    )
    shutil.copytree(
        PROJECT_ROOT / "tests" / "fixtures" / "collection_ops_sources",
        run_dir / "collection_ops_sources",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PROTEIN_WORKBENCH_SOURCE_ROOT"] = str(PROJECT_ROOT)
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        root = tmp_path / name.lower()
        root.mkdir()
        env[f"PROTEIN_WORKBENCH_{name}_ROOT"] = str(root)
    block_marker = tmp_path / "installed-run.block"
    env["PROTEIN_WORKBENCH_INSTALLED_BLOCK_MARKER"] = str(block_marker)

    expected = repr(sorted(EXPECTED_MODULE_IDS))
    probe = f"""
from pathlib import Path
import json
import core
import examples
import modules
from core import (
    ModuleRegistry,
    TypeRegistry,
    build_discovered_frozen_catalog,
    discover_modules,
)
from protein_workbench_public import bundle_bytes, bundle_digest
import protein_workbench_public
from examples.v2_suite import verify_repository_examples

source_root = Path(__import__("os").environ["PROTEIN_WORKBENCH_SOURCE_ROOT"]).resolve()
assert source_root not in Path(core.__file__).resolve().parents
assert source_root not in Path(modules.__file__).resolve().parents
assert source_root not in Path(protein_workbench_public.__file__).resolve().parents
assert bundle_bytes().hex() == {SOURCE_PROTOCOL_BYTES.hex()!r}
assert bundle_digest() == {SOURCE_PROTOCOL_DIGEST!r}
catalog = build_discovered_frozen_catalog()
assert catalog.catalog_descriptor_bytes.hex() == {SOURCE_PORT_CATALOG_BYTES.hex()!r}
assert catalog.contract_digest == {SOURCE_PORT_CATALOG_DIGEST!r}
assert {{
    f"{{definition.type_id}}@{{definition.version}}": (
        definition.descriptor_bytes.hex()
    )
    for definition in catalog.port_types
}} == {SOURCE_PORT_TYPE_BYTES!r}
assert {{
    f"{{definition.type_id}}@{{definition.version}}": (
        definition.contract_digest
    )
    for definition in catalog.port_types
}} == {SOURCE_PORT_TYPE_DIGESTS!r}
inventory = json.loads(
    (
        Path(examples.__file__).resolve().parent
        / "v2"
        / "capability-inventory.json"
    ).read_text(encoding="utf-8")
)
assert inventory["contracts"] == {SOURCE_CONTRACT_REFERENCES!r}
assert verify_repository_examples() == {{
    "catalog_contract_digest": {SOURCE_PORT_CATALOG_DIGEST!r},
    "package_count": 11,
    "node_type_count": 48,
    "workflow_count": 2,
}}
assert {{
    (
        contract.contract_kind,
        contract.contract_id,
        contract.contract_version,
    )
    for contract in catalog.contracts
    if contract.contract_id.startswith("esm3.")
}} >= {{
    ("node_type", "esm3.generate_sequence", "2.0.0"),
    ("node_type", "esm3.generate_structure", "2.0.0"),
    ("node_type", "esm3.generate_paired", "2.0.0"),
    ("binding", "esm3.generate_sequence.biohub_medium", "2.0.0"),
    ("binding", "esm3.generate_structure.biohub_medium", "2.0.0"),
    ("binding", "esm3.generate_paired.biohub_medium", "2.0.0"),
    ("binding", "esm3.generate_sequence.biohub_open", "2.0.0"),
    ("binding", "esm3.generate_structure.biohub_open", "2.0.0"),
    ("binding", "esm3.generate_paired.biohub_open", "2.0.0"),
}}
assert {{
    (
        contract.contract_kind,
        contract.contract_id,
        contract.contract_version,
    )
    for contract in catalog.contracts
    if contract.contract_id.startswith("folding.")
}} >= {{
    ("node_type", "folding.fold", "2.0.0"),
    ("binding", "folding.fold.esmfold2_remote", "2.0.0"),
    ("binding", "folding.fold.esmfold2_local", "2.0.0"),
    ("binding", "folding.fold.simplefold_local", "2.0.0"),
}}
assert {{
    (
        contract.contract_kind,
        contract.contract_id,
        contract.contract_version,
    )
    for contract in catalog.contracts
    if contract.contract_id.startswith("proteinmpnn.")
}} >= {{
    ("node_type", "proteinmpnn.constraints", "2.0.0"),
    ("node_type", "proteinmpnn.random_fixed_positions", "2.0.0"),
    ("node_type", "proteinmpnn.design", "2.0.0"),
    ("node_type", "proteinmpnn.score", "2.0.0"),
    ("metric", "proteinmpnn.native_sequence_nll", "2.0.0"),
    ("method", "proteinmpnn.score.v_48_020_8907e667", "2.0.0"),
    ("binding", "proteinmpnn.constraints.local", "2.0.0"),
    ("binding", "proteinmpnn.random_fixed_positions.local", "2.0.0"),
    ("binding", "proteinmpnn.design.local", "2.0.0"),
    ("binding", "proteinmpnn.score.local", "2.0.0"),
}}
assert {{
    (
        contract.contract_kind,
        contract.contract_id,
        contract.contract_version,
    )
    for contract in catalog.contracts
    if contract.contract_id.startswith("solubility.")
}} >= {{
    ("node_type", "solubility.score_sequence", "2.0.0"),
    ("metric", "solubility.soluprot_probability", "2.0.0"),
    ("metric", "solubility.protein_sol_percent", "2.0.0"),
    ("metric", "solubility.protein_sol_scaled", "2.0.0"),
    ("metric", "solubility.protein_sol_pi", "2.0.0"),
    ("method", "solubility.soluprot_full.v1_1_0", "2.0.0"),
    ("method", "solubility.soluprot_no_tm.v1_1_0", "2.0.0"),
    (
        "method",
        "solubility.protein_sol.sequence_prediction_2017",
        "2.0.0",
    ),
    ("binding", "solubility.soluprot_full.local", "2.0.0"),
    ("binding", "solubility.soluprot_no_tm.local", "2.0.0"),
    ("binding", "solubility.protein_sol.local", "2.0.0"),
}}
assert {{
    (
        contract.contract_kind,
        contract.contract_id,
        contract.contract_version,
    )
    for contract in catalog.contracts
    if contract.contract_id.startswith("collection_ops.")
}} == {{
    ("node_type", "collection_ops.concat_candidates", "2.0.0"),
    ("node_type", "collection_ops.merge_scores", "2.0.0"),
    ("node_type", "collection_ops.rebind_candidate_pairing", "2.0.0"),
    ("node_type", "collection_ops.take_candidates", "2.0.0"),
    ("method", "collection_ops.concat_candidates.method", "2.0.0"),
    ("method", "collection_ops.merge_scores.method", "2.0.0"),
    ("method", "collection_ops.rebind_candidate_pairing.method", "2.0.0"),
    ("method", "collection_ops.take_candidates.method", "2.0.0"),
    ("binding", "collection_ops.concat_candidates.direct", "2.0.0"),
    ("binding", "collection_ops.merge_scores.direct", "2.0.0"),
    ("binding", "collection_ops.rebind_candidate_pairing.direct", "2.0.0"),
    ("binding", "collection_ops.take_candidates.direct", "2.0.0"),
}}
assert {{
    (
        contract.contract_kind,
        contract.contract_id,
        contract.contract_version,
    )
    for contract in catalog.contracts
    if contract.contract_id.startswith("selection.")
}} >= {{
    (kind, f"selection.{{operation}}{{suffix}}", "2.0.0")
    for operation in ("weighted_rank", "pareto", "diversity")
    for kind, suffix in (
        ("node_type", ""),
        ("method", ".method"),
        ("binding", ".direct"),
    )
}}

registry = ModuleRegistry(TypeRegistry())
discover_modules(registry)
assert sorted(item.module_id for item in registry.list_all()) == {expected}
"""
    subprocess.run(
        [str(python), "-I", "-c", probe],
        cwd=run_dir,
        env=env,
        check=True,
    )

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    server_command = [
        str(python),
        "-I",
        "-c",
        _installed_direct_server_probe(port),
    ]

    def launch_server() -> subprocess.Popen[str]:
        return subprocess.Popen(
            server_command,
            cwd=run_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

    server = launch_server()
    try:
        deadline = time.monotonic() + 20
        modules_payload = None
        while time.monotonic() < deadline:
            if server.poll() is not None:
                break
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/modules",
                    timeout=1,
                ) as response:
                    modules_payload = json.load(response)
                break
            except (OSError, json.JSONDecodeError):
                time.sleep(0.1)
        if modules_payload is None:
            output = server.communicate(timeout=5)[0]
            pytest.fail(f"Installed API did not start:\n{output}")
        assert sorted(item["module_id"] for item in modules_payload) == sorted(
            EXPECTED_MODULE_IDS
        )
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/projects",
            timeout=2,
        ) as response:
            projects = json.load(response)
        canonical = [
            project
            for project in projects
            if project["id"] == "canonical-3gb1"
        ]
        assert len(canonical) == 1
        assert canonical[0]["seed"] is True
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/v2/protocol",
            timeout=2,
        ) as response:
            installed_protocol_bytes = response.read()
            installed_protocol_digest = response.headers["Digest"]
        assert installed_protocol_bytes == SOURCE_PROTOCOL_BYTES
        assert installed_protocol_digest == SOURCE_PROTOCOL_DIGEST

        def request_json(
            operation_id: str,
            payload: dict,
            *,
            expected_status: int = 200,
        ) -> dict:
            prepared = prepare_rest_request(operation_id, payload)
            encoded = (
                json.dumps(prepared.json_body).encode("utf-8")
                if prepared.json_body is not None
                else None
            )
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}{prepared.route}",
                data=encoded,
                headers=(
                    {"Content-Type": "application/json"}
                    if encoded is not None
                    else {}
                ),
                method=prepared.method,
            )
            try:
                response = urllib.request.urlopen(request, timeout=2)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                status = response.status
                result = json.load(response)
            assert status == expected_status
            validate_response(operation_id, status, result)
            return result

        def wait_terminal(run_id: str) -> dict:
            return wait_for_network_run_terminal(
                websocket_origin=f"ws://127.0.0.1:{port}",
                project_id=project_id,
                run_id=run_id,
                fetch_projection=lambda: request_json(
                    "run_projection",
                    {
                        "project_id": project_id,
                        "run_id": run_id,
                    },
                ),
            )

        installed_catalog = request_json("catalog_snapshot", {})
        assert installed_catalog["catalog_contract_digest"] == (
            SOURCE_ZERO_CORE_CATALOG_DIGEST
        )
        assert any(
            contract["reference"]["contract_kind"] == "binding"
            and contract["reference"]["contract_id"]
            == "contract_test.synthetic_echo.direct"
            for contract in installed_catalog["contracts"]
        )

        legacy_project_request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/projects",
            data=json.dumps(
                {"name": "installed v2 authoring"}
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(
            legacy_project_request,
            timeout=2,
        ) as response:
            project_id = json.load(response)["id"]
        workflow = {
            "schema_version": "2.0.0",
            "workflow_id": project_id,
            "nodes": [
                {
                    "node_id": "synthetic-echo",
                    "node_type_id": "contract_test.synthetic_echo",
                    "node_type_version": "2.0.0",
                    "binding_id": "contract_test.synthetic_echo.direct",
                    "binding_version": "2.0.0",
                    "node_parameters": {"message": "INSTALLED"},
                    "binding_parameters": {"repeat_count": 1},
                }
            ],
            "edges": [],
            "contract_lock": [],
        }
        saved = request_json(
            "save_project_workflow",
            {
                "project_id": project_id,
                "expected_workflow_revision": 0,
                "workflow": workflow,
            },
        )
        loaded = request_json(
            "project_workflow_snapshot",
            {"project_id": project_id},
        )
        relocked = request_json(
            "relock_project_workflow",
            {"project_id": project_id, "workflow_revision": 1},
        )
        rejected = request_json(
            "workflow_compile",
            {
                "project_id": project_id,
                "workflow_revision": 1,
                "workflow": relocked["workflow"],
            },
            expected_status=422,
        )
        compiled = request_json(
            "workflow_compile",
            {
                "project_id": project_id,
                "workflow_revision": 2,
                "workflow": relocked["workflow"],
            },
        )
        assert saved["workflow_revision"] == 1
        assert loaded == saved
        assert relocked["workflow_revision"] == 2
        assert rejected["error"]["code"] == "compile_rejected"
        assert compiled["accepted"] is True
        assert compiled["workflow_revision"] == 2
        assert "execution_plan" not in compiled
        started = request_json(
            "start_run",
            {
                "project_id": project_id,
                "workflow_revision": 2,
                "compile_id": compiled["compile_id"],
                "client_request_id": "installed-direct-request",
            },
            expected_status=202,
        )
        projection = wait_terminal(started["run_id"])
        assert projection["status"] == "succeeded"
        assert projection["compile_id"] == compiled["compile_id"]
        assert projection["workflow_revision"] == 2
        assert projection["node_dispositions"] == [
            {
                "node_id": "synthetic-echo",
                "outcome": "succeeded",
                "resolution": "executed",
                "terminal_sequence": projection[
                    "node_dispositions"
                ][0]["terminal_sequence"],
                "blocked_by": [],
            }
        ]
        assert {
            output["output_port"]: output["values"]
            for output in projection["outputs"]
            if output["output_port"] == "text"
        } == {"text": ["INSTALLED"]}
        assert len(projection["artifact_index"]) == 1
        artifact = projection["artifact_index"][0]
        artifact_request = prepare_rest_request(
            "artifact_retrieval",
            {
                "project_id": project_id,
                "run_id": started["run_id"],
                "artifact_reference": artifact["artifact_reference"],
            },
        )
        with urllib.request.urlopen(
            urllib.request.Request(
                f"http://127.0.0.1:{port}{artifact_request.route}",
                method=artifact_request.method,
            ),
            timeout=2,
        ) as response:
            installed_artifact = response.read()
            installed_artifact_digest = response.headers["Digest"]
            content_disposition = response.headers["Content-Disposition"]
            artifact_headers = dict(response.headers)
        validate_artifact_response(
            {
                "artifact": artifact,
                "content_disposition": content_disposition,
            },
            artifact_headers,
            installed_artifact,
        )
        assert installed_artifact == b"INSTALLED"
        assert installed_artifact_digest == artifact["content_digest"]
        derived = request_json(
            "start_derived_run",
            {
                "project_id": project_id,
                "source_run_id": started["run_id"],
                "compile_id": compiled["compile_id"],
                "policy": "force_selected",
                "node_ids": ["synthetic-echo"],
                "client_request_id": "installed-derived-request",
            },
            expected_status=202,
        )
        derived_projection = wait_terminal(derived["run_id"])
        assert derived_projection["derived_from_run_id"] == started["run_id"]

        block_marker.write_text("block")
        interrupted = request_json(
            "start_run",
            {
                "project_id": project_id,
                "workflow_revision": 2,
                "compile_id": compiled["compile_id"],
                "client_request_id": "installed-restart-request",
            },
            expected_status=202,
        )
        interrupted_run_id = interrupted["run_id"]
        entered_marker = block_marker.with_suffix(".started")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not entered_marker.exists():
            time.sleep(0.05)
        assert entered_marker.is_file()

        stream_request = prepare_run_event_stream_request(
            {
                "project_id": project_id,
                "run_id": interrupted_run_id,
            }
        )
        assert stream_request.transport == "websocket"
        websocket_url = f"ws://127.0.0.1:{port}{stream_request.route}"
        with connect(
            websocket_url,
            open_timeout=5,
            close_timeout=2,
        ) as websocket:
            first_delivery = []
            while True:
                message = json.loads(websocket.recv(timeout=5))
                validate_event(message)
                first_delivery.append(message)
                if message["event"]["type"] == "replay_complete":
                    break
        first_durable = [
            message
            for message in first_delivery
            if message["event"]["type"] not in {
                "replay_started",
                "replay_complete",
            }
        ]
        invocation_started = next(
            message
            for message in first_durable
            if message["event"]["type"] == "engine_invocation_started"
        )
        resume_cursor = first_delivery[-1]["cursor"]

        server.kill()
        server.communicate(timeout=5)
        server = launch_server()
        deadline = time.monotonic() + 20
        interrupted_projection = None
        while time.monotonic() < deadline:
            if server.poll() is not None:
                break
            try:
                interrupted_projection = request_json(
                    "run_projection",
                    {
                        "project_id": project_id,
                        "run_id": interrupted_run_id,
                    },
                )
                break
            except (OSError, json.JSONDecodeError):
                time.sleep(0.1)
        if interrupted_projection is None:
            output = server.communicate(timeout=5)[0]
            pytest.fail(f"Restarted installed API did not recover:\n{output}")
        assert interrupted_projection["status"] == "interrupted"
        assert interrupted_projection["outputs"] == []
        assert interrupted_projection["artifact_index"] == []
        assert interrupted_projection["node_dispositions"][0]["outcome"] == (
            "interrupted"
        )

        resumed_stream_request = prepare_run_event_stream_request(
            {
                "project_id": project_id,
                "run_id": interrupted_run_id,
                "after_sequence": resume_cursor,
            }
        )
        with connect(
            f"ws://127.0.0.1:{port}{resumed_stream_request.route}",
            open_timeout=5,
            close_timeout=2,
        ) as websocket:
            resumed = []
            try:
                while True:
                    message = json.loads(websocket.recv(timeout=5))
                    validate_event(message)
                    resumed.append(message)
            except ConnectionClosed as closed:
                assert closed.rcvd is not None
                assert closed.rcvd.code == 1000
        resumed_durable = [
            message
            for message in resumed
            if message["event"]["type"] not in {
                "replay_started",
                "replay_complete",
            }
        ]
        invocation_terminal = next(
            message
            for message in resumed_durable
            if message["event"]["type"] == "engine_invocation_terminal"
            and message["event"]["invocation_id"]
            == invocation_started["event"]["invocation_id"]
        )
        assert invocation_terminal["event"]["status"] == "outcome_unknown"
        delivered_sequences = [
            message["sequence"]
            for message in (*first_durable, *resumed_durable)
        ]
        assert len(delivered_sequences) == len(set(delivered_sequences))
        terminal_cursor = interrupted_projection["ledger_cursor"]

        block_marker.unlink()
        server.kill()
        server.communicate(timeout=5)
        server = launch_server()
        deadline = time.monotonic() + 20
        repeated_projection = None
        while time.monotonic() < deadline:
            if server.poll() is not None:
                break
            try:
                repeated_projection = request_json(
                    "run_projection",
                    {
                        "project_id": project_id,
                        "run_id": interrupted_run_id,
                    },
                )
                break
            except (OSError, json.JSONDecodeError):
                time.sleep(0.1)
        if repeated_projection is None:
            output = server.communicate(timeout=5)[0]
            pytest.fail(f"Second installed restart did not recover:\n{output}")
        assert repeated_projection == interrupted_projection
        repeated_stream_request = prepare_run_event_stream_request(
            {
                "project_id": project_id,
                "run_id": interrupted_run_id,
                "after_sequence": terminal_cursor,
            }
        )
        with connect(
            f"ws://127.0.0.1:{port}{repeated_stream_request.route}",
            open_timeout=5,
            close_timeout=2,
        ) as websocket:
            repeated_delivery = []
            try:
                while True:
                    message = json.loads(websocket.recv(timeout=5))
                    validate_event(message)
                    repeated_delivery.append(message)
            except ConnectionClosed as closed:
                assert closed.rcvd is not None
                assert closed.rcvd.code == 1000
        assert {
            message["event"]["type"]
            for message in repeated_delivery
        } == {"replay_started", "replay_complete"}
        public_evidence = json.dumps(
            {
                "catalog": installed_catalog,
                "projection": projection,
                "interrupted": interrupted_projection,
                "replayed": resumed,
            },
            sort_keys=True,
        )
        assert "installed-secret-must-not-publish" not in public_evidence
        assert "/private/installed-runtime" not in public_evidence
        assert not any((tmp_path / "cache").rglob("*"))

        server.terminate()
        server.communicate(timeout=5)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        server = subprocess.Popen(
            [
                str(python),
                "-I",
                "-c",
                _installed_collection_ops_server_probe(port),
            ],
            cwd=run_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        deadline = time.monotonic() + 20
        collection_catalog = None
        while time.monotonic() < deadline:
            if server.poll() is not None:
                break
            try:
                collection_catalog = request_json("catalog_snapshot", {})
                break
            except (OSError, json.JSONDecodeError):
                time.sleep(0.1)
        if collection_catalog is None:
            output = server.communicate(timeout=5)[0]
            pytest.fail(
                "Installed collection operations API did not start:\n"
                f"{output}"
            )

        collection_contracts = {
            (
                contract["reference"]["contract_kind"],
                contract["reference"]["contract_id"],
            ): contract
            for contract in collection_catalog["contracts"]
        }
        assert {
            key
            for key in collection_contracts
            if key[1].startswith("collection_ops.")
        } == {
            ("node_type", "collection_ops.concat_candidates"),
            ("node_type", "collection_ops.merge_scores"),
            ("node_type", "collection_ops.rebind_candidate_pairing"),
            ("node_type", "collection_ops.take_candidates"),
            ("method", "collection_ops.concat_candidates.method"),
            ("method", "collection_ops.merge_scores.method"),
            ("method", "collection_ops.rebind_candidate_pairing.method"),
            ("method", "collection_ops.take_candidates.method"),
            ("binding", "collection_ops.concat_candidates.direct"),
            ("binding", "collection_ops.merge_scores.direct"),
            ("binding", "collection_ops.rebind_candidate_pairing.direct"),
            ("binding", "collection_ops.take_candidates.direct"),
        }
        merge_descriptor = collection_contracts[
            ("binding", "collection_ops.merge_scores.direct")
        ]["descriptor"]
        assert merge_descriptor["observation_propagation"] == {
            "schema_version": "2.0.0",
            "mode": "union",
            "output_port": "scores",
            "input_ports": ["scores_a", "scores_b", "scores_c"],
            "filter": None,
            "absent_input_policy": "ignore",
        }

        project_id = subprocess.run(
            [
                str(python),
                "-I",
                "-c",
                (
                    "import os;"
                    "from core.project import ProjectManager;"
                    "print(ProjectManager("
                    "root_dir=os.environ["
                    "'PROTEIN_WORKBENCH_PROJECT_ROOT'"
                    "]"
                    ").create("
                    "'installed collection operations'"
                    ").id)"
                ),
            ],
            cwd=run_dir,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert project_id

        def exact_reference(kind: str, contract_id: str) -> dict:
            return collection_contracts[(kind, contract_id)]["reference"]

        collection_workflow = {
            "schema_version": "2.0.0",
            "workflow_id": project_id,
            "nodes": [
                {
                    "node_id": "source-a",
                    "node_type_id": "contract_test.collection_ops_source",
                    "node_type_version": "2.0.0",
                    "binding_id": "contract_test.collection_ops_source.a",
                    "binding_version": "2.0.0",
                    "node_parameters": {"candidate_count": 2},
                    "binding_parameters": {},
                },
                {
                    "node_id": "source-b",
                    "node_type_id": "contract_test.collection_ops_source",
                    "node_type_version": "2.0.0",
                    "binding_id": "contract_test.collection_ops_source.b",
                    "binding_version": "2.0.0",
                    "node_parameters": {"candidate_count": 1},
                    "binding_parameters": {},
                },
                {
                    "node_id": "concat",
                    "node_type_id": "collection_ops.concat_candidates",
                    "node_type_version": "2.0.0",
                    "binding_id": "collection_ops.concat_candidates.direct",
                    "binding_version": "2.0.0",
                    "node_parameters": {},
                    "binding_parameters": {},
                },
                {
                    "node_id": "merge",
                    "node_type_id": "collection_ops.merge_scores",
                    "node_type_version": "2.0.0",
                    "binding_id": "collection_ops.merge_scores.direct",
                    "binding_version": "2.0.0",
                    "node_parameters": {},
                    "binding_parameters": {},
                },
            ],
            "edges": [
                {
                    "source_node_id": "source-a",
                    "source_port": "candidates",
                    "target_node_id": "concat",
                    "target_port": "candidates_a",
                },
                {
                    "source_node_id": "source-b",
                    "source_port": "candidates",
                    "target_node_id": "concat",
                    "target_port": "candidates_b",
                },
                {
                    "source_node_id": "source-a",
                    "source_port": "scores",
                    "target_node_id": "merge",
                    "target_port": "scores_a",
                },
                {
                    "source_node_id": "source-b",
                    "source_port": "scores",
                    "target_node_id": "merge",
                    "target_port": "scores_b",
                },
            ],
            "selection_objectives": [
                {
                    "objective_id": "partition-a-only",
                    "candidate_input": {
                        "node_id": "source-a",
                        "output_port": "candidates",
                    },
                    "score_collection_input": {
                        "node_id": "merge",
                        "output_port": "scores",
                    },
                    "source_partition": "contract_test.partition.a",
                    "metric": exact_reference(
                        "metric",
                        "contract_test.collection_ops_value",
                    ),
                    "method": exact_reference(
                        "method",
                        "contract_test.collection_ops_source.a.method",
                    ),
                    "context_selector": {"kind": "intrinsic"},
                    "utility_transform": exact_reference(
                        "utility_transform",
                        "contract_test.collection_ops_identity.a",
                    ),
                    "utility_parameters": {},
                    "weight": 1,
                    "match_cardinality": "exactly_one",
                    "missing_policy": "error",
                }
            ],
            "contract_lock": [],
        }
        saved = request_json(
            "save_project_workflow",
            {
                "project_id": project_id,
                "expected_workflow_revision": 0,
                "workflow": collection_workflow,
            },
        )
        relocked = request_json(
            "relock_project_workflow",
            {
                "project_id": project_id,
                "workflow_revision": saved["workflow_revision"],
            },
        )
        compiled = request_json(
            "workflow_compile",
            {
                "project_id": project_id,
                "workflow_revision": relocked["workflow_revision"],
                "workflow": relocked["workflow"],
            },
        )
        assert compiled["accepted"] is True

        def run_collection(request_id: str) -> dict:
            started = request_json(
                "start_run",
                {
                    "project_id": project_id,
                    "workflow_revision": relocked["workflow_revision"],
                    "compile_id": compiled["compile_id"],
                    "client_request_id": request_id,
                },
                expected_status=202,
            )
            return wait_terminal(started["run_id"])

        first_collection = run_collection("installed-collection-first")
        assert first_collection["status"] == "succeeded"
        first_outputs = {
            (output["node_id"], output["output_port"]): output["values"][0]
            for output in first_collection["outputs"]
        }
        source_a_candidates = first_outputs[("source-a", "candidates")]
        source_b_candidates = first_outputs[("source-b", "candidates")]
        concatenated = first_outputs[("concat", "candidates")]
        assert concatenated["$dataclass"] == "candidate_collection"
        assert concatenated["fields"]["items"] == [
            *source_a_candidates["fields"]["items"],
            *source_b_candidates["fields"]["items"],
        ]

        source_a_scores = first_outputs[("source-a", "scores")]
        source_b_scores = first_outputs[("source-b", "scores")]
        merged = first_outputs[("merge", "scores")]
        assert merged["$dataclass"] == "score_collection"
        assert merged["fields"]["entries"] == [
            *source_a_scores["fields"]["entries"],
            *source_b_scores["fields"]["entries"],
        ]
        assert [
            entry["fields"]["source_partition"]
            for entry in merged["fields"]["entries"]
        ] == [
            "contract_test.partition.a",
            "contract_test.partition.a",
            "contract_test.partition.b",
        ]

        second_collection = run_collection("installed-collection-second")
        assert second_collection["status"] == "succeeded"
        assert all(
            disposition["resolution"] == "cache_replayed"
            for disposition in second_collection["node_dispositions"]
        )
        second_outputs = {
            (output["node_id"], output["output_port"]): output["values"][0]
            for output in second_collection["outputs"]
        }
        assert second_outputs[("concat", "candidates")] == concatenated
        assert second_outputs[("merge", "scores")] == merged

        stream_request = prepare_run_event_stream_request(
            {
                "project_id": project_id,
                "run_id": second_collection["run_id"],
            }
        )
        with connect(
            f"ws://127.0.0.1:{port}{stream_request.route}",
            open_timeout=5,
            close_timeout=2,
        ) as websocket:
            replayed_events = []
            while True:
                message = json.loads(websocket.recv(timeout=5))
                validate_event(message)
                replayed_events.append(message)
                if message["event"]["type"] == "replay_complete":
                    break
        assert not {
            "operation_attempt_started",
            "engine_invocation_started",
        }.intersection(
            message["event"]["type"]
            for message in replayed_events
        )
    finally:
        if server.poll() is None:
            server.terminate()
        try:
            server.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.communicate()


@pytest.mark.installed_package
def test_installed_backend_runs_exact_canonical_v2_through_public_protocol(
    tmp_path: Path,
) -> None:
    """The built wheel completes canonical v2 with controlled providers."""
    wheel, _ = _build_artifacts(tmp_path / "dist")
    venv_dir = tmp_path / "installed"
    subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
    python = venv_dir / "bin" / "python"
    subprocess.run(
        [str(python), "-m", "pip", "install", str(wheel)],
        cwd=tmp_path,
        check=True,
    )

    torch_spec = importlib.util.find_spec("torch")
    assert torch_spec is not None and torch_spec.origin is not None
    provider_site_packages = Path(torch_spec.origin).resolve().parents[1]
    esm_source_root = PROJECT_ROOT / "repositories" / "esm"
    assert (esm_source_root / "esm" / "__init__.py").is_file()

    run_dir = tmp_path / "outside-source"
    run_dir.mkdir()
    shutil.copy2(
        PROJECT_ROOT / "tests" / "fixtures" / "canonical_3gb1_v2.py",
        run_dir / "canonical_3gb1_v2.py",
    )
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        root = tmp_path / name.lower()
        root.mkdir()
        env[f"PROTEIN_WORKBENCH_{name}_ROOT"] = str(root)

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    server = subprocess.Popen(
        [
            str(python),
            "-I",
            "-c",
            _installed_canonical_v2_server_probe(
                port,
                provider_site_packages=provider_site_packages,
                esm_source_root=esm_source_root,
            ),
        ],
        cwd=run_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    def request_json(
        operation_id: str,
        payload: dict,
        *,
        expected_status: int = 200,
    ) -> dict:
        prepared = prepare_rest_request(operation_id, payload)
        encoded = (
            json.dumps(prepared.json_body).encode("utf-8")
            if prepared.json_body is not None
            else None
        )
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}{prepared.route}",
            data=encoded,
            headers=(
                {"Content-Type": "application/json"}
                if encoded is not None
                else {}
            ),
            method=prepared.method,
        )
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            status = response.status
            result = json.load(response)
        assert status == expected_status
        validate_response(operation_id, status, result)
        return result

    try:
        deadline = time.monotonic() + 30
        catalog = None
        while time.monotonic() < deadline:
            if server.poll() is not None:
                break
            try:
                catalog = request_json("catalog_snapshot", {})
                break
            except (OSError, json.JSONDecodeError):
                time.sleep(0.1)
        if catalog is None:
            output = server.communicate(timeout=5)[0]
            pytest.fail(f"Installed canonical v2 API did not start:\n{output}")
        assert catalog["catalog_contract_digest"] == (
            SOURCE_PORT_CATALOG_DIGEST
        )

        project_id = "canonical-3gb1"
        snapshot = request_json(
            "project_workflow_snapshot",
            {"project_id": project_id},
        )
        assert snapshot["workflow"]["schema_version"] == "2.0.0"
        assert snapshot["workflow"]["contract_lock"]
        compiled = request_json(
            "workflow_compile",
            {
                "project_id": project_id,
                "workflow_revision": snapshot["workflow_revision"],
                "workflow": snapshot["workflow"],
            },
        )
        assert compiled["accepted"] is True
        started = request_json(
            "start_run",
            {
                "project_id": project_id,
                "workflow_revision": snapshot["workflow_revision"],
                "compile_id": compiled["compile_id"],
                "client_request_id": "installed-canonical-v2",
            },
            expected_status=202,
        )
        projection = wait_for_network_run_terminal(
            websocket_origin=f"ws://127.0.0.1:{port}",
            project_id=project_id,
            run_id=started["run_id"],
            fetch_projection=lambda: request_json(
                "run_projection",
                {
                    "project_id": project_id,
                    "run_id": started["run_id"],
                },
            ),
            timeout_seconds=90,
        )
        assert projection["status"] == "succeeded"
        assert len(projection["node_dispositions"]) == 21
        assert all(
            disposition["outcome"] == "succeeded"
            for disposition in projection["node_dispositions"]
        )

        outputs = {
            (output["node_id"], output["output_port"]): (
                output["values"][0]
            )
            for output in projection["outputs"]
        }

        def fields(node_id: str, port: str) -> dict:
            value = outputs[(node_id, port)]
            assert isinstance(value, dict)
            assert isinstance(value.get("fields"), dict)
            return value["fields"]

        generated_sequences = fields(
            "generate-paired",
            "sequence_candidates",
        )["items"]
        generated_structures = fields(
            "generate-paired",
            "structure_candidates",
        )["items"]
        counterpart_pairs = fields(
            "generate-paired",
            "counterpart_pairs",
        )["entries"]
        selected = fields("take-top-three", "candidates")["items"]
        children = fields(
            "design-children",
            "sequence_candidates",
        )["items"]
        final_folds = fields(
            "fold-final",
            "structure_candidates",
        )["items"]
        canonical_references = fields(
            "import-3gb1",
            "structure_candidates",
        )["items"]
        prompt = outputs[
            ("override-secondary-structure", "protein_prompt")
        ]
        prompt_sequence = prompt["sequence_track"]["fields"]["values"]
        prompt_secondary_structure = prompt[
            "secondary_structure_track"
        ]["fields"]["values"]
        prompt_visibility = prompt[
            "structure_visibility_track"
        ]["fields"]["values"]
        prompt_structure = prompt["structure_track"]["fields"]["values"]
        assert len(generated_sequences) == 10
        assert len(generated_structures) == 10
        assert len(counterpart_pairs) == 10
        assert len(selected) == 3
        assert len(children) == 15
        assert len(final_folds) == 15
        assert len(projection["artifact_index"]) == 15
        assert len({
            artifact["content_digest"]
            for artifact in projection["artifact_index"]
        }) == 15
        assert len(prompt_sequence) == 71
        assert prompt_sequence.count(None) == 35
        assert prompt_secondary_structure == [
            *(["E"] * 19),
            *([None] * 3),
            *(["H"] * 8),
            *([None] * 4),
            *(["E"] * 22),
            *([None] * 15),
        ]
        assert sum(
            structure is not None and visibility is True
            for structure, visibility in zip(
                prompt_structure,
                prompt_visibility,
                strict=True,
            )
        ) == 46

        generated_sequence_ids = [
            item["fields"]["candidate_id"]
            for item in generated_sequences
        ]
        generated_structure_ids = [
            item["fields"]["candidate_id"]
            for item in generated_structures
        ]
        assert [
            item["fields"]["parent_ids"]
            for item in generated_structures
        ] == [[candidate_id] for candidate_id in generated_sequence_ids]
        assert [
            (
                pair["fields"]["subject_candidate_id"],
                pair["fields"]["reference_candidate_id"],
            )
            for pair in counterpart_pairs
        ] == list(zip(
            generated_sequence_ids,
            generated_structure_ids,
            strict=True,
        ))

        rebound_pairs = fields(
            "rebind-counterparts",
            "pairing",
        )["entries"]
        fixed_alignments = outputs[
            ("align-fixed", "alignments")
        ]["alignments"]
        paired_alignments = outputs[
            ("align-paired", "alignments")
        ]["alignments"]
        canonical_reference_id = canonical_references[0]["fields"][
            "candidate_id"
        ]
        assert {
            alignment["reference"]["candidate_id"]
            for alignment in fixed_alignments
        } == {canonical_reference_id}
        assert {
            (
                alignment["subject"]["candidate_id"],
                alignment["reference"]["candidate_id"],
            )
            for alignment in paired_alignments
        } == {
            (
                pair["fields"]["subject_candidate_id"],
                pair["fields"]["reference_candidate_id"],
            )
            for pair in rebound_pairs
        }
        assert canonical_reference_id not in {
            alignment["reference"]["candidate_id"]
            for alignment in paired_alignments
        }

        child_parent_ids = [
            item["fields"]["parent_ids"][0] for item in children
        ]
        selected_ids = [
            item["fields"]["candidate_id"] for item in selected
        ]
        assert selected_ids == [
            "candidate-9f8a8c1b430ff92924b4480e6f68fecafb696d9044d9d1593d35a0a0e6a23ce2",
            "candidate-569ac9726a10ca1491a4a8a5f191cee3d216c45031ec54744e33b5703e461925",
            "candidate-88f6c50115f6aaaba9232835e6b4c070b90d620b8ae5a1ddea4b365a239f9964",
        ]
        assert Counter(child_parent_ids) == Counter({
            candidate_id: 5 for candidate_id in selected_ids
        })
        child_metadata = [
            dict(item["fields"]["metadata"]["$map"])
            for item in children
        ]
        assert {
            metadata["effective_seed"]
            for metadata in child_metadata
        } == {1603}
        child_call_seeds = {
            metadata["effective_call_seed"]
            for metadata in child_metadata
        }
        assert len(child_call_seeds) == 3
        child_ids = [
            item["fields"]["candidate_id"] for item in children
        ]
        assert [
            item["fields"]["parent_ids"] for item in final_folds
        ] == [[candidate_id] for candidate_id in child_ids]
        selection = projection["selection_results"][0]
        assert selection["selected_candidate_ids"][:3] == selected_ids
        assert [
            (
                objective["objective_id"],
                objective["source_partition"],
                objective["utility_transform"]["contract_id"],
                objective["declared_weight"],
                objective["effective_weight"],
            )
            for objective in selection["objectives"]
        ] == [
            (
                "fixed-3gb1",
                "structure_comparison.tm_score.fixed_reference",
                (
                    "structure_comparison.tm_score."
                    "fixed_reference.identity"
                ),
                0.7,
                0.7,
            ),
            (
                "paired-esm3",
                "structure_comparison.tm_score.per_subject_counterpart",
                (
                    "structure_comparison.tm_score."
                    "per_subject_counterpart.identity"
                ),
                0.3,
                0.3,
            ),
        ]

        for artifact in projection["artifact_index"]:
            prepared = prepare_rest_request(
                "artifact_retrieval",
                {
                    "project_id": project_id,
                    "run_id": started["run_id"],
                    "artifact_reference": artifact[
                        "artifact_reference"
                    ],
                },
            )
            with urllib.request.urlopen(
                urllib.request.Request(
                    f"http://127.0.0.1:{port}{prepared.route}",
                    method=prepared.method,
                ),
                timeout=5,
            ) as response:
                payload = response.read()
                headers = dict(response.headers)
                content_disposition = response.headers[
                    "Content-Disposition"
                ]
            validate_artifact_response(
                {
                    "artifact": artifact,
                    "content_disposition": content_disposition,
                },
                headers,
                payload,
            )
            assert "sha256:" + sha256(payload).hexdigest() == (
                artifact["content_digest"]
            )

        stream_request = prepare_run_event_stream_request(
            {
                "project_id": project_id,
                "run_id": started["run_id"],
            }
        )
        with connect(
            f"ws://127.0.0.1:{port}{stream_request.route}",
            open_timeout=5,
            close_timeout=2,
        ) as websocket:
            events = []
            while True:
                message = json.loads(websocket.recv(timeout=5))
                validate_event(message)
                if message["event"]["type"] not in {
                    "replay_started",
                    "replay_complete",
                }:
                    events.append(message)
                if message["event"]["type"] == "replay_complete":
                    break
        payloads = [message["event"] for message in events]
        assert payloads[-1] == {
            "type": "run_terminal",
            "status": "succeeded",
        }
        assert Counter(
            event["type"] for event in payloads
        )["node_disposition"] == 21
        operation_starts = Counter(
            event["operation_attempt_id"]
            for event in payloads
            if event["type"] == "operation_attempt_started"
        )
        operation_terminals = Counter(
            event["operation_attempt_id"]
            for event in payloads
            if event["type"] == "operation_attempt_terminal"
        )
        invocation_starts = Counter(
            event["invocation_id"]
            for event in payloads
            if event["type"] == "engine_invocation_started"
        )
        invocation_terminals = Counter(
            event["invocation_id"]
            for event in payloads
            if event["type"] == "engine_invocation_terminal"
        )
        assert operation_starts == operation_terminals
        assert invocation_starts == invocation_terminals
        assert set(operation_starts.values()) == {1}
        assert set(invocation_starts.values()) == {1}

        replay_started = request_json(
            "start_run",
            {
                "project_id": project_id,
                "workflow_revision": snapshot["workflow_revision"],
                "compile_id": compiled["compile_id"],
                "client_request_id": "installed-canonical-v2-replay",
            },
            expected_status=202,
        )
        replay = wait_for_network_run_terminal(
            websocket_origin=f"ws://127.0.0.1:{port}",
            project_id=project_id,
            run_id=replay_started["run_id"],
            fetch_projection=lambda: request_json(
                "run_projection",
                {
                    "project_id": project_id,
                    "run_id": replay_started["run_id"],
                },
            ),
            timeout_seconds=90,
        )
        def stable_outputs(value: dict) -> list[tuple]:
            return [
                (
                    output["node_id"],
                    output["output_port"],
                    output["port_type"],
                    output["content_digest"],
                    output["values"],
                )
                for output in value["outputs"]
            ]

        assert stable_outputs(replay) == stable_outputs(projection)
        assert replay["selection_results"] == (
            projection["selection_results"]
        )
        assert [
            artifact["content_digest"]
            for artifact in replay["artifact_index"]
        ] == [
            artifact["content_digest"]
            for artifact in projection["artifact_index"]
        ]

        tampered_artifact = projection["artifact_index"][0]
        managed = (
            tmp_path
            / "output"
            / project_id
            / started["run_id"]
            / "published"
            / tampered_artifact["artifact_reference"]
        )
        managed.write_bytes(b"TAMPERED")
        prepared = prepare_rest_request(
            "artifact_retrieval",
            {
                "project_id": project_id,
                "run_id": started["run_id"],
                "artifact_reference": tampered_artifact[
                    "artifact_reference"
                ],
            },
        )
        with pytest.raises(urllib.error.HTTPError) as rejected:
            urllib.request.urlopen(
                urllib.request.Request(
                    f"http://127.0.0.1:{port}{prepared.route}",
                    method=prepared.method,
                ),
                timeout=5,
            )
        assert rejected.value.status == 409
        with rejected.value:
            error = json.load(rejected.value)
        assert error["error"]["code"] == "artifact_integrity_mismatch"
    finally:
        if server.poll() is None:
            server.terminate()
        try:
            server.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.communicate()
