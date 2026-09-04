"""
Script to systematically identify Cases A, B, C, D in False Acceptance and False Rejection.
"""
import sys
sys.path.insert(0, '.')
import pandas as pd
from src.quality_classifier import classify_fundus_image_quality

df = pd.read_csv('reports/dataset_analysis.csv')
res = [classify_fundus_image_quality(r.to_dict()) for _, r in df.iterrows()]
res_df = pd.DataFrame(res)
full = pd.concat([df, res_df.drop(columns=['filename'])], axis=1)

print("=== CASE A: Potential FALSE ACCEPTANCE (Poor Quality -> NON-CRITICAL) ===")
# 1. Glare blobs >= 5 but NON-CRITICAL
fa_glare = full[(full['status'] == 'NON-CRITICAL') & (full['artifact_glare_blob_count'] >= 5)]
print(f"NON-CRITICAL with Glare Blobs >= 5: {len(fa_glare)}")
for _, r in fa_glare.head(5).iterrows():
    print(f"  {r['filename']}: Blobs={r['artifact_glare_blob_count']}, SatPct={r['artifact_sat_pixel_pct']:.3f}%, ScoreArt={r['score_artifact']:.2f}, Overall={r['overall_score']:.3f}")

# 2. Focus score < 0.60 but NON-CRITICAL
fa_blur = full[(full['status'] == 'NON-CRITICAL') & (full['score_focus'] < 0.60)]
print(f"\nNON-CRITICAL with Focus Score < 0.60: {len(fa_blur)}")
for _, r in fa_blur.head(5).iterrows():
    print(f"  {r['filename']}: ScoreFocus={r['score_focus']:.3f}, Lap={r['focus_var_laplacian']:.1f}, Ten={r['focus_tenengrad']:.1f}, Overall={r['overall_score']:.3f}")

# 3. Brightness < 60 or > 120 but NON-CRITICAL
fa_exp = full[(full['status'] == 'NON-CRITICAL') & ((full['brightness_mean'] < 60) | (full['brightness_mean'] > 120))]
print(f"\nNON-CRITICAL with Brightness < 60 or > 120: {len(fa_exp)}")
for _, r in fa_exp.head(5).iterrows():
    print(f"  {r['filename']}: Mean={r['brightness_mean']:.1f}, ScoreBright={r['score_brightness']:.2f}, Overall={r['overall_score']:.3f}")

print("\n=== CASE B: Potential FALSE REJECTION (Usable Image -> CRITICAL) ===")
# CRITICAL but Overall Score >= 0.70
fr_high_score = full[(full['status'] == 'CRITICAL') & (full['overall_score'] >= 0.70)]
print(f"CRITICAL with Overall Score >= 0.70: {len(fr_high_score)}")
for _, r in fr_high_score.head(10).iterrows():
    print(f"  {r['filename']}: Overall={r['overall_score']:.3f}, HardReasons={r['hard_failure_reasons']}, Lap={r['focus_var_laplacian']:.1f}, Mean={r['brightness_mean']:.1f}")

print("\n=== CASE C: Obviously Correctable Image -> CRITICAL ===")
# Images marked CRITICAL due to underexposure where mean is 38-40 (just below 40 threshold)
c_under = full[(full['status'] == 'CRITICAL') & (full['brightness_mean'].between(38.0, 39.99))]
print(f"CRITICAL with Brightness Mean in [38.0, 40.0): {len(c_under)}")
for _, r in c_under.head(5).iterrows():
    print(f"  {r['filename']}: Mean={r['brightness_mean']:.2f}, Lap={r['focus_var_laplacian']:.1f}, Overall={r['overall_score']:.3f}")

# Images marked CRITICAL due to vignetting ratio between 1.75 and 1.85
c_vignette = full[(full['status'] == 'CRITICAL') & (full['illum_center_edge_ratio'].between(1.75, 1.85))]
print(f"CRITICAL with Center/Edge Ratio in [1.75, 1.85): {len(c_vignette)}")
for _, r in c_vignette.iterrows():
    print(f"  {r['filename']}: Ratio={r['illum_center_edge_ratio']:.3f}, CoV={r['illum_map_cov']:.3f}, Overall={r['overall_score']:.3f}")

print("\n=== CASE D: Obviously Uncorrectable Image -> BORDERLINE ===")
# 1. Severe diffuse overexposure / bleaching (Mean > 140)
bd_bleached = full[(full['status'] == 'BORDERLINE') & (full['brightness_mean'] > 140)]
print(f"BORDERLINE with Brightness Mean > 140 (Bleached): {len(bd_bleached)}")
for _, r in bd_bleached.iterrows():
    print(f"  {r['filename']}: Mean={r['brightness_mean']:.1f}, ScoreBright={r['score_brightness']:.4f}, Overall={r['overall_score']:.3f}")

# 2. Severe blur (LapVar < 4.5) but BORDERLINE because Tenengrad >= 50
bd_blur = full[(full['status'] == 'BORDERLINE') & (full['focus_var_laplacian'] < 4.5)]
print(f"\nBORDERLINE with LapVar < 4.5 (Severely Blurry): {len(bd_blur)}")
for _, r in bd_blur.head(8).iterrows():
    print(f"  {r['filename']}: Lap={r['focus_var_laplacian']:.2f}, Ten={r['focus_tenengrad']:.1f}, ScoreFocus={r['score_focus']:.3f}, Overall={r['overall_score']:.3f}")
