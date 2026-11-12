// ════════════════════════════════════════════════════════════════
//  Cliente de la API: agrega el token de Firebase (o el usuario dev)
// ════════════════════════════════════════════════════════════════
const CFG = window.APP_CONFIG || {};
const BASE = (CFG.apiBase || '/api').replace(/\/$/, '');
let _token = async () => null;

export function setTokenProvider(fn) { _token = fn; }

async function headers(extra = {}) {
  const h = { ...extra };
  if (CFG.authMode === 'dev') {
    const u = localStorage.getItem('devUser');
    if (u) h['X-Dev-User'] = u;
  } else {
    const t = await _token();
    if (t) h['Authorization'] = 'Bearer ' + t;
  }
  return h;
}

export class ApiError extends Error {
  constructor(status, detail, datos) { super(detail); this.status = status; this.datos = datos || null; }
}

async function manejar(r) {
  if (r.ok) {
    const ct = r.headers.get('content-type') || '';
    return ct.includes('application/json') ? r.json() : r;
  }
  let detail = r.statusText, datos = null;
  try {
    const j = await r.json();
    if (j.detail && !Array.isArray(j.detail) && typeof j.detail === 'object') {  // {mensaje, ...datos}
      datos = j.detail;
      detail = j.detail.mensaje || detail;
    } else {
      detail = typeof j.detail === 'string' ? j.detail : (j.detail || []).map(d => `${(d.loc || []).slice(1).join('.')}: ${d.msg}`).join('; ') || detail;
    }
  } catch { /* respuesta sin JSON */ }
  throw new ApiError(r.status, detail, datos);
}

export async function get(path, params) {
  const q = params ? '?' + new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')) : '';
  return manejar(await fetch(BASE + path + q, { headers: await headers() }));
}

export async function send(method, path, body) {
  return manejar(await fetch(BASE + path, {
    method, headers: await headers({ 'Content-Type': 'application/json' }),
    body: body === undefined ? undefined : JSON.stringify(body),
  }));
}
export const post = (p, b) => send('POST', p, b ?? {});
export const put = (p, b) => send('PUT', p, b);
export const patch = (p, b) => send('PATCH', p, b);
export const del = (p) => send('DELETE', p);

export async function upload(path, file, fields = {}) {
  const fd = new FormData();
  fd.append('archivo', file);
  Object.entries(fields).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== '') fd.append(k, v); });
  return manejar(await fetch(BASE + path, { method: 'POST', headers: await headers(), body: fd }));
}

export async function descargar(path, params) {
  const q = params ? '?' + new URLSearchParams(params) : '';
  const r = await manejar(await fetch(BASE + path + q, { headers: await headers() }));
  const blob = await r.blob();
  const cd = r.headers.get('content-disposition') || '';
  const nombre = (cd.match(/filename="([^"]+)"/) || [])[1] || 'descarga';
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = nombre;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  return { nombre, headers: r.headers };
}
