"""Typed local inference failures at official calls; no models are loaded."""
from types import SimpleNamespace
from unittest.mock import Mock
import unittest
import torch
from modules.esm3.local_adapter import call_local_provider
from modules.esm3.adapter import ESM3ProviderError
from modules.folding.esmfold2_local import _LocalEngine
from modules.folding.esmfold2_remote import ESMFold2ProviderError


class LocalGenerationFailures(unittest.TestCase):
    def invoke(self, tool, error):
        if tool == 'esm3':
            return call_local_provider(SimpleNamespace(generate=Mock(side_effect=error)), None, None,
                                       'sequence', effective_seed=42, device='cpu')
        engine = _LocalEngine(None, SimpleNamespace(fold=Mock(side_effect=error)),
                              SimpleNamespace, SimpleNamespace)
        return engine.fold(sequence='A', parameters={}, effective_seed=42)

    def test_typed_oom_is_a_provider_failure(self):
        for tool, expected in [('esm3', ESM3ProviderError), ('fold', ESMFold2ProviderError)]:
            error = torch.cuda.OutOfMemoryError('controlled')
            with self.subTest(tool=tool), self.assertRaises(expected) as raised:
                self.invoke(tool, error)
            self.assertIs(raised.exception.__cause__, error)

    def test_program_errors_propagate_unchanged(self):
        for tool in ('esm3', 'fold'):
            for error in (RuntimeError('CUDA out of memory'), ValueError('shape')):
                with self.subTest(tool=tool, error=error), self.assertRaises(type(error)) as raised:
                    self.invoke(tool, error)
                self.assertIs(raised.exception, error)
