"""Exercise installed distributions from isolated interpreters and author projects."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv
from zipfile import ZipFile

import pytest


ROOT = Path(__file__).resolve().parents[1]


def run(arguments, cwd):
    environment = dict(os.environ)
    for name in ("PYTHONPATH", "PYTHONHOME", "NODE_PATH", "TS_NODE_PROJECT"):
        environment.pop(name, None)
    completed = subprocess.run(
        list(map(str, arguments)), cwd=cwd, env=environment,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180,
    )
    assert completed.returncode == 0, completed.stdout
    return completed.stdout


@pytest.fixture(scope="module")
def distributions(tmp_path_factory):
    directory = tmp_path_factory.mktemp("installed-modules")
    source = directory / "build-source"
    source.mkdir()
    for name in ("core", "modules", "examples", "protein_workbench_public"):
        shutil.copytree(ROOT / name, source / name, ignore=shutil.ignore_patterns(
            "__pycache__", "*.egg-info", "build", "dist", "node_modules",
        ))
    for name in ("pyproject.toml", "setup.py", "MANIFEST.in", "README.md", "uv.lock"):
        shutil.copy2(ROOT / name, source / name)
    wheels = directory / "wheels"
    wheels.mkdir()
    for package in (source, source / "examples/external_module", source / "examples/independent_consumer"):
        run([sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", wheels, package], directory)
    shutil.rmtree(source)
    host = next(wheels.glob("protein_workbench-*.whl"))
    with ZipFile(host) as archive:
        names = archive.namelist()
    assert not any(name.startswith(("examples/external_module/", "examples/independent_consumer/",
                                    "examples/typescript_module/")) for name in names)
    assert "protein_workbench_public/react-api.ts" not in names
    # Resolve normal wheel requirements once; fresh environments install offline.
    existing = os.environ.get("WORKBENCH_TEST_WHEELHOUSE")
    offline = ["--no-index", "--find-links", existing] if existing else []
    run([sys.executable, "-m", "pip", "download", "--only-binary=:all:",
         *offline, "--dest", wheels, host, "httpx==0.28.1"], directory)
    return directory, wheels


def install_environment(directory, wheels, *, examples=False):
    environment = directory / "python"
    venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / "bin/python"
    packages = ["protein-workbench", "httpx==0.28.1"]
    if examples:
        packages += ["workbench-notes-producer"]
    run([python, "-m", "pip", "install", "--no-index", "--find-links", wheels, *packages], directory)
    run([python, "-m", "pip", "check"], directory)
    return python


def test_consumer_survives_producer_uninstall_without_sources_or_workdirs(distributions, tmp_path):
    artifact_root, wheels = distributions
    python = install_environment(tmp_path, wheels, examples=True)
    assert not (artifact_root / "build-source").exists()
    produce = tmp_path / "produce.py"
    produce.write_text('''
import json, sys
from time import monotonic, sleep
from pathlib import Path
from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application
import protein_workbench_public.module_api as sdk
import workbench_notes

root = Path(sys.argv[1])
assert Path(sdk.__file__).is_relative_to(sys.prefix)
assert Path(workbench_notes.__file__).is_relative_to(sys.prefix)
with TestClient(create_application(data_root=root)) as client:
    project = client.post("/api/projects", json={"name": "Independent data"}).json()["id"]
    assert client.post("/api/modules", json={"entry_point": "workbench_notes:module"}).status_code == 200
    record = next(item for item in client.get("/api/modules").json() if item["id"] == "example.notes")
    assert client.get(record["ui_url"]).status_code == 200
    assert client.put("/api/modules/example.notes/settings", json={"settings": {"prefix": "note: "}}).status_code == 200
    token = client.post(f"/api/projects/{project}/uploads").json()["upload_id"]
    upload = f"/api/projects/{project}/uploads/{token}"
    assert client.put(upload + "/files", params={"key": "text"}, content=b"hello").status_code == 200
    source = client.post(upload + "/commit", json={"format": "example.note", "entry": "text", "files": {"text": "text"}}).json()["id"]
    flow = {"nodes": [{"id": "producer", "type": "example.uppercase", "parameters": {}, "inputs": {"note": [source]}}], "edges": []}
    assert client.put(f"/api/projects/{project}", json={"flow": flow, "layout": {}}).status_code == 200
    run = client.post(f"/api/projects/{project}/runs").json()
    deadline = monotonic() + 10
    while run["status"] == "running" and monotonic() < deadline:
        sleep(.01)
        run = client.get(f"/api/runs/{run['id']}").json()
    assert run["status"] == "succeeded", run
    output = run["nodes"]["producer"]["outputs"]["note"][0]
    assert client.get(f"/api/packages/{output}/file", params={"key": "text"}).content == b"note: HELLO"
    assert client.delete("/api/modules/example.notes").status_code == 200
Path(sys.argv[2]).write_text(json.dumps({"project": project, "output": output}))
''', encoding="utf-8")
    data = tmp_path / "data"
    state = tmp_path / "state.json"
    run([python, "-I", produce, data, state], tmp_path)
    run([python, "-m", "pip", "uninstall", "-y", "workbench-notes-producer"], tmp_path)
    shutil.rmtree(data / "work")
    produce.unlink()
    run([python, "-m", "pip", "install", "--no-index", "--find-links", wheels,
         "workbench-note-consumer"], tmp_path)
    run([python, "-m", "pip", "check"], tmp_path)
    consume = tmp_path / "consume.py"
    consume.write_text('''
import importlib.util, json, sys
from time import monotonic, sleep
from importlib.metadata import distribution
from pathlib import Path
from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application
import workbench_note_consumer

assert importlib.util.find_spec("workbench_notes") is None
assert Path(workbench_note_consumer.__file__).is_relative_to(sys.prefix)
assert all("notes-producer" not in item for item in distribution("workbench-note-consumer").requires)
root = Path(sys.argv[1])
state = json.loads(Path(sys.argv[2]).read_text())
project, original = state["project"], state["output"]
with TestClient(create_application(data_root=root)) as client:
    assert client.get(f"/api/packages/{original}/file", params={"key": "text"}).content == b"note: HELLO"
    assert client.post("/api/modules", json={"entry_point": "workbench_note_consumer:module"}).status_code == 200
    flow = {"nodes": [{"id": "reader", "type": "example.count", "parameters": {}, "inputs": {"note": [original]}}], "edges": []}
    assert client.put(f"/api/projects/{project}", json={"flow": flow, "layout": {"reader": {"x": 37, "y": 12}}}).status_code == 200
    run = client.post(f"/api/projects/{project}/runs").json()
    deadline = monotonic() + 10
    while run["status"] == "running" and monotonic() < deadline:
        sleep(.01)
        run = client.get(f"/api/runs/{run['id']}").json()
    assert run["status"] == "succeeded", run
    output = run["nodes"]["reader"]["outputs"]["count"][0]
    assert client.get(f"/api/packages/{output}/file", params={"key": "count"}).content == b"11"
with TestClient(create_application(data_root=root)) as reopened:
    project = reopened.get(f"/api/projects/{project}").json()
    assert project["flow"] == flow
    assert project["layout"] == {"reader": {"x": 37, "y": 12}}
    assert reopened.get(f"/api/packages/{original}/file", params={"key": "text"}).content == b"note: HELLO"
    assert reopened.get(f"/api/packages/{output}/file", params={"key": "count"}).content == b"11"
print("Producer absent: independent read, compute, save and reopen passed")
''', encoding="utf-8")
    assert "independent read, compute, save and reopen passed" in run([python, "-I", consume, data, state], tmp_path)


def test_typescript_author_compiles_with_installed_public_package(distributions, tmp_path):
    _, wheels = distributions
    python = install_environment(tmp_path, wheels)
    package = Path(run([python, "-I", "-c",
        'from importlib.resources import files; print(files("protein_workbench_public").joinpath("module_ui"))'], tmp_path).strip())
    packed = tmp_path / "packed"
    packed.mkdir()
    result = run(["npm", "pack", package, "--pack-destination", packed, "--json"], tmp_path)
    tarball = packed / json.loads(result)[0]["filename"]
    author = tmp_path / "author"
    shutil.copytree(ROOT / "examples/typescript_module", author,
                    ignore=shutil.ignore_patterns("node_modules", "dist", "*.tgz"))
    run(["npm", "install", "--no-audit", "--no-fund", tarball], author)
    installed = author / "node_modules/@protein-workbench/module-ui"
    assert installed.is_dir() and not installed.is_symlink()
    assert (installed / "index.d.ts").is_file()
    shutil.rmtree(packed)
    shutil.rmtree(python.parent.parent)
    run(["npm", "run", "build"], author)
    resolved = run([author / "node_modules/.bin/tsc", "-p", "tsconfig.json", "--listFilesOnly"], author)
    files = [Path(line).resolve() for line in resolved.splitlines() if line.endswith((".ts", ".tsx"))]
    assert files and all(path.is_relative_to(author.resolve()) for path in files)
    output = author / "dist/entry.js"
    assert output.is_file()
    assert "@protein-workbench/module-ui" not in output.read_text()


def test_structure_consumers_survive_staged_producer_code_removal(distributions, tmp_path):
    """Monolithic wheel staging removes only producer directories, not a pip uninstall."""
    artifact_root, wheels = distributions
    python = install_environment(tmp_path, wheels)
    assert not (artifact_root / 'build-source').exists()
    helper = tmp_path / 'acceptance.py'
    shutil.copy2(ROOT / 'tests/test_adoption_flow.py', helper)
    sample = tmp_path / 'sample'
    shutil.copytree(ROOT / 'modules/structure_comparison/sample', sample)
    prepare = tmp_path / 'prepare.py'
    prepare.write_text('''
import importlib.util, json, sys
from time import monotonic, sleep
from pathlib import Path
spec = importlib.util.spec_from_file_location('acceptance', sys.argv[1])
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)
sample, data, state = map(Path, sys.argv[2:])
prediction = {'objects':[{'id':'unchanged-prediction','sequence':'AAAAA','structure':{'file':'subject.pdb','format':'pdb'}}], 'tool':{'id':'recorded.tool','parameters':{'seed':0}}}
reference = {'objects':[{'id':'independent-reference','structure':{'file':'reference.cif','format':'mmcif'}}]}
p = ({'format':'workbench.prediction','entry':'manifest.json'}, {'manifest.json':json.dumps(prediction).encode(), 'subject.pdb':(sample/'subject.pdb').read_bytes(), '../opaque/supplement':b'opaque data retained'})
r = ({'format':'workbench.reference','entry':'manifest.json'}, {'manifest.json':json.dumps(reference).encode(), 'reference.cif':(sample/'reference.cif').read_bytes()})
state.write_text(json.dumps(a.prepare(data,[p],r)))
''', encoding='utf-8')
    data, state = tmp_path / 'data', tmp_path / 'state.json'
    run([python, '-I', prepare, helper, sample, data, state], tmp_path)
    site = Path(run([python, '-I', '-c', 'import sysconfig; print(sysconfig.get_paths()["purelib"])'], tmp_path).strip())
    # These are the two producer directories within the actual installed wheel.
    for name in ('folding', 'simplefold'):
        shutil.rmtree(site / 'modules' / name)
    shutil.rmtree(data / 'work')
    shutil.rmtree(sample)
    prepare.unlink()
    consume = tmp_path / 'consume.py'
    consume.write_text('''
import importlib, importlib.util, json, sys
from pathlib import Path
for producer in ('modules.folding', 'modules.simplefold'):
    assert importlib.util.find_spec(producer) is None
    try:
        importlib.import_module(producer)
    except ModuleNotFoundError:
        pass
    else:
        raise AssertionError(producer + ' remained importable')
import modules.structure_comparison, modules.structure_conversion
assert Path(modules.structure_comparison.__file__).is_relative_to(sys.prefix)
spec = importlib.util.spec_from_file_location('acceptance', sys.argv[1])
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)
a.reopen(Path(sys.argv[2]), json.loads(Path(sys.argv[3]).read_text()))
print('Staged producer code absent: read, ZIP, readopt, independent computation passed')
''', encoding='utf-8')
    assert 'Staged producer code absent' in run([python, '-I', consume, helper, data, state], tmp_path)
