#!/usr/bin/env python3
"""
PDFRecon v4.7.6 – 13-06-2025
Author : Rasmus Riis  (NC3)   •   RRK001@politi.dk
"""

from __future__ import annotations
import argparse, csv, hashlib, os, platform, re, subprocess, sys, zlib
from datetime import datetime
from pathlib import Path
from typing import List, Tuple
import tkinter as tk
from tkinter import filedialog, messagebox

# ── Meta info ───────────────────────────────────────────────────────
VERSION, BUILD_DATE = "v4.7.6", "13-06-2025"
ORG, AUTHOR, EMAIL = "NC3 – Nationalt Cyber Crime Center", "Rasmus Riis", "RRK001@politi.dk"

# ── Rapportfil ──────────────────────────────────────────────────────
REPORT_FILE = Path("fileinfo.tsv").resolve()

HEADER_ROW  = ["Original", "Altered", "Path", "MD5",
               "Created", "Modified", "EXIFTool", "Suspicious"]

def _ensure_header():
    with REPORT_FILE.open("w", newline="") as fp:
        csv.writer(fp, delimiter="\t").writerow(HEADER_ROW)

def _write(row: List[str]):
    with REPORT_FILE.open("a", newline="") as fp:
        csv.writer(fp, delimiter="\t").writerow(row)

# ── ExifTool wrapper ───────────────────────────────────────────────
def _exif(p: Path) -> str:
    exe = "exiftool.exe" if platform.system() == "Windows" else "exiftool"
    cmd = str(Path(__file__).with_name(exe) if Path(__file__).with_name(exe).exists() else exe)
    try:
        return subprocess.run([cmd, str(p)], capture_output=True, text=True)\
               .stdout.strip().replace("\n", chr(10))
    except FileNotFoundError:
        return "(exiftool not found)"

# ── Stream-dekomprimering ──────────────────────────────────────────
def _decomp(b: bytes) -> str:
    for fn in (
        zlib.decompress,
        lambda d: __import__("base64").a85decode(re.sub(rb"\s", b"", d), adobe=True),
        lambda d: __import__("binascii").unhexlify(re.sub(rb"\s|>", b"", d)),
    ):
        try: return fn(b).decode("latin1", "ignore")
        except Exception: pass
    return ""

def _collect_text(raw: bytes) -> str:
    txt = [raw.decode("latin1", "ignore")]

    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.S):
        txt.append(_decomp(m.group(1)))

    m = re.search(rb"<\?xpacket begin=.*?\?>(.*?)<\?xpacket end=[^>]*\?>", raw, re.S)
    if m:
        try:
            txt.append(m.group(1).decode("utf-8", "ignore"))
        except Exception:
            pass

    return "\n".join(txt)

# ── Indikator-detektor ─────────────────────────────────────────────
def _detect(txt: str) -> str:
    lo=txt.lower(); reasons=[]
    if re.search(r"touchup[\s_/]?textedit", lo): reasons.append("TouchUp_TextEdit")
    if "derivedfrom" in lo:    reasons.append("DerivedFrom")
    if "sourcemodified" in lo: reasons.append("SourceModified")
    if "xmpmm:history" in lo:  reasons.append("xmpMM:History")
    if "documentancestors" in lo: reasons.append("DocumentAncestors")

    iid=re.findall(r"(?:/|:)instanceid[^<\(\[]*(?:<|[\(])([^>\)]+)", lo,re.I)
    if len(set(iid))>2: reasons.append(f"Different InstanceID×{len(set(iid))}")
    did=re.findall(r"(?:/|:)documentid[^<\(\[]*(?:<|[\(])([^>\)]+)", lo,re.I)
    if len(set(did))>1: reasons.append(f"Multiple DocumentID×{len(set(did))}")

    if "/prev" in lo: reasons.append("IncrementalUpdate")
    if txt.lower().count("startxref")>1: reasons.append("Multiple startxref")

    hdr=re.search(r"%pdf-(\d\.\d)", txt, re.I)
    prod=re.search(r"/producer\s*\(([^)]+)\)", txt, re.I)
    if hdr and prod and float(hdr.group(1))<=1.4 and "acrobat" in prod.group(1).lower() and re.search(r"20\d{2}", prod.group(1)):
        reasons.append("HeaderVsProducer")

    def grab(sl,iso):
        m=re.search(rf"/{sl}\s*\(d:(\d{{14}})", txt, re.I)
        if m: return m.group(1)
        m=re.search(rf"{iso}[^>]*>(\d{{4}}-\d{{2}}-\d{{2}}[^<]+)", lo)
        return m.group(1) if m else None

    c,m=grab("CreationDate","createdate"),grab("ModDate","modifydate")
    try:
        if c and m:
            fmt="%Y%m%d%H%M%S" if len(c)==14 else None
            dc=datetime.strptime(c,fmt) if fmt else datetime.fromisoformat(c.replace("t"," ",1))
            dm=datetime.strptime(m,fmt) if fmt else datetime.fromisoformat(m.replace("t"," ",1))
            if (dm-dc).total_seconds()>60: reasons.append("ModDate>CreationDate")
    except Exception: pass
    return "; ".join(reasons)

