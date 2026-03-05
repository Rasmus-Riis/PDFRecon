from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
from pdfminer.pdfpage import PDFPage
from pdfminer.converter import PDFConverter
from pdfminer.layout import LAParams
from pdfminer.pdfdevice import PDFDevice
import io

class TouchUpExtractor(PDFConverter):
    def __init__(self, rsrcmgr, outfp, codec='utf-8', pageno=1, laparams=None):
        super().__init__(rsrcmgr, outfp, codec=codec, pageno=pageno, laparams=laparams)
        self.in_touchup = False
        self.extracted_text = []
        self.current_text = []

    def begin_tag(self, tag, props=None):
        if tag.name == 'TouchUp_TextEdit' or (props and b'TouchUp_TextEdit' in props):
            # Or if it's named TouchUp_TextEdit
            self.in_touchup = True
            self.current_text = []

    def end_tag(self):
        if self.in_touchup:
            self.in_touchup = False
            text = "".join(self.current_text).strip()
            if text:
                self.extracted_text.append(text)
            self.current_text = []

    def receive_layout(self, ltpage):
        pass

    def render_string(self, text, font, matrix, size, textstate):
        if self.in_touchup:
            self.current_text.append(text)
            
    # override other render methods if needed
def try_pdfminer(pdf_path):
    mgr = PDFResourceManager()
    out = io.StringIO()
    # Need a simpler device since PDFConverter handles full layout
    # Alternatively build a simple device:
    class BasicDevice(PDFDevice):
        def __init__(self, rsrcmgr):
            super().__init__(rsrcmgr)
            self.in_touchup = False
            self.extracted = []
            self.current = []
            
        def begin_tag(self, tag, props=None):
            # tag is PSLiteral
            tag_name = tag.name if hasattr(tag, 'name') else str(tag)
            if tag_name == 'TouchUp_TextEdit':
                self.in_touchup = True
            elif props and hasattr(props, 'keys'):
                for v in props.values():
                    v_name = v.name if hasattr(v, 'name') else str(v)
                    if 'TouchUp_TextEdit' in v_name:
                        self.in_touchup = True

        def end_tag(self):
            if self.in_touchup:
                self.in_touchup = False
                text = "".join(self.current)
                if text.strip():
                    self.extracted.append(text.strip())
                self.current = []
                
        def render_string(self, text, font, matrix, size, textstate):
            if self.in_touchup:
                self.current.append(text)
                
    device = BasicDevice(mgr)
    interpreter = PDFPageInterpreter(mgr, device)
    
    with open(pdf_path, 'rb') as f:
        for page in PDFPage.get_pages(f):
            interpreter.process_page(page)
            
    return device.extracted

if __name__ == "__main__":
    print("Testing device...")
    # I will just write a mockup layout test here
    print("Code ready.")
