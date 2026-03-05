import re
import fitz

def test_extract(stream):
    print("Testing stream...")
    blocks = stream.split(b"EMC")
    page_results = []
    
    for block in blocks:
        if b"TouchUp_TextEdit" in block:
            touchup_idx = block.find(b"TouchUp_TextEdit")
            content = block[touchup_idx:]
            print(f"Content block: {content}")
            
            # Literal Tj, TJ, ', "
            literal_matches = re.findall(rb"\((.*?)\)(?:\s*Tj|\s*TJ|\s*'|\s*\")", content)
            for m in literal_matches:
                text = fitz.utils.pdfdoc_decode(m).strip()
                print("  Literal match:", text)
                page_results.append(text)
                
            # Hex Tj
            hex_matches = re.findall(rb"<([0-9a-fA-F\s]+)>(?:\s*Tj|\s*TJ|\s*'|\s*\")", content)
            for m in hex_matches:
                try:
                    hex_str = m.replace(b" ", b"").replace(b"\n", b"").replace(b"\r", b"")
                    if len(hex_str) % 2 != 0:
                        hex_str += b"0"
                    decoded = bytes.fromhex(hex_str.decode('ascii'))
                    text = decoded.decode('latin-1', errors='ignore').strip()
                    print("  Hex match:", text)
                    page_results.append(text)
                except Exception as e:
                    print("Hex error", e)
                    
            # Array TJ
            array_matches = re.findall(rb"\[(.*?)\]\s*TJ", content)
            for m in array_matches:
                inner_lits = re.findall(rb"\((.*?)\)", m)
                for il in inner_lits:
                    text = fitz.utils.pdfdoc_decode(il).strip()
                    print("  Array literal match:", text)
                    page_results.append(text)
                    
                inner_hexs = re.findall(rb"<([0-9a-fA-F\s]+)>", m)
                for ih in inner_hexs:
                    h = ih.replace(b" ", b"")
                    if len(h) % 2 != 0: h += b"0"
                    decoded = bytes.fromhex(h.decode('ascii'))
                    text = decoded.decode('latin-1', errors='ignore').strip()
                    print("  Array hex match:", text)
                    page_results.append(text)

    print("Final Extracted:", page_results)

mock_stream = b'''
/P <</MCID 0>> BDC
(Ignored text) Tj
EMC
/TouchUp_TextEdit <</MCID 1>> BDC
(Hello World) Tj
<48656C6C6F20486578> Tj
[(Array ) -100 (Lit) 50 <20486578>] TJ
(Unclosed array?] Tj
EMC
'''

test_extract(mock_stream)
