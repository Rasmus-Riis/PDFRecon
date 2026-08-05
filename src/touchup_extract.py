"""
TouchUp Text Extraction and Decoding

One implementation, used by every scan path.

This code previously existed twice - once as a method on
:class:`~src.data_processing.DataProcessingMixin` for the in-process scan and
once inlined in :mod:`src.scan_worker` for the worker-pool and CLI scans. The
copies drifted: fixes applied to one silently did not reach the other, so the
same file could yield different TouchUp text depending on which path scanned
it. Both now delegate here.

Extraction works by masking everything *outside* a TouchUp marked-content
region and letting PyMuPDF extract what remains, which handles layout and
line breaks. That path decodes through the font's ToUnicode CMap, so it
produces garbled output when the CMap is missing or incomplete. With
``capture_runs=True`` the raw string operands and the font in effect are
collected during the same walk, so :mod:`src.cid_decoder` can recover the
text by other means.
"""

from __future__ import annotations

import io
import logging

import fitz


def extract_touchup_text(doc, capture_runs: bool = False):
    """
    Extract the text inside TouchUp-marked content.

    Returns ``page_results`` normally, or ``(page_results, runs, pdf_bytes)``
    when *capture_runs* is set, where *runs* are dicts carrying the page, the
    font resource name, the operator and the raw encoded bytes.
    """
    import pikepdf

    page_results: dict = {}
    captured_runs: list = []
    pdf_bytes = None
    if not doc or doc.is_closed:
        return (page_results, captured_runs, pdf_bytes) if capture_runs else page_results

    try:
        try:
            pdf_bytes = doc.tobytes()
            pdf = pikepdf.open(io.BytesIO(pdf_bytes))
        except Exception as e:
            logging.debug(f"Pikepdf open failed for TouchUp masking: {e}")
            return (page_results, captured_runs, pdf_bytes) if capture_runs else page_results

        with pdf:
            for page_num, page in enumerate(pdf.pages):
                try:
                    ops = pikepdf.parse_content_stream(page)
                    new_ops = []

                    touchup_stack = [False]
                    mp_flag = False
                    in_flagged_bt = False
                    current_font = None

                    properties = {}
                    if "/Resources" in page and "/Properties" in page.Resources:
                        properties = page.Resources.Properties

                    for operands, operator in ops:
                        op_name = str(operator)

                        # Track the selected font so a captured run can be
                        # tied back to the font dictionary that encodes it.
                        if capture_runs and op_name == "Tf" and operands:
                            try:
                                name = str(operands[0])
                                current_font = name[1:] if name.startswith("/") else name
                            except Exception:
                                current_font = None

                        # Set literals give O(1) operator lookups in this hot loop.
                        if op_name in {"BDC", "BMC"}:
                            is_touchup = False
                            tag = ""
                            if operands and (isinstance(operands[0], pikepdf.Name) or isinstance(operands[0], str)):
                                tag = str(operands[0])

                            if "TouchUp" in tag:
                                is_touchup = True
                            else:
                                # "tag properties BDC" - the property name is
                                # the second operand, not the tag. Looking up
                                # the tag instead missed every region marked
                                # indirectly through /Properties.
                                prop_key = operands[1] if len(operands) > 1 else None
                                if properties and prop_key is not None:
                                    try:
                                        if prop_key in properties and "TouchUp" in str(properties[prop_key]):
                                            is_touchup = True
                                    except Exception:
                                        pass
                            touchup_stack.append(is_touchup or touchup_stack[-1])

                        elif op_name == "EMC":
                            if len(touchup_stack) > 1:
                                touchup_stack.pop()
                            in_flagged_bt = False
                            mp_flag = False

                        elif op_name in {"MP", "DP"}:
                            tag = ""
                            if operands and (isinstance(operands[0], pikepdf.Name) or isinstance(operands[0], str)):
                                tag = str(operands[0])

                            if "TouchUp" in tag:
                                mp_flag = True
                            else:
                                # "tag properties DP" - same operand order as BDC.
                                prop_key = operands[1] if len(operands) > 1 else None
                                if properties and prop_key is not None:
                                    try:
                                        if prop_key in properties and "TouchUp" in str(properties[prop_key]):
                                            mp_flag = True
                                    except Exception:
                                        pass

                        elif op_name == "BT":
                            if mp_flag:
                                in_flagged_bt = True
                                mp_flag = False

                        elif op_name == "ET":
                            in_flagged_bt = False

                        is_inside_touchup = touchup_stack[-1] or in_flagged_bt

                        if not is_inside_touchup and op_name in {"Tj", "TJ", "'", '"'}:
                            # Drop the text rather than overwrite it with
                            # spaces. Substituting an equal number of 0x20
                            # bytes only blanks single-byte encodings; in a
                            # two-byte Identity-H font - exactly the kind the
                            # decoder exists for - the pair 0x20 0x20 is
                            # character code 0x2020, which renders as a
                            # dagger, so masked text came back as strings of
                            # daggers.
                            #
                            # The quote operators also advance to the next
                            # line, so they become T* to keep the line
                            # structure of what remains.
                            if op_name in {"'", '"'}:
                                new_ops.append(([], pikepdf.Operator("T*")))
                        else:
                            if capture_runs and is_inside_touchup and op_name in {"Tj", "TJ", "'", '"'}:
                                _capture_run(captured_runs, pikepdf, page_num,
                                             current_font, op_name, operands)
                            new_ops.append((operands, operator))

                    # pikepdf.Page has no set_contents(); assigning /Contents
                    # through the page object is the supported way to replace
                    # a content stream. Calling a method that does not exist
                    # raised AttributeError into the handler below, which
                    # meant masking silently never happened and this function
                    # returned the whole page's text.
                    page.Contents = pdf.make_stream(
                        pikepdf.unparse_content_stream(new_ops))

                except Exception as e:
                    logging.warning(
                        f"Failed to mask page {page_num + 1} for TouchUp "
                        f"extraction; its text is reported unmasked: {e}")
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

        return (page_results, captured_runs, pdf_bytes) if capture_runs else page_results

    except Exception as e:
        logging.warning(f"Robust TouchUp extraction failed: {e}")
        return ({}, captured_runs, pdf_bytes) if capture_runs else {}


