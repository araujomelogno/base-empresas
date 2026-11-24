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
    if (j.codigo) datos = { codigo: j.codigo, reintentar: !!j.reintentar };  // D55: 503 «base ocupada» / «consulta lenta»
    if (j.detail && !Array.isArray(j.detail) && typeof j.detail === 'object') {  // {mensaje, ...datos}
      datos = j.detail;
      detail = j.detail.mensaje || detail;
    } else {
      detail = typeof j.detail === 'string' ? j.detail : (j.detail || []).map(d => `${(d.loc || []).slice(1).join('.')}: ${d.msg}`).join('; ') || detail;
    }
  } catch { /* respuesta sin JSON */ }
  throw new ApiError(r.status, detail, datos);
}

export async function get(path, params, reintento = false) {
  const q = params ? '?' + new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')) : '';
  try {
    return await manejar(await fetch(BASE + path + q, { headers: await headers() }));
  } catch (e) {
    // D55: «La base está ocupada»: un reintento solo, a los 1,5 s; si vuelve a pasar, se muestra el mensaje tal cual
    if (!reintento && e instanceof ApiError && e.status === 503 && e.datos && e.datos.reintentar) {
      await new Promise(ok => setTimeout(ok, 1500));
      return get(path, params, true);
    }
    throw e;
  }
}

// D55: estado de la base (/estado, cada 30 s): carga en curso y fecha de los resúmenes
export let estadoBase = null;
export function setEstadoBase(e) { estadoBase = e; }

// Los valores de los filtros se guardan en el navegador 10 minutos, o hasta que cambia su fecha en el resumen
const CLAVE_VALORES = 'valoresFiltros';
export async function valores() {
  let c = null;
  try { c = JSON.parse(localStorage.getItem(CLAVE_VALORES) || 'null'); } catch { c = null; }
  const fecha = estadoBase && estadoBase.resumen ? estadoBase.resumen.valores : null;
  if (c && c.datos && Date.now() - c.t < 10 * 60 * 1000 && (!fecha || fecha === c.datos.actualizado)) return c.datos;
  const datos = await get('/empresas/valores');
  try { localStorage.setItem(CLAVE_VALORES, JSON.stringify({ t: Date.now(), datos })); } catch { /* sin almacenamiento */ }
  return datos;
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
