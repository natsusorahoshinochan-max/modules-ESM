"""THROWAWAY: real ESM3 structures and selected-result feedback, local resources only."""
from __future__ import annotations

import argparse
import gc
import json
import os
from pathlib import Path
import sys
import threading
import time

HERE = Path(__file__).resolve().parent
MODULES = HERE.parents[1]


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def monitor(output):
    import psutil
    began = time.monotonic()
    low = 0
    while True:
        available = psutil.virtual_memory().available
        low = low + 1 if available < 384 * 1024**2 else 0
        if low >= 3 or time.monotonic() - began > 600:
            write(output / "resource-stop.json", {"available_bytes": available, "elapsed": time.monotonic() - began})
            os._exit(75)
        time.sleep(1)


def load_float32_mapped(model, path):
    """Tool-private loading: same saved parameters, bounded anonymous scratch conversion."""
    import numpy as np
    import tempfile
    import torch
    state = torch.load(path, map_location="cpu", mmap=True, weights_only=True)
    descriptor, scratch = tempfile.mkstemp(prefix="PROTOTYPE-feedback-fp32-", dir="/private/tmp")
    os.close(descriptor)
    mapped = np.memmap(scratch, dtype=np.float32, mode="w+", shape=(sum(t.numel() for t in state.values()),))
    os.unlink(scratch)
    converted, offset = {}, 0
    for key, tensor in state.items():
        end = offset + tensor.numel()
        mapped[offset:end] = tensor.float().reshape(-1).numpy()
        converted[key] = torch.from_numpy(mapped[offset:end].reshape(tuple(tensor.shape)))
        mapped.flush()
        offset = end
    model.load_state_dict(converted, assign=True, strict=True)
    return model.eval()


def model():
    from accelerate import init_empty_weights
    from esm.models.esm3 import ESM3
    from esm.pretrained import ESM3_structure_encoder_v0, ESM3_structure_decoder_v0, ESM3_function_decoder_v0
    from esm.tokenization import get_esm3_model_tokenizers
    from esm.utils.constants.models import ESM3_OPEN_SMALL
    with init_empty_weights():
        value = ESM3(d_model=1536, n_heads=24, v_heads=256, n_layers=48,
                     structure_encoder_fn=ESM3_structure_encoder_v0,
                     structure_decoder_fn=ESM3_structure_decoder_v0,
                     function_decoder_fn=ESM3_function_decoder_v0,
                     tokenizers=get_esm3_model_tokenizers(ESM3_OPEN_SMALL))
    return load_float32_mapped(value, "data/weights/esm3_sm_open_v1.pth")


