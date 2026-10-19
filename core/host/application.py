"""Application entry for generic projects and module execution."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from uuid import uuid4


class HostError(ValueError):
    """An operation could not be completed; its message identifies the cause."""


class Workbench:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._database = self.root / "host.sqlite"
        with self._connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, data TEXT NOT NULL, PRIMARY KEY(kind,id))")

    def _connect(self):
        return sqlite3.connect(self._database)

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
        connection.execute("INSERT INTO records(kind,id,data) VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data", (kind, record["id"], json.dumps(record, allow_nan=False)))

    def _modules(self):
        from .registry import load
        loaded = []
        for record in self._records("module"):
            if record["enabled"]:
                try:
                    loaded.append((record, load(record["entry_point"])))
                except HostError:
                    continue
        return loaded

    def install(self, entry_point):
        from .registry import load
        module = load(entry_point)
        for record in self._records("module"):
            if record["id"] == module.id:
                if record["entry_point"] != entry_point:
                    raise HostError(f"Duplicate module identity: {module.id}")
                return record
        existing = {node["id"] for node in self.catalog()["nodes"]}
        for node in module.nodes:
            if node.id in existing:
                raise HostError(f"Duplicate node identity: {node.id}")
        return self._put("module", {"id": module.id, "name": module.name, "entry_point": entry_point, "enabled": True, "settings": {}, "settings_schema": module.settings, "ui": module.ui})

    def configure(self, module_id, settings):
        if not isinstance(settings, dict):
            raise HostError("Module settings must be an object")
        record = self._get("module", module_id)
        record["settings"] = settings
        return self._put("module", record)

    def list_modules(self):
        return self._records("module")

    def enable(self, module_id, enabled):
        record = self._get("module", module_id)
        record["enabled"] = bool(enabled)
        return self._put("module", record)

    def uninstall(self, module_id):
        self._get("module", module_id)
        with self._connect() as connection:
            connection.execute("DELETE FROM records WHERE kind='module' AND id=?", (module_id,))

    def ui_entry(self, module_id):
        record = self._get("module", module_id)
        if not record["enabled"] or not record["ui"]:
            raise HostError(f"Module has no enabled UI entry: {module_id}")
        path = Path(record["ui"])
        if not path.is_file():
            raise HostError(f"Missing module UI entry: {path}")
        return path

    def catalog(self):
        from .registry import node_record
        return {"nodes": [node_record(module, node) for _, module in self._modules() for node in module.nodes], "modules": self.list_modules()}

    def create_project(self, name):
        return self._put("project", {"id": uuid4().hex, "name": name, "flow": {"nodes": [], "edges": []}, "layout": {}})

    def list_projects(self):
        return [self.get_project(record["id"]) for record in self._records("project")]

    def get_project(self, project_id):
        project = self._get("project", project_id)
        available = {node["id"] for node in self.catalog()["nodes"]}
        project["missing_modules"] = sorted({node.get("type", "") for node in project["flow"].get("nodes", [])} - available)
        return project

    def save_project(self, project_id, flow, layout):
        project = self._get("project", project_id)
        project.update(flow=flow, layout=layout)
        self._put("project", project)
        return self.get_project(project_id)
