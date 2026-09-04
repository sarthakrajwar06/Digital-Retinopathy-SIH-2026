"""
Module 1: Fundus Image Quality Assessment — Decision Engine.

Implements the deterministic three-class Quality Decision Engine:
- Exactly 3 Quality Classes:
    * CRITICAL      -> Action: RECAPTURE
    * BORDERLINE    -> Action: ENHANCEMENT
    * NON-CRITICAL  -> Action: OK TO GO

- 7 Orthogonal Quality Dimensions (Normalized to [0.0, 1.0]):
    1. Focus / Blur
    2. Brightness / Exposure
    3. Contrast
    4. Noise
    5. Field of View (FOV)
    6. Illumination Uniformity
    7. Artifacts & Glare

- Pre-Composite Hard Failure Logic (Hard failure can NEVER be overridden by composite score).
- Unified multi-metric aggregation without double-counting.
- Stores raw metrics, normalized scores, severity flags, and clinical rationale.
"""

import math
import numpy as np
from src.config import (
    QUALITY_WEIGHTS,
    HARD_FAILURES,
    PROVISIONAL_BOUNDARIES,
    CRITICAL_SCORE_THRESHOLD,
    BORDERLINE_SCORE_THRESHOLD,
    MIN_DIMENSION_SCORE_NON_CRITICAL,
    MIN_DIMENSION_SCORE_BORDERLINE,
    ARTIFACT_GLARE_BLOB_NON_CRITICAL_MAX
)


# =====================================================================
# 1. NORMALIZATION FUNCTIONS (Mapping [0.0, 1.0])
# =====================================================================

def normalize_focus(lap_var, tenengrad, width=None, height=None):
    """
    Dimension 1: Focus & Sharpness.
    Combines Variance of Laplacian and Tenengrad Energy.
    Avoids double counting: merges high-correlation gradient metrics into one dimension.
    Scale-aware: accounts for continuous Laplacian scaling with spatial resolution.
    Returns: (score [0.0, 1.0], severity_flag, details_dict)
    """
    lap = float(max(0.0, lap_var))
    ten = float(max(0.0, tenengrad))
    
    # Scale adjustment factor relative to standard 1024 baseline
    # Continuous 2D Laplacian operator scales as (dim / 1024)^2
    if width and height and width > 0 and height > 0:
        scale_adj = (max(width, height) / 1024.0) ** 2
        lap_norm = lap * scale_adj
    else:
        lap_norm = lap * 2.5  # default nominal scale
        
    # Sigmoidal log-scale mappings
    # lap_norm: < 10.0 -> 0.0, 25.0 -> 0.5, 60.0 -> 0.9, > 100.0 -> 1.0
    s_lap = np.clip((np.log(max(1.0, lap_norm)) - np.log(10.0)) / (np.log(80.0) - np.log(10.0)), 0.0, 1.0)
    
    # Tenengrad: < 50.0 -> 0.0, 150.0 -> 0.5, 400.0 -> 0.85, > 700.0 -> 1.0
    s_ten = np.clip((np.log(max(1.0, ten)) - np.log(50.0)) / (np.log(600.0) - np.log(50.0)), 0.0, 1.0)
    
    score = float(0.60 * s_lap + 0.40 * s_ten)
    
    if score >= 0.70:
        flag = "GOOD"
    elif score >= 0.45:
        flag = "BORDERLINE_BLUR"
    else:
        flag = "SEVERE_BLUR"
        
    details = {
        'raw_laplacian_var': lap,
        'raw_tenengrad': ten,
        'scale_normalized_laplacian': round(lap_norm, 2),
        'focus_lap_subscore': round(float(s_lap), 4),
        'focus_ten_subscore': round(float(s_ten), 4),
        'focus_score': round(score, 4),
        'focus_flag': flag
    }
    return score, flag, details


