"""
Exporter Module

Handles report generation and file export functionality (Excel, CSV, JSON, HTML).
Extracts all export methods from PDFReconApp for modular architecture.
Phase 5b: Complete exporter extraction with all methods.
"""

import logging
import json
import csv
import html as html_escape_module
from pathlib import Path
from datetime import datetime
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill

from .config import UI_COLORS, XML_CONTROL_RE
from . import cid_report


# --- CID text decoding ------------------------------------------------------
# Three columns are appended to every tabular export. They are appended rather
# than inserted so existing column indices, which the row-building code uses
# positionally, keep working.
CID_COLUMN_KEYS = ["cid_col_decoded_text", "cid_col_method", "cid_col_confidence"]


def decoded_runs_for_path(all_scan_data: dict, path_str: str) -> list:
    """The decoded TouchUp runs recorded for a file, if any."""
    record = all_scan_data.get(path_str) if all_scan_data else None
    if not record:
        return []
    touchup = (record.get("indicator_keys") or {}).get("TouchUp_TextEdit") or {}
    return touchup.get("decoded_runs") or []


def cid_columns_for_path(all_scan_data: dict, path_str: str) -> list:
    """
    The three decoding cells for one file: text, method, confidence.

    The text cells carry their own confidence prefix as well, so a reading
    copied out of a single cell cannot lose its label.
    """
    runs = decoded_runs_for_path(all_scan_data, path_str)
    if not runs:
        return ["", "", ""]
    texts = "\n".join(
        f"[p{r.get('page')}] {cid_report.labelled_text(r)}" for r in runs)
    methods = ", ".join(sorted({cid_report.method_of(r) for r in runs}))
    return [texts, methods, cid_report.weakest_confidence(runs) or ""]


def cid_headers(get_translation=None) -> list:
    if get_translation:
        return [get_translation(key) for key in CID_COLUMN_KEYS]
    return ["Decoded Text", "Decoding Method", "Decoding Confidence"]


def clean_cell_value(value):
    """
    Removes control characters and invalid XML characters from cell values.
    Handles mojibake, BOM characters, and XML control characters.
    
    Args:
        value: Cell value to clean
        
    Returns:
        str: Cleaned cell value
    """
    if value is None:
        return ""
    s = str(value)
    # ⚡ Bolt Optimization: Use pre-compiled regex for stripping invalid XML chars instead of compiling inline per cell
    # Remove illegal XML control characters (allow \t \n \r)
    s = XML_CONTROL_RE.sub("", s)
    # Remove BOM characters
    if s.startswith("\ufeff") or s.startswith("\ufffe") or s.startswith("\xef\xbb\xbf"):
        s = s.lstrip("\ufeff\ufffe")
        if s.startswith("\xef\xbb\xbf"):
            s = s[3:]
    # Remove mojibake
    if s.startswith("þÿ") or s.startswith("ÿþ"):
        s = s[2:]
    s = s.replace("\x00", "")
    return s


def format_indicator_details(key: str, details: dict) -> str:
    """
    Formats indicator details as a human-readable string.
    Handles different indicator types and their specific data.
    
    Args:
        key: Indicator name
        details: Indicator details dictionary
        
    Returns:
        str: Formatted indicator string
    """
    if not details:
        return key
    
    if isinstance(details, dict):
        # Handle count-based indicators
        if 'count' in details:
            return f"{key} ({details['count']})"
        # Handle text-based indicators
        if 'text' in details:
            return f"{key}: {details['text'][:50]}..."
        # Handle font indicators
        if 'fonts' in details:
            font_count = len(details['fonts'])
            return f"{key} ({font_count} fonts)"
        # Handle list indicators
        if 'items' in details and isinstance(details['items'], list):
            return f"{key} ({len(details['items'])} items)"
    
    return key


