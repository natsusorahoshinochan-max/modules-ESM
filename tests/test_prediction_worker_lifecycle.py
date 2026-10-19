"""Observe cleanup through each public local prediction runner without a model."""
import socket
import sys
import time

import pytest

from modules.folding.adapters import create_local
from modules.folding.contract import PredictionRequest
from modules.simplefold import create


@pytest.mark.parametrize('factory', [create_local, create], ids=['esmfold2', 'simplefold'])
def test_cancelled_prediction_releases_descendant_resources(tmp_path, factory):
    # A deployment executable stands in for the external computational environment.
    # It starts a stubborn descendant owning a socket, without importing a model.
    ready = tmp_path / 'ready'
    executable = tmp_path / 'python'
    service = (
        'import os, signal, socket, time; from pathlib import Path; '
        'signal.signal(signal.SIGTERM, signal.SIG_IGN); '
        "s = socket.socket(); s.bind(('127.0.0.1', 0)); s.listen(); "
        f'Path({str(ready)!r}).write_text(str(s.getsockname()[1])); '
        'time.sleep(30)'
    )
    executable.write_text(
        f'#!{sys.executable}\nimport subprocess, sys, time\n'
        f'subprocess.Popen([sys.executable, "-c", {service!r}])\n'
        'time.sleep(30)\n'
    )
    executable.chmod(0o755)
    for name in ('simplefold_100M.ckpt', 'esm2.pt', 'esm2-contact-regression.pt', 'ccd.pkl'):
        (tmp_path / name).touch()
    deadline = time.monotonic() + 10
    class Runtime:
        workdir = tmp_path
        @property
        def cancelled(self):
            if time.monotonic() > deadline:
                raise TimeoutError('Lightweight worker never reported ready')
            return ready.exists()
    settings = {
        'python': str(executable), 'model_path': str(tmp_path),
        'language_model_path': str(tmp_path), 'esm2_source': str(tmp_path),
        'esm2_checkpoint': str(tmp_path / 'esm2.pt'), 'ccd_path': str(tmp_path / 'ccd.pkl'),
    }
    with pytest.raises(ValueError, match='cancelled'):
        factory(settings)(PredictionRequest('A', 'source'), {}, Runtime())
    with socket.socket() as returned_resource:
        returned_resource.bind(('127.0.0.1', int(ready.read_text())))
