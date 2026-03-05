"""
Build a single bilingual PDFRecon forensic manual (EN/DA) from lang/manual_da.html.

Strategy:
- Process SECTION divs as top-level units. For each section div, clone it entirely,
  translate all text nodes in the clone, then mark original as lang-en and clone as lang-da.
- This avoids the nested-duplication problem.
"""
import copy
import re
from bs4 import BeautifulSoup, NavigableString, Comment
from deep_translator import GoogleTranslator

# Technical terms that should NOT be translated
KEEP_ENGLISH = {
    'TouchUp_TextEdit', 'PieceInfo', 'AcroForm', 'NeedAppearances',
    'startxref', 'xref', 'CropBox', 'MediaBox', 'OpenAction',
    'ExifTool', 'EXIF', 'XMP', 'xmpMM', 'DocumentID', 'InstanceID',
    'DocumentAncestors', 'DerivedFrom', 'PDFRecon', 'PDF',
    '%%EOF', '%PDF-', 'Tm', 'Td', 'MD5', 'SHA256',
    'qpdf', 'mutool', 'HxD', '010 Editor', 'pdfimages',
    'F1', 'obj', 'endobj', 'trailer', 'Ctrl',
}

def should_translate(text):
    """Check if a text string should be translated."""
    stripped = text.strip()
    if len(stripped) < 2:
        return False
    if not any(c.isalpha() for c in stripped):
        return False
    # Don't translate pure code/technical strings
    if stripped in KEEP_ENGLISH:
        return False
    return True

def translate_text(translator, text):
    """Translate a text string, preserving leading/trailing whitespace."""
    if not should_translate(text):
        return text
    
    stripped = text.strip()
    leading = text[:len(text) - len(text.lstrip())]
    trailing = text[len(text.rstrip()):]
    
    try:
        translated = translator.translate(stripped)
        if translated:
            return leading + translated + trailing
    except Exception:
        pass
    return text

def translate_element_texts(element, translator, count_ref):
    """Recursively translate all NavigableString nodes in an element."""
    for child in list(element.children):
        if isinstance(child, NavigableString) and not isinstance(child, Comment):
            text = str(child)
            if should_translate(text):
                count_ref[0] += 1
                if count_ref[0] % 50 == 0:
                    print(f"  Translated {count_ref[0]} text nodes...")
                translated = translate_text(translator, text)
                child.replace_with(NavigableString(translated))
        elif hasattr(child, 'children'):
            translate_element_texts(child, translator, count_ref)

