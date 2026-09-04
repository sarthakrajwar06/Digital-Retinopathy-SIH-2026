"""
Detailed inspection of each of the 7 dimensions.
"""
import sys
sys.path.insert(0, '.')
import pandas as pd
import numpy as np
from src.quality_classifier import classify_fundus_image_quality

df = pd.read_csv('reports/dataset_analysis.csv')

print("=== 1. BRIGHTNESS AUDIT: Mean > 140 vs Bright Pct > 1.2% ===")
m140 = df[df['brightness_mean'] > 140]
print(f"Total Mean > 140: {len(m140)}")
for _, r in m140.iterrows():
    c = classify_fundus_image_quality(r.to_dict())
    print(f"  {r['filename']}: Mean={r['brightness_mean']:.1f}, BrightPct={r['brightness_bright_pct']:.3f}%, Status={c['status']}, OverallScore={c['overall_score']:.3f}, ScoreBright={c['score_brightness']:.4f}")

b12 = df[df['brightness_bright_pct'] > 1.2]
print(f"\nTotal Bright Pct > 1.2%: {len(b12)}")
for _, r in b12.iterrows():
    c = classify_fundus_image_quality(r.to_dict())
    print(f"  {r['filename']}: Mean={r['brightness_mean']:.1f}, BrightPct={r['brightness_bright_pct']:.3f}%, Status={c['status']}, OverallScore={c['overall_score']:.3f}, ScoreBright={c['score_brightness']:.4f}, Blobs={r['artifact_glare_blob_count']}")

print("\n=== 2. CONTRAST AUDIT ===")
print("Contrast RMS percentiles:")
print(df['contrast_rms'].describe(percentiles=[0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99]))
print("\nExtreme High Contrast (RMS > 42):")
high_c = df[df['contrast_rms'] > 42]
print(f"Total RMS > 42: {len(high_c)}")
for _, r in high_c.head(5).iterrows():
    c = classify_fundus_image_quality(r.to_dict())
    print(f"  {r['filename']}: RMS={r['contrast_rms']:.1f}, SatPct={r['artifact_sat_pixel_pct']:.3f}%, Blobs={r['artifact_glare_blob_count']}, Status={c['status']}, OverallScore={c['overall_score']:.3f}, ScoreContrast={c['score_contrast']:.4f}")

print("\n=== 3. NOISE AUDIT ===")
print("Noise residual std percentiles:")
print(df['noise_residual_std'].describe(percentiles=[0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99]))
print("Correlation between noise_residual_std and local_var_mean:", df['noise_residual_std'].corr(df['noise_local_var_mean']))
print("Correlation between noise_residual_std and focus_var_laplacian:", df['noise_residual_std'].corr(df['focus_var_laplacian']))
print("Correlation between noise_local_var_mean and focus_var_laplacian:", df['noise_local_var_mean'].corr(df['focus_var_laplacian']))

print("\n=== 4. ILLUMINATION AUDIT ===")
print("CoV percentiles:")
print(df['illum_map_cov'].describe(percentiles=[0.5, 0.75, 0.9, 0.95, 0.99, 0.995]))
print("Center/Edge Ratio percentiles:")
print(df['illum_center_edge_ratio'].describe(percentiles=[0.01, 0.05, 0.5, 0.9, 0.95, 0.99, 0.995]))

# Inspect aptos_6ccfdb031184.png
print("\nMetrics for aptos_6ccfdb031184.png:")
row_6cc = df[df['filename'] == 'aptos_6ccfdb031184.png'].iloc[0]
c_6cc = classify_fundus_image_quality(row_6cc.to_dict())
print(f"  CoV={row_6cc['illum_map_cov']:.4f}, Center/Edge Ratio={row_6cc['illum_center_edge_ratio']:.3f}")
print(f"  ScoreIllum={c_6cc['score_illumination']}, FlagIllum={c_6cc['flag_illumination']}")
print(f"  Status={c_6cc['status']}, HardFail={c_6cc['is_hard_failure']}, Reasons={c_6cc['hard_failure_reasons']}")

print("\n=== 5. ARTIFACT AUDIT ===")
print("Metrics for aptos_345b1f0abbba.png:")
row_345 = df[df['filename'] == 'aptos_345b1f0abbba.png'].iloc[0]
c_345 = classify_fundus_image_quality(row_345.to_dict())
print(f"  SatPct={row_345['artifact_sat_pixel_pct']:.4f}%, GlareBlobs={row_345['artifact_glare_blob_count']}")
print(f"  UnwantedBG={row_345['artifact_unwanted_bg_pct']:.2f}%")
print(f"  ScoreArt={c_345['score_artifact']}, FlagArt={c_345['flag_artifact']}")
print(f"  Status={c_345['status']}, HardFail={c_345['is_hard_failure']}, Reasons={c_345['hard_failure_reasons']}")

print("\nArtifact metrics on clean images with large black borders (coverage < 0.65):")
bb = df[df['fov_coverage'] < 0.65]
print(f"Total images with coverage < 0.65: {len(bb)}")
print(f"Mean sat pct in black border images: {bb['artifact_sat_pixel_pct'].mean():.4f}%")
print(f"Mean glare blobs in black border images: {bb['artifact_glare_blob_count'].mean():.2f}")
bb_sample = bb.head(3)
for _, r in bb_sample.iterrows():
    c = classify_fundus_image_quality(r.to_dict())
    print(f"  {r['filename']}: Cov={r['fov_coverage']:.2f}, SatPct={r['artifact_sat_pixel_pct']:.4f}%, Blobs={r['artifact_glare_blob_count']}, ScoreArt={c['score_artifact']}, Status={c['status']}")
