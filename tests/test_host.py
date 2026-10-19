from tests.run_helpers import wait_run
from core.host import Workbench


def test_host_without_modules_saves_and_reopens_incomplete_project(tmp_path):
    app = Workbench(tmp_path)
    assert app.catalog() == {"nodes": [], "modules": [], "tools": []}
    project = app.create_project("Research")
    flow = {"nodes": [{"id": "draft", "type": "absent.edit", "parameters": {"region": [12, 17]}}], "edges": [], "custom": {"prompt": "hello"}}
    layout = {"draft": {"x": 13, "y": 29}}
    app.save_project(project["id"], flow, layout)
    reopened = Workbench(tmp_path).get_project(project["id"])
    assert reopened["flow"] == flow
    assert reopened["layout"] == layout
    assert reopened["missing_modules"] == ["absent.edit"]


def test_external_declarations_and_settings_survive_reopening(tmp_path):
    app = Workbench(tmp_path)
    installed = app.install("tests.fixtures.host_module:module")
    app.configure(installed["id"], {"label": "configured"})
    reopened = Workbench(tmp_path)
    assert reopened.list_modules()[0]["settings"] == {"label": "configured"}
    catalog = reopened.catalog()
    assert [node["id"] for node in catalog["nodes"]] == ["independent.encode", "independent.receive"]
    assert catalog["nodes"][0]["inputs"] == {"source": {"accepts": ["independent.request"], "cardinality": "one", "required": True}}


def test_binary_input_is_saved_without_interpreting_its_scientific_content(tmp_path):
    from protein_workbench_public.module_api import Delivery
    app = Workbench(tmp_path)
    project = app.create_project("Binary")
    workdir = app.new_workdir()
    (workdir / "temporary-name").write_bytes(b"\x00not scientific JSON\xff")
    package = app.create_input(project["id"], Delivery("author.custom", "stable.bin", {"stable.bin": "temporary-name"}), workdir)
    assert package["files"] == ["stable.bin"]
    reopened = Workbench(tmp_path).package(package["id"])
    with reopened.open(reopened.entry) as stream:
        assert stream.read() == b"\x00not scientific JSON\xff"
    assert not workdir.exists()


def test_external_nodes_encode_then_independently_read_committed_package(tmp_path):
    from protein_workbench_public.module_api import Delivery
    app = Workbench(tmp_path)
    app.install("tests.fixtures.host_module:module")
    app.configure("independent", {"label": "!"})
    project = app.create_project("Pipeline")
    workdir = app.new_workdir()
    (workdir / "request").write_bytes(b"\x00hello")
    request = app.create_input(project["id"], Delivery("independent.request", "request", {"request": "request"}), workdir)
    app.save_project(project["id"], {"nodes": [{"id": "encode", "type": "independent.encode", "parameters": {"suffix": " world"}, "inputs": {"source": [request["id"]]}}, {"id": "receive", "type": "independent.receive"}], "edges": [{"source": "encode", "source_port": "result", "target": "receive", "target_port": "source"}]}, {})
    first = wait_run(app, app.start(project["id"]))
    second = wait_run(app, app.start(project["id"]))
    assert first["status"] == "succeeded"
    result_id = first["nodes"]["receive"]["outputs"]["result"][0]
    with Workbench(tmp_path).package(result_id).open("summary") as stream:
        assert stream.read() == b"received:\x00hello world!"
    assert first["nodes"]["encode"]["continuation"] == {"done": 1}
    assert first["id"] != second["id"]
    assert result_id != second["nodes"]["receive"]["outputs"]["result"][0]


def test_abandoned_upload_workdir_can_be_discarded(tmp_path):
    app = Workbench(tmp_path)
    workdir = app.new_workdir()
    (workdir / "unfinished").write_bytes(b"partial")
    app.discard_workdir(workdir)
    assert not workdir.exists()


