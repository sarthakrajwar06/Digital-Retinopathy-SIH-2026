"""
Generate DEMO placeholder assets for the DR dashboard.

These synthetic images stand in for the backend's composited output so the
dashboard is fully demoable without a model. Replace them at runtime with the
real images returned by the backend (see README -> Backend contract).

Outputs (written to ../assets):
  sample_result.png   -> fundus + Grad-CAM heatmap + labeled lesion boxes (main view)
  sample_original.png -> fundus only (XAI "Original" thumbnail)
  sample_heatmap.png  -> fundus + Grad-CAM heatmap (XAI "Grad-CAM Heatmap" thumbnail)
"""
import os
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.abspath(os.path.join(HERE, "..", "assets"))
os.makedirs(ASSETS, exist_ok=True)

S = 1000                      # canvas size (square)
CX, CY = S * 0.50, S * 0.50   # fundus centre
R = S * 0.46                  # fundus radius
NAVY = np.array([12, 22, 48], dtype=np.float32)   # dark panel background

rng = np.random.default_rng(42)


def _font(size, bold=False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for c in candidates:
        if os.path.exists(c):
            return ImageFont.truetype(c, size)
    return ImageFont.load_default()


def build_fundus():
    """Return an (S,S,3) float32 array: a synthetic retinal fundus on navy."""
    yy, xx = np.mgrid[0:S, 0:S].astype(np.float32)
    dx, dy = xx - CX, yy - CY
    dist = np.sqrt(dx * dx + dy * dy)

    # radial vignette 1.0 (centre) -> 0.0 (edge of disc)
    t = np.clip(dist / R, 0, 1)
    vign = np.clip(1.0 - t ** 2, 0, 1)

    # fundus tissue: warm amber, brighter at centre, darker at rim
    inner = np.array([206, 128, 66], dtype=np.float32)
    outer = np.array([120, 58, 30], dtype=np.float32)
    tissue = outer[None, None, :] + (inner - outer)[None, None, :] * vign[..., None]

    # subtle mottled texture
    noise = rng.normal(0, 7, size=(S, S, 1)).astype(np.float32)
    tissue = tissue + noise

    # optic disc: bright pale-yellow blob, temporal-right
    odx, ody = CX + R * 0.42, CY - R * 0.06
    od = np.exp(-(((xx - odx) ** 2 + (yy - ody) ** 2) / (2 * (R * 0.11) ** 2)))
    disc_col = np.array([245, 224, 150], dtype=np.float32)
    tissue = tissue * (1 - od[..., None] * 0.85) + disc_col[None, None, :] * (od[..., None] * 0.85)

    # macula: slightly darker central-left region
    mx, my = CX - R * 0.10, CY + R * 0.05
    mac = np.exp(-(((xx - mx) ** 2 + (yy - my) ** 2) / (2 * (R * 0.16) ** 2)))
    tissue = tissue * (1 - mac[..., None] * 0.28)

    # composite onto navy outside the circular fundus (soft edge)
    edge = np.clip((R - dist) / (S * 0.02), 0, 1)  # 1 inside, 0 outside
    img = NAVY[None, None, :] * (1 - edge[..., None]) + tissue * edge[..., None]

    img = np.clip(img, 0, 255).astype(np.uint8)
    pil = Image.fromarray(img, "RGB")

    # vessels: dark-red branching strokes drawn from the optic disc
    d = ImageDraw.Draw(pil)
    rng2 = np.random.default_rng(7)
    for _ in range(11):
        ang = rng2.uniform(0, 2 * np.pi)
        x, y = odx, ody
        w = rng2.integers(3, 7)
        pts = [(x, y)]
        for _ in range(14):
            ang += rng2.uniform(-0.35, 0.35)
            step = rng2.uniform(18, 30)
            x += np.cos(ang) * step
            y += np.sin(ang) * step
            if (x - CX) ** 2 + (y - CY) ** 2 > (R * 0.98) ** 2:
                break
            pts.append((x, y))
        if len(pts) > 1:
            d.line(pts, fill=(122, 30, 28), width=int(w), joint="curve")
    pil = pil.filter(ImageFilter.GaussianBlur(0.6))
    return np.asarray(pil).astype(np.float32)


def jet(v):
    """Map intensity v in [0,1] -> (r,g,b) 0..1 using a jet-like ramp."""
    v = np.clip(v, 0, 1)
    r = np.clip(1.5 - np.abs(4 * v - 3), 0, 1)
    g = np.clip(1.5 - np.abs(4 * v - 2), 0, 1)
    b = np.clip(1.5 - np.abs(4 * v - 1), 0, 1)
    return np.stack([r, g, b], axis=-1)


def add_heatmap(fundus):
    """Overlay a Grad-CAM-style heatmap; returns uint8 (S,S,3)."""
    yy, xx = np.mgrid[0:S, 0:S].astype(np.float32)
    # hotspots: strong central macular focus + two weaker satellites
    spots = [
        (CX - R * 0.06, CY + R * 0.04, R * 0.22, 1.0),
        (CX + R * 0.18, CY - R * 0.18, R * 0.12, 0.55),
        (CX - R * 0.28, CY + R * 0.20, R * 0.12, 0.45),
    ]
    inten = np.zeros((S, S), dtype=np.float32)
    for sx, sy, sr, amp in spots:
        inten += amp * np.exp(-(((xx - sx) ** 2 + (yy - sy) ** 2) / (2 * sr ** 2)))
    inten = np.clip(inten, 0, 1)

    # confine to fundus
    dist = np.sqrt((xx - CX) ** 2 + (yy - CY) ** 2)
    inten[dist > R * 0.99] = 0

    heat = jet(inten) * 255.0
    alpha = np.clip(inten * 1.15, 0, 0.72)[..., None]
    out = fundus * (1 - alpha) + heat * alpha
    return np.clip(out, 0, 255).astype(np.uint8)


def draw_boxes(pil):
    """Draw labeled yellow lesion bounding boxes + 'Right eye' caption."""
    d = ImageDraw.Draw(pil)
    fbox = _font(20, bold=True)
    boxes = [
        (455, 150, 560, 235, "Hemorrhages"),
        (300, 275, 405, 360, "Microaneurysms"),
        (185, 430, 285, 515, "MAs"),
        (215, 560, 320, 650, "Exudates"),
        (430, 560, 545, 655, "Exudates"),
        (585, 470, 690, 560, "Microaneurysms"),
    ]
    yellow = (255, 216, 0)
    for x0, y0, x1, y1, label in boxes:
        d.rectangle([x0, y0, x1, y1], outline=yellow, width=3)
        tb = d.textbbox((0, 0), label, font=fbox)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        ly = max(0, y0 - th - 8)
        d.rectangle([x0, ly, x0 + tw + 10, ly + th + 8], fill=(20, 20, 20))
        d.text((x0 + 5, ly + 3), label, fill=yellow, font=fbox)

    cap = _font(34, bold=True)
    txt = "Right eye"
    tb = d.textbbox((0, 0), txt, font=cap)
    d.text((S - (tb[2] - tb[0]) - 30, 24), txt, fill=(255, 255, 255), font=cap)
    return pil


def save(arr, name, size=None):
    im = Image.fromarray(arr, "RGB")
    if size:
        im = im.resize((size, size), Image.LANCZOS)
    im.save(os.path.join(ASSETS, name), optimize=True)
    print("wrote", name, im.size)


if __name__ == "__main__":
    fundus = build_fundus()
    heat = add_heatmap(fundus)

    save(fundus.astype(np.uint8), "sample_original.png", size=520)
    save(heat, "sample_heatmap.png", size=520)

    result = draw_boxes(Image.fromarray(heat, "RGB"))
    save(np.asarray(result), "sample_result.png")
    print("done ->", ASSETS)
