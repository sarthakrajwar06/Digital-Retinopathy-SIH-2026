# Module 1: Comprehensive Threshold, Logic, and Architectural Quality Audit

> [!IMPORTANT]
> **Important Clinical Limitation Disclaimer**  
> **Thresholds and quality classifications established herein are provisional and require validation against clinician-assessed fundus image gradability.**  
> The labels provided in `labels.xlsx` represent Diabetic Retinopathy (DR) disease severity grades (0–4) rather than photographic quality or gradability labels. All metrics, cutoffs, and logic tiers are derived from mathematical modeling and empirical quantile calibrations across the 4,178 fundus photographs (APTOS 2019 + IDRiD) established in `reports/dataset_analysis.csv`.

---

## Executive Summary

Before finalizing quality classifications across all 4,178 images, a rigorous, data-driven audit was performed on the current decision engine (`src/config.py`, `src/quality_classifier.py`, `src/fov_detector.py`, and `src/quality_metrics.py`).

### Dataset-Wide Decision Engine Outcome (4,178 Images)

| Quality Status | Action / Directive | Image Count | Population % | Hard Failures | Mean Composite Score |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **NON-CRITICAL** | **OK TO GO** | **3,885** | **92.99%** | 0 | 0.884 ± 0.046 |
| **BORDERLINE** | **ENHANCEMENT** | **210** | **5.03%** | 0 | 0.728 ± 0.053 |
| **CRITICAL** | **RECAPTURE** | **83** | **1.99%** | 83 | 0.697 ± 0.076 |
| **Total** | — | **4,178** | **100.00%** | **83** | **0.872 ± 0.061** |

---

## 1. Audit of Current Thresholds

Every current threshold configured in `src/config.py` and implemented in `src/quality_classifier.py` was evaluated against the full empirical distribution of all 4,178 images.

### Comprehensive Threshold Audit Table

