# -*- coding: utf-8 -*-
import yaml, re

path = '/Users/pengfit/.openclaw/workspace/skills/gov-price-dashboard/api/routes/prompts.yml'
with open(path, 'r', encoding='utf-8') as f:
    prompts = yaml.safe_load(f)

new_system = '你是一个建材品种分类专家。分类必须严格遵循给定的21个分类体系，不得自行发明新分类。'

new_template = open('/tmp/new_classify_prompt.txt', 'r', encoding='utf-8').read()

prompts['classify_breed_batch'] = {
    'system': new_system,
    'template': new_template
}

with open(path, 'w', encoding='utf-8') as f:
    yaml.dump(prompts, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
print('Done')