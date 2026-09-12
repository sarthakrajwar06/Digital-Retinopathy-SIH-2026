# SIH 2026 — Explainable AI for Diabetic Retinopathy Screening (PS 26038)

Monorepo for the Smart India Hackathon 2026 problem statement **26038**.
It contains the standalone module work **plus** the new integration server
that connects them into a single web app.

## Repository layout

| Folder | Contents | Status |
| ------ | -------- | ------ |
| `dr-dashboard/` | RetinaXplain frontend (plain HTML/CSS/JS) — upload form, DR results, quality pills, XAI views, and reports | UI done; wired to the real backend |
| `Image-quality-assessment-pipeline/` | **Module 1** — deterministic fundus image-quality assessment + enhancement (7 dimensions, CRITICAL / BORDERLINE / NON-CRITICAL) | standalone ✅ |
| `DiebeticRetinopathy/` | **Module 3** — EfficientNet-B0 DR severity classifier (grades 0–4) + trained checkpoint + `dr_predictor.py` | standalone ✅ |
| `integrated-server/` | Integration layer (Flask + Streamlit host): quality gate → DR classification → Grad-CAM XAI → history and PDF reports | local server and hosted app |

## Quick start: local Flask app

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r integrated-server/requirements-server.txt

python integrated-server/server.py        # http://0.0.0.0:8000
python integrated-server/smoke_test.py    # offline end-to-end test
```

Open the dashboard, upload a fundus photo → you get:
Module-1 quality verdict (+ enhancement when the photo is borderline) →
real DR grade/confidence from the trained EfficientNet-B0 checkpoint →
Grad-CAM heatmap images.

## Hosted Streamlit app

The deployed entrypoint is `integrated-server/streamlit_app.py`. It hosts the
original `dr-dashboard/` UI full-width and bridges the existing Flask analysis
and report routes through a Flask test client.

- Main file: `integrated-server/streamlit_app.py`
- Branch: `main`
- Dependencies: `requirements.txt`
- Browser title: `RetinaXplain`

Hosted report downloads decode image data into the runtime output directory so
the PDF can include the fundus image, Grad-CAM heatmap, and lesion annotation.

## The end-to-end flow (what the integration does)

```
upload ─► Module 1 quality gate (full resolution)
            ├─ NON-CRITICAL ────────────────► classify ORIGINAL
            ├─ BORDERLINE ── enhance & re-assess ─► classify ENHANCED
            └─ CRITICAL ────────────────────► RECAPTURE (classification flagged unreliable)
                                                  │
                  Grad-CAM (EfficientNet-B0) ◄────┘
                  + patient history (runtime/history.json)
```

## Known gaps (not implemented anywhere yet)

1. **Module 2 — Lesion detection / segmentation** is currently a provisional
   classical-CV candidate detector in `integrated-server/lesion_annotator.py`.
   Its counts and boxes are screening aids, not clinical diagnoses; replace it
   with a trained segmenter when available.
2. **Training dataset** (APTOS/IDRiD images + `labels.csv`) is not in the repo
   (large, licensed). The Module-3 notebook and Module-1 scripts reference a
   local `dataset/` folder you must re-supply to retrain or re-run reports.
3. **Grad-CAM was not in the notebooks** — the "Explainable AI" heatmap is
   implemented from scratch in `integrated-server/server.py`
   (`DRModelService.explain()`). Review it before clinical use.
4. **Patient history & telemedicine panel** run on a local JSON store with
   simulated numbers — swap in your DB/telemetry module.
5. `DiebeticRetinopathy/requirements.txt` pins CUDA wheels
   (`torch==2.7.0+cu128`) for the training machine; the server uses plain
   `torch`/`torchvision` (CPU fine).

## Note on the demo images in `dr-dashboard/assets/`

`sample_*.png` are synthetic placeholders (see `dr-dashboard/tools/`) and are
no longer used once the backend is running — real outputs come from
`/outputs/<run_id>/` and hosted report copies from
`/outputs/streamlit_reports/<report_id>/`.
