"""
Detailed threshold and logic audit script for Module 1.
Computes percentiles, counts, and behavior for all thresholds in config.py and quality_classifier.py.
"""
import sys
sys.path.insert(0, '.')
import math
import numpy as np
import pandas as pd
import scipy.stats as stats
from src.quality_classifier import classify_fundus_image_quality
from src.config import HARD_FAILURES, PROVISIONAL_BOUNDARIES, QUALITY_WEIGHTS, CRITICAL_SCORE_THRESHOLD, BORDERLINE_SCORE_THRESHOLD, MIN_DIMENSION_SCORE_NON_CRITICAL

# Load metrics
df = pd.read_csv('reports/dataset_analysis.csv')
n_total = len(df)

# Run classification
results = [classify_fundus_image_quality(row.to_dict()) for _, row in df.iterrows()]
res_df = pd.DataFrame(results)
full_df = pd.concat([df, res_df.drop(columns=['filename'])], axis=1)

print(f"Total dataset images: {n_total}")
print("Status counts:\n", res_df['status'].value_counts())
print("\nHard failures triggered:\n", res_df[res_df['is_hard_failure']]['hard_failure_reasons'].value_counts())

# Detailed threshold evaluation
threshold_list = [
    # Hard failures
    ('blur_laplacian_var_min', 'focus_var_laplacian', '<', 4.5, 'CRITICAL', 'YES', 'NO (Severe defocus requires recapture)'),
    ('blur_tenengrad_min', 'focus_tenengrad', '<', 50.0, 'CRITICAL', 'YES', 'NO (Severe defocus requires recapture)'),
    ('blur_combined_hard_fail', ('focus_var_laplacian', 'focus_tenengrad'), 'both <', (4.5, 50.0), 'CRITICAL', 'YES', 'NO'),
    ('brightness_mean_min', 'brightness_mean', '<', 40.0, 'CRITICAL', 'YES', 'NO (Signal below sensor floor, irrecoverable)'),
    ('brightness_dark_pct_max', 'brightness_dark_pct', '>', 18.0, 'CRITICAL', 'YES', 'NO (Extreme tissue clipping)'),
    ('brightness_mean_max', 'brightness_mean', '>', 140.0, 'CRITICAL', 'YES', 'NO (Flash bleaching, lost texture)'),
    ('brightness_bright_pct_max', 'brightness_bright_pct', '>', 1.2, 'CRITICAL', 'YES', 'NO (Permanent sensor saturation)'),
    ('brightness_overexp_combined', ('brightness_mean', 'brightness_bright_pct'), 'both >', (140.0, 1.2), 'CRITICAL', 'YES', 'NO'),
    ('illum_map_cov_max', 'illum_map_cov', '>', 0.52, 'CRITICAL', 'YES', 'NO (Severe quadrant shadow / heavy gradient)'),
    ('illum_center_edge_ratio_max', 'illum_center_edge_ratio', '>', 1.75, 'CRITICAL', 'YES', 'NO (Extreme peripheral blackout)'),
    ('artifact_sat_pixel_pct_max', 'artifact_sat_pixel_pct', '>', 0.50, 'CRITICAL', 'YES', 'NO'),
    ('artifact_glare_blob_count_min', 'artifact_glare_blob_count', '>=', 5, 'CRITICAL', 'YES', 'NO'),
    ('artifact_combined_hard_fail', ('artifact_sat_pixel_pct', 'artifact_glare_blob_count'), 'sat>0.5 & blobs>=5', (0.50, 5), 'CRITICAL', 'YES', 'NO'),
    ('fov_retinal_area_min', 'fov_retinal_area', '<', 150000, 'CRITICAL', 'YES', 'NO (Extreme low-res or thumbnail)'),
    ('fov_circularity_min', 'fov_circularity', '<', 0.78, 'CRITICAL', 'YES', 'NO (Severe boundary cut-off / distortion)'),
    ('fov_completeness_min', 'fov_completeness_ratio', '<', 0.70, 'CRITICAL', 'YES', 'NO (Aperture severely incomplete)'),

    # Provisional boundaries (Normalization / Soft gates)
    # Focus
    ('focus_lap_norm_critical', 'scale_normalized_laplacian', '<', 10.0, 'CRITICAL', 'NO', 'PARTIAL (Deconvolution/unsharp mask)'),
    ('focus_lap_norm_borderline', 'scale_normalized_laplacian', '<', 25.0, 'BORDERLINE', 'NO', 'YES (Unsharp masking / Wiener filter)'),
    ('focus_ten_critical', 'raw_tenengrad', '<', 50.0, 'CRITICAL', 'NO', 'PARTIAL'),
    ('focus_ten_borderline', 'raw_tenengrad', '<', 150.0, 'BORDERLINE', 'NO', 'YES (Edge enhancement)'),

    # Brightness
    ('brightness_mean_severe_under', 'brightness_mean', '<', 45.0, 'CRITICAL', 'NO', 'PARTIAL (Gamma curve lift)'),
    ('brightness_mean_mild_under', 'brightness_mean', '<', 70.0, 'BORDERLINE', 'NO', 'YES (Gamma correction, histogram stretch)'),
    ('brightness_mean_optimal_min', 'brightness_mean', '<', 70.0, 'BORDERLINE', 'NO', 'YES'),
    ('brightness_mean_optimal_max', 'brightness_mean', '>', 110.0, 'BORDERLINE', 'NO', 'YES (Gamma compression)'),
    ('brightness_mean_severe_over', 'brightness_mean', '>', 130.0, 'CRITICAL', 'NO', 'NO (Blanched retina)'),
    ('brightness_dark_penalty_start', 'brightness_dark_pct', '>', 4.0, 'BORDERLINE', 'NO', 'YES (Shadow lift)'),
    ('brightness_dark_severe_pct', 'brightness_dark_pct', '>', 15.0, 'CRITICAL', 'NO', 'NO'),
    ('brightness_bright_penalty_start', 'brightness_bright_pct', '>', 0.40, 'BORDERLINE', 'NO', 'YES (Highlight recovery)'),
    ('brightness_bright_severe_pct', 'brightness_bright_pct', '>', 1.20, 'CRITICAL', 'NO', 'NO'),

    # Contrast
    ('contrast_rms_severe_low', 'contrast_rms', '<', 11.0, 'CRITICAL', 'NO', 'PARTIAL (Dense cataract / haze)'),
    ('contrast_rms_mild_low', 'contrast_rms', '<', 16.0, 'BORDERLINE', 'NO', 'YES (CLAHE, local contrast enhancement)'),
    ('contrast_rms_optimal_max', 'contrast_rms', '>', 32.0, 'BORDERLINE', 'NO', 'YES (Dynamic range compression)'),
    ('contrast_rms_excessive', 'contrast_rms', '>', 42.0, 'BORDERLINE/CRITICAL', 'NO', 'PARTIAL (Glare suppression)'),

    # Noise
    ('noise_std_optimal_max', 'noise_residual_std', '>', 1.10, 'BORDERLINE', 'NO', 'YES (Bilateral filtering / NLM)'),
    ('noise_std_acceptable_max', 'noise_residual_std', '>', 1.80, 'BORDERLINE', 'NO', 'YES (Wavelet denoising)'),
    ('noise_std_severe_min', 'noise_residual_std', '>', 2.30, 'CRITICAL', 'NO', 'PARTIAL (Severe grain)'),

    # FOV
    ('fov_circ_good_min', 'fov_circularity', '<', 0.92, 'BORDERLINE', 'NO', 'NO (Camera aperture is physical)'),
    ('fov_circ_borderline_min', 'fov_circularity', '<', 0.85, 'BORDERLINE', 'NO', 'NO'),
    ('fov_comp_good_min', 'fov_completeness_ratio', '<', 0.85, 'BORDERLINE', 'NO', 'NO'),
    ('fov_comp_borderline_min', 'fov_completeness_ratio', '<', 0.75, 'BORDERLINE', 'NO', 'NO'),

    # Illumination
    ('illum_cov_good_max', 'illum_map_cov', '>', 0.24, 'BORDERLINE', 'NO', 'YES (Flat-field correction / Homomorphic)'),
    ('illum_cov_borderline_max', 'illum_map_cov', '>', 0.38, 'BORDERLINE', 'NO', 'YES (Vignetting correction)'),
    ('illum_ratio_dev_good', 'raw_illum_center_edge_ratio', 'dev >', 0.15, 'BORDERLINE', 'NO', 'YES (Radial gain compensation)'),
    ('illum_ratio_dev_borderline', 'raw_illum_center_edge_ratio', 'dev >', 0.35, 'BORDERLINE', 'NO', 'YES (Radial gain compensation)'),

    # Artifacts
    ('artifact_sat_good_max', 'artifact_sat_pixel_pct', '>', 0.01, 'BORDERLINE', 'NO', 'YES (Inpainting / highlight recovery)'),
    ('artifact_sat_borderline_max', 'artifact_sat_pixel_pct', '>', 0.08, 'BORDERLINE', 'NO', 'PARTIAL (Inpainting small reflections)'),
    ('artifact_sat_severe_min', 'artifact_sat_pixel_pct', '>', 0.30, 'CRITICAL', 'NO', 'NO (Obscured macula/arcade)'),
    ('artifact_blobs_good_max', 'artifact_glare_blob_count', '>', 0, 'BORDERLINE', 'NO', 'YES'),
    ('artifact_blobs_borderline_max', 'artifact_glare_blob_count', '>', 2, 'BORDERLINE', 'NO', 'PARTIAL'),
    ('artifact_blobs_severe_min', 'artifact_glare_blob_count', '>', 5, 'CRITICAL', 'NO', 'NO')
]

