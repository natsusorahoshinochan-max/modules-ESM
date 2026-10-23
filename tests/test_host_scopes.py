"""Native Map/Repeat execute real independent text packages through the host."""
from copy import deepcopy

import pytest

from core.host import HostError, Workbench
from protein_workbench_public.module_api import Delivery
from tests.fixtures import scope_module
from tests.test_host_scheduling import wait_run


def setup(tmp_path):
    app = Workbench(tmp_path)
    app.install('tests.fixtures.scope_module:module')
    project = app.create_project('Native scopes')['id']
    scope_module.observed.clear()
    scope_module.refuse_delivery.clear()
    return app, project


def package(app, project, value):
    workdir = app.new_workdir()
    (workdir / 'text').write_text(value)
    return app.create_input(project, Delivery('scope.text', 'text', {'text': 'text'}), workdir)['id']


def transform(identifier='edit', **parameters):
    return {'id': identifier, 'type': 'scope.transform', 'parameters': parameters}


def scope(kind, body, identifier='scope', **options):
    return {'id': identifier, 'type': 'host.' + kind, 'scope': {
        'inputs': {'items': {'accepts': ['scope.text'], 'cardinality': 'many', 'required': False},
                   'reference': {'accepts': ['scope.text'], 'cardinality': 'many', 'required': False}},
        'outputs': {'result': {'format': 'scope.text', 'cardinality': 'many'}},
        'body': {'nodes': [body], 'edges': []},
        'input_bindings': [{'input': 'items', 'node': body['id'], 'port': 'source' if body['type'] == 'scope.transform' else 'items'},
                           {'input': 'reference', 'node': body['id'], 'port': 'reference'}],
        'output_bindings': [{'output': 'result', 'node': body['id'], 'port': 'result'}],
        **({'item_input': 'items'} if kind == 'map' else {'rounds': 2, 'feedback': {'items': 'result'}}), **options}}


def run_flow(app, project, nodes):
    app.save_project(project, {'nodes': nodes, 'edges': []}, {})
    return wait_run(app, app.start(project))


def values(app, run, node='scope'):
    return [scope_module.text(app.package(key)) for key in run['nodes'][node]['outputs']['result']]


def test_two_rounds_map_dynamic_package_counts_and_fixed_reference(tmp_path):
    app, project = setup(tmp_path)
    loop = scope('repeat', scope('map', transform(copies=2), identifier='each'))
    loop['inputs'] = {'items': [package(app, project, 'red'), package(app, project, 'blue')],
                      'reference': [package(app, project, 'R')]}
    run = run_flow(app, project, [loop])
    assert run['status'] == 'succeeded', run
    assert values(app, run) == ['red!R!R'] * 4 + ['blue!R!R'] * 4
    assert len(scope_module.observed) == 6
    rounds = run['scopes']['scope']['iterations']
    assert len(rounds) == 2
    assert len(run['scopes'][rounds[0]['nodes']['each']]['iterations']) == 2
    assert len(run['scopes'][rounds[1]['nodes']['each']]['iterations']) == 4
    child = rounds[0]['nodes']['each']
    assert run['nodes'][child]['location'] == {'parent_scope': 'scope', 'node_id': 'each', 'round': 1}
    assert values(app, run, child) == ['red!R', 'red!R', 'blue!R', 'blue!R']


def test_empty_map_produces_empty_outputs_and_later_round_runs_no_tools(tmp_path):
    app, project = setup(tmp_path)
    loop = scope('repeat', scope('map', transform(copies=0), identifier='each'), rounds=3)
    loop['inputs'] = {'items': [package(app, project, 'red')]}
    run = run_flow(app, project, [loop])
    assert run['status'] == 'succeeded', run
    assert values(app, run) == []
    assert len(run['scopes']['scope']['iterations']) == 3
    assert len(scope_module.observed) == 1


def test_explicit_reference_feedback_changes_second_round_only(tmp_path):
    app, project = setup(tmp_path)
    loop = scope('repeat', scope('map', transform(), identifier='each'), feedback={'items': 'result', 'reference': 'result'})
    loop['inputs'] = {'items': [package(app, project, 'A')], 'reference': [package(app, project, 'R')]}
    run = run_flow(app, project, [loop])
    assert values(app, run) == ['A!R!A!R']
    assert [entry[1] for entry in scope_module.observed] == ['R', 'A!R']