def normalize_brightness(b_mean, b_median, dark_pct, bright_pct):
    """
    Dimension 2: Brightness & Exposure.
    Evaluates retinal mean intensity and clipping percentages strictly inside the FOV.
    Detects: severe underexposure, mild underexposure, acceptable, mild overexposure, severe overexposure.
    Returns: (score [0.0, 1.0], severity_flag, details_dict)
    """
    mean = float(b_mean)
    dark = float(dark_pct)
    bright = float(bright_pct)
    
    # Optimal clinical mean intensity: [70.0, 110.0] (Median across 4,178 images is 90.54)
    if 70.0 <= mean <= 110.0:
        base_score = 1.0 - 0.15 * (abs(mean - 90.0) / 20.0)
        flag = "ACCEPTABLE_EXPOSURE"
    elif mean < 70.0:
        if mean >= 45.0:
            # Mild underexposure [45, 70]
            base_score = 0.40 + 0.45 * ((mean - 45.0) / (70.0 - 45.0))
            flag = "MILD_UNDEREXPOSURE"
        else:
            # Severe underexposure (< 45)
            base_score = max(0.0, 0.40 * (mean - 25.0) / (45.0 - 25.0))
            flag = "SEVERE_UNDEREXPOSURE"
    else: # mean > 110.0
        if mean <= 130.0:
            # Mild overexposure [110, 130]
            base_score = 0.85 - 0.40 * ((mean - 110.0) / (130.0 - 110.0))
            flag = "MILD_OVEREXPOSURE"
        else:
            # Severe overexposure (> 130)
            base_score = max(0.0, 0.45 * (155.0 - mean) / (155.0 - 130.0))
            flag = "SEVERE_OVEREXPOSURE"
            
    # Penalize excessive dark / bright pixel proportions
    dark_penalty = 0.0
    if dark > 4.0:
        dark_penalty = min(0.40, (dark - 4.0) * 0.03)
        if dark > 15.0:
            flag = "SEVERE_UNDEREXPOSURE"
            
    bright_penalty = 0.0
    if bright > 0.40:
        bright_penalty = min(0.40, (bright - 0.40) * 0.35)
        if bright > 1.2:
            flag = "SEVERE_OVEREXPOSURE"
            
    score = float(np.clip(base_score - dark_penalty - bright_penalty, 0.0, 1.0))
    
    details = {
        'raw_brightness_mean': round(mean, 2),
        'raw_dark_pixel_pct': round(dark, 3),
        'raw_bright_pixel_pct': round(bright, 3),
        'brightness_base_score': round(float(base_score), 4),
        'dark_penalty': round(float(dark_penalty), 4),
        'bright_penalty': round(float(bright_penalty), 4),
        'brightness_score': round(score, 4),
        'brightness_flag': flag
    }
    return score, flag, details


def normalize_contrast(contrast_rms, contrast_spread):
    """
    Dimension 3: Contrast & Tonal Separation.
    Evaluates RMS grayscale standard deviation and P95-P5 spread inside retinal field.
    Note: High contrast is NOT monotonically better; excessively high contrast caused
    by harsh specular glare or unnatural edge steps is penalized.
    Returns: (score [0.0, 1.0], severity_flag, details_dict)
    """
    rms = float(contrast_rms)
    spread = float(contrast_spread)
    
    # Optimal RMS contrast: [16.0, 32.0] (Dataset Median is 20.51, IQR: 16.07 - 24.31)
    if 16.0 <= rms <= 32.0:
        score = 1.0
        flag = "GOOD_CONTRAST"
    elif rms < 16.0:
        if rms >= 11.0:
            # Borderline low contrast (mild haze / early media opacity)
            score = 0.45 + 0.55 * ((rms - 11.0) / (16.0 - 11.0))
            flag = "MILD_LOW_CONTRAST"
        else:
            # Severe low contrast (dense cataract haze / flat histogram)
            score = max(0.0, 0.45 * (rms - 6.0) / (11.0 - 6.0))
            flag = "SEVERE_LOW_CONTRAST"
    else: # rms > 32.0
        if rms <= 42.0:
            # High but acceptable contrast
            score = 1.0 - 0.20 * ((rms - 32.0) / (42.0 - 32.0))
            flag = "SLIGHTLY_HIGH_CONTRAST"
        else:
            # Excessively high contrast (often driven by glare / severe saturation)
            score = max(0.50, 0.80 - 0.30 * ((rms - 42.0) / (60.0 - 42.0)))
            flag = "EXCESSIVE_CONTRAST"
            
    score = float(np.clip(score, 0.0, 1.0))
    details = {
        'raw_contrast_rms': round(rms, 2),
        'raw_contrast_spread': round(spread, 2),
        'contrast_score': round(score, 4),
        'contrast_flag': flag
    }
    return score, flag, details


