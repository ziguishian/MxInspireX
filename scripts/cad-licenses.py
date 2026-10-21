"""Copy notices from the actual bundled wheels, including native dependencies."""
import importlib.metadata
import json
import shutil
import sys
from pathlib import Path

destination = Path(sys.argv[1])
destination.mkdir(parents=True, exist_ok=True)
additional = Path(__file__).resolve().parents[1] / 'services/api/notices'
if additional.is_dir(): shutil.copytree(additional,destination,dirs_exist_ok=True)
distributions = importlib.metadata.distributions(path=[sys.argv[2]]) if len(sys.argv)>2 else importlib.metadata.distributions()
inventory = []
for distribution in distributions:
    name = distribution.metadata.get('Name','unknown')
    records = []
    for file in distribution.files or []:
        if any(token in Path(str(file)).name.lower() for token in ('license', 'licence', 'copying', 'notice')):
            source = Path(distribution.locate_file(file))
            if not source.is_file() or source.stat().st_size > 2_000_000: continue
            relative = Path(name) / Path(str(file))
            if '..' in relative.parts: continue
            target = destination / relative
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(source.read_bytes())
            records.append(str(relative))
    inventory.append({'name':name,'version':distribution.version,'license':distribution.metadata.get('License-Expression') or distribution.metadata.get('License'),'notices':records})
(destination/'inventory.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2),encoding='utf-8')
