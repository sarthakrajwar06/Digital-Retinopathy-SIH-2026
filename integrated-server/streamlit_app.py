"""
RetinaXplain — Streamlit Cloud application.

This is a Streamlit UI adapter around the existing integrated Flask backend logic.
The original server.py remains reusable as an API backend; this file does not
start Flask or bind to port 8000.

Workflow preserved:
1. Fundus image upload
2. Module 1 quality gate + enhancement/reassessment
3. EfficientNet-B0 DR classification
4. Grad-CAM explanation
5. Module-2 lesion-candidate annotation (when available)
6. Screening history
7. PDF report generation
"""

from __future__ import annotations

import io
import sys
import uuid
from pathlib import Path

import streamlit as st
from PIL import Image

# --------------------------------------------------------------------------- #
# Make the integrated-server directory importable.
# --------------------------------------------------------------------------- #
APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent

if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

# Reuse the existing, tested screening logic from server.py.
# Importing server.py creates the Flask app object but does NOT call app.run(),
# because its startup block is protected by if __name__ == "__main__".
from server import (  # noqa: E402
    ALLOWED_EXT,
    DRModelService,
    OUTPUT_DIR,
    REPORT_DIR,
    QUALITY_READY,
    QUALITY_ERROR,
    ANNOTATOR_READY,
    ANNOTATOR_ERROR,
    assess_and_enhance_pipeline,
    quality_block,
    record_screening,
    telemedicine_stats,
)

try:
    from lesion_annotator import annotate_lesion_candidates
except Exception:
    annotate_lesion_candidates = None


st.set_page_config(
    page_title="RetinaXplain",
    page_icon="👁️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --------------------------------------------------------------------------- #
# Small UI helpers
# --------------------------------------------------------------------------- #
def status_badge(label: str, value: str):
    st.markdown(
        f"""
        <div style="
            border:1px solid rgba(128,128,128,.25);
            border-radius:12px;
            padding:12px 14px;
            margin-bottom:10px;">
            <div style="font-size:0.78rem;opacity:.70">{label}</div>
            <div style="font-size:1.08rem;font-weight:650">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def display_quality(q):
    st.subheader("Image Quality Assessment")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        status_badge("Overall", q["overall"])
    with c2:
        status_badge("Focus", q["focus"])
    with c3:
        status_badge("Illumination", q["illumination"])
    with c4:
        status_badge("Field of View", q["field_of_view"])

    action = q["action"]
    if action == "RECAPTURE":
        st.error(
            f"**Quality gate: RECAPTURE REQUIRED** — {q.get('reason') or 'The image is not reliable enough for screening.'}"
        )
    elif action == "ENHANCE_AND_REASSESS":
        st.warning(
            f"**Quality gate: ENHANCE & REASSESS** — {q.get('reason') or 'The image is borderline.'}"
        )
    else:
        st.success(
            f"**Quality gate: OK TO GO** — {q.get('reason') or 'The image passed the quality gate.'}"
        )

    with st.expander("Quality gate details"):
        a, b, c, d = st.columns(4)
        a.metric("Original score", f"{q['overall_score']:.3f}")
        b.metric("Post-enhancement", f"{q['post_enhancement_score']:.3f}")
        c.metric("Score delta", f"{q['score_delta']:+.3f}")
        d.metric("Final status", q["final_status"])

        if q.get("enhancement"):
            st.write(f"**Enhancement:** {q['enhancement']}")

        scores = q.get("dimension_scores") or {}
        if scores:
            st.write("**Dimension scores**")
            st.json(scores)


@st.cache_resource(show_spinner=False)
def get_model():
    return DRModelService.get_instance()


def analyze_image(raw: bytes, filename: str):
    """Run the same screening pipeline used by server.py's /api/analyze."""
    import cv2
    import numpy as np

    bgr = cv2.imdecode(
        np.frombuffer(raw, dtype=np.uint8),
        cv2.IMREAD_COLOR,
    )
    if bgr is None:
        raise ValueError("Could not decode image. Is it a valid fundus photo?")

    h, w = bgr.shape[:2]
    if min(h, w) < 96:
        raise ValueError(f"Image too small ({w}x{h}) for fundus analysis.")

    try:
        pil_rgb = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception:
        pil_rgb = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))

    qres, _orig_bgr, passed_bgr = assess_and_enhance_pipeline(
        bgr, filename=filename
    )

    model = get_model()
    pil_for_model = Image.fromarray(
        cv2.cvtColor(passed_bgr, cv2.COLOR_BGR2RGB)
    )
    classification, canvas, heat_img, result_img = model.explain(pil_for_model)

    if ANNOTATOR_READY and annotate_lesion_candidates is not None:
        ann = annotate_lesion_candidates(
            passed_bgr,
            classification["grade"],
        )
    else:
        ann = {
            "microaneurysms": 0,
            "hemorrhages": 0,
            "exudates": 0,
            "annotated_bgr": None,
            "note": f"Annotator unavailable: {ANNOTATOR_ERROR}",
        }

    return {
        "qres": qres,
        "classification": classification,
        "canvas": canvas,
        "heat_img": heat_img,
        "result_img": result_img,
        "submitted": Image.open(io.BytesIO(raw)).convert("RGB"),
        "enhanced_bgr": passed_bgr if qres.get("enhancement_applied") else None,
        "annotated_bgr": ann.get("annotated_bgr"),
        "lesions": ann,
        "width": w,
        "height": h,
    }


