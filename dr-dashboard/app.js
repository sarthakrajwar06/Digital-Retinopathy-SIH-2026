/* ===================================================================
   DR Screening Dashboard — app.js
   Frontend only. All result data (including the composited fundus image)
   is designed to come from the backend. Today it uses a demo mock so the
   dashboard runs standalone; wiring the real model is a one-function change
   (see analyzeImage() and the contract below).

   ┌─────────────────────────────────────────────────────────────────┐
   │ BACKEND CONTRACT                                                  │
   │ POST {API_BASE}/api/analyze   (multipart/form-data)               │
   │   fields: patient_id (str), eye ("Left"|"Right"), image (file)    │
   │                                                                   │
   │ 200 OK → JSON:                                                    │
   │ {                                                                 │
   │   "result_image_url": "https://…/result.png",  // fundus WITH     │
   │        // Grad-CAM heatmap + lesion boxes already drawn in        │
   │   "classification": {                                             │
   │      "grade": 3,                 // 0..4 from DRPredictor          │
   │      "confidence": 0.94,         // max softmax prob              │
   │      "class_probs": [0.01,0.03,0.10,0.72,0.14],                   │
   │      "referable": true,          // grade >= 2                    │
   │      "referable_prob": 0.96      // P(G2)+P(G3)+P(G4)             │
   │   },                                                              │
   │   "lesions":  { "microaneurysms":12, "hemorrhages":4,             │
   │                 "exudates":7, "detection_bars":[3,12,7,4,2] },    │
   │   "quality":  { "focus":"Optimal", "illumination":"Optimal",      │
   │                 "field_of_view":"Optimal", "overall":"Excellent", │
   │                 "enhancement":"Adaptive (CLAHE + Norm)" },        │
   │   "xai":      { "original_url":"…", "heatmap_url":"…" },           │
   │   "telemedicine": { "throughput_per_hr":120,                      │
   │                 "capacity_per_year":100000, "current_load_pct":68 },│
   │   "history":  [ {"t":"2026-01","grade":1}, {"t":"2026-04","grade":2},│
   │                 {"t":"2026-07","grade":2}, {"t":"now","grade":3} ] │
   │ }                                                                 │
   │                                                                   │
   │ NOTE: classification.* maps 1:1 to DRPredictor output. The other  │
   │ blocks (lesions/quality/telemedicine/history) are stubbed until   │
   │ their modules exist — return them from the backend in this shape. │
   └─────────────────────────────────────────────────────────────────┘
   =================================================================== */

const API_BASE = ""; // same origin; set to "http://localhost:5000" etc. if separate

/* grade → clinical label (0..4). Referable = grade >= 2. */
const GRADE_LABELS = {
  0: "No DR",
  1: "Mild NPDR",
  2: "Moderate (Referable NPDR)",
  3: "Severe (Referable NPDR)",
  4: "Proliferative DR (Referable)",
};

/* ---- demo mock (delete once the backend returns real data) ---- */
const MOCK = {
  result_image_url: "assets/sample_result.png",
  classification: {
    grade: 3, confidence: 0.94,
    class_probs: [0.01, 0.03, 0.10, 0.72, 0.14],
    referable: true, referable_prob: 0.96,
  },
  lesions: { microaneurysms: 12, hemorrhages: 4, exudates: 7, detection_bars: [3, 12, 7, 4, 2] },
  quality: { focus: "Optimal", illumination: "Optimal", field_of_view: "Optimal",
             overall: "Excellent", enhancement: "Adaptive (CLAHE + Norm)" },
  xai: { original_url: "assets/sample_original.png", heatmap_url: "assets/sample_heatmap.png" },
  telemedicine: { throughput_per_hr: 120, capacity_per_year: 100000, current_load_pct: 68 },
  history: [ { t: "Jan", grade: 1 }, { t: "Apr", grade: 2 }, { t: "Jul", grade: 2 }, { t: "Now", grade: 3 } ],
};

/* =============================== refs =============================== */
const $ = (id) => document.getElementById(id);
const app = document.querySelector(".app");
const form = $("screeningForm");
const fileInput = $("fileInput");
const dropZone = $("dropZone");
const dzInner = $("dzInner");
const dzPreview = $("dzPreview");
const previewImg = $("previewImg");
const previewName = $("previewName");
const formError = $("formError");
const uploadState = $("uploadState");
const resultState = $("resultState");
const loading = $("loading");
const resultImage = $("resultImage");
const eyeLabel = $("eyeLabel");
const newScreeningBtn = $("newScreeningBtn");

let selectedFile = null;

