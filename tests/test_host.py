from core.host import Workbench


def test_host_without_modules_saves_and_reopens_incomplete_project(tmp_path):
    app = Workbench(tmp_path)
    assert app.catalog() == {"nodes": [], "modules": []}
    project = app.create_project("Research")
    flow = {"nodes": [{"id": "draft", "type": "absent.edit", "parameters": {"region": [12, 17]}}], "edges": [], "custom": {"prompt": "hello"}}
    layout = {"draft": {"x": 13, "y": 29}}
    app.save_project(project["id"], flow, layout)
    reopened = Workbench(tmp_path).get_project(project["id"])
    assert reopened["flow"] == flow
    assert reopened["layout"] == layout
    assert reopened["missing_modules"] == ["absent.edit"]
