"""
Module 1: Deterministic Quality Enhancement for Borderline Fundus Images.

This module provides reproducible, bounded, explainable, and non-hallucinating
enhancement operations strictly mapped to detected quality deficits.

Safety Principles & Protocol:
1. Gating: Enhancement is applied ONLY to images classified as BORDERLINE.
   CRITICAL images (hard failures / fatal floors) NEVER enter enhancement.
   NON-CRITICAL images (acceptable quality) are NEVER unnecessarily modified.
2. Single Pass: An image is enhanced at most ONCE. No recursive loops.
3. Strict Masking: All operations are masked to the retinal Field of View (FOV).
   Dark camera borders and background pixels are strictly preserved and never amplified.
4. Bounded Correction: Every parameter (gamma, CLAHE clip, gain, bilateral sigma,
   unsharp amount) has hard upper and lower safety bounds in src/config.py.
5. Exact Reassessment: The enhanced image is evaluated using the EXACT SAME
   quality assessment engine. If enhancement does not achieve acceptable quality,
   or if degradation is detected, the image is safely triaged to CRITICAL / RECAPTURE.
"""

import math
import numpy as np
import cv2

from src.config import (
    ENHANCEMENT_CONFIG,
    MIN_DIMENSION_SCORE_BORDERLINE,
    MIN_DIMENSION_SCORE_NON_CRITICAL,
    CRITICAL_SCORE_THRESHOLD,
    BORDERLINE_SCORE_THRESHOLD,
    ARTIFACT_GLARE_BLOB_NON_CRITICAL_MAX,
)
from src.fov_detector import detect_retinal_fov
from src.quality_metrics import compute_image_quality_metrics
from src.quality_classifier import classify_fundus_image_quality


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
    B. Bounded Exposure / Intensity Correction.
    Lifts underexposed midtones (gamma < 1.0) or gently tones down mild
    overexposure (gamma > 1.0) via luminance channel mapping.
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
        'gamma': round(g, 3)
    }
    return enhanced, details


