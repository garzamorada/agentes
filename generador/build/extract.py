import re, json, sys
src = sys.argv[1]
cat = None; skills = {}
for line in open(src, encoding='utf-8'):
    m = re.match(r'^## (.+)$', line)
    if m:
        cat = m.group(1).strip(); continue
    m = re.match(r'^- `([^`]+)` — (.*)$', line)
    if m and cat:
        desc = re.sub(r'\s*\*requires:.*$', '', m.group(2)).strip()
        desc = desc.split('. ')[0][:140]
        skills.setdefault(cat, []).append([m.group(1), desc])
json.dump(skills, open('build/skills.json','w',encoding='utf-8'), ensure_ascii=False)
for k,v in skills.items(): print(k, len(v), sum(len(a)+len(b) for a,b in v))
