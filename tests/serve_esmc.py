"""Single ESMC SDK scenario for the application viewer test; no model runs."""
from types import SimpleNamespace
from unittest.mock import patch
import torch
import uvicorn
from protein_workbench_public.bootstrap import create_application

if __name__ == '__main__':
    with patch('esm.sdk.esmc_client') as sdk:
        sdk.return_value.logits.return_value = SimpleNamespace(
            logits=SimpleNamespace(sequence=torch.tensor([[99.] * 64, [1.25] * 64, [-2.5] * 64, [88.] * 64])),
            mean_embedding=torch.full((1, 1, 1152), 0.25),
        )
        uvicorn.run(create_application(load_example_results=False), host='127.0.0.1', port=8196)
