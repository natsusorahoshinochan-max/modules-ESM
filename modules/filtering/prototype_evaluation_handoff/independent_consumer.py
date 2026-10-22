"""THROWAWAY independent consumer: stdlib + Gemmi, no producer imports."""
import json
from pathlib import Path
import sys

import gemmi

package = Path(sys.argv[1])
manifest = json.loads((package / "manifest.json").read_text())
for key in manifest["files"]:
    (package / key).read_bytes()
objects = []
for obj in manifest["objects"]:
    fasta = (package / obj["sequence_file"]).read_text().splitlines()
    sequence = "".join(line.strip() for line in fasta if not line.startswith(">"))
    structure = gemmi.read_structure(str(package / obj["structure_file"]))
    actual = "".join(gemmi.find_tabulated_residue(residue.name).one_letter_code for chain in structure[0]
                     for residue in chain if gemmi.find_tabulated_residue(residue.name).is_amino_acid())
    if actual != sequence or sequence != obj["sequence"]:
        raise ValueError("Delivered sequence and actual coordinate residues disagree")
    objects.append({"object_id": obj["object_id"], "sequence_length": len(sequence), "observed_structure_residues": len(actual)})
evaluations = []
for evaluation in manifest["evaluations"]:
    comparison_file = package / evaluation["comparison_file"]
    comparison = json.loads(comparison_file.read_text())
    for side in ("subject", "reference"):
        gemmi.read_structure(str(comparison_file.parent / comparison[side]["structure"]["file"]))
    if comparison["subject"]["id"] != evaluation["subject_id"] or comparison["reference"]["id"] != evaluation["reference_id"]:
        raise ValueError("Evaluation subject/reference association disagrees")
    if comparison["metrics"] != evaluation["metrics"] or comparison["region"] != evaluation["region"] or comparison["method"] != evaluation["method"]:
        raise ValueError("Evaluation metrics/scope disagree")
    evaluations.append({"subject_id": evaluation["subject_id"], "reference_id": evaluation["reference_id"],
                        "region": evaluation["region"], "method": evaluation["method"]["name"], "tm_reference": evaluation["metrics"]["tm_reference"]})
print(json.dumps({"objects": objects, "evaluations": evaluations, "producer_imports": [],
                  "readable_files": len(manifest["files"]), "working_directory": str(package)}, ensure_ascii=False))