/* ============================ utilities ============================ */
const delay = (ms) => new Promise((r) => setTimeout(r, ms));
const selectedEye = () => document.querySelector('input[name="eye"]:checked')?.value || "Left";
const svgNS = "http://www.w3.org/2000/svg";
function el(name, attrs = {}) {
  const n = document.createElementNS(svgNS, name);
  for (const k in attrs) n.setAttribute(k, attrs[k]);
  return n;
}
function polar(cx, cy, r, deg) {
  const a = (deg * Math.PI) / 180;
  return [cx + r * Math.cos(a), cy - r * Math.sin(a)];
}

/* ============================ file input =========================== */
function showPreview(file) {
  selectedFile = file;
  previewImg.src = URL.createObjectURL(file);
  previewName.textContent = file.name;
  dzInner.hidden = true;
  dzPreview.hidden = false;
  formError.hidden = true;
}
function clearPreview() {
  selectedFile = null;
  fileInput.value = "";
  dzInner.hidden = false;
  dzPreview.hidden = true;
}

$("browseBtn").addEventListener("click", () => fileInput.click());
$("uploadBtn").addEventListener("click", () => fileInput.click());
$("clearImgBtn").addEventListener("click", clearPreview);

fileInput.addEventListener("change", (e) => {
  const f = e.target.files[0];
  if (f) showPreview(f);
});

dropZone.addEventListener("keydown", (e) => {
  if ((e.key === "Enter" || e.key === " ") && dzPreview.hidden) { e.preventDefault(); fileInput.click(); }
});
["dragenter", "dragover"].forEach((ev) =>
  dropZone.addEventListener(ev, (e) => { e.preventDefault(); dropZone.classList.add("is-drag"); }));
["dragleave", "drop"].forEach((ev) =>
  dropZone.addEventListener(ev, (e) => { e.preventDefault(); dropZone.classList.remove("is-drag"); }));
dropZone.addEventListener("drop", (e) => {
  const f = e.dataTransfer.files?.[0];
  if (f && f.type.startsWith("image/")) showPreview(f);
});

/* ============================ view mode ============================ */
$("viewMode").addEventListener("change", (e) => {
  const classificationOnly = e.target.value === "Classification only";
  $("cardXai").hidden = classificationOnly;
  $("cardSim").hidden = classificationOnly;
  $("cardLesion").hidden = classificationOnly;
});

/* ======================= the backend seam ========================= */
async function analyzeImage({ patientId, eye, file }) {
  // ---- REAL BACKEND: uncomment when /api/analyze is live ----
  // const fd = new FormData();
  // fd.append("patient_id", patientId);
  // fd.append("eye", eye);
  // fd.append("image", file);
  // const res = await fetch(`${API_BASE}/api/analyze`, { method: "POST", body: fd });
  // if (!res.ok) throw new Error(`Analysis failed (${res.status})`);
  // return await res.json();

  // ---- DEMO MOCK: remove when backend is wired ----
  await delay(1600);
  const original = file ? URL.createObjectURL(file) : MOCK.xai.original_url;
  return { ...MOCK, xai: { ...MOCK.xai, original_url: original } };
}

/* ========================= submit / analyze ======================= */
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  formError.hidden = true;

  if (!selectedFile) {
    formError.textContent = "Upload a retinal fundus image to start analysis.";
    formError.hidden = false;
    return;
  }

  const patientId = $("patientId").value.trim() || "Unlabeled";
  const eye = selectedEye();

  // enter loading state (show result panel with overlay)
  app.dataset.state = "loading";
  uploadState.hidden = true;
  resultState.hidden = false;
  loading.hidden = false;
  eyeLabel.textContent = `${eye} eye`;
  $("startBtn").disabled = true;

  try {
    const data = await analyzeImage({ patientId, eye, file: selectedFile });
    renderResults(data, eye);
    app.dataset.state = "results";
    loading.hidden = true;
    newScreeningBtn.hidden = false;
  } catch (err) {
    // failure is a moment for direction, not mood
    app.dataset.state = "empty";
    resultState.hidden = true;
    uploadState.hidden = false;
    loading.hidden = true;
    formError.textContent = `${err.message}. Check the backend is running, then try again.`;
    formError.hidden = false;
  } finally {
    $("startBtn").disabled = false;
  }
});

