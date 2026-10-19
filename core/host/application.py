"""Application entry for generic projects and module execution."""
from __future__ import annotations

import json
from copy import deepcopy
import fcntl
from contextlib import contextmanager, ExitStack
from pathlib import Path
import sqlite3
import shutil
import tempfile
from uuid import uuid4
from threading import RLock


class HostError(ValueError):
    """An operation could not be completed; its message identifies the cause."""


def _json_text(value):
    try:
        data = json.dumps(value, ensure_ascii=False, allow_nan=False)
        data.encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise HostError(f"Record must be UTF-8 JSON: {exc}") from exc
    return data


class Workbench:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._workdirs = set()
        self._draft_inputs = {}
        self._draft_lock = RLock()
        self._run_errors = {}
        self._packages = self.root / "packages"
        self._packages.mkdir(exist_ok=True)
        self._work = self.root / "work"
        self._work.mkdir(exist_ok=True)
        self._locks = self.root / "locks"
        self._locks.mkdir(exist_ok=True)
        self._database = self.root / "host.sqlite"
        with self._connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, data TEXT NOT NULL, PRIMARY KEY(kind,id))")

    @contextmanager
    def _project_lock(self, project_id, *, running=False):
        # Resolve IDs through stored records before using them in an owned path.
        project_id = self._get("project", project_id)["id"]
        with (self._locks / (("run-" if running else "files-") + project_id)).open("a+b") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | (fcntl.LOCK_NB if running else 0))
            except BlockingIOError as exc:
                raise HostError(f"Project is running: {project_id}") from exc
            try:
                self._get("project", project_id)
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    @contextmanager
    def _project_operation(self, project_ids, *, mutable=()):
        # Run leases reject immediately; file leases serialize complete copies/deletes.
        with ExitStack() as stack:
            for project_id in sorted(set(mutable)):
                if self._get("project", project_id).get("tutorial"):
                    raise HostError("Save the teaching example as your own project first")
                stack.enter_context(self._project_lock(project_id, running=True))
            for project_id in sorted(set(project_ids)):
                stack.enter_context(self._project_lock(project_id))
            yield

    @contextmanager
    def _connect(self):
        connection = None
        try:
            connection = sqlite3.connect(self._database)
            yield connection
            connection.commit()
        except (sqlite3.Error, OSError) as exc:
            if connection is not None:
                connection.rollback()
            raise HostError(f"Database read, write or commit failed: {exc}") from exc
        except BaseException:
            if connection is not None:
                connection.rollback()
            raise
        finally:
            if connection is not None:
                connection.close()

    def _records(self, kind):
        with self._connect() as connection:
            return [json.loads(row[0]) for row in connection.execute("SELECT data FROM records WHERE kind=? ORDER BY rowid", (kind,))]

    def _get(self, kind, identifier):
        with self._connect() as connection:
            row = connection.execute("SELECT data FROM records WHERE kind=? AND id=?", (kind, identifier)).fetchone()
        if row is None:
            raise HostError(f"Unknown {kind}: {identifier}")
        return json.loads(row[0])

    def _put(self, kind, record):
        try:
            with self._connect() as connection:
                self._write(connection, kind, record)
        except (sqlite3.Error, OSError, TypeError, ValueError) as exc:
            raise HostError(f"Could not commit {kind}: {exc}") from exc
        return record

    @staticmethod
    def _write(connection, kind, record):
        data = _json_text(record)
        connection.execute("INSERT INTO records(kind,id,data) VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data", (kind, record["id"], data))

    def _modules(self):
        from .registry import load_record
        loaded = []
        for record in self._records("module"):
            if record["enabled"]:
                try:
                    loaded.append((record, load_record(record)))
                except HostError:
                    continue
        return loaded

    def install(self, entry_point):
        from .module_packages import mutation_lock
        with mutation_lock(self):
            return self._install(entry_point)

    def _install(self, entry_point, *, package_path=None):
        from .registry import load, load_record
        module = load(entry_point)
        for record in self._records("module"):
            if record["id"] == module.id:
                if record["entry_point"] != entry_point:
                    raise HostError(f"Duplicate module identity: {module.id}")
                return record
        existing = set()
        existing_tools = set()
        for installed in self._records("module"):
            try:
                installed_module = load_record(installed)
                existing.update(node.id for node in installed_module.nodes)
                existing_tools.update(tool.id for tool in installed_module.tools)
            except HostError:
                continue
        for node in module.nodes:
            if node.id in existing:
                raise HostError(f"Duplicate node identity: {node.id}")
        if any(tool.id in existing_tools for tool in module.tools):
            raise HostError("Duplicate tool identity")
        return self._put("module", {**({"package_path": str(package_path)} if package_path else {}), "id": module.id, "name": module.name, "entry_point": entry_point, "enabled": True, "settings": {}, "settings_schema": module.settings, "ui": module.ui})

    def install_package(self, wheel, entry_point):
        from .module_packages import install
        return install(self, wheel, entry_point)

    def configure(self, module_id, settings):
        from .module_packages import mutation_lock
        with mutation_lock(self):
            if not isinstance(settings, dict):
                raise HostError("Module settings must be an object")
            record = self._get("module", module_id)
            record["settings"] = settings
            return self._put("module", record)

    def list_modules(self):
        from .registry import load_record
        records = self._records("module")
        for record in records:
            try:
                load_record(record)
                record["available"] = True
            except HostError as exc:
                record.update(available=False, load_error=str(exc))
        return records

    def enable(self, module_id, enabled):
        from .module_packages import mutation_lock
        with mutation_lock(self):
            record = self._get("module", module_id)
            if enabled:
                from .registry import load_record
                load_record(record)
            record["enabled"] = bool(enabled)
            return self._put("module", record)

    def uninstall(self, module_id):
        from .module_packages import mutation_lock
        with mutation_lock(self):
            record = self._get("module", module_id)
            with self._connect() as connection:
                connection.execute("DELETE FROM records WHERE kind='module' AND id=?", (module_id,))
            if record.get("package_path"):
                from .module_packages import remove
                remove(record["package_path"])

    def ui_entry(self, module_id):
        record = self._get("module", module_id)
        if not record["enabled"] or not record["ui"]:
            raise HostError(f"Module has no enabled UI entry: {module_id}")
        from .registry import load_record
        declaration = load_record(record)
        if not declaration.ui:
            raise HostError(f"Module has no UI entry: {module_id}")
        path = Path(declaration.ui)
        if not path.is_file():
            raise HostError(f"Missing module UI entry: {path}")
        return path

    def catalog(self):
        from .registry import node_record, tool_record
        return {"nodes": [node_record(module, node) for _, module in self._modules() for node in module.nodes], "modules": self.list_modules(), "tools": [tool_record(module, tool) for _, module in self._modules() for tool in module.tools]}

    def create_project(self, name):
        return self._put("project", {"id": uuid4().hex, "name": name, "flow": {"nodes": [], "edges": []}, "layout": {}})

    def list_projects(self):
        return [self.get_project(record["id"]) for record in self._records("project") if not record.get("tutorial")]

    def tutorial(self):
        """Open the bundled example without granting writes to its original files."""
        from protein_workbench_public import resources
        from .storage import receive
        from protein_workbench_public.module_api import Delivery
        directory = Path(resources.__file__).parent / "tutorial"
        with (self._locks / "tutorial").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if not any(record["id"] == "tutorial" for record in self._records("project")):
                template = json.loads((directory / "project.json").read_text())
                project = {"id": "tutorial", "tutorial": True, "name": template["name"], "flow": template["flow"], "layout": template["layout"]}
                received = []
                try:
                    identities = {}
                    for key, description in template["inputs"].items():
                        record = receive(project["id"], Delivery(**description), directory, self._packages)
                        received.append(record)
                        identities[key] = record["id"]
                    for node in project["flow"]["nodes"]:
                        node["inputs"] = {port: [identities[key] for key in keys] for port, keys in node.get("inputs", {}).items()}
                    with self._connect() as connection:
                        for record in received:
                            self._write(connection, "package", record)
                        self._write(connection, "project", project)
                except BaseException:
                    for record in received:
                        shutil.rmtree(self._packages / record["id"], ignore_errors=True)
                    raise
        return self.get_project("tutorial")

    def copy_project(self, source_id, name, flow=None, layout=None):
        """Copy the saved flow or an explicit draft, and only its directly bound inputs."""
        from .storage import copy_package
        with self._project_operation([source_id]), self._draft_lock:
            source = self._get("project", source_id)
            project = {"id": uuid4().hex, "name": name, "flow": deepcopy(source["flow"] if flow is None else flow), "layout": deepcopy(source["layout"] if layout is None else layout)}
            nodes = project["flow"].get("nodes", [])
            if not isinstance(nodes, list) or any(not isinstance(node, dict) or not isinstance(node.get("inputs", {}), dict) for node in nodes):
                raise HostError("Flow nodes must have input mappings")
            received = []
            identities = {}
            try:
                for node in nodes:
                    for port, keys in node.get("inputs", {}).items():
                        if not isinstance(keys, list) or any(not isinstance(key, str) for key in keys):
                            raise HostError("Direct inputs must be lists of package IDs")
                        copied = []
                        for key in keys:
                            if key not in identities:
                                package = self.package(key)
                                if package.metadata()["project_id"] != source_id:
                                    raise HostError("Copy inputs must belong to the source project; adopt them first")
                                record = copy_package(project["id"], package, self._packages)
                                received.append(record)
                                identities[key] = record["id"]
                            copied.append(identities[key])
                        node["inputs"][port] = copied
                with self._connect() as connection:
                    for record in received:
                        self._write(connection, "package", record)
                    self._write(connection, "project", project)
            except BaseException:
                for record in received:
                    shutil.rmtree(self._packages / record["id"], ignore_errors=True)
                raise
        return self.get_project(project["id"])

    def get_project(self, project_id):
        project = self._get("project", project_id)
        available = {node["id"] for node in self.catalog()["nodes"]}
        flow = project["flow"]
        nodes = flow.get("nodes", []) if isinstance(flow, dict) else []
        nodes = nodes if isinstance(nodes, list) else []
        requested = {node["type"] for node in nodes if isinstance(node, dict) and isinstance(node.get("type"), str)}
        project["missing_modules"] = sorted(requested - available)
        project["running"] = self._project_running(project_id)
        return project

    def _project_running(self, project_id):
        try:
            with self._project_lock(project_id, running=True):
                return False
        except HostError as exc:
            if str(exc).startswith("Project is running:"):
                return True
            raise

    def save_project(self, project_id, flow, layout):
        with self._project_operation([project_id], mutable=[project_id]):
            project = self._get("project", project_id)
            project.update(flow=flow, layout=layout)
            self._put("project", project)
        return self.get_project(project_id)

    def new_workdir(self):
        path = Path(tempfile.mkdtemp(prefix="execution-", dir=self._work))
        self._workdirs.add(path)
        return path

    def _owned_workdir(self, workdir):
        workdir = Path(workdir).absolute()
        if workdir not in self._workdirs or workdir.is_symlink() or not workdir.is_dir() or workdir.resolve().parent != self._work:
            raise HostError(f"Delivery workdir is not allocated by this host: {workdir}")
        return workdir

    def _release_workdir(self, workdir):
        self._workdirs.discard(workdir)
        shutil.rmtree(workdir, ignore_errors=True)

    def create_draft_input(self, project_id, delivery, workdir):
        """Hold a teaching draft input until the user saves or abandons it."""
        from .storage import receive
        workdir = self._owned_workdir(workdir)
        try:
            if not self._get("project", project_id).get("tutorial"):
                raise HostError("Temporary inputs belong to a teaching draft")
            with self._draft_lock:
                record = receive(project_id, delivery, workdir, self._packages)
                self._draft_inputs[record["id"]] = record
                return record
        finally:
            self._release_workdir(workdir)

    def discard_draft_input(self, package_id):
        with self._draft_lock:
            record = self._draft_inputs.get(package_id)
            if record is None:
                raise HostError("Unknown temporary input")
            shutil.rmtree(self._packages / package_id)
            del self._draft_inputs[package_id]

    def discard_draft_inputs(self):
        for package_id in list(self._draft_inputs):
            self.discard_draft_input(package_id)

    def create_input(self, project_id, delivery, workdir):
        from .storage import receive
        workdir = self._owned_workdir(workdir)
        record = None
        try:
            with self._project_operation([project_id], mutable=[project_id]):
                record = receive(project_id, delivery, workdir, self._packages)
                return self._put("package", record)
        except BaseException:
            if record is not None:
                shutil.rmtree(self._packages / record["id"], ignore_errors=True)
            raise
        finally:
            self._release_workdir(workdir)

    def adopt(self, target_project_id, source_package_id):
        """Copy every declared file without interpreting module-owned content."""
        with self._project_operation([target_project_id, self._get("package", source_package_id)["project_id"]], mutable=[target_project_id]):
            from .storage import copy_package
            self._get("project", target_project_id)
            source = self.package(source_package_id)
            record = None
            try:
                record = copy_package(target_project_id, source, self._packages)
                return self._put("package", record)
            except BaseException:
                if record is not None:
                    shutil.rmtree(self._packages / record["id"], ignore_errors=True)
                raise

    def delete_project(self, project_id):
        """Remove only this project's received files and records."""
        with self._project_operation([project_id], mutable=[project_id]):
            self._get("project", project_id)
            packages = self.list_packages(project_id)
            runs = self.list_runs(project_id)
            trash = Path(tempfile.mkdtemp(prefix="deleting-", dir=self._work))
            moved = []
            committed = False
            try:
                for record in packages:
                    source = self._packages / record["id"]
                    destination = trash / record["id"]
                    source.rename(destination)
                    moved.append((source, destination))
                with self._connect() as connection:
                    for kind, records in (("package", packages), ("run", runs), ("project", [{"id": project_id}])):
                        connection.executemany("DELETE FROM records WHERE kind=? AND id=?", [(kind, record["id"]) for record in records])
                committed = True
            except BaseException:
                for source, destination in reversed(moved):
                    destination.rename(source)
                raise
            finally:
                if committed or not moved:
                    try:
                        shutil.rmtree(trash)
                    except OSError as exc:
                        raise HostError(f"Project records removed but owned file cleanup failed: {exc}") from exc
                elif trash.exists() and not any(trash.iterdir()):
                    trash.rmdir()

    def export_package(self, package_id):
        """Materialize a closed ZIP; the caller owns removal after delivery."""
        with self._project_operation([self._get("package", package_id)["project_id"]]):
            from .storage import export_package
            return export_package(self.package(package_id), self._work)

    def package(self, package_id):
        from .storage import StoredPackage
        with self._draft_lock:
            record = self._draft_inputs.get(package_id) or self._get("package", package_id)
        return StoredPackage(record, self._packages / package_id)

    def list_packages(self, project_id):
        self._get("project", project_id)
        return [record for record in self._records("package") if record["project_id"] == project_id]

    def start(self, project_id):
        if self._get("project", project_id).get("tutorial"):
            raise HostError("Save the teaching example as your own project first")
        from threading import Thread
        from .execution import create_run, execute
        lease = self._project_lock(project_id, running=True)
        lease.__enter__()
        try:
            run, prepared = create_run(self, project_id)
            # The cancellation marker is independent of run-record replacement.
            marker = self._locks / ("cancel-" + run["id"])
            def work():
                try:
                    execute(self, run, prepared, marker.exists)
                except Exception as exc:
                    run["status"] = "failed"
                    run["diagnostics"].append(f"Backend run failed: {exc}")
                    try:
                        self._put("run", run)
                    except HostError as commit_error:
                        import logging
                        self._run_errors[run["id"]] = str(commit_error)
                        logging.getLogger(__name__).exception("Could not commit failed backend run %s", run["id"])
                finally:
                    lease.__exit__(None, None, None)
                    marker.unlink(missing_ok=True)
            response = json.loads(json.dumps(run))
            Thread(target=work, name="workbench-run-" + run["id"], daemon=False).start()
            return response
        except BaseException:
            lease.__exit__(None, None, None)
            raise

    def cancel_run(self, run_id):
        run = self.get_run(run_id)
        marker = self._locks / ("cancel-" + run["id"])
        if run["status"] == "running":
            marker.touch()
        result = self.get_run(run_id)
        if result["status"] != "running":
            marker.unlink(missing_ok=True)
        return result


    def get_run(self, run_id):
        run = self._get("run", run_id)
        if run["status"] == "running" and not self._project_running(run["project_id"]):
            # Re-read after acquiring the lease: a terminal commit may have happened
            # between the first read and the lease probe.
            run = self._get("run", run_id)
            if run["status"] == "running":
                run["status"] = "failed"
                detail = self._run_errors.get(run_id, "Run lease ended without a committed terminal state")
                run["diagnostics"] = [*run["diagnostics"], detail]
                for node in run["nodes"].values():
                    if node["status"] in ("pending", "running"):
                        node["status"] = "failed" if node["status"] == "running" else "blocked"
                        node["diagnostics"] = [*node["diagnostics"], "Backend run ended before this node's terminal state was committed"]
        return run

    def list_runs(self, project_id):
        self._get("project", project_id)
        return [self.get_run(run["id"]) for run in self._records("run") if run["project_id"] == project_id]

    def discard_workdir(self, workdir):
        """Discard a host-allocated upload whose caller has abandoned it."""
        self._release_workdir(self._owned_workdir(workdir))
