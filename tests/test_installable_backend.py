"""Acceptance contract for the built, installed backend artifact."""

from __future__ import annotations

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
        "modules/esm3/definitions/generate_paired.yaml",
        "modules/esm3/definitions/generate_sequence.yaml",
        "modules/esm3/definitions/generate_structure.yaml",
        "modules/esm3/definitions/pae_metric.yaml",
        "modules/folding/definitions/fold.yaml",
        "modules/folding/definitions/pae_metric.yaml",
        "modules/folding/definitions/plddt_mean_residue_metric.yaml",
        "modules/folding/definitions/plddt_per_residue_metric.yaml",
        "modules/folding/definitions/ptm_metric.yaml",
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
        for name in wheel_names
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
import core
import modules
from core import (
    ModuleRegistry,
    TypeRegistry,
    build_discovered_frozen_catalog,
    discover_modules,
)
from protein_workbench_public import bundle_bytes, bundle_digest
import protein_workbench_public

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
        projection = request_json(
            "run_projection",
            {
                "project_id": project_id,
                "run_id": started["run_id"],
            },
        )
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
        derived_projection = request_json(
            "run_projection",
            {
                "project_id": project_id,
                "run_id": derived["run_id"],
            },
        )
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
    finally:
        if server.poll() is None:
            server.terminate()
        try:
            server.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.communicate()
