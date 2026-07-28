"""Acceptance contract for the built, installed backend artifact."""

from __future__ import annotations

import json
import os
import socket
import stat
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from hashlib import sha256
from pathlib import Path

import pytest

from core import builtin_frozen_catalog
from protein_workbench_public import bundle_bytes, bundle_digest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_PROTOCOL_BYTES = bundle_bytes()
SOURCE_PROTOCOL_DIGEST = bundle_digest()
SOURCE_PORT_CATALOG = builtin_frozen_catalog()
SOURCE_PORT_CATALOG_BYTES = SOURCE_PORT_CATALOG.catalog_descriptor_bytes
SOURCE_PORT_CATALOG_DIGEST = SOURCE_PORT_CATALOG.contract_digest
SOURCE_PORT_TYPE_BYTES = {
    definition.type_id: definition.descriptor_bytes.hex()
    for definition in SOURCE_PORT_CATALOG.port_types
}
SOURCE_PORT_TYPE_DIGESTS = {
    definition.type_id: definition.contract_digest
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
    "esm3.update_prompt_sequence",
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
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PROTEIN_WORKBENCH_SOURCE_ROOT"] = str(PROJECT_ROOT)
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        root = tmp_path / name.lower()
        root.mkdir()
        env[f"PROTEIN_WORKBENCH_{name}_ROOT"] = str(root)

    expected = repr(sorted(EXPECTED_MODULE_IDS))
    probe = f"""
from pathlib import Path
import core
import modules
from core import (
    ModuleRegistry,
    TypeRegistry,
    builtin_frozen_catalog,
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
catalog = builtin_frozen_catalog()
assert catalog.catalog_descriptor_bytes.hex() == {SOURCE_PORT_CATALOG_BYTES.hex()!r}
assert catalog.contract_digest == {SOURCE_PORT_CATALOG_DIGEST!r}
assert {{
    definition.type_id: definition.descriptor_bytes.hex()
    for definition in catalog.port_types
}} == {SOURCE_PORT_TYPE_BYTES!r}
assert {{
    definition.type_id: definition.contract_digest
    for definition in catalog.port_types
}} == {SOURCE_PORT_TYPE_DIGESTS!r}

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
    server = subprocess.Popen(
        [
            str(python),
            "-I",
            "-m",
            "uvicorn",
            "core.server:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=run_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
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
            except OSError:
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
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/v2/catalog",
            timeout=2,
        ) as response:
            installed_catalog = json.load(response)
        assert installed_catalog["catalog_contract_digest"] == (
            SOURCE_PORT_CATALOG_DIGEST
        )
        assert installed_catalog["contracts"] == [
            definition.public_contract()
            for definition in SOURCE_PORT_CATALOG.port_types
        ]
    finally:
        if server.poll() is None:
            server.terminate()
        try:
            server.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.communicate()