| Threshold Name | Target Metric | Threshold Value | Dataset Percentile | Affected Images | Population % | Produces Status | Hard Failure? | Realistically Enhanceable? |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| `blur_laplacian_var_min` | `focus_var_laplacian` | `< 4.5` | P2.49 | 104 | 2.49% | CRITICAL | YES | **NO** (Severe optical defocus / motion loss) |
| `blur_tenengrad_min` | `focus_tenengrad` | `< 50.0` | P2.11 | 88 | 2.11% | CRITICAL | YES | **NO** (Irrecoverable gradient loss) |
| `blur_combined_hard_fail` | `focus_var_laplacian` & `tenengrad` | `Lap<4.5 & Ten<50` | N/A (Joint) | 10 | 0.24% | CRITICAL | YES | **NO** (Definite severe defocus) |
| `brightness_mean_min` | `brightness_mean` | `< 40.0` | P1.15 | 48 | 1.15% | CRITICAL | YES | **NO** (Tissue submerged below sensor noise floor) |
| `brightness_dark_pct_max` | `brightness_dark_pct` | `> 18.0%` | P99.88 (Top 0.12%) | 5 | 0.12% | CRITICAL | YES | **NO** (Extreme permanent blackout) |
| `brightness_mean_max` | `brightness_mean` | `> 140.0` | P99.88 (Top 0.12%) | 5 | 0.12% | CRITICAL | YES | **NO** (Diffusely blanched retina) |
| `brightness_bright_pct_max` | `brightness_bright_pct` | `> 1.2%` | P99.83 (Top 0.17%) | 7 | 0.17% | CRITICAL | YES | **NO** (Sensor saturation clipping) |
| `brightness_overexp_combined`| `brightness_mean` & `bright_pct` | `Mean>140 & Bright>1.2%` | N/A (Joint) | 0 | 0.00% | CRITICAL | YES | **NO** (Flawed joint condition; see Audit 4) |
| `illum_map_cov_max` | `illum_map_cov` | `> 0.52` | P99.76 (Top 0.24%) | 10 | 0.24% | CRITICAL | YES | **NO** (Severe quadrant shadow / heavy gradient) |
| `illum_center_edge_ratio_max`| `illum_center_edge_ratio` | `> 1.75` | P99.90 (Top 0.10%) | 4 | 0.10% | CRITICAL | YES | **PARTIAL** (Radial gain compensation) |
| `artifact_sat_pixel_pct_max` | `artifact_sat_pixel_pct` | `> 0.50%` | P99.50 (Top 0.50%) | 21 | 0.50% | CRITICAL | YES | **NO** (Extensive retinal obscuration) |
| `artifact_glare_blob_count_min`| `artifact_glare_blob_count` | `>= 5` | P99.63 (Top 0.37%) | 20 | 0.48% | CRITICAL | YES | **NO** (Severe multi-blob specular glare) |
| `artifact_combined_hard_fail` | `sat_pct` & `glare_blobs` | `Sat>0.5% & Blobs>=5` | N/A (Joint) | 10 | 0.24% | CRITICAL | YES | **NO** (Corneal flash reflection cluster) |
| `fov_retinal_area_min` | `fov_retinal_area` | `< 150,000 px` | P0.00 | 0 | 0.00% | CRITICAL | YES | **NO** (Min in dataset is 155,758 px) |
| `fov_circularity_min` | `fov_circularity` | `< 0.78` | P0.00 | 0 | 0.00% | CRITICAL | YES | **NO** (Min in dataset is 0.8122) |
| `fov_completeness_min` | `fov_completeness_ratio` | `< 0.70` | P0.00 | 0 | 0.00% | CRITICAL | YES | **NO** (Min in dataset is 0.8081) |
| `focus_lap_norm_critical` | `scale_normalized_laplacian` | `< 10.0` | P3.06 | 128 | 3.06% | CRITICAL | NO | **PARTIAL** (Wiener deconvolution / unsharp) |
| `focus_lap_norm_borderline` | `scale_normalized_laplacian` | `< 25.0` | P8.43 | 352 | 8.43% | BORDERLINE | NO | **YES** (Unsharp masking / High-boost filter) |
| `focus_ten_critical` | `raw_tenengrad` | `< 50.0` | P2.11 | 88 | 2.11% | CRITICAL | NO | **PARTIAL** (Laplacian sharpening) |
| `focus_ten_borderline` | `raw_tenengrad` | `< 150.0` | P36.40 | 1,521 | 36.40% | BORDERLINE | NO | **YES** (Gradient boost / CLAHE) |
| `brightness_mean_severe_under`| `brightness_mean` | `< 45.0` | P2.25 | 94 | 2.25% | CRITICAL | NO | **PARTIAL** (Adaptive gamma lift) |
| `brightness_mean_mild_under` | `brightness_mean` | `< 70.0` | P20.49 | 856 | 20.49% | BORDERLINE | NO | **YES** (Gamma correction / Histogram stretch) |
| `brightness_mean_optimal_max`| `brightness_mean` | `> 110.0` | P89.59 (Top 10.4%) | 435 | 10.41% | BORDERLINE | NO | **YES** (Highlight compression) |
| `brightness_mean_severe_over` | `brightness_mean` | `> 130.0` | P99.09 (Top 0.91%) | 38 | 0.91% | CRITICAL | NO | **NO** (Blanched posterior pole) |
| `brightness_dark_penalty_start`| `brightness_dark_pct` | `> 4.0%` | P92.94 (Top 7.06%) | 295 | 7.06% | BORDERLINE | NO | **YES** (Shadow lifting) |
| `brightness_bright_penalty_start`| `brightness_bright_pct`| `> 0.40%` | P98.28 (Top 1.72%) | 72 | 1.72% | BORDERLINE | NO | **YES** (Specular attenuation) |
| `contrast_rms_severe_low` | `contrast_rms` | `< 11.0` | P1.34 | 56 | 1.34% | CRITICAL | NO | **PARTIAL** (Dense cataract / haze) |
| `contrast_rms_mild_low` | `contrast_rms` | `< 16.0` | P24.65 | 1,030 | 24.65% | BORDERLINE | NO | **YES** (CLAHE local contrast enhancement) |
| `contrast_rms_optimal_max` | `contrast_rms` | `> 32.0` | P96.27 (Top 3.73%) | 156 | 3.73% | BORDERLINE | NO | **YES** (Tonal curve rebalancing) |
| `contrast_rms_excessive` | `contrast_rms` | `> 42.0` | P99.43 (Top 0.57%) | 24 | 0.57% | BORDERLINE | NO | **PARTIAL** (Glare suppression) |
| `noise_std_optimal_max` | `noise_residual_std` | `> 1.10` | P44.81 (Top 55.2%) | 2,306 | 55.19% | BORDERLINE | NO | **YES** (Bilateral / NLM denoising) |
| `noise_std_acceptable_max` | `noise_residual_std` | `> 1.80` | P72.64 (Top 27.4%) | 1,143 | 27.36% | BORDERLINE | NO | **YES** (Wavelet denoising) |
| `noise_std_severe_min` | `noise_residual_std` | `> 2.30` | P98.76 (Top 1.24%) | 52 | 1.24% | CRITICAL | NO | **PARTIAL** (Severe sensor grain) |
| `fov_circ_good_min` | `fov_circularity` | `< 0.92` | P14.77 | 617 | 14.77% | BORDERLINE | NO | **NO** (Camera aperture is physical hardware) |
| `fov_circ_borderline_min` | `fov_circularity` | `< 0.85` | P1.10 | 46 | 1.10% | BORDERLINE | NO | **NO** (Aperture crop is irreversible) |
| `fov_comp_good_min` | `fov_completeness_ratio` | `< 0.85` | P11.92 | 498 | 11.92% | BORDERLINE | NO | **NO** (Retinal tissue outside crop cannot be recovered) |
| `illum_cov_good_max` | `illum_map_cov` | `> 0.24` | P63.48 (Top 36.5%) | 1,526 | 36.52% | BORDERLINE | NO | **YES** (Homomorphic / flat-field correction) |
| `illum_cov_borderline_max` | `illum_map_cov` | `> 0.38` | P95.57 (Top 4.43%) | 185 | 4.43% | BORDERLINE | NO | **YES** (Flat-field shading correction) |
| `illum_ratio_dev_good` | `raw_illum_center_edge_ratio` | `|ratio-1.15| > 0.15` | P80.23 (dev) | 826 | 19.77% | BORDERLINE | NO | **YES** (Radial gain compensation) |
| `illum_ratio_dev_borderline` | `raw_illum_center_edge_ratio` | `|ratio-1.15| > 0.35` | P97.27 (dev) | 114 | 2.73% | BORDERLINE | NO | **YES** (Radial gain compensation) |
| `artifact_sat_good_max` | `artifact_sat_pixel_pct` | `> 0.01%` | P95.40 (Top 4.60%) | 192 | 4.60% | BORDERLINE | NO | **YES** (Local inpainting / specular recovery) |
| `artifact_sat_borderline_max`| `artifact_sat_pixel_pct` | `> 0.08%` | P97.08 (Top 2.92%) | 122 | 2.92% | BORDERLINE | NO | **PARTIAL** (Inpainting small reflections) |
| `artifact_sat_severe_min` | `artifact_sat_pixel_pct` | `> 0.30%` | P99.02 (Top 0.98%) | 41 | 0.98% | CRITICAL | NO | **NO** (Obscures diagnostic arcade/macula) |
| `artifact_blobs_good_max` | `artifact_glare_blob_count` | `> 0` | P47.53 (Top 52.5%) | 207 | 4.95% | BORDERLINE | NO | **YES** (Small artifact inpainting) |
| `artifact_blobs_borderline_max`| `artifact_glare_blob_count`| `> 2` | P98.30 (Top 1.70%) | 53 | 1.27% | BORDERLINE | NO | **PARTIAL** (Multiple glare patches) |
| `artifact_blobs_severe_min` | `artifact_glare_blob_count` | `> 5` | P99.63 (Top 0.37%) | 12 | 0.29% | CRITICAL | NO | **NO** (Severe glare cluster) |

