import re

def get_en_headings():
    headings = []
    with open('lang/manual_en.md', 'r', encoding='utf-8') as f:
        for line in f:
            if line.startswith('## '):
                headings.append(line.strip()[3:])
    return headings

def get_da_headings():
    headings = []
    with open('lang/manual_da.md', 'r', encoding='utf-8') as f:
        content = f.read()
        matches = re.findall(r'<b>(.*?)</b>', content)
        for m in matches:
            clean = m.strip().replace('*', '').replace('_', '')
            if clean:
                headings.append(clean)
    return headings

en_h = get_en_headings()
da_h = get_da_headings()

with open('tmp/diff2.txt', 'w', encoding='utf-8') as f:
    f.write(f"Count: EN={len(en_h)}, DA={len(da_h)}\n")
    for i in range(max(len(en_h), len(da_h))):
        e = en_h[i] if i < len(en_h) else "MISSING"
        d = da_h[i] if i < len(da_h) else "MISSING"
        f.write(f"{i+1:02d} | EN: {e[:40]:<40} | DA: {d[:40]}\n")
