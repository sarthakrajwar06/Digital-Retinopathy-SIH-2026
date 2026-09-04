"""
Module 1: Fundus Image Quality Assessment
Phase 1: Dataset Inventory & Inspection Module (Optimized Version).

Inspects image files with a SINGLE image decode via OpenCV:
- Computes SHA-256 for exact duplicates (streaming binary I/O)
- Dimensions, channels, and validity from single cv2.imread
- Fast grayscale verification (short-circuiting channel comparison)
- Perceptual dHash (16x16 thumbnail) via cv2.resize in < 1ms
- No redundant PIL opens or duplicate full-resolution array allocations
"""

import os
import hashlib
from collections import Counter
import cv2
import numpy as np


def compute_file_sha256(filepath):
    """
    Stream file bytes to compute SHA-256 hash without loading into memory.
    """
    hasher = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def inspect_decoded_image(img, filepath, file_hash=None):
    """
    OPTIMIZATION 1: Inspect an already-decoded OpenCV image array directly.
    Zero redundant decoding, microsecond execution.
    """
    filename = os.path.basename(filepath)
    ext = os.path.splitext(filename)[1].lower()
    file_size = os.path.getsize(filepath)
    
    if file_hash is None:
        file_hash = compute_file_sha256(filepath)
        
    if img is None:
        return {
            'filename': filename,
            'is_valid': False,
            'error': 'Failed to decode image with OpenCV',
            'file_format': ext.lstrip('.').upper(),
            'file_size_bytes': file_size,
            'width': None,
            'height': None,
            'aspect_ratio': None,
            'megapixels': None,
            'num_channels': None,
            'color_mode': None,
            'color_type': 'Corrupted',
            'is_grayscale': None,
            'sha256': file_hash,
            'dhash': None
        }
        
    if len(img.shape) == 2:
        h, w = img.shape
        num_channels = 1
        is_grayscale = True
        color_type = "Grayscale"
        mode = "L"
        gray_for_hash = img
    else:
        h, w, c = img.shape
        num_channels = c
        # Fast short-circuiting check if B == G == R without full array copy
        is_grayscale = bool(np.array_equal(img[:, :, 0], img[:, :, 1]) and np.array_equal(img[:, :, 1], img[:, :, 2]))
        color_type = "Grayscale-in-RGB" if is_grayscale else "RGB-TrueColor"
        mode = "BGR"
        gray_for_hash = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
    # Fast perceptual dHash (16x16 thumbnail)
    thumb = cv2.resize(gray_for_hash, (16, 16), interpolation=cv2.INTER_AREA)
    thumb_avg = float(thumb.mean())
    dhash = "".join(["1" if px > thumb_avg else "0" for px in thumb.ravel()])
    
    # Standard format name
    if ext == '.png':
        format_name = 'PNG'
    elif ext in ('.jpg', '.jpeg'):
        format_name = 'JPEG'
    else:
        format_name = ext.lstrip('.').upper()
        
    return {
        'filename': filename,
        'is_valid': True,
        'error': None,
        'file_format': format_name,
        'file_size_bytes': file_size,
        'width': w,
        'height': h,
        'aspect_ratio': round(w / h, 4) if h > 0 else 0,
        'megapixels': round((w * h) / 1e6, 3),
        'num_channels': num_channels,
        'color_mode': mode,
        'color_type': color_type,
        'is_grayscale': is_grayscale,
        'sha256': file_hash,
        'dhash': dhash
    }


def inspect_single_file(filepath):
    """
    Inspect a single file with a single OpenCV read (replaces slow PIL-based inspection).
    """
    file_hash = compute_file_sha256(filepath)
    img = cv2.imread(filepath)
    return inspect_decoded_image(img, filepath, file_hash=file_hash)
