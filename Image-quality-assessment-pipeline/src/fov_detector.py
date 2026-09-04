"""
Module 1: Fundus Image Quality Assessment
FOV (Field of View) and Retinal Mask Detector (Optimized Version).

Deterministic morphological detection of the retinal field, separating the active
retina from the unexposed camera background / black border.
Optimized to execute boundary detection, morphology, and geometric moments primarily
at scaled resolution (~512x512) before creating the full-resolution mask.
"""

import cv2
import numpy as np


def detect_retinal_fov(image_bgr, target_proc_size=512):
    """
    Detect the retinal field of view (FOV) mask deterministically.
    
    Parameters:
    -----------
    image_bgr : np.ndarray
        Input image in BGR format (H, W, 3) or Grayscale (H, W).
    target_proc_size : int
        Size for downscaled processing to ensure fast, scale-invariant morphology.
        
    Returns:
    --------
    dict containing:
        - 'mask': uint8 binary mask (H, W), 255 inside retina, 0 outside
        - 'mask_eroded': uint8 binary mask eroded to avoid edge boundary artifacts
        - 'retinal_area': int, number of foreground retinal pixels
        - 'image_area': int, total pixels (H * W)
        - 'fov_coverage': float, retinal_area / image_area
        - 'centroid': tuple (cx, cy)
        - 'radius_est': float, estimated radius of circular retina
        - 'bbox': tuple (x, y, w, h)
        - 'contour': ndarray, main retinal contour at original resolution
        - 'circularity': float, 4 * pi * area / perimeter^2
        - 'border_clipped': bool, True if retinal boundary touches image edges
    """
    if len(image_bgr.shape) == 2:
        h, w = image_bgr.shape
        gray = image_bgr
        max_c = gray
    else:
        h, w, _ = image_bgr.shape
        # In fundus images, the red channel has highest intensity in retina,
        # but max across channels handles atypical color balances cleanly
        max_c = np.maximum(np.maximum(image_bgr[:, :, 0], image_bgr[:, :, 1]), image_bgr[:, :, 2])

    total_pixels = h * w

    # Downscale for morphological segmentation
    scale = float(target_proc_size) / max(h, w)
    if scale < 1.0:
        small_c = cv2.resize(max_c, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    else:
        scale = 1.0
        small_c = max_c

    sh, sw = small_c.shape

    # Estimate background noise from the 4 corners (10x10 patches on small_c)
    patch_h = max(2, min(10, sh // 10))
    patch_w = max(2, min(10, sw // 10))
    corners = np.concatenate([
        small_c[:patch_h, :patch_w].ravel(),
        small_c[:patch_h, -patch_w:].ravel(),
        small_c[-patch_h:, :patch_w].ravel(),
        small_c[-patch_h:, -patch_w:].ravel()
    ])
    
    corner_mean = float(np.mean(corners))
    corner_p95 = float(np.percentile(corners, 95))

    # If corner mean is high (> 30), image is pre-cropped to retina with no black border
    if corner_mean > 30.0:
        full_mask = np.ones((h, w), dtype=np.uint8) * 255
        erode_px = max(5, int(min(h, w) * 0.015)) | 1
        k_erode = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (erode_px, erode_px))
        full_mask_eroded = cv2.erode(full_mask, k_erode)
        return {
            'mask': full_mask,
            'mask_eroded': full_mask_eroded,
            'retinal_area': total_pixels,
            'image_area': total_pixels,
            'fov_coverage': 1.0,
            'centroid': (w // 2, h // 2),
            'radius_est': min(w, h) / 2.0,
            'bbox': (0, 0, w, h),
            'contour': np.array([[[0, 0]], [[w - 1, 0]], [[w - 1, h - 1]], [[0, h - 1]]], dtype=np.int32),
            'circularity': 1.0,
            'border_clipped': True
        }

    # Deterministic thresholding adaptive to corner background level
    thresh_val = max(10.0, corner_p95 + 5.0)
    thresh_val = min(thresh_val, 25.0)  # upper bound guard
    _, binary = cv2.threshold(small_c, int(thresh_val), 255, cv2.THRESH_BINARY)

    # Morphological closing to seal vessels, fovea, lesions at 512x512 resolution
    k_size = max(5, int(15 * scale)) | 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_size, k_size))
    closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    # Find external contours and select largest connected component
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        full_mask = np.ones((h, w), dtype=np.uint8) * 255
        return {
            'mask': full_mask,
            'mask_eroded': full_mask,
            'retinal_area': total_pixels,
            'image_area': total_pixels,
            'fov_coverage': 1.0,
            'centroid': (w // 2, h // 2),
            'radius_est': min(w, h) / 2.0,
            'bbox': (0, 0, w, h),
            'contour': np.array([[[0, 0]], [[w - 1, 0]], [[w - 1, h - 1]], [[0, h - 1]]], dtype=np.int32),
            'circularity': 1.0,
            'border_clipped': True
        }

    main_contour = max(contours, key=cv2.contourArea)

    # Smooth contour with convex hull at 512x512
    hull = cv2.convexHull(main_contour)
    small_mask_hull = np.zeros((sh, sw), dtype=np.uint8)
    cv2.drawContours(small_mask_hull, [hull], -1, 255, -1)
    small_mask = small_mask_hull

    # OPTIMIZATION 2: Perform boundary erosion at scaled 512x512 resolution
    # Instead of running a 35x35 morphological kernel over 12 MP
    erode_size_small = max(3, int(min(sh, sw) * 0.012)) | 1
    k_erode_small = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (erode_size_small, erode_size_small))
    small_mask_eroded = cv2.erode(small_mask, k_erode_small)
    if np.count_nonzero(small_mask_eroded) < 50:
        small_mask_eroded = small_mask

    # Upsample both mask and eroded mask to original resolution
    mask = cv2.resize(small_mask, (w, h), interpolation=cv2.INTER_NEAREST)
    mask_eroded = cv2.resize(small_mask_eroded, (w, h), interpolation=cv2.INTER_NEAREST)

    # Retinal area & coverage
    retinal_area = int(np.count_nonzero(mask))
    fov_coverage = float(retinal_area) / float(total_pixels)
    radius_est = float(np.sqrt(retinal_area / np.pi))

    # OPTIMIZATION 2: Compute geometric moments and contour properties at 512x512
    inv_scale_x = float(w) / float(sw)
    inv_scale_y = float(h) / float(sh)
    
    M = cv2.moments(hull)
    if M["m00"] > 0:
        cx = int(round((M["m10"] / M["m00"]) * inv_scale_x))
        cy = int(round((M["m01"] / M["m00"]) * inv_scale_y))
    else:
        cx, cy = w // 2, h // 2
        
    bx_s, by_s, bw_s, bh_s = cv2.boundingRect(hull)
    bx = int(round(bx_s * inv_scale_x))
    by = int(round(by_s * inv_scale_y))
    bw = int(round(bw_s * inv_scale_x))
    bh = int(round(bh_s * inv_scale_y))
    
    perimeter_s = cv2.arcLength(hull, True)
    area_s = cv2.contourArea(hull)
    circularity = (4.0 * np.pi * area_s / (perimeter_s * perimeter_s)) if perimeter_s > 0 else 0.0

    # Scale contour to original resolution for visual inspection
    orig_contour = np.round(hull.astype(np.float32) * np.array([[[inv_scale_x, inv_scale_y]]])).astype(np.int32)

    # Border clipping check
    border_clipped = (bx <= 3) or (by <= 3) or (bx + bw >= w - 3) or (by + bh >= h - 3)

    return {
        'mask': mask,
        'mask_eroded': mask_eroded,
        'retinal_area': retinal_area,
        'image_area': total_pixels,
        'fov_coverage': fov_coverage,
        'centroid': (cx, cy),
        'radius_est': radius_est,
        'bbox': (bx, by, bw, bh),
        'contour': orig_contour,
        'circularity': float(circularity),
        'border_clipped': bool(border_clipped)
    }