def structures(output, round2=False):
    import numpy as np
    import torch
    import gemmi
    from accelerate import init_empty_weights
    from esm.models.vqvae import StructureTokenDecoder
    from esm.sdk.api import ESMProtein, ESMProteinError, GenerationConfig
    from esm.utils.decoding import decode_structure
    from esm.utils.structure.protein_chain import ProteinChain
    cases = ["all_coords_default_true", "sparse_coords_default_true"]
    folder = output / ("round2-candidates" if round2 else "candidates")
    folder.mkdir(exist_ok=True)
    if round2:
        sequence_results = json.loads((output / "feedback/result.json").read_text())["outputs"]
    candidates, arrays = [], {}
    generator = model()
    structure_tokenizer = generator.tokenizers.structure
    for index, name in enumerate(cases, 1):
        prior_path = MODULES / "esm3/prototype_file_input/evidence" / f"{name}.json"
        prior = sequence_results[index - 1] if round2 else json.loads(prior_path.read_text())
        seed = (180 if round2 else 80) + index
        started = time.monotonic()
        torch.manual_seed(seed)
        with torch.inference_mode():
            encoded = generator.encode(ESMProtein(sequence=prior["sequence"]))
            result = generator.generate(encoded, GenerationConfig(track="structure", num_steps=4, temperature=0.5, temperature_annealing=False))
        if isinstance(result, ESMProteinError):
            raise ValueError(result.error_msg)
        assert not (result.structure[1:-1] == structure_tokenizer.mask_token_id).any()
        assert torch.equal(result.sequence, encoded.sequence)
        arrays[f"candidate_{index}_structure_tokens"] = result.structure.numpy()
        candidates.append({"object_id": f"feedback-round2-candidate-{index}" if round2 else f"feedback-candidate-{index}", "label": f"第2轮序列 {index} 的 ESM3 生成结构" if round2 else f"历史序列 {index} 的 ESM3 生成结构",
                           "sequence": prior["sequence"], "structure_file": f"candidate-{index}.pdb",
                           "sequence_file": f"candidate-{index}.fasta", "method": "ESM3 sequence-conditioned structure generation",
                           "source_sequence_evidence": "modules/sequence_edit/prototype_result_feedback/evidence/feedback/result.json" if round2 else f"modules/esm3/prototype_file_input/evidence/{name}.json",
                           "parameters": {"model": "esm3_sm_open_v1", "track": "structure", "num_steps": 4, "temperature": 0.5,
                                          "temperature_annealing": False, "seed": seed, "device": "cpu", "dtype": "float32"},
                           "sampling_seconds": time.monotonic() - started})
        print("Structure tokens generated", index, round(candidates[-1]["sampling_seconds"], 2), flush=True)
    del generator, encoded, result
    gc.collect()
    with init_empty_weights():
        decoder = StructureTokenDecoder(d_model=1280, n_heads=20, n_layers=30)
    decoder = load_float32_mapped(decoder, "data/weights/esm3_structure_decoder_v0.pth")
    for index, item in enumerate(candidates, 1):
        with torch.inference_mode():
            coords, plddt, ptm, pae = decode_structure(torch.tensor(arrays[f"candidate_{index}_structure_tokens"]), decoder, structure_tokenizer, item["sequence"])
        assert coords.shape[0] == len(item["sequence"]) == (59 if round2 else 58)
        assert torch.isfinite(coords[:, :3]).all()
        chain = ProteinChain.from_atom37(coords, sequence=item["sequence"], chain_id="A")
        chain.to_pdb(folder / item["structure_file"])
        (folder / item["sequence_file"]).write_text(f">{item['object_id']}\n{item['sequence']}\n")
        parsed = gemmi.read_structure(str(folder / item["structure_file"]))
        assert len(parsed[0]["A"]) == len(item["sequence"])
        item["confidence"] = {"method": "ESM3 structure decoder; natural output of generation", "plddt": plddt.tolist(), "ptm": float(ptm)}
        arrays[f"candidate_{index}_decoded_coordinates"] = coords.numpy()
        print("Structure file ready", item["structure_file"], flush=True)
    prefix = "round2-" if round2 else ""
    np.savez_compressed(output / f"{prefix}structure-native-output.npz", **arrays)
    write(folder / "manifest.json", {"objects": candidates, "scope": "New ESM3 sequence-conditioned structure generation from explicit sequence results. This is not independent folding validation."})
    write(output / f"{prefix}structures-summary.json", {"status": "passed", "actual_calls": 2, "generated_lengths": [len(item["sequence"]) for item in candidates], "all_backbone_positions_present": True,
          "sequence_inputs": "this run's second-round sequences" if round2 else "reused prior real sequences", "new_structure_coordinates": True, "method": "ESM3 generation and native learned structure decoder", "independent_prediction": False})


