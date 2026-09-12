
// ---- RetinaXplain / Streamlit bridge -------------------------------------
// The original dashboard expects POST /api/analyze and POST /api/report.
// Streamlit Cloud does not expose the old Flask port, so these requests are
// routed through a Streamlit Components v2 Python bridge instead.
const root = parentElement;
const document = parentElement.ownerDocument;
const RX = window.__retinaxplain_bridge || (window.__retinaxplain_bridge = {
  pending: new Map(),
  counter: 0,
});

function rxId(prefix) {
  RX.counter += 1;
  return `${prefix}-${Date.now()}-${RX.counter}-${Math.random().toString(36).slice(2,8)}`;
}

function bytesToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  const chunk = 0x8000;
  let binary = '';
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, Math.min(i + chunk, bytes.length)));
  }
  return btoa(binary);
}

function makeResponse(payload, status=200, headers={}) {
  const text = JSON.stringify(payload ?? {});
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (name) => headers[String(name).toLowerCase()] || null },
    json: async () => payload ?? {},
    text: async () => text,
    blob: async () => {
      const b64 = payload?.pdf_base64 || '';
      const binary = atob(b64);
      const arr = new Uint8Array(binary.length);
      for (let i=0;i<binary.length;i++) arr[i] = binary.charCodeAt(i);
      return new Blob([arr], {type: payload?.mime || 'application/pdf'});
    },
  };
}

async function bridgeFetch(input, init={}) {
  const url = typeof input === 'string' ? input : (input?.url || '');
  if (!url.includes('/api/analyze') && !url.includes('/api/report')) {
    return window.fetch(input, init);
  }

  const id = rxId(url.includes('/api/analyze') ? 'analyze' : 'report');
  let request;
  if (url.includes('/api/analyze')) {
    const fd = init.body;
    const file = fd?.get('image');
    if (!file) return makeResponse({error:'No image file uploaded'}, 400);
    request = {
      id,
      type: 'analyze',
      patient_id: fd.get('patient_id') || 'Unlabeled',
      eye: fd.get('eye') || 'Right',
      filename: file.name || 'fundus.jpg',
      mime: file.type || 'image/jpeg',
      image_base64: bytesToBase64(await file.arrayBuffer()),
    };
  } else {
    let parsed = {};
    try { parsed = JSON.parse(init.body || '{}'); } catch (_) {}
    request = {id, type:'report', payload: parsed};
  }

  const promise = new Promise((resolve) => RX.pending.set(id, resolve));
  setTriggerValue('bridge_request', request);
  return promise;
}

// Resolve a pending browser promise after Python has handled a request.
if (data?.bridge_response?.id && RX.pending.has(data.bridge_response.id)) {
  const response = data.bridge_response;
  RX.pending.get(response.id)(makeResponse(response.body, response.status || 200));
  RX.pending.delete(response.id);
}

/* ORIGINAL_SCRIPT */
