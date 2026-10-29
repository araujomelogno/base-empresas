// ════════════════════════════════════════════════════════════════
//  Utilidades de interfaz (mismo estilo que la app de fichaje)
// ════════════════════════════════════════════════════════════════
import * as api from './api.js';

export const TZ = (window.APP_CONFIG || {}).tz || 'America/Montevideo';
export const $ = (sel, ctx = document) => ctx.querySelector(sel);
export const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];
export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const main = () => document.getElementById('main');

export function initials(name, email) {
  const src = (name || email || '?').trim();
  const parts = src.split(/[\s.@]+/).filter(Boolean);
  return (parts.length >= 2 ? parts[0][0] + parts[1][0] : src.slice(0, 2)).toUpperCase();
}

export function toast(msg, type = '') {
  const w = document.getElementById('toast-wrap');
  const t = document.createElement('div');
  t.className = 'toast ' + type;
  t.innerHTML = `<span>${type === 'ok' ? '✅' : type === 'err' ? '⚠️' : 'ℹ️'}</span><span>${esc(msg)}</span>`;
  w.appendChild(t);
  setTimeout(() => { t.style.opacity = '0'; t.style.transform = 'translateY(8px)'; t.style.transition = 'all .25s'; setTimeout(() => t.remove(), 260); }, 4200);
}