---

## 2. Focus / Blur Audit

### Multi-Resolution Resolution Scaling Analysis
The dataset spans resolutions from 0.17 MP (474×358) to 12.21 MP (4288×2848).

When computing the discrete 2D Laplacian operator `cv2.Laplacian` with a fixed $3 \times 3$ kernel:
1. The discrete second difference $D_2[n] = I[n+1] - 2I[n] + I[n-1]$ represents $(\Delta x)^2 \frac{\partial^2 I}{\partial x^2}$.
2. As resolution increases, the physical step size $\Delta x \propto 1 / \max(W, H)$ shrinks.
3. Therefore, an anatomical vessel boundary transition that spans 2 pixels at $1050 \times 1050$ spans 8 pixels at $4288 \times 2848$. The local discrete gradient across adjacent pixels is substantially smaller.
4. **Empirical Confirmation:**
   - For images $< 1.5$ MP (e.g., $1050 \times 1050$), mean raw Laplacian variance is **48.37**.
   - For images $3.5$–$6.0$ MP (e.g., $2416 \times 1736$), mean raw Laplacian variance drops to **12.49**.
   - For images $> 6.0$ MP (e.g., $4288 \times 2848$), mean raw Laplacian variance drops to **18.89**.

### Discrepancy Between Normalization and Hard Failures
- In `normalize_focus`, resolution compensation is applied:
  $$\text{lap\_norm} = \text{lap\_var} \times \left(\frac{\max(W, H)}{1024}\right)^2$$
- However, in `evaluate_hard_failures`, the raw unscaled value is used:
  `lap < 4.5 AND ten < 50.0`.
- **Consequence:** Out of 104 images with raw $\text{LapVar} < 4.5$:
  - 93 images are $3216 \times 2136$ resolution.
  - 8 images are $2588 \times 1958$ resolution.
  - Exactly **0 images** are $1050 \times 1050$ resolution.
