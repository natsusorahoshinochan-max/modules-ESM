"""Failures observed through the same application boundary as real clients."""
from tests.run_helpers import wait_run
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from core.host import HostError, Workbench
from protein_workbench_public.module_api import Delivery


def test_empty_host_and_sdk_never_import_scientific_or_legacy_runtime_modules(tmp_path):
    source = Path(__file__).resolve().parents[1]
    script = '''
import importlib.abc
import sys
class BlockScientificImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        blocked = ("datatypes", "modules", "core.catalog", "core.execution", "core.workflow", "torch", "esm")
        if any(fullname == item or fullname.startswith(item + ".") for item in blocked):
            raise AssertionError("Forbidden startup import: " + fullname)
sys.meta_path.insert(0, BlockScientificImports())
from protein_workbench_public.module_api import Module, Node, Delivery, Outcome
from core.host import Workbench
from tests.run_helpers import wait_run
app = Workbench(sys.argv[1])
project = app.create_project("Empty host")
app.save_project(project["id"], {"nodes": [], "edges": []}, {"viewport": [1,2]})
assert wait_run(app, app.start(project["id"]))["status"] == "succeeded"
assert Workbench(sys.argv[1]).get_project(project["id"])["layout"] == {"viewport": [1,2]}
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path / "store")], cwd=tmp_path, env=dict(os.environ, PYTHONPATH=str(source)), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("problem", ["missing_entry", "missing_file", "unreadable", "escape", "absolute", "leaf_symlink", "directory_symlink", "directory", "external_workdir"])
def test_invalid_file_delivery_never_creates_a_readable_package(tmp_path, problem):
    app = Workbench(tmp_path / "store")
    project = app.create_project("Bad delivery")
    workdir = app.new_workdir()
    (workdir / "data").write_bytes(b"data")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "data").write_bytes(b"outside")
    entry, files = "entry", {"entry": "data"}
    expected = ""
    if problem == "missing_entry":
        entry, expected = "absent", "entry.*absent"
    elif problem == "missing_file":
        files, expected = {"entry": "missing"}, "declared file.*entry.*missing"
    elif problem == "unreadable":
        (workdir / "data").chmod(0)
        expected = "not a readable regular file|Permission denied"
    elif problem == "escape":
        files, expected = {"entry": "../outside"}, "must stay within workdir"
    elif problem == "absolute":
        files, expected = {"entry": str(outside / "data")}, "must stay within workdir"
    elif problem == "leaf_symlink":
        (workdir / "linked").symlink_to(outside / "data")
        files, expected = {"entry": "linked"}, "Could not receive declared file"
    elif problem == "directory_symlink":
        (workdir / "linked").symlink_to(outside, target_is_directory=True)
        files, expected = {"entry": "linked/data"}, "Could not receive declared file"
    elif problem == "directory":
        (workdir / "directory").mkdir()
        files, expected = {"entry": "directory"}, "not a readable regular file"
    elif problem == "external_workdir":
        workdir, expected = outside, "not allocated by this host"
    with pytest.raises(HostError, match=expected):
        app.create_input(project["id"], Delivery("author.format", entry, files), workdir)
    assert app.list_packages(project["id"]) == []
    assert (outside / "data").read_bytes() == b"outside"


def test_file_complete_scientifically_invalid_json_is_accepted_without_viewer(tmp_path):
    app = Workbench(tmp_path)
    project = app.create_project("Module-owned meaning")
    workdir = app.new_workdir()
    (workdir / "manifest").write_text('{"scientific_reference":"missing-object", "structure":"undeclared-scientific-file.cif"}')
    package = app.create_input(project["id"], Delivery("unknown.author.format", "manifest.json", {"manifest.json": "manifest"}), workdir)
    assert app.catalog()["modules"] == []
    with app.package(package["id"]).open("manifest.json") as stream:
        assert b"missing-object" in stream.read()


def _pipeline(app):
    app.install("tests.fixtures.host_module:module")
    project = app.create_project("Failure boundary")
    workdir = app.new_workdir()
    (workdir / "request").write_bytes(b"original")
    source = app.create_input(project["id"], Delivery("independent.request", "request", {"request": "request"}), workdir)
    app.save_project(project["id"], {"nodes": [{"id": "producer", "type": "independent.encode", "inputs": {"source": [source["id"]]}}, {"id": "consumer", "type": "independent.receive"}], "edges": [{"source": "producer", "source_port": "result", "target": "consumer", "target_port": "source"}]}, {})
    return project, source


@pytest.mark.parametrize("failure", ["write", "commit"])
def test_delivery_failure_does_not_commit_output_or_progress_or_start_downstream(tmp_path, monkeypatch, failure):
    app = Workbench(tmp_path)
    project, source = _pipeline(app)
    if failure == "write":
        def fail_write(fd):
            raise OSError("disk full during output write")
        monkeypatch.setattr(os, "fsync", fail_write)
        expected = "disk full"
    else:
        connect = sqlite3.connect
        armed = [True]

        class CommitFailure(sqlite3.Connection):
            def commit(self):
                count = self.execute("SELECT COUNT(*) FROM records WHERE kind='package'").fetchone()[0]
                if armed[0] and count > 1:
                    armed[0] = False
                    raise sqlite3.OperationalError("output commit refused")
                return super().commit()

        monkeypatch.setattr(sqlite3, "connect", lambda *args, **kwargs: connect(*args, **kwargs, factory=CommitFailure))
        expected = "output commit refused"
    run = wait_run(app, app.start(project["id"]))
    reopened = Workbench(tmp_path)
    assert run["status"] == "failed"
    assert expected in run["nodes"]["producer"]["diagnostics"][0]
    assert run["nodes"]["producer"]["outputs"] == {}
    assert run["nodes"]["producer"]["continuation"] is None
    assert run["nodes"]["consumer"]["status"] == "blocked"
    assert reopened.get_run(run["id"]) == run
    assert reopened.list_packages(project["id"]) == [source]
    with reopened.package(source["id"]).open("request") as stream:
        assert stream.read() == b"original"


def test_duplicate_node_identity_is_rejected_even_if_existing_module_disabled(tmp_path):
    app = Workbench(tmp_path)
    app.install("tests.fixtures.host_module:module")
    app.enable("independent", False)
    with pytest.raises(HostError, match="Duplicate node identity"):
        app.install("tests.fixtures.host_module:conflicting_module")


def test_input_formats_declaration_must_be_a_collection_of_names(tmp_path):
    app = Workbench(tmp_path)
    with pytest.raises(HostError, match="invalid input declaration"):
        app.install("tests.fixtures.host_module:malformed_module")