def test_child_continuation_uses_old_flow_and_does_not_retry_other_failures(tmp_path):
    app, project = setup(tmp_path)
    loop = scope('repeat', scope('map', transform(fail='A'), identifier='each'))
    loop['inputs'] = {'items': [package(app, project, 'A'), package(app, project, 'B')]}
    isolated = transform('isolated', fail='C')
    isolated['inputs'] = {'source': [package(app, project, 'C')]}
    failed = run_flow(app, project, [loop, isolated])
    assert failed['status'] == 'failed'
    target = next(key for key, state in failed['nodes'].items() if state.get('location', {}).get('node_id') == 'edit' and state['status'] == 'failed')
    app.save_project(project, {'nodes': [], 'edges': []}, {})
    final = wait_run(app, app.continue_run(failed['id'], target))
    assert final['nodes']['scope']['status'] == 'succeeded', final
    assert values(app, final) == ['A!!', 'B!!']
    assert final['nodes']['isolated']['status'] == 'failed'
    assert [item[0] for item in scope_module.observed].count('B') == 1
    assert [item[0] for item in scope_module.observed].count('C') == 1
    assert final['calls'][target]['parameters'] == {'fail': 'A'}
    assert final['nodes'][target]['location'] == failed['nodes'][target]['location']
    with pytest.raises(HostError, match='unfinished continuation'):
        app.continue_run(final['id'], 'scope')


def test_delivery_failure_does_not_advance_round_and_retry_receives_no_uncommitted_progress(tmp_path):
    app, project = setup(tmp_path)
    scope_module.refuse_delivery.add('A')
    loop = scope('repeat', scope('map', transform(), identifier='each'))
    loop['inputs'] = {'items': [package(app, project, 'A')]}
    failed = run_flow(app, project, [loop])
    assert len(failed['scopes']['scope']['iterations']) == 1
    target = next(key for key, state in failed['nodes'].items() if state.get('kind') == 'node' and state['status'] == 'failed')
    assert failed['nodes'][target]['outputs'] == {}
    assert failed['nodes'][target]['continuation'] is None
    final = wait_run(app, app.continue_run(failed['id'], target))
    assert values(app, final) == ['A!!']
    assert scope_module.observed[1][3] is False


def test_cancel_child_then_continue_advances_the_existing_scope(tmp_path):
    app, project = setup(tmp_path)
    scope_module.entered.clear(); scope_module.release.clear()
    loop = scope('repeat', scope('map', transform(hold=True), identifier='each'))
    loop['inputs'] = {'items': [package(app, project, 'A')]}
    app.save_project(project, {'nodes': [loop], 'edges': []}, {})
    running = app.start(project)
    try:
        assert scope_module.entered.wait(1)
        app.cancel_run(running['id'])
    finally:
        scope_module.release.set()
    cancelled = wait_run(app, running)
    target = next(key for key, state in cancelled['nodes'].items() if state.get('kind') == 'node')
    assert cancelled['nodes'][target]['status'] == 'cancelled'
    resumed = wait_run(app, app.continue_run(cancelled['id'], target))
    assert resumed['status'] == 'succeeded', resumed
    assert values(app, resumed) == ['A!!']


def test_copy_nested_direct_inputs_and_detect_missing_inner_module(tmp_path):
    app, project = setup(tmp_path)
    edit = transform()
    edit['inputs'] = {'reference': [package(app, project, 'R')]}
    node = scope('map', edit)
    node['scope']['input_bindings'] = node['scope']['input_bindings'][:1]
    node['inputs'] = {'items': [package(app, project, 'A')]}
    run_flow(app, project, [node])
    copied = app.copy_project(project, 'Copy')
    assert copied['flow']['nodes'][0]['scope']['body']['nodes'][0]['inputs']['reference'] != edit['inputs']['reference']
    app.delete_project(project)
    assert values(app, wait_run(app, app.start(copied['id']))) == ['A!R']
    missing = deepcopy(copied['flow'])
    missing['nodes'][0]['scope']['body']['nodes'][0]['type'] = 'missing.nested'
    saved = app.save_project(copied['id'], missing, {})
    assert saved['missing_modules'] == ['missing.nested']
    failed = wait_run(app, app.start(copied['id']))
    assert failed['nodes']['scope']['status'] == 'configuration_blocked'