def normalize_noise(noise_std, local_var_mean, noise_decoupled_std=None):
    """
    Dimension 4: High-Frequency Sensor Noise.
    Inverted metric: Lower noise corresponds to HIGHER quality score.
    Uses anatomical-decoupled noise if available to avoid penalizing microvascular detail.
    Returns: (score [0.0, 1.0], severity_flag, details_dict)
    """
    raw_std = float(noise_std)
    lvar = float(local_var_mean)
    
    # Use decoupled noise metric if provided; otherwise fall back to raw noise_std
    if noise_decoupled_std is not None and not np.isnan(noise_decoupled_std):
        std = float(noise_decoupled_std)
        used_decoupled = True
    else:
        std = raw_std
        used_decoupled = False
    
    # Scale calibrated for noise:
    # When using decoupled MAD noise: typical range is [0.40, 1.80]
    # When using raw residual std: typical range is [0.48, 2.30]
    if used_decoupled:
        if std <= 0.80:
            score = 1.0 - 0.10 * (std / 0.80)
            flag = "LOW_NOISE"
        elif std <= 1.30:
            score = 0.90 - 0.25 * ((std - 0.80) / (1.30 - 0.80))
            flag = "ACCEPTABLE_NOISE"
        elif std <= 1.80:
            score = 0.65 - 0.35 * ((std - 1.30) / (1.80 - 1.30))
            flag = "MODERATE_NOISE"
        else:
            score = max(0.0, 0.30 * (2.40 - std) / (2.40 - 1.80))
            flag = "SEVERE_NOISE"
    else:
        if std <= 1.10:
            score = 1.0 - 0.10 * (std / 1.10)
            flag = "LOW_NOISE"
        elif std <= 1.80:
            score = 0.90 - 0.25 * ((std - 1.10) / (1.80 - 1.10))
            flag = "ACCEPTABLE_NOISE"
        elif std <= 2.30:
            score = 0.65 - 0.35 * ((std - 1.80) / (2.30 - 1.80))
            flag = "MODERATE_NOISE"
        else:
            score = max(0.0, 0.30 * (2.95 - std) / (2.95 - 2.30))
            flag = "SEVERE_NOISE"
        
    score = float(np.clip(score, 0.0, 1.0))
    details = {
        'raw_noise_residual_std': round(raw_std, 3),
        'raw_noise_decoupled_std': round(std, 3) if used_decoupled else round(raw_std, 3),
        'raw_noise_local_var_mean': round(lvar, 2),
        'noise_score': round(score, 4),
        'noise_flag': flag
    }
    return score, flag, details


def normalize_fov(fov_coverage, fov_circularity, fov_area, width, height):
    """
    Dimension 5: Retinal Field of View (FOV).
    Evaluates FOV completeness using geometry, circularity, area, and canvas aspect ratio.
    CRITICAL: Does NOT reject valid square crops (~0.78-0.82 coverage) or rectangular camera
    images (~0.65-0.75 coverage). Compares retinal area to maximum inscribed circle.
    Returns: (score [0.0, 1.0], severity_flag, details_dict)
    """
    cov = float(fov_coverage)
    circ = float(fov_circularity)
    area = float(fov_area)
    w = float(width)
    h = float(height)
    
    # 1. Theoretical maximum inscribed circular area: pi/4 * min(W, H)^2
    min_dim = min(w, h)
    max_circle_area = (math.pi / 4.0) * (min_dim ** 2)
    completeness = area / max_circle_area if max_circle_area > 0 else 0.0
    
    # 2. Circularity score
    # Most valid fundus cameras produce circularity between 0.92 and 0.997
    if circ >= 0.92:
        s_circ = 1.0
    elif circ >= 0.85:
        s_circ = 0.70 + 0.30 * ((circ - 0.85) / (0.92 - 0.85))
    else:
        s_circ = max(0.0, 0.70 * ((circ - 0.75) / (0.85 - 0.75)))
        
    # 3. Completeness score relative to inscribed circle
    # In square images, completeness is ~0.94-1.0. In rectangular cameras, retina often
    # extends horizontally beyond min_dim, so completeness can be >= 1.0.
    if completeness >= 0.85:
        s_comp = 1.0
    elif completeness >= 0.75:
        s_comp = 0.65 + 0.35 * ((completeness - 0.75) / (0.85 - 0.75))
    else:
        s_comp = max(0.0, 0.65 * ((completeness - 0.50) / (0.75 - 0.50)))
        
    # 4. Absolute area score
    # Protects against extreme low-res thumbnail artifacts
    if area >= 500000:
        s_area = 1.0
    elif area >= 200000:
        s_area = 0.75 + 0.25 * ((area - 200000) / 300000)
    else:
        s_area = max(0.0, 0.75 * (area / 200000))
        
    score = float(np.clip(0.40 * s_circ + 0.40 * s_comp + 0.20 * s_area, 0.0, 1.0))
    
    if score >= 0.85:
        flag = "COMPLETE_FOV"
    elif score >= 0.65:
        flag = "BORDERLINE_FOV"
    else:
        flag = "INSUFFICIENT_FOV"
        
    details = {
        'raw_fov_coverage': round(cov, 4),
        'raw_fov_circularity': round(circ, 4),
        'raw_fov_retinal_area': int(area),
        'fov_completeness_ratio': round(float(completeness), 4),
        'fov_circularity_subscore': round(float(s_circ), 4),
        'fov_completeness_subscore': round(float(s_comp), 4),
        'fov_area_subscore': round(float(s_area), 4),
        'fov_score': round(score, 4),
        'fov_flag': flag
    }
    return score, flag, details


