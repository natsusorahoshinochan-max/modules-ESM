"""Current UI import contract: carry the selected sequence package unchanged."""
import io
import json
from types import SimpleNamespace

from modules.sequence_io import import_sequences, module


def test_sequence_import_retains_gaps_identity_and_position_correspondence(tmp_path):
    source = {'objects': [{'id': 'protein-a', 'label': 'A', 'sequence': 'AX_U',
        'source': {'name': 'input.fasta'},
        'positions': [{'sequence_index': i + 1, 'id': f'p{i}'} for i in range(4)]}]}
    package = SimpleNamespace(entry='manifest.json', open=lambda _: io.StringIO(json.dumps(source)))
    outcome = import_sequences(SimpleNamespace(parameters={}, inputs={'file': [package]}),
                               SimpleNamespace(cancelled=False, workdir=tmp_path))
    assert outcome.outputs['sequence'][0].format == 'workbench.sequence'
    assert json.loads((tmp_path / 'manifest.json').read_text()) == source
    node = next(node for node in module().nodes if node.id == 'workbench.import_sequence')
    assert node.inputs['file'].accepts == ('workbench.sequence',)
    assert node.outputs['sequence'].format == 'workbench.sequence'
