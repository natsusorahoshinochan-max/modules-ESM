"""Serve the real application with controlled SDK outcomes for the continuation UI test."""
from unittest.mock import patch

import uvicorn

from test_esmfold2_continuation import ControlledBiohub
from protein_workbench_public.bootstrap import create_application


if __name__ == "__main__":
    with patch("esm.sdk.esmfold2_client", return_value=ControlledBiohub()):
        uvicorn.run(create_application(load_example_results=False), host="127.0.0.1", port=8191)
