"""Scientific generation/design operations with independently installed tools."""
from pathlib import Path
from protein_workbench_public.module_api import InputPort, Module, Node, OutputPort, ToolSlot
from . import sequence, joint, backbone

def module():
    esm = {'esm3': ToolSlot('workbench.esm3.generate', {'zh-CN': '多轨生成', 'en': 'Multitrack generation'})}
    from modules.sequence_edit.tracks import TRACK_FORMATS, TRACK_NAMES
    source = {'source': InputPort(('workbench.sequence', 'workbench.protein'), required=False, name={'zh-CN': '整体输入', 'en': 'Protein input'}),
              **{name: InputPort((format,), required=False, name=TRACK_NAMES[name]) for name, format in TRACK_FORMATS.items()}}
    common = {'samples': {'type': 'integer', 'title': {'zh-CN': '候选数量', 'en': 'Samples'}, 'default': 1}}
    return Module('workbench.generation', {'zh-CN': '生成与设计', 'en': 'Generation and design'}, nodes=(
        Node('workbench.complete_sequence', {'zh-CN': '生成序列', 'en': 'Generate sequence'}, sequence.execute,
             inputs=source, outputs={'generated': OutputPort(sequence.FORMAT, name={'zh-CN': '生成结果', 'en': 'Generated results'})}, parameters=common, tools=esm),
        Node('workbench.esm3_sequence', {'zh-CN': '提取生成序列', 'en': 'Extract generated sequences'}, sequence.sequence,
             inputs={'generated': InputPort((sequence.FORMAT,), name={'zh-CN': '生成结果', 'en': 'Generated results'})}, outputs={'sequence': OutputPort('workbench.sequence', name={'zh-CN': '序列', 'en': 'Sequence'})},
             parameters={'chain_index': {'type': 'integer', 'title': {'zh-CN': '链索引（从 0 开始）', 'en': 'Chain index (zero-based)'}, 'description': 'Explicit zero-based chain index; required for multiple chains'}}),
        Node('workbench.joint_generation', {'zh-CN': '生成序列与结构', 'en': 'Generate sequence and structure'}, joint.execute,
             inputs=source, outputs={'generated': OutputPort(joint.FORMAT, name={'zh-CN': '生成结果', 'en': 'Generated results'})}, parameters={**common,
                'structure_parameters': {'type': 'object', 'default': {}, 'description': 'Selected tool control overrides for structure phase', 'title': {'zh-CN': '结构生成参数', 'en': 'Structure parameters'}}}, tools=esm),
        Node('workbench.joint_to_esm3', {'zh-CN': '选择生成阶段', 'en': 'Select generation stage'}, joint.convert_stage,
             inputs={'generated': InputPort((joint.FORMAT,), name={'zh-CN': '生成结果', 'en': 'Generated results'})}, outputs={'generated': OutputPort(sequence.FORMAT, name={'zh-CN': '生成结果', 'en': 'Generated results'})},
             parameters={'stage': {'type': 'string', 'title': {'zh-CN': '阶段', 'en': 'Stage'}, 'enum': ['sequence', 'structure'], 'enumLabels': {'sequence': {'zh-CN': '序列', 'en': 'Sequence'}, 'structure': {'zh-CN': '三维坐标', 'en': '3D coordinates'}}}}),
        Node('workbench.joint_structure', {'zh-CN': '提取生成结构', 'en': 'Extract generated structures'}, joint.convert_structure,
             inputs={'generated': InputPort((joint.FORMAT,), name={'zh-CN': '生成结果', 'en': 'Generated results'})}, outputs={'structures': OutputPort('workbench.structure_set', name={'zh-CN': '结构', 'en': 'Structure'})},
             parameters={'chain': {'type': 'string', 'title': {'zh-CN': '链', 'en': 'Chain'}}, 'start_number': {'type': 'integer', 'title': {'zh-CN': '起始编号', 'en': 'Start number'}}}),
        Node('workbench.design_backbone', {'zh-CN': '骨架设计', 'en': 'Backbone design'}, backbone.execute,
             inputs={'structure': InputPort(('workbench.structure_set', 'workbench.prediction', 'workbench.protein'), name={'zh-CN': '结构', 'en': 'Structure'})},
             outputs={'design': OutputPort('workbench.proteinmpnn_design', name={'zh-CN': '设计结果', 'en': 'Design results'})}, tools={'mpnn': ToolSlot('workbench.proteinmpnn.call', {'zh-CN': '骨架设计与评分', 'en': 'Backbone design and scoring'})}),
        Node('workbench.proteinmpnn_chain_sequence', {'zh-CN': '提取设计序列', 'en': 'Extract designed sequences'}, backbone._chain_sequence,
             inputs={'design': InputPort(('workbench.proteinmpnn_design',), name={'zh-CN': '设计结果', 'en': 'Design results'})}, outputs={'sequence': OutputPort('workbench.sequence', name={'zh-CN': '序列', 'en': 'Sequence'})},
             parameters={'chain': {'type': 'string', 'title': {'zh-CN': '链', 'en': 'Chain'}, 'description': 'Actual chain; omit only when every sample has the same single chain'}})),
        ui=str(Path(__file__).with_name('ui.js').resolve()))
