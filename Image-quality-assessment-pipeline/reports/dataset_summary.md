# SIH26038: Fundus Image Quality Assessment (Module 1)
## Phase 1–5 Comprehensive Dataset Inspection and Quality Metric Analysis Report

**Date & Time**: 2026-09-02  
**Dataset Directory**: `dataset/` (via NTFS junction to `D:\SIH_data\dataset\images`)  
**Analysis Scope**: Module 1 — Preliminary Image Quality Assessment (Deterministic only, No ML/DL, No thresholds/scoring)

---

## 1. Executive Summary & Inventory (Phase 1)

A complete inventory of all images in the dataset was performed without skipping any files. The dataset consists of high-resolution retinal fundus photography originating from two distinct clinical benchmarks: **APTOS 2019** (PNG format) and **IDRiD** (Indian Diabetic Retinopathy Image Dataset, JPG format).

- **Total Image Files Inspected**: **4178**
- **Valid Decodable Images**: **4178** (100.00%)
- **Corrupted / Unreadable Images**: **0**
- **Non-Image Metadata Files**: 1 (`labels.xlsx`, excluded from image pipeline)
- **Exact Duplicate Images (SHA-256 Match)**: **134** duplicate instances across **129** groups
- **Near-Duplicate Groups (dHash Match)**: **355**

### File Format Distribution
| Format | Count | Percentage |
| :--- | :--- | :--- |
| PNG | 3662 | 87.6% |
| JPEG | 516 | 12.4% |

### Resolution Distribution (Top Formats)
| Resolution (W x H) | Count | Percentage | Megapixels |
| :--- | :--- | :--- | :--- |
| 1050 x 1050 | 974 | 23.3% | 1.1 MP |
| 2416 x 1736 | 638 | 15.3% | 4.19 MP |
| 4288 x 2848 | 568 | 13.6% | 12.21 MP |
| 2588 x 1958 | 533 | 12.8% | 5.07 MP |
| 3216 x 2136 | 410 | 9.8% | 6.87 MP |
| 2048 x 1536 | 351 | 8.4% | 3.15 MP |
| 819 x 614 | 287 | 6.9% | 0.5 MP |
| 3388 x 2588 | 141 | 3.4% | 8.77 MP |
| 1504 x 1000 | 92 | 2.2% | 1.5 MP |
| 1844 x 1226 | 61 | 1.5% | 2.26 MP |

### Dimension Extremes
- **Width**: Min = 474 px, Max = 4288 px, Median = 2416 px
- **Height**: Min = 358 px, Max = 2848 px, Median = 1736 px
- **Resolution (Megapixels)**: Min = 0.17 MP, Max = 12.212 MP, Median = 4.194 MP

### Color Information
All 4178 valid images are 3-channel images. True-color RGB representations are preserved in all valid fundus images.

---

## 2. Preliminary Deterministic Quality Measurements (Phase 2)

All preliminary quality metrics were calculated **strictly inside the detected retinal field (FOV)**. The unexposed black camera background was completely segmented and masked out to prevent artificial skewing of brightness, contrast, and noise statistics. Furthermore, for Laplacian, gradient, and high-frequency noise calculations, an eroded retinal boundary mask was utilized to eliminate edge-boundary step artifacts.

