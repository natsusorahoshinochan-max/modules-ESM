"""ESM3 tools: deployment settings and public adapter implementations."""
from protein_workbench_public.module_api import Module

def module():
    from .adapters import tools
    return Module('workbench.esm3', 'ESM3 tools', tools=tools(), settings={'token': {'type': 'string', 'title': 'Biohub credential', 'secret': True}, 'service_url': 'Biohub service URL', 'model_path': 'Existing esm3-sm-open-v1 snapshot directory', 'device': 'cpu, cuda or mps', 'python': 'Existing Python executable with pinned esm and torch'})
