# DR Screening Dashboard — Frontend

Explainable-AI dashboard for the SIH 2026 (PS 26038) Diabetic Retinopathy screening tool.
This is the **frontend only** (plain HTML/CSS/JS, no build step, no framework). It renders
the two states from the approved mockup:

1. **Start screening** — patient ID, eye selection, fundus image upload.
2. **Results** — the analyzed fundus image plus DR classification, lesion counts, quality
   assessment, lesion-detection chart, XAI (Grad-CAM) thumbnails, a Simulink telemedicine
   panel, and a patient-history trend.

Everything in the results view — **including the composited fundus image** — is designed to
come from the backend. Right now it runs on a built-in **demo mock** so you can click through
it standalone. Wiring the real model is a one-function change (see below).

## Run it

No install needed. Either:

- **Double-click `index.html`** to open it in a browser, or
- Serve the folder (recommended, and required once you add a backend on another origin):

  ```bash
  cd dr-dashboard
  python -m http.server 8000
  # open http://localhost:8000
  ```

Enter a patient ID (optional), pick an eye, upload any image, and click **Start analysis**.
In demo mode it waits ~1.6 s, then fills every panel using `assets/sample_*.png` and mock
numbers. The image you upload appears as the XAI "Original" thumbnail.

## Files

```
dr-dashboard/
├── index.html            markup for both states + all panels
├── styles.css            layout & the mockup's colour system
├── app.js                state logic, charts (SVG), and the backend seam
├── assets/
│   ├── sample_result.png   demo: fundus + Grad-CAM heatmap + lesion boxes (main view)
│   ├── sample_original.png demo: plain fundus (XAI "Original")
│   └── sample_heatmap.png  demo: fundus + heatmap (XAI "Grad-CAM")
├── tools/
│   └── gen_placeholders.py regenerates the demo images (Pillow + numpy)
└── README.md
```

## Wiring the backend

All the "get data from the model" logic lives in **one function**, `analyzeImage()` in `app.js`.
Delete the demo block and uncomment the real `fetch` block:

```js
async function analyzeImage({ patientId, eye, file }) {
  const fd = new FormData();
  fd.append("patient_id", patientId);
  fd.append("eye", eye);
  fd.append("image", file);
  const res = await fetch(`${API_BASE}/api/analyze`, { method: "POST", body: fd });
  if (!res.ok) throw new Error(`Analysis failed (${res.status})`);
  return await res.json();
}
```

Set `API_BASE` at the top of `app.js` (empty = same origin, or e.g. `http://localhost:5000`).

### Expected response (`POST /api/analyze`)

```jsonc
{
  "result_image_url": "https://…/result.png",   // fundus WITH heatmap + boxes already drawn
  "classification": {
    "grade": 3,                                  // 0..4  ← DRPredictor
    "confidence": 0.94,                          //       ← DRPredictor (max prob)
    "class_probs": [0.01, 0.03, 0.10, 0.72, 0.14],//      ← DRPredictor
    "referable": true,                           // grade >= 2  ← DRPredictor
    "referable_prob": 0.96                       // P(G2)+P(G3)+P(G4)  ← DRPredictor
  },
  "lesions":  { "microaneurysms": 12, "hemorrhages": 4, "exudates": 7,
                "detection_bars": [3, 12, 7, 4, 2] },
  "quality":  { "focus": "Optimal", "illumination": "Optimal", "field_of_view": "Optimal",
                "overall": "Excellent", "enhancement": "Adaptive (CLAHE + Norm)" },
  "xai":      { "original_url": "…", "heatmap_url": "…" },
  "telemedicine": { "throughput_per_hr": 120, "capacity_per_year": 100000, "current_load_pct": 68 },
  "history":  [ { "t": "2026-01", "grade": 1 }, { "t": "2026-04", "grade": 2 },
                { "t": "2026-07", "grade": 2 }, { "t": "now", "grade": 3 } ]
}
```

## What is real vs. stubbed today

The dashboard shows several panels; only some map to a model that currently exists.

- **DR Classification** (`classification.*`) maps 1:1 to your Module 3 `DRPredictor`
  (grade, confidence, class probabilities, referable flag, referable probability). This is
  the real, load-bearing output.
- **Result image, XAI heatmap** — expected to be produced by Grad-CAM on the EfficientNet-B0
  model on the backend and returned as image URLs. Demo uses synthetic stand-ins.
- **Lesion detection, Quality assessment, Simulink telemedicine, Patient history** — no model
  yet (Modules 1/2 and the telemetry/history store are future work). The frontend expects the
  shapes above; return them from the backend when those modules land. Until then, keep them as
  clearly-labelled placeholder values.

## Two intentional deviations from the mockup

- **Grade labels are clinically standard.** Level 3 is shown as **"Severe (Referable NPDR)"**,
  not "Moderate" as printed in the mockup. Standard ETDRS grading is: 0 No DR, 1 Mild NPDR,
  2 Moderate NPDR, 3 Severe NPDR, 4 Proliferative DR. Edit `GRADE_LABELS` in `app.js` if you
  want different wording.
- The sidebar reads **"SIH 2026"** (the mockup said 2024).
