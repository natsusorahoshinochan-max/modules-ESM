"""Incomplete author numbering keeps explicit polymer labels through sequence handoff."""
from types import SimpleNamespace
import json
import pytest

from modules.sequence_io.formats import read_sequences


def package(folder, document, *, format='workbench.sequence', files=None):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'manifest.json').write_text(json.dumps(document))
    for name, content in (files or {}).items():
        (folder / name).write_bytes(content)
    return SimpleNamespace(id=folder.name, format=format, entry='manifest.json', files=tuple(['manifest.json', *(files or {})]), open=lambda name:(folder/name).open('rb'))


def test_sequence_positions_accept_independent_label_and_author_correspondence(tmp_path):
    rows = [{'sequence_index':1,'chain':'X','author_number':12,'insertion_code':'A','label_position':{'chain':'A','position':1}},
            {'sequence_index':2,'label_position':{'chain':'A','position':2}},
            {'sequence_index':3}]
    source = package(tmp_path, {'objects':[{'id':'known-labels','sequence':'AGC','positions':rows}]})
    assert read_sequences(source)[0]['positions'] == rows
    from modules.esmc.formats import read_sequences as esmc_sequences
    from modules.solubility.formats import read_sequences as solubility_sequences
    for reader in (esmc_sequences, solubility_sequences):
        assert reader(source)[0]['positions'] == rows
    from modules.generation.sources import read_sources
    assert [row['source']['position'] for row in read_sources(source)[0]['positions']] == rows


@pytest.mark.parametrize('positions', [
    [{'sequence_index':1,'label_position':{'chain':'A','position':0}}],
    [{'sequence_index':1,'chain':'X','label_position':{'chain':'A','position':1}}],
    [{'sequence_index':1,'label_position':{'chain':'A','position':1}}, {'sequence_index':2,'label_position':{'chain':'A','position':1}}],
])
def test_supplied_correspondence_is_validated_without_inventing_missing_fields(tmp_path, positions):
    source = package(tmp_path, {'objects':[{'id':'invalid','sequence':'A'*len(positions),'positions':positions}]})
    with pytest.raises(ValueError):
        read_sequences(source)


def test_unobserved_source_residue_survives_both_sequence_conversions_and_reediting(tmp_path):
    from modules.structure_io.target import write_target
    from modules.sequence_edit import edit
    from modules.generation.sources import read_sources
    from modules.generation.sequence import sequence
    from modules.collection import extract_sequences, merge
    raw = write_target([
        {'residue':'A','author_number':12,'author_chain':'X','atoms':{'CA':[1,2,3]}},
        {'residue':'G','author_number':None,'author_chain':'X','atoms':{}},
        {'residue':'C','author_number':30,'author_chain':'X','atoms':{'CA':[7,8,9]}},
    ])
    original = package(tmp_path/'original', {'objects':[{'id':'structure','structure':{'file':'structure.cif','format':'mmcif'}}]},format='workbench.structure_set',files={'structure.cif':raw})
    def run(function, directory, inputs, parameters=None):
        directory.mkdir()
        result = function(SimpleNamespace(inputs=inputs,parameters=parameters or {}),SimpleNamespace(workdir=directory,cancelled=False))
        delivery = next(iter(result.outputs.values()))
        if isinstance(delivery,list): delivery=delivery[0]
        return SimpleNamespace(id=directory.name,format=delivery.format,entry=delivery.entry,files=tuple(delivery.files),open=lambda name:(directory/delivery.files[name]).open('rb'))
    edited = run(edit,tmp_path/'edit',{'source':[original]},{'selection':{'chains':['X']},'tracks':[]})
    positions = read_sources(edited)[0]['positions']
    generated = package(tmp_path/'generated', {'objects':[{'id':'generated','sequence':'AGC','positions':positions,'native':{'file':'native.json'}}]},format='workbench.esm3_generation',files={'native.json':json.dumps({'tracks':{'sequence':'AGC'},'metrics':{}}).encode()})
    converted = run(sequence,tmp_path/'converted',{'generated':[generated]})
    expected = [
        {'sequence_index':1,'chain':'X','author_number':12,'insertion_code':'','label_position':{'chain':'A','position':1}},
        {'sequence_index':2,'label_position':{'chain':'A','position':2}},
        {'sequence_index':3,'chain':'X','author_number':30,'insertion_code':'','label_position':{'chain':'A','position':3}},
    ]
    assert read_sequences(converted)[0]['positions'] == expected
    collected = run(merge,tmp_path/'merged',{'packages':[generated]})
    extracted = run(extract_sequences,tmp_path/'extracted',{'collection':[collected]})
    assert read_sequences(extracted)[0]['positions'] == expected
    reopened = run(edit,tmp_path/'reopened',{'source':[extracted]})
    with reopened.open(reopened.entry) as stream:
        document = json.load(stream)
    assert document['positions'][1]['source']['position'] == expected[1]
    second_source = read_sources(reopened)[0]
    second_generated = package(tmp_path/'generated-again',{'objects':[{'id':'again','sequence':'AGC','positions':second_source['positions'],'native':{'file':'native.json'}}]},format='workbench.esm3_generation',files={'native.json':json.dumps({'tracks':{'sequence':'AGC'},'metrics':{}}).encode()})
    assert read_sequences(run(sequence,tmp_path/'converted-again',{'generated':[second_generated]}))[0]['positions'] == expected


def test_independent_backbone_scoring_uses_explicit_reference_mapping_with_label_only_source(tmp_path):
    from modules.sequence_backbone_evaluation.formats import mapped_sequences
    original = {'id':'source','sequence':'AGC','positions':[
        {'sequence_index':1,'chain':'X','author_number':12,'insertion_code':''},
        {'sequence_index':2,'label_position':{'chain':'A','position':2}},
        {'sequence_index':3},
    ]}
    reference = [{'chain':'R','author_number':index+100,'insertion_code':''} for index in range(1,4)]
    bindings = [{'object':'source','reference_chain':'R','positions':[{'sequence_index':index,**row} for index,row in enumerate(reference,1)]}]
    assert mapped_sequences([original],reference,bindings) == ({'R':'AGC'},['source'])