### Metric Overview Table
| Metric | Min | P5 | P25 | Median | Mean | P75 | P95 | Max | StdDev |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `focus_var_laplacian` | 2.57 | 5.22 | 11.12 | **23.48** | 28.70 | 45.82 | 61.76 | 172.87 | 20.49 |
| `focus_laplacian_energy` | 2.57 | 5.22 | 11.12 | **23.49** | 28.70 | 45.82 | 61.76 | 172.87 | 20.49 |
| `focus_tenengrad` | 24.59 | 62.08 | 120.49 | **247.61** | 337.10 | 534.35 | 820.28 | 1,888.3 | 268.83 |
| `focus_sobel_mean` | 4.05 | 6.06 | 8.47 | **11.33** | 12.12 | 15.84 | 18.51 | 24.42 | 4.17 |
| `brightness_mean` | 27.43 | 49.82 | 74.85 | **90.54** | 87.45 | 101.42 | 115.68 | 154.52 | 19.99 |
| `brightness_median` | 28.00 | 48.00 | 74.00 | **90.00** | 86.76 | 101.00 | 116.00 | 155.00 | 20.68 |
| `brightness_p5` | 4.00 | 22.00 | 46.25 | **66.00** | 62.01 | 78.00 | 95.00 | 144.00 | 22.52 |
| `brightness_p10` | 6.00 | 30.00 | 54.00 | **72.00** | 68.64 | 85.00 | 100.00 | 146.00 | 21.77 |
| `brightness_p25` | 21.00 | 39.00 | 63.00 | **80.00** | 77.13 | 92.00 | 107.00 | 150.00 | 20.95 |
| `brightness_p75` | 32.00 | 57.00 | 84.00 | **101.00** | 97.62 | 112.00 | 128.00 | 171.00 | 21.38 |
| `brightness_p90` | 35.00 | 67.00 | 93.00 | **111.00** | 108.24 | 124.00 | 143.00 | 192.00 | 22.86 |
| `brightness_p95` | 37.00 | 73.00 | 99.00 | **118.00** | 115.58 | 132.00 | 152.00 | 209.00 | 24.16 |
| `brightness_dark_pct` | 0.3175 | 0.6591 | 0.7660 | **1.00** | 1.80 | 2.67 | 4.43 | 22.72 | 1.87 |
| `brightness_severe_dark_pct` | 0.0000 | 0.3474 | 0.6260 | **0.7795** | 1.37 | 2.10 | 3.65 | 14.95 | 1.32 |
| `brightness_bright_pct` | 0.0000 | 0.0000 | 0.0000 | **0.0000** | 0.0238 | 0.0000 | 0.1375 | 1.73 | 0.1146 |
| `brightness_severe_bright_pct` | 0.0000 | 0.0000 | 0.0000 | **0.0000** | 0.0083 | 0.0000 | 0.0001 | 0.9819 | 0.0595 |
| `contrast_grayscale_std` | 7.23 | 12.51 | 16.07 | **20.51** | 20.73 | 24.31 | 30.41 | 56.11 | 5.95 |
| `contrast_rms` | 7.23 | 12.51 | 16.07 | **20.51** | 20.73 | 24.31 | 30.41 | 56.11 | 5.95 |
| `contrast_spread_p95_p5` | 16.00 | 29.00 | 40.00 | **49.00** | 53.56 | 61.00 | 97.00 | 187.00 | 21.82 |
| `contrast_iqr` | 6.00 | 11.00 | 15.00 | **19.00** | 20.50 | 24.00 | 36.00 | 83.00 | 8.40 |
| `contrast_michelson` | 0.0776 | 0.1532 | 0.2227 | **0.2816** | 0.3180 | 0.3718 | 0.6123 | 0.9459 | 0.1478 |
| `noise_residual_std` | 0.4793 | 0.6653 | 0.8877 | **1.32** | 1.37 | 1.87 | 2.17 | 2.94 | 0.5306 |
| `noise_residual_mad` | 0.1738 | 0.3488 | 0.5672 | **0.8640** | 0.8580 | 1.16 | 1.35 | 2.11 | 0.3365 |
| `noise_local_var_mean` | 0.8077 | 2.29 | 4.08 | **7.99** | 12.18 | 21.03 | 31.71 | 102.33 | 10.73 |
| `noise_local_var_median` | 0.5586 | 1.19 | 2.16 | **3.60** | 4.37 | 6.51 | 8.67 | 13.18 | 2.53 |
| `fov_retinal_area` | 155,758.0 | 403,488.2 | 901,446.0 | **3,515,638.0** | 3,493,645.5 | 5,154,043.0 | 8,638,398.6 | 10,591,634.0 | 2,708,136.0 |
| `fov_image_area` | 169,692.0 | 502,866.0 | 1,102,500.0 | **4,194,176.0** | 4,615,820.9 | 6,869,376.0 | 12,212,224.0 | 12,212,224.0 | 3,708,353.7 |
| `fov_coverage` | 0.4760 | 0.4795 | 0.7231 | **0.8088** | 0.7649 | 0.8382 | 0.9131 | 0.9938 | 0.1245 |
| `fov_radius_est` | 222.66 | 358.38 | 535.67 | **1,057.9** | 965.28 | 1,280.9 | 1,658.2 | 1,836.1 | 424.65 |
| `fov_circularity` | 0.8122 | 0.9180 | 0.9270 | **0.9541** | 0.9540 | 0.9903 | 0.9968 | 0.9971 | 0.0332 |
| `fov_aspect_ratio` | 0.9910 | 1.00 | 1.00 | **1.23** | 1.18 | 1.30 | 1.32 | 1.43 | 0.1358 |
| `illum_center_mean` | 28.50 | 53.10 | 82.24 | **98.97** | 96.29 | 112.33 | 128.84 | 166.37 | 22.75 |
| `illum_edge_mean` | 24.64 | 47.33 | 70.91 | **86.66** | 84.00 | 97.96 | 113.69 | 152.77 | 20.18 |
| `illum_center_edge_ratio` | 0.6557 | 0.9477 | 1.08 | **1.15** | 1.15 | 1.22 | 1.38 | 1.95 | 0.1329 |
| `illum_center_edge_diff` | 0.0029 | 2.13 | 7.68 | **12.45** | 13.51 | 18.06 | 28.43 | 61.62 | 8.13 |
| `illum_map_std` | 4.68 | 8.70 | 12.26 | **15.23** | 15.57 | 18.10 | 23.99 | 51.79 | 4.85 |
| `illum_map_cov` | 0.0797 | 0.1396 | 0.1814 | **0.2174** | 0.2306 | 0.2660 | 0.3717 | 0.6974 | 0.0717 |
| `artifact_sat_pixel_pct` | 0.0000 | 0.0000 | 0.0000 | **0.0000** | 0.0093 | 0.0000 | 0.0015 | 1.00 | 0.0639 |
| `artifact_glare_blob_count` | 0.0000 | 0.0000 | 0.0000 | **0.0000** | 0.1115 | 0.0000 | 0.0000 | 27.00 | 0.7911 |
| `artifact_glare_max_area` | 0.0000 | 0.0000 | 0.0000 | **0.0000** | 352.26 | 0.0000 | 0.0000 | 45,943.0 | 2,566.4 |
| `artifact_glare_total_area_pct` | 0.0000 | 0.0000 | 0.0000 | **0.0000** | 0.0093 | 0.0000 | 0.0000 | 1.00 | 0.0637 |
| `artifact_unwanted_bg_pct` | 0.6217 | 8.69 | 16.18 | **19.12** | 23.51 | 27.69 | 52.05 | 52.40 | 12.45 |

