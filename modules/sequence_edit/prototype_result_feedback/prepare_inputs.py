"""THROWAWAY: populate the HTML with actual results and execute its editing actions."""
import argparse
import json
from pathlib import Path
import subprocess

import gemmi

HERE = Path(__file__).resolve().parent


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def write_target_cif(target, path):
    """Structure-module side: current positions and real atoms become standard mmCIF."""
    aa = dict(zip("ACDEFGHIKLMNPQRSTVWYX", "ALA CYS ASP GLU PHE GLY HIS ILE LYS LEU MET ASN PRO GLN ARG SER THR VAL TRP TYR UNK".split()))
    document = gemmi.cif.Document()
    block = document.add_new_block("PROTOTYPE_feedback_target")
    block.set_pair("_entry.id", "PROTOTYPE_feedback_target")
    block.set_pair("_struct.title", gemmi.cif.quote("Edited target template; atom coordinates retained from selected generated result"))
    block.init_loop("_entity.", ["id", "type"]).add_row(["1", "polymer"])
    sequence = "".join(row["amino_acid"] for row in target["positions"])
    block.init_loop("_entity_poly.", ["entity_id", "type", "pdbx_seq_one_letter_code", "pdbx_seq_one_letter_code_can", "pdbx_strand_id"]).add_row(["1", "'polypeptide(L)'", sequence, sequence, "A"])
    block.init_loop("_struct_asym.", ["id", "entity_id"]).add_row(["A", "1"])
    block.init_loop("_entity_poly_seq.", ["entity_id", "num", "mon_id", "hetero"])
    block.init_loop("_pdbx_poly_seq_scheme.", ["asym_id", "entity_id", "seq_id", "mon_id", "pdb_seq_num", "auth_seq_num", "pdb_mon_id", "auth_mon_id", "pdb_strand_id", "pdb_ins_code", "hetero"])
    atoms = block.init_loop("_atom_site.", ["group_PDB", "id", "type_symbol", "label_atom_id", "label_alt_id", "label_comp_id", "label_asym_id", "label_entity_id", "label_seq_id", "pdbx_PDB_ins_code", "Cartn_x", "Cartn_y", "Cartn_z", "occupancy", "B_iso_or_equiv", "auth_seq_id", "auth_comp_id", "auth_asym_id", "auth_atom_id", "pdbx_PDB_model_num"])
    positions = block.find_loop("_entity_poly_seq.entity_id").get_loop()
    scheme = block.find_loop("_pdbx_poly_seq_scheme.asym_id").get_loop()
    serial = 0
    for row in target["positions"]:
        index, monomer = str(row["target_position"]), aa[row["amino_acid"]]
        positions.add_row(["1", index, monomer, "n"])
        observed = bool(row["atoms"])
        author = str(row["author_number"]) if observed else "?"
        scheme.add_row(["A", "1", index, monomer, author, author, monomer if observed else "?", monomer if observed else "?", "A", ".", "n"])
        for name, xyz in row["atoms"].items():
            serial += 1
            atoms.add_row(["ATOM", str(serial), name[0], name, ".", monomer, "A", "1", index, ".", *(f"{x:.3f}" for x in xyz), "1.0", "0.0", author, monomer, "A", name, "1"])
    document.write_file(str(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True, help="Manifest from the actual filtering/collection extraction")
    args = parser.parse_args()
    output = HERE / "evidence"
    manifest = json.loads((output / "candidates/manifest.json").read_text())
    selected_manifest = json.loads(args.selection.read_text())
    selected = selected_manifest["objects"][0]
    selected_id = selected["object_id"]
    data = {"objects": [], "evidence_note": "嵌入两份真实 ESM3 生成结构。实际采样、参数、分数选择和第二轮结果见 evidence。页面上的编辑只在内存中。"}
    for item in manifest["objects"]:
        source_path = output / "candidates" / item["structure_file"]
        if item["object_id"] == selected_id:
            item = selected
            source_path = args.selection.parent / item["structure_file"]
        chain = gemmi.read_structure(str(source_path))[0]["A"]
        positions = [{"atoms": {atom.name: [atom.pos.x, atom.pos.y, atom.pos.z] for atom in residue}} for residue in chain]
        assert len(positions) == len(item["sequence"])
        data["objects"].append({"object_id": item["object_id"], "label": item["label"], "sequence": item["sequence"], "positions": positions})
    html_path = HERE / "index.html"
    html = html_path.read_text()
    start = html.index('<script id="fixture-data">') + len('<script id="fixture-data">')
    end = html.index("</script>", start)
    html_path.write_text(html[:start] + "const FEEDBACK_DATA = " + json.dumps(data, ensure_ascii=False) + ";" + html[end:])
    edit = {"type": "preview", "after": 11, "count": 2, "delete_position": 27}
    conditions = [{"type": "fix", "regions": "1-5"}, {"type": "coords", "regions": "1-5,30-35"}]
    for mode in ["feedback", "sequence-only", "cancel"]:
        bundle = output / mode
        bundle.mkdir(exist_ok=True)
        actions = [{"type": "sequence_only" if mode == "sequence-only" else "choose", "object_id": selected_id}]
        actions += conditions[:1] if mode == "sequence-only" else conditions
        actions += [edit, {"type": "cancel" if mode == "cancel" else "confirm"}, {"type": "deliver"}]
        write(bundle / "actions.json", {"actions": actions})
        subprocess.run(["node", str(HERE / "export.cjs"), str(bundle / "actions.json"), str(bundle / "html-export.json")], check=True)
        exported = json.loads((bundle / "html-export.json").read_text())
        delivery = exported["delivery"]
        write(bundle / "request.json", delivery["request"])
        write(bundle / "target.json", delivery["target"])
        if mode != "sequence-only":
            write_target_cif(delivery["target"], bundle / "target.cif")
        expected = 58 if mode == "cancel" else 59
        assert len(delivery["target"]["positions"]) == expected
        assert len(delivery["request"]["sequence_conditions"]) == 5
        assert len(delivery["request"]["coordinate_conditions"]) == (0 if mode == "sequence-only" else 11)
        if mode == "cancel":
            before = exported["snapshots"][2]["state"]["rows"]
            after = exported["snapshots"][-1]["state"]["rows"]
            assert before == after
        if mode == "feedback":
            assert [r["target_index"] + 1 for r in delivery["request"]["coordinate_conditions"]] == [1, 2, 3, 4, 5, 31, 32, 33, 34, 35, 36]
            assert [r["target_position"] for r in delivery["target"]["positions"] if not r["atoms"]] == [12, 13]
    write(output / "editing-summary.json", {"status": "passed", "selected_object_id": selected_id,
          "input_manifest": str(args.selection.resolve()), "input_structure": str((args.selection.parent / selected["structure_file"]).resolve()),
          "executed": "same pure reducer embedded in index.html, invoked by export.cjs", "source_length": 58,
          "confirmed_target_length": 59, "inserted_positions": [12, 13], "removed_source_position": 25,
          "fixed_sequence_positions": [1, 2, 3, 4, 5], "coordinate_positions": [1, 2, 3, 4, 5, 31, 32, 33, 34, 35, 36],
          "cancel_restores_all_rows_and_conditions": True, "sequence_only_target_length": 59})
    print("Actual HTML logic exported confirmed 59-position and cancelled 58-position templates")


if __name__ == "__main__":
    main()
