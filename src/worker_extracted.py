def _add_layer_indicators(raw: bytes, path: Path, indicators: dict):
    """
    Adds indicators for layers:
      - "Has Layers (count)" if OCGs are found.
      - "More Layers Than Pages" if layer count > page count.
    """
    try:
        layers_cnt = count_layers(raw)
    except Exception:
        layers_cnt = 0

    if layers_cnt <= 0:
        return

    indicators['HasLayers'] = {'count': layers_cnt}

    # Compare with page count (best-effort)
    page_count = 0
    try:
        with fitz.open(path) as _doc:
            page_count = _doc.page_count
    except Exception:
        pass

    if page_count and layers_cnt > page_count:
        indicators['MoreLayersThanPages'] = {'layers': layers_cnt, 'pages': page_count}
def extract_revisions(raw, original_path):
    """
    Extracts previous versions (revisions) of a PDF from its raw byte content
    by looking for '%%EOF' markers. It prepares potential paths but does not write files.
    """
    revisions = []
    offsets = []
    pos = len(raw)
    # Find all '%%EOF' markers from the end of the file backwards
    while (pos := raw.rfind(b"%%EOF", 0, pos)) != -1: offsets.append(pos)
    
    # A typical final %%EOF is very close to the end of the file.
    # We want to keep all %%EOF markers EXCEPT the very last one.
    sorted_offsets = sorted(offsets)
    
    # Remove the last offset if it's the actual end of the file (or very close to it)
    if sorted_offsets and sorted_offsets[-1] > len(raw) - 100:
        sorted_offsets.pop()
        
    # Filter out invalid or unlikely offsets
    valid_offsets = [o for o in sorted_offsets if o >= 500]
    
    if valid_offsets:
        # Define the subdirectory for potential revisions
        altered_dir = original_path.parent / "Altered_files"
        if not altered_dir.exists():
            altered_dir.mkdir(parents=True, exist_ok=True)
        
        for offset in valid_offsets:
            # Add 5 bytes to include the '%%EOF' itself
            rev_bytes = raw[:offset + 5]
            
            # Check if this revision can actually be opened by PyMuPDF
            is_valid = False
            try:
                # Try to open the raw bytes as a PDF
                test_doc = fitz.open(stream=rev_bytes, filetype="pdf")
                # If it has at least one page, we consider it valid enough to display
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
                # Package the data for later validation
                revisions.append((rev_path, original_path.name, rev_bytes))
            
    return revisions

def exiftool_output(path, detailed=False):
    """Runs ExifTool safely with a timeout and improved error handling."""

    # --- Security Fix: Secure ExifTool Resolution ---
    exe_path = None
    is_safe_location = False

    # 1. Check Configured Path
    if PDFReconConfig.EXIFTOOL_PATH:
        p = Path(PDFReconConfig.EXIFTOOL_PATH)
        if p.is_file():
            exe_path = p
            is_safe_location = True # User manually configured it

    # 2. Check System Path (if not configured)
    if not exe_path:
        system_path = shutil.which("exiftool")
        if system_path:
            exe_path = Path(system_path)
            is_safe_location = True # System paths are generally trusted

    # 3. Check Bundled Path (if frozen/packaged)
    if not exe_path:
        bundled_path = _resolve_path("exiftool.exe", base_is_parent=False)
        if bundled_path.is_file():
            exe_path = bundled_path
            # If frozen, it's in a temp dir controlled by bootloader => Safe
            if getattr(sys, 'frozen', False):
                is_safe_location = True
            else:
                # Running as script: treat as unsafe unless hash matches
                is_safe_location = False

    # 4. Check Local Path (External/Portable)
    if not exe_path:
        local_path = _resolve_path("exiftool.exe", base_is_parent=True)
        if local_path.is_file():
            exe_path = local_path
            is_safe_location = False # Definitely unsafe (next to exe)

    # 5. Not Found
    if not exe_path:
        return _("exif_err_notfound")

    # --- Integrity Check ---
    # Calculate Hash if configured OR if location is unsafe
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
        # Suppress console window on Windows
        startupinfo = None
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
        # Build the command-line arguments for ExifTool
        command = [str(exe_path)]
        if detailed: command.extend(["-a", "-u", "-s", "-G1", "-struct"])
        else: command.extend(["-a", "-u", "-s", "-G1"])
        command.append("-") # Read from stdin

        # Run the process
        process = subprocess.run(
            command,
            input=file_content,
            capture_output=True,
            check=False,
            startupinfo=startupinfo,
            timeout=PDFReconConfig.EXIFTOOL_TIMEOUT
        )
        
        # Handle non-zero exit codes or stderr output
        if process.returncode != 0 or process.stderr:
            error_message = process.stderr.decode('latin-1', 'ignore').strip()
            if not process.stdout.strip(): return f"{_('exif_err_prefix')}\n{error_message}"
            logging.warning(f"ExifTool stderr for {path.name}: {error_message}")

        # Decode the output, trying UTF-8 first, then latin-1 as a fallback
        try: raw_output = process.stdout.decode('utf-8').strip()
        except UnicodeDecodeError: raw_output = process.stdout.decode('latin-1', 'ignore').strip()

        # Remove empty lines from the output
        return "\n".join([line for line in raw_output.splitlines() if line.strip()])

    except subprocess.TimeoutExpired:
        logging.error(f"ExifTool timed out for file {path.name}")
        return _("exif_err_prefix") + f"\nTimeout after {PDFReconConfig.EXIFTOOL_TIMEOUT} seconds."
    except Exception as e:
        logging.error(f"Error running exiftool for file {path}: {e}")
        return _("exif_err_run").format(e=e)

