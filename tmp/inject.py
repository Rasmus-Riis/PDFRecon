import os
import re

html_path = r"c:\Users\riisr\Documents\GitHub\PDFRecon\PDFRecon_Manual.html"
with open(html_path, "r", encoding="utf-8") as f:
    html = f.read()

menu_addition = """            <li class="section-header lang-en">— BONUS (MALWARE / PHISHING) —</li>
            <li class="section-header lang-da">— BONUS (MALWARE / PHISHING) —</li>
            <li class="lang-en" onclick="showSection('urls')">Possible URLs</li>
            <li class="lang-da" onclick="showSection('urls')">Mulige Webadresser</li>
            <li class="lang-en" onclick="showSection('emails')">Possible Emails</li>
            <li class="lang-da" onclick="showSection('emails')">Mulige E-mailadresser</li>
            <li class="lang-en" onclick="showSection('javascript')">JavaScript</li>
            <li class="lang-da" onclick="showSection('javascript')">JavaScript</li>
            <li class="lang-en" onclick="showSection('submit_form')">Submit Form Action</li>
            <li class="lang-da" onclick="showSection('submit_form')">Send formular</li>
            <li class="lang-en" onclick="showSection('launch_shell')">Launch Shell Action</li>
            <li class="lang-da" onclick="showSection('launch_shell')">Start Shell Command</li>
            <li class="lang-en" onclick="showSection('null_byte')">Starts with Null Byte</li>
            <li class="lang-da" onclick="showSection('null_byte')">Starter med Nul-byte</li>
"""

