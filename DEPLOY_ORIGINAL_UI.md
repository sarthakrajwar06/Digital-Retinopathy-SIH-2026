# RetinaXplain — deploy the existing HTML/CSS/JS UI

This bundle keeps `dr-dashboard/index.html`, `style.css`, and `script.js` as the UI source.
`integrated-server/streamlit_app.py` hosts that dashboard using Streamlit Components v2 and
bridges the existing Flask `/api/analyze` and `/api/report` routes through Python's Flask test client.
No Flask server port is opened.

The browser title is `RetinaXplain`, and the hosted wrapper removes the
default Streamlit chrome so the original dashboard owns the visible canvas.

## Streamlit Cloud settings
- Repository: `sarthakrajwar06/Digital-Retinopathy-SIH-2026`
- Branch: `main`
- Main file: `integrated-server/streamlit_app.py`

Copy `retinaxplain_component_bridge.js` next to `streamlit_app.py`.
Keep the original `dr-dashboard/` folder in the repository.

## Runtime behavior

- `/api/analyze` runs through Flask's in-process test client.
- `/api/report` returns a generated PDF through the same bridge.
- Hosted data-url images are decoded into
	`runtime/outputs/streamlit_reports/` before PDF generation.
