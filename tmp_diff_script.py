import subprocess
import json

branches = []
with open('perf_prs.txt', 'r', encoding='utf-8') as f:
    for line in f:
        if line.startswith('---'):
            parts = line.split('---')
            if len(parts) >= 3:
                branches.append(parts[1].strip())

summary = ""
for b in branches:
    try:
        diff_stat = subprocess.check_output(['git', 'diff', 'origin/main...' + b, '--stat']).decode('utf-8')
        summary += f"\n{'='*50}\nBranch: {b}\n{diff_stat}\n"
    except Exception as e:
        summary += f"\nError on {b}: {e}\n"

with open('perf_summary.txt', 'w', encoding='utf-8') as f:
    f.write(summary)
