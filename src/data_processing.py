import re
import hashlib
import subprocess
import zlib
import base64
import binascii
import logging
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from .utils import _import_with_fallback
from .config import PDFReconConfig, PDFProcessingError, PDFCorruptionError, \
    PDFTooLargeError, PDFEncryptedError, KV_PATTERN, DATE_TZ_PATTERN
from .pdf_processor import count_layers
from .xmp_relationship import XMPRelationshipManager

fitz = _import_with_fallback('fitz', 'fitz', 'PyMuPDF')
import typing
from typing import Any, Callable, Dict, Set, List

class DataProcessingMixin:
    if typing.TYPE_CHECKING:
        all_scan_data: Dict[str, Any]
        tree: Any
        file_annotations: Dict[str, str]
        case_is_dirty: bool
        progress_var: Any
        stop_event: Any
        scan_total: int
        scan_completed: int
        _schedule_main: Callable[..., None]
        _safe_update_ui: Callable[[Callable], None]
        status_label: Any
        worker_pool: Any
        _cancel_scan_event: Any
        language: str
        _resolve_case_path: Callable[..., str]
        
    def _(self, key, default=None):
        """Placeholder for translation method. Overridden by App."""
        return str(key)

    # Tokens from known PDF creators/editors/viewers (Wikipedia "List of PDF software" + project-specific).
    SOFTWARE_TOKENS = re.compile(
        r"(abbey|abbyy|acrobat|adobe|apache|birt|billy|bluebeam|bullzip|businesscentral|cairo|canva|chrome|chromium|"
        r"clibpdf|collabora|cups|cutepdf|deskpdf|dinero|dynamics|ecopy|economic|edge|eboks|evince|excel|firefox|"
        r"finereader|formpipe|foxit|fpdf|framemaker|gdoc|ghostscript|ghostview|gimp|helpndoc|illustrator|ilovepdf|"
        r"imagemagick|indesign|inkscape|itext|javelin|jasperreports|karbon|kmd|lasernet|latex|libharu|libreoffice|"
        r"luatex|mathcad|microsoft|mobipocket|mupdf|navision|netcompany|nitro|okular|office|openoffice|openpdf|"
        r"paperport|pagestream|pageplus|pdf24|pdfarranger|pdfbox|pdfcreator|pdfedit|pdfescape|pdfgear|pdflatex|"
        r"pdfjs|pdfsam|pdfsharp|pdfstudio|pdftk|pdfxchange|photoshop|poppler|powerpoint|pstoedit|primopdf|prince|"
        r"qpdf|qiqqa|quartz|reportlab|revu|safari|scribus|serif|skim|skia|smallpdf|sodapdf|solidconverter|"
        r"stdu|sumatra|swftools|tcpdf|tex|utopia|visma|word|wkhtml|wkhtmltopdf|xara|xetex|xpdf)",
        re.IGNORECASE
    )

    @staticmethod
    def _compile_software_regex():
        return DataProcessingMixin.SOFTWARE_TOKENS

    def _add_layer_indicators(self, raw: bytes, path: Path, indicators: dict):
        try:
            layers_cnt = count_layers(raw)
        except Exception:
            layers_cnt = 0

        if layers_cnt <= 0:
            return

        indicators['HasLayers'] = {'count': layers_cnt}

        page_count = 0
        try:
            with fitz.open(path) as _doc:
                page_count = _doc.page_count
        except Exception:
            pass

        if page_count and layers_cnt > page_count:
            indicators['MoreLayersThanPages'] = {'layers': layers_cnt, 'pages': page_count}

    def _extract_key_dates_from_timeline(self, timeline_data):
        dates = {
            "created": None,
            "modified": None,
            "metadata": None,
            "tool": None
        }
        
        if not timeline_data:
            return dates

        all_events = timeline_data.get("aware", []) + timeline_data.get("naive", [])
        
        for dt_obj, description in all_events:
            desc_lower = description.lower()
            dt_str = dt_obj.strftime("%d-%m-%Y %H:%M:%S")
            
            if "created" in desc_lower or "creation" in desc_lower:
                if not dates["created"] or "exiftool" in desc_lower:
                    dates["created"] = dt_str
            
            if "modified" in desc_lower or "modify" in desc_lower:
                if not dates["modified"] or "exiftool" in desc_lower:
                    dates["modified"] = dt_str
            
            if "metadata" in desc_lower:
                if not dates["metadata"] or "exiftool" in desc_lower:
                    dates["metadata"] = dt_str

            if "tool:" in desc_lower:
                try:
                    tool_part = description.split("Tool:")[1].strip()
                    if tool_part and not dates["tool"]:
                        dates["tool"] = tool_part[:50]  
                except Exception:
                    pass

        return dates

    def extract_revisions(self, raw, original_path):
        revisions = []
        offsets = []
        pos = len(raw)
        while (pos := raw.rfind(b"%%EOF", 0, pos)) != -1: offsets.append(pos)
        
        sorted_offsets = sorted(offsets)
        
        if sorted_offsets and sorted_offsets[-1] > len(raw) - 100:
            sorted_offsets.pop()
            
        valid_offsets = [o for o in sorted_offsets if o >= 500]
        
        if valid_offsets:
            altered_dir = original_path.parent / "Altered_files"
            if not altered_dir.exists():
                altered_dir.mkdir(parents=True, exist_ok=True)
            
            for offset in valid_offsets:
                rev_bytes = raw[:offset + 5]
                
                is_valid = False
                try:
                    test_doc = fitz.open(stream=rev_bytes, filetype="pdf")
                    if len(test_doc) > 0:
                        is_valid = True
                    test_doc.close()
                except Exception:
                    is_valid = False
                    
                if is_valid:
                    rev_idx = len(revisions) + 1
                    rev_filename = f"{original_path.stem}_rev{rev_idx}_@{offset}.pdf"
                    rev_path = altered_dir / rev_filename
                    rev_path.write_bytes(rev_bytes)
                    revisions.append((rev_path, original_path.name, rev_bytes))
                
        return revisions

    def exiftool_output(self, path, detailed=False):
        exe_path = None
        is_safe_location = False

        if PDFReconConfig.EXIFTOOL_PATH:
            p = Path(PDFReconConfig.EXIFTOOL_PATH)
            if p.is_file():
                exe_path = p
                is_safe_location = True 

        if not exe_path:
            system_path = shutil.which("exiftool")
            if system_path:
                exe_path = Path(system_path)
                is_safe_location = True 

        if not exe_path:
            bundled_path = self._resolve_path("exiftool.exe", base_is_parent=False)
            if bundled_path.is_file():
                exe_path = bundled_path
                if getattr(sys, 'frozen', False):
                    is_safe_location = True
                else:
                    is_safe_location = False

        if not exe_path:
            local_path = self._resolve_path("exiftool.exe", base_is_parent=True)
            if local_path.is_file():
                exe_path = local_path
                is_safe_location = False 

        if not exe_path:
            return self._("exif_err_notfound")

        if PDFReconConfig.EXIFTOOL_HASH or not is_safe_location:
            try:
                sha256_hash = hashlib.sha256()
                with open(exe_path, "rb") as f:
                    for byte_block in iter(lambda: f.read(4096), b""):
                        sha256_hash.update(byte_block)
                file_hash = sha256_hash.hexdigest()

                if PDFReconConfig.EXIFTOOL_HASH:
                    if file_hash.lower() != PDFReconConfig.EXIFTOOL_HASH.lower():
                         return f"Error: ExifTool hash mismatch. Expected {PDFReconConfig.EXIFTOOL_HASH}, got {file_hash}."

                elif not is_safe_location:
                     msg = "Security Error: ExifTool found in untrusted location without integrity verification.\n" \
                           "To fix this, either:\n" \
                           "1. Install ExifTool to a system path (e.g. PATH),\n" \
                           "2. Configure 'ExifToolPath' in config.ini to a trusted location, or\n" \
                           "3. Configure 'ExifToolHash' in config.ini with the SHA256 hash of the local executable."
                     logging.error(msg)
                     return msg

            except Exception as e:
                logging.error(f"Error verifying ExifTool integrity: {e}")
                return f"Error verifying ExifTool integrity: {e}"
        
        try:
            file_content = path.read_bytes()
            startupinfo = None
            if sys.platform == "win32":
                import subprocess
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            command = [str(exe_path)]
            if detailed: command.extend(["-a", "-u", "-s", "-G1", "-struct"])
            else: command.extend(["-a", "-u", "-s", "-G1"])
            command.append("-") 

            run_kw = dict(
                capture_output=True,
                check=False,
                timeout=PDFReconConfig.EXIFTOOL_TIMEOUT,
            )
            if startupinfo is not None:
                run_kw["startupinfo"] = startupinfo
            if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
                run_kw["creationflags"] = subprocess.CREATE_NO_WINDOW
            process = subprocess.run(command, input=file_content, **run_kw)
            
            if process.returncode != 0 or process.stderr:
                error_message = process.stderr.decode('latin-1', 'ignore').strip()
                if not process.stdout.strip(): return f"{self._('exif_err_prefix')}\n{error_message}"
                logging.warning(f"ExifTool stderr for {path.name}: {error_message}")

            try: raw_output = process.stdout.decode('utf-8').strip()
            except UnicodeDecodeError: raw_output = process.stdout.decode('latin-1', 'ignore').strip()

            return "\n".join([line for line in raw_output.splitlines() if line.strip()])

        except subprocess.TimeoutExpired:
            logging.error(f"ExifTool timed out for file {path.name}")
            return self._("exif_err_prefix") + f"\nTimeout after {PDFReconConfig.EXIFTOOL_TIMEOUT} seconds."
        except Exception as e:
            logging.error(f"Error running exiftool for file {path}: {e}")
            return self._("exif_err_run").format(e=e)

    def _get_filesystem_times(self, filepath):
        events = []
        try:
            stat = filepath.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime).astimezone()
            events.append((mtime, f"File System: {self._('col_modified')}"))
            ctime = datetime.fromtimestamp(stat.st_ctime).astimezone()
            events.append((ctime, f"File System: {self._('col_created')}"))
        except FileNotFoundError:
            pass
        return events

    @staticmethod
    def _parse_exif_data(exiftool_output: str):
        data = {
            "producer_pdf": "", "producer_xmppdf": "", "softwareagent": "",
            "application": "", "software": "", "creatortool": "", "xmptoolkit": "",
            "create_dt": None, "modify_dt": None, "history_events": [], "all_dates": []
        }
        lines = exiftool_output.splitlines()

        history_pattern = re.compile(r"\[XMP-xmpMM\]\s+History\s+:\s+(.*)")

        def looks_like_software(s: str) -> bool:
            return bool(s and DataProcessingMixin.SOFTWARE_TOKENS.search(s))

        for ln in lines:
            m = KV_PATTERN.match(ln)
            if not m: 
                continue
            
            group = m.group("group").strip().lower()
            tag = m.group("tag").strip().lower().replace(" ", "")
            val = m.group("value").strip()

            if tag == "producer":
                if group == "pdf" and not data["producer_pdf"]: 
                    data["producer_pdf"] = val
                elif group in ("xmp-pdf", "xmp_pdf") and not data["producer_xmppdf"]: 
                    data["producer_xmppdf"] = val
            elif tag == "softwareagent" and not data["softwareagent"]: 
                data["softwareagent"] = val
            elif tag == "application" and not data["application"]: 
                data["application"] = val
            elif tag == "software" and not data["software"]: 
                data["software"] = val
            elif tag == "creatortool" and not data["creatortool"] and looks_like_software(val):
                data["creatortool"] = val
            elif tag == "xmptoolkit" and not data["xmptoolkit"]: 
                data["xmptoolkit"] = val
        
        if not data["producer_pdf"] and data["producer_xmppdf"]: 
            data["producer_pdf"] = data["producer_xmppdf"]
        if not data["producer_xmppdf"] and data["producer_pdf"]: 
            data["producer_xmppdf"] = data["producer_pdf"]

        for ln in lines:
            hist_match = history_pattern.match(ln)
            if hist_match:
                history_str = hist_match.group(1)
                event_blocks = re.findall(r'\{([^}]+)\}', history_str)
                for block in event_blocks:
                    details = {k.strip(): v.strip() for k, v in (pair.split('=', 1) for pair in block.split(',') if '=' in pair)}
                    if 'When' in details:
                        try:
                            dt_obj = datetime.fromisoformat(details['When'].replace('Z', '+00:00'))
                            data["history_events"].append((dt_obj, details))
                        except (ValueError, IndexError):
                            pass
                continue

            kv_match = KV_PATTERN.match(ln)
            if not kv_match: 
                continue

            val_str = kv_match.group("value").strip()
            match = DATE_TZ_PATTERN.match(val_str)
            
            if match:
                parts = match.groupdict()
                date_part = parts.get("date").replace(":", "-", 2).replace(" ", "T")
                tz_part = parts.get("tz")
                
                try:
                    full_date_str = date_part
                    if tz_part:
                        full_date_str += tz_part.replace('Z', '+00:00')
                    
                    dt = datetime.fromisoformat(full_date_str)
                    
                    tag = kv_match.group("tag").strip().lower().replace(" ", "")
                    group = kv_match.group("group").strip()
                    data["all_dates"].append({"dt": dt, "tag": tag, "group": group, "full_str": val_str})

                except ValueError:
                    continue
        
        for d in data["all_dates"]:
            if d["tag"] in {"createdate", "creationdate"}:
                if data["create_dt"] is None or d["dt"] < data["create_dt"]:
                    data["create_dt"] = d["dt"]
            elif d["tag"] in {"modifydate", "metadatadate"}:
                if data["modify_dt"] is None or d["dt"] > data["modify_dt"]:
                    data["modify_dt"] = d["dt"]
        
        return data

    def _detect_tool_change_from_exif(self, exiftool_output: str, parsed_data=None):
        data = parsed_data if parsed_data else self._parse_exif_data(exiftool_output)
        
        create_tool = data["producer_pdf"] or data["producer_xmppdf"] or data["application"] or data["software"] or data["creatortool"] or ""
        modify_tool = data["softwareagent"] or data["producer_pdf"] or data["producer_xmppdf"] or data["application"] or data["software"] or data["creatortool"] or ""
        
        create_engine = modify_engine = ""
        if data["xmptoolkit"]:
            if data["create_dt"]: create_engine = data["xmptoolkit"]
            if data["modify_dt"]: modify_engine = data["xmptoolkit"]

        changed_tool = bool(create_tool and modify_tool and create_tool.strip() != modify_tool.strip())
        changed_engine = bool(create_engine and modify_engine and create_engine.strip() != modify_engine.strip())
        
        reason = ""
        if changed_tool and changed_engine: reason = "mixed"
        elif changed_tool: reason = "producer" if (data["producer_pdf"] or data["producer_xmppdf"]) else "software"
        elif changed_engine: reason = "engine"

        return {
            "changed": changed_tool or changed_engine,
            "create_tool": create_tool, "modify_tool": modify_tool,
            "create_engine": create_engine, "modify_engine": modify_engine,
            "modify_dt": data["modify_dt"],
            "reason": reason
        }

    def _parse_exiftool_timeline(self, exiftool_output, parsed_data=None):
        events = []
        data = parsed_data if parsed_data else self._parse_exif_data(exiftool_output)

        create_tool = data["producer_pdf"] or data["producer_xmppdf"] or data["application"] or data["software"] or data["creatortool"] or ""
        modify_tool = data["softwareagent"] or create_tool 

        for dt_obj, details in data["history_events"]:
            action = details.get('Action', 'N/A')
            agent = details.get('SoftwareAgent', '')
            changed = details.get('Changed', '')
            desc = [f"Action: {action}"]
            if agent: desc.append(f"Agent: {agent}")
            if changed: desc.append(f"Changed: {changed}")
            events.append((dt_obj, f"XMP History   - {' | '.join(desc)}"))

        def _ts_label(tag: str) -> str:
            t = tag.replace(" ", "").lower()
            return {"createdate": "Created", "creationdate": "Created", "modifydate": "Modified", "metadatadate": "Metadata"}.get(t, tag)

        for d in data["all_dates"]:
            label = self._(_ts_label(d["tag"]).lower())
            tool = create_tool if d["tag"] in {"createdate", "creationdate"} else modify_tool
            tool_part = f" | Tool: {tool}" if tool else ""
            events.append((d["dt"], f"ExifTool ({d['group']}) - {label}: {d['full_str']}{tool_part}"))
        
        if data["xmptoolkit"]:
            anchor_dt = data["create_dt"] or (data["all_dates"][0]["dt"] if data["all_dates"] else datetime.now())
            label_engine = "XMP Engine" if self.language.get() == "en" else "XMP-motor"
            events.append((anchor_dt, f"{label_engine}: {data['xmptoolkit']}"))

        return events

    @staticmethod
    def _format_timedelta(delta):
        if not delta or delta.total_seconds() < 0.001:
            return ""

        s = delta.total_seconds()
        days, remainder = divmod(s, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        parts = []
        if days > 0: parts.append(f"{int(days)}d")
        if hours > 0: parts.append(f"{int(hours)}h")
        if minutes > 0: parts.append(f"{int(minutes)}m")
        if seconds > 0 or not parts: parts.append(f"{seconds:.2f}s")

        return f"(+{ ' '.join(parts) })"

    def _parse_raw_content_timeline(self, file_content_string):
        events = []
        
        pdf_date_extended = re.compile(
            r"\/([A-Z][a-zA-Z0-9_]+)\s*\(\s*D:(\d{14})([+\-]\d{2}'\d{2}'|[+\-]\d{2}:\d{2}|[+\-]\d{4}|Z)?"
        )
        
        for match in pdf_date_extended.finditer(file_content_string):
            label, date_str, tz_str = match.groups()
            try:
                dt_obj = datetime.strptime(date_str, "%Y%m%d%H%M%S")
                
                if tz_str:
                    if tz_str == 'Z':
                        dt_obj = dt_obj.replace(tzinfo=timezone.utc)
                    else:
                        tz_clean = tz_str.replace("'", "").replace(":", "")
                        if len(tz_clean) == 5:  
                            tz_clean = tz_clean[:3] + ":" + tz_clean[3:]
                        try:
                            dt_obj = datetime.fromisoformat(dt_obj.strftime("%Y-%m-%dT%H:%M:%S") + tz_clean)
                        except ValueError:
                            pass  
                
                tz_display = tz_str if tz_str else ""
                display_line = f"Raw File: /{label}: {dt_obj.strftime('%Y-%m-%d %H:%M:%S')}{tz_display}"
                events.append((dt_obj, display_line))
            except ValueError:
                continue

        xmp_date_pattern = re.compile(r"<([a-zA-Z0-9:]+)[^>]*?>\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[^\s<]*)\s*<\/([a-zA-Z0-9:]+)>")
        for match in xmp_date_pattern.finditer(file_content_string):
            label, date_str, closing_label = match.groups()
            if label != closing_label: 
                continue
            try:
                normalized = date_str.strip()
                has_tz = 'Z' in normalized or '+' in normalized[10:] or (normalized.count('-') > 2 and '-' in normalized[10:])
                normalized = normalized.replace('Z', '+00:00')
                
                if '.' in normalized:
                    dot_pos = normalized.index('.')
                    tz_start = -1
                    for i, c in enumerate(normalized[dot_pos:]):
                        if c in '+-':
                            tz_start = dot_pos + i
                            break
                    if tz_start > 0:
                        normalized = normalized[:dot_pos] + normalized[tz_start:]
                    else:
                        normalized = normalized[:dot_pos]
                
                dt_obj = datetime.fromisoformat(normalized)
                display_line = f"Raw File: <{label}>: {date_str}"
                events.append((dt_obj, display_line))
            except (ValueError, IndexError):
                continue
        return events

    def generate_comprehensive_timeline(self, filepath, raw_file_content, exiftool_output, parsed_exif_data=None):
        all_events = []

        if parsed_exif_data is None:
            parsed_exif_data = self._parse_exif_data(exiftool_output)

        all_events.extend(self._get_filesystem_times(filepath))
        all_events.extend(self._parse_exiftool_timeline(exiftool_output, parsed_data=parsed_exif_data))
        all_events.extend(self._parse_raw_content_timeline(raw_file_content))

        try:
            info = self._detect_tool_change_from_exif(exiftool_output, parsed_data=parsed_exif_data)
            if info.get("changed"):
                when = info.get("modify_dt")
                if not when and all_events:
                    naive_dts = [e[0] for e in all_events if e[0].tzinfo is None]
                    when = max(naive_dts) if naive_dts else max(e[0] for e in all_events)
                if not when:
                    when = datetime.now()
                
                if self.language.get() == "da":
                    label = "Værktøj skiftet"
                    parts = [f"{info.get('create_tool','?')} → {info.get('modify_tool','?')}"]
                    if info.get("reason") == "engine":
                        parts.append(f"(XMP-motor: {info.get('create_engine','?')} → {info.get('modify_engine','?')})")
                    line = f"{label}: " + " ".join(parts)
                else:
                    label = "Tool changed"
                    parts = [f"{info.get('create_tool','?')} → {info.get('modify_tool','?')}"]
                    if info.get("reason") == "engine":
                        parts.append(f"(XMP engine: {info.get('create_engine','?')} → {info.get('modify_engine','?')})")
                    line = f"{label}: " + " ".join(parts)
                all_events.append((when, line))
        except Exception:
            pass

        aware_events = []
        naive_events = []
        for dt_obj, description in all_events:
            if dt_obj.tzinfo is not None:
                aware_events.append((dt_obj, description))
            else:
                naive_events.append((dt_obj, description))

        aware_events.sort(key=lambda x: x[0])
        naive_events.sort(key=lambda x: x[0])

        return {"aware": aware_events, "naive": naive_events}

    def _hash_file(self, filepath):
        sha256_hash = hashlib.sha256()
        try:
            with open(filepath, "rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            return sha256_hash.hexdigest()
        except FileNotFoundError:
            logging.error(f"Could not hash file, not found: {filepath}")
            return None
        except Exception as e:
            logging.error(f"Error hashing file {filepath}: {e}")
            return None

    def _calculate_hashes(self, data_to_hash):
        hashes = {}
        for item in data_to_hash:
            path_str = item.get('path')
            if path_str:
                full_path = self._resolve_case_path(path_str)
                file_hash = self._hash_file(full_path)
                if file_hash:
                    hashes[str(path_str)] = file_hash
        return hashes

    def _format_indicator_details(self, key, details):
        if key == 'TouchUp_TextEdit':
            found_text_str = ""
            diff_str = ""
            if details and details.get('found_text'):
                found_text = details['found_text']
                if isinstance(found_text, dict):
                    lines = [self._("details_note_individual_ops")]
                    for page_num in sorted(found_text.keys()):
                        texts = found_text[page_num]
                        if page_num == 0:
                            lines.append("\n" + self._("details_extracted_text"))
                        else:
                            lines.append(f"\n" + self._("details_side") + f" {page_num}:")
                        for idx, text in enumerate(texts, 1):
                            lines.append(f"  [{idx}] {text}")
                    found_text_str = "\n".join(lines)
                elif isinstance(found_text, list):
                    found_text_str = "\n".join(found_text)
            if details and details.get('text_diff'):
                diff_str = self._("details_comparison_available")
            
            if found_text_str and diff_str:
                return f"TouchUp TextEdit:\n{found_text_str}\n\n({diff_str})"
            elif found_text_str:
                return f"TouchUp TextEdit:\n{found_text_str}"
            elif diff_str:
                return f"TouchUp TextEdit ({diff_str})"
            else:
                return self._("details_touchup_acrobat")

        if key == 'MultipleCreators':
            values_str = "\n    - " + "\n    - ".join(f'"{v}"' for v in details['values'])
            return self._("details_multiple_creators").format(count=details['count']) + values_str
        if key == 'MultipleProducers':
            values_str = "\n    - " + "\n    - ".join(f'"{v}"' for v in details['values'])
            return self._("details_multiple_producers").format(count=details['count']) + values_str
        if key == 'MultipleFontSubsets':
            font_details = []
            for base_font, subsets in details['fonts'].items():
                font_details.append(f"'{base_font}': {{{{{', '.join(subsets)}}}}}")
            return self._("details_multiple_fonts") + "\n    - " + "\n    - ".join(font_details)
        if key == 'CreateDateMismatch':
            return self._("details_creation_mismatch").format(info=details['info'], xmp=details['xmp'])
        if key == 'ModifyDateMismatch':
            return self._("details_modify_mismatch").format(info=details['info'], xmp=details['xmp'])
        if key == 'TrailerIDChange':
            return self._("details_trailer_id_changed").format(old=details['from'], new=details['to'])
        if key == 'XMPIDChange':
            return self._("details_xmp_id_changed").format(old=details['from'], new=details['to'])
        if key == 'MultipleStartxref':
            offsets_str = "\n    - " + "\n    - ".join(str(o) for o in details.get('offsets', []))
            return self._("details_multiple_startxref").format(count=details['count'], offsets="") + offsets_str
        if key == 'IncrementalUpdates':
            return self._("details_incremental_updates").format(count=details['count'])
        if key == 'XMPHistory':
            return self._("details_xmp_history_exists")
        if key == 'LargeObjectNumberGaps':
            return self._("details_structural_gaps").format(percent=details['gap_percentage'], count=details['gap_count'], max_id=details['max_object'])
        if key == 'OrphanedObjects':
            ids_str = "\n    - " + "\n    - ".join(str(i) for i in details.get('ids', []))
            return self._("details_unreferenced_objects").format(count=details['count'], ids="") + ids_str
        if key == 'MissingObjects':
            ids_str = "\n    - " + "\n    - ".join(str(i) for i in details.get('ids', []))
            return self._("details_dangling_refs").format(count=details['count'], ids="") + ids_str
        if key == 'ObjGenGtZero':
            return self._("details_gen_gt_zero").format(count=details['count'])
        if key == 'HasAnnotations':
            annot_types = details.get('types', [])
            if annot_types:
                types_str = ", ".join(annot_types)
                return f"{self._('details_has_annotations')}: {details.get('count', 0)} ({types_str})"
            return self._("details_has_annotations")
        if key == 'HasLayers':
            return self._("details_has_layers").format(count=details['count'])
        if key == 'MoreLayersThanPages':
            return self._("details_more_layers_than_pages").format(layers=details['layers'], pages=details['pages'])
        if key == 'RelatedFiles':
            files = details.get('files', [])
            # Filter out placeholder IDs (e.g. 'ID: xmp.did:...', 'xmp.did:...')
            def _is_placeholder(name_val):
                s = str(name_val).strip()
                return not s or s == 'xmp.did:...' or (s.startswith('ID: ') and s.endswith('...'))
            filtered_files = [f for f in files if f.get('name') and not _is_placeholder(f['name'])]
            count = len(filtered_files)
            if count == 0: return None
            
            lines = [f"{self._('related_files_label')} ({count}):"]
            for f in filtered_files:
                rel_type = f.get('type', 'related')
                name = f.get('name', 'Unknown')
                if rel_type == 'derived_from':
                    lines.append(f"  ← {self._('relationship_derived_from')}: {name}")
                elif rel_type == 'parent_of':
                    lines.append(f"  → {self._('relationship_parent_of') if hasattr(self, '_') and self._('relationship_parent_of') != 'relationship_parent_of' else 'Parent of'}: {name}")
                else:
                    lines.append(f"  ↔ {self._('relationship_related_to') if hasattr(self, '_') and self._('relationship_related_to') != 'relationship_related_to' else 'Related to'}: {name}")
            return "\n".join(lines)
            
        if key == 'TimestampSpoofing':
            return self._("timestamp_spoofing").format(note=details.get('note', ''))
        if key == 'HiddenAnnotations':
            count = details.get('count', 0)
            if count == 0: return None
            annots = details.get('details', [])
            annot_str = "\n    • " + "\n    • ".join(f"Page {a['page']}: {a['type']} (Flags: {a['flags']}) at {a['rect']}" for a in annots)
            if count > len(annots): annot_str += self._("hidden_annotations_more").format(more=count-len(annots))
            return self._("hidden_annotations").format(count=count, details=annot_str.lstrip('\n    • '))
        if key == 'SubmitFormAction':
            return self._("submit_form_action").format(count=details.get('count', 0))
        if key == 'LaunchShellAction':
            return self._("launch_shell_action").format(count=details.get('count', 0))
        if key == 'ExtractedJavaScript':
            scripts = details if isinstance(details, list) else details.get('scripts', [])
            if not scripts:
                return self._("details_javascript_none")
            lines = [self._("details_javascript_count").format(count=len(scripts))]
            for i, s in enumerate(scripts[:5], 1):
                src = s.get('source', '?')
                code = (s.get('code') or '')[:200]
                if len(s.get('code') or '') > 200:
                    code += "..."
                lines.append(f"  [{i}] {src}: {code}")
            if len(scripts) > 5:
                lines.append(self._("details_javascript_more").format(count=len(scripts) - 5))
            return "\n".join(lines)

        if key == 'EmailAddresses':
            count = details.get('count', 0)
            if count == 0: return None
            emails = details.get('emails', [])
            emails_str = "\n    • " + "\n    • ".join(emails[:20])
            if count > 20: emails_str += self._("email_addresses_more").format(more=count-20)
            return self._("email_addresses").format(count=count, emails=emails_str.lstrip('\n    • '))
        if key == 'URLs':
            count = details.get('count', 0)
            if count == 0: return None
            domains = details.get('domains', [])
            domains_str = "\n    • " + "\n    • ".join(domains[:20])
            if count > 20: domains_str += self._("urls_more").format(more=count-20)
            return self._("urls_found").format(count=count, domains=domains_str.lstrip('\n    • '))
        if key == 'UNCPaths':
            count = details.get('count', 0)
            if count == 0: return None
            paths = details.get('paths', [])
            paths_str = ", ".join(paths[:5])
            if count > 5: paths_str += self._("unc_paths_more").format(more=count-5)
            return self._("unc_paths").format(count=count, paths=paths_str)
        if key == 'Languages':
            langs_list = ", ".join(details.get('languages', []))
            return self._("languages").format(languages=langs_list)
        if key == 'Encrypted' or key == 'PasswordRequired' or key == 'EncryptedButOpen' or key == 'EncryptionDictionary' or key == 'SecurityRestrictions':
            status = details.get('status', 'Present')
            if key == 'SecurityRestrictions' and 'restrictions' in details:
                rest = ", ".join(details['restrictions'])
                return self._("details_security_restrictions").format(restrictions=rest, p_value=details.get('permissions_value', 'Unknown'))
            return f"{key.replace('_', ' ')}: {status}"
        if key == 'InvisibleTextMode' or key == 'FileAttachmentAnnotations' or key == '3DObjects' or key == 'SoundAnnotations' or key == 'VideoContent' or key == 'RichMedia':
            status = details.get('status', 'Detected')
            note = f" ({details['note']})" if 'note' in details else ""
            return f"{key.replace('_', ' ')}: {status}{note}"
        if key == 'ExcessiveWhiteColor' or key == 'TextOutsideMediaBox':
            note = details.get('note', '')
            page = f" (Page {details['page']})" if 'page' in details else ""
            return f"{key.replace('_', ' ')}: {note}{page}"
        if key == 'EmbeddedFiles':
            count = details.get('count', 0)
            files = ", ".join(details.get('filenames', []))
            return self._("details_embedded_files").format(count=count, files=files)
        if key == 'OCRLayer':
            status = details.get('status', 'Suspected')
            note = details.get('note', '')
            pages = details.get('pages_with_pattern', 0)
            return self._("details_ocr_layer").format(status=status, note=note, pages=pages)
        if key == 'PolyglotFile':
            status = details.get('status', 'Suspicious')
            offset = details.get('pdf_header_offset', 0)
            fmt = details.get('detected_prefix_format', 'Unknown')
            return self._("details_polyglot").format(status=status, offset=offset, fmt=fmt)
        if key == 'FutureDatedTimestamps':
            count = details.get('count', 0)
            dates = ", ".join([d.get('date', '') for d in details.get('dates', [])])
            return self._("details_future_dated").format(count=count, dates=dates)
        if key == 'PDFACompliance':
            part = details.get('part', 'Unknown')
            return self._("details_pdfa_compliance").format(part=part)
            
        if key == 'NonEmbeddedFont':
            fonts = details.get('fonts', [])
            if not fonts: return None
            font_str = ", ".join(fonts[:10])
            if len(fonts) > 10: font_str += f" (+{len(fonts)-10} more)"
            return self._("NonEmbeddedFont") + f": {font_str}"
            
        if key == 'XMPHistoryGap':
            gaps = details.get('gaps', [])
            if not gaps: return None
            gap_summaries = []
            for g in gaps[:5]:
                if g['type'] == 'sequence_gap':
                    gap_summaries.append(self._("details_seq_gap").format(old=g['prev_id'], new=g['current_id']))
                else:
                    gap_summaries.append(self._("details_time_jump").format(days=g['jump_days'], old=g['prev_date'], new=g['current_date']))
            gap_str = "\n    • " + "\n    • ".join(gap_summaries)
            if len(gaps) > 5: gap_str += f"\n    • ... (+{len(gaps)-5} more)"
            return self._("XMPHistoryGap") + ":" + gap_str
            
        if key == 'StructuralScrubbing':
            blocks = details.get('blocks', [])
            if not blocks: return None
            null_blocks = [b for b in blocks if b['type'] == 'null']
            space_blocks = [b for b in blocks if b['type'] == 'space']
            summary = []
            if null_blocks:
                max_null = max(b['length'] for b in null_blocks)
                summary.append(self._("details_null_blocks").format(count=len(null_blocks), size=max_null))
            if space_blocks:
                max_space = max(b['length'] for b in space_blocks)
                summary.append(self._("details_space_blocks").format(count=len(space_blocks), size=max_space))
            return self._("StructuralScrubbing") + ": " + self._("details_and").join(summary)
            
        if key == 'PDFAViolation':
            violations = details.get('violations', [])
            if not violations: return None
            v_str = ", ".join(violations)
            return self._("PDFAViolation") + f": {v_str}"
        if key == 'JPEG_Analysis':
            total = details.get('total_jpegs', 0)
            suspicious = details.get('suspicious_count', 0)
            if suspicious == 0:
                return None
            note = details.get('note', '')
            result = f"• {self._('details_jpeg_analysis')}: {suspicious} {self._('details_out_of')} {total} {self._('details_jpeg_fingerprints')}"
            if 'suspicious_details' in details:
                det = "\n    " + "\n    ".join([f"Page {d.split('Page ')[1]}" if 'Page ' in d else d for d in details['suspicious_details']])
                # Simple cleanup of english hardcodes in details
                det = det.replace("Page ", self._('details_side') + " ").replace("SUSPICIOUS: Ultra-low compression", self._('details_ultra_low_comp'))
                result += det
            return result + "\n    " + self._("details_jpeg_note")
            
        if key == 'ErrorLevelAnalysis':
            findings = details.get('findings', [])
            lines = [self._("details_ela_title").format(count=len(findings))]
            for f in findings:
                lines.append(f"  • Page {f.get('page')} (Image XREF: {f.get('xref')}): Map Variance {f.get('variance', 0):.2f}")
            return "\n".join(lines)
        if key == 'TextOperatorAnomaly':
            anomalies = details.get('anomalies', [])
            lines = [self._("details_text_anomaly_title").format(count=len(anomalies))]
            for a in anomalies[:5]:
                lines.append(f"  • {a.get('desc')} -> {a.get('snippet')}")
            if len(anomalies) > 5:
                lines.append(f"  • ... (+{len(anomalies)-5} more)")
            return "\n".join(lines)
        if key == 'TimestampMismatch':
            mismatches = details.get('mismatches', [])
            lines = [self._("details_timestamp_mismatch_title")]
            for m in mismatches:
                lines.append(f"  • {m.get('type')}: Info={m.get('info_date', '?')}, XMP={m.get('xmp_date', '?')}")
            return "\n".join(lines)
        if key == 'AssetRelationship':
            lines = [f"{self._('asset_relationships_label')}:"]
            if details.get('derivation'):
                df = details['derivation']
                lines.append(f"  ← {self._('relationship_derived_from')}: DocumentID={df.get('documentID', '?')}")
            
            ing_count = len(details.get('ingredients', []))
            if ing_count > 0:
                lines.append(f"  • {self._('relationship_ingredients')} ({ing_count} {self._('found_label')}):")
                for ing in details['ingredients'][:5]:
                    name = ing.get('filePath') or f"ID: {ing.get('documentID', '?')[:8]}..."
                    lines.append(f"    - {name}")
                if ing_count > 5:
                    lines.append(f"    - ... and {ing_count - 5} more")
            
            pantry_count = len(details.get('pantry', {}))
            if pantry_count > 0:
                lines.append(f"  • {self._('details_pantry_count').format(count=pantry_count)}")
                
            if details.get('anomalies'):
                lines.append(f"\n  [!] {self._('relationship_anomalies')}:")
                for anomaly in details['anomalies']:
                    lines.append(f"    - {anomaly}")
            
            return "\n".join(lines)

        if key == 'PageInconsistency':
            pages = details.get('pages', [])
            lines = [self._("details_page_inconsistency_title").format(count=len(pages))]
            for p in pages:
                lines.append(f"  • Page {p.get('page')}: {p.get('type')} ({p.get('details')})")
            return "\n".join(lines)
        if key == 'ColorSpaceAnomaly':
            findings = details.get('findings', [])
            lines = [self._("details_color_space_anomaly_title").format(count=len(findings))]
            for f in findings:
                page_str = f"Page {f.get('page')}: " if f.get('page') else ""
                lines.append(f"  • {page_str}{f.get('desc')}")
            return "\n".join(lines)
        if key == 'ImagesWithEXIF':
            count = details.get('count', 0)
            return self._("details_exif_metadata_found").format(count=count)

        # NEW: Forensic Enhancements
        if key == 'FontCharacterRemapping':
            remaps = details.get('details', [])
            remap_str = "\n    • " + "\n    • ".join(f"Font '{r['font']}' maps hex <{r['from_hex']}> to Unicode '{r['to_unicode']}'" for r in remaps)
            return self._("details_font_remapping").format(count=details['count']) + remap_str

        if key == 'VersionFeatureContradiction':
            contradictions = details.get('contradictions', [])
            c_str = "\n    • " + "\n    • ".join(contradictions)
            return self._("details_version_contradiction").format(version=details['version']) + c_str

        if key == 'UnbalancedObjects':
            return self._("details_unbalanced_objects").format(obj=details['obj_count'], endobj=details['endobj_count'])

        if key == 'DuplicateObjectIDs':
            ids_str = ", ".join(details.get('ids', []))
            return self._("details_duplicate_object_ids").format(count=details['count'], ids=ids_str)

        if key == 'FormFieldOverlay':
            fields = details.get('details', [])
            field_str = "\n    • " + "\n    • ".join(f"Page {f['page']}: '{f['field']}' = '{f['value']}' (BBox: {f['rect']})" for f in fields)
            return self._("details_form_field_overlay").format(count=details['count']) + field_str

        if key == 'StackedFilters':
            streams = details.get('details', [])
            stream_str = "\n    • " + "\n    • ".join(f"XRef {s['xref']}: {', '.join(s['filters'])}" for s in streams)
            return self._("details_stacked_filters").format(count=details['count']) + stream_str
            
        return key.replace("_", " ")

    def get_flag(self, indicators_dict, is_revision, parent_id=None):
        if is_revision:
            return self._("revision_of").format(id=parent_id)

        keys_set = set(indicators_dict.keys())
        YES = self._("status_yes")
        NO = self._("status_no")

        high_risk_indicators = {
            "HasRevisions",
            "TouchUp_TextEdit",
            "Signature: Invalid",
            "ErrorLevelAnalysis",
            "PageInconsistency",
            "ColorSpaceAnomaly",
            "TextOperatorAnomaly",
            "FontCharacterRemapping",
            "VersionFeatureContradiction",
            "UnbalancedObjects",
            "DuplicateObjectIDs",
            "FormFieldOverlay",
            "StackedFilters",
            "TimestampMismatch",
            "MissingObjects",
        }

        if any(ind in high_risk_indicators for ind in keys_set):
            return YES

        if indicators_dict:
            return self._("status_possible")

        return NO

    def extract_additional_xmp_ids(self, txt: str) -> dict:
        def _norm(val):
            if val is None:
                return None
            if isinstance(val, (bytes, bytearray)):
                val = val.decode("utf-8", "ignore")
            s = str(val).strip()
            s = re.sub(r"^urn:uuid:", "", s, flags=re.I)
            s = re.sub(r"^(uuid:|xmp\.iid:|xmp\.did:)", "", s, flags=re.I)
            s = s.strip("<>").strip()
            return s.upper() if s else None

        out = {
            "stref_doc_ids": set(),
            "stref_inst_ids": set(),
            "derived_doc_ids": set(),
            "derived_inst_ids": set(),
            "derived_orig_ids": set(),
            "ingredient_doc_ids": set(),
            "ingredient_inst_ids": set(),
            "history_inst_ids": set(),
            "history_doc_ids": set(),
            "ps_doc_ancestors": set(),
        }

        txt_lower = txt.lower()

        if "stref:documentid" in txt_lower:
            for match in re.findall(r'stRef:documentID="([^"]+)"', txt, re.I):
                v = _norm(match);  out["stref_doc_ids"].add(v) if v else None
            for match in re.findall(r"<stRef:documentID>([^<]+)</stRef:documentID>", txt, re.I):
                v = _norm(match);  out["history_doc_ids"].add(v) if v else None

        if "stref:instanceid" in txt_lower:
            for match in re.findall(r'stRef:instanceID="([^"]+)"', txt, re.I):
                v = _norm(match);  out["stref_inst_ids"].add(v) if v else None
            for match in re.findall(r"<stRef:instanceID>([^<]+)</stRef:instanceID>", txt, re.I):
                v = _norm(match);  out["history_inst_ids"].add(v) if v else None

        if "xmpmm:derivedfrom" in txt_lower:
            df = re.search(r"<xmpMM:DerivedFrom\b[^>]*>(.*?)</xmpMM:DerivedFrom>", txt, re.I | re.S)
            if df:
                blk = df.group(1)
                for match in re.findall(r'stRef:documentID="([^"]+)"', blk, re.I):
                    v = _norm(match); out["derived_doc_ids"].add(v) if v else None
                for match in re.findall(r'stRef:instanceID="([^"]+)"', blk, re.I):
                    v = _norm(match); out["derived_inst_ids"].add(v) if v else None
                for match in re.findall(r"<stRef:documentID>([^<]+)</stRef:documentID>", blk, re.I):
                    v = _norm(match); out["derived_doc_ids"].add(v) if v else None
                for match in re.findall(r"<stRef:instanceID>([^<]+)</stRef:instanceID>", blk, re.I):
                    v = _norm(match); out["derived_inst_ids"].add(v) if v else None
                for match in re.findall(r"(?:xmpMM:|)OriginalDocumentID(?:>|=\")([^<\">]+)", blk, re.I):
                    v = _norm(match); out["derived_orig_ids"].add(v) if v else None

        if "xmpmm:ingredients" in txt_lower:
            ing = re.search(r"<xmpMM:Ingredients\b[^>]*>(.*?)</xmpMM:Ingredients>", txt, re.I | re.S)
            if ing:
                blk = ing.group(1)
                for match in re.findall(r'stRef:documentID="([^"]+)"', blk, re.I):
                    v = _norm(match); out["ingredient_doc_ids"].add(v) if v else None
                for match in re.findall(r'stRef:instanceID="([^"]+)"', blk, re.I):
                    v = _norm(match); out["ingredient_inst_ids"].add(v) if v else None
                for match in re.findall(r"<stRef:documentID>([^<]+)</stRef:documentID>", blk, re.I):
                    v = _norm(match); out["ingredient_doc_ids"].add(v) if v else None
                for match in re.findall(r"<stRef:instanceID>([^<]+)</stRef:instanceID>", blk, re.I):
                    v = _norm(match); out["ingredient_inst_ids"].add(v) if v else None

        if "xmpmm:history" in txt_lower:
            hist = re.search(r"<xmpMM:History\b[^>]*>(.*?)</xmpMM:History>", txt, re.I | re.S)
            if hist:
                blk = hist.group(1)
                for match in re.findall(r'(?:InstanceID|stRef:instanceID)="([^"]+)"', blk, re.I):
                    v = _norm(match); out["history_inst_ids"].add(v) if v else None
                for match in re.findall(r'(?:DocumentID|stRef:documentID)="([^"]+)"', blk, re.I):
                    v = _norm(match); out["history_doc_ids"].add(v) if v else None
                for match in re.findall(r"<stRef:instanceID>([^<]+)</stRef:instanceID>", blk, re.I):
                    v = _norm(match); out["history_inst_ids"].add(v) if v else None
                for match in re.findall(r"<stRef:documentID>([^<]+)</stRef:documentID>", blk, re.I):
                    v = _norm(match); out["history_doc_ids"].add(v) if v else None
                for match in re.findall(r"(uuid:[0-9a-f\-]+|xmp\.iid:[^,<>} \]]+|xmp\.did:[^,<>} \]]+)", blk, re.I):
                    v = _norm(match); out["history_inst_ids"].add(v) if v else None

        if "photoshop:documentancestors" in txt_lower:
            ps = re.search(r"<photoshop:DocumentAncestors\b[^>]*>(.*?)</photoshop:DocumentAncestors>", txt, re.I | re.S)
            if ps:
                for match in re.findall(r"<rdf:li[^>]*>([^<]+)</rdf:li>", ps.group(1), re.I):
                    v = _norm(match); out["ps_doc_ancestors"].add(v) if v else None

        for k in out:
            out[k] = {v for v in out[k] if v}

        return out

    def _extract_all_document_ids(self, txt: str, exif_output: str) -> dict:
        def _norm(val):
            if val is None:
                return None
            if isinstance(val, (bytes, bytearray)):
                val = val.decode("utf-8", "ignore")
            s = str(val).strip()
            s = re.sub(r"^urn:uuid:", "", s, flags=re.I)
            s = re.sub(r"^(uuid:|xmp\.iid:|xmp\.did:)", "", s, flags=re.I)
            s = s.strip("<>").strip()
            return s.upper() if s else None

        own_ids = set()
        ref_ids = set()

        txt_lower = txt.lower()

        if "xmpmm:documentid" in txt_lower:
            m = re.search(r'xmpMM:DocumentID(?:>|=")([^<"]+)', txt, re.I)
            if m:
                v = _norm(m.group(1))
                if v: own_ids.add(v)

        if "xmpmm:instanceid" in txt_lower:
            m = re.search(r'xmpMM:InstanceID(?:>|=")([^<"]+)', txt, re.I)
            if m:
                v = _norm(m.group(1))
                if v: own_ids.add(v)

        if "/id" in txt_lower:
            for v1, v2 in re.findall(r"/ID\s*\[\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\]", txt):
                v1, v2 = _norm(v1), _norm(v2)
                if v1: own_ids.add(v1)
                if v2: own_ids.add(v2)

        if "xmpmm:originaldocumentid" in txt_lower:
            m = re.search(r'xmpMM:OriginalDocumentID(?:>|=")([^<"]+)', txt, re.I)
            if m:
                v = _norm(m.group(1))
                if v: ref_ids.add(v)

        if "xmpmm:derivedfrom" in txt_lower:
            df = re.search(r"<xmpMM:DerivedFrom\b[^>]*>(.*?)</xmpMM:DerivedFrom>", txt, re.I | re.S)
            if df:
                blk = df.group(1)
                for match in re.findall(r'stRef:documentID(?:>|=")([^<"]+)', blk, re.I):
                    v = _norm(match)
                    if v: ref_ids.add(v)
                for match in re.findall(r'stRef:instanceID(?:>|=")([^<"]+)', blk, re.I):
                    v = _norm(match)
                    if v: ref_ids.add(v)

        if "xmpmm:ingredients" in txt_lower:
            ing = re.search(r"<xmpMM:Ingredients\b[^>]*>(.*?)</xmpMM:Ingredients>", txt, re.I | re.S)
            if ing:
                blk = ing.group(1)
                for match in re.findall(r'stRef:documentID(?:>|=")([^<"]+)', blk, re.I):
                    v = _norm(match)
                    if v: ref_ids.add(v)

        if "photoshop:documentancestors" in txt_lower:
            ps = re.search(r"<photoshop:DocumentAncestors\b[^>]*>(.*?)</photoshop:DocumentAncestors>", txt, re.I | re.S)
            if ps:
                for match in re.findall(r"<rdf:li[^>]*>([^<]+)</rdf:li>", ps.group(1), re.I):
                    v = _norm(match)
                    if v: ref_ids.add(v)

        if "xmpmm:history" in txt_lower:
            hist = re.search(r"<xmpMM:History\b[^>]*>(.*?)</xmpMM:History>", txt, re.I | re.S)
            if hist:
                blk = hist.group(1)
                for match in re.findall(r'stRef:documentID(?:>|=")([^<"]+)', blk, re.I):
                    v = _norm(match)
                    if v: ref_ids.add(v)

        if exif_output:
            exif_lower = exif_output.lower()
            if "id" in exif_lower:
                for match in re.findall(r"Document\s*ID\s*:\s*(\S+)", exif_output, re.I):
                    v = _norm(match)
                    if v: own_ids.add(v)
                for match in re.findall(r"Instance\s*ID\s*:\s*(\S+)", exif_output, re.I):
                    v = _norm(match)
                    if v: own_ids.add(v)
                for match in re.findall(r"Original\s*Document\s*ID\s*:\s*(\S+)", exif_output, re.I):
                    v = _norm(match)
                    if v: ref_ids.add(v)

        ref_ids = ref_ids - own_ids

        return {
            "own_ids": own_ids,
            "ref_ids": ref_ids
        }

    def _cross_reference_document_ids(self):
        if not self.all_scan_data:
            return

        id_to_owners = {}
        path_to_ids = {}

        for path_str, data in self.all_scan_data.items():
            if data.get("is_revision"):
                continue
            
            doc_ids = data.get("document_ids")
            if not doc_ids:
                continue

            path_to_ids[path_str] = doc_ids
            
            for own_id in doc_ids.get("own_ids", set()):
                if own_id not in id_to_owners:
                    id_to_owners[own_id] = []
                id_to_owners[own_id].append(path_str)

        relationships = {}

        for path_str, doc_ids in path_to_ids.items():
            ref_ids = doc_ids.get("ref_ids", set())
            own_ids = doc_ids.get("own_ids", set())

            for ref_id in ref_ids:
                owners = id_to_owners.get(ref_id, [])
                for owner_path in owners:
                    if owner_path != path_str:
                        if path_str not in relationships:
                            relationships[path_str] = {}
                        if owner_path not in relationships[path_str]:
                            relationships[path_str][owner_path] = "derived_from"

                        if owner_path not in relationships:
                            relationships[owner_path] = {}
                        if path_str not in relationships[owner_path]:
                            relationships[owner_path][path_str] = "parent_of"

            for own_id in own_ids:
                for other_path, other_ids in path_to_ids.items():
                    if other_path == path_str:
                        continue
                    if own_id in other_ids.get("ref_ids", set()):
                        if path_str not in relationships:
                            relationships[path_str] = {}
                        if other_path not in relationships[path_str]:
                            relationships[path_str][other_path] = "parent_of"

        for path_str, related_files in relationships.items():
            if path_str in self.all_scan_data:
                data = self.all_scan_data[path_str]
                if "indicator_keys" not in data:
                    data["indicator_keys"] = {}
                
                related_info = []
                for related_path, rel_type in related_files.items():
                    try:
                        related_name = Path(related_path).name
                    except Exception:
                        related_name = related_path
                    related_info.append({
                        "path": related_path,
                        "name": related_name,
                        "type": rel_type
                    })

                data["indicator_keys"]["RelatedFiles"] = {
                    "count": len(related_files),
                    "files": related_info
                }

        if relationships:
            logging.info(f"Document ID cross-reference found {len(relationships)} files with relationships.")

    def _extract_xmp_relationships(self, xmp_str: str, indicators: dict):
        """Extract and store XMP asset relationship information."""
        if not xmp_str:
            return
            
        manager = XMPRelationshipManager()
        data = manager.parse_xmp(xmp_str)
        
        if data.get('derivation') or data.get('ingredients') or data.get('pantry'):
            indicators['AssetRelationship'] = data
            
            # Also add to related files if possible
            if 'RelatedFiles' not in indicators:
                indicators['RelatedFiles'] = {'count': 0, 'files': []}
            
            # Root derivation
            derivation = data.get('derivation')
            if isinstance(derivation, dict):
                doc_id = derivation.get('documentID')
                if doc_id:
                    # Avoid duplicates
                    if not any(f.get('id') == doc_id for f in indicators['RelatedFiles']['files']):
                        id_str = str(doc_id)
                        short_id = id_str[:8] if len(id_str) >= 8 else id_str
                        indicators['RelatedFiles']['files'].append({
                            'type': 'derived_from',
                            'name': f"ID: {short_id}...",
                            'id': doc_id
                        })
                        indicators['RelatedFiles']['count'] += 1
            
            # Ingredients
            ingredients = data.get('ingredients', [])
            if isinstance(ingredients, list):
                for ing in ingredients:
                    if not isinstance(ing, dict): continue
                    doc_id = ing.get('documentID')
                    if doc_id:
                        # Avoid duplicates
                        if not any(f.get('id') == doc_id for f in indicators['RelatedFiles']['files']):
                            id_str = str(doc_id)
                            short_id = id_str[:8] if len(id_str) >= 8 else id_str
                            indicators['RelatedFiles']['files'].append({
                                'type': 'ingredient',
                                'name': ing.get('filePath') or f"ID: {short_id}...",
                                'id': doc_id
                            })
                            indicators['RelatedFiles']['count'] += 1

    def _extract_touchup_text(self, doc):
        import pikepdf
        import io
        import logging
        import fitz

        page_results = {}
        if not doc or doc.is_closed:
            return page_results

        try:
            try:
                pdf_bytes = doc.tobytes()
                pdf = pikepdf.open(io.BytesIO(pdf_bytes))
            except Exception as e:
                logging.debug(f"Pikepdf open failed for TouchUp masking: {e}")
                return page_results

            with pdf:
                for page_num, page in enumerate(pdf.pages):
                    try:
                        ops = pikepdf.parse_content_stream(page)
                        new_ops = []
                        
                        touchup_stack = [False]
                        mp_flag = False
                        in_flagged_bt = False
                        
                        properties = {}
                        if "/Resources" in page and "/Properties" in page.Resources:
                            properties = page.Resources.Properties

                        for operands, operator in ops:
                            op_name = str(operator)
                            
                            if op_name in ["BDC", "BMC"]:
                                is_touchup = False
                                tag = ""
                                if operands and (isinstance(operands[0], pikepdf.Name) or isinstance(operands[0], str)):
                                    tag = str(operands[0])
                                
                                if "TouchUp" in tag:
                                    is_touchup = True
                                elif properties and operands and operands[0] in properties:
                                    try:
                                        if "TouchUp" in str(properties[operands[0]]):
                                            is_touchup = True
                                    except Exception: pass
                                touchup_stack.append(is_touchup or touchup_stack[-1])
                            
                            elif op_name == "EMC":
                                if len(touchup_stack) > 1:
                                    touchup_stack.pop()
                                in_flagged_bt = False
                                mp_flag = False
                            
                            elif op_name in ["MP", "DP"]:
                                tag = ""
                                if operands and (isinstance(operands[0], pikepdf.Name) or isinstance(operands[0], str)):
                                    tag = str(operands[0])
                                    
                                if "TouchUp" in tag:
                                    mp_flag = True
                                elif properties and operands and operands[0] in properties:
                                    try:
                                        if "TouchUp" in str(properties[operands[0]]):
                                            mp_flag = True
                                    except Exception: pass
                            
                            elif op_name == "BT":
                                if mp_flag:
                                    in_flagged_bt = True
                                    mp_flag = False
                            
                            elif op_name == "ET":
                                in_flagged_bt = False
                            
                            is_inside_touchup = touchup_stack[-1] or in_flagged_bt
                            
                            if not is_inside_touchup and op_name in ["Tj", "TJ", "'", '"']:
                                if op_name == "TJ":
                                    new_list = []
                                    for item in operands[0]:
                                        if isinstance(item, pikepdf.String):
                                            new_list.append(pikepdf.String(" " * len(bytes(item))))
                                        else:
                                            new_list.append(item)
                                    new_ops.append(([new_list], operator))
                                else:
                                    new_ops.append(([pikepdf.String(" " * len(bytes(operands[0])))], operator))
                            else:
                                new_ops.append((operands, operator))

                        page.set_contents(pikepdf.unparse_content_stream(new_ops))
                        
                    except Exception as e:
                        logging.debug(f"Failed to mask page {page_num}: {e}")
                        continue

                out_buf = io.BytesIO()
                pdf.save(out_buf)
                out_buf.seek(0)
                
                with fitz.open(stream=out_buf, filetype="pdf") as masked_doc:
                    for i, masked_page in enumerate(masked_doc):
                        text = masked_page.get_text("text").strip()
                        if text:
                            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                            if lines:
                                page_results[i + 1] = lines
            
            return page_results

        except Exception as e:
            logging.warning(f"Robust TouchUp extraction failed: {e}")
            return {}

    def _get_text_for_comparison(self, source):
        full_text = []
        doc = None
        try:
            if isinstance(source, bytes):
                doc = fitz.open(stream=source, filetype="pdf")
            else:
                resolved_path = self._resolve_case_path(source)
                doc = fitz.open(resolved_path)

            for page in doc:
                full_text.append(page.get_text("text", sort=True))
            return "\n".join(full_text)
        except Exception as e:
            logging.error(f"Robust text extraction failed: {e}")
            return ""
        finally:
            if doc:
                doc.close()

    def _get_touchup_regions_for_page(self, fitz_doc, page_num, touchup_texts):
        regions = []
        if not touchup_texts:
            return regions
            
        try:
            page = fitz_doc.load_page(page_num)
            
            searchable_fragments = []
            
            for text in touchup_texts:
                if not text:
                    continue
                    
                current_fragment = []
                for char in text:
                    if char.isalnum() or char in ' .,:-':
                        current_fragment.append(char)
                    else:
                        if current_fragment:
                            fragment = ''.join(current_fragment).strip()
                            if len(fragment) >= 3 and any(c.isalpha() for c in fragment):
                                searchable_fragments.append(fragment)
                            current_fragment = []
                
                if current_fragment:
                    fragment = ''.join(current_fragment).strip()
                    if len(fragment) >= 3 and any(c.isalpha() for c in fragment):
                        searchable_fragments.append(fragment)
            
            for text in touchup_texts:
                if not text:
                    continue
                import re
                words = re.findall(r'[A-Za-zÀ-ÿ]{3,}', text)
                searchable_fragments.extend(words)
            
            seen = set()
            unique_fragments = []
            for f in searchable_fragments:
                if f.lower() not in seen and len(f) >= 3:
                    seen.add(f.lower())
                    unique_fragments.append(f)
            
            logging.debug(f"TouchUp searchable fragments for page {page_num + 1}: {unique_fragments[:10]}")
            
            for fragment in unique_fragments[:20]:
                try:
                    rects = page.search_for(fragment, quads=False)
                    if rects:
                        regions.extend(rects)
                        logging.debug(f"Found '{fragment}' at {len(rects)} location(s)")
                except Exception as e:
                    logging.debug(f"Search error for '{fragment}': {e}")
                    
        except Exception as e:
            logging.warning(f"Error finding TouchUp regions on page {page_num}: {e}")
        
        return regions

    def analyze_fonts(self, filepath, doc):
        font_subsets = {}
        for page_num in range(len(doc)):
            fonts_on_page = doc.get_page_fonts(page_num)
            for font_info in fonts_on_page:
                basefont_name = font_info[3]
                if "+" in basefont_name:
                    try:
                        _, actual_base_font = basefont_name.split("+", 1)
                        normalized_base = actual_base_font.split('-')[0]
                        if normalized_base not in font_subsets:
                            font_subsets[normalized_base] = set()
                        font_subsets[normalized_base].add(basefont_name)
                    except ValueError:
                        continue
        
        conflicting_fonts = {base: subsets for base, subsets in font_subsets.items() if len(subsets) > 1}
        if conflicting_fonts:
            logging.info(f"Multiple font subsets found in {filepath.name}: {conflicting_fonts}")

        return conflicting_fonts

    @staticmethod
    def decompress_stream(b):
        for fn in (zlib.decompress, lambda d: base64.a85decode(re.sub(rb"\s", b"", d), adobe=True), lambda d: binascii.unhexlify(re.sub(rb"\s|>", b"", d))):
            try:
                return fn(b).decode("latin1", "ignore")
            except Exception:
                pass
        return ""

    @staticmethod
    def extract_text(raw: bytes):
        txt_segments = []

        # ⚡ Bolt Optimization: Use re.findall instead of list(re.finditer)
        # Leveraging C-level list comprehensions bypasses the overhead of
        # generating and iterating over Match objects in Python.
        stream_matches = re.findall(rb"(?s)stream\b(.*?)\bendstream", raw)
        
        found_touchup_marker = False

        for body_raw in stream_matches:
            body = body_raw.strip(b"\r\n ")
            if len(body) <= 500_000:
                try:
                    decompressed = DataProcessingMixin.decompress_stream(body)
                    if decompressed:
                        txt_segments.append(decompressed)
                        if not found_touchup_marker and re.search(r"TouchUp", decompressed, re.I):
                            found_touchup_marker = True
                except Exception:
                    try:
                        decoded = body.decode("latin1", "ignore")
                        txt_segments.append(decoded)
                        if not found_touchup_marker and "TouchUp" in decoded:
                            found_touchup_marker = True
                    except Exception:
                        pass

        txt_segments.append(raw[:1_000_000].decode("latin1", "ignore"))
        if len(raw) > 1_000_000:
            txt_segments.append(raw[-1_000_000:].decode("latin1", "ignore"))

        m = re.search(rb"<\?xpacket begin=.*?\?>(.*?)\<\?xpacket end=[^>]*\?\>", raw, re.S)
        if m:
            try:
                txt_segments.append(m.group(1).decode("utf-8", "ignore"))
            except Exception:
                txt_segments.append(m.group(1).decode("latin1", "ignore"))

        if found_touchup_marker or re.search(rb"touchup_textedit", raw, re.I):
            txt_segments.append("TouchUp_TextEdit")

        return "\n".join(txt_segments)