def test_scope_boundary_format_and_cycle_are_configuration_errors(tmp_path):
    app, project = setup(tmp_path)
    node = scope('map', transform())
    node['scope']['inputs']['items']['accepts'] = ['different.format']
    failed = run_flow(app, project, [node])
    assert failed['nodes']['scope']['status'] == 'configuration_blocked'
    assert 'format' in str(failed['nodes']['scope']['diagnostics']).lower()


@pytest.mark.parametrize('nested', [False, True])
def test_cancel_between_items_can_continue_scope_without_repeating_success(tmp_path, monkeypatch, nested):
    app, project = setup(tmp_path)
    node = scope('map', transform(), identifier='each' if nested else 'scope')
    if nested:
        node = scope('repeat', node, rounds=1)
    node['inputs'] = {'items': [package(app, project, 'A'), package(app, project, 'B')]}
    app.save_project(project, {'nodes': [node], 'edges': []}, {})
    put = app._put
    cancelled = False

    def after_first_item(kind, record):
        nonlocal cancelled
        result = put(kind, record)
        scopes = record.get('scopes', {}).values()
        completed_item = any(item.get('iterations') and 'outputs' in item['iterations'][0] for item in scopes)
        if kind == 'run' and not cancelled and completed_item:
            cancelled = True
            app.cancel_run(record['id'])
        return result

    monkeypatch.setattr(app, '_put', after_first_item)
    stopped = wait_run(app, app.start(project))
    assert stopped['nodes']['scope']['status'] == 'cancelled'
    assert len(stopped['scopes']['scope']['iterations']) == 1
    final = wait_run(app, app.continue_run(stopped['id'], 'scope'))
    assert final['status'] == 'succeeded'
    assert values(app, final) == ['A!', 'B!']
    assert [item[0] for item in scope_module.observed] == ['A', 'B']


def test_scope_failure_blocks_outer_successor_but_independent_group_runs(tmp_path):
    app, project = setup(tmp_path)
    node = scope('map', transform(fail='A'))
    node['inputs'] = {'items': [package(app, project, 'A')]}
    later = scope('map', transform(suffix='?'), identifier='later')
    independent = transform('isolated')
    independent['inputs'] = {'source': [package(app, project, 'B')]}
    flow = {'nodes': [node, later, independent], 'edges': [
        {'source': 'scope', 'source_port': 'result', 'target': 'later', 'target_port': 'items'}]}
    app.save_project(project, flow, {})
    failed = wait_run(app, app.start(project))
    assert failed['nodes']['later']['status'] == 'blocked'
    assert failed['nodes']['isolated']['status'] == 'succeeded'
    child = next(key for key, state in failed['nodes'].items() if state.get('kind') == 'node')
    final = wait_run(app, app.continue_run(failed['id'], child))
    assert final['status'] == 'succeeded'
    assert values(app, final, 'later') == ['A!?']
    assert [item[0] for item in scope_module.observed].count('B') == 1


def test_inner_cycle_blocks_connected_outer_group_before_any_call(tmp_path):
    app, project = setup(tmp_path)
    node = scope('map', transform())
    node['inputs'] = {'items': [package(app, project, 'A')]}
    node['scope']['body']['edges'] = [{'source': 'edit', 'source_port': 'result', 'target': 'edit', 'target_port': 'reference'}]
    independent = transform('isolated')
    independent['inputs'] = {'source': [package(app, project, 'B')]}
    failed = run_flow(app, project, [node, independent])
    assert failed['nodes']['scope']['status'] == 'configuration_blocked'
    assert 'cycle' in str(failed['nodes']['scope']['diagnostics'])
    assert failed['nodes']['isolated']['status'] == 'succeeded'
    assert [item[0] for item in scope_module.observed] == ['B']


def test_teaching_draft_copies_inner_input_before_releasing_temporary_package(tmp_path):
    app, _ = setup(tmp_path)
    tutorial = app.tutorial()
    workdir = app.new_workdir()
    (workdir / 'text').write_text('A')
    held = app.create_draft_input(tutorial['id'], Delivery('scope.text', 'text', {'text': 'text'}), workdir)
    edit = transform()
    edit['inputs'] = {'source': [held['id']]}
    node = scope('repeat', edit, rounds=1, feedback={})
    node['scope']['input_bindings'] = []
    copied = app.copy_project('tutorial', 'Own work', {'nodes': [node], 'edges': []}, {})
    app.discard_draft_input(held['id'])
    assert values(app, wait_run(app, app.start(copied['id']))) == ['A!']
    assert app.tutorial()['flow'] == tutorial['flow']


