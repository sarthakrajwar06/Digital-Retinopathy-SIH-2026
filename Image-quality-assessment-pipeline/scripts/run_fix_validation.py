"""
Run targeted validation of Module 1 logic fixes on 55 images.
Generates reports/decision_engine_fix_validation.csv and reports/decision_engine_fix_validation.md.
"""
import sys
sys.path.insert(0, '.')
import os
import cv2
import math
import numpy as np
import pandas as pd
from scipy.stats import pearsonr

from src.fov_detector import detect_retinal_fov
from src.quality_metrics import compute_image_quality_metrics
from src.quality_classifier import classify_fundus_image_quality
from src.config import (
    HARD_FAILURES,
    MIN_DIMENSION_SCORE_BORDERLINE,
    MIN_DIMENSION_SCORE_NON_CRITICAL,
    ARTIFACT_GLARE_BLOB_NON_CRITICAL_MAX,
    CRITICAL_SCORE_THRESHOLD,
    BORDERLINE_SCORE_THRESHOLD
)

# Load existing metrics dataframe for baseline reference
df_all = pd.read_csv('reports/dataset_analysis.csv')

# Define the 11 cohorts (55 images)
validation_cohorts = [
    ('Very Sharp', [
        ('aptos_9c5dd3612f0c.png', 'Very sharp microvasculature (LapVar=172.9)'),
        ('aptos_906d02fb822d.png', 'Pristine APTOS reference image (Score=0.956)'),
        ('aptos_a4012932e18d.png', 'Crisp fovea and vascular arcade'),
        ('train_IDRiD_034.jpg', 'High-res 12.2MP reference standard'),
        ('test_IDRiD_086.jpg', 'Sharp IDRiD diagnostic image')
    ]),
    ('Severe Blur', [
        ('aptos_6a244e855d0e.png', 'Severe defocus + bleach; specifically requested test case'),
        ('aptos_164cd5a3a6cd.png', 'Severe defocus blur; high-res (W=2588, Lap=3.88)'),
        ('aptos_1f543a86c4d4.png', 'Severe motion/defocus blur (W=3216, Lap=3.42)'),
        ('aptos_a3bd2e034614.png', 'Severe defocus blur (W=2588, Lap=3.06)'),
        ('aptos_0180bfa26c0b.png', 'Severe defocus blur (W=1844, Lap=3.75)')
    ]),
    ('Moderate Blur', [
        ('aptos_85fce24084da.png', 'Moderate blur candidate for sharpening (Lap=3.96)'),
        ('aptos_2131aa3a1e6f.png', 'Moderate blur (Lap=4.16, Ten=73.8)'),
        ('aptos_24b943fe725e.png', 'Mild-to-moderate blur (Lap=4.50, Ten=84.5)'),
        ('aptos_4158c340fa49.png', 'Moderate blur candidate (Lap=4.05, Ten=59.8)'),
        ('aptos_6d9effbcde78.png', 'Moderate blur candidate (Lap=4.33, Ten=63.7)')
    ]),
    ('Severe Dark', [
        ('aptos_77baa08a1345.png', 'Darkest image in dataset (Mean=27.4, Dark=22.7%)'),
        ('aptos_b6304c545f95.png', 'Severe underexposure (Mean=28.0, Dark=19.4%)'),
        ('aptos_4a7dc013e802.png', 'Severe underexposure (Mean=29.0, Dark=22.0%)'),
        ('aptos_417f408ee8e0.png', 'Severe underexposure (Mean=30.1, Dark=13.1%)'),
        ('aptos_66460ecab347.png', 'Severe underexposure floor (Mean=37.1 < 40)')
    ]),
    ('Normal Exposure', [
        ('aptos_6cffc6c6851a.png', 'Balanced clinical exposure (Mean=93.9)'),
        ('aptos_000c1434d8d7.png', 'Clean diagnostic exposure (Mean=85.2)'),
        ('train_IDRiD_092.jpg', 'Normal exposure 12.2MP fundus (Mean=91.2)'),
        ('test_IDRiD_055.jpg', 'Optimal diagnostic range (Mean=88.4)'),
        ('test_IDRiD_059.jpg', 'Optimal diagnostic range (Mean=89.2)')
    ]),
    ('Severe Bright', [
        ('aptos_89ee1fa16f90.png', 'Diffusely bleached retina (Mean=153.7 > 140)'),
        ('aptos_3c326543fff6.png', 'Severe overexposure (Mean=145.2 > 140)'),
        ('aptos_cd29c88c9e36.png', 'Diffusely bleached retina (Mean=141.5 > 140)'),
        ('aptos_aa6242f9e08c.png', 'Severe overexposure (Mean=140.8 > 140)'),
        ('aptos_4dd7b322f342.png', 'Sensor saturation clipping (BrightPct=1.73% > 1.5%)')
    ]),
    ('Low Contrast', [
        ('aptos_e65a2ff90494.png', 'Lowest contrast in dataset (RMS=7.23, dense haze)'),
        ('aptos_002c21358ce6.png', 'Low contrast cataract simulation (RMS=10.42)'),
        ('aptos_01b3aed3ed4c.png', 'Borderline low contrast haze (RMS=11.25)'),
        ('aptos_02685f13cefd.png', 'Mild haze candidate for CLAHE (RMS=12.01)'),
        ('aptos_042470a92154.png', 'Mild low contrast (RMS=12.84)')
    ]),
    ('Noisy Images', [
        ('aptos_f86d1c404acb.png', 'High high-frequency texture (Raw Noise=2.94)'),
        ('aptos_663a923d5398.png', 'High sensor grain candidate'),
        ('aptos_8d8aca52c07b.png', 'Sensor noise candidate'),
        ('aptos_82910bba4753.png', 'Moderate sensor grain'),
        ('aptos_2f143453bb71.png', 'Moderate sensor grain candidate')
    ]),
    ('Uneven Illumination', [
        ('aptos_6ccfdb031184.png', 'Highest CoV in dataset (0.697); specifically requested'),
        ('aptos_50d8a8fb7737.png', 'Highest Center/Edge Ratio (1.948); specifically requested'),
        ('train_IDRiD_352.jpg', 'Mild vignetting (Ratio=1.755, CoV=0.422); specifically requested'),
        ('aptos_5cab3ef4b31c.png', 'Buffered vignetting (Ratio=1.752, CoV=0.478); specifically requested'),
        ('aptos_b69c224edd6e.png', 'Moderate vignetting (CoV=0.384, Ratio=1.312)')
    ]),
    ('Glare Artifact', [
        ('aptos_345b1f0abbba.png', 'Severe corneal glare (5 blobs, Sat=1.00%); specifically requested'),
        ('aptos_15cc2aef772a.png', '15 glare blobs; specifically requested'),
        ('aptos_913490237ad4.png', 'Corneal glare cluster (5 blobs, Sat=0.99%)'),
        ('aptos_3b232b394e4f.png', 'Multi-blob glare (9 blobs, Sat=0.72%)'),
        ('aptos_2221cf5c7935.png', 'Corneal glare (5 blobs, Sat=0.83%)')
    ]),
    ('FOV Border & Marginal', [
        ('aptos_58eb3809f456.png', 'Marginal underexposure (Mean=39.37); specifically requested'),
        ('aptos_6cb96a6fb029.png', 'Wide black borders (Coverage=47.6%, Circ=0.997)'),
        ('aptos_f18abfa690ab.png', 'Lowest circularity in dataset (0.812)'),
        ('aptos_005b95c28852.png', 'Clean black camera border (Coverage=47.6%)'),
        ('aptos_01d9477b1171.png', 'Clean black camera border (Coverage=47.6%)')
    ])
]

