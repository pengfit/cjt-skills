# -*- coding: utf-8 -*-
path = '/Users/pengfit/.openclaw/workspace/skills/gov-price-dashboard/api/routes/provenance.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

old = 'PROMPTS = _load_prompts()\n\n    """生成 fix-case API 的 user content（fix-case 端点专用）""" '
new = 'PROMPTS = _load_prompts()\n\n\ndef fix_case_prompt_fn(spec, breed="", category="", expected=None):\n    """生成 fix-case API 的 user content（fix-case 端点专用）""" '

if old in content:
    content = content.replace(old, new)
    print("Fixed!")
else:
    print("Pattern not found, trying to find...")
    idx = content.find('PROMPTS = _load_prompts()')
    print(repr(content[idx:idx+200]))

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)