def test_module_cannot_replace_host_scope_node_type(tmp_path):
    app = Workbench(tmp_path)
    with pytest.raises(HostError, match='Duplicate node identity: host.map'):
        app.install('tests.fixtures.scope_module:reserved_module')


@pytest.mark.parametrize('remove', ['disable', 'uninstall'])
def test_continue_consumes_received_input_after_successful_source_removed(tmp_path, remove):
    app, project = setup(tmp_path)
    app.install('tests.fixtures.scope_module:source_module')
    flow = {'nodes': [{'id': 'source', 'type': 'scope.source'}, transform(fail='A')],
            'edges': [{'source': 'source', 'source_port': 'result', 'target': 'edit', 'target_port': 'source'}]}
    app.save_project(project, flow, {})
    failed = wait_run(app, app.start(project))
    fixed = failed['calls']['edit']['inputs']['source']
    if remove == 'disable':
        app.enable('scope.source', False)
    else:
        app.uninstall('scope.source')
    resumed = wait_run(app, app.continue_run(failed['id'], 'edit'))
    assert resumed['status'] == 'succeeded'
    assert values(app, resumed, 'edit') == ['A!']
    assert resumed['calls']['edit']['inputs']['source'] == fixed
    assert resumed['nodes']['source'] == failed['nodes']['source']


def test_nested_continuation_skips_removed_successful_source_but_reports_future_use(tmp_path):
    app, project = setup(tmp_path)
    app.install('tests.fixtures.scope_module:source_module')
    node = scope('repeat', transform(fail='A'), rounds=2, feedback={})
    node['scope']['input_bindings'] = []
    node['scope']['body']['nodes'].insert(0, {'id': 'source', 'type': 'scope.source'})
    node['scope']['body']['edges'] = [{'source': 'source', 'source_port': 'result', 'target': 'edit', 'target_port': 'source'}]
    failed = run_flow(app, project, [node])
    first = failed['scopes']['scope']['iterations'][0]['nodes']
    app.uninstall('scope.source')
    resumed = wait_run(app, app.continue_run(failed['id'], first['edit']))
    assert resumed['nodes'][first['edit']]['status'] == 'succeeded'
    assert resumed['nodes'][first['source']] == failed['nodes'][first['source']]
    second = resumed['scopes']['scope']['iterations'][1]['nodes']
    assert resumed['nodes'][second['source']]['status'] == 'failed'
    assert 'Missing module node: scope.source' in str(resumed['nodes'][second['source']]['diagnostics'])
    assert resumed['nodes'][second['edit']]['status'] == 'blocked'
    app.install('tests.fixtures.scope_module:source_module')
    after_source = wait_run(app, app.continue_run(resumed['id'], second['source']))
    assert after_source['nodes'][second['source']]['status'] == 'succeeded'
    # Each new scientific call still follows its own normal failure contract.
    assert after_source['nodes'][second['edit']]['status'] == 'failed'
    finished = wait_run(app, app.continue_run(after_source['id'], second['edit']))
    assert finished['status'] == 'succeeded'


def test_last_scope_round_continues_without_removed_successful_source(tmp_path):
    app, project = setup(tmp_path)
    app.install('tests.fixtures.scope_module:source_module')
    node = scope('repeat', transform(fail='A'), rounds=1, feedback={})
    node['scope']['input_bindings'] = []
    node['scope']['body']['nodes'].insert(0, {'id': 'source', 'type': 'scope.source'})
    node['scope']['body']['edges'] = [{'source': 'source', 'source_port': 'result', 'target': 'edit', 'target_port': 'source'}]
    failed = run_flow(app, project, [node])
    first = failed['scopes']['scope']['iterations'][0]['nodes']
    app.uninstall('scope.source')
    resumed = wait_run(app, app.continue_run(failed['id'], first['edit']))
    assert resumed['status'] == 'succeeded'
    assert values(app, resumed) == ['A!']
