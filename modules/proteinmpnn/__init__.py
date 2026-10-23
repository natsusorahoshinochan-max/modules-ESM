"""ProteinMPNN tools: deployment settings and public adapter implementations."""
from protein_workbench_public.module_api import Module

def module():
    from .adapters import tools
    return Module('workbench.proteinmpnn', 'ProteinMPNN tools', tools=tools(), settings={'source': 'Existing ProteinMPNN source directory', 'weights': 'Existing weights root', 'python': 'Existing Python executable with torch, numpy and gemmi', 'device': 'cpu, cuda or mps'})