# ── Log-helper ─────────────────────────────────────────────────────
def _log(path: Path, raw: bytes,
         orig:str, alt:str, ct:datetime, mt:datetime,
         analyze:bool, extra:str="") -> bool:
    susp=_detect(_collect_text(raw)) if analyze else ""
    if extra: susp=f"{susp}; {extra}" if susp else extra
    _write([orig,alt,str(path),
            hashlib.md5(raw).hexdigest(), ct, mt, _exif(path), susp])
    return bool(susp)

# ── Scan-folder ────────────────────────────────────────────────────
def scan(folder: Path)->Tuple[int,int,int]:
    _ensure_header()
    total=rev_cnt=susp=0
    folder=folder.resolve()
    for base,_,files in os.walk(folder):
        for fn in files:
            if not fn.lower().endswith(".pdf"): continue
            total+=1
            fp=Path(base)/fn; raw=fp.read_bytes(); st=fp.stat()
            ct,mt=datetime.fromtimestamp(st.st_ctime),datetime.fromtimestamp(st.st_mtime)

            offs,pos=[],len(raw)
            while (pos:=raw.rfind(b"%%EOF",0,pos))!=-1: offs.append(pos)
            valid=[o for o in sorted(offs) if 1000<=o<=len(raw)-500]

            if _log(fp,raw,fn,"",ct,mt,True,"HasRevisions" if valid else ""): susp+=1

            if valid:
                out=Path(base)/"Altered_files"; out.mkdir(exist_ok=True)
                for idx,off in enumerate(valid,1):
                    rev_cnt+=1
                    rev=raw[:off+5]
                    rname=f"{fp.stem}_rev{idx}_off{off}.pdf"
                    rpath=out/rname; rpath.write_bytes(rev)
                    _log(rpath,rev,"",rname,ct,mt,False,"Revision")

    report=str(REPORT_FILE)
    print(f"\nProcessed : {total}\nRevisions : {rev_cnt}\nSuspicious: {susp}\n"
          f"See complete results in: {report}\n")
    return total,rev_cnt,susp

# ── GUI / CLI ──────────────────────────────────────────────────────
def gui():
    def run():
        fld = filedialog.askdirectory(title="Vælg mappe med PDF-filer")
        if not fld:
            status_label.config(text="Ingen mappe valgt.")
            return
        status_label.config(text="🔍 Analyserer…")
        btn_scan.config(state=tk.DISABLED)
        root.update_idletasks()
        tot, revs, sus = scan(Path(fld))
        status_label.config(text=f"✔ {tot} filer | {revs} rev | {sus} suspect")
        btn_scan.config(state=tk.NORMAL)

        msg = (
            f"Filer behandlet : {tot}\n"
            f"Revisioner       : {revs}\n"
            f"Suspicious filer : {sus}\n\n"
            f"Se komplette resultater i:\n{REPORT_FILE}\n\n"
            f"Vil du åbne mappen?"
        )
        if messagebox.askyesno("Analyse fuldført", msg):
            try:
                os.startfile(os.path.dirname(REPORT_FILE))  # Windows
            except AttributeError:
                subprocess.run(["xdg-open", os.path.dirname(REPORT_FILE)])

    def about():
        messagebox.showinfo("Om PDFRecon",
            f"Version : {VERSION} ({BUILD_DATE})\n"
            f"Organisation : {ORG}\n"
            f"Author       : {AUTHOR}\n"
            f"E-mail       : {EMAIL}")

    def on_close():
        if messagebox.askokcancel("Afslut", "Vil du lukke PDFRecon?"):
            root.destroy()

    root = tk.Tk()
    root.title("PDFRecon – NC3")
    root.geometry("520x260")
    root.resizable(False, False)
    root.configure(bg="#f2f2f2")
    root.protocol("WM_DELETE_WINDOW", on_close)

    font_title = ("Segoe UI", 14, "bold")
    font_text = ("Segoe UI", 10)
    font_button = ("Segoe UI", 10)

    tk.Label(root, text="PDFRecon", font=font_title, bg="#f2f2f2", anchor="w")\
        .pack(fill="x", padx=15, pady=(12, 0))

    tk.Label(root, text="NC3 værktøj til detektion af PDF-manipulation",
             font=font_text, bg="#f2f2f2", fg="#555").pack(anchor="w", padx=15)

    frame = tk.Frame(root, bg="#f2f2f2")
    frame.pack(pady=(20, 0))

    btn_scan = tk.Button(frame, text="🔍 Vælg mappe og scan", width=40,
                         font=font_button, command=run)
    btn_scan.grid(row=0, column=0, padx=10, pady=5)

    btn_about = tk.Button(frame, text="ℹ Om PDFRecon", width=40,
                          font=font_button, command=about)
    btn_about.grid(row=1, column=0, padx=10, pady=5)

    status_label = tk.Label(root, text="Klar", font=("Segoe UI", 9),
                            fg="#003366", bg="#f2f2f2")
    status_label.pack(pady=15)

    root.mainloop()

def _cli():
    p=argparse.ArgumentParser(); p.add_argument("directory",nargs="?")
    a=p.parse_args(); return Path(a.directory) if a.directory else None

if __name__=="__main__":
    p=_cli()
    if p:
        if not p.exists(): sys.exit("Stien findes ikke")
        scan(p)
    else:
        gui()