/* ============================== render ============================= */
function renderResults(d, eye) {
  const c = d.classification;

  // main composited image (from backend)
  resultImage.src = d.result_image_url;
  eyeLabel.textContent = `${eye} eye`;

  // DR classification
  $("drGrade").textContent = `LEVEL ${c.grade}`;
  $("drLabel").textContent = GRADE_LABELS[c.grade] ?? "—";
  $("drConfidence").textContent = `${Math.round(c.confidence * 100)}%`;
  drawGauge(c.grade);

  // lesion counts
  $("cntMicro").textContent = d.lesions.microaneurysms;
  $("cntHem").textContent = d.lesions.hemorrhages;
  $("cntExu").textContent = d.lesions.exudates;

  // quality pills
  setPill($("qFocus"), d.quality.focus);
  setPill($("qIllum"), d.quality.illumination);
  setPill($("qFov"), d.quality.field_of_view);

  // lesion chart
  drawBars(d.lesions.detection_bars);

  // XAI thumbs
  setThumb($("xaiOriginal"), $("xaiOriginalWrap"), d.xai.original_url);
  setThumb($("xaiHeatmap"), $("xaiHeatmapWrap"), d.xai.heatmap_url);
  $("xaiCaption").textContent = `Key regions for Level ${c.grade} prediction highlighted`;

  // telemedicine
  const t = d.telemedicine;
  $("tmThroughput").textContent = `${t.throughput_per_hr}/hr`;
  $("tmCapacity").textContent = `${t.capacity_per_year.toLocaleString()}/yr`;
  $("tmLoad").textContent = `${t.current_load_pct}%`;
  $("tmLoadBar").style.width = `${t.current_load_pct}%`;

  // history
  drawHistory(d.history);

  // status bar
  $("sbQuality").textContent = d.quality.overall;
  $("sbMid").innerHTML = `<em>Enhanced:</em> ${d.quality.enhancement}`;
  $("sbGrade").textContent = `LEVEL ${c.grade}${c.referable ? " (Referable)" : ""}`;
}

function setPill(node, value) {
  node.textContent = value;
  node.className = "pill " + (/optimal|good|pass|excellent/i.test(value) ? "pill-ok"
    : /poor|fail|reject/i.test(value) ? "pill-warn" : "pill-idle");
}
function setThumb(img, wrap, url) {
  img.src = url; img.hidden = false;
  wrap.querySelector("span").style.display = "none";
}

/* ============================== charts ============================= */
function drawGauge(grade) {
  const svg = $("gauge");
  svg.innerHTML = "";
  const cx = 100, cy = 104, r = 84, w = 15;
  const colors = ["#3fa45a", "#8bc34a", "#f4c430", "#ef8c34", "#e0413a"];

  // 5 colored segments across 180° → 0°
  for (let i = 0; i < 5; i++) {
    const a0 = 180 - i * 36, a1 = 180 - (i + 1) * 36;
    let dstr = "";
    for (let a = a0; a >= a1; a -= 4) {
      const [x, y] = polar(cx, cy, r, a);
      dstr += (dstr ? "L" : "M") + x.toFixed(1) + " " + y.toFixed(1) + " ";
    }
    const [xe, ye] = polar(cx, cy, r, a1);
    dstr += `L${xe.toFixed(1)} ${ye.toFixed(1)}`;
    svg.appendChild(el("path", { d: dstr, fill: "none", stroke: colors[i],
      "stroke-width": w, "stroke-linecap": i === 0 || i === 4 ? "round" : "butt" }));
  }

  // needle
  const t = Math.max(0, Math.min(4, grade ?? 0));
  const ang = 180 - (t / 4) * 180;
  const [nx, ny] = polar(cx, cy, r - 22, ang);
  svg.appendChild(el("line", { x1: cx, y1: cy, x2: nx.toFixed(1), y2: ny.toFixed(1),
    stroke: "#243040", "stroke-width": 3.5, "stroke-linecap": "round" }));
  svg.appendChild(el("circle", { cx, cy, r: 6, fill: "#243040" }));
}

function drawBars(values) {
  const svg = $("lesionChart");
  svg.innerHTML = "";
  const W = 260, H = 150, padL = 26, padB = 22, padT = 8;
  const base = H - padB, plotW = W - padL - 12, plotH = base - padT;
  const yMax = Math.max(16, ...values);

  // y grid + labels
  for (let g = 0; g <= yMax; g += 4) {
    const y = base - (g / yMax) * plotH;
    svg.appendChild(el("line", { x1: padL, y1: y, x2: W - 6, y2: y,
      stroke: "rgba(255,255,255,.28)", "stroke-width": 1 }));
    const tx = document.createElementNS(svgNS, "text");
    tx.setAttribute("x", padL - 6); tx.setAttribute("y", y + 3);
    tx.setAttribute("text-anchor", "end"); tx.setAttribute("font-size", "9");
    tx.setAttribute("fill", "rgba(255,255,255,.85)"); tx.textContent = g;
    svg.appendChild(tx);
  }
  // bars
  const n = values.length, slot = plotW / n, bw = slot * 0.5;
  values.forEach((v, i) => {
    const h = (v / yMax) * plotH;
    const x = padL + i * slot + (slot - bw) / 2;
    svg.appendChild(el("rect", { x, y: base - h, width: bw, height: h, rx: 2,
      fill: "rgba(255,255,255,.92)" }));
    const tx = document.createElementNS(svgNS, "text");
    tx.setAttribute("x", x + bw / 2); tx.setAttribute("y", base + 14);
    tx.setAttribute("text-anchor", "middle"); tx.setAttribute("font-size", "9");
    tx.setAttribute("fill", "rgba(255,255,255,.85)"); tx.textContent = i + 1;
    svg.appendChild(tx);
  });
}