- Furthermore, because of the `AND` condition (`LapVar < 4.5 AND Tenengrad < 50.0`), high-resolution blurry images such as `aptos_6a244e855d0e.png` ($\text{LapVar} = 2.57$, severely blurred) exhibit a Tenengrad of $114.55$ (due to cumulative high-resolution gradient summation) and **completely bypass the hard failure**, receiving a status of `BORDERLINE` rather than `CRITICAL`.

### Monotonicity Check
Across images of identical resolution, the focus score behaves monotonically:
- `debug_very_sharp_aptos_9c5dd3612f0c.png`: Focus Score = **1.000** (`GOOD`)
- `opt_sample50_sharp_aptos_66460ecab347.png`: Focus Score = **0.864** (`GOOD`)
- `opt_sample50_blurry_aptos_85fce24084da.png`: Focus Score = **0.579** (`BORDERLINE_BLUR`)
- `debug_very_blurry_aptos_6a244e855d0e.png`: Focus Score = **0.402** (`SEVERE_BLUR`)

---

## 3. Field of View (FOV) Audit

A critical objective was ensuring that legitimate fundus cameras with square crops or rectangular black borders are not falsely penalized.

### Geometry and Resolution Breakdown

| Resolution Group | Dominant Aspect Ratio | Image Count | Mean FOV Coverage | Mean Circularity | Mean Inscribed Completeness | FOV Score | FOV Status Flag |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **$1050 \times 1050$** | 1:1 (Square) | 974 | 81.5% (80.1%–85.9%) | 0.990 | 1.038 | **1.000** | 100% `COMPLETE_FOV` |
| **$2416 \times 1736$** | 4:3 (Rectangular) | 638 | 83.9% (83.7%–85.8%) | 0.927 | 1.486 | **1.000** | 100% `COMPLETE_FOV` |
| **$4288 \times 2848$** | 3:2 (Camera Border) | 568 | 71.0% (69.3%–86.7%) | 0.949 | 1.361 | **1.000** | 100% `COMPLETE_FOV` |
| **$2048 \times 1536$** | 4:3 (Wide Border) | 351 | 47.6% (47.6%–56.8%) | 0.996 | 1.000 | **0.942** | 100% `COMPLETE_FOV` |

### Key Findings
1. **Protection of Square and Cropped Formats:** All 974 square $1050 \times 1050$ images scored 1.000 for FOV. None were penalized for having $\sim 81\%$ coverage because their completeness relative to the maximum inscribed circular aperture is $\ge 1.00$.
2. **Protection of Wide Black Borders:** In images like `aptos_6cb96a6fb029.png` (coverage = $47.6\%$), the retina is a pristine, complete circle with circularity $0.9968$. The classifier correctly assigns an FOV score of **0.9413** (`COMPLETE_FOV`).
3. **Hard Failure Invariance:** Across the entire 4,178-image dataset:
   - Minimum retinal area is **155,758 px** (threshold: 150,000 px).
   - Minimum circularity is **0.8122** (threshold: 0.780).
   - Minimum completeness ratio is **0.8081** (threshold: 0.700).
   - Consequently, **zero images** in the dataset triggered FOV hard failure, confirming that no severely mutilated crescent slivers exist in the population.

---

## 4. Brightness / Exposure Audit

### Empirical Distribution
- **Mean Retinal Intensity:** Min = 27.43, P1 = 39.48, P5 = 49.82, Median = 90.54, P95 = 115.68, P99 = 129.23, Max = 154.52.
- **Dark Pixel % ($I < 20$):** Median = 1.00%, P95 = 4.43%, P99 = 9.82%, Max = 22.72%.
- **Bright Pixel % ($I > 240$):** Median = 0.00%, P95 = 0.14%, P99 = 0.58%, Max = 1.73%.

### Evaluation of Severe Exposure Rules
1. **Severe Underexposure Rule:** `Mean < 40.0 OR Dark Pct > 18.0%`
   - `Mean < 40.0`: 48 images (1.15%)
   - `Dark Pct > 18.0%`: 5 images (0.12%)
   - Combined `OR`: **49 images (1.17%)**
   - **Audit Finding:** Perfectly calibrated. Captures severely blackened images (such as `aptos_77baa08a1345.png`, Mean = 27.43) where the retinal tissue signal has collapsed into sensor read noise.
2. **Severe Overexposure Rule:** `Mean > 140.0 AND Bright Pct > 1.2%`
   - `Mean > 140.0`: 5 images (0.12%)
   - `Bright Pct > 1.2%`: 7 images (0.17%)
   - Combined `AND`: **0 images (0.00%)**
   - Combined `OR`: **12 images (0.29%)**
   - **Critical Audit Finding (Flawed Logic):** Requiring an `AND` between Mean > 140 and Bright Pct > 1.2% renders the hard failure unreachable:
     - Images with `Mean > 140` (e.g., `aptos_6a244e855d0e.png` at 154.5) have diffuse flash bleaching where pixels cluster at 150–165 without crossing 240, yielding `Bright Pct = 0.00%`.
     - Images with `Bright Pct > 1.2%` have localized specular flash burns, but their overall retinal mean is 80–110.
     - Consequently, **zero overexposed images** trigger a hard failure, allowing severely blanched images to be categorized as `BORDERLINE`.

