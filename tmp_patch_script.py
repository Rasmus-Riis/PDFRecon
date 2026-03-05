import subprocess

branches = []
with open('perf_prs.txt', 'r', encoding='utf-8') as f:
    for line in f:
        if line.startswith('---'):
            parts = line.split('---')
            if len(parts) >= 3:
                branches.append(parts[1].strip())

patch = ""
for b in branches:
    try:
        diff_out = subprocess.check_output(['git', 'diff', 'origin/main...' + b]).decode('utf-8')
        patch += f"\n{'='*50}\nBranch: {b}\n{'='*50}\n{diff_out}\n"
    except Exception as e:
        patch += f"\nError on {b}: {e}\n"

with open('perf_patches.txt', 'w', encoding='utf-8') as f:
    f.write(patch)