print("\n--- DETAILED THRESHOLD AUDIT TABLE ---")
audit_rows = []
for item in threshold_list:
    name, col, op, val, prod_status, is_hf, enhanceable = item
    if isinstance(col, tuple):
        if op == 'both <':
            c1, c2 = col
            v1, v2 = val
            affected = (full_df[c1] < v1) & (full_df[c2] < v2)
            pctile = "N/A (Joint)"
        elif op == 'both >':
            c1, c2 = col
            v1, v2 = val
            affected = (full_df[c1] > v1) & (full_df[c2] > v2)
            pctile = "N/A (Joint)"
        elif op == 'sat>0.5 & blobs>=5':
            c1, c2 = col
            v1, v2 = val
            affected = (full_df[c1] > v1) & (full_df[c2] >= v2)
            pctile = "N/A (Joint)"
        val_str = str(val)
        metric_name = f"{col[0]} & {col[1]}"
    else:
        metric_name = col
        val_str = f"{op} {val}"
        series = full_df[col]
        if op == '<':
            affected = series < val
            pctile = f"P{stats.percentileofscore(series, val):.2f}"
        elif op == '<=':
            affected = series <= val
            pctile = f"P{stats.percentileofscore(series, val):.2f}"
        elif op == '>':
            affected = series > val
            pctile = f"P{100.0 - stats.percentileofscore(series, val):.2f} above (P{stats.percentileofscore(series, val):.2f})"
        elif op == '>=':
            affected = series >= val
            pctile = f"P{100.0 - stats.percentileofscore(series, val):.2f} above (P{stats.percentileofscore(series, val):.2f})"
        elif op == 'dev >':
            dev = (series - 1.15).abs()
            affected = dev > val
            pctile = f"P{stats.percentileofscore(dev, val):.2f} (dev)"

    count = int(affected.sum())
    pct = (count / n_total) * 100.0
    audit_rows.append({
        'Threshold Name': name,
        'Metric': metric_name,
        'Threshold Value': val_str,
        'Dataset Percentile': pctile,
        'Affected Images': count,
        'Percentage': f"{pct:.2f}%",
        'Produces Status': prod_status,
        'Hard Failure': is_hf,
        'Enhanceable': enhanceable
    })

audit_df = pd.DataFrame(audit_rows)
print(audit_df.to_string())
audit_df.to_csv('reports/threshold_audit_raw.csv', index=False)
