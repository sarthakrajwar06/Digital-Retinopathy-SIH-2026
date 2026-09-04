# DR Screening Dashboard — Frontend

Explainable-AI dashboard for the SIH 2026 (PS 26038) Diabetic Retinopathy screening tool.
Plain HTML/CSS/JS (no build step, no framework) with two states:

1. **Start screening** — patient ID, eye selection, fundus image upload.
2. **Results** — the analyzed fundus image plus DR classification, quality
   assessment, lesion-detection chart, XAI (Grad-CAM) thumbnails, a Simulink
   telemedicine panel, and a patient-history trend.

The dashboard is **wired to the integrated backend** (`integrated-server/`,
one folder up), which serves this frontend at `/` and implements
`POST /api/analyze` by chaining the Module-1 quality gate → Module-3
EfficientNet-B0 classifier → Grad-CAM.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r ../integrated-server/requirements-server.txt
python ../integrated-server/server.py
# open http://localhost:8000  (dashboard is served by the backend)
```

Enter a patient ID (optional), pick an eye, upload a fundus photo, click
**Start analysis** → the panels fill with real model outputs. No backend
running? The form shows a clear error telling you the server is offline.

## Files

```
dr-dashboard/
├── index.html            markup for both states + all panels + quality-gate banner
├── styles.css            layout & the mockup's colour system
├── app.js                state logic, charts (SVG), backend fetch (analyzeImage)
├── assets/
│   ├── sample_result.png   LEGACY demo placeholders (see tools/) — not used
│   ├── sample_original.png when the backend is running
│   └── sample_heatmap.png
├── tools/
│   └── gen_placeholders.py regenerates the legacy demo images (Pillow + numpy)
└── README.md
```

## Backend contract (`POST /api/analyze`)

Multipart fields: `patient_id`, `eye`, `image`. Full JSON shape is documented
in the `BACKEND CONTRACT` block at the top of `app.js` and implemented in
`../integrated-server/server.py`. In addition to the contract fields, the
backend returns a `quality_gate` object (Module-1 verdict + rationale) that
drives the banner under the result image.

## What is real vs. placeholder today

- **DR Classification** — real: Module 3 `DRPredictor` (grade 0–4, softmax
  probabilities, referable flag/probability) on the quality-approved image.
- **Result image / XAI** — real: Grad-CAM on EfficientNet-B0 feature maps
  (implemented in `integrated-server/server.py`), returned as URLs to
  per-run PNGs.
- **Quality Assessment pills + banner** — real: Module 1 7-dimension
  assessment, enhancement applied to BORDERLINE images before grading.
- **Lesion Detection (Module 2)** — **not integrated** (no code/weights in
  the repo). Backend returns `null` counts and the card shows a note.
- **Simulink telemedicine / Patient history** — simulated/local JSON store
  (`integrated-server/runtime/history.json`); swap for a real DB/telemetry
  module when available.

## Intentional deviation from the mockup

Grade labels are clinically standard (ETDRS): 0 No DR, 1 Mild NPDR,
2 Moderate NPDR, 3 Severe NPDR, 4 Proliferative DR. Edit `GRADE_LABELS` in
`app.js` if you want different wording.
