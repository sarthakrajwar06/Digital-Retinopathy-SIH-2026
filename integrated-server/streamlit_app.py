"""RetinaXplain — deploy the existing HTML/CSS/JS dashboard on Streamlit Cloud.

The dashboard files under dr-dashboard/ remain the source of truth for the UI.
Streamlit Components v2 hosts those files without converting the design to Streamlit widgets.
The Python side calls the existing Flask application through its test client, so no Flask
port is opened and the existing /api/analyze and /api/report logic is reused unchanged.
"""
from __future__ import annotations

import base64
import io
import json
import mimetypes
import re
import sys
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent
DASH_DIR = ROOT_DIR / "dr-dashboard"

if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

st.set_page_config(
    page_title="RetinaXplain — Explainable Retinal Screening",
    page_icon="👁️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
        """
        <style>
            html, body, .stApp,
            [data-testid="stAppViewContainer"],
            [data-testid="stMain"],
            [data-testid="stMainBlockContainer"] {
                background: linear-gradient(90deg, #d9683e 0%, #ee9661 48%, #f6b17e 100%) !important;
            }
            [data-testid="stHeader"],
            [data-testid="stToolbar"],
            [data-testid="stDecoration"],
            [data-testid="stSidebar"] {
                display: none !important;
            }
            [data-testid="stMainBlockContainer"] {
                max-width: none !important;
                padding: 0 !important;
            }
            [data-testid="stAppViewContainer"] > .main,
            [data-testid="stAppViewContainer"] section.main,
            [data-testid="stMain"] > div,
            section.main,
            .main .block-container,
            [data-testid="stElementContainer"] {
                width: 100% !important;
                max-width: none !important;
                margin: 0 !important;
                padding: 0 !important;
            }
            html, body, .stApp,
            [data-testid="stAppViewContainer"] > .main,
            [data-testid="stMain"] > div,
            .main .block-container {
                background: linear-gradient(90deg, #d9683e 0%, #ee9661 48%, #f6b17e 100%) !important;
            }
            [data-testid="stVerticalBlock"] {
                gap: 0 !important;
            }
            iframe {
                display: block !important;
                width: 100% !important;
                max-width: none !important;
                border: 0 !important;
            }
        </style>
        """,
        unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Existing backend — no app.run(), no port 8000.
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def get_backend():
    import server
    return server.create_app(), server


def image_to_data_url(path: Path) -> str | None:
    if not path or not path.exists():
        return None
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return "data:" + mime + ";base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def rewrite_analysis_urls(payload: dict, server_module) -> dict:
    """Turn Flask /outputs/... URLs into browser-safe data URLs for the hosted UI."""
    out = json.loads(json.dumps(payload))
    output_root = Path(server_module.OUTPUT_DIR)

    def convert(url):
        if not isinstance(url, str) or not url.startswith("/outputs/"):
            return url
        rel = url[len("/outputs/"):]
        path = output_root / rel
        return image_to_data_url(path) or url

    for key in ("result_image_url", "submitted_photo_url", "enhanced_photo_url"):
        if key in out:
            out[key] = convert(out[key])
    lesions = out.get("lesions") or {}
    if "annotated_url" in lesions:
        lesions["annotated_url"] = convert(lesions["annotated_url"])
    xai = out.get("xai") or {}
    for key in ("original_url", "heatmap_url"):
        if key in xai:
            xai[key] = convert(xai[key])
    return out


def save_data_url(value: str | None, destination: Path) -> str | None:
    if not isinstance(value, str) or not value.startswith("data:"):
        return value
    try:
        header, encoded = value.split(",", 1)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(base64.b64decode(encoded))
        return str(destination)
    except Exception:
        return value


def prepare_report_payload(payload: dict, report_dir: Path) -> dict:
    """Restore data URLs to local files because the existing PDF renderer expects paths."""
    out = json.loads(json.dumps(payload))
    report_id = re.sub(r"[^A-Za-z0-9._-]+", "_", str(out.get("report_id", "report")))
    base = report_dir / report_id
    for idx, eye in enumerate(out.get("eyes") or []):
        prefix = base / f"eye_{idx+1}"
        mapping = {
            "image_path": "image.png",
            "gradcam_path": "heatmap.png",
            "annotated_image_path": "annotated.png",
        }
        for key, filename in mapping.items():
            if key in eye:
                eye[key] = save_data_url(eye.get(key), prefix / filename)
    return out


def handle_bridge_request(request: dict) -> dict:
    try:
        backend, server_module = get_backend()
        client = backend.test_client()
        kind = request.get("type")
        request_id = request.get("id")

        if kind == "analyze":
            raw = base64.b64decode(request["image_base64"])
            form = {
                "patient_id": request.get("patient_id") or "Unlabeled",
                "eye": request.get("eye") or "Right",
                "image": (io.BytesIO(raw), request.get("filename") or "fundus.jpg"),
            }
            response = client.post("/api/analyze", data=form, content_type="multipart/form-data")
            body = response.get_json(silent=True) or {"error": response.get_data(as_text=True)}
            if response.status_code < 300 and isinstance(body, dict):
                body = rewrite_analysis_urls(body, server_module)
            return {"id": request_id, "status": response.status_code, "body": body}

        if kind == "report":
            payload = prepare_report_payload(request.get("payload") or {}, Path(server_module.REPORT_DIR) / "streamlit_bridge")
            response = client.post("/api/report", json=payload)
            if response.status_code >= 300:
                body = response.get_json(silent=True) or {"error": response.get_data(as_text=True)}
                return {"id": request_id, "status": response.status_code, "body": body}
            return {
                "id": request_id,
                "status": 200,
                "body": {
                    "pdf_base64": base64.b64encode(response.data).decode("ascii"),
                    "mime": "application/pdf",
                },
            }

        return {"id": request_id, "status": 400, "body": {"error": "Unknown bridge request"}}
    except Exception as exc:
        return {
            "id": request.get("id"),
            "status": 500,
            "body": {"error": f"{type(exc).__name__}: {exc}"},
        }


# ---------------------------------------------------------------------------
# Load the original dashboard source files. Only the transport seam is changed.
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def load_frontend():
    import re
    html = (DASH_DIR / "index.html").read_text(encoding="utf-8")
    css = (DASH_DIR / "style.css").read_text(encoding="utf-8")
    js = (DASH_DIR / "script.js").read_text(encoding="utf-8")

    body_match = re.search(r"<body[^>]*>(.*)</body>", html, flags=re.S | re.I)
    if not body_match:
        raise RuntimeError("dr-dashboard/index.html does not contain a <body> section")
    body = body_match.group(1)

    def uri(rel):
        p = DASH_DIR / rel
        mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        return "data:" + mime + ";base64," + base64.b64encode(p.read_bytes()).decode("ascii")

    body = body.replace("images/fundus-sample.jpg", uri("images/fundus-sample.jpg"))
    body = body.replace("images/heatmap.png", uri("images/heatmap.png"))
    body = re.sub(r'<script\s+src=["\']script\.js["\']\s*></script>', "", body, flags=re.I)
    body = '<div class="retinaxplain-root">' + body + '</div>'

    css = re.sub(r"(^|\n)\s*body\s*\{", r"\1.retinaxplain-root{", css, count=1)
    css = re.sub(r"(^|\n)\s*html\s*\{", r"\1.retinaxplain-root{", css, count=1)
    css = "@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,300;9..144,400;9..144,500;9..144,600&family=Inter:wght@400;500;600;700&display=swap');\n" + css
    css += "\nhtml,body{margin:0!important;padding:0!important;background:transparent!important;}\n.retinaxplain-root{width:100%;min-height:100%;margin:0!important;position:relative;}\n"

    js = js.replace("document.body.classList.add('modal-open')", "root.classList.add('modal-open')")
    js = js.replace("document.body.classList.remove('modal-open')", "root.classList.remove('modal-open')")
    bridge = Path(__file__).resolve().with_name("retinaxplain_component_bridge.js").read_text(encoding="utf-8")
    return body, css, bridge.replace("/* ORIGINAL_SCRIPT */", js)


HTML, CSS, JS = load_frontend()

component = st.components.v2.component(
    name="retinaxplain_original_dashboard",
    html=HTML,
    css=CSS,
    js=JS,
    isolate_styles=False,
)

if "bridge_response" not in st.session_state:
    st.session_state.bridge_response = None

result = component(
    key="retinaxplain_dashboard",
    data={"bridge_response": st.session_state.bridge_response},
    on_bridge_request_change=lambda: None,
    width="stretch",
    height=3800,
)

request = getattr(result, "bridge_request", None)
if request:
    # Triggers are transient; process the current request exactly once per rerun.
    last_id = st.session_state.get("last_bridge_request_id")
    request_id = request.get("id") if isinstance(request, dict) else None
    if request_id and request_id != last_id:
        st.session_state.last_bridge_request_id = request_id
        st.session_state.bridge_response = handle_bridge_request(request)
        st.rerun()