---

## 5. Contrast Audit

### Empirical Distribution
- **RMS Contrast:** Min = 7.23, P1 = 10.72, P5 = 12.51, Median = 20.51, P75 = 24.31, P95 = 30.41, P99 = 38.69, Max = 56.11.
- **Low Contrast Handling:** 56 images (1.34%) have RMS contrast $< 11.0$, corresponding to simulated dense cataracts or severe media opacities. The lowest contrast image in the dataset is `aptos_e65a2ff90494.png` ($\text{RMS} = 7.23$), which receives a Contrast Score of **0.1107** (`SEVERE_LOW_CONTRAST`).
- **High Contrast != Good Quality:**
  - Optimal contrast is defined in $[16.0, 32.0]$ (Score = 1.000).
  - Images with $\text{RMS} > 42.0$ (24 images, 0.57%) are penalized.
  - For example, `aptos_4dd7b322f342.png` ($\text{RMS} = 56.1$) is driven by specular reflection and receives a penalized contrast score of **0.5648** (`EXCESSIVE_CONTRAST`). High contrast is correctly prevented from inflating the overall score.

---

## 6. Noise Audit

### Score Direction and Metric Verification
The noise normalization correctly inverts the metric: lower noise yields a higher quality score.
- Noise $\le 1.10$: Score $\in [0.90, 1.00]$ (`LOW_NOISE`)
- Noise $\in (1.10, 1.80]$: Score $\in [0.65, 0.90]$ (`ACCEPTABLE_NOISE`)
- Noise $> 2.30$: Score $\in [0.00, 0.30]$ (`SEVERE_NOISE`)

### Critical Finding: Anatomical High-Frequency Coupling
- **Pearson correlation between `noise_residual_std` and `focus_var_laplacian` is $0.970$.**
- **Pearson correlation between `noise_local_var_mean` and `focus_var_laplacian` is $0.803$.**
- **Root Cause:** The noise metric calculates $I - \text{GaussianBlur}(I, 5\times 5, 1.0)$, which is a high-pass spatial filter. This operation captures all fine anatomical vessel boundaries, nerve fiber striations, and capillary transitions.
- **Consequence:** 
  - Blurry images devoid of edge transitions (such as `aptos_6a244e855d0e.png`) produce near-zero high-pass residuals ($\text{std} = 0.479$) and are awarded a near-perfect noise score of **0.9564**.
  - Extremely sharp images with rich microvascular networks produce high residuals ($\text{std} > 2.2$) and are penalized for noise.
  - The current noise measurement reflects anatomical edge energy rather than true sensor gain noise floor.

---

## 7. Illumination Audit

### Vignetting and Lateral Gradient Findings
- **Illumination CoV:** Median = 0.217, P90 = 0.322, P95 = 0.372, P99 = 0.455, Max = 0.697.
- **Center/Edge Ratio:** Median = 1.147 (natural fundus camera vignetting), P95 = 1.382, P99 = 1.549, Max = 1.948.
- **Clinical Vignetting Protection:** The normal center/edge ratio of $\sim 1.15$ receives a ratio subscore of **1.000**. Mild-to-moderate vignetting up to $1.35$ remains within acceptable limits.
- **Extreme Case Evaluation (`aptos_6ccfdb031184.png`):**
  - $\text{Map CoV} = \mathbf{0.6974}$ (maximum in entire dataset).
  - $\text{Center/Edge Ratio} = 0.985$ (ratio is balanced because illumination gradient is lateral, across left-to-right quadrants rather than radial).
  - Hard failure triggered: `Severe Non-Uniform Illumination (Map CoV=0.697 > 0.52)`.
  - Assigned: `CRITICAL` / `RECAPTURE`.

---

## 8. Artifact / Background Audit

### Camera Background vs. Capture Artifact
- Across 532 images with low FOV coverage ($< 65\%$, representing wide unexposed camera borders):
  - Mean saturated pixel percentage inside the retina is **0.0061%**.
  - Mean glare blob count inside the retina is **0.06**.
  - The unexposed camera border is completely excluded by evaluating artifacts strictly within `mask_eroded > 0`. Clean images with massive black borders (e.g., `aptos_005b95c28852.png`) receive an Artifact Score of **1.000**.