function drawHistory(points) {
  $("historyEmpty").hidden = true;
  const svg = $("historyChart");
  svg.hidden = false;
  svg.innerHTML = "";
  const W = 520, H = 130, padL = 26, padR = 12, padB = 20, padT = 12;
  const base = H - padB, plotW = W - padL - padR, plotH = base - padT, gMax = 4;

  for (let g = 0; g <= gMax; g++) {
    const y = base - (g / gMax) * plotH;
    svg.appendChild(el("line", { x1: padL, y1: y, x2: W - padR, y2: y,
      stroke: "rgba(38,50,65,.12)", "stroke-width": 1 }));
    const tx = document.createElementNS(svgNS, "text");
    tx.setAttribute("x", padL - 6); tx.setAttribute("y", y + 3);
    tx.setAttribute("text-anchor", "end"); tx.setAttribute("font-size", "9");
    tx.setAttribute("fill", "#5b6875"); tx.textContent = g;
    svg.appendChild(tx);
  }
  const n = points.length;
  const xOf = (i) => padL + (n === 1 ? plotW / 2 : (i / (n - 1)) * plotW);
  const yOf = (g) => base - (g / gMax) * plotH;

  let dstr = "";
  points.forEach((p, i) => { dstr += (i ? "L" : "M") + xOf(i).toFixed(1) + " " + yOf(p.grade).toFixed(1) + " "; });
  svg.appendChild(el("path", { d: dstr, fill: "none", stroke: "#3d7cc0", "stroke-width": 2.5,
    "stroke-linejoin": "round", "stroke-linecap": "round" }));

  points.forEach((p, i) => {
    svg.appendChild(el("circle", { cx: xOf(i), cy: yOf(p.grade), r: 3.5, fill: "#3d7cc0" }));
    const tx = document.createElementNS(svgNS, "text");
    tx.setAttribute("x", xOf(i)); tx.setAttribute("y", base + 14);
    tx.setAttribute("text-anchor", "middle"); tx.setAttribute("font-size", "9");
    tx.setAttribute("fill", "#5b6875"); tx.textContent = p.t;
    svg.appendChild(tx);
  });
}

/* ============================== reset ============================= */
function resetToStart() {
  app.dataset.state = "empty";
  resultState.hidden = true;
  uploadState.hidden = false;
  loading.hidden = true;
  newScreeningBtn.hidden = true;
  formError.hidden = true;
  clearPreview();
  $("patientId").value = "";
  // reset panels to pending
  $("drGrade").textContent = "—";
  $("drLabel").textContent = "DR Scale (grade pending…)";
  $("drConfidence").textContent = "—%";
  $("cntMicro").textContent = "0"; $("cntHem").textContent = "0"; $("cntExu").textContent = "0";
  ["qFocus", "qIllum"].forEach((id) => { const p = $(id); p.textContent = "pending"; p.className = "pill pill-idle"; });
  const fov = $("qFov"); fov.textContent = "Not assessed"; fov.className = "pill pill-idle";
  $("tmThroughput").textContent = "—"; $("tmCapacity").textContent = "—"; $("tmLoad").textContent = "—";
  $("tmLoadBar").style.width = "0%";
  $("xaiCaption").textContent = "Heatmaps will appear after processing";
  ["xaiOriginal", "xaiHeatmap"].forEach((id) => { const im = $(id); im.hidden = true; im.removeAttribute("src"); });
  $("xaiOriginalWrap").querySelector("span").style.display = "";
  $("xaiHeatmapWrap").querySelector("span").style.display = "";
  $("sbQuality").textContent = "Not assessed";
  $("sbMid").innerHTML = "<em>Ready for input</em>";
  $("sbGrade").textContent = "Pending";
  $("historyEmpty").hidden = false;
  $("historyChart").hidden = true;
  drawGauge(0);
  drawBars([0, 0, 0, 0, 0]);
}

newScreeningBtn.addEventListener("click", resetToStart);

/* navigation (only Dashboard is functional in this frontend) */
document.querySelectorAll(".nav-item").forEach((btn) =>
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav-item").forEach((b) => b.classList.remove("is-active"));
    btn.classList.add("is-active");
    if (btn.dataset.nav === "dashboard") resetToStart();
  }));

/* ============================== init ============================= */
drawGauge(0);
drawBars([0, 0, 0, 0, 0]);
