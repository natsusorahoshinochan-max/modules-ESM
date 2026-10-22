"""THROWAWAY public module: copies existing files; performs no model inference."""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from protein_workbench_public.module_api import (
    Delivery, InputPort, Module, Node, Outcome, OutputPort, Tool, ToolSlot,
)

FORMAT = "prototype.nested_resume.files"


def file_tool(settings):
    controls = Path(settings["controls"])

    def copy_files(package, destination, request, runtime):
        # This intentional unavailable-tool switch exercises a reachable call failure.
        if (controls / "unavailable").exists() and request == "request-2":
            raise RuntimeError("PROTOTYPE file-copy tool temporarily unavailable")
        destination.mkdir()
        copied = {}
        for number, key in enumerate(package.files):
            if key == package.entry:
                continue
            output = destination / f"file-{number}.fasta"
            with package.open(key) as source, output.open("wb") as writer:
                shutil.copyfileobj(source, writer)
            copied[key] = str(output.relative_to(runtime.workdir))
        return copied

    return copy_files


def batch(call, runtime):
    params = call.parameters
    controls = Path(call.settings["controls"])
    events = controls / "events.jsonl"
    files, completed = {}, []
    if call.previous:
        completed = list(call.previous.continuation["completed"])
        for package in call.previous.outputs["result"]:
            with package.open(package.entry) as reader:
                old_manifest = json.load(reader)
            for key in old_manifest["files"]:
                local = runtime.workdir / key
                local.parent.mkdir(parents=True, exist_ok=True)
                with package.open(key) as reader, local.open("wb") as writer:
                    shutil.copyfileobj(reader, writer)
                files[key] = key
    status, diagnostics = "succeeded", ()
    for number in range(params["requests"]):
        request = f"request-{number + 1}"
        if request in completed:
            continue
        if runtime.cancelled:
            status, diagnostics = "cancelled", ("User cancelled the whole run between requests",)
            break
        with events.open("a") as log:
            log.write(json.dumps({"call": params["label"], "request": request,
                                  "parameter": params["label_parameter"], "event": "attempt"}) + "\n")
        try:
            folder = runtime.workdir / request
            copied = call.tools["files"](call.inputs["item"][0], folder, request, runtime)
            for source_key, relative in copied.items():
                files[f"{request}/{source_key}"] = relative
            completed.append(request)
            runtime.progress(f"{request} copied existing files; no inference")
        except RuntimeError as exc:
            status, diagnostics = "failed", (str(exc),)
            break
        if params.get("pause_after_first") and number == 0 and call.previous is None:
            (controls / "ready-to-cancel").write_text("First request finished; awaiting user cancel")
            while not runtime.cancelled and not (controls / "release").exists():
                time.sleep(0.01)
    manifest = {"operation": "copy existing historical files; no scientific computation",
                "parameter": params["label_parameter"], "completed": completed,
                "files": list(files)}
    (runtime.workdir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return Outcome(status=status, outputs={"result": [Delivery(
        FORMAT, "manifest.json", {"manifest.json": "manifest.json", **files})]},
        diagnostics=diagnostics, continuation={"completed": completed})


def collect(call, runtime):
    """A format-owning module combines files; the host does not parse their meaning."""
    files = {}
    for index, package in enumerate(call.inputs["items"]):
        for number, key in enumerate(package.files):
            if key == package.entry:
                continue
            name = f"input-{index}-file-{number}.fasta"
            with package.open(key) as source, (runtime.workdir / name).open("wb") as writer:
                shutil.copyfileobj(source, writer)
            files[name] = name
    (runtime.workdir / "manifest.json").write_text(json.dumps({
        "operation": "explicit collection of successful input packages",
        "input_packages": [package.id for package in call.inputs["items"]],
        "files": list(files),
    }, indent=2))
    return Outcome(outputs={"result": [Delivery(
        FORMAT, "manifest.json", {"manifest.json": "manifest.json", **files})]})


def get_module():
    return Module(
        id="prototype.nested_resume", name="PROTOTYPE nested scope file exercise",
        nodes=(
            Node("prototype.nested_resume.batch", "Copy historical files", batch,
                 inputs={"item": InputPort((FORMAT,))}, outputs={"result": OutputPort(FORMAT)},
                 tools={"files": ToolSlot("prototype.copy_files", "File operation")}),
            Node("prototype.nested_resume.collect", "Collect explicit packages", collect,
                 inputs={"items": InputPort((FORMAT,), cardinality="many")},
                 outputs={"result": OutputPort(FORMAT)}),
        ),
        tools=(Tool("prototype.nested_resume.copy", "Copy existing files (no model)",
                    "prototype.copy_files", file_tool),),
    )
