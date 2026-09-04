"""
Module 1: Fundus Image Quality Assessment (Decision Engine Configuration).

All thresholds and weights established here are PROVISIONAL, calibrated directly
against the empirical distributions of all 4,178 fundus photographs (APTOS + IDRiD)
as established in reports/dataset_analysis.csv and reports/dataset_summary.md.

Clinical Disclaimer:
labels.xlsx contains Diabetic Retinopathy (DR) disease severity grades (0-4),
NOT clinical image quality or gradability labels. In the absence of separate
clinician-graded quality ground truth, these thresholds are mathematically
anchored to empirical population quantiles (P5, P10, P25, P50, P75, P90, P95).
"""

# =====================================================================
# 1. QUALITY DIMENSION COMPOSITE WEIGHTS
# =====================================================================
# 7 orthogonal quality dimensions. Weights sum strictly to 1.00.
# Avoids double counting: sub-metrics (e.g. Laplacian Var, Tenengrad) are
# aggregated into a single dimension before weighting.
QUALITY_WEIGHTS = {
    'focus': 0.25,        # Sharpness is paramount for microaneurysm & vessel gradability
    'brightness': 0.15,   # Exposure must permit diagnostic tissue visibility
    'contrast': 0.15,     # Tonal separation needed to resolve lesions from background
    'noise': 0.10,        # High-frequency sensor grain degradation
    'fov': 0.15,          # Retinal field completeness, circularity & area
    'illumination': 0.10, # Uniformity across central & peripheral retina
    'artifact': 0.10      # Glare blobs and specular reflections obscuring tissue
}

# Assert unity sum to guarantee deterministic bounded score in [0.0, 1.0]
assert abs(sum(QUALITY_WEIGHTS.values()) - 1.0) < 1e-6, "Weights must sum to 1.0"


# =====================================================================
# 2. HARD FAILURE THRESHOLDS (Evaluated BEFORE composite scoring)
# =====================================================================
# If any hard failure condition is met, the image is immediately assigned:
# Status: CRITICAL, Action: RECAPTURE.
# The composite score NEVER overrides a hard failure.
HARD_FAILURES = {
    # FIX 2: Severe optical defocus / motion blur (scale-aware)
    'blur_normalized_laplacian_min': 8.0,   # Scale-normalized Laplacian variance floor
    'blur_laplacian_var_raw_min': 4.0,      # Raw Laplacian variance floor
    'blur_tenengrad_raw_max': 120.0,        # Tenengrad ceiling for raw blur confirmation
    
    # Severe underexposure (tissue signal submerged near sensor noise floor)
    'brightness_mean_min': 40.0,
    'brightness_dark_pct_max': 18.0,  # >18% pixels below intensity 20
    
    # FIX 1: Severe overexposure (diffuse bleaching OR sensor saturation clipping)
    'brightness_mean_max': 140.0,     # Diffuse flash bleaching
    'brightness_bright_pct_max': 1.5, # >1.5% pixels saturated >240
    
    # FIX 5: Severe illumination failure (quadrant shadow OR extreme peripheral blackout)
    'illum_map_cov_max': 0.52,                 # Severe quadrant shadow / heavy unrecoverable gradient
    'illum_center_edge_ratio_max': 1.85,       # Extreme peripheral blackout (unbuffered)
    'illum_center_edge_ratio_buffer': 1.75,    # Marginal vignetting buffer (requires CoV > 0.45)
    'illum_cov_buffer_min': 0.45,
    
    # Severe glare / specular corneal flash reflection
    'artifact_sat_pixel_pct_max': 0.50, # Saturated retina pixels
    'artifact_glare_blob_count_min': 5, # At least 5 distinct glare reflection blobs
    
    # Insufficient / severely clipped retinal field of view
    'fov_retinal_area_min': 150000,    # Absolute minimum retinal pixel count
    'fov_circularity_min': 0.78,       # Significant boundary truncation / crescent crop
    'fov_completeness_min': 0.70       # Ratio of retinal area to maximum inscribed circle
}


