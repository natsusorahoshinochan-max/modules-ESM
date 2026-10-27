"""ESM3 tools: deployment settings and public adapter implementations."""
from protein_workbench_public.module_api import Module

def module():
    from .adapters import tools
    return Module('workbench.esm3', {'zh-CN': 'ESM3 工具', 'en': 'ESM3 tools'}, tools=tools(), settings={'token': {'type': 'string', 'title': {'zh-CN': 'Biohub 凭据', 'en': 'Biohub credential'}, 'secret': True}, 'service_url': {'title': {'zh-CN': '服务地址', 'en': 'Service URL'}, 'description': 'Biohub service URL'}, 'model_path': {'title': {'zh-CN': '模型目录', 'en': 'Model directory'}, 'description': 'Existing esm3-sm-open-v1 snapshot directory'}, 'device': {'title': {'zh-CN': '计算设备', 'en': 'Device'}, 'description': 'cpu, cuda or mps'}, 'python': {'title': {'zh-CN': 'Python 路径', 'en': 'Python path'}, 'description': 'Existing Python executable with pinned esm and torch'}})