def build_manual():
    print("Loading lang/manual_da.html (forensic manual)...")
    with open('lang/manual_da.html', 'r', encoding='utf-8') as f:
        html = f.read()
    
    soup = BeautifulSoup(html, 'html.parser')
    translator = GoogleTranslator(source='en', target='da')
    
    # ── 1. Inject CSS for language toggling ──
    style = soup.head.find('style')
    style.append("""
/* Language toggle */
body.lang-da .lang-en { display: none !important; }
body.lang-en .lang-da { display: none !important; }
.lang-toggle { padding: 0 20px 10px 20px; display: flex; gap: 5px; }
.lang-toggle button {
    flex: 1; padding: 6px; cursor: pointer; border: none; border-radius: 3px;
    font-size: 13px; transition: all 0.2s;
}
.lang-btn-active { background-color: #00A0D6; color: #000; font-weight: bold; }
.lang-btn-inactive { background-color: #3d3d3d; color: #dcdcdc; }
""")
    
    # ── 2. Set body default language ──
    soup.body['class'] = ['lang-en']
    
    # ── 3. Update sidebar header ──
    sidebar = soup.find(id='sidebar')
    
    # Remove any existing lang toggle divs we added previously
    for div in sidebar.find_all('div', style=lambda s: s and 'display: flex' in s and 'gap: 5px' in s):
        div.decompose()
    
    # Update sidebar h2
    sidebar_h2 = sidebar.find('h2')
    if sidebar_h2:
        sidebar_h2.string = "📋 PDFRecon Manual"
    
    # ── 4. Add language toggle buttons after the h2 ──
    toggle_html = """
    <div class="lang-toggle">
        <button id="btn-en" class="lang-btn-active" onclick="setLang('en')">🇬🇧 English</button>
        <button id="btn-da" class="lang-btn-inactive" onclick="setLang('da')">🇩🇰 Dansk</button>
    </div>
    """
    toggle_soup = BeautifulSoup(toggle_html, 'html.parser')
    sidebar_h2.insert_after(toggle_soup)
    
    # ── 5. Translate sidebar navigation items ──
    print("Translating sidebar navigation...")
    nav_ul = sidebar.find('ul', id='nav')
    if nav_ul:
        for li in nav_ul.find_all('li', recursive=False):
            # Skip section-header items
            if 'section-header' in li.get('class', []):
                # Clone the section header too
                da_li = copy.copy(li)
                li['class'] = li.get('class', []) + ['lang-en']
                da_li['class'] = [c for c in da_li.get('class', []) if c != 'lang-en'] + ['lang-da']
                # Translate text in da_li
                for s in da_li.find_all(string=True):
                    text = str(s).strip()
                    if text and any(c.isalpha() for c in text):
                        translated = translate_text(translator, str(s))
                        s.replace_with(NavigableString(translated))
                li.insert_after(da_li)
                continue
            
            # Regular nav item: duplicate with translation
            da_li = copy.copy(li)
            li['class'] = li.get('class', []) + ['lang-en']
            da_li['class'] = [c for c in da_li.get('class', []) if c != 'lang-en'] + ['lang-da']
            for s in da_li.find_all(string=True):
                text = str(s).strip()
                if text and any(c.isalpha() for c in text):
                    translated = translate_text(translator, str(s))
                    s.replace_with(NavigableString(translated))
            li.insert_after(da_li)
    
    # ── 6. Translate each content section ──
    content_div = soup.find(id='content')
    sections = content_div.find_all('div', class_='section', recursive=False)
    
    print(f"Translating {len(sections)} content sections...")
    for i, section in enumerate(sections):
        section_id = section.get('id', f'section_{i}')
        print(f"  Section {i+1}/{len(sections)}: {section_id}")
        
        # Deep copy the section
        da_section = copy.copy(section)
        
        # Mark original as EN, clone as DA
        section['class'] = section.get('class', []) + ['lang-en']
        da_section['class'] = [c for c in da_section.get('class', []) if c != 'lang-en'] + ['lang-da']
        
        # Keep the same id for the DA version but add -da suffix
        da_section['id'] = section_id + '-da'
        
        # Copy the display style from original
        if section.get('style'):
            da_section['style'] = section['style']
        
        # Translate all text nodes in the DA section
        count_ref = [0]
        translate_element_texts(da_section, translator, count_ref)
        print(f"    Translated {count_ref[0]} text nodes")
        
        # Insert DA section right after EN section
        section.insert_after(da_section)
    
    # ── 7. Add the JavaScript for language switching ──
    script_html = """
    <script>
    function setLang(lang) {
        document.body.className = 'lang-' + lang;
        var btnEn = document.getElementById('btn-en');
        var btnDa = document.getElementById('btn-da');
        if (lang === 'en') {
            btnEn.className = 'lang-btn-active';
            btnDa.className = 'lang-btn-inactive';
        } else {
            btnDa.className = 'lang-btn-active';
            btnEn.className = 'lang-btn-inactive';
        }
    }
    
    // Update showSection to handle both EN and DA sections
    var _origShowSection = typeof showSection === 'function' ? showSection : null;
    function showSection(id) {
        var sections = document.querySelectorAll('#content .section');
        for (var i = 0; i < sections.length; i++) {
            sections[i].style.display = 'none';
        }
        var enSection = document.getElementById(id);
        var daSection = document.getElementById(id + '-da');
        if (enSection) enSection.style.display = 'block';
        if (daSection) daSection.style.display = 'block';
        
        // Update active nav item
        var navItems = document.querySelectorAll('#nav li');
        for (var i = 0; i < navItems.length; i++) {
            navItems[i].classList.remove('active');
        }
        // Find and activate clicked items
        var clicked = document.querySelectorAll('#nav li[onclick*=\"\\'' + id + '\\'\"]');
        for (var i = 0; i < clicked.length; i++) {
            clicked[i].classList.add('active');
        }
    }
    
    // Search functionality
    document.addEventListener('DOMContentLoaded', function() {
        var searchInput = document.getElementById('search');
        if (searchInput) {
            searchInput.addEventListener('input', function() {
                var query = this.value.toLowerCase();
                var navItems = document.querySelectorAll('#nav li:not(.section-header)');
                for (var i = 0; i < navItems.length; i++) {
                    if (!query || navItems[i].textContent.toLowerCase().includes(query)) {
                        navItems[i].style.display = '';
                    } else {
                        navItems[i].style.display = 'none';
                    }
                }
            });
        }
        
        // Auto-detect language from URL parameter
        var params = new URLSearchParams(window.location.search);
        var lang = params.get('lang');
        if (lang === 'da' || lang === 'en') {
            setLang(lang);
        }
    });
    </script>
    """
    soup.body.append(BeautifulSoup(script_html, 'html.parser'))
    
    # ── 8. Remove any old inline scripts from the original ──
    # (keep only our new one)
    for script in soup.find_all('script'):
        text = script.string or ''
        if 'showSection' in text and 'setLang' not in text:
            script.decompose()
    
    # ── 9. Save ──
    output_path = 'PDFRecon_Manual.html'
    print(f"Saving to {output_path}...")
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(str(soup))
    
    print(f"Done! Bilingual manual saved to {output_path}")
    print("Open with ?lang=da for Danish, default is English.")

if __name__ == '__main__':
    build_manual()