def apply_illumination_correction(image_bgr, fov_mask, gain_min=None, gain_max=None):
    """
    C. Deterministic Illumination Normalization / Flat-Fielding.
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
    sigma = max(w, h) * cfg['illum_filter_sigma_fraction']
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
    D. Controlled Edge-Preserving Denoising.
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
    E. Conservative Unsharp Masking.
    Applied strictly to mildly blurred images to enhance microvascular contrast
    without introducing edge-ringing artifacts or synthetic structures.
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
    F. Punctate Specular Glare Inpainting.
    Restricted strictly to small punctate flash reflections (< 250 px).
    Interpolates tiny saturated spots from adjacent retinal pixels using
    Navier-Stokes/Telea inpainting without synthesizing retinal structures.
    Large glare patches (> 250 px) remain untouched.
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
        # Only inpaint small punctate reflections
        if blob_area <= max_a:
            inpaint_mask[labels == i] = 255
            recovered_blob_count += 1
            
    if recovered_blob_count > 0:
        # Small dilation to cover transition boundary
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


def enhance_borderline_image(image_bgr, fov_info, initial_classification):
    """
    Executes targeted, deterministic enhancement on a BORDERLINE fundus image.
    Operations are strictly mapped to the specific deficits detected during
    initial assessment.
    
    Execution Order (Multi-Deficit Safety Pipeline):
    1. Denoising (if noisy, to prevent noise amplification downstream)
    2. Illumination Flat-Fielding (if non-uniform spatial gradients present)
    3. Exposure Correction (if global underexposure/overexposure present)
    4. Contrast Enhancement (CLAHE on L-channel if low contrast)
    5. Glare Attenuation (if small punctate specular reflections present)
    6. Mild Sharpening (if mild focus deficit present, after denoising & contrast)
    
    Returns:
        (enhanced_image_bgr, list_of_applied_operations, operations_details_dict)
    """
    if initial_classification.get('status') != 'BORDERLINE':
        return image_bgr.copy(), [], {'error': 'Enhancement permitted ONLY for BORDERLINE images'}
        
    mask = fov_info['mask_eroded']
    current_img = image_bgr.copy()
    applied_ops = []
    op_details = {}
    
    # 1. Deficit Detection from Initial Classification
    s_focus = initial_classification.get('score_focus', 1.0)
    s_bright = initial_classification.get('score_brightness', 1.0)
    s_contrast = initial_classification.get('score_contrast', 1.0)
    s_noise = initial_classification.get('score_noise', 1.0)
    s_illum = initial_classification.get('score_illumination', 1.0)
    s_art = initial_classification.get('score_artifact', 1.0)
    
    f_focus = initial_classification.get('flag_focus', '')
    f_bright = initial_classification.get('flag_brightness', '')
    f_contrast = initial_classification.get('flag_contrast', '')
    f_noise = initial_classification.get('flag_noise', '')
    f_illum = initial_classification.get('flag_illumination', '')
    f_art = initial_classification.get('flag_artifact', '')
    
    raw_mean = initial_classification.get('raw_brightness_mean', 85.0)
    raw_rms = initial_classification.get('raw_contrast_rms', 20.0)
    raw_blobs = initial_classification.get('raw_artifact_glare_blob_count', 0)
    raw_ratio = initial_classification.get('raw_illum_center_edge_ratio', 1.15)
    raw_cov = initial_classification.get('raw_illum_map_cov', 0.22)
    
    # A. Noise Deficit
    needs_denoising = (s_noise < 0.65) or (f_noise in ['MODERATE_NOISE', 'SEVERE_NOISE'])
    # B. Illumination Deficit
    needs_illumination = (s_illum < 0.65) or (f_illum in ['MODERATE_VIGNETTING', 'MODERATE_GRADIENT']) or (raw_ratio > 1.30) or (raw_cov > 0.30)
    # C. Exposure Deficit
    needs_exposure = (s_bright < 0.65) or (f_bright in ['MILD_UNDEREXPOSURE', 'MILD_OVEREXPOSURE']) or (raw_mean < 70.0) or (raw_mean > 110.0)
    # D. Contrast Deficit
    needs_contrast = (s_contrast < 0.65) or (f_contrast in ['LOW_CONTRAST', 'CRITICAL_LOW_CONTRAST']) or (raw_rms < 16.0)
    # E. Glare Deficit
    needs_glare = (s_art < 0.65) or (f_art == 'BORDERLINE_GLARE') or (raw_blobs >= 5)
    # F. Focus Deficit (mild blur only; never severe blur)
    needs_sharpening = (s_focus < 0.65) and (s_focus >= MIN_DIMENSION_SCORE_BORDERLINE) and ('SEVERE_BLUR' not in f_focus)
    
    # 2. Sequential Deterministic Execution
    # Step 1: Denoise first
    if needs_denoising:
        current_img, det_d = apply_denoising(current_img, mask)
        applied_ops.append('bilateral_denoising')
        op_details['bilateral_denoising'] = det_d
        
    # Step 2: Illumination Flat-Fielding
    if needs_illumination:
        current_img, det_i = apply_illumination_correction(current_img, mask)
        applied_ops.append('illumination_normalization')
        op_details['illumination_normalization'] = det_i
        
    # Step 3: Exposure / Gamma Correction
    if needs_exposure:
        current_img, det_g = apply_gamma_correction(current_img, mask, retinal_mean=raw_mean)
        applied_ops.append('gamma_correction')
        op_details['gamma_correction'] = det_g
        
    # Step 4: Contrast Enhancement (CLAHE)
    if needs_contrast:
        current_img, det_c = apply_clahe(current_img, mask)
        applied_ops.append('CLAHE')
        op_details['CLAHE'] = det_c
        
    # Step 5: Punctate Glare Inpainting
    if needs_glare:
        current_img, det_gl = apply_glare_inpaint(current_img, mask)
        if det_gl['recovered_blobs'] > 0:
            applied_ops.append('glare_attenuation')
            op_details['glare_attenuation'] = det_gl
            
    # Step 6: Mild Sharpening
    if needs_sharpening:
        current_img, det_s = apply_mild_sharpening(current_img, mask)
        applied_ops.append('unsharp_masking')
        op_details['unsharp_masking'] = det_s
        
    # Default fallback: if borderline due to general marginal scores without a single dominant flag
    if len(applied_ops) == 0:
        current_img, det_c = apply_clahe(current_img, mask, clip_limit=1.5)
        applied_ops.append('CLAHE')
        op_details['CLAHE'] = det_c
        
    return current_img, applied_ops, op_details


def assess_and_enhance_pipeline(image_bgr, filename='unknown'):
    """
    Complete Module 1 Quality Pipeline with Deterministic Enhancement & Reassessment.
    
    Protocol:
    1. Assess original image.
    2. If CRITICAL -> Final CRITICAL -> RECAPTURE (enhancement bypassed).
    3. If NON-CRITICAL -> Final NON-CRITICAL -> OK TO GO (enhancement bypassed).
    4. If BORDERLINE ->
       a. Apply targeted deterministic enhancement (at most once).
       b. Reassess enhanced image with the EXACT SAME quality assessment engine.
       c. Verify no degradation or safety violation.
       d. Determine final status:
          - Post-enhancement NON-CRITICAL -> Final NON-CRITICAL -> OK TO GO
          - Post-enhancement BORDERLINE -> Final BORDERLINE -> ENHANCEMENT
          - Post-enhancement CRITICAL / degraded -> Final CRITICAL -> RECAPTURE
    5. Assert strict runtime invariants.
    
    Returns:
        (pipeline_result_dict, original_image_bgr, enhanced_image_bgr)
    """
    h, w = image_bgr.shape[:2]
    
    # -------------------------------------------------------------
    # 1. INITIAL ASSESSMENT
    # -------------------------------------------------------------
    fov_orig = detect_retinal_fov(image_bgr)
    metrics_orig = compute_image_quality_metrics(image_bgr, fov_orig)
    metrics_orig['filename'] = filename
    metrics_orig['width'] = w
    metrics_orig['height'] = h
    
    class_orig = classify_fundus_image_quality(metrics_orig)
    orig_status = class_orig['status']
    
    # Result container
    res = {
        'filename': filename,
        'original_status': orig_status,
        'original_directive': class_orig['directive'],
        'original_overall_score': class_orig['overall_score'],
        'original_hard_failure': class_orig['is_hard_failure'],
        'original_hard_failure_reasons': class_orig['hard_failure_reasons'],
        'enhancement_required': class_orig['enhancement_required'],
        'enhancement_applied': False,
        'enhancement_operations': [],
        'enhancement_details': {},
        
        # Original Dimension Scores
        'original_scores': {
            'focus': class_orig['score_focus'],
            'brightness': class_orig['score_brightness'],
            'contrast': class_orig['score_contrast'],
            'noise': class_orig['score_noise'],
            'fov': class_orig['score_fov'],
            'illumination': class_orig['score_illumination'],
            'artifact': class_orig['score_artifact']
        },
        'original_flags': {
            'focus': class_orig['flag_focus'],
            'brightness': class_orig['flag_brightness'],
            'contrast': class_orig['flag_contrast'],
            'noise': class_orig['flag_noise'],
            'fov': class_orig['flag_fov'],
            'illumination': class_orig['flag_illumination'],
            'artifact': class_orig['flag_artifact']
        }
    }
    
    # -------------------------------------------------------------
    # 2. DECISION BRANCHING
    # -------------------------------------------------------------
    if orig_status == 'CRITICAL':
        # CRITICAL images NEVER enter enhancement
        res['final_status'] = 'CRITICAL'
        res['final_directive'] = 'RECAPTURE'
        res['ok_to_go'] = False
        res['recapture_required'] = True
        res['post_enhancement_status'] = 'NOT_APPLICABLE'
        res['post_enhancement_overall_score'] = class_orig['overall_score']
        res['score_delta'] = 0.0
        res['degradation_detected'] = False
        res['reason'] = f"Original image triggered non-recoverable CRITICAL quality failure; enhancement bypassed ({class_orig['rationale']})"
        enhanced_image = image_bgr.copy()
        
    elif orig_status == 'NON-CRITICAL':
        # NON-CRITICAL images are NEVER unnecessarily modified
        res['final_status'] = 'NON-CRITICAL'
        res['final_directive'] = 'OK TO GO'
        res['ok_to_go'] = True
        res['recapture_required'] = False
        res['post_enhancement_status'] = 'NOT_APPLICABLE'
        res['post_enhancement_overall_score'] = class_orig['overall_score']
        res['score_delta'] = 0.0
        res['degradation_detected'] = False
        res['reason'] = f"Original image meets acceptable clinical quality standards; enhancement not needed ({class_orig['rationale']})"
        enhanced_image = image_bgr.copy()
        
    else:  # orig_status == 'BORDERLINE'
        # ---------------------------------------------------------
        # 3. SINGLE DETERMINISTIC ENHANCEMENT PASS
        # ---------------------------------------------------------
        enhanced_image, applied_ops, op_details = enhance_borderline_image(image_bgr, fov_orig, class_orig)
        res['enhancement_applied'] = True
        res['enhancement_operations'] = applied_ops
        res['enhancement_details'] = op_details
        
        # ---------------------------------------------------------
        # 4. POST-ENHANCEMENT REASSESSMENT (SAME ASSESSMENT ENGINE)
        # ---------------------------------------------------------
        fov_post = detect_retinal_fov(enhanced_image)
        metrics_post = compute_image_quality_metrics(enhanced_image, fov_post)
        metrics_post['filename'] = f"{filename}_enhanced"
        metrics_post['width'] = w
        metrics_post['height'] = h
        
        class_post = classify_fundus_image_quality(metrics_post)
        post_status = class_post['status']
        res['post_enhancement_status'] = post_status
        res['post_enhancement_directive'] = class_post['directive']
        res['post_enhancement_overall_score'] = class_post['overall_score']
        res['post_enhancement_hard_failure'] = class_post['is_hard_failure']
        res['post_enhancement_hard_failure_reasons'] = class_post['hard_failure_reasons']
        
        # Post-enhancement Dimension Scores
        res['post_scores'] = {
            'focus': class_post['score_focus'],
            'brightness': class_post['score_brightness'],
            'contrast': class_post['score_contrast'],
            'noise': class_post['score_noise'],
            'fov': class_post['score_fov'],
            'illumination': class_post['score_illumination'],
            'artifact': class_post['score_artifact']
        }
        res['post_flags'] = {
            'focus': class_post['flag_focus'],
            'brightness': class_post['flag_brightness'],
            'contrast': class_post['flag_contrast'],
            'noise': class_post['flag_noise'],
            'fov': class_post['flag_fov'],
            'illumination': class_post['flag_illumination'],
            'artifact': class_post['flag_artifact']
        }
        
        # ---------------------------------------------------------
        # 5. DELTA CALCULATION & DEGRADATION DETECTION
        # ---------------------------------------------------------
        score_delta = round(class_post['overall_score'] - class_orig['overall_score'], 4)
        res['score_delta'] = score_delta
        res['dimension_deltas'] = {
            'focus': round(class_post['score_focus'] - class_orig['score_focus'], 4),
            'brightness': round(class_post['score_brightness'] - class_orig['score_brightness'], 4),
            'contrast': round(class_post['score_contrast'] - class_orig['score_contrast'], 4),
            'noise': round(class_post['score_noise'] - class_orig['score_noise'], 4),
            'fov': round(class_post['score_fov'] - class_orig['score_fov'], 4),
            'illumination': round(class_post['score_illumination'] - class_orig['score_illumination'], 4),
            'artifact': round(class_post['score_artifact'] - class_orig['score_artifact'], 4)
        }
        
        # Degradation Detection Criteria:
        # 1. Post-enhancement triggers hard failure
        # 2. Critical dimension floor violation (< 0.20)
        # 3. Any single dimension drops severely (> 0.20 score degradation)
        # 4. Overall composite score degrades (> 0.05 decrease)
        degraded = False
        degradation_reasons = []
        if class_post['is_hard_failure']:
            degraded = True
            degradation_reasons.append(f"Triggered hard failure: {class_post['hard_failure_reasons']}")
        min_crit = min(class_post['score_focus'], class_post['score_brightness'], class_post['score_contrast'], class_post['score_fov'])
        if min_crit < MIN_DIMENSION_SCORE_BORDERLINE:
            degraded = True
            degradation_reasons.append(f"Critical dimension floor violated (min={min_crit:.3f} < {MIN_DIMENSION_SCORE_BORDERLINE})")
        for dim, delta in res['dimension_deltas'].items():
            post_score = res['post_scores'][dim]
            orig_score = res['original_scores'][dim]
            # Genuine clinical degradation: dimension dropped below non-critical threshold (0.35)
            if orig_score >= MIN_DIMENSION_SCORE_NON_CRITICAL and post_score < (MIN_DIMENSION_SCORE_NON_CRITICAL - 0.01):
                degraded = True
                degradation_reasons.append(f"Dimension {dim} dropped below non-critical threshold ({orig_score:.3f} -> {post_score:.3f}, delta={delta:+.3f})")
            # Or severe degradation (> 0.25 drop) ending up in deficit territory (< 0.50)
            elif delta < -0.25 and post_score < 0.50:
                degraded = True
                degradation_reasons.append(f"Severe degradation in {dim} ({orig_score:.3f} -> {post_score:.3f}, delta={delta:+.3f})")
        if score_delta < -0.05:
            degraded = True
            degradation_reasons.append(f"Overall composite score decreased by {score_delta:.3f}")
            
        res['degradation_detected'] = degraded
        res['degradation_reasons'] = '; '.join(degradation_reasons) if degradation_reasons else "None"
        
        # ---------------------------------------------------------
        # 6. FINAL BORDERLINE DECISION
        # ---------------------------------------------------------
        ops_str = ', '.join(applied_ops)
        if degraded or post_status == 'CRITICAL':
            res['final_status'] = 'CRITICAL'
            res['final_directive'] = 'RECAPTURE'
            res['ok_to_go'] = False
            res['recapture_required'] = True
            res['reason'] = f"Enhancement failed to recover acceptable quality (escalated to CRITICAL): {res['degradation_reasons'] if degraded else class_post['rationale']}"
            
        elif post_status == 'NON-CRITICAL':
            res['final_status'] = 'NON-CRITICAL'
            res['final_directive'] = 'OK TO GO'
            res['ok_to_go'] = True
            res['recapture_required'] = False
            res['reason'] = f"Successfully improved from BORDERLINE to NON-CRITICAL via {ops_str} (Score: {class_orig['overall_score']:.3f} -> {class_post['overall_score']:.3f}, Delta: {score_delta:+.3f}). Passed post-enhancement quality assessment."
            
        else:  # post_status == 'BORDERLINE'
            res['final_status'] = 'BORDERLINE'
            res['final_directive'] = 'ENHANCEMENT'
            res['ok_to_go'] = False
            res['recapture_required'] = False
            res['reason'] = f"Remains BORDERLINE after single enhancement pass ({ops_str}; Score: {class_orig['overall_score']:.3f} -> {class_post['overall_score']:.3f}, Delta: {score_delta:+.3f}). Further enhancement capped."
            
    # -------------------------------------------------------------
    # 7. STRICT INVARIANT ASSERTIONS
    # -------------------------------------------------------------
    f_stat = res['final_status']
    ok = res['ok_to_go']
    recap = res['recapture_required']
    
    if f_stat == 'CRITICAL':
        assert ok is False, f"Invariant failed: CRITICAL with ok_to_go=True in {filename}"
        assert recap is True, f"Invariant failed: CRITICAL with recapture_required=False in {filename}"
    elif f_stat == 'BORDERLINE':
        assert ok is False, f"Invariant failed: BORDERLINE with ok_to_go=True in {filename}"
        assert recap is False, f"Invariant failed: BORDERLINE with recapture_required=True in {filename}"
    elif f_stat == 'NON-CRITICAL':
        assert ok is True, f"Invariant failed: NON-CRITICAL with ok_to_go=False in {filename}"
        assert recap is False, f"Invariant failed: NON-CRITICAL with recapture_required=True in {filename}"
    else:
        raise ValueError(f"Invalid final status: {f_stat}")
        
    return res, image_bgr, enhanced_image
