"""
End-to-end smoke test for the INTEGRATED DR screening server.

Verifies the full chain without a running HTTP server:
    upload image -> Module 1 quality gate -> Module 3 DRPredictor
                 -> Grad-CAM outputs written -> patient history updated

Usage:
    python integrated-server/smoke_test.py [image1.jpg image2.jpg ...]

With no arguments it picks two bundled sample fundus photos from the
quality-pipeline reports folder (a "normal/accepted" one and an
"escalated_critical" one) to exercise both the OK-TO-GO and the
RECAPTURE paths.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent
ROOT_DIR = SERVER_DIR.parent
SAMPLES_DIR = ROOT_DIR / "Image-quality-assessment-pipeline" / "reports" / "module1_full_visual_samples"

sys.path.insert(0, str(SERVER_DIR))

import server as sv  # noqa: E402


def pick_samples():
    normal = SAMPLES_DIR / "normal_accepted_aptos_000c1434d8d7.jpg"
    critical = SAMPLES_DIR / "escalated_critical_aptos_0da632ca45e0.jpg"
    if not normal.exists():
        normal = sorted(SAMPLES_DIR.glob("*.jpg"))[0]
        critical = sorted(SAMPLES_DIR.glob("*.jpg"))[-1]
    return [normal, critical]


def run_analyze(client, path: Path, patient: str):
    with open(path, "rb") as f:
        data = f.read()
    resp = client.post(
        "/api/analyze",
        data={
            "patient_id": patient,
            "eye": "Right",
            "image": (io.BytesIO(data), path.name),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200, f"{path.name}: HTTP {resp.status_code}: {resp.get_data(as_text=True)[:500]}"
    j = resp.get_json()

    # contract checks (see BACKEND CONTRACT in dr-dashboard/app.js)
    assert set(j["classification"]) == {"grade", "confidence", "class_probs",
                                        "referable", "referable_prob"}
    assert 0 <= j["classification"]["grade"] <= 4
    assert len(j["classification"]["class_probs"]) == 5
    assert abs(sum(j["classification"]["class_probs"]) - 1.0) < 0.05
    assert j["classification"]["referable"] == (j["classification"]["grade"] >= 2)

    for key in ("result_image_url", "xai", "quality", "quality_gate",
                "lesions", "telemedicine", "history"):
        assert key in j, f"missing response key {key}"

    gate = j["quality_gate"]
    assert gate["action"] in ("OK TO GO", "ENHANCEMENT", "RECAPTURE")

    # outputs physically exist and are servable
    for url in (j["result_image_url"], j["xai"]["original_url"], j["xai"]["heatmap_url"]):
        r = client.get(url)
        assert r.status_code == 200, f"missing static output {url}"
        assert len(r.data) > 1000

    return j


def main():
    app = sv.create_app()
    app.config["TESTING"] = True
    client = app.test_client()

    # warm-up: forces Module 3 (torch) import + model load
    h = client.get("/api/health").get_json()
    print("health:", h)
    assert h["quality_module"], f"quality module failed: {h['quality_error']}"
    assert h["dr_model"], f"DR model failed: {h['dr_model_error']}"

    paths = [Path(a) for a in sys.argv[1:]] or pick_samples()
    print(f"\nSample images: {[p.name for p in paths]}\n")

    for i, p in enumerate(paths):
        print("-" * 70)
        print(f"[{i + 1}/{len(paths)}] {p.name}")
        j = run_analyze(client, p, patient=f"SMOKE-{i:03d}")
        c = j["classification"]
        g = j["quality_gate"]
        print(f"  quality  : {g['original_status']} -> {g['final_status']} "
              f"[{g['action']}]  ops={g['operations']}")
        print(f"  reason   : {g['reason'][:150]}")
        print(f"  DR grade : {c['grade']}  confidence={c['confidence']:.3f}  "
              f"referable={c['referable']} ({c['referable_prob']:.3f})")
        print(f"  probs    : {[round(x, 3) for x in c['class_probs']]}")
        print(f"  latency  : {j['request']['processed_ms']} ms  "
              f"history points={len(j['history'])}")

    print("-" * 70)
    print("INTEGRATED SERVER SMOKE TEST: PASS")


if __name__ == "__main__":
    main()
