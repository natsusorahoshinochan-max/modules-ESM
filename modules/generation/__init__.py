"""Scientific generation/design operations with independently installed tools."""
from pathlib import Path
from protein_workbench_public.module_api import InputPort, Module, Node, OutputPort, ToolSlot
from . import sequence, joint, backbone

def module():
    esm = {'esm3': ToolSlot('workbench.esm3.generate', 'Multitrack generation')}
    from modules.sequence_edit.tracks import TRACK_FORMATS, TRACK_NAMES
    source = {'source': InputPort(('workbench.sequence', 'workbench.protein'), required=False, name='整体输入'),
              **{name: InputPort((format,), required=False, name=TRACK_NAMES[name]) for name, format in TRACK_FORMATS.items()}}
    common = {'samples': {'type': 'integer', 'default': 1}}
    return Module('workbench.generation', 'Generation and design', nodes=(
        Node('workbench.complete_sequence', 'Complete or generate a conditioned sequence', sequence.execute,
             inputs=source, outputs={'generated': OutputPort(sequence.FORMAT)}, parameters=common, tools=esm),
        Node('workbench.esm3_sequence', 'Use a generated chain as sequence', sequence.sequence,
             inputs={'generated': InputPort((sequence.FORMAT,))}, outputs={'sequence': OutputPort('workbench.sequence')},
             parameters={'chain_index': {'description': 'Explicit zero-based chain index; required for multiple chains'}}),
        Node('workbench.joint_generation', 'Generate sequence then structure', joint.execute,
             inputs=source, outputs={'generated': OutputPort(joint.FORMAT)}, parameters={**common,
                'structure_parameters': {'type': 'object', 'default': {}, 'description': 'Selected tool control overrides for structure phase'}}, tools=esm),
        Node('workbench.joint_to_esm3', 'Select a joint generation phase', joint.convert_stage,
             inputs={'generated': InputPort((joint.FORMAT,))}, outputs={'generated': OutputPort(sequence.FORMAT)},
             parameters={'stage': {'type': 'string', 'enum': ['sequence', 'structure']}}),
        Node('workbench.joint_structure', 'Use generated structure coordinates', joint.convert_structure,
             inputs={'generated': InputPort((joint.FORMAT,))}, outputs={'structures': OutputPort('workbench.structure_set')},
             parameters={'chain': {'type': 'string'}, 'start_number': {'type': 'integer'}}),
        Node('workbench.design_backbone', 'Design sequences from backbone', backbone.execute,
             inputs={'structure': InputPort(('workbench.structure_set', 'workbench.prediction', 'workbench.protein'))},
             outputs={'design': OutputPort('workbench.proteinmpnn_design')}, tools={'mpnn': ToolSlot('workbench.proteinmpnn.call', 'Backbone design and scoring')}),
        Node('workbench.proteinmpnn_chain_sequence', 'Use one design chain as sequence', backbone._chain_sequence,
             inputs={'design': InputPort(('workbench.proteinmpnn_design',))}, outputs={'sequence': OutputPort('workbench.sequence')},
             parameters={'chain': {'description': 'Actual chain; omit only when every sample has the same single chain'}})),
        ui=str(Path(__file__).with_name('ui.js').resolve()))
