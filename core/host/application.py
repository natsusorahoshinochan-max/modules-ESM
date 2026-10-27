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
from urllib.parse import quote, urlencode
from threading import RLock


class HostError(ValueError):
    """An operation could not be completed; its message identifies the cause."""

    def __init__(self, message, *, status_code=400):
        super().__init__(message)
        self.status_code = status_code


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
        from .interactions import Interactions
        self.interactions = Interactions(self)
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
    def _run_lease(self, project_id, run_id, *, probe=False):
        # Callers supply generated IDs or IDs read from a persisted run record.
        path = self._locks / ("execution-" + project_id + "-" + run_id)
        try:
            with path.open("a+b") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    if probe:
                        yield False
                        return
                    raise HostError(f"Run is already executing: {run_id}") from exc
                try:
                    yield True
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)
        except OSError as exc:
            raise HostError(f"Could not access run lease {run_id}: {exc}") from exc

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

    def _module_snapshot(self):
        """Caller holds the module lock; read and load each declaration once."""
        from .registry import load
        records, loaded = self._records("module"), []
        paths = [record["package_path"] for record in records if record.get("package_path")]
        for record in records:
            try:
                declaration = load(record["entry_point"], package_path=record.get("package_path"), installed_paths=paths)
                record["available"] = True
                record["name"] = declaration.name
                record["ui"] = declaration.ui
                record["settings_schema"] = declaration.settings
                if record["enabled"]:
                    loaded.append((record, declaration))
            except HostError as exc:
                record.update(available=False, load_error=str(exc))
            record["ui_url"] = (f"/api/modules/{quote(record['id'], safe='')}/ui.js?" + urlencode({"installation_id": record["installation_id"]})) if record["enabled"] and record["available"] and record["ui"] else None
        return records, loaded

    def _modules(self):
        from .module_packages import module_lock
        with module_lock(self):
            return self._module_snapshot()[1]

    def install(self, entry_point):
        from .module_packages import module_lock
        with module_lock(self):
            return self._install(entry_point)

    def _install(self, entry_point, *, package_path=None):
        from .registry import load
        paths = [record["package_path"] for record in self._records("module") if record.get("package_path")]
        module = load(entry_point, package_path=package_path, installed_paths=paths)
        records, loaded = self._module_snapshot()
        for record in records:
            if record["id"] == module.id:
                if package_path or record["entry_point"] != entry_point:
                    raise HostError(f"Duplicate module identity: {module.id}")
                return record
        # Disabled declarations still reserve node and tool identities.
        for record in records:
            if record["available"] and not record["enabled"]:
                loaded.append((record, load(record["entry_point"], package_path=record.get("package_path"), installed_paths=paths)))
        from .scopes import SCOPE_TYPES
        existing = {node.id for _, declaration in loaded for node in declaration.nodes} | SCOPE_TYPES
        existing_tools = {tool.id for _, declaration in loaded for tool in declaration.tools}
        for node in module.nodes:
            if node.id in existing:
                raise HostError(f"Duplicate node identity: {node.id}")
        existing_interactions = {item.id for _, declaration in loaded for item in declaration.interactions}
        if any(item.id in existing_interactions for item in module.interactions):
            raise HostError("Duplicate interaction identity")
        if any(tool.id in existing_tools for tool in module.tools):
            raise HostError("Duplicate tool identity")
        return self._put("module", {**({"package_path": str(package_path)} if package_path else {}), "id": module.id, "installation_id": uuid4().hex, "name": module.name, "entry_point": entry_point, "enabled": True, "settings": {}, "settings_schema": module.settings, "ui": module.ui})

    def install_package(self, wheel, entry_point):
        from .module_packages import install
        return install(self, wheel, entry_point)

    def configure(self, module_id, settings):
        from .module_packages import module_lock
        with module_lock(self):
            if not isinstance(settings, dict):
                raise HostError("Module settings must be an object")
            record = self._get("module", module_id)
            record["settings"] = settings
            return self._put("module", record)

    def list_modules(self):
        from .module_packages import module_lock
        with module_lock(self):
            return self._module_snapshot()[0]

    def enable(self, module_id, enabled):
        from .module_packages import module_lock
        with module_lock(self):
            record = self._get("module", module_id)
            if enabled:
                from .registry import load
                paths = [item["package_path"] for item in self._records("module") if item.get("package_path")]
                load(record["entry_point"], package_path=record.get("package_path"), installed_paths=paths)
            record["enabled"] = bool(enabled)
            return self._put("module", record)

    def uninstall(self, module_id):
        from .module_packages import module_lock, discard
        with module_lock(self):
            record = self._get("module", module_id)
            with self._connect() as connection:
                connection.execute("DELETE FROM records WHERE kind='module' AND id=?", (module_id,))
            if record.get("package_path"):
                discard(record["package_path"])

    def open_module_ui(self, module_id, installation_id):
        from .module_packages import module_lock
        from .registry import load
        with module_lock(self):
            record = self._get("module", module_id)
            if record["installation_id"] != installation_id:
                raise HostError("Module installation changed; refresh the module catalog", status_code=409)
            if not record["enabled"]:
                raise HostError(f"Module has no enabled UI entry: {module_id}")
            paths = [item["package_path"] for item in self._records("module") if item.get("package_path")]
            declaration = load(record["entry_point"], package_path=record.get("package_path"), installed_paths=paths)
            if not declaration.ui:
                raise HostError(f"Module has no UI entry: {module_id}")
            return Path(declaration.ui).open("rb")

    def catalog(self):
        from .module_packages import module_lock
        from .registry import node_record, tool_record
        with module_lock(self):
            records, loaded = self._module_snapshot()
            return {"nodes": [node_record(module, node) for _, module in loaded for node in module.nodes], "interactions": [{"id": item.id, "module_id": module.id, "inputs": {name: {"accepts": list(port.accepts), "required": port.required, "cardinality": port.cardinality} for name, port in item.inputs.items()}, "parameters": item.parameters} for _, module in loaded for item in module.interactions], "modules": records, "tools": [tool_record(module, tool) for _, module in loaded for tool in module.tools]}

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
                        record["role"] = "input"
                        received.append(record)
                        identities[key] = record["id"]
                    from .scopes import walk_nodes
                    for node in walk_nodes(project["flow"], strict=True):
                        node["inputs"] = {port: [identities[key] for key in keys] for port, keys in node.get("inputs", {}).items()}
                        if node.get('document'):
                            node['document'] = identities[node['document']]
                    with self._connect() as connection:
                        for record in received:
                            self._write(connection, "package", record)
                        self._write(connection, "project", project)
                except BaseException:
                    for record in received:
                        shutil.rmtree(self._packages / record["id"], ignore_errors=True)
                    raise
        return self.get_project("tutorial")

    def copy_project(self, source_id, name, flow=None, layout=None, input_packages=None):
        """Copy project inputs and selected results without unrelated run outputs."""
        from .storage import copy_package
        with self._project_operation([source_id]), self._draft_lock:
            source = self._get("project", source_id)
            project = {"id": uuid4().hex, "name": name, "flow": deepcopy(source["flow"] if flow is None else flow), "layout": deepcopy(source["layout"] if layout is None else layout)}
            from .scopes import walk_nodes
            nodes = list(walk_nodes(project["flow"], strict=True))
            if any(not isinstance(node.get("inputs", {}), dict) for node in nodes):
                raise HostError("Flow nodes must have input mappings")
            if input_packages is not None and (not isinstance(input_packages, list) or any(not isinstance(key, str) for key in input_packages)):
                raise HostError("Copy input_packages must be a list of package IDs")
            requested = list(input_packages or [])
            if not source.get("tutorial"):
                requested.extend(record["id"] for record in self.list_packages(source_id) if record.get("role") == "input")
            for node in nodes:
                if node.get('document') is not None:
                    if not isinstance(node['document'], str):
                        raise HostError('Editor document must be a package ID')
                    requested.append(node['document'])
                for keys in node.get("inputs", {}).values():
                    if not isinstance(keys, list) or any(not isinstance(key, str) for key in keys):
                        raise HostError("Direct inputs must be lists of package IDs")
                    requested.extend(keys)
            received = []
            identities = {}
            try:
                for key in dict.fromkeys(requested):
                    package = self.package(key)
                    if package.metadata()["project_id"] != source_id:
                        raise HostError("Copy inputs must belong to the source project; adopt them first")
                    record = copy_package(project["id"], package, self._packages)
                    record["role"] = "input"
                    received.append(record)
                    identities[key] = record["id"]
                for node in nodes:
                    if node.get('document'):
                        node['document'] = identities[node['document']]
                    for port, keys in node.get("inputs", {}).items():
                        node["inputs"][port] = [identities[key] for key in keys]
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
        from .scopes import SCOPE_TYPES, walk_nodes
        available = {node["id"] for node in self.catalog()["nodes"]} | SCOPE_TYPES
        nodes = walk_nodes(project["flow"])
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
        if workdir.exists():
            shutil.rmtree(workdir)
        self._workdirs.discard(workdir)

    def create_draft_input(self, project_id, delivery, workdir, *, retain_workdir=False):
        """Hold a teaching draft input until the user saves or abandons it."""
        from .storage import receive
        workdir = self._owned_workdir(workdir)
        try:
            if not self._get("project", project_id).get("tutorial"):
                raise HostError("Temporary inputs belong to a teaching draft")
            with self._draft_lock:
                record = receive(project_id, delivery, workdir, self._packages)
                record["role"] = "input"
                self._draft_inputs[record["id"]] = record
                return record
        finally:
            if not retain_workdir:
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

    def create_input(self, project_id, delivery, workdir, *, retain_workdir=False):
        from .storage import receive
        workdir = self._owned_workdir(workdir)
        record = None
        try:
            with self._project_operation([project_id], mutable=[project_id]):
                record = receive(project_id, delivery, workdir, self._packages)
                record["role"] = "input"
                return self._put("package", record)
        except BaseException:
            if record is not None:
                shutil.rmtree(self._packages / record["id"], ignore_errors=True)
            raise
        finally:
            if not retain_workdir:
                self._release_workdir(workdir)

    def adopt(self, target_project_id, source_package_id):
        """Copy every declared file without interpreting module-owned content."""
        with self._project_operation([target_project_id, self.package(source_package_id).metadata()["project_id"]], mutable=[target_project_id]), self._draft_lock:
            from .storage import copy_package
            self._get("project", target_project_id)
            source = self.package(source_package_id)
            record = None
            try:
                record = copy_package(target_project_id, source, self._packages)
                record["role"] = "input"
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
                        if committed:
                            for lease in self._locks.glob("execution-" + project_id + "-*"):
                                lease.unlink()
                        shutil.rmtree(trash)
                    except OSError as exc:
                        raise HostError(f"Project records removed but owned file cleanup failed: {exc}") from exc
                elif trash.exists() and not any(trash.iterdir()):
                    trash.rmdir()

    def export_package(self, package_id):
        """Materialize a closed ZIP; the caller owns removal after delivery."""
        with self._project_operation([self.package(package_id).metadata()["project_id"]]), self._draft_lock:
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

    @staticmethod
    def _failed_run(run, detail):
        run["status"] = "failed"
        run["diagnostics"] = [*run["diagnostics"], detail]
        for node in run["nodes"].values():
            if node["status"] == "running":
                node.update(status="failed", diagnostics=[*node["diagnostics"], detail])
            elif node["status"] == "pending":
                node.update(status="blocked", diagnostics=["Backend execution interrupted before this node started: " + detail])
        return run

    def _fail_run(self, run_id, error):
        import logging
        detail = f"Backend run failed: {error}"
        self._run_errors[run_id] = detail
        try:
            # Only persisted outputs and terminal node states survive a fatal error.
            self._put("run", self._failed_run(self._get("run", run_id), detail))
        except Exception as commit_error:
            self._run_errors[run_id] = f"{detail}; failure state could not be committed: {commit_error}"
            logging.getLogger(__name__).exception("Could not commit failed backend run %s", run_id)

    def _interrupted_run(self, run):
        # The caller owns this run's exclusive lease across the record reread.
        detail = self._run_errors.get(run["id"], "Run lease ended without a committed terminal state")
        return self._failed_run(run, detail)

    def start(self, project_id):
        return self._launch(project_id)

    def continue_run(self, run_id, node_id):
        original = self._get("run", run_id)
        return self._launch(original["project_id"], (run_id, node_id))

    def _launch(self, project_id, continuing=None):
        if self._get("project", project_id).get("tutorial"):
            raise HostError("Save the teaching example as your own project first")
        from threading import Thread
        from .execution import create_run, execute, prepare_continuation
        leases = ExitStack()
        run = None
        try:
            leases.enter_context(self._project_lock(project_id, running=True))
            run_id = continuing[0] if continuing else uuid4().hex
            leases.enter_context(self._run_lease(project_id, run_id))
            if continuing:
                original = self._get("run", run_id)
                if original["status"] == "running":
                    original = self._interrupted_run(original)
                prepared = prepare_continuation(self, original, continuing[1])
                run = original
                run["status"] = "running"
                run["diagnostics"] = []
                self._put("run", run)
                self._run_errors.pop(run_id, None)
            else:
                run, prepared = create_run(self, project_id, run_id)
            marker = self._locks / ("cancel-" + run_id)
            def work():
                try:
                    execute(self, run, prepared, marker.exists, continuing[1] if continuing else None)
                except Exception as exc:
                    self._fail_run(run_id, exc)
                finally:
                    try:
                        marker.unlink(missing_ok=True)
                    except OSError as exc:
                        self._fail_run(run_id, f"Cancellation marker cleanup failed: {exc}")
                    finally:
                        leases.close()
            response = json.loads(json.dumps(run))
            Thread(target=work, name="workbench-run-" + run_id, daemon=False).start()
            return response
        except BaseException as exc:
            if run is not None:
                self._fail_run(run["id"], f"Could not dispatch backend task: {exc}")
            leases.close()
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
        if run["status"] != "running":
            return run
        with self._run_lease(run["project_id"], run["id"], probe=True) as idle:
            # Keep an idle probe locked across the re-read and failure projection.
            run = self._get("run", run_id)
            if idle and run["status"] == "running":
                return self._interrupted_run(run)
            return run

    def list_runs(self, project_id):
        self._get("project", project_id)
        return [self.get_run(run["id"]) for run in self._records("run") if run["project_id"] == project_id]

    def discard_workdir(self, workdir):
        """Discard a host-allocated upload whose caller has abandoned it."""
        self._release_workdir(self._owned_workdir(workdir))
