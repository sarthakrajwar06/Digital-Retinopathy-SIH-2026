"""
Module 1: Fundus Image Quality Assessment
Preliminary Deterministic Quality Measurements Module (Optimized Version).

Implements preliminary deterministic image quality metrics inside the detected
retinal field (excluding black background):
A. Focus / Blur
B. Brightness / Exposure
C. Contrast
D. Noise
E. Field of View
F. Illumination (Optimized: Downsampled coordinate grids at ~256x256)
G. Artifacts
"""

import cv2
import numpy as np


def compute_image_quality_metrics(image_bgr, fov_info):
    """
    Calculate deterministic quality measurements for a fundus image
    strictly inside the detected retinal field.
    
    Parameters:
    -----------
    image_bgr : np.ndarray
        Input image in BGR format (H, W, 3).
    fov_info : dict
        Output from detect_retinal_fov containing 'mask', 'mask_eroded', etc.
        
    Returns:
    --------
    dict: dictionary of metric names and numeric values.
    """
    h, w, c = image_bgr.shape
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    
    mask = fov_info['mask']
    mask_eroded = fov_info['mask_eroded']
    retinal_area = fov_info['retinal_area']
    image_area = fov_info['image_area']
    fov_coverage = fov_info['fov_coverage']
    
    # Pixel values strictly inside retinal field
    retina_mask_bool = mask > 0
    eroded_mask_bool = mask_eroded > 0
    
    retina_gray = gray[retina_mask_bool]
    eroded_gray = gray[eroded_mask_bool]
    
    # Safety guard if mask is degenerate
    if len(retina_gray) == 0:
        retina_gray = gray.ravel()
        eroded_gray = gray.ravel()
        retina_mask_bool = np.ones((h, w), dtype=bool)
        eroded_mask_bool = np.ones((h, w), dtype=bool)
        retinal_area = h * w
    elif len(eroded_gray) == 0:
        eroded_gray = retina_gray
        eroded_mask_bool = retina_mask_bool

    # ==========================================================
    # A. FOCUS / BLUR (inside eroded retinal field to avoid edge jump)
    # ==========================================================
    lap = cv2.Laplacian(gray, cv2.CV_32F)
    lap_retina = lap[eroded_mask_bool]
    var_laplacian = float(np.var(lap_retina))
    laplacian_energy = float(np.mean(np.square(lap_retina)))
    
    # Sobel gradients
    sobel_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    sobel_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    sobel_mag_sq = sobel_x**2 + sobel_y**2
    sobel_mag = np.sqrt(sobel_mag_sq)
    
    tenengrad_energy = float(np.mean(sobel_mag_sq[eroded_mask_bool]))
    sobel_gradient_mean = float(np.mean(sobel_mag[eroded_mask_bool]))

    # ==========================================================
    # B. BRIGHTNESS / EXPOSURE (inside retinal field)
    # ==========================================================
    mean_intensity = float(np.mean(retina_gray))
    median_intensity = float(np.median(retina_gray))
    
    # Vectorized percentile computation (5, 10, 25, 75, 90, 95)
    pcts = np.percentile(retina_gray, [5, 10, 25, 75, 90, 95])
    intensity_p5 = float(pcts[0])
    intensity_p10 = float(pcts[1])
    intensity_p25 = float(pcts[2])
    intensity_p75 = float(pcts[3])
    intensity_p90 = float(pcts[4])
    intensity_p95 = float(pcts[5])
    
    # Dark pixels within retina (<20: underexposed/blackout; <10: severe dark)
    dark_pixel_pct = float(np.mean(retina_gray < 20) * 100.0)
    severe_dark_pct = float(np.mean(retina_gray < 10) * 100.0)
    
    # Bright/saturated pixels within retina (>240: overexposed; >250: severe saturation)
    bright_pixel_pct = float(np.mean(retina_gray > 240) * 100.0)
    severe_bright_pct = float(np.mean(retina_gray > 250) * 100.0)

    # ==========================================================
    # C. CONTRAST (inside retinal field)
    # ==========================================================
    grayscale_std = float(np.std(retina_gray))
    rms_contrast = grayscale_std  # RMS contrast = std(I)
    hist_spread_p95_p5 = float(intensity_p95 - intensity_p5)
    hist_iqr = float(intensity_p75 - intensity_p25)
    michelson_contrast = float((intensity_p95 - intensity_p5) / (intensity_p95 + intensity_p5 + 1e-5))

    # ==========================================================
    # D. NOISE (inside eroded retinal field)
    # ==========================================================
    # High-frequency residual: difference between original and Gaussian smoothed
    blurred = cv2.GaussianBlur(gray, (5, 5), 1.0)
    residual = gray.astype(np.float32) - blurred.astype(np.float32)
    res_retina = residual[eroded_mask_bool]
    
    # Standard reference metric (preserved for diagnostic & legacy continuity)
    noise_residual_std = float(np.std(res_retina))
    noise_residual_mad = float(np.mean(np.abs(res_retina - np.mean(res_retina))))
    
    # Local patch variance (7x7 box filter)
    gray_f = gray.astype(np.float32)
    local_mean = cv2.blur(gray_f, (7, 7))
    local_mean_sq = cv2.blur(gray_f ** 2, (7, 7))
    local_var = np.maximum(0.0, local_mean_sq - (local_mean ** 2))
    loc_var_retina = local_var[eroded_mask_bool]
    
    local_variance_mean = float(np.mean(loc_var_retina))
    # Subsample for median to avoid sorting 10M floats while preserving statistical accuracy
    local_variance_median = float(np.median(loc_var_retina[::8])) if len(loc_var_retina) > 1000 else float(np.median(loc_var_retina))

    # FIX 6: ANATOMICAL STRUCTURE EXCLUSION MASK (Decoupled Noise Estimation)
    # Detect and exclude blood vessels, optic disc boundary, and strong edges from noise region
    green = image_bgr[:, :, 1]
    scale_noise = max(w, h) / 1024.0
    k_size_vessel = max(5, int(11 * scale_noise)) | 1
    k_vessel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_size_vessel, k_size_vessel))
    blackhat = cv2.morphologyEx(green, cv2.MORPH_BLACKHAT, k_vessel)
    
    sobel_x_green = cv2.Sobel(green, cv2.CV_32F, 1, 0, ksize=3)
    sobel_y_green = cv2.Sobel(green, cv2.CV_32F, 0, 1, ksize=3)
    edge_mag_green = np.sqrt(sobel_x_green**2 + sobel_y_green**2)
    
    retina_edges = edge_mag_green[eroded_mask_bool]
    retina_bhat = blackhat[eroded_mask_bool]
    
    thresh_edge = np.percentile(retina_edges, 65) if len(retina_edges) > 0 else 0.0
    thresh_bhat = np.percentile(retina_bhat, 65) if len(retina_bhat) > 0 else 0.0
    vessel_mask = (edge_mag_green > thresh_edge) | (blackhat > thresh_bhat)
    
    k_dilate = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (max(3, int(5 * scale_noise)) | 1, max(3, int(5 * scale_noise)) | 1))
    dilated_vessels = cv2.dilate(vessel_mask.astype(np.uint8), k_dilate) > 0
    
    # Homogeneous parenchyma mask (retina without strong vessel transitions)
    parenchyma_mask = eroded_mask_bool & (~dilated_vessels)
    if np.count_nonzero(parenchyma_mask) < 0.15 * np.count_nonzero(eroded_mask_bool):
        parenchyma_mask = eroded_mask_bool
        
    res_parenchyma = residual[parenchyma_mask]
    parenchyma_coverage = float(np.count_nonzero(parenchyma_mask) / max(1, np.count_nonzero(eroded_mask_bool)))
    
    # Robust anatomical-decoupled noise estimator (MAD on parenchyma)
    noise_decoupled_std = float(np.median(np.abs(res_parenchyma - np.median(res_parenchyma))) / 0.6745)

    # ==========================================================
    # E. FIELD OF VIEW
    # ==========================================================
    bx, by, bw, bh = fov_info['bbox']
    fov_aspect_ratio = float(bw) / float(max(1, bh))
    retinal_radius_est = float(fov_info['radius_est'])
    retinal_circularity = float(fov_info['circularity'])
    border_clipped = bool(fov_info['border_clipped'])

    # ==========================================================
    # F. ILLUMINATION (OPTIMIZATION 3: Scaled Grid at ~256x256)
    # ==========================================================
    # Downsampled green channel illumination map for computational efficiency & scale invariance
    scale_illum = 256.0 / max(h, w)
    small_green = cv2.resize(image_bgr[:, :, 1], (0, 0), fx=scale_illum, fy=scale_illum, interpolation=cv2.INTER_AREA)
    small_gray = cv2.resize(gray, (0, 0), fx=scale_illum, fy=scale_illum, interpolation=cv2.INTER_AREA)
    sh_i, sw_i = small_green.shape
    
    small_mask = cv2.resize(mask, (sw_i, sh_i), interpolation=cv2.INTER_NEAREST)
    small_eroded = cv2.resize(mask_eroded, (sw_i, sh_i), interpolation=cv2.INTER_NEAREST)
    
    # Low-pass illumination surface
    illum_blur = cv2.GaussianBlur(small_green.astype(np.float32), (0, 0), sigmaX=15.0)
    illum_mask_bool = small_eroded > 0
    if np.count_nonzero(illum_mask_bool) == 0:
        illum_mask_bool = small_mask > 0
        
    illum_vals = illum_blur[illum_mask_bool]
    illum_mean = float(np.mean(illum_vals))
    illum_map_std = float(np.std(illum_vals))
    illum_map_cov = float(illum_map_std / (illum_mean + 1e-5))

    # Center vs Edge illumination variation on downsampled representation
    # Avoids allocating 120MB np.ogrid[:h, :w] distance matrices on 12MP images
    cx, cy = fov_info['centroid']
    cx_s = cx * (sw_i / float(w))
    cy_s = cy * (sh_i / float(h))
    radius_s = retinal_radius_est * (sw_i / float(w))
    
    y_s, x_s = np.ogrid[:sh_i, :sw_i]
    dist_s = np.sqrt((x_s - cx_s)**2 + (y_s - cy_s)**2)
    
    small_retina_bool = small_mask > 0
    # Central zone: r <= 0.45 * R
    center_zone_s = (dist_s <= 0.45 * radius_s) & small_retina_bool
    # Peripheral zone: 0.70 * R <= r <= 0.95 * R
    edge_zone_s = (dist_s >= 0.70 * radius_s) & (dist_s <= 0.95 * radius_s) & small_retina_bool
    
    if np.count_nonzero(center_zone_s) > 10:
        illum_center_mean = float(np.mean(small_gray[center_zone_s]))
    else:
        illum_center_mean = mean_intensity
        
    if np.count_nonzero(edge_zone_s) > 10:
        illum_edge_mean = float(np.mean(small_gray[edge_zone_s]))
    else:
        illum_edge_mean = mean_intensity
        
    illum_center_edge_ratio = float(illum_center_mean / (illum_edge_mean + 1e-5))
    illum_center_edge_diff = float(abs(illum_center_mean - illum_edge_mean))

    # ==========================================================
    # G. ARTIFACTS
    # ==========================================================
    # Saturated / Glare pixels (high intensity in all channels or gray >= 250)
    # inside eroded retinal field
    sat_condition = (image_bgr[:, :, 0] >= 245) & (image_bgr[:, :, 1] >= 245) & (image_bgr[:, :, 2] >= 245)
    sat_condition = sat_condition | (gray >= 250)
    sat_in_retina = sat_condition & eroded_mask_bool
    
    sat_pixel_count = int(np.count_nonzero(sat_in_retina))
    saturated_pixel_pct = float(sat_pixel_count / max(1, retinal_area) * 100.0)
    
    # Connected artifact regions (glare blobs with area >= 20 px)
    sat_uint8 = sat_in_retina.astype(np.uint8) * 255
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(sat_uint8, connectivity=8)
    
    glare_blob_count = 0
    glare_max_blob_area = 0
    glare_total_area = 0
    
    for i in range(1, num_labels):  # label 0 is background
        blob_area = stats[i, cv2.CC_STAT_AREA]
        if blob_area >= 20:
            glare_blob_count += 1
            glare_total_area += blob_area
            if blob_area > glare_max_blob_area:
                glare_max_blob_area = int(blob_area)
                
    glare_total_area_pct = float(glare_total_area / max(1, retinal_area) * 100.0)
    unwanted_background_pct = float((1.0 - fov_coverage) * 100.0)

    return {
        # Focus / Blur
        'focus_var_laplacian': var_laplacian,
        'focus_laplacian_energy': laplacian_energy,
        'focus_tenengrad': tenengrad_energy,
        'focus_sobel_mean': sobel_gradient_mean,
        
        # Brightness / Exposure
        'brightness_mean': mean_intensity,
        'brightness_median': median_intensity,
        'brightness_p5': intensity_p5,
        'brightness_p10': intensity_p10,
        'brightness_p25': intensity_p25,
        'brightness_p75': intensity_p75,
        'brightness_p90': intensity_p90,
        'brightness_p95': intensity_p95,
        'brightness_dark_pct': dark_pixel_pct,
        'brightness_severe_dark_pct': severe_dark_pct,
        'brightness_bright_pct': bright_pixel_pct,
        'brightness_severe_bright_pct': severe_bright_pct,
        
        # Contrast
        'contrast_grayscale_std': grayscale_std,
        'contrast_rms': rms_contrast,
        'contrast_spread_p95_p5': hist_spread_p95_p5,
        'contrast_iqr': hist_iqr,
        'contrast_michelson': michelson_contrast,
        
        # Noise
        'noise_residual_std': noise_residual_std,
        'noise_residual_mad': noise_residual_mad,
        'noise_decoupled_std': noise_decoupled_std,
        'noise_parenchyma_coverage': parenchyma_coverage,
        'noise_local_var_mean': local_variance_mean,
        'noise_local_var_median': local_variance_median,
        
        # FOV
        'fov_retinal_area': retinal_area,
        'fov_image_area': image_area,
        'fov_coverage': fov_coverage,
        'fov_radius_est': retinal_radius_est,
        'fov_circularity': retinal_circularity,
        'fov_aspect_ratio': fov_aspect_ratio,
        'fov_border_clipped': border_clipped,
        
        # Illumination
        'illum_center_mean': illum_center_mean,
        'illum_edge_mean': illum_edge_mean,
        'illum_center_edge_ratio': illum_center_edge_ratio,
        'illum_center_edge_diff': illum_center_edge_diff,
        'illum_map_std': illum_map_std,
        'illum_map_cov': illum_map_cov,
        
        # Artifacts
        'artifact_sat_pixel_pct': saturated_pixel_pct,
        'artifact_glare_blob_count': glare_blob_count,
        'artifact_glare_max_area': glare_max_blob_area,
        'artifact_glare_total_area_pct': glare_total_area_pct,
        'artifact_unwanted_bg_pct': unwanted_background_pct
    }
