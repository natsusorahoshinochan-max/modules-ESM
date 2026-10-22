"""THROWAWAY: six real comparisons, shared UI/CLI filtering, independent read."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, default=ROOT / "modules/sequence_edit/prototype_result_feedback/evidence/candidates/manifest.json")
    parser.add_argument("--output", type=Path, default=HERE / "evidence")
    parser.add_argument("--primary-only", action="store_true", help="Reuse the fixed primary score for a later round without the extra comparison branches")
    args = parser.parse_args()
    from modules.structure_comparison.api import StructureInput, compare
    import tmtools

    plan = json.loads((HERE / "plan.json").read_text())
    incoming = json.loads(args.candidates.read_text())
    if len(incoming["objects"]) != 2:
        raise ValueError("This rehearsal requires the two actual generated candidates")
    evidence = args.output.resolve()
    package = evidence / "all-candidates"
    package.mkdir(parents=True, exist_ok=True)
    objects = []
    for i, obj in enumerate(incoming["objects"], 1):
        source = args.candidates.parent / obj["structure_file"]
        suffix = source.suffix
        structure_file = f"objects/candidate-{i}{suffix}"
        sequence_file = f"objects/candidate-{i}.fasta"
        (package / structure_file).parent.mkdir(exist_ok=True)
        shutil.copyfile(source, package / structure_file)
        (package / sequence_file).write_text(f'>{obj["object_id"]}\n{obj["sequence"]}\n')
        objects.append({**obj, "structure_file": structure_file, "sequence_file": sequence_file})

    original = ROOT / "modules/esm3/prototype_file_input/fixtures/1PGA.pdb"
    (package / "references").mkdir(exist_ok=True)
    shutil.copyfile(original, package / "references/original-1pga.pdb")
    references = [{"object_id": "original-1pga", "label": "原始 1PGA · A 链 56 位", "structure_file": "references/original-1pga.pdb"},
                  {"object_id": objects[0]["object_id"], "label": "候选一 · 本次明确选择的结构参考", "structure_file": objects[0]["structure_file"]}]
    positions = {"positions": [{"chain": "A", "author_number": n, "insertion_code": ""} for n in [1, 2, 3, 4, 5, 30, 31, 32, 33, 34, 35]]}
    regions = {"full-chain-A": {"chains": ["A"]}, "A:1-5,30-35": positions}
    source_for = lambda obj: StructureInput(obj["object_id"], (package / obj["structure_file"]).read_bytes(),
                                           "pdb" if obj["structure_file"].endswith(".pdb") else "mmcif",
                                           sequence=obj.get("sequence"), label=obj["label"])
    evaluations, options = [], []
    runtime = SimpleNamespace(workdir=evidence / "comparison-work", cancelled=False)
    runtime.workdir.mkdir(exist_ok=True)
    for spec in plan["comparisons"][:1] if args.primary_only else plan["comparisons"]:
        ref = references[1 if spec["reference"] == "first-candidate" else 0]
        option_key = spec["key"] + ":tm_reference"
        options.append({"key": option_key, "label": ref["label"] + " · " + spec["region"] + " · TM-score / 参考长度",
                        "reference_id": ref["object_id"], "region_key": spec["region"], "method_name": "TM-align", "metric": "tm_reference"})
        for index, obj in enumerate(objects, 1):
            outcome = compare(source_for(obj), source_for(ref), runtime,
                              subject_selection=regions[spec["region"]], reference_selection=regions[spec["region"]])
            delivery = outcome.outputs["comparison"][0]
            comparison = json.loads((runtime.workdir / delivery.files[delivery.entry]).read_text())
            destination = f'comparisons/{spec["key"]}-{index}'
            (package / destination).mkdir(parents=True, exist_ok=True)
            for key, relative in delivery.files.items():
                shutil.copyfile(runtime.workdir / relative, package / destination / key)
            evaluations.append({"evaluation_id": comparison["id"], "subject_id": obj["object_id"],
                                "reference_id": ref["object_id"], "region_key": spec["region"],
                                "method": comparison["method"], "region": comparison["region"],
                                "metrics": comparison["metrics"], "alignment": comparison["alignment"],
                                "comparison_file": destination + "/manifest.json",
                                "files": [destination + "/" + key for key in delivery.files]})
    collection = {"format": "prototype.evaluated_collection", "objects": objects, "references": references,
                  "evaluations": evaluations, "score_options": options,
                  "evidence_scope": "Actual ESM3 generated structures and native TM-align scores; structure generation is the actual source of the compared coordinates."}
    save(package / "manifest.json", collection)
    save(evidence / "collection.json", collection)
    save(evidence / "actual-tool.json", {"entry": "modules.structure_comparison.api.compare", "tmtools": tmtools.__version__, "calls": len(evaluations)})
    shutil.rmtree(runtime.workdir)
    native_values = {e["subject_id"]: e["metrics"]["tm_reference"]["value"] for e in evaluations
                     if e["reference_id"] == "original-1pga" and e["region_key"] == "full-chain-A"}
    expected = [obj["object_id"] for obj in sorted(objects, key=lambda obj: -native_values[obj["object_id"]])
                if native_values[obj["object_id"]] >= plan["primary_filter"]["threshold"]][:plan["primary_filter"]["limit"]]
    # Publish the scientific result promptly for the next-round model consumer.
    save(evidence / "primary-selection.json", {"parameters": plan["primary_filter"], "values": native_values, "selected_ids": expected,
                                               "independent_calculation": "Python sort by descending native value, stable input order; threshold before limit"})
    html = (HERE / "index.html").read_text()
    file_texts = {str(path.relative_to(package)): path.read_text() for path in package.rglob("*") if path.is_file()}
    embedded = json.dumps({"collection": collection, "plan": plan, "file_texts": file_texts}, ensure_ascii=False, allow_nan=False).replace("</", "<\\/")
    start = '<script id="evidence" type="application/json">'
    a, b = html.index(start) + len(start), html.index("</script>", html.index(start))
    html_output = HERE / "index.html" if evidence == HERE / "evidence" else evidence / "index.html"
    html_output.write_text(html[:a] + embedded + html[b:])
    result = json.loads(subprocess.check_output(["node", str(HERE / "replay.cjs"), str(evidence / "collection.json"), str(HERE / "plan.json")], text=True))
    if result["primary"]["selected_ids"] != expected:
        raise AssertionError("Shared JS selection differs from independent native-score calculation")
    selected_package = evidence / "PROTOTYPE_WIPE_ME" / "selected"
    if selected_package.exists():
        shutil.rmtree(selected_package)
    selected_package.mkdir(parents=True, exist_ok=True)
    extracted = result["primary"]["extracted"]
    for key in extracted["files"]:
        destination = selected_package / key
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(package / key, destination)
    save(selected_package / "manifest.json", extracted)
    consumer_output = subprocess.check_output([sys.executable, "-I", str(HERE / "independent_consumer.py"), str(selected_package)], cwd=selected_package, text=True)
    result["independent_consumer"] = json.loads(consumer_output)
    result["independent_expected"] = expected
    result["compared_against_independent_calculation"] = True
    save(evidence / "result.json", result)
    print(json.dumps({"selected_ids": expected, "native_values": native_values, "comparisons": len(evaluations),
                      "independent_read": result["independent_consumer"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
