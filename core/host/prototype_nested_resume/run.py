"""THROWAWAY: exercise real host Start/Cancel/Continue in isolated scratch storage."""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from core.host.application import Workbench
from protein_workbench_public.module_api import Delivery
from core.host.prototype_nested_resume.demo_module import FORMAT

HERE = Path(__file__).resolve().parent


def wait_for(predicate, description):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise RuntimeError(f"Timed out: {description}")


def finished(app, run_id):
    run = wait_for(lambda: (run if (run := app.get_run(run_id))["status"] != "running" else None),
                   "host run terminal state")
    wait_for(lambda: not app.get_project(run["project_id"])["running"], "project lease release")
    return run


def snapshot(app, run, scopes):
    return {"id": run["id"], "status": run["status"], "calls": run["calls"], "nodes": [
        {"call_id": node_id, "scope": scopes[node_id], **state}
        for node_id, state in run["nodes"].items()
    ]}


def main():
    scratch = Path(tempfile.mkdtemp(prefix="PROTOTYPE-nested-resume-wipe-me-"))
    controls = scratch / "controls"
    controls.mkdir()
    app = Workbench(scratch / "host")
    app.install("core.host.prototype_nested_resume.demo_module:get_module")
    app.configure("prototype.nested_resume", {"controls": str(controls)})
    project = app.create_project("PROTOTYPE: historical files, no model execution")
    generation = ROOT / "modules/esm3/prototype_file_input/evidence/generation.json"
    cases = json.loads(generation.read_text())["cases"]
    packages = []
    for case in cases[:2]:
        workdir = app.new_workdir()
        (workdir / "sequence.fasta").write_text(f">historical_esm3_{case['case']}\n{case['sequence']}\n")
        (workdir / "manifest.json").write_text(json.dumps({"files": ["sequence.fasta"],
            "input_kind": "user explicitly selected historical ESM3 sequence",
            "source": str(generation.relative_to(ROOT)), "case": case["case"]}))
        package = app.create_input(project["id"], Delivery(FORMAT, "manifest.json", {
            "manifest.json": "manifest.json", "sequence.fasta": "sequence.fasta"}), workdir)
        packages.append(package["id"])
    evidence = {"question": "Can explicit nested call locations reuse fixed calls and actual package delivery?",
                "execution": "Real host APIs; lightweight file operations; zero new model inference",
                "scratch": str(scratch), "source": str(generation.relative_to(ROOT)), "scenarios": {}}
    for scenario in ("cancel", "temporary_tool_failure"):
        scopes, nodes, edges = {}, [], []

        def add(label, scope, package=None, requests=1, pause=False):
            identifier = uuid4().hex  # Ordinary identity, independent of scope/content.
            scopes[identifier] = scope
            nodes.append({"id": identifier, "type": "prototype.nested_resume.batch",
                "inputs": {"item": [package]} if package else {},
                "parameters": {"label": label, "requests": requests, "pause_after_first": pause,
                               "label_parameter": "original"},
                "tools": {"files": "prototype.nested_resume.copy"}})
            return identifier

        def edge(source, target, port="items"):
            edges.append({"source": source, "source_port": "result", "target": target, "target_port": port})

        def join(label, sources):
            identifier = uuid4().hex
            scopes[identifier] = label
            nodes.append({"id": identifier, "type": "prototype.nested_resume.collect"})
            for source in sources:
                edge(source, identifier)
            return identifier

        # Cancel is global: the independent branch intentionally runs before cancellation.
        independent = None
        if scenario == "cancel":
            independent = add("independent", "root/independent", packages[0])
        first = add("item-0", "root/repeat/round:1/map/item:0/copy", packages[0])
        target = add("item-1", "root/repeat/round:1/map/item:1/copy", packages[1],
                     requests=2, pause=scenario == "cancel")
        joined = join("root/repeat/round:1/collect", [first, target])
        # One explicit feedback edge: a received collection package is the next-round input.
        second_round = add("round-2", "root/repeat/round:2/copy")
        edge(joined, second_round, "item")
        if scenario != "cancel":
            independent = add("independent", "root/independent", packages[0])
            (controls / "unavailable").touch()
        flow = {"nodes": nodes, "edges": edges}
        app.save_project(project["id"], flow, {})
        run = app.start(project["id"])
        if scenario == "cancel":
            wait_for(lambda: (controls / "ready-to-cancel").exists(), "first request completion")
            app.cancel_run(run["id"])
        interrupted = finished(app, run["id"])
        partial_files = []
        for package_id in interrupted["nodes"][target]["outputs"]["result"]:
            package = app.package(package_id)
            for key in package.files:
                if key.endswith(".fasta"):
                    with package.open(key) as reader:
                        partial_files.append({"package_id": package_id, "key": key,
                                              "content": reader.read().decode()})
        before_events = [json.loads(line) for line in (controls / "events.jsonl").read_text().splitlines()]
        # User edits saved canvas after the run stops, then explicitly continues the OLD run.
        for node in flow["nodes"]:
            if "parameters" in node:
                node["parameters"]["label_parameter"] = "edited-canvas"
        app.save_project(project["id"], flow, {})
        (controls / "unavailable").unlink(missing_ok=True)
        app.continue_run(run["id"], target)
        complete = finished(app, run["id"])
        all_events = [json.loads(line) for line in (controls / "events.jsonl").read_text().splitlines()]
        continuation_events = all_events[len(before_events):]
        checks = {
            "first_item_succeeded": interrupted["nodes"][first]["status"] == "succeeded",
            "independent_succeeded": interrupted["nodes"][independent]["status"] == "succeeded",
            "target_partial_one_request": interrupted["nodes"][target]["continuation"]["completed"] == ["request-1"],
            "downstream_not_called": joined not in interrupted["calls"] and second_round not in interrupted["calls"],
            "continued_run_succeeded": complete["status"] == "succeeded",
            "target_retries_only_request_2": [x["request"] for x in continuation_events if x["call"] == "item-1"] == ["request-2"],
            "success_nodes_not_repeated": all(x["call"] not in ("item-0", "independent") for x in continuation_events),
            "old_parameters_preserved": all(x["parameter"] == "original" for x in continuation_events),
            "old_input_tool_call_preserved": complete["calls"][target] == interrupted["calls"][target],
            "join_waited_for_two_successes": len(complete["calls"][joined]["inputs"]["items"]) == 2,
            "round_2_used_explicit_feedback": complete["calls"][second_round]["inputs"]["item"] == complete["nodes"][joined]["outputs"]["result"],
        }
        delivered_files = []
        for package_id in complete["nodes"][second_round]["outputs"]["result"]:
            package = app.package(package_id)
            for key in package.files:
                with package.open(key) as reader:
                    content = reader.read()
                delivered_files.append({"package_id": package_id, "key": key, "bytes": len(content),
                                        "content": content.decode()})
        checks["actual_final_fasta_files_readable"] = len([item for item in delivered_files if item["key"].endswith(".fasta")]) == 3
        checks["partial_file_readable_before_continue"] = len(partial_files) == 1 and cases[1]["sequence"] in partial_files[0]["content"]
        checks["final_files_match_selected_inputs"] = sorted(
            item["content"].splitlines()[1] for item in delivered_files if item["key"].endswith(".fasta")
        ) == sorted([cases[0]["sequence"], cases[1]["sequence"], cases[1]["sequence"]])
        evidence["scenarios"][scenario] = {
            "flow_kind": "explicitly expanded two-round DAG; no native nested scheduler",
            "before_continuation": snapshot(app, interrupted, scopes),
            "after_continuation": snapshot(app, complete, scopes),
            "before_events": before_events, "continuation_events": continuation_events,
            "partial_files_read_before_continuation": partial_files,
            "actual_delivered_files": delivered_files, "checks": checks,
        }
        (controls / "events.jsonl").unlink()
        (controls / "ready-to-cancel").unlink(missing_ok=True)
    evidence["passed"] = all(all(item["checks"].values()) for item in evidence["scenarios"].values())
    output = HERE / "evidence" / "actual-host-run.json"
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": evidence["passed"], "scratch": str(scratch), "evidence": str(output),
        "scenarios": {name: data["checks"] for name, data in evidence["scenarios"].items()}}, indent=2))
    if not evidence["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
