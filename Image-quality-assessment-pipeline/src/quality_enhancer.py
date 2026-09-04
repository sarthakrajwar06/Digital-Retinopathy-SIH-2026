"""
Module 1B: Borderline Fundus Image Quality Enhancement for SIH26038.

This module provides reproducible, bounded, explainable, and non-hallucinating
enhancement operations strictly targeted to BORDERLINE fundus images.

Core Protocol & Architectural Rules:
1. Gating / Routing:
   - NON-CRITICAL (GRADABLE): 100% enhancement bypass -> OK TO GO (original image preserved).
   - CRITICAL (NON_GRADABLE): 100% enhancement bypass -> RECAPTURE (no enhancement).
   - BORDERLINE: Targeted deterministic enhancement -> Module 1A Reassessment -> Final Decision.
2. Targeted Enhancement Methods:
   - Low contrast -> CLAHE on L-channel in CIELAB
   - Uneven illumination -> background illumination estimation + normalization
   - Mild underexposure -> conservative gamma correction on L-channel
   - Mild overexposure -> controlled highlight intensity compression (saturated pixels cannot be recovered)
   - Moderate noise -> mild edge-preserving bilateral filtering
   - Mild blur -> conservative sharpening only (severe blur is NEVER sharpened -> RECAPTURE)
   - Glare / specular artifacts -> punctate glare inpainting (< 250 px only; severe glare -> RECAPTURE)
   - Poor FOV -> RECAPTURE (do not hallucinate missing retinal content)
3. Operational Bounds & Processing Order:
   - MAX_OPERATIONS_PER_ATTEMPT = 2
   - MAX_ENHANCEMENT_ATTEMPTS = 2
   - Preferred processing order:
     1. Mild illumination correction
     2. Mild denoising
     3. CLAHE
     4. Gamma correction / intensity compression
     5. Conservative sharpening
     6. Module 1A reassessment
4. Comprehensive Safety Checks:
   - Pixel values strictly in [0, 255] uint8, finite
   - Retinal FOV preserved and not deteriorated
   - Saturation not excessively increased
   - Noise not substantially increased
   - Contrast not artificially exploded (RMS <= 45.0)
   - Focus not deteriorated
   - Hard failures strictly enforced (never overridden)
   - Any degradation detected triggers immediate rejection -> CRITICAL / RECAPTURE
5. Authority:
   - Module 1A assessment is NEVER bypassed and remains the sole authority.
"""

import math
import os
import time
import numpy as np
import cv2

from src.config import (
    ENHANCEMENT_CONFIG,
    MAX_ENHANCEMENT_ATTEMPTS,
    MAX_OPERATIONS_PER_ATTEMPT,
    MIN_DIMENSION_SCORE_BORDERLINE,
    MIN_DIMENSION_SCORE_NON_CRITICAL,
    CRITICAL_SCORE_THRESHOLD,
    BORDERLINE_SCORE_THRESHOLD,
    ARTIFACT_GLARE_BLOB_NON_CRITICAL_MAX,
    HARD_FAILURES,
    PROVISIONAL_BOUNDARIES
)
from src.fov_detector import detect_retinal_fov
from src.quality_metrics import compute_image_quality_metrics
from src.quality_classifier import classify_fundus_image_quality


# =====================================================================
# 1. DETERMINISTIC ENHANCEMENT PRIMITIVES
# =====================================================================

def apply_clahe(image_bgr, fov_mask, clip_limit=None, tile_grid_size=None):
    """
    A. Contrast Enhancement via Contrast-Limited Adaptive Histogram Equalization.
    Applied exclusively to the Lightness (L) channel in CIELAB color space inside
    the retinal FOV mask to avoid color shift or noise over-amplification.
    """
    cfg = ENHANCEMENT_CONFIG
    clip = float(clip_limit) if clip_limit is not None else cfg['clahe_clip_limit']
    clip = min(clip, cfg['clahe_clip_limit_max'])
    grid = tile_grid_size if tile_grid_size is not None else cfg['clahe_tile_grid_size']

    lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB)
    L = lab[:, :, 0]
    
    clahe = cv2.createCLAHE(clipLimit=clip, tileGridSize=grid)
    L_clahe = clahe.apply(L)
    
    # Strictly mask to retinal field
    mask_bool = fov_mask > 0
    lab[:, :, 0] = np.where(mask_bool, L_clahe, L)
    
    enhanced = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    enhanced[~mask_bool] = image_bgr[~mask_bool]
    
    details = {
        'operation': 'CLAHE',
        'clip_limit': clip,
        'tile_grid_size': grid
    }
    return enhanced, details


def apply_gamma_correction(image_bgr, fov_mask, gamma=None, retinal_mean=None):
    """
    B. Bounded Exposure / Intensity Correction (Mild Underexposure / Mild Overexposure).
    Lifts underexposed midtones (gamma < 1.0) or gently tones down mild
    overexposure (gamma > 1.0) via luminance channel mapping.
    
    NOTE: Saturated pixels (sensor clipping at 255) cannot be recovered.
    This operation adjusts the distribution of non-saturated midtones.
    """
    cfg = ENHANCEMENT_CONFIG
    if gamma is None:
        if retinal_mean is not None and retinal_mean > 110.0:
            g = cfg['gamma_overexposed']
        else:
            g = cfg['gamma_underexposed']
    else:
        g = float(gamma)
        
    g = float(np.clip(g, cfg['gamma_min'], cfg['gamma_max']))
    
    # Apply to L channel of LAB to preserve chromaticity ratios
    lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB)
    L = lab[:, :, 0].astype(np.float32) / 255.0
    
    # Power-law transform
    L_gamma = np.power(L, g) * 255.0
    L_gamma = np.clip(L_gamma, 0, 255).astype(np.uint8)
    
    mask_bool = fov_mask > 0
    lab[:, :, 0] = np.where(mask_bool, L_gamma, lab[:, :, 0])
    
    enhanced = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    enhanced[~mask_bool] = image_bgr[~mask_bool]
    
    details = {
        'operation': 'gamma_correction',
        'gamma': round(g, 3),
        'direction': 'lift_underexposed' if g < 1.0 else 'tone_down_overexposed'
    }
    return enhanced, details


