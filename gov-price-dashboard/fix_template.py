# -*- coding: utf-8 -*-
# Fix the broken end of _BREED_BATCH_TEMPLATE in provenance.py

path = '/Users/pengfit/.openclaw/workspace/skills/gov-price-dashboard/api/routes/provenance.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# The corrupted line - try to find it
target = '"品种1":'
idx = content.find(target)
if idx == -1:
    print("Cannot find target")
    import sys; sys.exit(1)

# Find the start of this line
line_start = content.rfind('\n', 0, idx) + 1
line_end = content.find('\n', idx)
bad_line = content[line_start:line_end]

# Show what's there
print(f"Bad line: {repr(bad_line)}")

# Replace with correct ending
correct = '    "{\\n  \\"ok\\": true,\\n  \\"results\\": {\\n    \\"品种1\\": {\\"category\\": \\"分类名\\", \\"confidence\\": 0.95, \\"note\\": \\"\\"},\\n    \\"品种2\\": {\\"category\\": \\"分类名\\", \\"confidence\\": 0.88, \\"note\\": \\"\\"}\\n  }\\n}")'

content = content[:line_start] + correct + '\n' + content[line_end+1:]
with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Fixed!")