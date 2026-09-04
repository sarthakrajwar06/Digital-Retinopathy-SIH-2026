"""
Select and classify 30 representative images across all quality profiles.
"""
import sys
sys.path.insert(0, '.')
import pandas as pd
import numpy as np
from src.quality_classifier import classify_fundus_image_quality

df = pd.read_csv('reports/dataset_analysis.csv')

# Add classifications
results = [classify_fundus_image_quality(r.to_dict()) for _, r in df.iterrows()]
res_df = pd.DataFrame(results)
full = pd.concat([df, res_df.drop(columns=['filename'])], axis=1)

# 1. 5 Very Good Images:
# Criteria: status == 'NON-CRITICAL', overall_score > 0.90, focus_score > 0.85, brightness [80, 100], contrast [18, 25], cov < 0.20, sat == 0
vg_candidates = full[
    (full['status'] == 'NON-CRITICAL') &
    (full['overall_score'] >= 0.95) &
    (full['brightness_mean'].between(80, 95)) &
    (full['contrast_rms'].between(18, 26)) &
    (full['artifact_sat_pixel_pct'] == 0) &
    (full['artifact_glare_blob_count'] == 0) &
    (full['illum_map_cov'] < 0.20)
].sort_values('overall_score', ascending=False)
vg_5 = vg_candidates.head(5)['filename'].tolist()

# 2. 5 Very Blurry Images:
# Lowest focus scores / Laplacian variance across different resolutions
vb_candidates = full.sort_values(['score_focus', 'focus_var_laplacian'], ascending=[True, True])
vb_5 = vb_candidates.head(5)['filename'].tolist()

# 3. 5 Very Dark / Underexposed:
# Lowest brightness mean / highest dark pct
vd_candidates = full.sort_values(['brightness_mean', 'brightness_dark_pct'], ascending=[True, False])
vd_5 = vd_candidates.head(5)['filename'].tolist()

# 4. 5 Very Bright / Overexposed:
# Highest brightness mean
vo_candidates = full.sort_values('brightness_mean', ascending=False)
vo_5 = vo_candidates.head(5)['filename'].tolist()

# 5. 5 Low Contrast / Noisy / Uneven Illumination:
# Mix of lowest contrast, highest noise, highest illumination CoV
lc_1 = full.sort_values('contrast_rms', ascending=True).iloc[0]['filename']
lc_2 = full.sort_values('contrast_rms', ascending=True).iloc[1]['filename']
hn_1 = full.sort_values('noise_residual_std', ascending=False).iloc[0]['filename']
ui_1 = full.sort_values('illum_map_cov', ascending=False).iloc[0]['filename'] # aptos_6ccfdb031184
ui_2 = full.sort_values('illum_center_edge_ratio', ascending=False).iloc[0]['filename']
lcn_5 = [lc_1, lc_2, hn_1, ui_1, ui_2]

# 6. 5 Artifact / FOV Problem Cases:
art_1 = 'aptos_345b1f0abbba.png' # known glare artifact
art_2 = full.sort_values('artifact_sat_pixel_pct', ascending=False).iloc[0]['filename']
art_3 = full.sort_values('artifact_glare_blob_count', ascending=False).iloc[0]['filename']
fov_1 = full.sort_values('fov_circularity', ascending=True).iloc[0]['filename']
fov_2 = full.sort_values('fov_coverage', ascending=True).iloc[0]['filename']
afov_5 = [art_1, art_2, art_3, fov_1, fov_2]

# Combine all 30
selected = [
    ('Very Good', vg_5),
    ('Very Blurry', vb_5),
    ('Very Dark / Underexposed', vd_5),
    ('Very Bright / Overexposed', vo_5),
    ('Low Contrast / Noisy / Uneven Illumination', lcn_5),
    ('Artifact / FOV Problem', afov_5)
]

rows = []
for cat, fnames in selected:
    for fn in fnames:
        r = full[full['filename'] == fn].iloc[0]
        # Detect problems
        problems = []
        if r['score_focus'] < 0.65: problems.append(f"Blur (score={r['score_focus']:.2f}, Lap={r['focus_var_laplacian']:.1f})")
        if r['score_brightness'] < 0.65: problems.append(f"Exposure (score={r['score_brightness']:.2f}, Mean={r['brightness_mean']:.1f})")
        if r['score_contrast'] < 0.65: problems.append(f"Contrast (score={r['score_contrast']:.2f}, RMS={r['contrast_rms']:.1f})")
        if r['score_noise'] < 0.65: problems.append(f"Noise (score={r['score_noise']:.2f}, Std={r['noise_residual_std']:.2f})")
        if r['score_fov'] < 0.85: problems.append(f"FOV (score={r['score_fov']:.2f}, Circ={r['fov_circularity']:.2f})")
        if r['score_illumination'] < 0.65: problems.append(f"Illumination (score={r['score_illumination']:.2f}, CoV={r['illum_map_cov']:.2f})")
        if r['score_artifact'] < 0.65: problems.append(f"Artifact (score={r['score_artifact']:.2f}, Sat={r['artifact_sat_pixel_pct']:.2f}%)")
        
        prob_str = "; ".join(problems) if problems else "None (Optimal quality)"
        
        rows.append({
            'category': cat,
            'filename': fn,
            'overall_score': r['overall_score'],
            'score_focus': r['score_focus'],
            'score_brightness': r['score_brightness'],
            'score_contrast': r['score_contrast'],
            'score_noise': r['score_noise'],
            'score_fov': r['score_fov'],
            'score_illumination': r['score_illumination'],
            'score_artifact': r['score_artifact'],
            'detected_problems': prob_str,
            'hard_failure': r['is_hard_failure'],
            'hard_failure_reasons': r['hard_failure_reasons'],
            'status': r['status'],
            'directive': r['action'],
            'ok_to_go': r['status'] == 'NON-CRITICAL',
            'recapture_required': r['status'] == 'CRITICAL',
            'rationale': r['rationale']
        })

rep_df = pd.DataFrame(rows)
print(f"Total representative images: {len(rep_df)}")
print(rep_df[['category', 'filename', 'overall_score', 'status', 'directive', 'hard_failure']].to_string())
rep_df.to_csv('reports/representative_quality_audit.csv', index=False)
print("Saved to reports/representative_quality_audit.csv")
