"""Independent complete-structure comparison using public file packages."""
from pathlib import Path

from protein_workbench_public.module_api import InputPort, Module, Node, Outcome, OutputPort

from .api import compare, comparison_parameters, read_comparison_input, read_comparison_inputs


def execute(call, runtime):
    parameters = comparison_parameters(call.parameters)
    reference = read_comparison_input(call.inputs['reference'][0])
    outputs = []
    for package in call.inputs.get('subject', ()):
        for subject in read_comparison_inputs(package):
            result = compare(subject, reference, runtime, **parameters)
            if result.status != 'succeeded':
                return Outcome(status=result.status, outputs={'comparison': outputs}, diagnostics=result.diagnostics)
            outputs.extend(result.outputs['comparison'])
    return Outcome(outputs={'comparison': outputs})


def module():
    return Module(
        id='workbench.structure_comparison', name='Structure comparison',
        nodes=(Node(
            id='workbench.compare', name='Compare protein structures and regions', execute=execute,
            inputs={'subject': InputPort(('workbench.prediction', 'workbench.structure_set', 'workbench.coordinates'), cardinality='many'), 'reference': InputPort(('workbench.reference', 'workbench.structure_set', 'workbench.prediction', 'workbench.coordinates'))},
            outputs={'comparison': OutputPort('workbench.comparison', cardinality='many')},
            parameters={'subject_selection': {'type': 'object', 'description': 'Optional chains or actual positions'}, 'reference_selection': {'type': 'object', 'description': 'Optional chains or actual positions'}},
        ),), ui=str(Path(__file__).with_name('ui.js').resolve()),
    )
