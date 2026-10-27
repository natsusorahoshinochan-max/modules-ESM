"""Scientific generation/design operations with independently installed tools."""
from pathlib import Path
from protein_workbench_public.module_api import InputPort, Module, Node, OutputPort, ToolSlot
from . import sequence, joint, backbone

def module():
    esm = {'esm3': ToolSlot('workbench.esm3.generate', 'Multitrack generation')}
    from modules.sequence_edit.tracks import TRACK_FORMATS, TRACK_NAMES
    source = {'source': InputPort(('workbench.sequence', 'workbench.protein'), required=False, name='整体输入'),
              **{name: InputPort((format,), required=False, name=TRACK_NAMES[name]) for name, format in TRACK_FORMATS.items()}}
    common = {'samples': {'type': 'integer', 'title': '候选数量', 'default': 1}}
    return Module('workbench.generation', '生成与设计', nodes=(
        Node('workbench.complete_sequence', '生成序列', sequence.execute,
             inputs=source, outputs={'generated': OutputPort(sequence.FORMAT, name='生成结果')}, parameters=common, tools=esm),
        Node('workbench.esm3_sequence', '提取生成序列', sequence.sequence,
             inputs={'generated': InputPort((sequence.FORMAT,), name='生成结果')}, outputs={'sequence': OutputPort('workbench.sequence', name='序列')},
             parameters={'chain_index': {'type': 'integer', 'title': '链索引（从 0 开始）', 'description': 'Explicit zero-based chain index; required for multiple chains'}}),
        Node('workbench.joint_generation', '生成序列与结构', joint.execute,
             inputs=source, outputs={'generated': OutputPort(joint.FORMAT, name='生成结果')}, parameters={**common,
                'structure_parameters': {'type': 'object', 'default': {}, 'description': 'Selected tool control overrides for structure phase'}}, tools=esm),
        Node('workbench.joint_to_esm3', '选择生成阶段', joint.convert_stage,
             inputs={'generated': InputPort((joint.FORMAT,), name='生成结果')}, outputs={'generated': OutputPort(sequence.FORMAT, name='生成结果')},
             parameters={'stage': {'type': 'string', 'title': '阶段', 'enum': ['sequence', 'structure'], 'enumLabels': {'sequence': '序列', 'structure': '三维坐标'}}}),
        Node('workbench.joint_structure', '提取生成结构', joint.convert_structure,
             inputs={'generated': InputPort((joint.FORMAT,), name='生成结果')}, outputs={'structures': OutputPort('workbench.structure_set', name='结构')},
             parameters={'chain': {'type': 'string', 'title': '链'}, 'start_number': {'type': 'integer', 'title': '起始编号'}}),
        Node('workbench.design_backbone', '骨架设计', backbone.execute,
             inputs={'structure': InputPort(('workbench.structure_set', 'workbench.prediction', 'workbench.protein'), name='结构')},
             outputs={'design': OutputPort('workbench.proteinmpnn_design', name='设计结果')}, tools={'mpnn': ToolSlot('workbench.proteinmpnn.call', 'Backbone design and scoring')}),
        Node('workbench.proteinmpnn_chain_sequence', '提取设计序列', backbone._chain_sequence,
             inputs={'design': InputPort(('workbench.proteinmpnn_design',), name='设计结果')}, outputs={'sequence': OutputPort('workbench.sequence', name='序列')},
             parameters={'chain': {'type': 'string', 'title': '链', 'description': 'Actual chain; omit only when every sample has the same single chain'}})),
        ui=str(Path(__file__).with_name('ui.js').resolve()))
