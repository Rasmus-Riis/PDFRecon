import re

def get_headings(file_path):
    headings = []
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
        matches = re.findall(r'<b>(.*?)</b>', content)
        for m in matches:
            clean = m.strip().replace('*', '').replace('_', '')
            if clean:
                headings.append(clean)
    return headings

en_h = get_headings('lang/manual_en.md')
da_h = get_headings('lang/manual_da.md')

with open('tmp/diff.txt', 'w', encoding='utf-8') as f:
    f.write(f"Count: EN={len(en_h)}, DA={len(da_h)}\n")
    for i in range(max(len(en_h), len(da_h))):
        e = en_h[i] if i < len(en_h) else "MISSING"
        d = da_h[i] if i < len(da_h) else "MISSING"
        f.write(f"{i+1:02d} | EN: {e[:40]:<40} | DA: {d[:40]}\n")