def _parse_exif_data(exiftool_output: str):
    """
    Parses EXIFTool output into a structured dictionary for reuse.
    """
    data = {
        "producer_pdf": "", "producer_xmppdf": "", "softwareagent": "",
        "application": "", "software": "", "creatortool": "", "xmptoolkit": "",
        "create_dt": None, "modify_dt": None, "history_events": [], "all_dates": []
    }
    lines = exiftool_output.splitlines()

    # --- Regex Patterns (reuse module-level constants) ---
    history_pattern = re.compile(r"\[XMP-xmpMM\]\s+History\s+:\s+(.*)")

    def looks_like_software(s: str) -> bool:
        return bool(s and software_tokens.search(s))

    # --- First Pass: Collect Key-Value Pairs for Tools ---
    for ln in lines:
        m = KV_PATTERN.match(ln)
        if not m: 
            continue
        
        group = m.group("group").strip().lower()
        tag = m.group("tag").strip().lower().replace(" ", "")
        val = m.group("value").strip()

        # Map tags to data dictionary keys for software detection
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
    
    # Fallback for producer fields
    if not data["producer_pdf"] and data["producer_xmppdf"]: 
        data["producer_pdf"] = data["producer_xmppdf"]
    if not data["producer_xmppdf"] and data["producer_pdf"]: 
        data["producer_xmppdf"] = data["producer_pdf"]

    # --- Second Pass: Collect All Dates and History Events ---
    for ln in lines:
        # History events
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

        # Generic date lines
        kv_match = KV_PATTERN.match(ln)
        if not kv_match: 
            continue

        val_str = kv_match.group("value").strip()
        match = DATE_TZ_PATTERN.match(val_str)
        
        if match:
            parts = match.groupdict()
            # Massage date into ISO format: YYYY-MM-DDTHH:MM:SS
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
    
    # Find first create date and latest modify date
    for d in data["all_dates"]:
        if d["tag"] in {"createdate", "creationdate"}:
            if data["create_dt"] is None or d["dt"] < data["create_dt"]:
                data["create_dt"] = d["dt"]
        elif d["tag"] in {"modifydate", "metadatadate"}:
            if data["modify_dt"] is None or d["dt"] > data["modify_dt"]:
                data["modify_dt"] = d["dt"]
    
    return data
    
def _detect_tool_change_from_exif(exiftool_output: str, parsed_data=None):
    """
    Determines if the primary tool changed between creation and last modification.
    This function is now a lightweight wrapper around _parse_exif_data.
    """
    data = parsed_data if parsed_data else _parse_exif_data(exiftool_output)
    
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

def _parse_exiftool_timeline(exiftool_output, parsed_data=None):
    """
    Generates a list of timeline events from parsed EXIF data.
    """
    events = []
    data = parsed_data if parsed_data else _parse_exif_data(exiftool_output)

    create_tool = data["producer_pdf"] or data["producer_xmppdf"] or data["application"] or data["software"] or data["creatortool"] or ""
    modify_tool = data["softwareagent"] or create_tool # Fallback to create_tool if no specific modify tool

    # --- Add History Events ---
    for dt_obj, details in data["history_events"]:
        action = details.get('Action', 'N/A')
        agent = details.get('SoftwareAgent', '')
        changed = details.get('Changed', '')
        desc = [f"Action: {action}"]
        if agent: desc.append(f"Agent: {agent}")
        if changed: desc.append(f"Changed: {changed}")
        events.append((dt_obj, f"XMP History   - {' | '.join(desc)}"))

    # --- Add Generic Date Events ---
    def _ts_label(tag: str) -> str:
        t = tag.replace(" ", "").lower()
        return {"createdate": "Created", "creationdate": "Created", "modifydate": "Modified", "metadatadate": "Metadata"}.get(t, tag)

    for d in data["all_dates"]:
        label = _(_ts_label(d["tag"]).lower())
        tool = create_tool if d["tag"] in {"createdate", "creationdate"} else modify_tool
        tool_part = f" | Tool: {tool}" if tool else ""
        events.append((d["dt"], f"ExifTool ({d['group']}) - {label}: {d['full_str']}{tool_part}"))
    
    # --- Add XMP Engine Information ---
    if data["xmptoolkit"]:
        anchor_dt = data["create_dt"] or (data["all_dates"][0]["dt"] if data["all_dates"] else datetime.now())
        label_engine = "XMP Engine" if language == "en" else "XMP-motor"
        events.append((anchor_dt, f"{label_engine}: {data['xmptoolkit']}"))

    return events
    
