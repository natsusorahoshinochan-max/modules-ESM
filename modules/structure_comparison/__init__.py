"""Independent complete-structure comparison using public file packages."""
from pathlib import Path

from protein_workbench_public.module_api import InputPort, Module, Node, OutputPort

from .api import compare, read_comparison_input


def execute(call, runtime):
    if call.parameters:
        raise ValueError('Complete-structure comparison has no node parameters')
    return compare(read_comparison_input(call.inputs['subject'][0]), read_comparison_input(call.inputs['reference'][0]), runtime)


def module():
    return Module(
        id='workbench.structure_comparison', name='Structure comparison',
        nodes=(Node(
            id='workbench.compare', name='Compare complete protein structures', execute=execute,
            inputs={'subject': InputPort(('workbench.prediction', 'workbench.structure_set')), 'reference': InputPort(('workbench.reference', 'workbench.structure_set'))},
            outputs={'comparison': OutputPort('workbench.comparison')},
        ),), ui=str(Path(__file__).with_name('ui.js').resolve()),
    )
