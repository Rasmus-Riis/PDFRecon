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

## Missing Objects
**Classification:** <red>YES</red>

**What it means:** PDF references objects that don't exist—indicates corruption or improper editing.

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

# MEDIUM-CONFIDENCE INDICATORS (Indications Found - Yellow)

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
**Classification:** <yellow>Indications Found</yellow>

**What it means:** Document IDs don't match, indicating merging or extensive modification.

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

## Contact
Developer: Rasmus Riis  
Email: riisras@gmail.com