def normalize_illumination(map_cov, center_edge_ratio):
    """
    Dimension 6: Illumination Uniformity.
    Combines Gaussian illumination map CoV and Center-to-Edge gradient ratio.
    Avoids double counting: both lighting metrics merged into single illumination dimension.
    Returns: (score [0.0, 1.0], severity_flag, details_dict)
    """
    cov = float(map_cov)
    ratio = float(center_edge_ratio)
    
    # CoV Subscore: Median is 0.217, P75 is 0.266, P95 is 0.372
    if cov <= 0.24:
        s_cov = 1.0
    elif cov <= 0.38:
        # Moderate vignetting / gradient
        s_cov = 0.65 + 0.35 * ((0.38 - cov) / (0.38 - 0.24))
    else:
        # Severe illumination non-uniformity
        s_cov = max(0.0, 0.65 * ((0.52 - cov) / (0.52 - 0.38)))
        
    # Center-to-Edge Ratio Subscore: Natural clinical fundus has mild vignetting ~1.15
    ratio_dev = abs(ratio - 1.15)
    if ratio_dev <= 0.15:
        s_ratio = 1.0
    elif ratio_dev <= 0.35:
        s_ratio = 0.70 + 0.30 * ((0.35 - ratio_dev) / 0.20)
    else:
        s_ratio = max(0.0, 0.70 * ((0.65 - ratio_dev) / 0.30))
        
    score = float(np.clip(0.65 * s_cov + 0.35 * s_ratio, 0.0, 1.0))
    
    if score >= 0.80:
        flag = "UNIFORM_ILLUMINATION"
    elif score >= 0.50:
        flag = "MODERATE_UNEVEN_ILLUMINATION"
    else:
        flag = "SEVERE_UNEVEN_ILLUMINATION"
        
    details = {
        'raw_illum_map_cov': round(cov, 4),
        'raw_illum_center_edge_ratio': round(ratio, 3),
        'illum_cov_subscore': round(float(s_cov), 4),
        'illum_ratio_subscore': round(float(s_ratio), 4),
        'illumination_score': round(score, 4),
        'illumination_flag': flag
    }
    return score, flag, details


def normalize_artifact(sat_pct, glare_blobs):
    """
    Dimension 7: Artifacts & Specular Glare.
    Distinguishes legitimate black camera border from genuine capture artifacts INSIDE retina.
    Evaluates saturated pixel percentage and distinct glare reflection blobs.
    Returns: (score [0.0, 1.0], severity_flag, details_dict)
    """
    sat = float(sat_pct)
    blobs = int(glare_blobs)
    
    # In pristine retina: sat_pct is 0.000%, glare_blobs is 0
    if sat <= 0.01 and blobs == 0:
        score = 1.0
        flag = "CLEAN_NO_ARTIFACTS"
    elif sat <= 0.08 and blobs <= 2:
        # Minor specular reflection (non-critical)
        score = 0.80 - 0.20 * (sat / 0.08)
        flag = "MINOR_GLARE"
    elif sat <= 0.30 or blobs <= 5:
        # Moderate glare patch
        score = 0.50 - 0.25 * ((sat - 0.08) / 0.22)
        flag = "MODERATE_GLARE"
    else:
        # Severe glare obscuring retinal structures
        score = max(0.0, 0.25 * ((0.60 - sat) / 0.30))
        flag = "SEVERE_GLARE"
        
    score = float(np.clip(score, 0.0, 1.0))
    details = {
        'raw_artifact_sat_pixel_pct': round(sat, 4),
        'raw_artifact_glare_blob_count': blobs,
        'artifact_score': round(score, 4),
        'artifact_flag': flag
    }
    return score, flag, details