- **Extreme Case Evaluation (`aptos_345b1f0abbba.png`):**
  - Retinal Saturated Pixel % = **1.0015%** (threshold: 0.50%).
  - Glare Blobs = **5** (threshold: 5).
  - Hard failure triggered: `Severe Corneal Glare Artifacts (5 blobs, 1.00% saturation)`.
  - Assigned: `CRITICAL` / `RECAPTURE`.

---

## 9. Composite Score Audit

### Dimension Weights and Aggregation
$$\sum w_i = 0.25 (\text{Focus}) + 0.15 (\text{Brightness}) + 0.15 (\text{Contrast}) + 0.10 (\text{Noise}) + 0.15 (\text{FOV}) + 0.10 (\text{Illum}) + 0.10 (\text{Artifact}) = \mathbf{1.000}$$

- **Orthogonality:** Submetrics within a dimension are merged into a single normalized score in $[0.0, 1.0]$ prior to composite weighting:
  - Focus: $0.60 \times s_{\text{lap}} + 0.40 \times s_{\text{ten}}$
  - FOV: $0.40 \times s_{\text{circ}} + 0.40 \times s_{\text{comp}} + 0.20 \times s_{\text{area}}$
  - Illumination: $0.65 \times s_{\text{cov}} + 0.35 \times s_{\text{ratio}}$
  - No submetric is independently double-weighted.

---

## 10. Status Logic Audit

### Sequential Evaluation Hierarchy
1. **STEP 1:** Hard failure evaluation $\rightarrow$ If `True`, immediately assign `status = CRITICAL`, `directive = RECAPTURE`.
2. **STEP 2:** Calculate seven normalized dimension scores in $[0.0, 1.0]$.
3. **STEP 3:** Calculate weighted composite score.
4. **STEP 4:** Apply status logic:
   - If composite score $\ge 0.70$ and all critical dimensions $\ge 0.35 \rightarrow$ `NON-CRITICAL` / `OK TO GO`.
   - Else if composite score $\ge 0.50 \rightarrow$ `BORDERLINE` / `ENHANCEMENT`.
   - Else $\rightarrow$ `CRITICAL` / `RECAPTURE`.

### State Contradiction Verification
Across all 4,178 evaluations:
- `status = NON-CRITICAL` and `recapture_required = True`: **0 instances**
- `status = CRITICAL` and `ok_to_go = True`: **0 instances**
- `status = BORDERLINE` and `ok_to_go = True`: **0 instances**
- Total logic contradictions: **0**

---

## 11. Representative Visual Validation (30 Images)