# Simulate OLD logic for before/after comparison
def old_classify(raw_m):
    w = raw_m.get('width', 1024)
    h = raw_m.get('height', 1024)
    lap = float(raw_m.get('focus_var_laplacian', 0.0))
    ten = float(raw_m.get('focus_tenengrad', 0.0))
    
    # Old hard failures
    reasons = []
    if lap < 4.5 and ten < 50.0:
        reasons.append("Severe Defocus Blur (Old)")
    if raw_m.get('brightness_mean', 0.0) < 40.0:
        reasons.append("Severe Underexposure (Old)")
    elif raw_m.get('brightness_dark_pct', 0.0) > 18.0:
        reasons.append("Excessive Darkness (Old)")
    if raw_m.get('brightness_mean', 0.0) > 140.0 and raw_m.get('brightness_bright_pct', 0.0) > 1.2:
        reasons.append("Severe Overexposure (Old AND rule)")
    if raw_m.get('illum_map_cov', 0.0) > 0.52:
        reasons.append("Severe Illum CoV (Old)")
    elif raw_m.get('illum_center_edge_ratio', 1.0) > 1.75:
        reasons.append("Severe Vignetting (Old unbuffered)")
    if raw_m.get('artifact_sat_pixel_pct', 0.0) > 0.50 and raw_m.get('artifact_glare_blob_count', 0) >= 5:
        reasons.append("Severe Glare (Old)")
        
    is_hf = len(reasons) > 0
    if is_hf:
        return "CRITICAL", "RECAPTURE"
    else:
        # Simplified composite estimate
        return "NON-CRITICAL" if raw_m.get('overall_score', 0.8) >= 0.70 else "BORDERLINE", "OK TO GO" if raw_m.get('overall_score', 0.8) >= 0.70 else "ENHANCEMENT"

