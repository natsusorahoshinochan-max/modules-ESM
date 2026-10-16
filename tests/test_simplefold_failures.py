"""Controlled official inference boundary; no SimpleFold model is loaded."""
from __future__ import annotations

from pathlib import Path
import unittest

import torch

from modules.folding.simplefold_runtime import ActivatedSimpleFoldFolding


class SimpleFoldInferenceFailures(unittest.TestCase):
    def invoke_failure(self, error: Exception):
        class ControlledInferenceWrapper:
            def run_inference(self, batch, model, plddt_model, device):
                raise error

        runtime = ActivatedSimpleFoldFolding(
            provider_directory=Path.cwd(), model_directory=Path.cwd(),
            output_directory=Path.cwd(), inference_wrapper=ControlledInferenceWrapper(),
            process_one_inference_structure=None, torch_device=torch.device('cpu'),
            torch_module=torch, effective_seed=12, num_samples=2,
            process_structure=None, to_pdb=None,
        )
        runtime.prepared_inputs = (({}, None, None),)
        runtime.folding_model = None
        runtime.plddt_models = {}
        return runtime.invoke()

    def test_typed_cuda_memory_failure_is_reported_as_a_failed_request(self):
        from modules.folding.simplefold_adapter import SimpleFoldProviderError
        error = torch.cuda.OutOfMemoryError('controlled CUDA allocation failure')
        with self.assertRaises(SimpleFoldProviderError) as raised:
            self.invoke_failure(error)
        self.assertIs(raised.exception.__cause__, error)

    def test_program_errors_are_not_reported_as_recoverable_provider_failures(self):
        for error in (ValueError('bad tensor shape'), RuntimeError('CUDA out of memory')):
            with self.subTest(error=error), self.assertRaises(type(error)) as raised:
                self.invoke_failure(error)
            self.assertIs(raised.exception, error)


if __name__ == '__main__':
    unittest.main()
