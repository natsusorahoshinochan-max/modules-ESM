"""Observe asynchronous runs through public status queries."""
from time import monotonic, sleep


def wait_run(app, run):
    deadline = monotonic() + 10
    while run['status'] == 'running' and monotonic() < deadline:
        sleep(.01)
        run = app.get_run(run['id'])
    assert run['status'] != 'running', run
    return run


def wait_response(client, response):
    if response.status_code != 200:
        return response
    deadline = monotonic() + 10
    while response.json()['status'] == 'running' and monotonic() < deadline:
        sleep(.01)
        response = client.get('/api/runs/' + response.json()['id'])
    assert response.json()['status'] != 'running', response.text
    return response