print("Running validation on 55 images...")
validation_rows = []
raw_noises = []
decoupled_noises = []
laps = []

for cohort_name, img_list in validation_cohorts:
    for fn, desc in img_list:
        img_path = f"dataset/{fn}"
        if not os.path.exists(img_path):
            print(f"WARNING: {fn} not found on disk!")
            continue
            
        img = cv2.imread(img_path)
        h, w, _ = img.shape
        fov_info = detect_retinal_fov(img)
        metrics = compute_image_quality_metrics(img, fov_info)
        metrics['filename'] = fn
        metrics['width'] = w
        metrics['height'] = h
        
        # New classification with all 8 fixes
        res_new = classify_fundus_image_quality(metrics)
        
        # Old classification for comparison
        old_stat, old_act = old_classify(metrics)
        
        raw_noises.append(metrics['noise_residual_std'])
        decoupled_noises.append(metrics['noise_decoupled_std'])
        laps.append(metrics['focus_var_laplacian'])
        
        # Identify detected problems
        problems = []
        if res_new['score_focus'] < 0.65:
            problems.append(f"Focus Deficit ({res_new['score_focus']:.2f})")
        if res_new['score_brightness'] < 0.65:
            problems.append(f"Exposure Deficit ({res_new['score_brightness']:.2f})")
        if res_new['score_contrast'] < 0.65:
            problems.append(f"Contrast Deficit ({res_new['score_contrast']:.2f})")
        if res_new['score_noise'] < 0.65:
            problems.append(f"Noise Deficit ({res_new['score_noise']:.2f})")
        if res_new['score_fov'] < 0.85:
            problems.append(f"FOV Deficit ({res_new['score_fov']:.2f})")
        if res_new['score_illumination'] < 0.65:
            problems.append(f"Illumination Deficit ({res_new['score_illumination']:.2f})")
        if res_new['score_artifact'] < 0.65:
            problems.append(f"Artifact Glare ({res_new['score_artifact']:.2f})")
        prob_str = "; ".join(problems) if problems else "None (Optimal quality)"
        
        validation_rows.append({
            'cohort': cohort_name,
            'filename': fn,
            'description': desc,
            'old_status': old_stat,
            'old_directive': old_act,
            'new_status': res_new['status'],
            'new_directive': res_new['directive'],
            'overall_score': res_new['overall_score'],
            'score_focus': res_new['score_focus'],
            'score_brightness': res_new['score_brightness'],
            'score_contrast': res_new['score_contrast'],
            'score_noise': res_new['score_noise'],
            'score_fov': res_new['score_fov'],
            'score_illumination': res_new['score_illumination'],
            'score_artifact': res_new['score_artifact'],
            'raw_noise_residual_std': metrics['noise_residual_std'],
            'noise_decoupled_std': metrics['noise_decoupled_std'],
            'detected_problems': prob_str,
            'hard_failure': res_new['is_hard_failure'],
            'hard_failure_reasons': res_new['hard_failure_reasons'],
            'ok_to_go': res_new['ok_to_go'],
            'recapture_required': res_new['recapture_required'],
            'enhancement_required': res_new['enhancement_required'],
            'rationale': res_new['rationale']
        })

val_df = pd.DataFrame(validation_rows)
val_df.to_csv('reports/decision_engine_fix_validation.csv', index=False)
print(f"Saved {len(val_df)} image validation records to reports/decision_engine_fix_validation.csv")

# Pearson correlation calculation
r_raw, _ = pearsonr(raw_noises, laps)
r_dec, _ = pearsonr(decoupled_noises, laps)
print(f"Raw Noise vs Laplacian Pearson correlation:       {r_raw:.4f}")
print(f"Decoupled Noise vs Laplacian Pearson correlation: {r_dec:.4f}")
print(f"Absolute correlation reduction:                   {abs(r_raw) - abs(r_dec):.4f}")
