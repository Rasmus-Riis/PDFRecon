import re
import logging
import xml.etree.ElementTree as ET
from typing import Dict, List, Any, Optional, Set

class XMPRelationshipManager:
    """
    Parses and manages XMP Media Management relationships.
    Reconstructs document derivation history and asset composition.
    """
    
    # Namespaces
    NS = {
        'xmp': 'http://ns.adobe.com/xap/1.0/',
        'xmpMM': 'http://ns.adobe.com/xap/1.0/mm/',
        'stRef': 'http://ns.adobe.com/xap/1.0/sType/ResourceRef#',
        'stEvt': 'http://ns.adobe.com/xap/1.0/sType/ResourceEvent#',
        'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'
    }

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def parse_xmp(self, xmp_str: str) -> Dict[str, Any]:
        """
        Parses an XMP packet string and extracts Media Management metadata.
        """
        result: Dict[str, Any] = {
            'ids': {},
            'derivation': None,
            'ingredients': [],
            'pantry': {},
            'anomalies': []
        }

        try:
            # Strip XMP packet wrappers if present
            xmp_content = re.sub(r'<\?xpacket.*?\?>', '', xmp_str, flags=re.S).strip()
            if not xmp_content:
                return result

            root = ET.fromstring(xmp_content)
            
            # Extract basic IDs
            ids: Dict[str, str] = {}
            self._extract_ids(root, ids)
            result['ids'] = ids
            
            # Extract DerivedFrom
            result['derivation'] = self._extract_derived_from(root)
            
            # Extract Ingredients
            result['ingredients'] = self._extract_ingredients(root)
            
            # Extract Pantry (Recursive XMP packets)
            result['pantry'] = self._extract_pantry(root)
            
            # Check for anomalies
            self._check_anomalies(result)

        except Exception as e:
            self.logger.warning(f"Error parsing XMP relationship data: {e}")
            anomalies = result.get('anomalies')
            if isinstance(anomalies, list):
                anomalies.append(f"Parsing Error: {str(e)}")

        return result

    def _extract_ids(self, root: ET.Element, ids_dict: Dict[str, str]):
        """Extract primary XMP identifiers."""
        # Mapping of our internal keys to multiple possible XMP tags/attributes
        mapping = {
            'documentID': ['xmpMM:DocumentID', 'DocumentID'],
            'instanceID': ['xmpMM:InstanceID', 'InstanceID'],
            'originalDocumentID': ['xmpMM:OriginalDocumentID', 'OriginalDocumentID']
        }
        
        for desc in root.findall('.//rdf:Description', self.NS):
            for target_key, xmp_variants in mapping.items():
                if target_key in ids_dict and ids_dict[target_key]:
                    continue
                
                # Check child elements
                for variant in xmp_variants:
                    tag = variant if ':' in variant else f"xmpMM:{variant}"
                    # Use .// for recursive search to handle nested rdf:li/etc.
                    child = desc.find(f".//{tag}", self.NS)
                    if child is not None and child.text:
                        ids_dict[target_key] = str(child.text).strip()
                        break
                
                if target_key in ids_dict and ids_dict[target_key]:
                    continue
                    
                # Check attributes
                for variant in xmp_variants:
                    attr_name = variant.split(':')[-1]
                    val = desc.get(f"{{{self.NS['xmpMM']}}}{attr_name}")
                    if val:
                        ids_dict[target_key] = val.strip()
                        break

    def _extract_derived_from(self, root: ET.Element) -> Optional[Dict[str, str]]:
        """Extract xmpMM:DerivedFrom property."""
        df_elem = root.find('.//xmpMM:DerivedFrom', self.NS)
        if df_elem is None:
            for desc in root.findall('.//rdf:Description', self.NS):
                df_elem = desc.find('xmpMM:DerivedFrom', self.NS)
                if df_elem is not None:
                    break
        
        if df_elem is not None:
            res: Dict[str, str] = {}
            # Check for stRef properties inside (either as attributes or children)
            for key in ['documentID', 'instanceID', 'originalDocumentID', 'fromPart', 'toPart']:
                # As attribute
                val = df_elem.get(f"{{{self.NS['stRef']}}}{key}")
                if val:
                    res[key] = val
                else:
                    # As child
                    child = df_elem.find(f".//stRef:{key}", self.NS)
                    if child is not None and child.text:
                        res[key] = str(child.text).strip()
            return res if res else None
        return None

    def _extract_ingredients(self, root: ET.Element) -> List[Dict[str, Any]]:
        """Extract xmpMM:Ingredients array."""
        ingredients = []
        ing_elem = root.find('.//xmpMM:Ingredients', self.NS)
        if ing_elem is None:
            for desc in root.findall('.//rdf:Description', self.NS):
                ing_elem = desc.find('xmpMM:Ingredients', self.NS)
                if ing_elem is not None:
                    break
                    
        if ing_elem is not None:
            for bag in ing_elem.findall('.//rdf:Bag', self.NS) + ing_elem.findall('.//rdf:Seq', self.NS):
                for li in bag.findall('./rdf:li', self.NS):
                    ref: Dict[str, Any] = {}
                    for key in ['documentID', 'instanceID', 'filePath', 'fromPart', 'toPart']:
                        # Check attribute or child
                        val = li.get(f"{{{self.NS['stRef']}}}{key}")
                        if val:
                            ref[key] = val
                        else:
                            child = li.find(f".//stRef:{key}", self.NS)
                            if child is not None and child.text:
                                ref[key] = str(child.text).strip()
                    if ref:
                        ingredients.append(ref)
        return ingredients

    def _extract_pantry(self, root: ET.Element) -> Dict[str, Dict[str, Any]]:
        """Extract xmpMM:Pantry array containing complete embedded XMP packets."""
        pantry: Dict[str, Dict[str, Any]] = {}
        pantry_elem = root.find('.//xmpMM:Pantry', self.NS)
        if pantry_elem is None:
            for desc in root.findall('.//rdf:Description', self.NS):
                pantry_elem = desc.find('xmpMM:Pantry', self.NS)
                if pantry_elem is not None:
                    break
                    
        if pantry_elem is not None:
            for bag in pantry_elem.findall('.//rdf:Bag', self.NS) + pantry_elem.findall('.//rdf:Seq', self.NS):
                for li in bag.findall('rdf:li', self.NS):
                    # An item in the pantry can be an rdf:Description or just children if parseType="Resource"
                    # We'll treat the li or its Description child as the source
                    source = li.find('rdf:Description', self.NS)
                    if source is None:
                        source = li
                    
                    # Look for InstanceID to use as key
                    instance_id = source.get(f"{{{self.NS['xmpMM']}}}InstanceID")
                    if not instance_id:
                        child = source.find('.//xmpMM:InstanceID', self.NS)
                        if child is not None and child.text:
                            instance_id = str(child.text).strip()
                    
                    if instance_id:
                        try:
                            # Re-construct a mini-XMP for recursive parsing
                            inner_content = ET.tostring(source, encoding='unicode')
                            # Ensure we have the correct wrapper for parse_xmp
                            wrapped = (
                                f"<x:xmpmeta xmlns:x='adobe:ns:meta/' "
                                f"xmlns:rdf='{self.NS['rdf']}' "
                                f"xmlns:xmpMM='{self.NS['xmpMM']}' "
                                f"xmlns:stRef='{self.NS['stRef']}'>"
                                f"<rdf:RDF><rdf:Description>{inner_content}</rdf:Description></rdf:RDF></x:xmpmeta>"
                            )
                            pantry[instance_id] = self.parse_xmp(wrapped)
                        except Exception as e:
                            self.logger.error(f"Failed to parse pantry item {instance_id}: {e}")
        return pantry

    def _check_anomalies(self, result: Dict[str, Any]):
        """Flag forensic anomalies in the relationship data."""
        pantry_ids: Set[str] = set(result['pantry'].keys())
        anomalies: List[str] = result.get('anomalies', [])
        
        # 1. Missing Pantry Items
        ingredients = result.get('ingredients', [])
        for ing in ingredients:
            iid = ing.get('instanceID')
            if iid and iid not in pantry_ids:
                anomalies.append(f"Missing Pantry item for ingredient: {iid}")

        # 2. OriginalDocumentID Mismatch
        ids = result.get('ids', {})
        primary_orig_id = ids.get('originalDocumentID')
        derivation = result.get('derivation')
        if primary_orig_id and derivation and derivation.get('originalDocumentID'):
            if primary_orig_id != derivation['originalDocumentID']:
                anomalies.append(f"OriginalDocumentID mismatch with parent: {primary_orig_id} vs {derivation['originalDocumentID']}")
        
        # 3. DocumentID vs Pantry consistency
        for iid, pdata in result['pantry'].items():
            for ing in ingredients:
                if ing.get('instanceID') == iid:
                    if ing.get('documentID') and pdata.get('ids', {}).get('documentID'):
                        if ing['documentID'] != pdata['ids']['documentID']:
                            anomalies.append(f"Ingredient DocumentID mismatch for {iid}: {ing['documentID']} vs {pdata['ids']['documentID']}")
                            
        result['anomalies'] = anomalies

    def get_ancestry(self, xmp_data: Dict[str, Any]) -> List[str]:
        """Returns the chain of DocumentIDs in the derivation history."""
        chain: List[str] = []
        curr: Any = xmp_data
        
        while isinstance(curr, dict) and curr.get('derivation'):
            derivation = curr.get('derivation')
            if not isinstance(derivation, dict):
                break
                
            parent_id = derivation.get('documentID')
            if isinstance(parent_id, str):
                chain.append(parent_id)
                # If we have the parent's XMP in the pantry, we could continue
                parent_instance = derivation.get('instanceID')
                pantry = curr.get('pantry', {})
                if isinstance(parent_instance, str) and isinstance(pantry, dict) and parent_instance in pantry:
                    curr = pantry[parent_instance]
                else:
                    break
            else:
                break
        return chain