def feedback(output):
    import numpy as np
    import torch
    from esm.sdk.api import ESMProtein, ESMProteinError, GenerationConfig
    from esm.utils import residue_constants
    import gemmi
    request = json.loads((output / "feedback/request.json").read_text())
    block = gemmi.cif.read_file(str(output / "feedback" / request["structure_file"])).sole_block()
    positions = list(block.find("_entity_poly_seq.", ["num", "mon_id"]))
    prompt = ["_"] * len(positions)
    for item in request["sequence_conditions"]:
        prompt[item["target_index"]] = item["amino_acid"]
    coordinates = np.full((len(positions), 37, 3), np.nan, dtype=np.float32)
    atoms = {(int(row[0]) - 1, row[1]): [float(row[i]) for i in (2, 3, 4)] for row in block.find("_atom_site.", ["label_seq_id", "label_atom_id", "Cartn_x", "Cartn_y", "Cartn_z"])}
    for item in request["coordinate_conditions"]:
        for atom in item["atoms"]:
            coordinates[item["target_index"], residue_constants.atom_order[atom]] = atoms[item["target_index"], atom]
    generator = model()
    with torch.inference_mode():
        encoded = generator.encode(ESMProtein(sequence="".join(prompt), coordinates=torch.tensor(coordinates)))
    reports = []
    for seed in [101, 102]:
        torch.manual_seed(seed)
        began = time.monotonic()
        with torch.inference_mode():
            result = generator.generate(encoded, GenerationConfig(track="sequence", num_steps=1, temperature=0.5, temperature_annealing=False, condition_on_coordinates_only=True))
        if isinstance(result, ESMProteinError):
            raise ValueError(result.error_msg)
        sequence = generator.tokenizers.sequence.decode(result.sequence[1:-1].tolist()).replace(" ", "")
        assert len(sequence) == len(positions) and sequence[:5] == "MTYKL" and "_" not in sequence
        assert torch.allclose(result.coordinates, encoded.coordinates, equal_nan=True)
        reports.append({"seed": seed, "sequence": sequence, "length": len(sequence), "seconds": time.monotonic() - began,
                        "output": "new sequence; returned coordinate track remains input condition"})
        print("Round two sequence", seed, sequence, flush=True)
    # A separate sequence-only template uses the same editing logic and no coordinates.
    seq_request = json.loads((output / "sequence-only/request.json").read_text())
    seq_value = json.loads((output / "sequence-only/target.json").read_text())
    seq_prompt = ["_"] * len(seq_value["positions"])
    for item in seq_request["sequence_conditions"]:
        seq_prompt[item["target_index"]] = item["amino_acid"]
    with torch.inference_mode():
        only = generator.encode(ESMProtein(sequence="".join(seq_prompt)))
    assert only.coordinates is None and only.structure is None and len(only.sequence) == len(seq_prompt) + 2
    np.savez_compressed(output / "feedback/native-input.npz", coordinates=coordinates, sequence_tokens=encoded.sequence.numpy(),
                        sequence_only_tokens=only.sequence.numpy())
    write(output / "feedback/result.json", {"status": "passed", "actual_generation_calls": 2, "model": "esm3_sm_open_v1", "method": "native ESM3 sequence generation",
         "selected_object_id": request["selected_object_id"], "target_length": len(positions), "native_prompt": "".join(prompt),
         "coordinate_target_positions_one_based": [item["target_index"] + 1 for item in request["coordinate_conditions"]],
         "fixed_sequence_conditions_preserved": True, "input_coordinates_not_claimed_as_generated_structure": True,
         "parameters": {"num_steps": 1, "temperature": 0.5, "condition_on_coordinates_only": True, "temperature_annealing": False, "device": "cpu", "dtype": "float32"},
         "outputs": reports, "sequence_only": {"encoded": True, "target_length": len(seq_prompt), "coordinates": None, "structure_tokens": None,
         "native_prompt": "".join(seq_prompt), "scope": "actual native encode, no second sequence-only sampling"}})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["structures", "feedback", "round2-structures"])
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=HERE / "evidence")
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    source, output = args.source_root.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "candidates").mkdir(exist_ok=True)
    sys.path.insert(0, str(source / "repositories/esm"))
    sys.path.insert(0, str(source))
    if not args.worker:
        from protein_workbench_public.worker_process import run_worker
        run_worker([sys.executable, str(Path(__file__).resolve()), args.phase, "--source-root", str(source), "--output", str(output), "--worker"],
                   cwd=source, log_path=output / f"{args.phase}-worker.log", cancelled=lambda: False, label="ESM3 result-feedback prototype")
        return
    os.environ.update(INFRA_PROVIDER="prototype-local-assets", HF_HUB_OFFLINE="1", DISABLE_ITERATIVE_SAMPLING_TQDM="1")
    os.chdir(source / ".models/esm3")
    import torch
    torch.set_num_threads(2)
    threading.Thread(target=monitor, args=(output,), daemon=True).start()
    try:
        if args.phase == "feedback":
            feedback(output)
        else:
            structures(output, round2=args.phase == "round2-structures")
    except Exception as error:
        write(output / f"{args.phase}-failure.json", {"type": type(error).__name__, "message": str(error)})
        raise


if __name__ == "__main__":
    main()