# =====================================================================
# 3. PROVISIONAL METRIC CALIBRATION BOUNDARIES
# =====================================================================
# Anchored to empirical quantiles: P5, P25, Median (P50), P75, P95.
PROVISIONAL_BOUNDARIES = {
    'focus': {
        # Median LapVar = 23.48, P25 = 11.12, P5 = 5.22
        'critical_max': 6.0,       # Severe blur -> low gradability
        'borderline_min': 6.0,
        'borderline_max': 16.0,    # Mild-to-moderate blur -> candidate for sharpening
        'good_min': 16.0           # Clear microvascular detail
    },
    'brightness': {
        # Median Mean = 90.54, P25 = 74.85, P75 = 101.42, P5 = 49.82, P95 = 115.68
        'under_severe_max': 45.0,  # Severe darkness
        'under_mild_max': 70.0,    # Mild underexposure -> candidate for gamma/illumination boost
        'optimal_min': 70.0,       # Optimal diagnostic range [70, 110]
        'optimal_max': 110.0,
        'over_mild_max': 130.0,    # Mild overexposure
        'over_severe_min': 130.0   # Severe overexposure
    },
    'contrast': {
        # Median RMS = 20.51, P25 = 16.07, P75 = 24.31, P5 = 12.51, P95 = 30.41
        'critical_low_max': 11.0,  # Dense cataract / media haze
        'borderline_low_max': 16.0,# Mild haze -> candidate for CLAHE contrast enhancement
        'optimal_min': 16.0,       # Healthy retinal contrast
        'optimal_max': 32.0,
        'excessive_max': 45.0      # Excessively high contrast (often artifact-driven)
    },
    'noise': {
        # Median Std = 1.32, P75 = 1.87, P95 = 2.17, Max = 2.94
        'optimal_max': 1.10,       # Very clean sensor floor
        'acceptable_max': 1.80,    # Typical diagnostic fundus
        'borderline_max': 2.30,    # Noticeable analog gain grain -> candidate for denoising
        'severe_min': 2.30         # Heavy grain obscuring micro-aneurysms
    },
    'fov': {
        # Circular inscribed fundus in square canvas = ~0.78-0.82 coverage.
        # Rectangular camera fundus = ~0.65-0.75 coverage.
        'circularity_good_min': 0.92,
        'circularity_borderline_min': 0.85,
        'completeness_good_min': 0.85,
        'completeness_borderline_min': 0.75
    },
    'illumination': {
        # Median CoV = 0.217, P75 = 0.266, P95 = 0.372
        'cov_good_max': 0.25,      # Uniform illumination
        'cov_borderline_max': 0.40,# Moderate peripheral vignetting -> correctable
        'cov_critical_min': 0.45,  # Severe quadrant shadow
        'ratio_good_min': 0.90,    # Center-to-edge ratio
        'ratio_good_max': 1.30,
        'ratio_borderline_max': 1.60
    },
    'artifact': {
        'sat_pct_good_max': 0.02,
        'sat_pct_borderline_max': 0.20,
        'glare_blobs_good_max': 0,
        'glare_blobs_borderline_max': 3
    }
}


# =====================================================================
# 4. DECISION THRESHOLDS & THREE-CLASS ENGINE
# =====================================================================
# THREE mutually exclusive quality classes:
# 1. CRITICAL     -> Action: RECAPTURE
# 2. BORDERLINE   -> Action: ENHANCEMENT
# 3. NON-CRITICAL -> Action: OK TO GO

CRITICAL_SCORE_THRESHOLD = 0.50
BORDERLINE_SCORE_THRESHOLD = 0.70

# FIX 3: Minimum allowable individual score for BORDERLINE classification
# If any critical dimension (Focus, Brightness, Contrast, FOV) has score < 0.20,
# the image CANNOT enter enhancement and is immediately forced to CRITICAL -> RECAPTURE
MIN_DIMENSION_SCORE_BORDERLINE = 0.20

# Minimum allowable individual score for NON-CRITICAL classification
# If any single dimension has score < 0.35, the image CANNOT be NON-CRITICAL
MIN_DIMENSION_SCORE_NON_CRITICAL = 0.35

# FIX 4: Multi-blob glare gating:
# If glare_blob_count >= 5, NON-CRITICAL is forbidden (must be BORDERLINE or CRITICAL)
ARTIFACT_GLARE_BLOB_NON_CRITICAL_MAX = 4


# =====================================================================
# 5. DETERMINISTIC ENHANCEMENT CONFIGURATION (BORDERLINE IMAGES ONLY)
# =====================================================================
# Strict, configurable safety bounds for post-triage BORDERLINE enhancement.
# Enhancement is never applied to CRITICAL or NON-CRITICAL images.
ENHANCEMENT_CONFIG = {
    # General Safety Bounds
    'max_operations_per_image': 4,
    'min_retinal_area_for_enhancement': 150000,
    
    # A. Contrast Enhancement (CLAHE on L-channel of LAB)
    'clahe_clip_limit': 2.0,           # Conservative clip limit to avoid over-amplifying noise
    'clahe_clip_limit_max': 3.0,       # Strict upper safety ceiling
    'clahe_tile_grid_size': (8, 8),
    
    # B. Exposure / Intensity Correction (Gamma Correction on L-channel)
    'gamma_underexposed': 0.80,        # Lifts midtones for mean in [45.0, 70.0]
    'gamma_min': 0.70,                 # Strict lower safety limit (never below 0.65)
    'gamma_overexposed': 1.15,         # Tones down midtones for mean in [110.0, 130.0]
    'gamma_max': 1.30,                 # Strict upper safety ceiling
    
    # C. Illumination Correction (Flat-Fielding via Normalized Convolution)
    'illum_gain_min': 0.75,            # Maximum attenuation of bright posterior pole
    'illum_gain_max': 1.35,            # Maximum boost of shaded peripheral retina
    'illum_filter_sigma_fraction': 0.05,# Gaussian sigma as fraction of max dimension (~50-100 px)
    
    # D. Noise Reduction (Bilateral Filter on Retinal Mask)
    'denoise_diameter': 3,             # Small neighborhood preserving fine capillaries
    'denoise_sigma_color': 15.0,       # Edge-preserving color variance (preserves vessel borders)
    'denoise_sigma_color_max': 25.0,   # Strict upper limit
    'denoise_sigma_space': 5.0,        # Spatial coordinate variance
    'denoise_sigma_space_max': 10.0,   # Strict upper limit
    
    # E. Mild Sharpening (Unsharp Masking on Retinal Mask)
    'sharpen_amount': 0.30,            # Very conservative blend factor (no halos)
    'sharpen_amount_max': 0.50,        # Strict upper limit
    'sharpen_kernel_sigma': 1.2,
    
    # F. Glare Attenuation (Punctate Specular Inpainting)
    'glare_max_blob_area_recoverable': 250, # Only small punctate blobs (<250 px); large blobs remain untouched
    'glare_inpaint_radius': 3
}