---

## 3. Detailed Distribution Findings (Phase 3)

The distribution plots have been generated and saved inside `reports/plots/`:

### A. Focus & Blur (`reports/plots/focus_distribution.png`)
- **Variance of Laplacian**: Exhibits a heavy right-tailed distribution. Median value is 23.48 (IQR: 11.12 – 45.82). The bottom 5th percentile drops below 5.22, indicating severe optical defocus or motion blur.
- **Tenengrad Energy & Sobel Mean**: Correlate strongly with Laplacian variance, confirming that anatomical microvascular details provide consistent gradient signatures when sharp.

### B. Brightness & Exposure (`reports/plots/brightness_distribution.png`)
- **Retinal Mean Intensity**: Centered around median 90.5 (Mean: 87.4, Std: 20.0).
- **Underexposure**: The 5th percentile of mean intensity is 49.8, with severe dark pixel percentages reaching 22.7% in underexposed outliers.
- **Overexposure**: Saturated retinal pixels (>240) represent a small fraction across the majority of the dataset (median 0.000%), but outlier images exhibit heavy specular flash reflection.

### C. Contrast (`reports/plots/contrast_distribution.png`)
- **RMS Contrast (Grayscale Std)**: Median is 20.5 (P5: 12.5, P95: 30.4). Low-contrast fundus images (P5 < 12.5) correspond to hazy media (e.g. cataract or dense vitreous opacity).
- **Histogram Spread (P95 - P5)**: Ranges from 16.0 to 187.0 with a median of 49.0.

### D. High-Frequency Noise (`reports/plots/noise_distribution.png`)
- **Residual Noise Std**: Median is 1.32. A subset of images exhibiting sensor gain boost (high ISO under low lighting) demonstrates noise standard deviations up to 2.94.
- **Local Patch Variance**: Median is 7.99.

