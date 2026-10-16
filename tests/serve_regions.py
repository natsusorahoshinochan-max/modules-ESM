"""Browser scenario with an explicit external source of existing measurements."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile

import uvicorn
from protein_workbench_public.bootstrap import create_application
from protein_workbench_public.module_registry import DEFAULT_MODULES

root = Path(os.environ.get('PROTEIN_WORKBENCH_DATA_ROOT', tempfile.mkdtemp(prefix='regional-ui-')))
root.mkdir(parents=True, exist_ok=True)
os.environ['PROTEIN_WORKBENCH_DATA_ROOT'] = str(root)
(root / 'modules.json').write_text(json.dumps({'packages': [
    *[asdict(module) for module in DEFAULT_MODULES],
    {'package_id': 'region_observations', 'package_module': 'region_observations',
     'enabled': True, 'source_root': str(Path(__file__).parent.resolve())},
]}))
uvicorn.run(create_application(load_example_results=False), host='127.0.0.1', port=8237, log_level='warning')
