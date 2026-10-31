"""Extrae el catálogo de skills de NVIDIA (README de github.com/NVIDIA/skills) a build/skills.json.

Uso: python build/extract.py <README.md>
"""
import json
import re
import sys
from pathlib import Path

cat, skills = None, {}
for line in Path(sys.argv[1]).read_text(encoding='utf-8').splitlines():
    m = re.match(r'^## (.+)$', line)
    if m:
        cat = m.group(1).strip()
        continue
    m = re.match(r'^- `([^`]+)` — (.*)$', line)
    if m and cat:
        desc = re.sub(r'\s*\*requires:.*$', '', m.group(2)).strip()
        desc = desc.split('. ')[0][:140]
        skills.setdefault(cat, []).append([m.group(1), desc])
Path('build/skills.json').write_text(json.dumps(skills, ensure_ascii=False), encoding='utf-8')
for k, v in skills.items():
    print(k, len(v), sum(len(a) + len(b) for a, b in v))
