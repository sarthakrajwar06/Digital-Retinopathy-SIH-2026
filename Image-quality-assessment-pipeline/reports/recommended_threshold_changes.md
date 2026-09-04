# Module 1: Recommended Threshold and Decision Logic Revisions

> [!IMPORTANT]
> **Implementation and Validation Status Notice**  
> All 6 recommended logic fixes below have been **formally implemented** in `src/config.py`, `src/quality_metrics.py`, and `src/quality_classifier.py`, and thoroughly verified on a targeted 55-image validation set.  
> See the detailed validation report: [decision_engine_fix_validation.md](file:///C:/Users/SAMSUNG/OneDrive/Desktop/SIH/reports/decision_engine_fix_validation.md) and [decision_engine_fix_validation.csv](file:///C:/Users/SAMSUNG/OneDrive/Desktop/SIH/reports/decision_engine_fix_validation.csv).
>
> **Provisional Clinical Disclaimer:**  
> Thresholds and quality classifications in this audit and validation report are provisional and require validation against clinician-assessed fundus image gradability. Because the dataset does not contain clinician-assessed image-quality or gradability labels, no claims of clinical sensitivity, specificity, or clinical-grade diagnostic performance are made.

---

## Implementation Status Summary

| Recommendation | Status | Implementation Details | Target File(s) |
|---|---|---|---|
| **1. Overexposure Hard Failure Decoupling** | ✅ **IMPLEMENTED** | Replaced `AND` with configurable `OR`: `Mean > 140.0 OR BrightPct > 1.5%`. Successfully catches both diffuse bleaching and localized saturation. | `src/config.py`, `src/quality_classifier.py` |
| **2. Minimum Dimension Floor for BORDERLINE** | ✅ **IMPLEMENTED** | Added `MIN_DIMENSION_SCORE_BORDERLINE = 0.20`. Any critical dimension (Focus, Brightness, Contrast, FOV) < 0.20 immediately forces `CRITICAL` / `RECAPTURE`. | `src/config.py`, `src/quality_classifier.py` |
| **3. Multi-Blob Glare Gating** | ✅ **IMPLEMENTED** | Added `ARTIFACT_GLARE_BLOB_NON_CRITICAL_MAX = 4`. Images with $\ge 5$ glare blobs are strictly forbidden from `NON-CRITICAL` and clamped to `BORDERLINE` for inpainting. | `src/config.py`, `src/quality_classifier.py` |
| **4. Center-to-Edge Ratio Vignetting Buffer** | ✅ **IMPLEMENTED** | Replaced unbuffered `Ratio > 1.75` with `Ratio > 1.85 OR (Ratio > 1.75 AND CoV > 0.45)`. Rescued pristine clinical image `train_IDRiD_352.jpg` while catching severe quadrant shadows. | `src/config.py`, `src/quality_classifier.py` |
| **5. Scale-Aware Blur Hard Failure** | ✅ **IMPLEMENTED** | Calibrated scale-aware rule: `NormLap < 8.0 OR (RawLap < 4.0 AND Tenengrad < 120.0)`. Correctly catches high-res severe blur (`aptos_6a244e855d0e.png`) across resolutions. | `src/config.py`, `src/quality_classifier.py` |
| **6. Anatomical Decoupling of Noise Metric** | ✅ **IMPLEMENTED** | Deterministic green-channel black-hat + Sobel edge exclusion mask + robust Median Absolute Deviation (MAD) on homogeneous parenchyma. Focus-noise correlation reduced by 24.4% (from 0.886 down to 0.642). | `src/quality_metrics.py`, `src/quality_classifier.py` |

---

## 1. Recommendation 1: Overexposure Hard Failure Decoupling
- **Status:** ✅ **IMPLEMENTED**
- **Implemented Code (`src/config.py` & `src/quality_classifier.py`):**
  ```python
  HARD_FAILURES['brightness_mean_max'] = 140.0
  HARD_FAILURES['brightness_bright_pct_max'] = 1.5

  # Disjunctive hard failure evaluation:
  if b_mean > HARD_FAILURES['brightness_mean_max']:
      reasons.append(f"Severe Flash Bleaching (Retinal Mean Intensity={b_mean:.1f} > 140.0)")
  elif b_bright > HARD_FAILURES['brightness_bright_pct_max']:
      reasons.append(f"Severe Sensor Saturation (Saturated Pixel Pct={b_bright:.2f}% > 1.5%)")
  ```
- **Validation Outcome:** Catches 5 diffusely bleached cases (`aptos_89ee1fa16f90.png`, `aptos_3c326543fff6.png`, `aptos_cd29c88c9e36.png`, `aptos_aa6242f9e08c.png`, `aptos_6a244e855d0e.png`) and extreme saturation clipping (`aptos_4dd7b322f342.png`), all routed to `CRITICAL` / `RECAPTURE`.

---

## 2. Recommendation 2: Minimum Dimension Floor for BORDERLINE Classification
- **Status:** ✅ **IMPLEMENTED**
- **Implemented Code (`src/config.py` & `src/quality_classifier.py`):**
  ```python
  MIN_DIMENSION_SCORE_BORDERLINE = 0.20

  # Step 3 in Three-Class Hierarchy:
  min_crit_score = min(s_focus, s_bright, s_contrast, s_fov)
  if min_crit_score < MIN_DIMENSION_SCORE_BORDERLINE:
      status = "CRITICAL"
      action = "RECAPTURE"
  ```
- **Validation Outcome:** Prevents hopeless images with fatal single deficits from entering enhancement. Correctly triaged severe low-contrast opacity `aptos_e65a2ff90494.png` (`score_contrast = 0.0 < 0.20`) directly to `CRITICAL` / `RECAPTURE`.

---

## 3. Recommendation 3: Multi-Blob Glare Gating for NON-CRITICAL
- **Status:** ✅ **IMPLEMENTED**
- **Implemented Code (`src/config.py` & `src/quality_classifier.py`):**
  ```python
  ARTIFACT_GLARE_BLOB_NON_CRITICAL_MAX = 4

  # Step 4 in Three-Class Hierarchy:
  if glare_blobs > ARTIFACT_GLARE_BLOB_NON_CRITICAL_MAX:
      if overall_score >= CRITICAL_SCORE_THRESHOLD:
          status = "BORDERLINE"
          action = "ENHANCEMENT"
      else:
          status = "CRITICAL"
          action = "RECAPTURE"
  ```
- **Validation Outcome:** Test case `aptos_15cc2aef772a.png` (15 glare blobs, overall score 0.816) was successfully demoted from `NON-CRITICAL` (`OK TO GO`) to `BORDERLINE` (`ENHANCEMENT`) for localized inpainting.

---

## 4. Recommendation 4: Center-to-Edge Ratio Hard Failure Buffer
- **Status:** ✅ **IMPLEMENTED**
- **Implemented Code (`src/config.py` & `src/quality_classifier.py`):**
  ```python
  HARD_FAILURES['illum_center_edge_ratio_max'] = 1.85
  HARD_FAILURES['illum_center_edge_ratio_buffer'] = 1.75
  HARD_FAILURES['illum_cov_buffer_min'] = 0.45
  HARD_FAILURES['illum_map_cov_max'] = 0.52

  # Step 1 Illumination Hard Failure evaluation:
  if cov_i > cov_max:
      reasons.append(f"Severe Non-Uniform Illumination (Map CoV={cov_i:.3f} > {cov_max})")
  elif rat_i > rat_max:
      reasons.append(f"Extreme Center/Edge Vignetting (Ratio={rat_i:.2f} > {rat_max})")
  elif rat_i > rat_buf and cov_i > cov_buf:
      reasons.append(f"Severe Peripheral Blackout & Gradient (Ratio={rat_i:.2f} > {rat_buf}, CoV={cov_i:.3f} > {cov_buf})")
  ```
- **Validation Outcome:** 
  - `train_IDRiD_352.jpg` (Ratio=1.755, CoV=0.422) is protected from hard failure and routed to `BORDERLINE` (`ENHANCEMENT`) with pristine overall score 0.857.
  - `aptos_5cab3ef4b31c.png` (Ratio=1.752, CoV=0.478) correctly triggers `CRITICAL` / `RECAPTURE`.
  - `aptos_50d8a8fb7737.png` (Ratio=1.948 > 1.85) correctly triggers `CRITICAL` / `RECAPTURE`.
  - `aptos_6ccfdb031184.png` (CoV=0.697 > 0.52) correctly triggers `CRITICAL` / `RECAPTURE`.

---

## 5. Recommendation 5: Scale-Aware Blur Hard Failure
- **Status:** ✅ **IMPLEMENTED**
- **Implemented Code (`src/config.py` & `src/quality_classifier.py`):**
  ```python
  HARD_FAILURES['blur_normalized_laplacian_min'] = 8.0
  HARD_FAILURES['blur_laplacian_var_raw_min'] = 4.0
  HARD_FAILURES['blur_tenengrad_raw_max'] = 120.0

  scale_adj = (max(w, h) / 1024.0) ** 2 if (w and h and w > 0 and h > 0) else 1.0
  lap_norm = lap * scale_adj

  if lap_norm < blur_norm_min or (lap < blur_raw_min and ten < blur_ten_max):
      reasons.append(f"Severe Defocus Blur (NormLap={lap_norm:.1f} < {blur_norm_min}, RawLap={lap:.2f}, Tenengrad={ten:.1f})")
  ```
- **Validation Outcome:** Catches high-resolution severe blur test case `aptos_6a244e855d0e.png` (RawLap=2.57, Tenengrad=114.6) as `CRITICAL` / `RECAPTURE`, while zero sharp images are falsely flagged.

---

## 6. Recommendation 6: Anatomical Decoupling of Noise Metric
- **Status:** ✅ **IMPLEMENTED**
- **Implemented Code (`src/quality_metrics.py` & `src/quality_classifier.py`):**
  - Retained `noise_residual_std` as legacy / diagnostic metric.
  - Introduced deterministic anatomical exclusion mask (green-channel morphological black-hat + Sobel edge detection dilated by $5 \\times \\text{scale}$) inside eroded retinal FOV.
  - Computed robust Median Absolute Deviation (MAD) on homogeneous parenchyma:
    $$\text{noise\\_decoupled\\_std} = \frac{\text{median}(|R_{\\text{parenchyma}} - \\tilde{R}|)}{0.6745}$$
- **Validation Outcome:** Pearson correlation between noise and focus dropped from $0.8861$ to $0.6418$ ($\Delta r = 0.2443$), substantially restoring orthogonality between sharpness and sensor grain.