section_addition = """
        <div class="section lang-en" id="urls" style="display:none;">
            <h1>Possible URLs <span class="badge badge-info" style="background-color: #007bff;">BONUS</span></h1>
            <p><strong>Classification:</strong> <span style="color: #007bff; font-weight:bold;">Bonus (Malware/Phishing)</span></p>
            <p><strong>What it means:</strong> Detects URLs found in the raw file that might be pointing to malicious payloads, internal systems, or the web-based software that generated the PDF.</p>
        </div>
        <div class="section lang-da" id="urls-da" style="display:none;">
            <h1>Mulige Webadresser <span class="badge badge-info" style="background-color: #007bff;">BONUS</span></h1>
            <p><strong>Klassifikation:</strong> <span style="color: #007bff; font-weight:bold;">Bonus (Malware/Phishing)</span></p>
            <p><strong>Hvad det betyder:</strong> Detekterer URL'er fundet i den rå fil, som måske peger på ondsindede payloads, interne systemer eller den webbaserede software, der genererede PDF'en.</p>
        </div>

        <div class="section lang-en" id="emails" style="display:none;">
            <h1>Possible Emails <span class="badge badge-info" style="background-color: #007bff;">BONUS</span></h1>
            <p><strong>Classification:</strong> <span style="color: #007bff; font-weight:bold;">Bonus (Malware/Phishing)</span></p>
            <p><strong>What it means:</strong> Detects email addresses hidden in the raw data of the file. This can unintentionally identify the author, organization, or software license used to create the document.</p>
        </div>
        <div class="section lang-da" id="emails-da" style="display:none;">
            <h1>Mulige E-mailadresser <span class="badge badge-info" style="background-color: #007bff;">BONUS</span></h1>
            <p><strong>Klassifikation:</strong> <span style="color: #007bff; font-weight:bold;">Bonus (Malware/Phishing)</span></p>
            <p><strong>Hvad det betyder:</strong> Detekterer e-mailadresser skjult i filens rå data. Dette kan utilsigtet identificere forfatteren, organisationen eller den softwarelicens, der blev brugt til at oprette dokumentet.</p>
        </div>

        <div class="section lang-en" id="javascript" style="display:none;">
            <h1>JavaScript Extraction <span class="badge badge-info" style="background-color: #007bff;">BONUS</span></h1>
            <p><strong>Classification:</strong> <span style="color: #007bff; font-weight:bold;">Bonus (Malware/Phishing)</span></p>
            <p><strong>What it means:</strong> The PDF contains JavaScript code. While JavaScript logic can be used in dynamic forms, it is frequently used aggressively to exploit older PDF readers, fetch remote payloads, or try to escape sandbox confinements.</p>
        </div>
        <div class="section lang-da" id="javascript-da" style="display:none;">
            <h1>JavaScript Udvinding <span class="badge badge-info" style="background-color: #007bff;">BONUS</span></h1>
            <p><strong>Klassifikation:</strong> <span style="color: #007bff; font-weight:bold;">Bonus (Malware/Phishing)</span></p>
            <p><strong>Hvad det betyder:</strong> PDF'en indeholder JavaScript kode. Mens JavaScript logik kan bruges i dynamiske formater, er det desværre ofte brugt aggressivt til at udnytte ældre PDF læsere, hente uønskede payloads over et usikkert netværk eller forsøge et flugt fra en computers isolationsmiljø.</p>
        </div>

        <div class="section lang-en" id="submit_form" style="display:none;">
            <h1>Submit Form Action <span class="badge badge-info" style="background-color: #007bff;">BONUS</span></h1>
            <p><strong>Classification:</strong> <span style="color: #007bff; font-weight:bold;">Bonus (Malware/Phishing)</span></p>
            <p><strong>What it means:</strong> Indicates the presence of the `/SubmitForm` action which attempts to securely transport or send user data back to a remote host upon opening or interacting with specific items on the document.</p>
        </div>
        <div class="section lang-da" id="submit_form-da" style="display:none;">
            <h1>Send formular <span class="badge badge-info" style="background-color: #007bff;">BONUS</span></h1>
            <p><strong>Klassifikation:</strong> <span style="color: #007bff; font-weight:bold;">Bonus (Malware/Phishing)</span></p>
            <p><strong>Hvad det betyder:</strong> Indikerer, at en handling `/SubmitForm` forsøger at overføre brugerindtastede data tilbage til en fjernserver for eventuel indsamling og profilering.</p>
        </div>

        <div class="section lang-en" id="launch_shell" style="display:none;">
            <h1>Launch Shell Action <span class="badge badge-info" style="background-color: #007bff;">BONUS</span></h1>
            <p><strong>Classification:</strong> <span style="color: #007bff; font-weight:bold;">Bonus (Malware/Phishing)</span></p>
            <p><strong>What it means:</strong> The highly dangerous `/Launch` routine was detected. The document is capable of interacting natively with underlying system tools (such as cmd.exe or PowerShell.exe) to initiate execution of commands directly against your hardware and OS.</p>
        </div>
        <div class="section lang-da" id="launch_shell-da" style="display:none;">
            <h1>Start Shell Command <span class="badge badge-info" style="background-color: #007bff;">BONUS</span></h1>
            <p><strong>Klassifikation:</strong> <span style="color: #007bff; font-weight:bold;">Bonus (Malware/Phishing)</span></p>
            <p><strong>Hvad det betyder:</strong> Den yderst farlige rutine `/Launch` blev opdaget. Dokumentet har den ondsindede egenskab at kunne kommunikere indbygget direkte med bagvedliggende systemværktøjer (f.eks cmd.exe eller PowerShell.exe).</p>
        </div>

        <div class="section lang-en" id="null_byte" style="display:none;">
            <h1>Starts with Null Byte <span class="badge badge-info" style="background-color: #007bff;">BONUS</span></h1>
            <p><strong>Classification:</strong> <span style="color: #007bff; font-weight:bold;">Bonus (Malware/Phishing)</span></p>
            <p><strong>What it means:</strong> The file begins with a Null byte (`0x00`) just before the standard `%PDF-` header magic number. Highly suspicious formatting often indicative of malware attempting evasion techniques to break detection mechanisms.</p>
        </div>
        <div class="section lang-da" id="null_byte-da" style="display:none;">
            <h1>Starter med Nul-byte <span class="badge badge-info" style="background-color: #007bff;">BONUS</span></h1>
            <p><strong>Klassifikation:</strong> <span style="color: #007bff; font-weight:bold;">Bonus (Malware/Phishing)</span></p>
            <p><strong>Hvad det betyder:</strong> Filen begynder med en Null-byte (`0x00`) der falder lige foran den lovpåkrævede `%PDF-` overskrift. Mistænkelig redigering der ofte indikerer at skjult ondsindet kode forsøger at undslippe rutinemæssig detektering.</p>
        </div>
"""

# 1. Inject Menu
if "BONUS (MALWARE / PHISHING)" not in html:
    ref_marker = '            <li class="section-header lang-en">— REFERENCE —</li>'
    html = html.replace(ref_marker, menu_addition + ref_marker)

# 2. Inject Sections
if "id=\"urls\"" not in html:
    end_marker = '        <div class="section lang-da" id="operators-da" style="display:none;">'
    # We find where operators-da ends to inject our sections safely
    parts = html.split(end_marker)
    if len(parts) == 2:
        inner_parts = parts[1].split('        </div>')
        reconstructed = end_marker + inner_parts[0] + '        </div>\n' + section_addition + '        </div>'.join(inner_parts[1:])
        html = parts[0] + reconstructed

with open(html_path, "w", encoding="utf-8") as f:
    f.write(html)

print("Injected malware sections.")
