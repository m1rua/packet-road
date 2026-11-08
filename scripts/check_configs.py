"""Static configuration checks, not additional test scenarios."""
import json
from pathlib import Path

import yaml

for path in Path('.').rglob('*'):
    if any(part.startswith('.') or part == 'work' for part in path.parts):
        continue
    if path.suffix in ('.yaml', '.yml'):
        list(yaml.safe_load_all(path.read_text()))
    elif path.suffix == '.json':
        json.loads(path.read_text())
print('YAML and JSON syntax OK')
