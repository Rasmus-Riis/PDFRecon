# PDFRecon - Manual

## Introduction
PDFRecon is a tool designed to assist in the investigation of PDF files. The program analyzes files for a range of technical indicators that can reveal alteration, editing, or hidden content. The results are presented in a clear table that can be exported to Excel for further documentation.

## Important Note on Timestamps
The 'File Created' and 'File Modified' columns show timestamps from the computer's file system. Be aware that these timestamps can be unreliable. A simple action like copying a file from one location to another will typically update these dates to the time of the copy. For a more reliable timeline, use the 'Show Timeline' feature, which is based on metadata inside the file itself.

## Classification System
The program classifies each file based on the indicators found. This is done to quickly prioritize which files require closer examination.

<red><b>YES (High Risk):</b></red> Assigned to files where strong evidence of alteration has been found. These files should always be thoroughly investigated. Indicators that trigger this flag are typically difficult to forge and point directly to a change in the file's content or structure.

<yellow><b>Indications Found (Medium Risk):</b></yellow> Assigned to files where one or more technical traces have been found that deviate from a standard, 'clean' PDF. These traces are not definitive proof of alteration in themselves, but they show that the file has a history or structure that warrants a closer look.

<green><b>NOT DETECTED (Low Risk):</b></green> Assigned to files where the program has not found any of the known indicators. This does not mean that the file is 100% unchanged, but that it does not exhibit the typical signs of alteration that the tool looks for.

## Explanation of Indicators
Below is a detailed explanation of each indicator that PDFRecon looks for.
 
<b>Has Revisions</b>
*<i>Changed:</i>* <red>YES</red>
• What it means: The PDF standard allows changes to be saved on top of an existing file (incremental saving). This leaves the original version of the document intact inside the file. PDFRecon has found and extracted one or more of these previous versions. This is unequivocal proof that the file has been changed after its original creation.

<b>TouchUp_TextEdit</b>
*<i>Changed:</i>* <red>YES</red>
• What it means: This is a specific metadata flag left by Adobe Acrobat when a user has manually edited text directly in the PDF document. It is very strong evidence of direct content alteration.

<b>Multiple Font Subsets</b>
*<i>Changed:</i>* <yellow>Indications Found</yellow>
• What it means: When text is added to a PDF, often only the characters actually used from a font are embedded (a 'subset'). If a file is edited with another program that does not have access to the exact same font, a new subset of the same base font may be created. Finding multiple subsets (e.g., Multiple Font Subsets: 'Arial': F1+ArialMT', 'F2+Arial-BoldMT' is a strong indication that text has been added or changed at different times or with different tools.

<b>Multiple Creators / Producers</b>
*<i>Changed:</i>* <yellow>Indikationer Fundet</yellow>
• Hvad det betyder: PDF-filer indeholder metadata om, hvilket program der har oprettet (/Creator) og genereret (/Producer) filen. Hvis der findes flere forskellige navne i disse felter (f.eks. Multiple Creators (Fundet 2): "Microsoft Word", "Adobe Acrobat Pro"), indikerer det, at filen er blevet behandlet af mere end ét program. Dette sker typisk, når en fil oprettes i ét program og derefter redigeres i et andet.

<b>xmpMM:History / DerivedFrom / DocumentAncestors</b>
*<i>Changed:</i>* <yellow>Indications Found</yellow>
• What it means: These are different types of XMP metadata that store information about the file's history. They can contain timestamps for when the file was saved, IDs from previous versions, and what software was used. The presence of these fields proves that the file has an editing history.

<b>Multiple DocumentID / Different InstanceID</b>
*<i>Changed:</i>* <yellow>Indications Found</yellow>
• What it means: Each PDF has a unique DocumentID that should ideally be the same for all versions. The InstanceID, however, changes every time the file is saved. If multiple different DocumentIDs are found (e.g., Trailer ID Changed: From [ID1...] to [ID2...]), or if there is an abnormally high number of InstanceIDs, it points to a complex editing history, potentially where parts from different documents have been combined.

<b>Multiple startxref</b>
*<i>Changed:</i>* <yellow>Indications Found</yellow>
• What it means: 'startxref' is a keyword that tells a PDF reader where to start reading the file's structure. A standard, unchanged file has only one. If there are more, it is a sign that incremental changes have been made (see 'Has Revisions').

<b>Objects with generation > 0</b>
*<i>Changed:</i>* <yellow>Indications Found</yellow>
• What it means: Each object in a PDF file has a version number (generation). In an original, unaltered file, this number is typically 0 for all objects. If objects are found with a higher generation number (e.g., '12 1 obj'), it is a sign that the object has been overwritten in a later, incremental save. This indicates that the file has been updated.

<b>More Layers Than Pages</b>
*<i>Changed:</i>* <yellow>Indications Found</yellow>
• What it means: The document's structure contains more layers (Optional Content Groups) than it has pages. Each layer is a container for content that can be shown or hidden. While technically possible, having more layers than pages is unusual. It might indicate a complex document, a file that has been heavily edited, or potentially that information is hidden in layers not associated with visible content. Files with this indicator should be examined more closely in a PDF reader that supports layer functionality.

<b>Linearized / Linearized + updated</b>
*<i>Changed:</i>* <yellow>Indications Found</yellow>
• What it means: A "linearized" PDF is optimized for fast web viewing. If such a file was later modified (updated), PDFRecon flags it. This may indicate that a supposedly final document was edited afterwards.

<b>Has PieceInfo</b>
*<i>Changed:</i>* <yellow>Indications Found</yellow>
• What it means: Some applications, particularly from Adobe, store extra technical traces (PieceInfo) about changes or versions. This can reveal that the file has been processed in specific tools like Illustrator.

<b>Has Redactions</b>
*<i>Changed:</i>* <yellow>Indications Found</yellow>
• What it means: The document contains technical fields for redaction (blackouts/removals). In some cases, hidden text may still be present. Redactions should always be assessed critically.

<b>Has Annotations</b>
*<i>Changed:</i>* <yellow>Indications Found</yellow>
• What it means: The document includes comments, notes, or highlights. They may have been added later and can contain information that is not visible in the main content.

<b>AcroForm NeedAppearances=true</b>
*<i>Changed:</i>* <yellow>Indications Found</yellow>
• What it means: Form fields may need their appearance regenerated when the document opens. Field text can change or be auto-filled, which may obscure the original content.

<b>Has Digital Signature</b>
*<i>Changed:</i>* <yellow>Indications Found</yellow>
• What it means: The document contains a digital signature. A valid signature confirms the file has not changed since signing. An invalid/broken signature can be a strong sign of later alteration.

<b>Date inconsistency (Info vs. XMP)</b>
*<i>Changed:</i>* <yellow>Indications Found</yellow>
• What it means: The creation/modification dates in the PDF Info dictionary do not match the dates in XMP metadata (e.g., Creation Date Mismatch: Info='20230101...', XMP='2023-01-02...'). Such discrepancies can indicate hidden or unauthorized changes.