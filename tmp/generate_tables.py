import json
import os

def generate_tables():
    with open("lang/translations.json", "r", encoding="utf-8") as f:
        translations = json.load(f)

    # All known indicators
    indicators = [
        "HasXFAForm", "HasDigitalSignature", "MultipleStartxref", "IncrementalUpdates",
        "Linearized", "LinearizedUpdated", "HasRedactions", "HasAnnotations",
        "HasPieceInfo", "HasAcroForm", "AcroFormNeedAppearances", "ObjGenGtZero",
        "TrailerIDChange", "XMPIDChange", "XMPHistory", "MultipleCreators",
        "MultipleProducers", "CreateDateMismatch", "ModifyDateMismatch",
        "MultipleFontSubsets", "OrphanedObjects", "MissingObjects",
        "LargeObjectNumberGaps", "HiddenAnnotations", "TimestampSpoofing",
        "SubmitFormAction", "LaunchShellAction", "ExtractedJavaScript",
        "TouchUp_TextEdit", "ExifToolMismatch", "SuspiciousObjectContent",
        "HasLayers", "MoreLayersThanPages", "ColorProfileMismatch",
        "HighDefImage", "HiddenText", "XMPHistoryGap", "StructuralScrubbing",
        "PDFAViolation", "RelatedFiles"
    ]

    def insert_table(filepath, title, desc, h1, h2):
        print(f"Generating for {filepath}")
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        if title in content:
            print("Already there")
            return

        table = f"\n\n---\n\n## {title}\n\n{desc}\n\n"
        table += f"| {h1} | {h2} |\n|---|---|\n"

        for ind in indicators:
            val = translations.get(ind, ind)
            # Find closest translation. translations.json has a flat structure.
            table += f"| `{ind}` | {val} |\n"
            
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(table)
            
    insert_table("lang/manual_en.md", "Appendix: Complete Indicator List", "Overview of all technical forensic indicators.", "Indicator Key", "Full Name")
    insert_table("lang/manual_da.md", "Bilag: Fuldstændig Indikatorliste", "Oversigt over alle tekniske forensiske indikatorer.", "Indikator Nøgle", "Fulde Navn")

generate_tables()