# =====================================================================
# 2. HARD FAILURE LOGIC (Evaluated BEFORE composite scoring)
# =====================================================================

def evaluate_hard_failures(raw_metrics):
    """
    Evaluates whether an image triggers any non-recoverable Hard Failure.
    The composite score NEVER overrides a hard failure.
    
    Hard Failure Triggers:
    1. Severe optical defocus / motion blur (LapVar < 4.5 AND Tenengrad < 50)
    2. Severe underexposure (Mean < 40.0 OR Dark Pct > 18.0%)
    3. Severe overexposure (Mean > 140.0 AND Bright Pct > 1.2%)
    4. Severe illumination failure (CoV > 0.52 OR Center/Edge Ratio > 1.75)
    5. Severe glare artifact cluster (Sat Pct > 0.50% AND Glare Blobs >= 5)
    6. Insufficient / genuinely cut-off retinal field (Area < 150k OR Circ < 0.78 OR Completeness < 0.70)
    """
    reasons = []
    
    # 1. FIX 2: Scale-Aware Severe Defocus Blur
    lap = float(raw_metrics.get('focus_var_laplacian', 0.0))
    ten = float(raw_metrics.get('focus_tenengrad', 0.0))
    w = raw_metrics.get('width', 1024)
    h = raw_metrics.get('height', 1024)
    scale_adj = (max(w, h) / 1024.0) ** 2 if (w and h and w > 0 and h > 0) else 1.0
    lap_norm = lap * scale_adj
    
    blur_norm_min = HARD_FAILURES.get('blur_normalized_laplacian_min', 8.0)
    blur_raw_min = HARD_FAILURES.get('blur_laplacian_var_raw_min', 4.0)
    blur_ten_max = HARD_FAILURES.get('blur_tenengrad_raw_max', 120.0)
    
    if lap_norm < blur_norm_min or (lap < blur_raw_min and ten < blur_ten_max):
        reasons.append(f"Severe Defocus Blur (NormLap={lap_norm:.1f} < {blur_norm_min}, RawLap={lap:.2f}, Tenengrad={ten:.1f})")
        
    # 2. Severe Underexposure
    b_mean = float(raw_metrics.get('brightness_mean', 0.0))
    b_dark = float(raw_metrics.get('brightness_dark_pct', 0.0))
    if b_mean < HARD_FAILURES['brightness_mean_min']:
        reasons.append(f"Severe Underexposure (Retinal Mean Intensity={b_mean:.1f} < {HARD_FAILURES['brightness_mean_min']})")
    elif b_dark > HARD_FAILURES['brightness_dark_pct_max']:
        reasons.append(f"Excessive Darkness (Dark Pixel Pct={b_dark:.1f}% > {HARD_FAILURES['brightness_dark_pct_max']}%)")
        
    # 3. FIX 1: Severe Overexposure / Bleaching (Safer OR-based rule)
    b_bright = float(raw_metrics.get('brightness_bright_pct', 0.0))
    if b_mean > HARD_FAILURES['brightness_mean_max']:
        reasons.append(f"Severe Flash Bleaching (Retinal Mean Intensity={b_mean:.1f} > {HARD_FAILURES['brightness_mean_max']})")
    elif b_bright > HARD_FAILURES['brightness_bright_pct_max']:
        reasons.append(f"Severe Sensor Saturation (Saturated Pixel Pct={b_bright:.2f}% > {HARD_FAILURES['brightness_bright_pct_max']}%)")
        
    # 4. FIX 5: Severe Illumination Failure (Buffered Radial Falloff + Quadrant Shadow)
    cov_i = float(raw_metrics.get('illum_map_cov', 0.0))
    rat_i = float(raw_metrics.get('illum_center_edge_ratio', 1.0))
    cov_max = HARD_FAILURES['illum_map_cov_max']
    rat_max = HARD_FAILURES['illum_center_edge_ratio_max']
    rat_buf = HARD_FAILURES['illum_center_edge_ratio_buffer']
    cov_buf = HARD_FAILURES['illum_cov_buffer_min']
    
    if cov_i > cov_max:
        reasons.append(f"Severe Non-Uniform Illumination (Map CoV={cov_i:.3f} > {cov_max})")
    elif rat_i > rat_max:
        reasons.append(f"Extreme Center/Edge Vignetting (Ratio={rat_i:.2f} > {rat_max})")
    elif rat_i > rat_buf and cov_i > cov_buf:
        reasons.append(f"Severe Peripheral Blackout & Gradient (Ratio={rat_i:.2f} > {rat_buf}, CoV={cov_i:.3f} > {cov_buf})")
        
    # 5. Severe Glare / Specular Flash Reflection
    sat_pct = float(raw_metrics.get('artifact_sat_pixel_pct', 0.0))
    blobs = int(raw_metrics.get('artifact_glare_blob_count', 0))
    if sat_pct > HARD_FAILURES['artifact_sat_pixel_pct_max'] and blobs >= HARD_FAILURES['artifact_glare_blob_count_min']:
        reasons.append(f"Severe Corneal Glare Artifacts ({blobs} blobs, {sat_pct:.2f}% saturation)")
        
    # 6. Insufficient / Severely Truncated FOV
    area = float(raw_metrics.get('fov_retinal_area', 0))
    circ = float(raw_metrics.get('fov_circularity', 1.0))
    max_circle = (math.pi / 4.0) * (min(w, h) ** 2)
    comp = area / max_circle if max_circle > 0 else 0.0
    
    if area < HARD_FAILURES['fov_retinal_area_min']:
        reasons.append(f"Insufficient Retinal Area ({int(area):,} px < {HARD_FAILURES['fov_retinal_area_min']:,} px)")
    elif circ < HARD_FAILURES['fov_circularity_min']:
        reasons.append(f"Distorted/Truncated Retinal Boundary (Circularity={circ:.3f} < {HARD_FAILURES['fov_circularity_min']})")
    elif comp < HARD_FAILURES['fov_completeness_min']:
        reasons.append(f"Incomplete Inscribed Retinal Aperture (Completeness={comp:.2f} < {HARD_FAILURES['fov_completeness_min']})")
        
    is_hard_failure = len(reasons) > 0
    return is_hard_failure, reasons


