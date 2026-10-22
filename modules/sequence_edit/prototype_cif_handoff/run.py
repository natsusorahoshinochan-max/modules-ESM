"""THROWAWAY: compare two deliveries from one real, reachable editing action."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
MODULES = HERE.parents[1]


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def write_edited_cif(source_path: Path, request: dict, destination: Path) -> None:
    """Producer writes the edited template using ordinary PDBx/mmCIF categories."""
    import gemmi

    source = gemmi.read_structure(str(source_path))
    chain = source[0][request["chain"]]
    residues = {(r.seqid.num, r.seqid.icode.strip()): r for r in chain}
    targets = [None if item is None else residues[(item["author_number"], item["insertion_code"])]
               for item in request["target_to_source"]]
    monomers = ["UNK" if residue is None else residue.name for residue in targets]
    sequence = "".join(gemmi.find_tabulated_residue(name).one_letter_code for name in monomers)
    document = gemmi.cif.Document()
    block = document.add_new_block("PROTOTYPE_edited_1PGA_template")
    block.set_pair("_entry.id", "PROTOTYPE_edited_1PGA_template")
    block.set_pair("_struct.title", gemmi.cif.quote(
        "Edited template: 1PGA chain A, insert three unknown residues after A11, delete A25; "
        "retained coordinates copied without prediction or relaxation"))
    entity = block.init_loop("_entity.", ["id", "type", "pdbx_description"])
    entity.add_row(["1", "polymer", gemmi.cif.quote("Edited protein template")])
    polymer = block.init_loop("_entity_poly.", ["entity_id", "type", "pdbx_seq_one_letter_code",
                                               "pdbx_seq_one_letter_code_can", "pdbx_strand_id"])
    polymer.add_row(["1", gemmi.cif.quote("polypeptide(L)"), sequence, sequence, "A"])
    entity_sequence = block.init_loop("_entity_poly_seq.", ["entity_id", "num", "mon_id", "hetero"])
    components = block.init_loop("_chem_comp.", ["id", "type"])
    for name in sorted(set(monomers)):
        components.add_row([name, gemmi.cif.quote("peptide linking" if name == "GLY" else "L-peptide linking")])
    asym = block.init_loop("_struct_asym.", ["id", "entity_id"])
    asym.add_row(["A", "1"])
    scheme = block.init_loop("_pdbx_poly_seq_scheme.", [
        "asym_id", "entity_id", "seq_id", "mon_id", "ndb_seq_num", "pdb_seq_num", "auth_seq_num",
        "pdb_mon_id", "auth_mon_id", "pdb_strand_id", "pdb_ins_code", "hetero"])
    atoms = block.init_loop("_atom_site.", [
        "group_PDB", "id", "type_symbol", "label_atom_id", "label_alt_id", "label_comp_id",
        "label_asym_id", "label_entity_id", "label_seq_id", "pdbx_PDB_ins_code", "Cartn_x", "Cartn_y",
        "Cartn_z", "occupancy", "B_iso_or_equiv", "auth_seq_id", "auth_comp_id", "auth_asym_id",
        "auth_atom_id", "pdbx_PDB_model_num"])
    # Adding categories can move Gemmi's block items; retrieve earlier loops now.
    entity_sequence = block.find_loop("_entity_poly_seq.entity_id").get_loop()
    scheme = block.find_loop("_pdbx_poly_seq_scheme.asym_id").get_loop()
    serial = 0
    for target_index, (monomer, residue) in enumerate(zip(monomers, targets), 1):
        label = str(target_index)
        entity_sequence.add_row(["1", label, monomer, "n"])
        author = "?" if residue is None else str(residue.seqid.num)
        insertion = "." if residue is None else residue.seqid.icode.strip() or "."
        coordinate_monomer = "?" if residue is None else monomer
        scheme.add_row(["A", "1", label, monomer, label, author, author,
                        coordinate_monomer, coordinate_monomer, "A", insertion, "n"])
        if residue is None:
            continue
        for atom in residue:
            serial += 1
            atoms.add_row([
                "ATOM", str(serial), atom.element.name, atom.name, ".", monomer, "A", "1", label,
                insertion, f"{atom.pos.x:.3f}", f"{atom.pos.y:.3f}", f"{atom.pos.z:.3f}",
                f"{atom.occ:.2f}", f"{atom.b_iso:.2f}", author, monomer, "A", atom.name, "1"])
    document.write_file(str(destination))


def compile_cif_request(request: dict, bundle: Path):
    """Independent receiver reads standard fields and target-based conditions only."""
    import gemmi
    import numpy as np
    import torch
    from esm.sdk.api import ESMProtein
    from esm.utils import residue_constants

    block = gemmi.cif.read_file(str(bundle / request["structure_file"])).sole_block()
    entity_id = next(row[1] for row in block.find("_struct_asym.", ["id", "entity_id"])
                     if row[0] == request["chain"])
    residues = [(int(row[1]), row[2]) for row in block.find("_entity_poly_seq.", ["entity_id", "num", "mon_id"])
                if row[0] == entity_id]
    residues.sort()
    assert [row[0] for row in residues] == list(range(1, len(residues) + 1))
    observed = {}
    for row in block.find("_atom_site.", ["label_asym_id", "label_seq_id", "label_atom_id", "Cartn_x", "Cartn_y", "Cartn_z"]):
        if row[0] == request["chain"]:
            observed[(int(row[1]) - 1, row[2])] = [float(row[index]) for index in (3, 4, 5)]
    sequence = ["_"] * len(residues)
    for condition in request["sequence_conditions"]:
        sequence[condition["target_index"]] = condition["amino_acid"]
    coordinates = np.full((len(residues), 37, 3), np.nan, dtype=np.float32)
    for condition in request["coordinate_conditions"]:
        for atom in condition["atoms"]:
            coordinates[condition["target_index"], residue_constants.atom_order[atom]] = observed[(condition["target_index"], atom)]
    return ESMProtein(sequence="".join(sequence), coordinates=torch.tensor(coordinates))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=HERE / "evidence")
    args = parser.parse_args()
    sys.path.insert(0, str(args.source_root.resolve() / "repositories" / "esm"))
    import attr
    import Bio
    from Bio.PDB import MMCIFParser
    from Bio.PDB.MMCIF2Dict import MMCIF2Dict
    import gemmi
    import numpy as np
    import torch
    from esm.sdk.api import ESMProtein
    from esm.tokenization.sequence_tokenizer import EsmSequenceTokenizer
    from esm.utils.encoding import tokenize_sequence

    output = args.output.resolve()
    route_a, route_b = output / "route-a", output / "route-b"
    route_a.mkdir(parents=True, exist_ok=True)
    route_b.mkdir(parents=True, exist_ok=True)
    (output / "comparison.json").unlink(missing_ok=True)
    actions = {"actions": [{"type": "insert3"}, {"type": "delete25"}]}
    write_json(output / "user-actions.json", actions)
    bridge = HERE.parent / "prototype_file_handoff" / "export.cjs"
    subprocess.run(["node", str(bridge), str(output / "user-actions.json"), str(route_a / "request.json")], check=True)
    request_a = json.loads((route_a / "request.json").read_text())
    fixture = MODULES / "esm3" / "prototype_file_input" / "fixtures" / "1PGA.pdb"
    shutil.copyfile(fixture, route_a / "1PGA.pdb")
    write_edited_cif(route_a / "1PGA.pdb", request_a, route_b / "edited.cif")
    request_b = {"structure_file": "edited.cif", "chain": "A",
                 "sequence_conditions": request_a["sequence_conditions"],
                 "coordinate_conditions": request_a["coordinate_conditions"]}
    write_json(route_b / "request.json", request_b)

    previous_adapter_path = MODULES / "esm3" / "prototype_file_input" / "run.py"
    spec = importlib.util.spec_from_file_location("previous_file_input_prototype", previous_adapter_path)
    previous_adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(previous_adapter)
    protein_a, _, _ = previous_adapter.compile_request(request_a, route_a)
    protein_b = compile_cif_request(json.loads((route_b / "request.json").read_text()), route_b)

    # Read the new standard file independently with two existing general parsers.
    structure = gemmi.read_structure(str(route_b / "edited.cif"))
    bio_structure = MMCIFParser(QUIET=True, auth_chains=False, auth_residues=False).get_structure("edited", str(route_b / "edited.cif"))
    bio_cif = MMCIF2Dict(str(route_b / "edited.cif"))
    full_sequence = structure.entities[0].full_sequence
    target_numbers = list(map(int, bio_cif["_entity_poly_seq.num"]))
    observed_numbers = sorted(set(map(int, bio_cif["_atom_site.label_seq_id"])))
    tokenizer = EsmSequenceTokenizer()
    tokens_a = tokenize_sequence(protein_a.sequence, tokenizer).tolist()
    tokens_b = tokenize_sequence(protein_b.sequence, tokenizer).tolist()
    previous_evidence = MODULES / "esm3" / "prototype_file_input" / "evidence"
    prior = np.load(previous_evidence / "compiled-inputs.npz")
    prior_request = json.loads((previous_evidence / "request.json").read_text())
    fields_equal = {}
    for field in attr.fields(ESMProtein):
        left, right = getattr(protein_a, field.name), getattr(protein_b, field.name)
        fields_equal[field.name] = bool(torch.allclose(left, right, rtol=0, atol=0, equal_nan=True)) if isinstance(left, torch.Tensor) else left == right
    results = {
        "same_reachable_user_request_as_previous_real_generation": request_a == prior_request,
        "cif_entity_sequence_58": len(full_sequence) == 58 and len(target_numbers) == 58,
        "three_inserted_unknowns_without_atoms": full_sequence[11:14] == ["UNK"] * 3 and all(i not in observed_numbers for i in [12, 13, 14]),
        "observed_residues_55_in_gemmi_and_biopython": len(structure[0]["A"]) == 55 and len(list(bio_structure.get_residues())) == 55,
        "same_all_native_esmprotein_fields": all(fields_equal.values()),
        "same_native_sequence_token_ids": tokens_a == tokens_b,
        "same_coordinates_as_previous_real_generation_input": bool(np.array_equal(protein_b.coordinates.numpy(), prior["coordinates"], equal_nan=True)),
        "fixed_five_sequence_positions": protein_b.sequence == "MTYKL" + "_" * 53,
        "selected_backbone_atoms_165": int(torch.isfinite(protein_b.coordinates).all(-1).sum()) == 165,
        "no_target_to_source_in_cif_request": "target_to_source" not in request_b,
    }
    assert all(results.values()), results
    np.savez_compressed(output / "native-inputs.npz", route_a_coordinates=protein_a.coordinates.numpy(),
                        route_b_coordinates=protein_b.coordinates.numpy(),
                        route_a_sequence_tokens=np.asarray(tokens_a), route_b_sequence_tokens=np.asarray(tokens_b))
    summary = {
        "status": "passed", "question": "Can a complete edited mmCIF plus the same conditions replace source PDB plus an external target mapping for this edit?",
        "user_scenario": "1PGA chain A; insert 3 unknown positions after source A11; delete source A25; fix first 5 letters; condition on retained N/CA/C coordinates",
        "results": results, "native_field_equality": fields_equal,
        "target_sequence": bio_cif["_entity_poly.pdbx_seq_one_letter_code_can"][0],
        "native_sequence_prompt": protein_b.sequence,
        "full_target_length": len(full_sequence), "observed_target_positions": observed_numbers,
        "coordinate_shape": list(protein_b.coordinates.shape),
        "sequence_token_ids": tokens_b,
        "parsers": {"gemmi": gemmi.__version__, "biopython": Bio.__version__, "torch": torch.__version__},
        "verdict": "Both deliveries construct exactly the same native ESMProtein, including unknown positions and coordinate masks. This generation request does not need an external target_to_source mapping when the edited mmCIF contains the complete target axis.",
        "scope": "One reachable user workflow, native ESMProtein and tokenizer execution, two standard parsers. No repeated model inference: input equals the saved input used in prior real generation. Biological quality, folding and iterative evaluation are outside this comparison.",
    }
    write_json(output / "comparison.json", summary)
    print(json.dumps({"status": summary["status"], "target_length": len(full_sequence), "observed": 55,
                      "same_native_input": all(fields_equal.values()), "same_as_prior_generation_input": results["same_coordinates_as_previous_real_generation_input"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