The complete evaluation of all 30 representative images is exported to [`reports/representative_quality_audit.csv`](file:///C:/Users/SAMSUNG/OneDrive/Desktop/SIH/reports/representative_quality_audit.csv). A summary of the cohorts is detailed below:

| Cohort | Representative Filename | Overall Score | Key Metric Values | Hard Failure? | Status | Directive | Primary Classification Reason |
| :--- | :--- | :---: | :--- | :---: | :---: | :---: | :--- |
| **Very Good** | `aptos_906d02fb822d.png` | 0.956 | Mean=88.7, Lap=42.1, RMS=21.4 | NO | NON-CRITICAL | OK TO GO | Pristine across all 7 dimensions |
| **Very Good** | `aptos_a4012932e18d.png` | 0.956 | Mean=88.7, Lap=42.1, RMS=21.4 | NO | NON-CRITICAL | OK TO GO | Optimal exposure, sharpness, and clean media |
| **Very Good** | `train_IDRiD_034.jpg` | 0.954 | Mean=87.5, Lap=30.6, RMS=23.7 | NO | NON-CRITICAL | OK TO GO | High-resolution 12.2MP reference standard |
| **Very Good** | `test_IDRiD_086.jpg` | 0.951 | Mean=84.4, Lap=25.2, RMS=24.1 | NO | NON-CRITICAL | OK TO GO | Excellent diagnostic contrast and vessel sharpness |
| **Very Good** | `aptos_6cffc6c6851a.png` | 0.942 | Mean=93.9, Lap=57.2, RMS=18.5 | NO | NON-CRITICAL | OK TO GO | Uniform illumination, zero glare, complete FOV |
| **Very Blurry** | `aptos_164cd5a3a6cd.png` | 0.722 | Lap=3.88, Ten=37.8, Mean=56.0 | **YES** | **CRITICAL** | **RECAPTURE** | Hard Failure: Severe Defocus Blur |
| **Very Blurry** | `aptos_1f543a86c4d4.png` | 0.826 | Lap=3.42, Ten=43.1, Mean=87.2 | **YES** | **CRITICAL** | **RECAPTURE** | Hard Failure: Severe Defocus Blur |
| **Very Blurry** | `aptos_a3bd2e034614.png` | 0.697 | Lap=3.06, Ten=31.5, Mean=61.8 | **YES** | **CRITICAL** | **RECAPTURE** | Hard Failure: Severe Defocus Blur |
| **Very Blurry** | `aptos_6a244e855d0e.png` | 0.698 | Lap=2.57, Ten=114.6, Mean=154.5 | NO | **BORDERLINE** | **ENHANCEMENT** | Bypassed HF due to Tenengrad>50 (ScoreFocus=0.40) |
| **Very Blurry** | `aptos_85fce24084da.png` | 0.817 | Lap=3.96, Ten=75.1, Mean=78.2 | NO | **BORDERLINE** | **ENHANCEMENT** | Moderate defocus candidate for sharpening |
| **Very Dark** | `aptos_77baa08a1345.png` | 0.592 | Mean=27.4, DarkPct=22.7%, Lap=8.3 | **YES** | **CRITICAL** | **RECAPTURE** | Hard Failure: Severe Underexposure & Excessive Dark |
| **Very Dark** | `aptos_b6304c545f95.png` | 0.637 | Mean=28.0, DarkPct=19.4%, Lap=8.9 | **YES** | **CRITICAL** | **RECAPTURE** | Hard Failure: Severe Underexposure & Excessive Dark |
| **Very Dark** | `aptos_4a7dc013e802.png` | 0.614 | Mean=29.0, DarkPct=22.0%, Lap=7.9 | **YES** | **CRITICAL** | **RECAPTURE** | Hard Failure: Severe Underexposure & Excessive Dark |
| **Very Dark** | `aptos_417f408ee8e0.png` | 0.664 | Mean=30.1, DarkPct=13.1%, Lap=9.5 | **YES** | **CRITICAL** | **RECAPTURE** | Hard Failure: Severe Underexposure (Mean < 40) |
| **Very Dark** | `aptos_66460ecab347.png` | 0.721 | Mean=37.1, DarkPct=2.8%, Lap=66.5 | **YES** | **CRITICAL** | **RECAPTURE** | Hard Failure: Severe Underexposure (Mean < 40) |
| **Very Bright** | `aptos_89ee1fa16f90.png` | 0.733 | Mean=153.7, BrightPct=0.0%, Lap=22.9 | NO | **BORDERLINE** | **ENHANCEMENT** | Bypassed HF due to BrightPct=0 (ScoreBright=0.023) |
| **Very Bright** | `aptos_3c326543fff6.png` | 0.809 | Mean=145.2, BrightPct=0.04%, Lap=50.2| NO | **BORDERLINE** | **ENHANCEMENT** | Bypassed HF due to BrightPct=0.04 (ScoreBright=0.176) |
| **Very Bright** | `aptos_cd29c88c9e36.png` | 0.725 | Mean=141.5, BrightPct=0.0%, Lap=18.4 | NO | **BORDERLINE** | **ENHANCEMENT** | Severe overexposure candidate for gamma compress |
| **Very Bright** | `aptos_aa6242f9e08c.png` | 0.797 | Mean=140.8, BrightPct=0.30%, Lap=61.8| NO | **BORDERLINE** | **ENHANCEMENT** | Mild saturation overexposure |
| **Very Bright** | `train_IDRiD_078.jpg` | 0.817 | Mean=130.6, BrightPct=0.01%, Lap=25.2| NO | **BORDERLINE** | **ENHANCEMENT** | Borderline bright, correctable via histogram curve |
| **Low Contrast**| `aptos_e65a2ff90494.png` | 0.734 | RMS=7.23, Mean=58.2, Lap=11.3 | NO | **BORDERLINE** | **ENHANCEMENT** | Lowest contrast in dataset (ScoreContrast=0.111) |
| **High Noise** | `aptos_f86d1c404acb.png` | 0.751 | NoiseStd=2.94, LocalVar=24.7, Lap=83.9 | NO | **NON-CRITICAL** | **OK TO GO** | Noise std inflated by dense vessels (ScoreNoise=0.01) |
| **Uneven Illum**| `aptos_6ccfdb031184.png` | 0.714 | CoV=0.697, Ratio=0.985, Mean=85.8 | **YES** | **CRITICAL** | **RECAPTURE** | Hard Failure: Severe Non-Uniform Illumination (CoV>0.52) |
| **Uneven Illum**| `aptos_50d8a8fb7737.png` | 0.767 | Ratio=1.948, CoV=0.457, Mean=78.4 | **YES** | **CRITICAL** | **RECAPTURE** | Hard Failure: Extreme Vignetting (Ratio > 1.75) |
| **Uneven Illum**| `aptos_b69c224edd6e.png` | 0.824 | CoV=0.384, Ratio=1.312, Mean=90.1 | NO | **BORDERLINE** | **ENHANCEMENT** | Moderate vignetting correctable by flat-fielding |
| **Glare Artifact**| `aptos_345b1f0abbba.png` | 0.748 | SatPct=1.00%, Blobs=5, Mean=75.7 | **YES** | **CRITICAL** | **RECAPTURE** | Hard Failure: Severe Corneal Glare Artifacts |
| **Glare Artifact**| `aptos_15cc2aef772a.png` | 0.808 | Blobs=15, SatPct=0.026%, Bright=1.23%| NO | **NON-CRITICAL** | **OK TO GO** | False Acceptance: 15 glare blobs passed to Non-Critical |
| **Glare Artifact**| `aptos_913490237ad4.png` | 0.774 | SatPct=0.99%, Blobs=5, Mean=104.2 | **YES** | **CRITICAL** | **RECAPTURE** | Hard Failure: Severe Corneal Glare Artifacts |
| **Low Circularity**|`aptos_f18abfa690ab.png` | 0.761 | Circ=0.812, Comp=0.808, Area=207k | NO | **NON-CRITICAL** | **OK TO GO** | Lowest circularity in dataset (ScoreFOV=0.742) |
| **Wide Border** | `aptos_6cb96a6fb029.png` | 0.727 | Coverage=0.476, Circ=0.997, Mean=37.5| **YES** | **CRITICAL** | **RECAPTURE** | Triggered Underexposure HF (Mean=37.5), NOT FOV |

---

## 12. False Acceptance / False Rejection Review

### Case A: Potential False Acceptances (Poor Quality $\rightarrow$ NON-CRITICAL)
1. **Multi-Blob Glare Bypassing Filters (10 images):**  
   Images such as `aptos_15cc2aef772a.png` contain **15 distinct glare blobs** across the retinal field, yet are classified as `NON-CRITICAL` (`OK TO GO`) with an overall score of $0.808$. Because `artifact_sat_pixel_pct` is only $0.026\%$ (small punctate reflections), it bypassed the hard failure (`Sat > 0.5% & Blobs >= 5`).
2. **Defocus Blur Permitted in Non-Critical (503 images):**  
   503 images with `score_focus < 0.60` (e.g., `aptos_001639a390f0.png`, $\text{ScoreFocus} = 0.448$, $\text{LapVar} = 4.4$) achieved `NON-CRITICAL` status because their other 6 dimensions exceeded $0.90$, elevating composite score past $0.70$ and clearing the soft gate `MIN_DIMENSION_SCORE_NON_CRITICAL = 0.35`.

### Case B: Potential False Rejections (Usable Image $\rightarrow$ CRITICAL)
1. **High Overall Score Hard Failures (47 images):**  
   47 images with weighted composite scores $\ge 0.70$ are classified as `CRITICAL` / `RECAPTURE`.
   - `train_IDRiD_352.jpg`: **Overall Score = 0.877**, razor-sharp vascular tree, optimal exposure, but triggered hard failure solely because `illum_center_edge_ratio = 1.755` (just $0.005$ above the $1.750$ threshold).
   - `aptos_5cab3ef4b31c.png`: **Overall Score = 0.752**, Center/Edge ratio = $1.752$.

### Case C: Obviously Correctable Image $\rightarrow$ CRITICAL
1. **Marginal Underexposure (13 images):**  
   13 images possess Retinal Mean Intensity in $[38.0, 40.0)$. An image with Mean = $39.37$ (e.g., `aptos_58eb3809f456.png`, $\text{LapVar} = 64.8$, $\text{Overall} = 0.785$) is immediately marked `CRITICAL` / `RECAPTURE`, despite possessing intact tissue signal that can be restored into optimal diagnostic range via adaptive gamma enhancement.
2. **Marginal Vignetting (2 images):**  
   Center-to-edge ratios in $[1.75, 1.80]$ represent smooth radial falloff that flat-field correction can easily invert.

### Case D: Obviously Uncorrectable Image $\rightarrow$ BORDERLINE
1. **Diffusely Bleached Retina (5 images):**  
   Images with Mean $> 140.0$ (`aptos_6a244e855d0e.png` at 154.5, `aptos_89ee1fa16f90.png` at 153.7) receive near-zero brightness scores ($0.0087$ and $0.0231$), but because their other 5 dimensions score $\sim 1.0$, composite score reaches $\sim 0.70$, classifying them as `BORDERLINE` (`ENHANCEMENT`). Permanently bleached tissue cannot be restored by software enhancement.
2. **Defocus Blur Misclassified as Borderline (11 images):**  
   11 images with raw $\text{LapVar} < 4.5$ bypassed hard failure because cumulative Tenengrad energy exceeded $50.0$.
