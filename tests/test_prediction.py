import json

from core.host import Workbench
from protein_workbench_public.module_api import Delivery


def test_public_tool_is_discovered_and_injected_without_node_enumerating_it(tmp_path):
    app = Workbench(tmp_path)
    app.install('modules.folding:module')
    app.install('tests.fixtures.prediction_tool:module')
    app.configure('lab.predictor', {'prefix': 'observed'})
    project = app.create_project('Prediction')
    work = app.new_workdir()
    (work / 'input.json').write_text(json.dumps({'objects': [{'id': 'input', 'sequence': 'ACD'}]}))
    package = app.create_input(project['id'], Delivery('workbench.sequence', 'input', {'input': 'input.json'}), work)
    app.save_project(project['id'], {'nodes': [{'id': 'predict', 'type': 'workbench.predict', 'inputs': {'sequence': [package['id']]}, 'tools': {'predictor': 'lab.external'}, 'tool_parameters': {'predictor': {'seed': 0}}}], 'edges': []}, {})
    catalog = app.catalog()
    assert any(tool['id'] == 'lab.external' for tool in catalog['tools'])
    result = app.start(project['id'])
    assert result['status'] == 'succeeded', result
    output = app.package(result['nodes']['predict']['outputs']['structure'][0])
    with output.open(output.entry) as stream:
        manifest = json.load(stream)
    assert manifest['objects'][0]['sequence'] == 'ACD'
    with output.open('structure.pdb') as stream:
        assert stream.read().decode() == 'observed seed=0 sequence=ACD'
    with output.open('confidence.json') as stream:
        assert json.load(stream)['plddt'] == [0.8, 0.9, 0.7]


def test_default_official_module_can_be_disabled_and_stays_disabled_on_reopen(tmp_path):
    from protein_workbench_public.bootstrap import create_application
    app = create_application(data_root=tmp_path).state.workbench
    assert any(item['id'] == 'workbench.prediction' and item['enabled'] for item in app.list_modules())
    for module in app.list_modules():
        app.enable(module['id'], False)
    reopened = create_application(data_root=tmp_path).state.workbench
    assert reopened.catalog()['nodes'] == []


def test_missing_selected_tool_stops_run_without_resetting_saved_selection(tmp_path):
    import pytest
    from core.host import HostError
    app = Workbench(tmp_path)
    app.install('modules.folding:module')
    project = app.create_project('Missing tool')
    flow = {'nodes': [{'id': 'predict', 'type': 'workbench.predict', 'tools': {'predictor': 'uninstalled.tool'}}], 'edges': []}
    app.save_project(project['id'], flow, {})
    with pytest.raises(HostError, match='uninstalled.tool'):
        app.start(project['id'])
    assert app.get_project(project['id'])['flow'] == flow