def save_outputs(result, patient_id: str, eye: str, filename: str):
    """Persist the same output artifacts/history used by the Flask backend."""
    import cv2

    run_id = uuid.uuid4().hex[:12]
    run_dir = OUTPUT_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    result["canvas"].save(run_dir / "original.png")
    result["heat_img"].save(run_dir / "heatmap.png")
    result["result_img"].save(run_dir / "result.png")
    result["submitted"].save(run_dir / "submitted.png")

    enhanced_bgr = result.get("enhanced_bgr")
    if enhanced_bgr is not None:
        Image.fromarray(
            cv2.cvtColor(enhanced_bgr, cv2.COLOR_BGR2RGB)
        ).save(run_dir / "enhanced.png")

    annotated_bgr = result.get("annotated_bgr")
    if annotated_bgr is not None:
        Image.fromarray(
            cv2.cvtColor(annotated_bgr, cv2.COLOR_BGR2RGB)
        ).save(run_dir / "annotated.png")

    q = quality_block(result["qres"])
    cls = result["classification"]

    history = record_screening(
        patient_id,
        eye,
        cls["grade"],
        cls["referable"],
        result["qres"]["final_directive"],
    )

    return run_id, q, history


def make_report_data(result, q, patient_id, eye, filename, history):
    cls = result["classification"]
    lesions = result["lesions"]

    return {
        "report_id": uuid.uuid4().hex[:12],
        "patient_id": patient_id or "Unlabeled",
        "eye": eye,
        "image_name": filename,
        "classification": cls,
        "lesions": {
            "microaneurysms": int(lesions.get("microaneurysms", 0)),
            "hemorrhages": int(lesions.get("hemorrhages", 0)),
            "exudates": int(lesions.get("exudates", 0)),
        },
        "quality": {
            "focus": q["focus"],
            "illumination": q["illumination"],
            "field_of_view": q["field_of_view"],
            "overall": q["overall"],
            "enhancement": q["enhancement"],
        },
        "quality_gate": {
            "original_status": q["original_status"],
            "final_status": q["final_status"],
            "action": q["action"],
            "overall_score": q["overall_score"],
            "post_enhancement_score": q["post_enhancement_score"],
            "score_delta": q["score_delta"],
            "enhancement_applied": bool(result["qres"].get("enhancement_applied")),
            "operations": result["qres"].get("enhancement_operations") or [],
            "recapture_required": bool(result["qres"]["recapture_required"]),
            "ok_to_go": bool(result["qres"]["ok_to_go"]),
            "reason": q["reason"],
            "dimension_scores": q["dimension_scores"],
        },
        "history": history,
        "telemedicine": telemedicine_stats(),
    }