# =====================================================================
# 3. MASTER QUALITY CLASSIFICATION & DECISION ENGINE
# =====================================================================

def classify_fundus_image_quality(raw_metrics):
    """
    Master Decision Engine evaluating Module 1 Image Quality.
    
    Input:
        raw_metrics (dict): Output from Phase 1 inventory and Phase 2 deterministic quality metrics.
        
    Output:
        result (dict): Complete classification record containing:
            - status: 'CRITICAL' | 'BORDERLINE' | 'NON-CRITICAL'
            - action: 'RECAPTURE' | 'ENHANCEMENT' | 'OK TO GO'
            - overall_score: [0.0, 1.0] weighted composite score
            - 7 dimension scores & severity flags
            - is_hard_failure (bool) & failure reasons
            - clinical rationale summary
    """
    w = raw_metrics.get('width', 1024)
    h = raw_metrics.get('height', 1024)
    
    # 1. Compute 7 Normalized Dimension Scores [0.0, 1.0]
    s_focus, f_focus, det_focus = normalize_focus(
        raw_metrics.get('focus_var_laplacian', 0.0),
        raw_metrics.get('focus_tenengrad', 0.0),
        width=w, height=h
    )
    
    s_bright, f_bright, det_bright = normalize_brightness(
        raw_metrics.get('brightness_mean', 85.0),
        raw_metrics.get('brightness_median', 85.0),
        raw_metrics.get('brightness_dark_pct', 1.0),
        raw_metrics.get('brightness_bright_pct', 0.0)
    )
    
    s_contrast, f_contrast, det_contrast = normalize_contrast(
        raw_metrics.get('contrast_rms', 20.0),
        raw_metrics.get('contrast_spread_p95_p5', 50.0)
    )
    
    s_noise, f_noise, det_noise = normalize_noise(
        raw_metrics.get('noise_residual_std', 1.3),
        raw_metrics.get('noise_local_var_mean', 8.0),
        raw_metrics.get('noise_decoupled_std', None)
    )
    
    s_fov, f_fov, det_fov = normalize_fov(
        raw_metrics.get('fov_coverage', 0.75),
        raw_metrics.get('fov_circularity', 0.95),
        raw_metrics.get('fov_retinal_area', 1000000),
        w, h
    )
    
    s_illum, f_illum, det_illum = normalize_illumination(
        raw_metrics.get('illum_map_cov', 0.22),
        raw_metrics.get('illum_center_edge_ratio', 1.15)
    )
    
    s_art, f_art, det_art = normalize_artifact(
        raw_metrics.get('artifact_sat_pixel_pct', 0.0),
        raw_metrics.get('artifact_glare_blob_count', 0)
    )
    
    # 2. Check Pre-Composite Hard Failures
    is_hard_failure, failure_reasons = evaluate_hard_failures(raw_metrics)
    
    # 3. Calculate Weighted Composite Quality Score
    overall_score = (
        QUALITY_WEIGHTS['focus'] * s_focus +
        QUALITY_WEIGHTS['brightness'] * s_bright +
        QUALITY_WEIGHTS['contrast'] * s_contrast +
        QUALITY_WEIGHTS['noise'] * s_noise +
        QUALITY_WEIGHTS['fov'] * s_fov +
        QUALITY_WEIGHTS['illumination'] * s_illum +
        QUALITY_WEIGHTS['artifact'] * s_art
    )
    overall_score = float(np.clip(overall_score, 0.0, 1.0))
    
    # Critical dimension score check (Focus, Brightness, Contrast, FOV)
    min_crit_score = min(s_focus, s_bright, s_contrast, s_fov)
    min_dim_score = min(s_focus, s_bright, s_contrast, s_noise, s_fov, s_illum, s_art)
    glare_blobs = int(raw_metrics.get('artifact_glare_blob_count', 0))
    
    # =================================================================
    # FIX 7: EXACT THREE-CLASS QUALITY HIERARCHY
    # =================================================================
    # STEP 1: Hard failure? -> ALWAYS CRITICAL -> RECAPTURE
    if is_hard_failure:
        status = "CRITICAL"
        action = "RECAPTURE"
        rationale = f"Hard Failure Triggered: {'; '.join(failure_reasons)}"
        
    # STEP 2 & 3: FIX 3 — Critical Dimension Floor Check (< 0.20)
    # Executed BEFORE accepting BORDERLINE (unrecoverable single-dimension failure)
    elif min_crit_score < MIN_DIMENSION_SCORE_BORDERLINE:
        status = "CRITICAL"
        action = "RECAPTURE"
        fatal_dims = []
        if s_focus < MIN_DIMENSION_SCORE_BORDERLINE: fatal_dims.append(f"Focus ({s_focus:.3f})")
        if s_bright < MIN_DIMENSION_SCORE_BORDERLINE: fatal_dims.append(f"Exposure ({s_bright:.3f})")
        if s_contrast < MIN_DIMENSION_SCORE_BORDERLINE: fatal_dims.append(f"Contrast ({s_contrast:.3f})")
        if s_fov < MIN_DIMENSION_SCORE_BORDERLINE: fatal_dims.append(f"FOV ({s_fov:.3f})")
        rationale = f"Critical Dimension Floor Violated (< {MIN_DIMENSION_SCORE_BORDERLINE}): {', '.join(fatal_dims)}"
        
    # STEP 4: FIX 4 — Multi-Blob Glare Gating (glare_blob_count >= 5)
    # NON-CRITICAL is forbidden. Must be at least BORDERLINE -> ENHANCEMENT
    elif glare_blobs > ARTIFACT_GLARE_BLOB_NON_CRITICAL_MAX:
        if overall_score >= CRITICAL_SCORE_THRESHOLD:
            status = "BORDERLINE"
            action = "ENHANCEMENT"
            rationale = f"Multi-blob specular glare cluster ({glare_blobs} blobs >= {ARTIFACT_GLARE_BLOB_NON_CRITICAL_MAX+1}) requires inpainting/enhancement; NON-CRITICAL forbidden (Overall Score = {overall_score:.3f})"
        else:
            status = "CRITICAL"
            action = "RECAPTURE"
            rationale = f"Multi-blob specular glare cluster ({glare_blobs} blobs) with sub-critical composite score (Overall Score = {overall_score:.3f} < {CRITICAL_SCORE_THRESHOLD})"
            
    # STEP 5: Composite Score Tiers
    # Rule A: High composite score AND all major dimensions >= 0.35 -> NON-CRITICAL -> OK TO GO
    elif overall_score >= BORDERLINE_SCORE_THRESHOLD and min_dim_score >= MIN_DIMENSION_SCORE_NON_CRITICAL:
        status = "NON-CRITICAL"
        action = "OK TO GO"
        rationale = f"All 7 quality dimensions within acceptable clinical limits (Overall Score = {overall_score:.3f} >= {BORDERLINE_SCORE_THRESHOLD}, Min Dimension = {min_dim_score:.3f})"
        
    # Rule B: Intermediate score OR correctable borderline dimensions -> BORDERLINE -> ENHANCEMENT
    elif overall_score >= CRITICAL_SCORE_THRESHOLD:
        status = "BORDERLINE"
        action = "ENHANCEMENT"
        deficient_dims = []
        if s_focus < 0.65: deficient_dims.append("Focus/Defocus")
        if s_bright < 0.65: deficient_dims.append("Exposure")
        if s_contrast < 0.65: deficient_dims.append("Contrast")
        if s_illum < 0.65: deficient_dims.append("Illumination")
        if s_noise < 0.65: deficient_dims.append("Noise")
        dims_str = ", ".join(deficient_dims) if deficient_dims else "Moderate global quality"
        rationale = f"Intermediate quality suitable for enhancement ({dims_str}; Overall Score = {overall_score:.3f})"
        
    # Rule C: Sub-critical composite score -> CRITICAL -> RECAPTURE
    else:
        status = "CRITICAL"
        action = "RECAPTURE"
        rationale = f"Composite quality score below critical viability threshold (Overall Score = {overall_score:.3f} < {CRITICAL_SCORE_THRESHOLD})"
        
    # =================================================================
    # FIX 8: DIRECTIVES AND INVARIANT ASSERTION CHECKER
    # =================================================================
    directive = action
    ok_to_go = (status == "NON-CRITICAL")
    recapture_required = (status == "CRITICAL")
    enhancement_required = (status == "BORDERLINE")
    
    # Strict Invariant Assertions:
    if status == "CRITICAL":
        assert ok_to_go is False, f"Invariant violation: CRITICAL with ok_to_go=True in {raw_metrics.get('filename')}"
        assert recapture_required is True, f"Invariant violation: CRITICAL with recapture_required=False in {raw_metrics.get('filename')}"
        assert enhancement_required is False, f"Invariant violation: CRITICAL with enhancement_required=True in {raw_metrics.get('filename')}"
    elif status == "BORDERLINE":
        assert ok_to_go is False, f"Invariant violation: BORDERLINE with ok_to_go=True in {raw_metrics.get('filename')}"
        assert recapture_required is False, f"Invariant violation: BORDERLINE with recapture_required=True in {raw_metrics.get('filename')}"
        assert enhancement_required is True, f"Invariant violation: BORDERLINE with enhancement_required=False in {raw_metrics.get('filename')}"
    elif status == "NON-CRITICAL":
        assert ok_to_go is True, f"Invariant violation: NON-CRITICAL with ok_to_go=False in {raw_metrics.get('filename')}"
        assert recapture_required is False, f"Invariant violation: NON-CRITICAL with recapture_required=True in {raw_metrics.get('filename')}"
        assert enhancement_required is False, f"Invariant violation: NON-CRITICAL with enhancement_required=True in {raw_metrics.get('filename')}"
    else:
        raise ValueError(f"Invalid quality class: {status}")
        
    # Assemble comprehensive result dictionary
    result = {
        'filename': raw_metrics.get('filename', 'unknown'),
        'status': status,
        'action': action,
        'directive': directive,
        'ok_to_go': ok_to_go,
        'recapture_required': recapture_required,
        'enhancement_required': enhancement_required,
        'overall_score': round(overall_score, 4),
        
        # 7 Quality Dimension Scores
        'score_focus': round(s_focus, 4),
        'score_brightness': round(s_bright, 4),
        'score_contrast': round(s_contrast, 4),
        'score_noise': round(s_noise, 4),
        'score_fov': round(s_fov, 4),
        'score_illumination': round(s_illum, 4),
        'score_artifact': round(s_art, 4),
        
        # Dimension Severity Flags
        'flag_focus': f_focus,
        'flag_brightness': f_bright,
        'flag_contrast': f_contrast,
        'flag_noise': f_noise,
        'flag_fov': f_fov,
        'flag_illumination': f_illum,
        'flag_artifact': f_art,
        
        # Hard Failure Information
        'is_hard_failure': is_hard_failure,
        'hard_failure_reasons': '; '.join(failure_reasons) if failure_reasons else "None",
        'rationale': rationale
    }
    
    # Merge detailed dimension breakdowns
    result.update(det_focus)
    result.update(det_bright)
    result.update(det_contrast)
    result.update(det_noise)
    result.update(det_fov)
    result.update(det_illum)
    result.update(det_art)
    
    return result