def apply_intensity_compression(image_bgr, fov_mask, factor=None):
    """
    C. Controlled Highlight Intensity Compression (Mild Overexposure).
    Softly compresses non-saturated highlight midtones to reduce diffuse bleaching.
    
    CLINICAL / PHYSICAL DISCLAIMER:
    Saturated pixels (>240 or 255) cannot be recovered because sensor optical
    information was permanently clipped during image capture. This deterministic
    operation compresses high-luminance midtones without claiming recovery of blown-out tissue.
    """
    f = float(factor) if factor is not None else 0.18
    f = float(np.clip(f, 0.05, 0.35))
    
    lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB)
    L = lab[:, :, 0].astype(np.float32) / 255.0
    
    # Soft highlight shoulder compression: L_out = L / (1.0 + f * L^2)
    L_comp = L / (1.0 + f * (L ** 2))
    L_comp = np.clip(L_comp * 255.0, 0, 255).astype(np.uint8)
    
    mask_bool = fov_mask > 0
    lab[:, :, 0] = np.where(mask_bool, L_comp, lab[:, :, 0])
    
    enhanced = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    enhanced[~mask_bool] = image_bgr[~mask_bool]
    
    details = {
        'operation': 'intensity_compression',
        'compression_factor': round(f, 3),
        'clinical_note': 'Highlight midtones compressed; saturated pixels remain unrecovered'
    }
    return enhanced, details


