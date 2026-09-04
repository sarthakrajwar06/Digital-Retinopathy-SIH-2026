# SIH26038 – Explainable AI for Diabetic Retinopathy Screening

## Module 1: Image Quality Assessment & Enhancement

This repository contains the implementation of **Module 1** for the Smart India Hackathon 2026 problem statement **SIH26038 – Explainable AI for Diabetic Retinopathy Screening in Rural India**.

The purpose of Module 1 is to determine whether an incoming retinal fundus photograph is suitable for downstream retinal analysis and diabetic retinopathy screening.

---

## 🎯 Objective

Before applying retinal analysis or AI-based screening, the input fundus image must first be checked for image quality.

Module 1 performs deterministic image quality assessment and classifies each image into three clinical-quality states:

- **NON-CRITICAL** → Image is acceptable → **OK TO GO**
- **BORDERLINE** → Image may benefit from enhancement → **ENHANCE & REASSESS**
- **CRITICAL** → Image is unsuitable → **RECAPTURE REQUIRED**

> `OK TO GO` is a clinical action directive, not a separate quality class.

---

## 🔍 Quality Assessment

The pipeline evaluates seven image-quality dimensions:

1. **Focus / Sharpness**
2. **Brightness / Exposure**
3. **Contrast**
4. **Noise**
5. **Field of View (FOV)**
6. **Illumination Uniformity**
7. **Artifacts / Glare**

The individual measurements are normalized to `[0, 1]` and combined using a weighted quality score.

---
## 🧠 Decision Pipeline
```text
Input Fundus Image
        │
        ▼
Basic Image Validation
        │
        ▼
Retinal FOV Detection
        │
        ▼
7-Dimension Quality Assessment
        │
        ├── Focus
        ├── Brightness
        ├── Contrast
        ├── Noise
        ├── FOV
        ├── Illumination
        └── Artifacts
        │
        ▼
Score Normalization
        │
        ▼
Hard-Failure Checks
        │
        ▼
Weighted Quality Score
        │
        ├── NON-CRITICAL
        │       └── OK TO GO
        │
        ├── BORDERLINE
        │       └── Enhancement
        │              └── Reassessment
 ```

✨ Borderline Image Enhancement

For borderline images, the system can apply controlled deterministic enhancement operations and then reassess the image using the same quality assessment pipeline.

Possible enhancement operations include:

CLAHE-based contrast enhancement
Gamma/intensity correction
Illumination normalization
Controlled denoising
Conservative sharpening
Limited artifact/glare handling

Only one enhancement cycle is performed.

Severe blur, insufficient FOV, severe clipping, and major capture failures are not assumed to be recoverable through enhancement.


🛡️ Safety & Decision Rules

The pipeline follows a strict three-state decision contract:

| Status       | Action             |
| ------------ | ------------------ |
| NON-CRITICAL | OK TO GO           |
| BORDERLINE   | ENHANCE → REASSESS |
| CRITICAL     | RECAPTURE          |

Additional runtime checks verify:

Normalized scores remain within [0, 1]
Composite score remains within [0, 1]
Quality weights sum to 1.0
Clinical action flags remain consistent
CRITICAL images are not enhanced
NON-CRITICAL images bypass enhancement
Input dataset files are not modified

📁 Project Structure
 ```text
.
├── src/
│   ├── config.py
│   ├── dataset_inspector.py
│   ├── fov_detector.py
│   ├── pipeline.py
│   ├── quality_classifier.py
│   ├── quality_enhancer.py
│   └── quality_metrics.py
│
├── scripts/
│   ├── smoke_test_module1.py
│   ├── run_module1_full_production.py
│   └── validation/testing scripts
│
├── reports/
│   └── Module 1 validation and analysis reports
│
├── .gitignore
└── README.md
 ```

⚙️ Requirements

Python 3.13
OpenCV
NumPy
SciPy
scikit-image
Pillow

Install dependencies as required by the project environment.


▶️ Running Module 1

From the project root:
 ```text
py -3.13 scripts\smoke_test_module1.py
 ```
The smoke test runs the complete Module 1 pipeline on a fundus image and reports the quality assessment and final decision.

Test a specific image
 ```text
py -3.13 scripts\smoke_test_module1.py "dataset\your_image.png"
 ```
The script supports a specific image path and reports:
Raw quality metrics
Normalized quality scores
Composite score
Original status
Enhancement requirement
Enhancement operations
Final status
OK_TO_GO
RECAPTURE_REQUIRED
ENHANCEMENT_REQUIRED


📊 Full Dataset Evaluation

The complete dataset evaluation was performed separately during development and validation.

The production evaluation processed 4,178 fundus images.

Final provisional distribution:
 ```text
NON-CRITICAL: 3,891
BORDERLINE: 13
CRITICAL: 274
 ```
These results are included as development/validation artifacts and should not be interpreted as clinical performance claims.


🧪 Verification

The Module 1 smoke test successfully verified:

Core module imports
End-to-end image processing
FOV detection
Seven-dimensional quality assessment
Score normalization
Composite scoring
Enhancement routing
Clinical decision flags
Runtime invariants
Dataset immutability

Example verification result:
 ```text
MODULE 1 SMOKE TEST: PASS
 ```

⚠️ Clinical Disclaimer

This repository represents a research/prototype implementation for the Smart India Hackathon problem statement.

The quality thresholds, weights, and decision boundaries are provisional and require further empirical calibration and clinical validation using appropriately labelled fundus-image quality/gradability data.

The Module 1 output is not a medical diagnosis and should not be used as a standalone clinical decision system.


🚀 Future Integration

Module 1 is designed as the image-quality gate before downstream retinal analysis and diabetic retinopathy screening.

The final system can integrate:
 ```text
Fundus Image
      ↓
Module 1
Image Quality Assessment
      ↓
Quality Gate
      ↓
Retinal Analysis / DR Screening
      ↓
Explainable Result
 ```


🏆 Smart India Hackathon 2026

Problem Statement: SIH26038
Domain: HealthTech
Focus: Explainable AI for Diabetic Retinopathy Screening in Rural India

Developed as part of the Smart India Hackathon 2026.
.
  


