"""
JPEG Forensics - Quantization Table Analysis

Detects manipulated or fake scanned images by analyzing JPEG quantization tables.
Different cameras, scanners, and software leave distinct "fingerprints" in QT data.
"""

import re
import logging
import hashlib
from pathlib import Path


# Known Quantization Table signatures (first 8 values of luminance table)
KNOWN_QT_SIGNATURES = {
    # Adobe Photoshop signatures
    '03020202020303020202030302030303': 'Photoshop Quality 100 (Maximum)',
    '05030404030504040404050706050404': 'Photoshop Quality 95-98',
    '08050505050705080809090a0a0a090a': 'Photoshop Quality 90',
    '0c08080a080c0c0c0c0c0c0c0c0c0c0c': 'Photoshop Quality 80',
    '1812121518181c181c1c1c1c1c1c1c1c': 'Photoshop Quality 60 (Save for Web common)',
    '28191f1f1f1f1f28282828282828282': 'Photoshop Quality 40-50 (High compression)',
    
    # GIMP signatures
    '03020203030203030303030304030403': 'GIMP Quality 100',
    '06040406060604060606060708070606': 'GIMP Quality 95',
    '09060609090609090909090a0b0a0909': 'GIMP Quality 90',
    
    # Common scanner signatures
    '02020202020202020202020202020202': 'Generic Scanner (Very low compression)',
    '04030403040504040404050706050404': 'HP Scanner (Standard quality)',
    '06040506050506060606070908070606': 'Canon Scanner (Standard)',
    '08060608080608080808090b0a090808': 'Epson Scanner (Standard)',
    
    # Camera signatures (examples - real cameras have more variation)
    '0202020202020202020202020202020': 'Suspicious: All identical values (possibly forged)',
    '01010101010101010101010101010101': 'Critical: QT=1 (Invalid - likely manipulated)',
}


def extract_jpeg_qt_from_bytes(jpeg_bytes: bytes) -> dict:
    """
    Extract quantization table from JPEG data.
    
    Args:
        jpeg_bytes (bytes): Raw JPEG image data
        
    Returns:
        dict: Quantization table info including signature and match
    """
    try:
        # JPEG markers: SOI=0xFFD8, DQT=0xFFDB
        if not jpeg_bytes.startswith(b'\xff\xd8'):
            return {'error': 'Not a valid JPEG (missing SOI marker)'}
        
        # Find DQT (Define Quantization Table) marker
        dqt_pattern = b'\xff\xdb'
        dqt_pos = jpeg_bytes.find(dqt_pattern)
        
        if dqt_pos == -1:
            return {'error': 'No quantization table found'}
        
        # DQT structure: FF DB [length 2 bytes] [precision+table_id 1 byte] [64 bytes of QT data]
        dqt_start = dqt_pos + 2  # Skip FF DB
        
        # Read length (big-endian)
        if dqt_start + 2 > len(jpeg_bytes):
            return {'error': 'Truncated DQT marker'}
        
        length = (jpeg_bytes[dqt_start] << 8) | jpeg_bytes[dqt_start + 1]
        
        # Read precision/table ID byte
        if dqt_start + 3 > len(jpeg_bytes):
            return {'error': 'Truncated DQT data'}
        
        prec_table = jpeg_bytes[dqt_start + 2]
        precision = (prec_table >> 4) & 0x0F  # High nibble
        table_id = prec_table & 0x0F  # Low nibble
        
        # Read QT values (64 bytes for 8-bit precision, 128 for 16-bit)
        qt_start = dqt_start + 3
        qt_size = 64 if precision == 0 else 128
        
        if qt_start + qt_size > len(jpeg_bytes):
            return {'error': 'Truncated quantization table'}
        
        qt_values = list(jpeg_bytes[qt_start:qt_start + qt_size])
        
        # Create signature from first 16 values (most distinctive)
        signature = ''.join(f'{v:02x}' for v in qt_values[:16])
        
        # Check against known signatures
        match = KNOWN_QT_SIGNATURES.get(signature, None)
        
        # Calculate hash of full QT for uniqueness
        qt_hash = hashlib.md5(bytes(qt_values)).hexdigest()[:16]
        
        # Analyze QT characteristics
        qt_min = min(qt_values)
        qt_max = max(qt_values)
        qt_avg = sum(qt_values) / len(qt_values)
        qt_uniformity = len(set(qt_values))  # Number of unique values
        
        # Detect suspicious patterns
        warnings = []
        
        if qt_min == qt_max:
            warnings.append('CRITICAL: All QT values identical (likely forged)')
        elif qt_uniformity < 10:
            warnings.append('SUSPICIOUS: Very low QT diversity (unusual for real camera/scanner)')
        elif qt_min < 2:
            warnings.append('SUSPICIOUS: QT values below 2 (unusual compression)')
        elif qt_max > 250:
            warnings.append('WARNING: Very high QT values (extreme compression)')
        
        # Check for common editing software patterns
        if any(sig in signature for sig in ['181818', '1c1c1c', '282828']):
            if not match:
                warnings.append('Pattern matches Photoshop-style compression')
        
        return {
            'signature': signature,
            'match': match,
            'qt_hash': qt_hash,
            'table_id': table_id,
            'precision': '8-bit' if precision == 0 else '16-bit',
            'min': qt_min,
            'max': qt_max,
            'avg': round(qt_avg, 1),
            'unique_values': qt_uniformity,
            'warnings': warnings,
            'full_qt': qt_values[:64]  # First 64 values (luminance table)
        }
        
    except Exception as e:
        return {'error': f'QT extraction failed: {str(e)}'}


