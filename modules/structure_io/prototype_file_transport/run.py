"""THROWAWAY: measure standard-file transport with real upstream parsers.

This executes parsers/featurization, not protein generation. Challenge inputs are
programmatic variants of the archived 1PGA structure, not experimental structures.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
import warnings

HERE = Path(__file__).resolve().parent


def clean(value):
    import numpy as np
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean(v) for v in value]
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def attempt(callback):
    with warnings.catch_warnings(record=True) as observed:
        warnings.simplefilter("always")
        try:
            result = {"status": "returned", "value": callback()}
        except Exception as error:
            result = {"status": "raised", "error": type(error).__name__, "message": str(error)}
    result["warnings"] = [str(w.message) for w in observed]
    return result


def pdb_lines(path):
    return path.read_text().splitlines()


def atom(line):
    return line.startswith(("ATOM  ", "HETATM"))


def put_pdb(path, lines):
    path.write_text("\n".join(lines) + "\n")


def edit_cif(source, destination, transform):
    import gemmi
    doc = gemmi.cif.read(str(source))
    transform(doc.sole_block())
    doc.write_file(str(destination))


def change_author_ids(block, chain, renumber):
    for tag in ["_atom_site.auth_asym_id", "_entity_poly.pdbx_strand_id", "_pdbx_poly_seq_scheme.pdb_strand_id"]:
        values = block.find_values(tag)
        for i, value in enumerate(values):
            if value == "A":
                values[i] = chain
    for tag in ["_atom_site.auth_seq_id", "_pdbx_poly_seq_scheme.auth_seq_num", "_pdbx_poly_seq_scheme.pdb_seq_num"]:
        values = block.find_values(tag)
        for i, value in enumerate(values):
            if value.lstrip("-").isdigit():
                values[i] = str(renumber(int(value)))


def remove_cif_atoms(block, label_position):
    loop = block.find_loop("_atom_site.id").get_loop()
    width = loop.width()
    rows = [loop.values[i:i + width] for i in range(0, len(loop.values), width)]
    column = list(loop.tags).index("_atom_site.label_seq_id")
    rows = [row for row in rows if row[column] != str(label_position)]
    loop.set_all_values([list(col) for col in zip(*rows)])
    for tag in ["_pdbx_poly_seq_scheme.auth_seq_num", "_pdbx_poly_seq_scheme.pdb_seq_num"]:
        block.find_values(tag)[label_position - 1] = "?"


def insertion_cif(block):
    table = block.find(["_atom_site.label_seq_id", "_atom_site.auth_seq_id", "_atom_site.pdbx_PDB_ins_code"])
    for row in table:
        if row[0].isdigit():
            position = int(row[0])
            if position >= 12:
                row[1] = str(position - 1)
            if position == 12:
                row[2] = "A"
    table = block.find(["_pdbx_poly_seq_scheme.seq_id", "_pdbx_poly_seq_scheme.auth_seq_num", "_pdbx_poly_seq_scheme.pdb_seq_num", "_pdbx_poly_seq_scheme.pdb_ins_code"])
    for row in table:
        position = int(row[0])
        if position >= 12:
            row[1] = row[2] = str(position - 1)
        if position == 12:
            row[3] = "A"


def esm_summary(chain):
    import numpy as np
    return {"sequence": chain.sequence, "length": len(chain.sequence), "chain": chain.chain_id,
            "author_numbers": chain.residue_index.tolist(), "insertion_codes": chain.insertion_code.tolist(),
            "observed_positions": np.where(chain.atom37_mask.any(-1))[0].tolist(),
            "atom37_mask": chain.atom37_mask.tolist(), "atom37_positions": chain.atom37_positions}


def coordinate_list(structure):
    return [[a.pos.x, a.pos.y, a.pos.z] for model in structure for chain in model for residue in chain for a in residue]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=HERE / "evidence")
    args = parser.parse_args()
    source = args.source_root.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").unlink(missing_ok=True)
    fixtures = output / "inputs"
    fixtures.mkdir(exist_ok=True)
    sys.path[:0] = [str(source / "repositories" / "esm"), str(source / "repositories" / "ProteinMPNN")]
    import gemmi
    import numpy as np
    import torch
    import biotite
    from Bio.PDB import MMCIFParser
    from esm.utils.structure.protein_chain import ProteinChain
    from esm.utils import residue_constants
    from protein_mpnn_utils import parse_PDB, tied_featurize, _S_to_seq

    raw_pdb = HERE.parent.parent / "esm3" / "prototype_real_validation" / "fixtures" / "1PGA.pdb"
    raw_cif = HERE / "fixtures" / "1PGA.cif"
    base_pdb, base_cif = fixtures / "original-1PGA.pdb", fixtures / "original-1PGA.cif"
    shutil.copyfile(raw_pdb, base_pdb)
    shutil.copyfile(raw_cif, base_cif)
    original = pdb_lines(base_pdb)
    summary = {"question": "What does standard-file transport preserve, and what must a receiving adapter select or map explicitly?",
               "execution": "Actual ESM SDK loaders, ProteinMPNN parser and featurizer, Gemmi and Bio.PDB; no model inference.",
               "dependencies": {"gemmi": gemmi.__version__, "biotite": biotite.__version__, "torch": torch.__version__,
                                "esm_source": str(source / "repositories" / "esm"), "mpnn_source": str(source / "repositories" / "ProteinMPNN")},
               "scenarios": []}

    def scenario(key, title, facts, verdict, **details):
        save(output / f"{key}.json", details)
        summary["scenarios"].append({"id": key, "title": title, "observed": facts, "design_implication": verdict,
                                     "evidence": f"{key}.json"})

    base_esm = ProteinChain.from_pdb(base_pdb, chain_id="A")
    base_cif_esm = ProteinChain.from_mmcif(base_cif, chain_id="A")
    base_mpnn = parse_PDB(str(base_pdb), input_chain_list=["A"])[0]
    assert len(base_esm.sequence) == len(base_cif_esm.sequence) == len(base_mpnn["seq"]) == 56
    scenario("01-baseline", "原始 PDB 与 mmCIF 可直接交给实际 loader", ["PDB ESM、mmCIF ESM、PDB ProteinMPNN 均读取 56 个蛋白位置。"],
             "结构文件可成为公开交接载体；atom37 留在实际 SDK 内部。", esm_pdb=esm_summary(base_esm), esm_cif=esm_summary(base_cif_esm), mpnn=base_mpnn)

    namespace_cif = fixtures / "challenge-author-H101-label-A1.cif"
    edit_cif(base_cif, namespace_cif, lambda b: change_author_ids(b, "H", lambda n: n + 100))
    author_structure = MMCIFParser(QUIET=True, auth_chains=True, auth_residues=True).get_structure("author", namespace_cif)
    label_structure = MMCIFParser(QUIET=True, auth_chains=False, auth_residues=False).get_structure("label", namespace_cif)
    namespaces = {"author": [(c.id, next(c.get_residues()).id) for c in author_structure[0]],
                  "label": [(c.id, next(c.get_residues()).id) for c in label_structure[0]]}
    native_h = ProteinChain.from_mmcif(namespace_cif, chain_id="H")
    wrong_a = attempt(lambda: esm_summary(ProteinChain.from_mmcif(namespace_cif, chain_id="A")))
    assert native_h.residue_index[0] == 101 and wrong_a["status"] == "raised"
    scenario("02-namespaces", "同一 mmCIF 的 label 与 author 命名空间", ["Bio.PDB 读取同一文件得到 author 链 H/残基 101 或 label 链 A/序列位置 1。", "ESM 指定 author 链 H 成功；把 label 链 A 直接传入会报错。"],
             "选择参数必须明确命名空间；适配器依据文件中的对应关系转换。", parser_selections=namespaces, esm_author=esm_summary(native_h), esm_wrong_namespace=wrong_a)

    gap_pdb = fixtures / "challenge-unmodeled-A25.pdb"
    put_pdb(gap_pdb, [line for line in original if not(atom(line) and line[21] == "A" and int(line[22:26]) == 25)])
    gap_cif = fixtures / "challenge-unmodeled-A25.cif"
    edit_cif(base_cif, gap_cif, lambda b: remove_cif_atoms(b, 25))
    gap_esm = ProteinChain.from_pdb(gap_pdb, chain_id="A")
    gap_cif_esm = ProteinChain.from_mmcif(gap_cif, chain_id="A")
    gap_mpnn = parse_PDB(str(gap_pdb), input_chain_list=["A"])[0]
    assert len(gap_esm.sequence) == 55 and len(gap_cif_esm.sequence) == len(gap_mpnn["seq"]) == 56
    assert gap_mpnn["seq"][24] == "-" and not gap_cif_esm.atom37_mask[24].any()
    scenario("03-unmodeled-residue", "保留完整序列但移除 A25 原子的同一结构", ["ESM from_pdb 返回 55 位，忽略仍在文件中的 SEQRES 完整序列。", "ESM from_mmcif 返回 56 位，保留 A25 氨基酸且坐标缺失。", "ProteinMPNN PDB parser 返回 56 位，A25 变成 '-'，不是原有氨基酸。"],
             "文件格式相同或可转换不足以保证位置相同；接收模块要校验真实读取后的序列及位置。", esm_pdb=esm_summary(gap_esm), esm_cif=esm_summary(gap_cif_esm), mpnn=gap_mpnn)

    insertion_pdb = fixtures / "challenge-insertion-A11A.pdb"
    changed = []
    for line in original:
        if atom(line) and line.startswith("ATOM  "):
            n = int(line[22:26])
            line = line[:22] + f"{n - 1 if n >= 12 else n:4d}" + ("A" if n == 12 else " ") + line[27:]
        changed.append(line)
    put_pdb(insertion_pdb, changed)
    insertion_file = fixtures / "challenge-insertion-A11A.cif"
    edit_cif(base_cif, insertion_file, insertion_cif)
    insertion_esm = ProteinChain.from_pdb(insertion_pdb, chain_id="A")
    insertion_native_cif = ProteinChain.from_mmcif(insertion_file, chain_id="A")
    insertion_mpnn = parse_PDB(str(insertion_pdb), input_chain_list=["A"])[0]
    assert insertion_esm.residue_index[11] == 11 and insertion_esm.insertion_code[11] == "A"
    assert insertion_esm.atom37_mask[11].any()
    assert insertion_mpnn["seq"] == base_mpnn["seq"]
    assert insertion_native_cif.residue_index[11] == 12 and not insertion_native_cif.atom37_mask[11].any()
    scenario("04-insertion-code", "同一 author 编号带插入码的真实 loader 差异", ["PDB 的 A11 和 A11A 被 ESM 与 ProteinMPNN 保留为两个位置。", "当前固定 ESM mmCIF loader 将第二个 author 11 改为 12，仍带插入码 A，导致该位置坐标全丢失。"],
             "不能把 SDK 文件读取当成无损承诺；该 mmCIF 路径需显式校验或修正适配后再接入。", esm_pdb=esm_summary(insertion_esm), esm_cif=esm_summary(insertion_native_cif), mpnn=insertion_mpnn)

    numbering_pdb = fixtures / "challenge-author-numbering-gap.pdb"
    changed = []
    for line in original:
        if line.startswith("ATOM  ") and int(line[22:26]) >= 25:
            line = line[:22] + f"{int(line[22:26]) + 100:4d}" + line[26:]
        changed.append(line)
    put_pdb(numbering_pdb, changed)
    numbering_esm = ProteinChain.from_pdb(numbering_pdb, chain_id="A")
    numbering_mpnn = parse_PDB(str(numbering_pdb), input_chain_list=["A"])[0]
    assert len(numbering_esm.sequence) == 56 and len(numbering_mpnn["seq"]) == 156
    scenario("05-numbering-gap", "只有 author 编号跳跃，实际原子没有少", ["把 A25…A56 改为 A125…A156：ESM 仍有 56 位，ProteinMPNN 扩成 156 位，额外补 100 个 '-'。"],
             "工具的链内索引由真实 parser 决定；不能把 author 编号当作连续目标序列位置。", esm=esm_summary(numbering_esm), mpnn=numbering_mpnn)

    missing_o = fixtures / "challenge-missing-O-A11.pdb"
    put_pdb(missing_o, [line for line in original if not(line.startswith("ATOM  ") and int(line[22:26]) == 11 and line[12:16].strip() == "O")])
    missing_mpnn = parse_PDB(str(missing_o), input_chain_list=["A"])[0]
    features = tied_featurize([deepcopy(missing_mpnn)], torch.device("cpu"), None)
    observed_mask = features[2].numpy()[0]
    rendered_seq = _S_to_seq(features[1][0], features[2][0])
    assert observed_mask[10] == 0 and len(rendered_seq) == 55
    scenario("06-missing-backbone", "缺少一个 O 原子并不会让原生 parser 报错", ["ProteinMPNN parser 接受 56 位输入；实际 featurizer 将 A11 的整残基 mask 置 0。", "使用其原生 mask 输出序列时，A11 消失，剩余 55 位。"],
             "承诺完整骨架设计的适配器应在调用前指出缺失的必需原子，不能默默缩短结果。", mpnn=missing_mpnn, feature_mask=observed_mask, native_masked_sequence=rendered_seq)

    altloc = fixtures / "challenge-altloc-A11-CA.pdb"
    changed = []
    expected_alt_a = None
    expected_alt_b = None
    for line in original:
        if line.startswith("ATOM  ") and int(line[22:26]) == 11 and line[12:16].strip() == "CA":
            expected_alt_a = [float(line[30:38]) + 20, float(line[38:46]), float(line[46:54])]
            expected_alt_b = [float(line[30:38]) + 40, float(line[38:46]), float(line[46:54])]
            for code, occ, xyz in [("A", 0.2, expected_alt_a), ("B", 0.8, expected_alt_b)]:
                changed.append(line[:16] + code + line[17:30] + "".join(f"{v:8.3f}" for v in xyz) + f"{occ:6.2f}" + line[60:])
        else:
            changed.append(line)
    put_pdb(altloc, changed)
    alt_esm = ProteinChain.from_pdb(altloc, chain_id="A")
    alt_mpnn = parse_PDB(str(altloc), input_chain_list=["A"])[0]
    ca = residue_constants.atom_order["CA"]
    assert np.allclose(alt_esm.atom37_positions[10, ca], expected_alt_a)
    assert np.allclose(alt_mpnn["coords_chain_A"]["CA_chain_A"][10], expected_alt_a)
    scenario("07-altloc", "占有率更高的构象并非自动采用", ["A11 CA 的 A 构象 occupancy=0.2、B=0.8；ESM 和 ProteinMPNN 都选文件中先出现的 A。"],
             "需要明确 altloc 选择，随后输出已选择的单构象文件；不能让不同 loader 默认值替用户选择。", supplied_A=expected_alt_a, supplied_B=expected_alt_b, esm=esm_summary(alt_esm), mpnn=alt_mpnn)

    multimodel = fixtures / "challenge-two-model-hybrid.pdb"
    first_atoms = [l for l in pdb_lines(missing_o) if atom(l)]
    second_atoms = []
    for line in original:
        if atom(line):
            second_atoms.append(line[:30] + "".join(f"{float(line[k:k+8]) + 100:8.3f}" for k in [30, 38, 46]) + line[54:])
    put_pdb(multimodel, ["MODEL        1", *first_atoms, "ENDMDL", "MODEL        2", *second_atoms, "ENDMDL", "END"])
    multi_esm = ProteinChain.from_pdb(multimodel, chain_id="A")
    multi_mpnn = parse_PDB(str(multimodel), input_chain_list=["A"])[0]
    native_o = multi_mpnn["coords_chain_A"]["O_chain_A"][10]
    original_o = base_mpnn["coords_chain_A"]["O_chain_A"][10]
    assert not multi_esm.atom37_mask[10, residue_constants.atom_order["O"]]
    assert np.allclose(native_o, np.array(original_o) + 100)
    assert np.allclose(multi_mpnn["coords_chain_A"]["CA_chain_A"][10], base_mpnn["coords_chain_A"]["CA_chain_A"][10])
    scenario("08-multiple-models", "ProteinMPNN 合并两个 MODEL 的原子", ["模型 1 缺少 A11 O；模型 2 全体原子平移 100 Å。", "ESM 只读模型 1；ProteinMPNN 保留模型 1 的 CA，却从模型 2 补入 O，形成不存在于任何原模型的混合骨架。"],
             "多构象文件必须先明确选择一个模型，再给只接受单构象的工具。", esm=esm_summary(multi_esm), mpnn=multi_mpnn, original_O=original_o, parsed_O=native_o)

    ligand_file = fixtures / "challenge-added-ligand.pdb"
    ligand_lines = ["HETATM 9001  C1  LIG B   1       1.000   2.000   3.000  1.00 20.00           C  ",
                    "HETATM 9002  O1  LIG B   1       2.000   2.000   3.000  1.00 20.00           O  "]
    put_pdb(ligand_file, [line for line in original if not line.startswith("END")] + ligand_lines + ["END"])
    ligand_structure = gemmi.read_structure(str(ligand_file))
    components = [{"chain": c.name, "residue": r.name, "author_number": r.seqid.num, "atoms": len(r)} for c in ligand_structure[0] for r in c if r.het_flag != "A"]
    ligand_esm = ProteinChain.from_pdb(ligand_file, chain_id="A")
    ligand_mpnn = parse_PDB(str(ligand_file))[0]
    assert len(ligand_esm.sequence) == len(ligand_mpnn["seq"]) == 56
    assert any(r["residue"] == "LIG" for r in components)
    scenario("09-components", "文件可保留配体和水，模型 loader 仍会过滤", ["Gemmi 保留 20 个水及人为加入的 2 原子 LIG；ESM/ProteinMPNN 输入对象只剩 56 位蛋白。"],
             "适配器必须明确本次任务选择的组分，并拒绝所选工具无法接纳的组分；原文件独立保留。", nonprotein_components=components, esm=esm_summary(ligand_esm), mpnn=ligand_mpnn)

    long_chain_cif = fixtures / "challenge-long-chain.cif"
    edit_cif(base_cif, long_chain_cif, lambda b: change_author_ids(b, "TARGET_LONG", lambda n: n))
    long_structure = gemmi.read_structure(str(long_chain_cif))
    conversion = attempt(lambda: long_structure.make_pdb_string())
    assert conversion["status"] == "raised"
    scenario("10-long-chain", "mmCIF 长链标识不能直接写入传统 PDB", ["TARGET_LONG 在 mmCIF 中读取成功；Gemmi 直接写 PDB 抛错。"],
             "转换需显式改名并输出位置对应；无法无损转出的内容应报告。", mmcif_chain_ids=[c.name for c in long_structure[0]], direct_pdb_conversion=conversion)

    # One small, explicit operation: choose a model, select protein chain, then
    # write contiguous tool numbering and keep the actual mapping in a sidecar.
    # It is intentionally not a shared schema or a general format converter.
    fixes = []
    for name, path, chosen_model, chosen_chain in [
        ("numbering-gap", numbering_pdb, 0, "A"),
        ("long-chain", long_chain_cif, 0, "TARGET_LONG"),
        ("model-two", multimodel, 1, "A"),
        ("insertion-code", insertion_file, 0, "A"),
    ]:
        loaded = gemmi.read_structure(str(path))
        selected = [r.clone() for c in loaded[chosen_model] if c.name == chosen_chain for r in c if r.het_flag == "A" and gemmi.find_tabulated_residue(r.name).is_amino_acid()]
        normalized = gemmi.Structure()
        model = gemmi.Model("1")
        chain = gemmi.Chain("A")
        mapping = []
        expected_coordinates = []
        for i, residue in enumerate(selected, start=1):
            mapping.append({"tool_chain": "A", "tool_position": i, "source_model": chosen_model + 1,
                            "source_author_chain": chosen_chain, "source_author_number": residue.seqid.num,
                            "source_insertion_code": residue.seqid.icode.strip()})
            expected_coordinates.extend([[a.pos.x, a.pos.y, a.pos.z] for a in residue])
            residue.seqid = gemmi.SeqId(i, " ")
            chain.add_residue(residue)
        model.add_chain(chain)
        normalized.add_model(model)
        normalized_path = output / f"explicit-{name}.pdb"
        normalized.write_pdb(str(normalized_path))
        save(output / f"explicit-{name}-mapping.json", {"selected": {"model": chosen_model + 1, "author_chain": chosen_chain, "components": "protein"}, "positions": mapping})
        back = gemmi.read_structure(str(normalized_path))
        mpnn_back = parse_PDB(str(normalized_path), input_chain_list=["A"])[0]
        esm_back = ProteinChain.from_pdb(normalized_path, chain_id="A")
        assert np.allclose(coordinate_list(back), expected_coordinates, atol=0.00051)
        assert len(mpnn_back["seq"]) == len(esm_back.sequence) == len(mapping) == 56
        assert np.isfinite(np.array(mpnn_back["coords_chain_A"]["O_chain_A"])).all()
        if name == "insertion-code":
            assert mapping[11]["source_author_number"] == 11 and mapping[11]["source_insertion_code"] == "A"
            assert esm_back.atom37_mask[11].any()
            fixed_source = next(item for item in mapping if item["source_author_number"] == 11 and item["source_insertion_code"] == "A")
            fixed = {mpnn_back["name"]: {"A": [fixed_source["tool_position"]]}}
            fixed_features = tied_featurize([deepcopy(mpnn_back)], torch.device("cpu"), None, fixed_position_dict=fixed)
            # Native chain_M_pos is tuple index 10, and fixed_positions use 1-based tool positions.
            assert fixed_features[10][0, 11].item() == 0
            assert fixed_features[10][0, 10].item() == 1
            save(output / "explicit-insertion-fixed-positions.json", {"requested_author_number": 11, "requested_insertion_code": "A", "native_fixed_positions": fixed, "native_chain_M_pos": fixed_features[10].numpy()})
        if name == "model-two":
            assert np.allclose(mpnn_back["coords_chain_A"]["CA_chain_A"][10], np.array(base_mpnn["coords_chain_A"]["CA_chain_A"][10]) + 100)
        fixes.append({"case": name, "length": len(mpnn_back["seq"]), "all_selected_atom_coordinates_preserved": True,
                      "mapping": f"explicit-{name}-mapping.json", "pdb": normalized_path.name,
                      "esm_native": esm_summary(esm_back), "mpnn_native": mpnn_back})
    scenario("11-explicit-selection-and-mapping", "一个小型显式准备操作修复四种交接歧义", ["明确模型/author 链/蛋白组分后，输出连续工具编号 PDB 和真实位置映射。", "编号跳跃、长链名、选择模型 2、插入码四种输入均回读为 56 位；所选全部原子坐标及来源位置均验证保留。", "用映射把固定 A11A 转成 ProteinMPNN fixed_positions 的第 12 位，原生 featurizer 确认只固定 A11A、未误固定 A11。"],
             "文件 + 具体选择参数 + 必要位置映射足够处理这些病例，无需公共 atom37 数据层。", repairs=fixes)

    manifest = [{"path": p.name, "kind": "archived RCSB source" if p.name.startswith("original") else "programmatically transformed challenge fixture"} for p in sorted(fixtures.iterdir())]
    save(output / "fixture-manifest.json", manifest)
    summary["scenario_count"] = len(summary["scenarios"])
    summary["limitations"] = ["只执行真实 parser、文件转换和 ProteinMPNN featurizer，没有调用生成模型。", "挑战结构仅用于暴露接口行为，插入码、altloc、模型平移和配体均为程序变换。", "小型显式转换仅针对已选择的蛋白单链；没有实现一般性的多组分格式转换器。", "原始结构完整保存；工具临时 PDB 是显式蛋白选择后的输入。"]
    save(output / "summary.json", summary)
    print(json.dumps({"scenarios_completed": len(summary["scenarios"]), "summary": str(output / "summary.json")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