def generate_comprehensive_timeline(filepath, raw_file_content, exiftool_output, parsed_exif_data=None):
    """
    Combines events from all sources, separating them into timezone-aware and naive lists.
    """
    all_events = []

    if parsed_exif_data is None:
        parsed_exif_data = _parse_exif_data(exiftool_output)

    # 1) Get File System, ExifTool, and Raw Content timestamps
    all_events.extend(_get_filesystem_times(filepath))
    all_events.extend(_parse_exiftool_timeline(exiftool_output, parsed_data=parsed_exif_data))
    all_events.extend(_parse_raw_content_timeline(raw_file_content))

    # 2) Add a special event if a tool change was detected
    try:
        info = _detect_tool_change_from_exif(exiftool_output, parsed_data=parsed_exif_data)
        if info.get("changed"):
            when = info.get("modify_dt")
            if not when and all_events:
                # Find a datetime object to anchor the event, prioritizing naive ones if present
                naive_dts = [e[0] for e in all_events if e[0].tzinfo is None]
                when = max(naive_dts) if naive_dts else max(e[0] for e in all_events)
            if not when:
                when = datetime.now()
            
            # Format the description of the tool change
            if language == "da":
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

    # 3) Separate events into two lists based on timezone info
    aware_events = []
    naive_events = []
    for dt_obj, description in all_events:
        if dt_obj.tzinfo is not None:
            aware_events.append((dt_obj, description))
        else:
            naive_events.append((dt_obj, description))

    # 4) Sort each list independently
    aware_events.sort(key=lambda x: x[0])
    naive_events.sort(key=lambda x: x[0])

    return {"aware": aware_events, "naive": naive_events}

def analyze_fonts(filepath, doc):
        """
        Analyzes fonts to detect multiple subsets of the same base font.
        Returns a dictionary of conflicting fonts, e.g.,
        {'Calibri': {'ABC+Calibri', 'DEF+Calibri-Bold'}}
        """
        font_subsets = {}
        # Iterate through each page to get the fonts used
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
        
        # Filter for only those fonts that actually have multiple subsets
        conflicting_fonts = {base: subsets for base, subsets in font_subsets.items() if len(subsets) > 1}
        if conflicting_fonts:
            logging.info(f"Multiple font subsets found in {filepath.name}: {conflicting_fonts}")

        return conflicting_fonts

def _extract_touchup_text(doc):
    """
    Extracts text from elements marked with TouchUp_TextEdit.
    Uses a 'Masking' strategy: creates a copy of the PDF, masks all non-TouchUp text
    using pikepdf, and then extracts the remaining (correctly decoded) text using fitz.
    This ensures CID-encoded fonts (common in TouchUp edits) are correctly translated.
    """
    import pikepdf
    import io
    import logging
    import fitz

    page_results = {}
    if not doc or doc.is_closed:
        return page_results

    try:
        # 1. Open a copy of the PDF using pikepdf for surgical masking
        try:
            # Use tobytes() to ensure we have the most recent state in memory
            pdf_bytes = doc.tobytes()
            pdf = pikepdf.open(io.BytesIO(pdf_bytes))
        except Exception as e:
            logging.debug(f"Pikepdf open failed for TouchUp masking: {e}")
            return page_results

        with pdf:
            for page_num, page in enumerate(pdf.pages):
                try:
                    # Parse the content stream
                    ops = pikepdf.parse_content_stream(page)
                    new_ops = []
                    
                    touchup_stack = [False]
                    mp_flag = False
                    in_flagged_bt = False
                    
                    # Find Marked Content properties for tag lookup
                    properties = {}
                    if "/Resources" in page and "/Properties" in page.Resources:
                        properties = page.Resources.Properties

                    for operands, operator in ops:
                        op_name = str(operator)
                        
                        # Track TouchUp scope (BDC / BMC)
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
                        
                        # Handle Marked Points (MP / DP)
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
                        
                        # Determine if current operator should be masked
                        is_inside_touchup = touchup_stack[-1] or in_flagged_bt
                        
                        if not is_inside_touchup and op_name in ["Tj", "TJ", "'", '"']:
                            # Mask non-TouchUp text by replacing it with spaces
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
                            # Keep original operator
                            new_ops.append((operands, operator))

                    # Apply modified stream to the page
                    page.set_contents(pikepdf.unparse_content_stream(new_ops))
                    
                except Exception as e:
                    logging.debug(f"Failed to mask page {page_num}: {e}")
                    continue

            # 2. Save modified PDF to buffer and use fitz to decode remaining text
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


def _get_text_for_comparison(source):
    """
    Performs a robust, layout-preserving text extraction on a PDF.
    Source can be bytes, a string path, or a Path object.
    """
    full_text = []
    doc = None
    try:
        if isinstance(source, bytes):
            doc = fitz.open(stream=source, filetype="pdf")
        else:
            resolved_path = _resolve_case_path(source) # Resolve the path
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
    
        