def test_required_many_input_is_checked_after_upstream_returns_empty_batch(tmp_path):
    app = Workbench(tmp_path)
    app.install("tests.fixtures.host_module:empty_module")
    project = app.create_project("Empty batch")
    app.save_project(project["id"], {"nodes": [{"id": "source", "type": "empty.source"}, {"id": "receiver", "type": "empty.receive"}], "edges": [{"source": "source", "source_port": "result", "target": "receiver", "target_port": "source"}]}, {})
    run = wait_run(app, app.start(project["id"]))
    assert run["nodes"]["receiver"]["status"] == "failed"
    assert "Required input is missing: receiver.source" in run["nodes"]["receiver"]["diagnostics"][0]


def test_logical_file_key_is_opaque_and_never_used_as_filesystem_location(tmp_path):
    from protein_workbench_public.module_api import Delivery
    app = Workbench(tmp_path)
    project = app.create_project("Opaque key")
    workdir = app.new_workdir()
    (workdir / "actual").write_bytes(b"opaque")
    key = "logical/../binary ? #"
    result = app.create_input(project["id"], Delivery("custom", key, {key: "actual"}), workdir)
    with app.package(result["id"]).open(key) as stream:
        assert stream.read() == b"opaque"


def test_node_parameter_mutation_does_not_change_recorded_invocation(tmp_path):
    app = Workbench(tmp_path)
    app.install("tests.fixtures.host_module:mutating_module")
    app.configure("mutating", {"nested": {"value": "original setting"}})
    project = app.create_project("Fixed call")
    app.save_project(project["id"], {"nodes": [{"id": "mutate", "type": "mutating.node", "parameters": {"nested": {"value": "original parameter"}}}], "edges": []}, {})
    run = wait_run(app, app.start(project["id"]))
    assert run["flow"]["nodes"][0]["parameters"] == {"nested": {"value": "original parameter"}}
    assert app.get_project(project["id"])["flow"]["nodes"][0]["parameters"] == {"nested": {"value": "original parameter"}}
    assert app.list_modules()[0]["settings"] == {"nested": {"value": "original setting"}}


def test_malformed_saved_flow_has_a_concrete_start_error(tmp_path):
    import pytest
    from core.host import HostError
    app = Workbench(tmp_path)
    project = app.create_project("Unfinished document")
    app.save_project(project["id"], "unfinished", {})
    with pytest.raises(HostError, match="Flow must be an object"):
        wait_run(app, app.start(project["id"]))


def test_invalid_unicode_catalog_declaration_is_rejected_before_registration(tmp_path):
    import pytest
    from core.host import HostError
    app = Workbench(tmp_path)
    with pytest.raises(HostError, match='UTF-8'):
        app.install('tests.fixtures.host_module:invalid_catalog_module')
    assert Workbench(tmp_path).catalog() == {'nodes': [], 'modules': [], 'tools': []}
def test_http_continue_provides_accepted_outputs_without_private_continuation(tmp_path):
    from fastapi.testclient import TestClient
    from protein_workbench_public.bootstrap import create_application
    from tests.run_helpers import wait_response
    with TestClient(create_application(data_root=tmp_path)) as client:
        assert client.post('/api/modules', json={'entry_point': 'tests.fixtures.host_module:output_only_module'}).status_code == 200
        project = client.post('/api/projects', json={'name': 'Output-only continuation'}).json()['id']
        assert client.put('/api/projects/' + project, json={'flow': {'nodes': [{'id': 'node', 'type': 'output.node'}], 'edges': []}, 'layout': {}}).status_code == 200
        first = wait_response(client, client.post('/api/projects/' + project + '/runs')).json()
        assert first['status'] == 'failed'
        assert first['nodes']['node']['continuation'] is None
        prior = first['nodes']['node']['outputs']['result'][0]
        assert client.get('/api/packages/' + prior + '/file', params={'key': 'data'}).content == b'accepted partial'
        final = wait_response(client, client.post('/api/runs/' + first['id'] + '/nodes/node/continue')).json()
        assert final['id'] == first['id']
        assert final['status'] == 'succeeded'
        output = final['nodes']['node']['outputs']['result'][0]
        assert client.get('/api/packages/' + output + '/file', params={'key': 'data'}).content == b'accepted partial + completed'
