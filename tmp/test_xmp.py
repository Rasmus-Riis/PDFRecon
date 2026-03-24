import sys
import os
from pathlib import Path

# Add src to path
sys.path.append(str(Path(__file__).parent.parent / 'src'))

try:
    from xmp_relationship import XMPRelationshipManager
except ImportError:
    # Handle absolute path if relative fails
    src_path = r'c:\Users\riisr\Documents\GitHub\PDFRecon\src'
    sys.path.append(src_path)
    from xmp_relationship import XMPRelationshipManager

xmp_sample = """<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Adobe XMP Core 5.6-c140 79.160451, 2017/05/06-01:08:21        ">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:xmpMM="http://ns.adobe.com/xap/1.0/mm/"
    xmlns:stRef="http://ns.adobe.com/xap/1.0/sType/ResourceRef#"
    xmlns:stEvt="http://ns.adobe.com/xap/1.0/sType/ResourceEvent#">
   <xmpMM:DocumentID>xmp.did:eb864506-8b35-4d7a-8b8a-8b8a8b8a8b8a</xmpMM:DocumentID>
   <xmpMM:InstanceID>xmp.iid:eb864506-8b35-4d7a-8b8a-8b8a8b8a8b8b</xmpMM:InstanceID>
   <xmpMM:OriginalDocumentID>xmp.did:original-id-123</xmpMM:OriginalDocumentID>
   <xmpMM:DerivedFrom rdf:parseType="Resource">
    <stRef:documentID>xmp.did:parent-doc-id</stRef:documentID>
    <stRef:instanceID>xmp.iid:parent-ins-id</stRef:instanceID>
   </xmpMM:DerivedFrom>
   <xmpMM:Ingredients>
    <rdf:Bag>
     <rdf:li rdf:parseType="Resource">
      <stRef:documentID>xmp.did:ingredient-1</stRef:documentID>
      <stRef:instanceID>xmp.iid:ingredient-1</stRef:instanceID>
      <stRef:filePath>image1.jpg</stRef:filePath>
      <stRef:fromPart>time:0</stRef:fromPart>
      <stRef:toPart>time:10</stRef:toPart>
     </rdf:li>
    </rdf:Bag>
   </xmpMM:Ingredients>
   <xmpMM:Pantry>
    <rdf:Bag>
     <rdf:li rdf:parseType="Resource">
      <xmpMM:InstanceID>xmp.iid:ingredient-1</xmpMM:InstanceID>
      <xmpMM:DocumentID>xmp.did:ingredient-1-mismatch</xmpMM:DocumentID>
     </rdf:li>
    </rdf:Bag>
   </xmpMM:Pantry>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>"""

manager = XMPRelationshipManager()
import xml.etree.ElementTree as ET
try:
    root = ET.fromstring(xmp_sample)
    print(f"Root tag: {root.tag}")
    for elem in root.iter():
        print(f"Found tag: {elem.tag}")
except Exception as e:
    print(f"ET.fromstring failed: {e}")

results = manager.parse_xmp(xmp_sample)

print("--- XMP Relationship Test Results ---")
print(f"DocumentID: {results.get('ids', {}).get('documentID')}")
print(f"OriginalDocumentID: {results.get('ids', {}).get('originalDocumentID')}")
print(f"Derivation: {results.get('derivation')}")
print(f"Ingredients count: {len(results.get('ingredients', []))}")
print(f"Pantry count: {len(results.get('pantry', {}))}")
print("\nAnomalies found:")
for anomaly in results.get('anomalies', []):
    print(f"  [!] {anomaly}")

print("\nFull Results:")
import json
print(json.dumps(results, indent=2))

# Verify specific values
assert results['ids']['documentID'] == 'xmp.did:eb864506-8b35-4d7a-8b8a-8b8a8b8a8b8a'
assert results['ingredients'][0]['fromPart'] == 'time:0'
assert any("mismatch" in a for a in results['anomalies'])

print("\nSUCCESS: Basic parsing and anomaly detection verified.")