export const num = (n) => (n === null || n === undefined || n === '') ? '—' : Number(n).toLocaleString('es-UY');
export const pct = (a, b) => b ? (100 * a / b).toLocaleString('es-UY', { maximumFractionDigits: 1 }) + '%' : '—';
export function fecha(s) {
  if (!s) return '—';
  const d = new Date(s.length === 10 ? s + 'T12:00:00' : s);
  return d.toLocaleDateString('es-UY', { timeZone: TZ, day: '2-digit', month: '2-digit', year: 'numeric' });
}
export function fechaHora(s) {
  if (!s) return '—';
  return new Date(s).toLocaleString('es-UY', { timeZone: TZ, day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}
export const rutFmt = (r) => r && r.length === 12 ? `${r.slice(0, 2)}.${r.slice(2, 5)}.${r.slice(5, 8)}.${r.slice(8, 11)}-${r[11]}` : (r || '');

const ETIQUETAS = {
  sin_verificar: 'sin verificar', no_corresponde: 'no corresponde', en_curso: 'en curso', fuera_de_marco: 'fuera de marco',
  no_contactable: 'no contactable', en_proceso: 'en proceso', naturaleza_excluida: 'naturaleza excluida', no_llamar: 'no llamar',
  muestra_activa: 'en muestra activa', sin_telefono_discable: 'sin teléfono discable', enfriamiento: 'enfriamiento',
  actualizar_candidata: 'actualizó candidata', no_disponible: 'no disponible',
  vinculo: 'estado de vínculo teléfono–empresa', estado_parte: 'estado de la parte', tel_alt_nuevo: 'teléfono alternativo nuevo',
  tel_usado_nuevo: 'teléfono usado nuevo', contacto_nuevo: 'contacto nuevo', empresa_cerrada: 'empresa marcada cerrada',
  calidad_sin_telefono: 'calidad informada sin teléfono usado', intermediario_confirmado: 'intermediario confirmado por la sala',
  ultimo_contacto_efectivo: 'último contacto efectivo actualizado', total_excluidas: 'total excluidas (sin repetir)',
  baja: 'dada de baja', cerrada: 'empresa cerrada',
};
export const etiqueta = (s) => ETIQUETAS[s] || String(s ?? '').replace(/_/g, ' ');
export const est = (s, texto) => `<span class="est est-${esc(s)}">${esc(texto ?? etiqueta(s))}</span>`;

export function pageHeader(titulo, acento, sub, acciones = '') {
  return `<div class="page-header"><div class="accent-bar"></div>
    <div class="header-row"><div><h2>${esc(titulo)} <span class="accent">${esc(acento || '')}</span></h2><p>${sub || ''}</p></div>
    <div class="gap" id="ph-actions">${acciones}</div></div></div>`;
}

export function stats(items) {
  return `<div class="stat-grid">${items.map(([v, l, cls]) =>
    `<div class="stat ${cls || ''}"><div class="stat-num mono">${typeof v === 'number' ? num(v) : esc(v ?? '—')}</div><div class="stat-label">${esc(l)}</div></div>`).join('')}</div>`;
}

export function tabla(cols, filas, vacio = 'Sin datos') {
  if (!filas.length) return `<div class="empty-state"><span class="ei">🗂️</span>${esc(vacio)}</div>`;
  return `<div class="table-wrap"><table><thead><tr>${cols.map(c => `<th class="${c.cls || ''}">${esc(c.t)}</th>`).join('')}</tr></thead>
    <tbody>${filas.map((f, i) => `<tr ${f.__tr || ''}>${cols.map(c => `<td class="${c.cls || ''}">${c.f ? c.f(f, i) : esc(f[c.k])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}

export function card(titulo, cuerpo, acciones = '', tight = false) {
  return `<div class="card"><div class="card-header"><div class="card-header-title">${esc(titulo)}</div><div class="gap">${acciones}</div></div>
    <div class="card-body ${tight ? 'tight' : ''}">${cuerpo}</div></div>`;
}

export function cargando(el = main()) { el.innerHTML = `<div class="center-screen" style="min-height:40vh"><div class="spinner"></div></div>`; }

export function errorEn(el, e) {
  el.innerHTML = `<div class="alert alert-error">⚠️ ${esc(e.message || e)}</div>`;
}

// ── Modal ──
export function modal({ titulo, cuerpo, acciones = [], ancho }) {
  return new Promise((resolve) => {
    const b = document.createElement('div');
    b.className = 'modal-backdrop';
    b.innerHTML = `<div class="modal-box" style="${ancho ? `max-width:${ancho}px` : ''}"><div class="modal-head"><div class="modal-title">${esc(titulo)}</div>
      <button class="modal-close" data-x>×</button></div><div class="modal-body">${cuerpo}</div>
      <div class="modal-foot">${acciones.map((a, i) => `<button class="btn ${a.cls || 'btn-outline'}" data-i="${i}">${esc(a.t)}</button>`).join('')}</div></div>`;
    document.body.appendChild(b);
    const cerrar = (v) => { b.remove(); resolve(v); };
    b.querySelector('[data-x]').onclick = () => cerrar(null);
    b.onclick = (e) => { if (e.target === b) cerrar(null); };
    b.querySelectorAll('[data-i]').forEach(btn => btn.onclick = async () => {
      const a = acciones[+btn.dataset.i];
      if (!a.fn) return cerrar(a.valor ?? null);
      btn.disabled = true;
      try {
        const v = await a.fn(b);
        if (v !== false) cerrar(v ?? true);
      } catch (e) { toast(e.message, 'err'); } finally { btn.disabled = false; }
    });
    const primero = b.querySelector('input, select, textarea');
    if (primero) setTimeout(() => primero.focus(), 30);
  });
}

export async function confirmar(titulo, texto, boton = 'Confirmar', cls = 'btn-orange') {
  return modal({ titulo, cuerpo: `<p>${texto}</p>`, acciones: [{ t: 'Cancelar' }, { t: boton, cls, valor: true }] });
}

export async function pedirTexto(titulo, label, { obligatorio = true, placeholder = '' } = {}) {
  return modal({
    titulo, cuerpo: `<div class="form-group"><label>${esc(label)}</label><input type="text" id="m-txt" placeholder="${esc(placeholder)}" /></div>`,
    acciones: [{ t: 'Cancelar' }, {
      t: 'Aceptar', cls: 'btn-orange', fn: (b) => {
        const v = b.querySelector('#m-txt').value.trim();
        if (obligatorio && !v) { toast('Completá el campo', 'err'); return false; }
        return v || '';
      },
    }],
  });
}

// ── Tareas diferidas: barra de progreso hasta que terminan ──
export async function seguirTarea(tareaId, el, { texto = 'Procesando' } = {}) {
  for (;;) {
    const t = await api.get(`/tareas/${tareaId}`);
    const total = t.total || 0;
    const p = total ? Math.min(100, Math.round(100 * t.progreso / total)) : (t.estado === 'ok' ? 100 : 5);
    if (el) el.innerHTML = `<div class="progress"><span style="width:${p}%"></span></div>
      <div class="progress-label"><span>${esc(texto)}… ${est(t.estado)}</span><span class="mono">${total ? `${num(t.progreso)} / ${num(total)}` : ''}</span></div>`;
    if (t.estado === 'ok') return t;
    if (t.estado === 'error') throw new Error(t.error || 'La tarea falló');
    await new Promise(r => setTimeout(r, 900));
  }
}

// ── Barras horizontales de una sola serie, con valor y tooltip ──
export function barras(filas, { label, valor, formato = num } = {}) {
  if (!filas.length) return `<div class="empty-state">Sin datos en el período</div>`;
  const max = Math.max(...filas.map(f => f[valor])) || 1;
  return `<div class="bars" role="list">${filas.map(f => {
    const v = f[valor];
    return `<div class="bar-row" role="listitem" title="${esc(f[label])}: ${esc(formato(v))}"><div class="bl">${esc(f[label])}</div>
      <div class="bt"><span style="width:${Math.max(1, 100 * v / max)}%"></span></div><div class="bv">${esc(formato(v))}</div></div>`;
  }).join('')}</div>`;
}

export function columnas(filas, { label, valor }) {
  if (!filas.length) return `<div class="empty-state">Sin datos en el período</div>`;
  const max = Math.max(...filas.map(f => f[valor])) || 1;
  return `<div class="cols">${filas.map(f => `<div class="col" style="height:${Math.max(2, 100 * f[valor] / max)}%"
      title="${esc(fecha(f[label]))}: ${esc(num(f[valor]))} intentos"></div>`).join('')}</div>
    <div class="cols-labels"><span>${esc(fecha(filas[0][label]))}</span><span>máx. ${num(max)} por día</span><span>${esc(fecha(filas[filas.length - 1][label]))}</span></div>`;
}

export function chips(nombre, opciones, seleccion = []) {
  return `<div class="chips" data-chips="${esc(nombre)}">${opciones.map(o => {
    const [v, t] = Array.isArray(o) ? o : [o, o];
    return `<span class="chip ${seleccion.includes(v) ? 'on' : ''}" data-v="${esc(v)}">${esc(t)}</span>`;
  }).join('')}</div>`;
}
export function activarChips(ctx, onChange) {
  $$('[data-chips] .chip', ctx).forEach(c => c.onclick = () => { c.classList.toggle('on'); onChange && onChange(); });
}
export const chipsSel = (ctx, nombre) => $$(`[data-chips="${nombre}"] .chip.on`, ctx).map(c => c.dataset.v);

export function json(o) { return `<pre class="json">${esc(JSON.stringify(o, null, 2))}</pre>`; }

export function tabs(nombre, items, activo) {
  return `<div class="tabs" data-tabs="${nombre}">${items.map(([id, t]) => `<button class="tab ${id === activo ? 'active' : ''}" data-tab="${id}">${esc(t)}</button>`).join('')}</div>`;
}

export function archivoDrop(id, texto, accept) {
  return `<label class="file-drop" id="${id}-zona"><input type="file" id="${id}" accept="${accept}" />
    <div style="font-size:1.8rem">📄</div><div id="${id}-nombre">${esc(texto)}</div></label>`;
}
export function activarDrop(id, onFile) {
  const zona = document.getElementById(id + '-zona');
  const input = document.getElementById(id);
  const usar = (f) => { if (!f) return; document.getElementById(id + '-nombre').textContent = f.name; onFile(f); };
  input.onchange = () => usar(input.files[0]);
  zona.ondragover = (e) => { e.preventDefault(); zona.classList.add('over'); };
  zona.ondragleave = () => zona.classList.remove('over');
  zona.ondrop = (e) => { e.preventDefault(); zona.classList.remove('over'); usar(e.dataTransfer.files[0]); };
}