def export_to_excel(file_path, report_data: list, all_scan_data: dict, file_annotations: dict, 
                   exif_outputs: dict, column_keys: list, get_translation=None):
    """
    Exports the displayed data to XLSX with a frozen header and word wrap enabled.
    Includes all indicators, EXIF data, and annotations.
    
    Args:
        file_path: Output file path
        report_data: List of result rows to export
        all_scan_data: Dictionary of all scan data
        file_annotations: Dictionary of file notes
        exif_outputs: Dictionary of EXIF outputs
        column_keys: List of column translation keys
        get_translation: Function to translate column keys (optional)
    """
    try:
        logging.info(f"Exporting report to Excel file: {file_path}")

        wb = Workbook()
        ws = wb.active
        ws.title = "PDFRecon Results"

        # Use translation function if provided, otherwise use raw keys
        if get_translation:
            headers = [get_translation(key) for key in column_keys]
        else:
            headers = column_keys
        
        if len(headers) >= 10:
            headers[9] = f"{headers[9] if get_translation else 'Indicators'} (Overview)"

        base_column_count = len(headers)
        headers = headers + cid_headers(get_translation)

        for col_num, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_num, value=clean_cell_value(header))
            cell.font = Font(bold=True)
            cell.fill = PatternFill(start_color="DDDDDD", end_color="DDDDDD", fill_type="solid")
            cell.alignment = Alignment(wrap_text=True, horizontal="center", vertical="center")
        
        ws.freeze_panes = 'A2'

        # Create a lookup dictionary once to avoid repeated searches (optimization)
        indicators_by_path = {}
        for item in all_scan_data.values():
            path_str = str(item.get("path"))
            indicator_dict = item.get("indicator_keys") or {}
            if indicator_dict:
                lines = [format_indicator_details(key, details) for key, details in indicator_dict.items()]
                indicators_by_path[path_str] = "• " + "\n• ".join(lines)
            else:
                indicators_by_path[path_str] = ""

        # ⚡ Bolt Optimization: Cache alignment instance and dictionary lookups to avoid instantiation/lookup overhead in inner loop
        default_alignment = Alignment(wrap_text=True, vertical="top")
        exif_get = exif_outputs.get
        ind_get = indicators_by_path.get
        note_get = file_annotations.get

        for row_idx, row_data in enumerate(report_data, start=2):
            try:
                path = row_data[4]  # Path is at index 4
            except IndexError:
                path = ""

            exif_text = exif_get(path, "")
            indicators_full = ind_get(path, "")
            note_text = note_get(path, "")

            row_out = list(row_data)

            while len(row_out) < base_column_count:
                row_out.append("")

            row_out[8] = exif_text         # EXIF is at index 8
            if indicators_full:
                row_out[9] = indicators_full # Indicators is at index 9
            row_out[10] = note_text        # Note is at index 10

            row_out = row_out[:base_column_count] + cid_columns_for_path(all_scan_data, path)

            for col_idx, value in enumerate(row_out, start=1):
                cell = ws.cell(row=row_idx, column=col_idx, value=clean_cell_value(value))
                cell.alignment = default_alignment

        for col in ws.columns:
            try:
                max_len = max(len(str(c.value).split('\n')[0]) for c in col if c.value)
                ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 60)
            except (ValueError, TypeError):
                pass

        _add_decoding_sheet(wb, all_scan_data)

        wb.save(file_path)
        logging.info(f"Excel export completed: {file_path}")
        
    except Exception as e:
        logging.error(f"Error exporting to Excel: {e}")
        raise


def _add_decoding_sheet(wb, all_scan_data: dict) -> None:
    """
    Add a worksheet with one row per decoded text run.

    The summary columns on the main sheet answer "was anything decoded, and
    how sure is it". This sheet carries what an examiner needs to check the
    answer: the raw operand, the font and its hash, the tiers that ran, the
    reference font and the alternative readings.
    """
    rows = []
    for record in (all_scan_data or {}).values():
        path_str = str(record.get("path", ""))
        for row in cid_report.export_rows(decoded_runs_for_path(all_scan_data, path_str)):
            rows.append((path_str, row))

    if not rows:
        return

    ws = wb.create_sheet("Text Decoding")
    headers = ["File"] + [title for _key, title in cid_report.EXPORT_COLUMNS]
    for col_num, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_num, value=clean_cell_value(header))
        cell.font = Font(bold=True)
        cell.fill = PatternFill(start_color="DDDDDD", end_color="DDDDDD",
                                fill_type="solid")
        cell.alignment = Alignment(wrap_text=True, horizontal="center",
                                   vertical="center")
    ws.freeze_panes = "A2"

    alignment = Alignment(wrap_text=True, vertical="top")
    for row_idx, (path_str, row) in enumerate(rows, start=2):
        values = [path_str] + [row.get(key, "") for key, _title in cid_report.EXPORT_COLUMNS]
        for col_idx, value in enumerate(values, start=1):
            cell = ws.cell(row=row_idx, column=col_idx,
                           value=clean_cell_value(value))
            cell.alignment = alignment

    for col in ws.columns:
        try:
            max_len = max(len(str(c.value).split("\n")[0]) for c in col if c.value)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 60)
        except (ValueError, TypeError):
            pass


