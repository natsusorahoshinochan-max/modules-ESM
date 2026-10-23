"""Public operation/tool ownership and complete target handoff."""
from types import SimpleNamespace
import json
import pytest


def target_file(tmp_path, *, missing=True):
    from modules.structure_io.target import write_target
    rows = [
        {'residue': 'A', 'author_number': 42, 'insertion_code': 'B', 'atoms': {'N': [0.,0.,0.], 'CA': [1.,0.,0.], 'C': [2.,0.,0.], 'O': [3.,0.,0.]}},
        {'residue': 'C', 'author_number': 43, 'insertion_code': '', 'atoms': {} if missing else {'N': [4.,0.,0.], 'CA': [5.,0.,0.], 'C': [6.,0.,0.], 'O': [7.,0.,0.]}},
    ]
    (tmp_path / 'target.cif').write_bytes(write_target(rows))
    return rows


def test_scientific_operations_are_installed_separately_from_tools():
    from modules.generation import module
    from modules.esm3 import module as esm3
    from modules.proteinmpnn import module as mpnn
    assert not esm3().nodes and not mpnn().nodes
    assert {n.id for n in module().nodes} >= {'workbench.complete_sequence', 'workbench.joint_generation', 'workbench.design_backbone'}


def test_esm_adapter_encodes_selected_target_positions_without_serialized_atom_axis(tmp_path):
    import torch
    from modules.generation.contract import GenerateRequest
    from modules.esm3.adapters import protein_for
    target_file(tmp_path)
    request = GenerateRequest('sequence', {}, target_file='target.cif', conditions={'sequence': [{'position': 1, 'residue': 'A'}], 'coordinates': [{'position': 1, 'atoms': ['N','CA','C']}]})
    protein = protein_for(request, workdir=tmp_path)
    assert protein.sequence == 'A_'
    assert protein.coordinates.shape == (2,37,3)
    assert protein.coordinates[0,1].tolist() == [1.,0.,0.]
    assert torch.isnan(protein.coordinates[1]).all()
    assert torch.isnan(protein.coordinates[0,4]).all()


def test_mpnn_complete_target_rejects_inserted_unresolved_position_before_model(tmp_path, monkeypatch):
    from modules.proteinmpnn.contract import MPNNRequest
    from modules.proteinmpnn.adapters import create_local
    target_file(tmp_path)
    monkeypatch.setattr('modules.proteinmpnn.adapters.run_worker', lambda *a, **k: pytest.fail('Missing target position reached model'))
    with pytest.raises(ValueError, match='target position 2.*N'):
        create_local({})(MPNNRequest('target.cif', 'mmcif', complete_target=True), {}, SimpleNamespace(workdir=tmp_path, cancelled=False))


def test_sequence_output_coordinates_are_conditions_and_structure_output_has_adapter_file(tmp_path):
    import torch
    from esm.sdk.api import ESMProtein, GenerationConfig
    from modules.esm3.adapters import save_result
    runtime = SimpleNamespace(workdir=tmp_path)
    protein = ESMProtein(sequence='AC', coordinates=torch.ones(2,37,3))
    condition = save_result(protein, GenerationConfig(track='sequence'), {}, runtime)
    generated = save_result(protein, GenerationConfig(track='structure'), {}, runtime)
    assert condition.coordinate_role == 'input_conditions' and condition.structure_file is None
    assert generated.coordinate_role == 'generated_structure'
    assert (tmp_path / generated.structure_file).is_file()
    assert '_atom_site.' in (tmp_path / generated.structure_file).read_text()


def test_complete_target_fixed_conditions_and_original_native_controls_reach_mpnn(tmp_path, monkeypatch):
    from pathlib import Path
    from modules.proteinmpnn.contract import MPNNRequest
    from modules.proteinmpnn.adapters import create_local
    target_file(tmp_path, missing=False)
    seen = []
    def worker(command, **kwargs):
        payload = json.loads(Path(command[-1]).read_text())
        seen.append(payload)
        Path(payload['output']).write_text(json.dumps({'actual_seed': 17, 'samples': [{'chains': {'A': 'AC'}}]}))
    monkeypatch.setattr('modules.proteinmpnn.adapters.run_worker', worker)
    conditions = {'sequence': [{'position': 1, 'residue': 'A'}], 'coordinates': [{'position': pos, 'atoms': ['N', 'CA', 'C', 'O']} for pos in (1, 2)]}
    result = create_local({})(MPNNRequest('target.cif', 'mmcif', complete_target=True, conditions=conditions), {'seed': 17, 'sampling_temp': [.2], 'fixed_positions': {'A': [2]}}, SimpleNamespace(workdir=tmp_path, cancelled=False))
    assert seen[0]['parameters']['fixed_positions'] == {'A': [2, 1]}
    assert seen[0]['parameters']['sampling_temp'] == [.2]
    assert seen[0]['entry']['coords_chain_A']['CA_chain_A'] == [[1.,0.,0.], [5.,0.,0.]]
    assert result.positions == [
        {'chain': 'A', 'author_number': 42, 'insertion_code': 'B', 'tool_position': 1},
        {'chain': 'A', 'author_number': 43, 'insertion_code': '', 'tool_position': 2},
    ]
    conditions['coordinates'].pop()
    with pytest.raises(ValueError, match='full N/CA/C/O'):
        create_local({})(MPNNRequest('target.cif', 'mmcif', complete_target=True, conditions=conditions), {}, SimpleNamespace(workdir=tmp_path, cancelled=False))
    assert len(seen) == 1


def test_mpnn_target_preserves_source_author_chain_separately_from_label_chain(tmp_path):
    from modules.structure_io.target import write_target
    from modules.proteinmpnn.adapters import prepare_structure
    from modules.proteinmpnn.contract import MPNNRequest
    rows = target_file(tmp_path, missing=False)
    for row in rows:
        row['author_chain'] = 'Q'
    (tmp_path / 'target.cif').write_bytes(write_target(rows, chain='A'))
    entry, positions = prepare_structure(MPNNRequest('target.cif', 'mmcif', complete_target=True), tmp_path)
    assert entry['seq_chain_Q'] == 'AC'
    assert [(row['chain'], row['author_number'], row['insertion_code']) for row in positions] == [('Q', 42, 'B'), ('Q', 43, '')]
