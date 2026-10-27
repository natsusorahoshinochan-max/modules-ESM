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
        id='workbench.structure_comparison', name={'zh-CN': '结构比较', 'en': 'Structure comparison'},
        nodes=(Node(
            id='workbench.compare', name={'zh-CN': '比较结构', 'en': 'Compare structures'}, execute=execute,
            inputs={'subject': InputPort(('workbench.prediction', 'workbench.structure_set', 'workbench.coordinates'), cardinality='many', name={'zh-CN': '待比较结构', 'en': 'Subject structure'}), 'reference': InputPort(('workbench.reference', 'workbench.structure_set', 'workbench.prediction', 'workbench.coordinates'), name={'zh-CN': '参考结构', 'en': 'Reference structure'})},
            outputs={'comparison': OutputPort('workbench.comparison', cardinality='many', name={'zh-CN': '评分', 'en': 'Scores'})},
            parameters={'subject_selection': {'type': 'object', 'description': 'Optional chains or actual positions', 'title': {'zh-CN': '候选区域', 'en': 'Subject region'}}, 'reference_selection': {'type': 'object', 'description': 'Optional chains or actual positions', 'title': {'zh-CN': '参考区域', 'en': 'Reference region'}}},
        ),), ui=str(Path(__file__).with_name('ui.js').resolve()),
    )