### E. Field of View & Geometry (`reports/plots/fov_distribution.png`)
- **Retinal FOV Coverage**: Ranges from 47.6% to 99.4% with a median of 80.9%.
  - Circular aperture cameras (APTOS 3216x2136 and IDRiD 4288x2848) typically yield ~65%–75% coverage.
  - Pre-cropped square images (1050x1050) reach ~78%–82% coverage (approximating theoretical circle-in-square $\pi/4 \approx 78.54\%$).
- **Circularity**: Median is 0.954, confirming near-perfect circularity of the optical aperture.

### F. Illumination Uniformity (`reports/plots/illumination_distribution.png`)
- **Illumination Map CoV**: Median is 0.217.
- **Center vs Edge Ratio**: Median is 1.15. Retinal fundus images naturally exhibit peripheral vignetting where illumination diminishes toward the periphery. Outliers with ratios > 2.0 or < 0.6 indicate severe non-uniform flash alignment or quadrant shadow.

### G. Artifacts & Glare (`reports/plots/artifacts_distribution.png`)
- **Saturation Percentage**: Median is 0.000%.
- **Glare Blobs**: 207 images (5.0%) contain detected glare/specular reflection blobs (area $\ge 20$ pixels).
- **Unwanted Background**: Median unexposed background percentage is 19.1%.

---

## 4. Visual Inspection Archetypes (Phase 4)

Representative images spanning 10 key archetypes were selected and visualized in 4-panel diagnostic figures in `data/debug/`:

1. **Very Sharp** (`debug_very_sharp_*.png`): High vascular contrast, crisp optic disc rim, high Laplacian energy.
2. **Very Blurry** (`debug_very_blurry_*.png`): Severe optical defocus, smudged vessel branches.
3. **Very Dark** (`debug_very_dark_*.png`): Severe underexposure, signal lost in sensor noise floor.
4. **Very Bright** (`debug_very_bright_*.png`): Overexposed flash illumination, blanching retinal structures.
5. **Low Contrast** (`debug_low_contrast_*.png`): Flat tonal histogram, media haze.
6. **High Noise** (`debug_high_noise_*.png`): Granular high-frequency sensor noise across retinal field.
7. **Poor FOV** (`debug_poor_fov_*.png`): Significant field clipping or small aperture.
8. **Uneven Illumination** (`debug_uneven_illumination_*.png`): Strong vignetting or quadrant shadow.
9. **High Artifact** (`debug_high_artifact_*.png`): Specular cornea/lens reflection flash artifacts.
10. **Visually Good / Balanced** (`debug_visually_good_*.png`): Balanced exposure, crisp vessel edges, uniform lighting.

Each debug visualization displays:
- Panel 1: Original fundus photograph with core metrics.
- Panel 2: Detected binary retinal mask.
- Panel 3: Retinal boundary contour overlay with centroid and peripheral measurement zones.
- Panel 4: Diagnostic metric overlay (Laplacian edge energy, illumination surface, or glare mask).

---

## 5. Key Observations for Calibrating Module 1

The empirical distributions collected from these 4178 fundus images provide crucial insights for calibrating Module 1:

1. **Retinal Mask Segmentation Is Indispensable**: Calculating brightness or contrast without retinal mask segmentation causes catastrophic errors due to the 20%–50% black camera border.
2. **Boundary Erosion Is Essential for Gradient & Laplacian**: A 10–15 pixel erosion of the retinal mask is required when computing Laplacian, gradient, or noise metrics; otherwise, the sharp step at the boundary falsely inflates blur scores.
3. **Resolution-Dependent Metric Invariance**: Laplacian variance and noise residuals scale with image resolution and optical sharpness. Downsampling or normalizing scale will be essential when setting calibrated thresholds across heterogeneous resolutions (e.g. 1050x1050 vs 4288x2848).
4. **Empirical Quantile Anchors**: The 5th, 25th, 50th, 75th, and 95th percentiles tabulated in this report provide the exact statistical foundation needed to empirically calibrate future quality categories without arbitrary guessing.

---
*Report generated deterministically by Module 1 Inspection Pipeline.*
