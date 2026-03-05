import io
import fitz
from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
from pdfminer.pdfpage import PDFPage
from pdfminer.converter import PDFPageAggregator
from pdfminer.layout import LAParams

def create_test_pdf():
    raw_pdf = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length 124 >>
stream
BT
/F1 24 Tf
100 700 Td
(Normal text) Tj
ET
/TouchUp_TextEdit <</MCID 1>> BDC
BT
/F1 24 Tf
100 650 Td
(Hidden TouchUp) Tj
ET
EMC
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000225 00000 n 
0000000398 00000 n 
trailer
<< /Size 6 /Root 1 0 R >>
startxref
0
%%EOF
"""
    try:
        doc = fitz.open("pdf", raw_pdf)
        repaired = doc.write()
        doc.close()
        return repaired
    except Exception as e:
        return raw_pdf

def test_pdfminer():
    pdf_bytes = create_test_pdf()
    
    class TouchUpDevice(PDFPageAggregator):
        def __init__(self, rsrcmgr, laparams):
            super().__init__(rsrcmgr, laparams=laparams)
            self.in_touchup = False
            self.current_page_text = []

        def begin_tag(self, tag, props=None):
            super().begin_tag(tag, props)
            tag_name = tag.name if hasattr(tag, 'name') else str(tag)
            if tag_name == 'TouchUp_TextEdit':
                self.in_touchup = True
            elif props and hasattr(props, 'keys'):
                for v in props.values():
                    v_name = v.name if hasattr(v, 'name') else str(v)
                    if 'TouchUp_TextEdit' in v_name:
                        self.in_touchup = True

        def end_tag(self):
            super().end_tag()
            if self.in_touchup:
                self.in_touchup = False
                
        def render_string(self, textstate, seq, ncs, graphicstate):
            # We let super process the sequence into LTChar objects
            # and we can just intercept them!
            # PDFPageAggregator builds self.cur_item
            super().render_string(textstate, seq, ncs, graphicstate)
            if self.in_touchup:
                font = textstate.font
                text = ""
                for obj in seq:
                    try:
                        if isinstance(obj, str):
                            text += obj
                        else:
                            # Actually, font.decode returns (cid, size) tuples?
                            for cid in font.decode(obj):
                                # pdfminer returns characters via to_unichr
                                text += font.to_unichr(cid)
                    except Exception as e:
                        print("Decode Error:", e)
                if text:
                    self.current_page_text.append(text)

    rmgr = PDFResourceManager()
    device = TouchUpDevice(rmgr, laparams=LAParams())
    interpreter = PDFPageInterpreter(rmgr, device)

    try:
        pages = PDFPage.get_pages(io.BytesIO(pdf_bytes))
        for i, page in enumerate(pages):
            device.current_page_text = []
            interpreter.process_page(page)
            print("Extracted from TouchUp Block:", device.current_page_text)
    except Exception as e:
        print("Failed extraction:", e)

if __name__ == '__main__':
    test_pdfminer()
