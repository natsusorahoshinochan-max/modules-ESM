"""ProteinMPNN tools: deployment settings and public adapter implementations."""
from protein_workbench_public.module_api import Module

def module():
    from .adapters import tools
    return Module('workbench.proteinmpnn', {'zh-CN': 'ProteinMPNN 工具', 'en': 'ProteinMPNN tools'}, tools=tools(), settings={'source': {'title': {'zh-CN': '源码目录', 'en': 'Source directory'}, 'description': 'Existing ProteinMPNN source directory'}, 'weights': {'title': {'zh-CN': '权重目录', 'en': 'Weights directory'}, 'description': 'Existing weights root'}, 'python': {'title': {'zh-CN': 'Python 路径', 'en': 'Python path'}, 'description': 'Existing Python executable with torch, numpy and gemmi'}, 'device': {'title': {'zh-CN': '计算设备', 'en': 'Device'}, 'description': 'cpu, cuda or mps'}})