def apply_illumination_correction(image_bgr, fov_mask, gain_min=None, gain_max=None):
    """
    D. Deterministic Illumination Normalization / Flat-Fielding.
    Estimates the low-frequency background shading map via normalized Gaussian
    convolution and compensates for radial pupil vignetting inside the retinal field.
    """
    cfg = ENHANCEMENT_CONFIG
    g_min = float(gain_min) if gain_min is not None else cfg['illum_gain_min']
    g_max = float(gain_max) if gain_max is not None else cfg['illum_gain_max']
    
    h, w = image_bgr.shape[:2]
    mask_bool = fov_mask > 0
    mask_f = mask_bool.astype(np.float32)
    
    lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB)
    L = lab[:, :, 0].astype(np.float32)
    
    # Low-frequency illumination estimation using normalized convolution
    # Resolution-invariant optimization: downsample to proc_size=512 for smooth shading map
    max_dim = max(w, h)
    proc_size = 512
    if max_dim > proc_size:
        scale = float(proc_size) / max_dim
        small_L = cv2.resize(L * mask_f, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        small_M = cv2.resize(mask_f, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        sigma = proc_size * cfg['illum_filter_sigma_fraction']
        L_blur = cv2.GaussianBlur(small_L, (0, 0), sigma)
        M_blur = cv2.GaussianBlur(small_M, (0, 0), sigma)
        valid = M_blur > 1e-4
        small_bg = np.zeros_like(small_L)
        small_bg[valid] = L_blur[valid] / M_blur[valid]
        background = cv2.resize(small_bg, (w, h), interpolation=cv2.INTER_LINEAR)
    else:
        sigma = max_dim * cfg['illum_filter_sigma_fraction']
        L_masked = L * mask_f
        L_blur = cv2.GaussianBlur(L_masked, (0, 0), sigma)
        M_blur = cv2.GaussianBlur(mask_f, (0, 0), sigma)
        background = np.zeros_like(L)
        valid = M_blur > 1e-4
        background[valid] = L_blur[valid] / M_blur[valid]
    
    # Global retinal mean luminance target
    retina_pixels = L[mask_bool]
    target_mean = float(np.mean(retina_pixels)) if len(retina_pixels) > 0 else 100.0
    
    # Flat-field correction gain
    gain = np.ones_like(L)
    gain[mask_bool] = target_mean / np.maximum(10.0, background[mask_bool])
    gain = np.clip(gain, g_min, g_max)
    
    L_corr = np.clip(L * gain, 0, 255).astype(np.uint8)
    lab[:, :, 0] = np.where(mask_bool, L_corr, lab[:, :, 0])
    
    enhanced = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    enhanced[~mask_bool] = image_bgr[~mask_bool]
    
    details = {
        'operation': 'illumination_normalization',
        'gain_min': g_min,
        'gain_max': g_max,
        'sigma': round(sigma, 1)
    }
    return enhanced, details


def apply_denoising(image_bgr, fov_mask, d=None, sigma_color=None, sigma_space=None):
    """
    E. Controlled Edge-Preserving Denoising.
    Applies bilateral filtering strictly inside the retinal mask to attenuate
    sensor grain while preserving microvascular edges and retinal boundaries.
    """
    cfg = ENHANCEMENT_CONFIG
    diameter = int(d) if d is not None else cfg['denoise_diameter']
    s_col = float(sigma_color) if sigma_color is not None else cfg['denoise_sigma_color']
    s_col = min(s_col, cfg['denoise_sigma_color_max'])
    s_sp = float(sigma_space) if sigma_space is not None else cfg['denoise_sigma_space']
    s_sp = min(s_sp, cfg['denoise_sigma_space_max'])
    
    denoised = cv2.bilateralFilter(image_bgr, d=diameter, sigmaColor=s_col, sigmaSpace=s_sp)
    
    mask_bool = fov_mask > 0
    enhanced = image_bgr.copy()
    enhanced[mask_bool] = denoised[mask_bool]
    
    details = {
        'operation': 'bilateral_denoising',
        'diameter': diameter,
        'sigma_color': s_col,
        'sigma_space': s_sp
    }
    return enhanced, details


def apply_mild_sharpening(image_bgr, fov_mask, amount=None, sigma=None):
    """
    F. Conservative Unsharp Masking.
    Applied strictly to mildly blurred images to enhance microvascular contrast
    without introducing edge-ringing artifacts or synthetic structures.
    NOTE: Never applied to severely blurred images (severe blur -> RECAPTURE).
    """
    cfg = ENHANCEMENT_CONFIG
    amt = float(amount) if amount is not None else cfg['sharpen_amount']
    amt = min(amt, cfg['sharpen_amount_max'])
    sig = float(sigma) if sigma is not None else cfg['sharpen_kernel_sigma']
    
    blurred = cv2.GaussianBlur(image_bgr, (0, 0), sig)
    edge_residual = image_bgr.astype(np.float32) - blurred.astype(np.float32)
    
    sharpened = image_bgr.astype(np.float32) + amt * edge_residual
    sharpened = np.clip(sharpened, 0, 255).astype(np.uint8)
    
    mask_bool = fov_mask > 0
    enhanced = image_bgr.copy()
    enhanced[mask_bool] = sharpened[mask_bool]
    
    details = {
        'operation': 'unsharp_masking',
        'amount': amt,
        'sigma': sig
    }
    return enhanced, details


def apply_glare_inpaint(image_bgr, fov_mask, max_area=None, radius=None):
    """
    G. Punctate Specular Glare Inpainting.
    Restricted strictly to small punctate flash reflections (< 250 px).
    Interpolates tiny saturated spots from adjacent retinal pixels using
    Navier-Stokes/Telea inpainting without synthesizing retinal structures.
    Large glare patches (> 250 px) remain untouched and trigger RECAPTURE.
    """
    cfg = ENHANCEMENT_CONFIG
    max_a = int(max_area) if max_area is not None else cfg['glare_max_blob_area_recoverable']
    rad = int(radius) if radius is not None else cfg['glare_inpaint_radius']
    
    mask_bool = fov_mask > 0
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    sat_pixels = (gray > 240) & mask_bool
    
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(sat_pixels.astype(np.uint8))
    
    inpaint_mask = np.zeros_like(sat_pixels, dtype=np.uint8)
    recovered_blob_count = 0
    
    for i in range(1, num_labels):
        blob_area = stats[i, cv2.CC_STAT_AREA]
        if blob_area <= max_a:
            inpaint_mask[labels == i] = 255
            recovered_blob_count += 1
            
    if recovered_blob_count > 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (max(3, rad | 1), max(3, rad | 1)))
        inpaint_mask = cv2.dilate(inpaint_mask, k) & mask_bool.astype(np.uint8) * 255
        enhanced = cv2.inpaint(image_bgr, inpaint_mask, rad, cv2.INPAINT_TELEA)
        enhanced[~mask_bool] = image_bgr[~mask_bool]
    else:
        enhanced = image_bgr.copy()
        
    details = {
        'operation': 'glare_attenuation',
        'recovered_blobs': recovered_blob_count,
        'max_area_threshold': max_a
    }
    return enhanced, details


def apply_operation(image_bgr, fov_mask, op_name, params=None, retinal_mean=None):
    """Dispatches operation by name to underlying conservative primitive."""
    if params is None:
        p = {}
    else:
        p = dict(params)
        
    if op_name == 'illumination_normalization':
        return apply_illumination_correction(image_bgr, fov_mask, **p)
    elif op_name == 'bilateral_denoising':
        return apply_denoising(image_bgr, fov_mask, **p)
    elif op_name == 'CLAHE':
        return apply_clahe(image_bgr, fov_mask, **p)
    elif op_name == 'gamma_correction':
        if 'retinal_mean' not in p:
            p['retinal_mean'] = retinal_mean
        return apply_gamma_correction(image_bgr, fov_mask, **p)
    elif op_name == 'intensity_compression':
        return apply_intensity_compression(image_bgr, fov_mask, **p)
    elif op_name == 'unsharp_masking':
        return apply_mild_sharpening(image_bgr, fov_mask, **p)
    elif op_name == 'glare_attenuation':
        return apply_glare_inpaint(image_bgr, fov_mask, **p)
    else:
        return image_bgr.copy(), {'operation': op_name, 'status': 'skipped_unknown'}


# =====================================================================
# 2. ENHANCEMENT SELECTION LOGIC
# =====================================================================

def select_targeted_operations(classification, attempt=1, previous_operations=None):
    """
    Selects at most MAX_OPERATIONS_PER_ATTEMPT (2) targeted enhancement operations
    justified by the actual quality deficiencies present in classification.
    
    Adheres strictly to the preferred processing order:
    1. Illumination correction (flat-fielding)
    2. Denoising (bilateral filter)
    3. CLAHE (contrast enhancement)
    4. Gamma correction / intensity compression (exposure correction)
    5. Conservative sharpening (mild blur only; severe blur strictly excluded)
    6. Glare attenuation (punctate specular inpainting)
    
    Parameters:
        classification (dict): Output from Module 1A classify_fundus_image_quality.
        attempt (int): 1 or 2.
        previous_operations (list): Names of operations previously executed.
        
    Returns:
        list of dict: Selected operation specifications sorted by processing order.
    """
    if previous_operations is None:
        previous_operations = []
        
    s_focus = classification.get('score_focus', 1.0)
    s_bright = classification.get('score_brightness', 1.0)
    s_contrast = classification.get('score_contrast', 1.0)
    s_noise = classification.get('score_noise', 1.0)
    s_illum = classification.get('score_illumination', 1.0)
    s_art = classification.get('score_artifact', 1.0)
    
    f_focus = classification.get('flag_focus', '')
    f_bright = classification.get('flag_brightness', '')
    f_contrast = classification.get('flag_contrast', '')
    f_noise = classification.get('flag_noise', '')
    f_illum = classification.get('flag_illumination', '')
    f_art = classification.get('flag_artifact', '')
    
    raw_mean = classification.get('raw_brightness_mean', 85.0)
    raw_rms = classification.get('raw_contrast_rms', 20.0)
    raw_blobs = classification.get('raw_artifact_glare_blob_count', 0)
    raw_ratio = classification.get('raw_illum_center_edge_ratio', 1.15)
    raw_cov = classification.get('raw_illum_map_cov', 0.22)
    raw_lap = classification.get('raw_laplacian_var', 15.0)
    
    candidates = []
    
    # 1. Illumination Normalization (Order rank: 1)
    needs_illum = (s_illum < 0.65) or ('UNEVEN' in f_illum) or ('VIGNETTING' in f_illum) or (raw_ratio > 1.30) or (raw_cov > 0.30)
    if needs_illum:
        if attempt == 1 or 'illumination_normalization' not in previous_operations:
            candidates.append({
                'name': 'illumination_normalization',
                'order_rank': 1,
                'severity': 1.0 - s_illum,
                'params': {}
            })
            
    # 2. Mild Denoising (Order rank: 2)
    needs_denoise = (s_noise < 0.65) or ('NOISE' in f_noise and 'LOW' not in f_noise and 'ACCEPTABLE' not in f_noise)
    if needs_denoise:
        if attempt == 1 or 'bilateral_denoising' not in previous_operations:
            candidates.append({
                'name': 'bilateral_denoising',
                'order_rank': 2,
                'severity': 1.0 - s_noise,
                'params': {}
            })
            
    # 3. Contrast Enhancement (CLAHE) (Order rank: 3)
    needs_contrast = (s_contrast < 0.65) or ('LOW_CONTRAST' in f_contrast) or (raw_rms < 16.0)
    if needs_contrast:
        if attempt == 1:
            candidates.append({
                'name': 'CLAHE',
                'order_rank': 3,
                'severity': 1.0 - s_contrast,
                'params': {'clip_limit': ENHANCEMENT_CONFIG['clahe_clip_limit']}
            })
        elif 'CLAHE' not in previous_operations:
            candidates.append({
                'name': 'CLAHE',
                'order_rank': 3,
                'severity': 1.0 - s_contrast,
                'params': {'clip_limit': 1.5}  # Gentler clip limit for attempt 2
            })
            
    # 4. Exposure Correction (Order rank: 4)
    needs_exposure = (s_bright < 0.65) or ('UNDEREXPOSURE' in f_bright) or ('OVEREXPOSURE' in f_bright) or (raw_mean < 70.0) or (raw_mean > 110.0)
    if needs_exposure:
        if raw_mean > 110.0:
            op_name = 'intensity_compression' if attempt == 1 else 'gamma_correction'
            op_params = {'factor': 0.15} if op_name == 'intensity_compression' else {'gamma': 1.12}
        else:
            op_name = 'gamma_correction'
            op_params = {'gamma': 0.80 if attempt == 1 else 0.85, 'retinal_mean': raw_mean}
            
        if attempt == 1 or op_name not in previous_operations:
            candidates.append({
                'name': op_name,
                'order_rank': 4,
                'severity': 1.0 - s_bright,
                'params': op_params
            })
            
    # 5. Conservative Sharpening (Order rank: 5)
    # STRICT CHECK: Severe blur is NEVER sharpened -> RECAPTURE
    is_severe_blur = ('SEVERE_BLUR' in f_focus) or (s_focus < MIN_DIMENSION_SCORE_BORDERLINE) or (raw_lap < HARD_FAILURES['blur_laplacian_var_raw_min'])
    needs_sharpen = (s_focus < 0.65) and (not is_severe_blur)
    if needs_sharpen:
        if attempt == 1 or 'unsharp_masking' not in previous_operations:
            candidates.append({
                'name': 'unsharp_masking',
                'order_rank': 5,
                'severity': 1.0 - s_focus,
                'params': {'amount': 0.25 if attempt == 1 else 0.20}
            })
            
    # 6. Punctate Glare Inpainting (Order rank: 6)
    needs_glare = (s_art < 0.65) or (0 < raw_blobs <= 4)
    if needs_glare and ('glare_attenuation' not in previous_operations):
        candidates.append({
            'name': 'glare_attenuation',
            'order_rank': 6,
            'severity': 1.0 - s_art,
            'params': {}
        })
        
    # Default fallback: borderline due to general marginal composite score without single flag < 0.65
    if len(candidates) == 0:
        dim_candidates = [
            (1.0 - s_contrast, 'CLAHE', 3, {'clip_limit': 1.5}),
            (1.0 - s_bright, 'gamma_correction', 4, {'gamma': 0.88, 'retinal_mean': raw_mean}),
            (1.0 - s_illum, 'illumination_normalization', 1, {})
        ]
        dim_candidates.sort(key=lambda x: x[0], reverse=True)
        best_sev, best_name, best_rank, best_params = dim_candidates[0]
        if best_name not in previous_operations:
            candidates.append({
                'name': best_name,
                'order_rank': best_rank,
                'severity': best_sev,
                'params': best_params
            })
            
    # Select at most MAX_OPERATIONS_PER_ATTEMPT (2) highest severity deficits
    candidates.sort(key=lambda x: x['severity'], reverse=True)
    selected = candidates[:MAX_OPERATIONS_PER_ATTEMPT]
    
    # Sort selected operations strictly according to preferred processing order
    selected.sort(key=lambda x: x['order_rank'])
    
    return selected


# =====================================================================
# 3. SAFETY CHECKS AFTER EVERY ENHANCEMENT
# =====================================================================

def verify_enhancement_safety(original_image, enhanced_image, fov_orig, fov_post, metrics_orig, metrics_post, class_post, class_orig=None):
    """
    Comprehensive deterministic safety verification following Section 7 of Module 1B spec.
    Verifies:
    1. Pixel values remain valid (dtype uint8, finite, [0, 255])
    2. Retinal FOV is still present and has not deteriorated
    3. Saturation has not increased excessively
    4. Noise has not increased substantially
    5. Contrast has not become artificially extreme (RMS <= 45.0)
    6. Focus has not deteriorated substantially
    7. No obvious processing artifacts introduced
    8. Hard failures strictly enforced (never overridden)
    9. Critical dimension floor (>= 0.20)
    10. Composite quality score has not degraded
    
    Returns:
        (is_safe: bool, warnings: list, failure_reasons: list)
    """
    warnings = []
    failures = []
    
    # 1. Pixel Validity
    if enhanced_image is None or enhanced_image.size == 0:
        failures.append("Enhanced image is None or empty")
        return False, warnings, failures
        
    if enhanced_image.dtype != np.uint8:
        failures.append(f"Invalid image dtype {enhanced_image.dtype}; expected uint8")
        
    if enhanced_image.shape != original_image.shape:
        failures.append(f"Image shape changed from {original_image.shape} to {enhanced_image.shape}")
        
    if not np.isfinite(enhanced_image).all():
        failures.append("Non-finite values (NaN or Inf) detected in enhanced image")
        
    # 2. Retinal FOV Presence & Integrity
    area_orig = float(fov_orig.get('retinal_area', 0))
    area_post = float(fov_post.get('retinal_area', 0))
    circ_orig = float(fov_orig.get('circularity', 1.0))
    circ_post = float(fov_post.get('circularity', 1.0))
    
    if area_post <= 0:
        failures.append("Retinal FOV lost post-enhancement (retinal_area=0)")
    elif area_orig > 0 and area_post < 0.90 * area_orig:
        failures.append(f"Retinal FOV deteriorated: area shrank from {int(area_orig):,} to {int(area_post):,} px")
        
    if circ_post < 0.70 and circ_orig >= 0.75:
        failures.append(f"Retinal boundary circularity collapsed: {circ_orig:.3f} -> {circ_post:.3f}")
        
    # 3. Saturation Safety
    bright_orig = float(metrics_orig.get('brightness_bright_pct', 0.0))
    bright_post = float(metrics_post.get('brightness_bright_pct', 0.0))
    sat_orig = float(metrics_orig.get('artifact_sat_pixel_pct', 0.0))
    sat_post = float(metrics_post.get('artifact_sat_pixel_pct', 0.0))
    
    bright_max = HARD_FAILURES.get('brightness_bright_pct_max', 1.50)
    sat_max = HARD_FAILURES.get('artifact_sat_pixel_pct_max', 0.50)
    
    if bright_post > bright_max and bright_post > bright_orig + 0.10:
        failures.append(f"Severe overexposure saturation introduced: {bright_post:.2f}% > {bright_max}%")
    elif bright_post > bright_orig + 0.75:
        warnings.append(f"Moderate increase in saturated pixels: {bright_orig:.2f}% -> {bright_post:.2f}%")
        
    if sat_post > sat_max and sat_post > sat_orig + 0.10:
        failures.append(f"Excessive specular glare saturation: {sat_post:.2f}% > {sat_max}%")
        
    # 4. Noise Safety
    noise_orig = float(metrics_orig.get('noise_decoupled_std', metrics_orig.get('noise_residual_std', 1.0)))
    noise_post = float(metrics_post.get('noise_decoupled_std', metrics_post.get('noise_residual_std', 1.0)))
    s_noise_post = float(class_post.get('score_noise', 1.0))
    s_noise_orig = float(class_orig.get('score_noise', 1.0)) if class_orig else 1.0
    
    if s_noise_post < MIN_DIMENSION_SCORE_BORDERLINE and s_noise_orig >= MIN_DIMENSION_SCORE_BORDERLINE:
        failures.append(f"Noise score collapsed below critical floor: {s_noise_orig:.3f} -> {s_noise_post:.3f}")
    elif noise_post > 2.30 and noise_post > max(noise_orig * 1.50, noise_orig + 0.80):
        failures.append(f"Noise amplification into severe territory: {noise_orig:.3f} -> {noise_post:.3f} (+{noise_post - noise_orig:.3f})")
    elif noise_post > max(noise_orig * 1.80, noise_orig + 1.20) and s_noise_post < MIN_DIMENSION_SCORE_NON_CRITICAL:
        failures.append(f"Excessive noise amplification detected: {noise_orig:.3f} -> {noise_post:.3f} (+{noise_post - noise_orig:.3f})")
    elif noise_post > noise_orig * 1.25:
        warnings.append(f"Mild noise increase: {noise_orig:.3f} -> {noise_post:.3f}")
        
    # 5. Contrast Safety
    contrast_post = float(metrics_post.get('contrast_rms', 20.0))
    excessive_contrast = PROVISIONAL_BOUNDARIES['contrast'].get('excessive_max', 45.0)
    if contrast_post > excessive_contrast:
        failures.append(f"Artificial contrast explosion: RMS {contrast_post:.1f} > {excessive_contrast}")
        
    # 6. Focus Safety
    s_focus_orig = float(class_orig.get('score_focus', 1.0)) if class_orig else 1.0
    s_focus_post = float(class_post.get('score_focus', 1.0))
    if s_focus_orig >= 0.70 and s_focus_post < 0.45:
        failures.append(f"Focus deteriorated from GOOD to DEFICIT: {s_focus_orig:.3f} -> {s_focus_post:.3f}")
    elif s_focus_post < MIN_DIMENSION_SCORE_BORDERLINE:
        failures.append(f"Focus violated critical floor: {s_focus_post:.3f} < {MIN_DIMENSION_SCORE_BORDERLINE}")
        
    # 7. Hard Failure Safety
    if class_post.get('is_hard_failure', False):
        failures.append(f"Triggered hard failure: {class_post.get('hard_failure_reasons', 'Unknown')}")
        
    # 8. Critical Dimension Floor (< 0.20)
    min_crit = min(
        class_post.get('score_focus', 1.0),
        class_post.get('score_brightness', 1.0),
        class_post.get('score_contrast', 1.0),
        class_post.get('score_fov', 1.0)
    )
    if min_crit < MIN_DIMENSION_SCORE_BORDERLINE:
        failures.append(f"Critical dimension floor violated (min={min_crit:.3f} < {MIN_DIMENSION_SCORE_BORDERLINE})")
        
    # 9. Composite Score & Dimension Degradation
    if class_orig is not None:
        score_orig = float(class_orig.get('overall_score', 0.50))
        score_post = float(class_post.get('overall_score', 0.50))
        score_delta = score_post - score_orig
        if score_delta < -0.05:
            failures.append(f"Overall composite score degraded by {score_delta:.4f} ({score_orig:.4f} -> {score_post:.4f})")
            
        # Check if any dimension dropped below non-critical threshold
        for dim in ['focus', 'brightness', 'contrast', 'noise', 'fov', 'illumination', 'artifact']:
            d_orig = float(class_orig.get(f'score_{dim}', 1.0))
            d_post = float(class_post.get(f'score_{dim}', 1.0))
            if d_orig >= MIN_DIMENSION_SCORE_NON_CRITICAL and d_post < (MIN_DIMENSION_SCORE_NON_CRITICAL - 0.02):
                failures.append(f"Dimension {dim} dropped below non-critical threshold: {d_orig:.3f} -> {d_post:.3f}")
                
    is_safe = (len(failures) == 0)
    return is_safe, warnings, failures


# =====================================================================
# 4. PRIMARY PUBLIC INTERFACE & ORCHESTRATION
# =====================================================================

def process_borderline_image(image_bgr, quality_result=None, fov_info=None, filename='unknown'):
    """
    Primary Public Interface for Module 1B: Borderline Image Quality Enhancement.
    
    Standardized signature:
        result = process_borderline_image(image, quality_result)
        
    Protocol:
    1. Confirm input status is BORDERLINE.
       - If NON-CRITICAL: Bypass enhancement -> OK TO GO (original image preserved).
       - If CRITICAL: Bypass enhancement -> RECAPTURE (no enhancement).
    2. Attempt 1:
       - Select up to 2 targeted operations based on Module 1A metrics.
       - Apply operations strictly within retinal FOV.
       - Call Module 1A reassessment.
       - Run safety verification (revert & escalate if degraded).
       - If post-assessment is NON-CRITICAL: ACCEPT enhanced image -> OK TO GO.
       - If post-assessment is CRITICAL: REJECT -> RECAPTURE.
       - If post-assessment is still BORDERLINE: proceed to Attempt 2.
    3. Attempt 2:
       - Select up to 2 conservative complementary operations for remaining deficits.
       - Apply operations strictly within retinal FOV.
       - Call Module 1A reassessment.
       - Run safety verification.
       - If post-assessment is NON-CRITICAL: ACCEPT enhanced image -> OK TO GO.
       - If post-assessment is BORDERLINE or CRITICAL: REJECT -> RECAPTURE (attempts exhausted).
    4. Compile complete Before/After metadata (Section 8).
    
    Returns:
        dict: Complete enhancement and assessment record containing 'final_image', 'metadata',
              and direct access keys.
    """
    t_start = time.time()
    
    # Handle string path
    if isinstance(image_bgr, str):
        filename = filename if filename != 'unknown' else os.path.basename(image_bgr)
        img_path = image_bgr
        image_bgr = cv2.imread(img_path)
        if image_bgr is None:
            raise ValueError(f"Unable to read fundus image at path: {img_path}")
            
    h, w = image_bgr.shape[:2]
    original_img = image_bgr.copy()
    
    # 1. Module 1A Initial Assessment (if not already provided)
    if fov_info is None:
        fov_info = detect_retinal_fov(original_img)
        
    if quality_result is None:
        metrics_orig = compute_image_quality_metrics(original_img, fov_info)
        metrics_orig['filename'] = filename
        metrics_orig['width'] = w
        metrics_orig['height'] = h
        quality_result = classify_fundus_image_quality(metrics_orig)
    else:
        metrics_orig = compute_image_quality_metrics(original_img, fov_info)
        metrics_orig['filename'] = filename
        metrics_orig['width'] = w
        metrics_orig['height'] = h
        
    orig_status = quality_result['status']
    is_hf = quality_result.get('is_hard_failure', False)
    hf_reasons = quality_result.get('hard_failure_reasons', 'None')
    orig_directive = quality_result.get('directive', 'ENHANCEMENT')
    
    orig_scores = {
        'focus': quality_result['score_focus'],
        'brightness': quality_result['score_brightness'],
        'contrast': quality_result['score_contrast'],
        'noise': quality_result['score_noise'],
        'fov': quality_result['score_fov'],
        'illumination': quality_result['score_illumination'],
        'artifact': quality_result['score_artifact']
    }
    orig_flags = {
        'focus': quality_result['flag_focus'],
        'brightness': quality_result['flag_brightness'],
        'contrast': quality_result['flag_contrast'],
        'noise': quality_result['flag_noise'],
        'fov': quality_result['flag_fov'],
        'illumination': quality_result['flag_illumination'],
        'artifact': quality_result['flag_artifact']
    }
    
    # =================================================================
    # ROUTING CHECK: BYPASS NON-CRITICAL AND CRITICAL IMAGES
    # =================================================================
    if orig_status == 'NON-CRITICAL':
        proc_time = round(time.time() - t_start, 4)
        metadata = {
            'filename': filename,
            'original_status': 'NON-CRITICAL',
            'original_directive': orig_directive,
            'original_hard_failure': is_hf,
            'original_hard_failure_reasons': hf_reasons,
            'final_status': 'NON-CRITICAL',
            'original_quality_metrics': metrics_orig,
            'enhanced_quality_metrics': metrics_orig,
            'original_normalized_scores': orig_scores,
            'enhanced_normalized_scores': orig_scores,
            'enhancement_attempt_number': 0,
            'operations_applied': [],
            'score_change': 0.0,
            'final_decision': 'ACCEPT',
            'processing_time': proc_time,
            'warnings': [],
            'errors': [],
            'degradation_detected': False,
            'enhancement_success': False,
            'bypassed': True,
            'bypass_reason': 'NON-CRITICAL (GRADABLE) original image; enhancement bypassed',
            'ok_to_go': True,
            'recapture_required': False,
            'enhancement_required': False,
            'final_directive': 'OK TO GO',
            'rationale': f"Original image meets acceptable clinical quality standards; enhancement not needed ({quality_result['rationale']})"
        }
        res = dict(metadata)
        res['original_hard_failure'] = is_hf
        res['original_hard_failure_reasons'] = hf_reasons
        res['original_directive'] = orig_directive
        res['final_image'] = original_img.copy()
        res['original_image'] = original_img.copy()
        res['original_overall_score'] = quality_result['overall_score']
        res['post_enhancement_overall_score'] = quality_result['overall_score']
        res['post_enhancement_status'] = 'NOT_APPLICABLE'
        res['post_enhancement_directive'] = 'OK TO GO'
        res['post_scores'] = orig_scores
        res['post_flags'] = orig_flags
        res['original_scores'] = orig_scores
        res['original_flags'] = orig_flags
        res['dimension_deltas'] = {k: 0.0 for k in orig_scores}
        res['score_delta'] = 0.0
        res['enhancement_applied'] = False
        res['enhancement_operations'] = []
        res['enhancement_details'] = {}
        res['reason'] = metadata['rationale']
        res['metadata'] = metadata
        return res
        
    elif orig_status == 'CRITICAL':
        proc_time = round(time.time() - t_start, 4)
        metadata = {
            'filename': filename,
            'original_status': 'CRITICAL',
            'original_directive': orig_directive,
            'original_hard_failure': is_hf,
            'original_hard_failure_reasons': hf_reasons,
            'final_status': 'CRITICAL',
            'original_quality_metrics': metrics_orig,
            'enhanced_quality_metrics': metrics_orig,
            'original_normalized_scores': orig_scores,
            'enhanced_normalized_scores': orig_scores,
            'enhancement_attempt_number': 0,
            'operations_applied': [],
            'score_change': 0.0,
            'final_decision': 'REJECT',
            'processing_time': proc_time,
            'warnings': [],
            'errors': quality_result.get('hard_failure_reasons', '').split('; ') if quality_result.get('is_hard_failure') else [],
            'degradation_detected': False,
            'enhancement_success': False,
            'bypassed': True,
            'bypass_reason': 'CRITICAL (NON_GRADABLE) original image; enhancement bypassed',
            'ok_to_go': False,
            'recapture_required': True,
            'enhancement_required': False,
            'final_directive': 'RECAPTURE',
            'rationale': f"Original image triggered non-recoverable CRITICAL quality failure; enhancement bypassed ({quality_result['rationale']})"
        }
        res = dict(metadata)
        res['original_hard_failure'] = is_hf
        res['original_hard_failure_reasons'] = hf_reasons
        res['original_directive'] = orig_directive
        res['final_image'] = original_img.copy()
        res['original_image'] = original_img.copy()
        res['original_overall_score'] = quality_result['overall_score']
        res['post_enhancement_overall_score'] = quality_result['overall_score']
        res['post_enhancement_status'] = 'NOT_APPLICABLE'
        res['post_enhancement_directive'] = 'RECAPTURE'
        res['post_scores'] = orig_scores
        res['post_flags'] = orig_flags
        res['original_scores'] = orig_scores
        res['original_flags'] = orig_flags
        res['dimension_deltas'] = {k: 0.0 for k in orig_scores}
        res['score_delta'] = 0.0
        res['enhancement_applied'] = False
        res['enhancement_operations'] = []
        res['enhancement_details'] = {}
        res['reason'] = metadata['rationale']
        res['metadata'] = metadata
        return res
        
    # =================================================================
    # BORDERLINE ENHANCEMENT LOOP (MAX_ENHANCEMENT_ATTEMPTS = 2)
    # =================================================================
    current_img = original_img.copy()
    current_class = quality_result
    current_fov = fov_info
    current_metrics = metrics_orig
    
    total_applied_ops = []
    all_op_details = {}
    attempts_history = []
    warnings_list = []
    errors_list = []
    degradation_detected = False
    
    for attempt in range(1, MAX_ENHANCEMENT_ATTEMPTS + 1):
        # 1. Select targeted operations (strictly max 2 operations per attempt)
        selected_ops = select_targeted_operations(
            current_class,
            attempt=attempt,
            previous_operations=total_applied_ops
        )
        if not selected_ops:
            break
            
        attempt_img = current_img.copy()
        attempt_ops_applied = []
        attempt_op_details = {}
        mask = current_fov['mask_eroded']
        
        # 2. Sequential execution in preferred processing order
        for op in selected_ops:
            op_name = op['name']
            op_params = op.get('params', {})
            attempt_img, det = apply_operation(
                attempt_img, mask, op_name, op_params,
                retinal_mean=current_class.get('raw_brightness_mean', 85.0)
            )
            attempt_ops_applied.append(op_name)
            attempt_op_details[op_name] = det
            
        total_applied_ops.extend(attempt_ops_applied)
        all_op_details.update(attempt_op_details)
        
        # 3. EXISTING Module 1A Reassessment
        fov_post = detect_retinal_fov(attempt_img)
        metrics_post = compute_image_quality_metrics(attempt_img, fov_post)
        metrics_post['filename'] = f"{filename}_attempt{attempt}"
        metrics_post['width'] = w
        metrics_post['height'] = h
        class_post = classify_fundus_image_quality(metrics_post)
        
        # 4. Verify Safety Checks
        is_safe, attempt_warns, attempt_fails = verify_enhancement_safety(
            original_img, attempt_img, fov_info, fov_post,
            metrics_orig, metrics_post, class_post, class_orig=quality_result
        )
        warnings_list.extend(attempt_warns)
        
        attempt_record = {
            'attempt': attempt,
            'operations': attempt_ops_applied,
            'details': attempt_op_details,
            'post_status': class_post['status'],
            'post_score': class_post['overall_score'],
            'score_change': round(class_post['overall_score'] - quality_result['overall_score'], 4),
            'safety_passed': is_safe,
            'safety_failures': attempt_fails
        }
        attempts_history.append(attempt_record)
        
        if not is_safe:
            degradation_detected = True
            errors_list.extend(attempt_fails)
            # Revert to original image on safety failure
            current_img = original_img.copy()
            current_class = class_post
            current_metrics = metrics_post
            current_fov = fov_post
            break
            
        current_img = attempt_img
        current_class = class_post
        current_metrics = metrics_post
        current_fov = fov_post
        
        if class_post['status'] == 'NON-CRITICAL':
            # Successfully reached NON-CRITICAL quality standards!
            break
        elif class_post['status'] == 'CRITICAL':
            # Dropped to CRITICAL
            break
        # If still BORDERLINE and attempt < MAX_ENHANCEMENT_ATTEMPTS, loop continues to Attempt 2!
        
    # =================================================================
    # FINAL DECISION SYNTHESIS
    # =================================================================
    post_status = current_class['status']
    final_score = current_class['overall_score']
    score_change = round(final_score - quality_result['overall_score'], 4)
    proc_time = round(time.time() - t_start, 4)
    
    post_scores = {
        'focus': current_class['score_focus'],
        'brightness': current_class['score_brightness'],
        'contrast': current_class['score_contrast'],
        'noise': current_class['score_noise'],
        'fov': current_class['score_fov'],
        'illumination': current_class['score_illumination'],
        'artifact': current_class['score_artifact']
    }
    post_flags = {
        'focus': current_class['flag_focus'],
        'brightness': current_class['flag_brightness'],
        'contrast': current_class['flag_contrast'],
        'noise': current_class['flag_noise'],
        'fov': current_class['flag_fov'],
        'illumination': current_class['flag_illumination'],
        'artifact': current_class['flag_artifact']
    }
    
    ops_str = ', '.join(total_applied_ops) if total_applied_ops else "None"
    
    if degradation_detected or post_status == 'CRITICAL':
        final_status = 'CRITICAL'
        final_directive = 'RECAPTURE'
        final_decision = 'REJECT'
        ok_to_go = False
        recapture_required = True
        enhancement_required = False
        enhancement_success = False
        final_img = original_img.copy()
        reason = f"Enhancement failed: degradation detected or escalated to CRITICAL ({'; '.join(errors_list) if errors_list else current_class['rationale']})"
    elif post_status == 'NON-CRITICAL':
        final_status = 'NON-CRITICAL'
        final_directive = 'OK TO GO'
        final_decision = 'ACCEPT'
        ok_to_go = True
        recapture_required = False
        enhancement_required = False
        enhancement_success = True
        final_img = current_img
        reason = f"Successfully converted BORDERLINE -> NON-CRITICAL via {ops_str} (Score: {quality_result['overall_score']:.3f} -> {final_score:.3f}, Delta: {score_change:+.3f}). Passed Module 1A post-enhancement quality assessment."
    else:  # post_status == 'BORDERLINE'
        final_status = 'BORDERLINE'
        final_directive = 'RECAPTURE'
        final_decision = 'REJECT'
        ok_to_go = False
        recapture_required = True
        enhancement_required = False
        enhancement_success = False
        final_img = current_img
        reason = f"Remained BORDERLINE after {len(attempts_history)} enhancement attempt(s) ({ops_str}; Score: {quality_result['overall_score']:.3f} -> {final_score:.3f}, Delta: {score_change:+.3f}). Maximum attempts exhausted -> RECAPTURE."
        
    metadata = {
        'filename': filename,
        'original_status': orig_status,
        'original_directive': orig_directive,
        'original_hard_failure': is_hf,
        'original_hard_failure_reasons': hf_reasons,
        'final_status': final_status,
        'original_quality_metrics': metrics_orig,
        'enhanced_quality_metrics': current_metrics,
        'original_normalized_scores': orig_scores,
        'enhanced_normalized_scores': post_scores,
        'enhancement_attempt_number': len(attempts_history),
        'operations_applied': total_applied_ops,
        'score_change': score_change,
        'final_decision': final_decision,
        'processing_time': proc_time,
        'warnings': warnings_list,
        'errors': errors_list,
        'degradation_detected': degradation_detected,
        'enhancement_success': enhancement_success,
        'ok_to_go': ok_to_go,
        'recapture_required': recapture_required,
        'enhancement_required': enhancement_required,
        'final_directive': final_directive,
        'rationale': reason,
        'attempts_history': attempts_history
    }
    
    res = dict(metadata)
    res['original_hard_failure'] = is_hf
    res['original_hard_failure_reasons'] = hf_reasons
    res['original_directive'] = orig_directive
    res['final_image'] = final_img
    res['original_image'] = original_img.copy()
    res['original_overall_score'] = quality_result['overall_score']
    res['post_enhancement_overall_score'] = final_score
    res['post_enhancement_status'] = post_status
    res['post_enhancement_directive'] = final_directive
    res['post_scores'] = post_scores
    res['post_flags'] = post_flags
    res['original_scores'] = orig_scores
    res['original_flags'] = orig_flags
    res['dimension_deltas'] = {
        dim: round(post_scores[dim] - orig_scores[dim], 4)
        for dim in orig_scores
    }
    res['score_delta'] = score_change
    res['enhancement_applied'] = (len(total_applied_ops) > 0)
    res['enhancement_operations'] = total_applied_ops
    res['enhancement_details'] = all_op_details
    res['reason'] = reason
    res['metadata'] = metadata
    
    # Invariant assertion
    if final_status == 'CRITICAL':
        assert ok_to_go is False, f"Invariant failed: CRITICAL with ok_to_go=True in {filename}"
        assert recapture_required is True, f"Invariant failed: CRITICAL with recapture_required=False in {filename}"
        assert enhancement_required is False, f"Invariant failed: CRITICAL with enhancement_required=True in {filename}"
    elif final_status == 'NON-CRITICAL':
        assert ok_to_go is True, f"Invariant failed: NON-CRITICAL with ok_to_go=False in {filename}"
        assert recapture_required is False, f"Invariant failed: NON-CRITICAL with recapture_required=True in {filename}"
        assert enhancement_required is False, f"Invariant failed: NON-CRITICAL with enhancement_required=True in {filename}"
    elif final_status == 'BORDERLINE':
        assert ok_to_go is False, f"Invariant failed: BORDERLINE with ok_to_go=True in {filename}"
        if len(attempts_history) >= MAX_ENHANCEMENT_ATTEMPTS:
            assert recapture_required is True, f"Invariant failed: Exhausted BORDERLINE with recapture_required=False in {filename}"
            assert enhancement_required is False, f"Invariant failed: Exhausted BORDERLINE with enhancement_required=True in {filename}"
            
    return res


# =====================================================================
# 5. BACKWARD-COMPATIBILITY PIPELINE WRAPPERS
# =====================================================================

def enhance_borderline_image(image_bgr, fov_info, initial_classification):
    """
    Executes a single targeted enhancement pass (max 2 operations) on a BORDERLINE image.
    Preserved for backward compatibility with existing callers.
    """
    if initial_classification.get('status') != 'BORDERLINE':
        return image_bgr.copy(), [], {'error': 'Enhancement permitted ONLY for BORDERLINE images'}
        
    mask = fov_info['mask_eroded']
    selected_ops = select_targeted_operations(initial_classification, attempt=1)
    
    current_img = image_bgr.copy()
    applied_ops = []
    op_details = {}
    
    for op in selected_ops:
        op_name = op['name']
        op_params = op.get('params', {})
        current_img, det = apply_operation(
            current_img, mask, op_name, op_params,
            retinal_mean=initial_classification.get('raw_brightness_mean', 85.0)
        )
        applied_ops.append(op_name)
        op_details[op_name] = det
        
    return current_img, applied_ops, op_details


def assess_and_enhance_pipeline(image_bgr, filename='unknown'):
    """
    Complete Module 1 Quality Pipeline with Deterministic Enhancement & Reassessment.
    Preserves backward compatibility while executing the full 2-attempt Module 1B architecture.
    
    Returns:
        (pipeline_result_dict, original_image_bgr, enhanced_image_bgr)
    """
    res = process_borderline_image(image_bgr, filename=filename)
    return res, res['original_image'], res['final_image']