def export_to_csv(file_path, report_data: list, all_scan_data: dict, file_annotations: dict,
                 exif_outputs: dict, column_keys: list, get_translation=None):
    """
    Exports the displayed data to a CSV file with EXIF and indicator data.
    
    Args:
        file_path: Output file path
        report_data: List of result rows to export
        all_scan_data: Dictionary of all scan data
        file_annotations: Dictionary of file notes
        exif_outputs: Dictionary of EXIF outputs
        column_keys: List of column translation keys
        get_translation: Function to translate column keys (optional)
    """
    try:
        # Use translation function if provided
        if get_translation:
            headers = [get_translation(key) for key in column_keys]
        else:
            headers = column_keys
        
        def _indicators_for_path(path_str: str) -> str:
            """Helper function to get a semicolon-separated string of indicators."""
            rec = all_scan_data.get(path_str)
            if not rec:
                return ""
            indicator_dict = rec.get('indicator_keys') or {}
            if not indicator_dict:
                return ""
            lines = [format_indicator_details(key, details) for key, details in indicator_dict.items()]
            return "; ".join(lines)

        # Prepare data with full EXIF output + full indicators
        data_for_export = []

        # ⚡ Bolt Optimization: Cache dictionary lookups outside the loop
        exif_get = exif_outputs.get
        note_get = file_annotations.get

        base_column_count = len(headers)
        headers = headers + cid_headers(get_translation)

        for row_data in report_data:
            new_row = list(row_data)
            path = new_row[4]  # Path is at index 4
            exif_output = exif_get(path, "")
            indicators_full = _indicators_for_path(path)
            note_text = note_get(path, "")

            while len(new_row) < base_column_count:
                new_row.append("")

            new_row[8] = exif_output      # EXIF is at index 8
            if indicators_full:
                new_row[9] = indicators_full # Indicators is at index 9
            new_row[10] = note_text       # Note is at index 10

            new_row = new_row[:base_column_count] + cid_columns_for_path(all_scan_data, path)
            data_for_export.append(new_row)

        # Use utf-8-sig for better Excel compatibility with special characters
        with open(file_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(data_for_export)
        
        logging.info(f"CSV export completed: {file_path}")
        
    except Exception as e:
        logging.error(f"Error exporting to CSV: {e}")
        raise


def export_to_json(file_path, all_scan_data: dict, file_annotations: dict, exif_outputs: dict):
    """
    Exports a more detailed report of all scanned data and notes to a JSON file.
    Includes indicator details, EXIF data, and annotations.
    
    Args:
        file_path: Output file path
        all_scan_data: Dictionary of all scan data
        file_annotations: Dictionary of file notes
        exif_outputs: Dictionary of EXIF outputs
    """
    try:
        scan_data_export = []
        for item in all_scan_data.values():
            path_str = str(item['path'])
            item_copy = item.copy()
            item_copy['path'] = path_str  # Convert Path object to string
            if 'original_path' in item_copy:
                item_copy['original_path'] = str(item_copy['original_path'])
            
            if 'indicator_keys' in item_copy:
                serializable_indicators = {}
                for key, details in item_copy['indicator_keys'].items():
                    if 'fonts' in details:
                        serializable_details = details.copy()
                        serializable_details['fonts'] = {k: list(v) for k, v in details['fonts'].items()}
                        serializable_indicators[key] = serializable_details
                    else:
                        serializable_indicators[key] = details
                item_copy['indicator_keys'] = serializable_indicators

            item_copy['exif_data'] = exif_outputs.get(path_str, "")

            # Surface decoding at the top level of the record. The full
            # evidence is already inside indicator_keys, but a consumer should
            # not have to know that a decoded reading lives under a TouchUp
            # indicator in order to find its confidence.
            runs = decoded_runs_for_path(all_scan_data, path_str)
            if runs:
                item_copy['text_decoding'] = {
                    'summary': cid_report.summarise(runs),
                    'runs': runs,
                }

            scan_data_export.append(item_copy)

        full_export_payload = {
            'scan_results': scan_data_export,
            'file_annotations': file_annotations
        }
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(full_export_payload, f, indent=4, default=str)
        
        logging.info(f"JSON export completed: {file_path}")
            
    except Exception as e:
        logging.error(f"Error exporting to JSON: {e}")
        raise


def export_to_html(file_path, report_data: list, file_annotations: dict, all_scan_data: dict,
                  column_keys: list, tree_get_children=None, tree_item=None, tag_map=None, get_translation=None):
    """
    Exports a simple, color-coded HTML report with indicators and notes.
    
    Args:
        file_path: Output file path
        report_data: List of result rows to export
        file_annotations: Dictionary of file notes
        all_scan_data: Dictionary of all scan data
        column_keys: List of column translation keys
        tree_get_children: Function to get tree children (optional)
        tree_item: Function to get tree item values (optional)
        tag_map: Dictionary mapping tag names to CSS classes (optional)
        get_translation: Function to translate column keys (optional)
    """
    try:
        # Use translation function if provided
        if get_translation:
            headers_list = [get_translation(key) for key in column_keys]
        else:
            headers_list = column_keys
        
        base_column_count = len(headers_list)
        headers_list = headers_list + cid_headers(get_translation)
        headers = "".join(f"<th>{h}</th>" for h in headers_list)

        if not tag_map:
            tag_map = {"red_row": "red-row", "yellow_row": "yellow-row", "blue_row": "blue-row", "gray_row": "gray-row"}
        
        # ⚡ Bolt Optimization: Pre-compute path-to-tag mapping to avoid O(N^2) lookups
        path_to_tag_class = {}
        if tree_get_children and tree_item:
            try:
                for item_id in tree_get_children():
                    item_values = tree_item(item_id, "values")
                    if item_values and len(item_values) > 4:
                        path_val = item_values[4]
                        tags = tree_item(item_id, "tags")
                        if tags:
                            path_to_tag_class[path_val] = tag_map.get(tags[0], "")
            except (IndexError, TypeError):
                pass

        rows = ""
        
        # Generate Table Rows
        for i, values in enumerate(report_data):
            tag_class = ""
            try:
                path_str = values[4]
                tag_class = path_to_tag_class.get(path_str, "")
            except IndexError:
                path_str = ""
            
            note_text = html_escape_module.escape(file_annotations.get(path_str, "")).replace('\n', '<br>')
            
            row_values = [html_escape_module.escape(str(v)) for v in values]
            while len(row_values) < base_column_count:
                row_values.append("")
            if len(row_values) > 10:
                row_values[10] = note_text

            row_values = row_values[:base_column_count]
            decoded_text, methods, confidence = cid_columns_for_path(
                all_scan_data, path_str)
            # Confidence gets its own CSS class so a speculative reading is
            # visually distinct in the report, not just labelled.
            row_values.append(
                html_escape_module.escape(decoded_text).replace("\n", "<br>"))
            row_values.append(html_escape_module.escape(methods))
            row_values.append(
                f'<span class="conf-{confidence.lower()}">{html_escape_module.escape(confidence)}</span>'
                if confidence else "")

            rows += f'<tr class="{tag_class}">' + "".join(f"<td>{v}</td>" for v in row_values) + "</tr>"

        html_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>PDFRecon Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        table {{ border-collapse: collapse; width: 100%; border: 1px solid #ddd; }}
        th {{ background-color: #f2f2f2; padding: 12px; text-align: left; font-weight: bold; border: 1px solid #ddd; }}
        td {{ padding: 8px; border: 1px solid #ddd; word-break: break-word; }}
        .red-row {{ background-color: #FFDDDD; }}
        .yellow-row {{ background-color: #FFFFCC; }}
        .blue-row {{ background-color: #CCE5FF; }}
        .gray-row {{ background-color: #E0E0E0; }}
        h1 {{ color: #333; }}
        .report-date {{ color: #666; font-style: italic; }}
        .conf-certain {{ color: #1B5E20; font-weight: bold; }}
        .conf-probable {{ color: #8a6100; font-weight: bold; }}
        .conf-speculative {{ color: #fff; background: #B22222; font-weight: bold;
                             padding: 1px 6px; border-radius: 3px; }}
    </style>
</head>
<body>
    <h1>PDFRecon Report</h1>
    <p class="report-date">Generated on {date}</p>
    <table>
        <thead><tr>{headers}</tr></thead>
        <tbody>{rows}</tbody>
    </table>
</body>
</html>
"""
        
        html_content = html_template.format(
            date=datetime.now().strftime("%d-%m-%Y %H:%M:%S"),
            headers=headers,
            rows=rows
        )
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        logging.info(f"HTML export completed: {file_path}")
        
    except Exception as e:
        logging.error(f"Error exporting to HTML: {e}")
        raise
