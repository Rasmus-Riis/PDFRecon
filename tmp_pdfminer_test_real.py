import sys
from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
from pdfminer.pdfpage import PDFPage
from pdfminer.converter import PDFPageAggregator
from pdfminer.layout import LAParams

def test_pdfminer(pdf_path):
    print(f"--- Scanning {pdf_path} ---")
    class TouchUpDevice(PDFPageAggregator):
        def __init__(self, rsrcmgr, laparams):
            super().__init__(rsrcmgr, laparams=laparams)
            self.in_touchup = False
            self.current_page_text = []

        def begin_tag(self, tag, props=None):
            super().begin_tag(tag, props)
            tag_name = tag.name if hasattr(tag, 'name') else str(tag)
            print(f"begin_tag: {tag_name}, props={props}")
            if tag_name == 'TouchUp_TextEdit':
                self.in_touchup = True
            elif props and hasattr(props, 'keys'):
                for v in props.values():
                    v_name = v.name if hasattr(v, 'name') else str(v)
                    print("prop_value name:", v_name)
                    if 'TouchUp_TextEdit' in v_name:
                        self.in_touchup = True

        def end_tag(self):
            super().end_tag()
            if self.in_touchup:
                self.in_touchup = False
                
        def receive_layout(self, ltpage):
            pass

        def render_string(self, textstate, seq, ncs, graphicstate):
            super().render_string(textstate, seq, ncs, graphicstate)
            if self.in_touchup:
                font = textstate.font
                text = ""
                for obj in seq:
                    try:
                        if isinstance(obj, str):
                            text += obj
                        elif isinstance(obj, bytes):
                            for cid in font.decode(obj):
                                try:
                                    text += font.to_unichr(cid)
                                except Exception:
                                    pass
                    except Exception:
                        pass
                if text:
                    self.current_page_text.append(text)

    rmgr = PDFResourceManager()
    device = TouchUpDevice(rmgr, laparams=LAParams())
    interpreter = PDFPageInterpreter(rmgr, device)

    try:
        with open(pdf_path, "rb") as f:
            pages = PDFPage.get_pages(f)
            for i, page in enumerate(pages):
                device.current_page_text = []
                interpreter.process_page(page)
                if device.current_page_text:
                    print(f"Page {i+1} extracted: {device.current_page_text}")
                else:
                    print(f"Page {i+1} touching up no text")
    except Exception as e:
        print("Failed extraction:", e)

if __name__ == '__main__':
    import os
    for p in ["mock_test.pdf", "test_missing.pdf"]:
        if os.path.exists(p):
            test_pdfminer(p)