# --------------------------------------------------------------------------- #
# Header
# --------------------------------------------------------------------------- #
st.title("RetinaXplain")
st.caption(
    "Explainable AI for Diabetic Retinopathy Screening — SIH 2026 / PS 26038"
)

if not QUALITY_READY:
    st.error(f"Quality module unavailable: {QUALITY_ERROR}")

# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.header("Screening Details")

    patient_id = st.text_input(
        "Patient ID",
        placeholder="Optional",
    )

    eye = st.selectbox(
        "Eye",
        ["Right", "Left"],
    )

    st.divider()
    st.subheader("System Status")

    status_badge(
        "Image Quality Module",
        "Ready" if QUALITY_READY else "Unavailable",
    )
    status_badge(
        "Lesion Annotator",
        "Ready" if ANNOTATOR_READY else "Optional / Unavailable",
    )

    st.caption(
        "The DR model is loaded on CPU for Streamlit Cloud compatibility."
    )

# --------------------------------------------------------------------------- #
# Upload
# --------------------------------------------------------------------------- #
st.subheader("Fundus Image")

uploaded = st.file_uploader(
    "Upload a retinal fundus photograph",
    type=["jpg", "jpeg", "png", "bmp", "tif", "tiff"],
    help="The original image is passed to the quality module before any model processing.",
)

if uploaded is None:
    st.info(
        "Upload a fundus image to run the complete RetinaXplain screening pipeline."
    )

else:
    filename = uploaded.name
    suffix = Path(filename).suffix.lower()

    if suffix not in ALLOWED_EXT:
        st.error(f"Unsupported file type: {suffix}")
        st.stop()

    raw = uploaded.getvalue()

    # Preview before analysis.
    preview = Image.open(io.BytesIO(raw)).convert("RGB")
    st.image(
        preview,
        caption=f"Submitted image — {preview.width} × {preview.height}px",
        width="stretch",
    )

    run = st.button(
        "Run RetinaXplain Analysis",
        type="primary",
        width="stretch",
    )

    if run:
        if not QUALITY_READY:
            st.error(f"Cannot analyze: {QUALITY_ERROR}")
            st.stop()

        with st.status("Running RetinaXplain pipeline...", expanded=True) as status:
            try:
                st.write("1/5 — Assessing image quality...")
                result = analyze_image(raw, filename)

                st.write("2/5 — Applying quality-gate decision...")
                st.write("3/5 — Running EfficientNet-B0 DR classification...")
                st.write("4/5 — Generating Grad-CAM explanation...")
                st.write("5/5 — Detecting lesion candidates and saving history...")

                run_id, q, history = save_outputs(
                    result,
                    patient_id,
                    eye,
                    filename,
                )

                result["run_id"] = run_id
                result["q"] = q
                result["history"] = history

                st.session_state["last_result"] = result
                st.session_state["last_patient_id"] = patient_id
                st.session_state["last_eye"] = eye
                st.session_state["last_filename"] = filename

                status.update(
                    label="Analysis complete",
                    state="complete",
                    expanded=False,
                )

            except Exception as exc:
                status.update(
                    label="Analysis failed",
                    state="error",
                    expanded=True,
                )
                st.exception(exc)
                st.stop()

# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #
if "last_result" in st.session_state:
    result = st.session_state["last_result"]
    q = result["q"]
    cls = result["classification"]
    lesions = result["lesions"]
    patient_id = st.session_state["last_patient_id"]
    eye = st.session_state["last_eye"]
    filename = st.session_state["last_filename"]

    st.divider()
    st.header("Screening Result")

    if q["action"] == "RECAPTURE":
        st.error(
            "**RECAPTURE REQUIRED** — the image was flagged as unreliable by the quality gate."
        )
    elif q["action"] == "ENHANCE_AND_REASSESS":
        st.warning(
            "**ENHANCE & REASSESS** — the borderline image was processed before classification."
        )
    else:
        st.success("**OK TO GO** — the image passed the quality gate.")

    display_quality(q)

    st.subheader("DR Classification")

    names = ["No DR", "Mild NPDR", "Moderate NPDR", "Severe NPDR", "PDR"]
    grade = int(cls["grade"])
    label = names[min(4, max(0, grade))]

    c1, c2, c3 = st.columns(3)
    c1.metric("DR Grade", f"{grade} — {label}")
    c2.metric("Confidence", f"{cls['confidence'] * 100:.1f}%")
    c3.metric(
        "Referable Probability",
        f"{cls['referable_prob'] * 100:.1f}%",
    )

    if cls["referable"]:
        st.warning("The model classifies this result as referable DR.")
    else:
        st.success("The model classifies this result as non-referable DR.")

    st.subheader("Explainable AI — Grad-CAM")

    c1, c2, c3 = st.columns(3)
    with c1:
        st.image(result["canvas"], caption="Model input", width="stretch")
    with c2:
        st.image(result["heat_img"], caption="Grad-CAM heatmap", width="stretch")
    with c3:
        st.image(result["result_img"], caption="XAI overlay", width="stretch")

    st.subheader("Lesion Candidates")

    l1, l2, l3 = st.columns(3)
    l1.metric("Microaneurysms", int(lesions.get("microaneurysms", 0)))
    l2.metric("Hemorrhages", int(lesions.get("hemorrhages", 0)))
    l3.metric("Exudates", int(lesions.get("exudates", 0)))

    if lesions.get("annotated_bgr") is not None:
        import cv2

        annotated = Image.fromarray(
            cv2.cvtColor(lesions["annotated_bgr"], cv2.COLOR_BGR2RGB)
        )
        st.image(
            annotated,
            caption="Lesion-candidate annotation",
            width="stretch",
        )

    if lesions.get("note"):
        st.caption(lesions["note"])

    # ----------------------------------------------------------------------- #
    # PDF report
    # ----------------------------------------------------------------------- #
    st.subheader("Clinical Report")

    report_data = make_report_data(
        result,
        q,
        patient_id,
        eye,
        filename,
        result["history"],
    )

    try:
        from report_service import normalize_report, render_pdf

        report_id = report_data["report_id"]
        report_path = REPORT_DIR / f"report_{report_id}.pdf"
        normalized = normalize_report(report_data)
        render_pdf(normalized, report_path, APP_DIR)

        st.download_button(
            "Download RetinaXplain PDF Report",
            data=report_path.read_bytes(),
            file_name=f"RetinaXplain_{report_id}.pdf",
            mime="application/pdf",
            width="stretch",
        )
    except Exception as exc:
        st.warning(f"PDF report generation is unavailable: {type(exc).__name__}: {exc}")

    # ----------------------------------------------------------------------- #
    # Telemedicine + history
    # ----------------------------------------------------------------------- #
    st.subheader("Telemedicine & Patient History")

    stats = telemedicine_stats()
    a, b, c = st.columns(3)
    a.metric("Throughput / hour", stats["throughput_per_hr"])
    b.metric("Annual design capacity", f"{stats['capacity_per_year']:,}")
    c.metric("Current load", f"{stats['current_load_pct']}%")

    history = result["history"]
    if history:
        import pandas as pd

        history_df = pd.DataFrame(history)
        st.line_chart(
            history_df.set_index("t")["grade"],
            y_label="DR Grade",
        )
else:
    st.divider()
    st.info("No analysis has been run yet.")