def analyze_pdf_images_qt(doc, filepath: Path, indicators: dict):
    """
    Analyze all JPEG images in a PDF for quantization table signatures.
    
    Args:
        doc: PyMuPDF document object
        filepath (Path): Path to PDF file
        indicators (dict): Dictionary to add indicators to
    """
    try:
        if not doc:
            return
        
        images_analyzed = []
        suspicious_images = []
        
        for page_num in range(len(doc)):
            try:
                page = doc[page_num]
                images = page.get_images(full=True)
                
                for img_index, img in enumerate(images):
                    try:
                        xref = img[0]  # Image xref number
                        
                        # Extract image
                        base_image = doc.extract_image(xref)
                        
                        if not base_image or base_image.get('ext') != 'jpeg':
                            continue
                        
                        image_bytes = base_image['image']
                        
                        # Analyze QT
                        qt_info = extract_jpeg_qt_from_bytes(image_bytes)
                        
                        if 'error' in qt_info:
                            continue
                        
                        img_data = {
                            'page': page_num + 1,
                            'xref': xref,
                            'size_kb': len(image_bytes) / 1024,
                            'qt_info': qt_info
                        }
                        
                        images_analyzed.append(img_data)
                        
                        # Check for suspicious patterns
                        if qt_info.get('warnings') or qt_info.get('match'):
                            suspicious_images.append(img_data)
                            
                    except Exception as e:
                        logging.debug(f"Error analyzing image {img_index} on page {page_num + 1}: {e}")
                        continue
                        
            except Exception as e:
                logging.debug(f"Error processing page {page_num + 1}: {e}")
                continue
        
        # Report findings
        if images_analyzed:
            indicators['JPEG_Analysis'] = {
                'total_jpegs': len(images_analyzed),
                'suspicious_count': len(suspicious_images)
            }
            
            if suspicious_images:
                details = []
                for img in suspicious_images[:5]:  # Limit to first 5
                    qt = img['qt_info']
                    detail = f"Page {img['page']}, xref {img['xref']}"
                    
                    if qt.get('match'):
                        detail += f" - {qt['match']}"
                    
                    if qt.get('warnings'):
                        detail += f" - {'; '.join(qt['warnings'])}"
                    
                    details.append(detail)
                
                indicators['JPEG_Analysis']['suspicious_details'] = details
                indicators['JPEG_Analysis']['note'] = 'Suspicious JPEG compression patterns detected - may indicate edited/fake scan'
                
                logging.warning(f"Suspicious JPEG images found in {filepath.name}: {len(suspicious_images)} of {len(images_analyzed)}")
            
    except Exception as e:
        logging.debug(f"Error in JPEG QT analysis: {e}")


def analyze_office_images_qt(image_data: bytes, image_name: str) -> dict:
    """
    Analyze a single image from an Office document.
    
    Args:
        image_data (bytes): Raw image data
        image_name (str): Name/identifier of the image
        
    Returns:
        dict: Analysis results
    """
    try:
        # Check if it's a JPEG
        if not image_data.startswith(b'\xff\xd8'):
            return {'analyzed': False, 'reason': 'Not a JPEG image'}
        
        qt_info = extract_jpeg_qt_from_bytes(image_data)
        
        if 'error' in qt_info:
            return {'analyzed': False, 'error': qt_info['error']}
        
        result = {
            'analyzed': True,
            'image_name': image_name,
            'size_kb': round(len(image_data) / 1024, 1),
            'qt_signature': qt_info['signature'],
            'qt_hash': qt_info['qt_hash'],
            'suspected_source': qt_info.get('match', 'Unknown'),
            'warnings': qt_info.get('warnings', []),
            'qt_stats': {
                'min': qt_info['min'],
                'max': qt_info['max'],
                'avg': qt_info['avg'],
                'unique_values': qt_info['unique_values']
            }
        }
        
        # Determine suspicion level
        if qt_info.get('warnings'):
            result['suspicion_level'] = 'HIGH' if any('CRITICAL' in w for w in qt_info['warnings']) else 'MEDIUM'
        elif qt_info.get('match') and 'Photoshop' in qt_info['match']:
            result['suspicion_level'] = 'MEDIUM'
            result['warnings'].append('Image uses Photoshop-style compression (may not be original scan)')
        else:
            result['suspicion_level'] = 'LOW'
        
        return result
        
    except Exception as e:
        return {'analyzed': False, 'error': str(e)}
