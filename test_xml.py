import fitz
import sys

def test_xml_extract(pdf_path):
    doc = fitz.open(pdf_path)
    page = doc[0]
    xml_text = page.get_text("xml")
    print(xml_text[:2000])
    doc.close()

if __name__ == "__main__":
    test_xml_extract(sys.argv[1])