def _capture_run(captured_runs, pikepdf, page_num, font_resource, op_name, operands):
    """
    Record one text-showing operator found inside a TouchUp region.

    The raw operand bytes are kept exactly as they appear in the content
    stream, because they are the evidence the decoder works from. A ``TJ``
    array's string elements are concatenated: the numbers between them are
    kerning adjustments, not content, and the strings together form one
    readable run.
    """
    try:
        fragments = []
        if op_name == "TJ":
            if not operands:
                return
            for item in operands[0]:
                if isinstance(item, pikepdf.String):
                    fragments.append(bytes(item))
        elif op_name == '"':
            # aw ac string "  -- the string is the third operand
            if len(operands) >= 3 and isinstance(operands[2], pikepdf.String):
                fragments.append(bytes(operands[2]))
        else:  # Tj and '
            if operands and isinstance(operands[0], pikepdf.String):
                fragments.append(bytes(operands[0]))

        encoded = b"".join(fragments)
        if not encoded:
            return

        captured_runs.append({
            "page": page_num + 1,
            "index": len(captured_runs),
            "font_resource": font_resource,
            "operator": op_name,
            "encoded": encoded,
        })
    except Exception as exc:
        logging.debug(f"Could not capture TouchUp run on page {page_num + 1}: {exc}")


def decode_touchup_runs(captured_runs, pdf_bytes):
    """
    Decode captured TouchUp runs with the tiered CID decoder.

    Returns ``(decoded, custody)`` where *decoded* is a list of records
    carrying the text, method, confidence, evidence and alternatives for each
    run, and *custody* summarises which tiers ran and the hashes of the tables
    and fonts involved.

    Runs whose font cannot be located are still reported, with the reason,
    rather than dropped: an examiner needs to know a run existed even when it
    could not be decoded. Any failure here leaves the extracted text
    untouched.
    """
    if not captured_runs or not pdf_bytes:
        return [], None

    try:
        from .cid_decoder import DecoderCache, DecoderSettings, decode, summarise_for_custody
    except ImportError as exc:
        logging.warning(f"CID decoder unavailable: {exc}")
        return [], None

    settings = DecoderSettings.from_config()
    if not settings.enabled:
        return [], None

    decoded = []
    results = []
    doc = None
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")

        # Map each page's font resource names to their xrefs. The xrefs come
        # from the same byte stream the runs were captured from, and PyMuPDF's
        # tobytes() preserves the original numbering, so they match what an
        # examiner sees opening the file itself.
        fonts_by_page = {}
        for page_num in range(len(doc)):
            mapping = {}
            try:
                for info in doc[page_num].get_fonts(full=True):
                    mapping[info[4]] = info[0]
            except Exception as exc:
                logging.debug(f"Could not list fonts on page {page_num + 1}: {exc}")
            fonts_by_page[page_num + 1] = mapping

        with DecoderCache(pdf_bytes=pdf_bytes, settings=settings) as cache:
            for run in captured_runs:
                resource = run.get("font_resource")
                xref = fonts_by_page.get(run["page"], {}).get(resource)
                if xref is None:
                    decoded.append({
                        "page": run["page"],
                        "index": run["index"],
                        "font_resource": resource,
                        "encoded_hex": run["encoded"].hex().upper(),
                        "text": None,
                        "method": "unavailable",
                        "confidence": "SPECULATIVE",
                        "error": (
                            f"font resource /{resource} not found among the "
                            f"fonts of page {run['page']}"),
                    })
                    continue
                try:
                    result = decode(doc, xref, run["encoded"], cache=cache,
                                    resource_name=resource or "")
                except Exception as exc:
                    logging.warning(
                        f"CID decoding failed on page {run['page']}: {exc}")
                    decoded.append({
                        "page": run["page"],
                        "index": run["index"],
                        "font_resource": resource,
                        "encoded_hex": run["encoded"].hex().upper(),
                        "text": None,
                        "method": "error",
                        "confidence": "SPECULATIVE",
                        "error": str(exc),
                    })
                    continue

                results.append(result)
                record = result.as_dict()
                record.update({
                    "page": run["page"],
                    "index": run["index"],
                    "font_resource": resource,
                    "font_xref": xref,
                })
                decoded.append(record)
    except Exception as exc:
        logging.warning(f"TouchUp decoding pass failed: {exc}")
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass

    custody = summarise_for_custody(results) if results else None
    return decoded, custody


def extract_and_decode(doc):
    """
    Extract TouchUp text and decode it in one call.

    Convenience for scan paths that want both, returning
    ``(page_results, decoded_runs, decode_custody)``.
    """
    page_results, captured, pdf_bytes = extract_touchup_text(doc, capture_runs=True)
    decoded, custody = decode_touchup_runs(captured, pdf_bytes)
    return page_results, decoded, custody
