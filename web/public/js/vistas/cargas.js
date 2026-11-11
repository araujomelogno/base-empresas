// Cargas de bases, intermediarios y revisión de fusiones (R1.2, R1.3)
import * as api from '../api.js';
import { $, $$, esc, main, toast, num, fecha, fechaHora, rutFmt, est, etiqueta, pageHeader, stats, tabla, card, modal,
  pedirTexto, confirmar, seguirTarea, archivoDrop, activarDrop, tabs } from '../ui.js';
import { actualizarContadores } from '../app.js';

const CAMPOS = {
  rut: 'RUT', razon_social: 'Razón social', fantasia: 'Nombre de fantasía', naturaleza: 'Naturaleza jurídica (código o nombre)',
  ciiu: 'CIIU / rubro', tamano: 'Tamaño', departamento: 'Departamento', localidad: 'Localidad', direccion: 'Dirección', web: 'Web',
  email: 'Email (para el dominio)', estado: 'Estado (activa / cerrada)',
  sucursal_direccion: 'Dirección de la sucursal', sucursal_departamento: 'Departamento de la sucursal', sucursal_localidad: 'Localidad de la sucursal',
};
const REGLAS = { rut: 'RUT (por defecto)', telefono: 'Teléfono', razon_social: 'Razón social normalizada', dominio: 'Dominio web' };
// C10: qué significa cada estado y qué sigue
export const ESTADOS_CARGA = {
  analizando: ['El sistema está leyendo el archivo y calculando el preview.', 'Esperar; la barra muestra el avance.'],
  preview: ['Los conteos están listos. Todavía no se escribió nada en la base.', 'Revisar y Confirmar, o Descartar.'],
  en_proceso: ['Se está aplicando a la base.', 'Esperar.'],
  confirmada: ['Aplicada a la base.', 'Se puede Deshacer mientras ninguna de sus empresas haya entrado a una muestra.'],
  descartada: ['Se revisó y no se aplicó.', 'Nada; queda como registro.'],
  deshecha: ['Se aplicó y después se anuló; la historia queda tachada.', 'Nada.'],
  error: ['Falló el análisis o la aplicación; abajo está el motivo.', 'Corregir el archivo o el mapeo y hacer una carga nueva.'],
};
const estCarga = (e) => `<span title="${esc(ESTADOS_CARGA[e] ? ESTADOS_CARGA[e].join(' ') : '')}">${est(e)}</span>`;

export async function lista(ctx) {
  const cargas = await api.get('/cargas');
  main().innerHTML = pageHeader('Cargas', 'de bases', 'Cada carga es un lote con fuente, responsable y licencia. Se puede deshacer mientras ninguna de sus empresas haya entrado a una muestra.',
    ctx.puede('steward') ? `<button class="btn btn-orange" id="c-nueva">+ Nueva carga</button>` : '') +
    card('Historial de cargas', tabla([
      { t: '#', f: c => `<a class="link" href="#/cargas/${c.id}">${c.id}</a>` },
      { t: 'Fuente', f: c => `<span class="td-strong">${esc(c.fuente)}</span><div class="small muted">${esc(c.archivo_nombre)}</div>` },
      { t: 'Tipo', k: 'tipo_fuente' }, { t: 'Fusión', f: c => esc(REGLAS[c.regla_fusion] || c.regla_fusion) }, { t: 'Estado', f: c => estCarga(c.estado) },
      { t: 'Altas', cls: 'num', f: c => num(c.conteos.altas || 0) }, { t: 'Act.', cls: 'num', f: c => num(c.conteos.actualizaciones || 0) },
      { t: 'Rechazos', cls: 'num', f: c => num(c.conteos.rechazos || 0) }, { t: 'Responsable', k: 'responsable' }, { t: 'Fecha', f: c => fechaHora(c.fecha) },
    ], cargas, 'Todavía no hay cargas'), '', true) +
    `<p class="small muted mt">Pasá el mouse por el estado para ver qué significa y qué sigue.</p>`;
  if ($('#c-nueva')) $('#c-nueva').onclick = () => ctx.ir('cargas/nueva');
}

function pasos(n) {
  return `<div class="steps">${['Archivo', 'Mapeo', 'Preview', 'Confirmación'].map((t, i) =>
    `<div class="step ${i + 1 === n ? 'on' : i + 1 < n ? 'done' : ''}"><span class="n">${i + 1 < n ? '✓' : i + 1}</span>${t}</div>`).join('')}</div>`;
}

export async function nueva(ctx) {
  const [plantillas, cfg] = await Promise.all([api.get('/cargas/plantillas'), api.get('/config')]);
  main().innerHTML = pageHeader('Nueva', 'carga', 'Subí un Excel, CSV o .sav de empresas. Nada se escribe en la base hasta que confirmes.') + pasos(1) +
    card('1 · Archivo', `<div class="form-row">
      <div>${archivoDrop('c-arch', 'Arrastrá el archivo o tocá para elegirlo (.xlsx, .csv, .sav)', '.xlsx,.csv,.txt,.sav')}</div>
      <div><div class="form-group"><label>Tipo de fuente</label><input type="text" id="c-tipo" list="c-tipos" placeholder="p. ej. padrón DGI, estudio clima 2025" />
        <datalist id="c-tipos">${plantillas.map(p => `<option value="${esc(p.tipo_fuente)}">`).join('')}</datalist>
        <div class="field-hint">El mapeo de columnas y las traducciones de valores se guardan como plantilla por tipo de fuente y se reusan en la próxima carga.</div></div>
        <button class="btn btn-orange" id="c-analizar" disabled>Analizar archivo</button></div></div>`) + `<div id="c-paso2"></div>`;
  let archivo = null;
  activarDrop('c-arch', (f) => { archivo = f; $('#c-analizar').disabled = false; });
  $('#c-analizar').onclick = async () => {
    $('#c-analizar').disabled = true;
    try {
      const a = await api.upload('/cargas/analizar', archivo, { tipo_fuente: $('#c-tipo').value.trim() });
      mapeo(ctx, a, $('#c-tipo').value.trim(), cfg.parametros);
    } catch (e) { toast(e.message, 'err'); $('#c-analizar').disabled = false; }
  };
}

// ── 2 · Mapeo (C3, C4) ──
function estadoInicial(a) {
  const m = a.mapeo || {};
  const st = { nucleo: {}, sucursal: {}, atributos: { ...(m.atributos || {}) }, tels: [], origen_defecto: m.origen_defecto || '',
    traducciones: m.traducciones || {} };
  a.campos.empresa.forEach(k => { if (m[k] || k === 'rut') st.nucleo[k] = m[k] || ''; });
  a.campos.sucursal.forEach(k => { st.sucursal[k] = m[k] || ''; });
  (m.telefonos || []).forEach(col => {
    const o = (m.origenes_telefono || {})[col] || {};
    st.tels.push({ col, origen: o.columna ? 'col:' + o.columna : o.fijo ? 'fijo:' + o.fijo : '' });
  });
  return st;
}

function mapeoDe(st) {
  const m = { telefonos: [], traducciones: st.traducciones };
  Object.entries({ ...st.nucleo, ...st.sucursal }).forEach(([k, v]) => { if (v) m[k] = v; });  // sin columna no se guarda
  const at = Object.fromEntries(Object.entries(st.atributos).filter(([, v]) => v));
  if (Object.keys(at).length) m.atributos = at;
  const ot = {};
  st.tels.filter(t => t.col).forEach(t => {
    m.telefonos.push(t.col);
    if (t.origen.startsWith('col:')) ot[t.col] = { columna: t.origen.slice(4) };
    else if (t.origen.startsWith('fijo:')) ot[t.col] = { fijo: t.origen.slice(5) };
  });
  if (Object.keys(ot).length) m.origenes_telefono = ot;
  if (st.origen_defecto) m.origen_defecto = st.origen_defecto;
  return m;
}

function columnasUsadas(m) {
  const u = new Set();
  Object.entries(m).forEach(([k, v]) => { if (typeof v === 'string' && CAMPOS[k]) u.add(v); });
  (m.telefonos || []).forEach(c => u.add(c));
  Object.values(m.origenes_telefono || {}).forEach(o => o.columna && u.add(o.columna));
  Object.values(m.atributos || {}).forEach(c => u.add(c));
  return u;
}

function mapeo(ctx, a, tipoFuente, params) {
  const st = estadoInicial(a);
  const atributos = Object.fromEntries(a.atributos.map(x => [x.clave, x]));
  const opts = (sel, vacio = '— no usar —') => `<option value="">${vacio}</option>` + a.columnas.map(c => `<option ${c === sel ? 'selected' : ''}>${esc(c)}</option>`).join('');
  const quitar = (attr, k) => `<button class="btn btn-outline btn-sm btn-del" ${attr}="${esc(k)}" title="Quitar">×</button>`;
  $('.steps').outerHTML = pasos(2);
  $('#c-paso2').innerHTML = card(`2 · Mapeo de columnas — ${a.nombre} (${num(a.n_filas)} filas)`, `
    <div class="alert alert-info"><span>Mapeo ${a.origen_mapeo === 'plantilla' ? `cargado de la plantilla <strong>${esc(tipoFuente)}</strong>` : 'sugerido por los nombres de columna'}.
      Se muestran solo los campos que se reconocieron en el archivo: <strong>todo es opcional salvo el RUT</strong>. Los demás se agregan con «+ Agregar».</span></div>
    ${(a.avisos || []).map(x => `<div class="alert alert-warn"><span>${esc(x)}</span></div>`).join('')}
    <div class="grid-2"><div id="c-bloques"></div>
    <div><div class="form-group"><label>Nombre de la fuente</label><input type="text" id="c-fuente" value="${esc(a.nombre.replace(/\.[^.]+$/, ''))}" /></div>
      <div class="form-group"><label>Licencia de uso</label><input type="text" id="c-licencia" placeholder="p. ej. base propia, uso interno" /></div>
      <div class="form-row"><div class="form-group"><label>Regla de fusión</label><select class="fselect" id="c-regla">${
        params.reglas_fusion.map(r => `<option value="${r}">${esc(REGLAS[r] || r)}</option>`).join('')}</select>
        <div class="field-hint">Las coincidencias que no son por RUT van a la bandeja de revisión.</div></div>
        <div class="form-group"><label>Confianza (0–100)</label><input type="number" id="c-conf" min="0" max="100" value="${params.confianza_fuentes.carga ?? 50}" /></div></div>
      <label class="check"><input type="checkbox" id="c-plantilla" checked /> Guardar el mapeo y las traducciones como plantilla de "${esc(tipoFuente || 'sin tipo')}"</label>
      <div class="mt"><button class="btn btn-orange" id="c-siguiente">Siguiente</button></div><div id="c-prog" class="mt"></div></div></div>`) +
    `<div id="c-traduccion"></div>` +
    card('Primeras filas del archivo', `<div class="table-wrap"><table><thead><tr>${a.columnas.map(c => `<th>${esc(c)}</th>`).join('')}</tr></thead>
      <tbody>${a.ejemplos.map(f => `<tr>${a.columnas.map(c => `<td>${esc(f[c] ?? '')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`, '', true);

  const dibujar = () => {
    const sinUsar = (obj, todos) => todos.filter(k => !(k in obj));
    const faltanNucleo = sinUsar(st.nucleo, a.campos.empresa);
    const faltanAttr = sinUsar(st.atributos, Object.keys(atributos));
    const origenOpts = (sel) => `<option value="" ${!sel ? 'selected' : ''}>Origen por defecto de la carga</option>
      <optgroup label="Columna del archivo">${a.columnas.map(c => `<option value="col:${esc(c)}" ${sel === 'col:' + c ? 'selected' : ''}>columna «${esc(c)}»</option>`).join('')}</optgroup>
      <optgroup label="Origen fijo">${a.origenes.map(o => `<option value="fijo:${esc(o.codigo)}" ${sel === 'fijo:' + o.codigo ? 'selected' : ''}>${esc(o.nombre)}</option>`).join('')}</optgroup>`;
    const m = mapeoDe(st);
    const noUsadas = a.columnas.filter(c => !columnasUsadas(m).has(c));
    $('#c-bloques').innerHTML = `
      <div class="map-bloque"><h4>1 · Empresa</h4><p class="field-hint">Los datos del registro maestro. Solo el RUT es obligatorio.</p>
        ${Object.keys(st.nucleo).map(k => `<div class="map-fila"><span class="td-strong">${esc(CAMPOS[k])}${k === 'rut' ? ' <span class="est est-error">obligatorio</span>' : ''}</span>
          <select class="fselect" data-nucleo="${k}">${opts(st.nucleo[k], k === 'rut' ? '— elegí la columna —' : '— no usar —')}</select>
          ${k === 'rut' ? '<span></span>' : quitar('data-quitar-nucleo', k)}</div>`).join('')}
        ${faltanNucleo.length ? `<div class="map-agregar"><select class="fselect" id="c-add-nucleo"><option value="">+ Agregar campo…</option>${
          faltanNucleo.map(k => `<option value="${k}">${esc(CAMPOS[k])}</option>`).join('')}</select></div>` : ''}</div>
      <div class="map-bloque"><h4>2 · Atributos</h4><p class="field-hint">Otros datos de la empresa definidos en Administración → Atributos (cantidad de empleados, exporta, cámara…).</p>
        ${Object.keys(st.atributos).map(k => `<div class="map-fila"><span class="td-strong">${esc(atributos[k].nombre)} <span class="small muted">${esc(atributos[k].tipo)}</span></span>
          <select class="fselect" data-attr="${esc(k)}">${opts(st.atributos[k])}</select>${quitar('data-quitar-attr', k)}</div>`).join('')}
        ${faltanAttr.length ? `<div class="map-agregar"><select class="fselect" id="c-add-attr"><option value="">+ Agregar atributo…</option>${
          faltanAttr.map(k => `<option value="${esc(k)}">${esc(atributos[k].nombre)}</option>`).join('')}</select></div>`
          : Object.keys(atributos).length ? '' : '<div class="small muted">No hay atributos activos. Un administrador los crea en Administración → Atributos.</div>'}</div>
      <div class="map-bloque"><h4>3 · Teléfonos</h4><p class="field-hint">Cada columna de teléfono con su origen: una columna del archivo que lo dice (puede ser la misma para todas) o un origen fijo. Una celda puede traer varios números separados por / ; o ,</p>
        ${st.tels.map((t, i) => `<div class="map-fila tel"><select class="fselect" data-tel="${i}">${opts(t.col, '— columna —')}</select>
          <select class="fselect" data-tel-origen="${i}">${origenOpts(t.origen)}</select>${quitar('data-quitar-tel', i)}</div>`).join('')}
        <div class="map-agregar"><button class="btn btn-outline btn-sm" id="c-add-tel">+ Agregar columna de teléfono</button></div>
        <div class="form-group mt"><label>Origen por defecto de la carga ${st.tels.length ? '<span class="est est-error">obligatorio</span>' : ''}</label>
          <select class="fselect" id="c-origen-defecto"><option value="">— elegí el origen —</option>${a.origenes.map(o => `<option value="${esc(o.codigo)}" ${o.codigo === st.origen_defecto ? 'selected' : ''}>${esc(o.nombre)}</option>`).join('')}</select>
          <div class="field-hint">Se usa para las columnas sin origen propio y cuando la columna de origen viene vacía en una fila.</div></div></div>
      <details class="map-bloque" ${Object.values(st.sucursal).some(Boolean) ? 'open' : ''}><summary>4 · Sucursal (opcional)</summary>
        <p class="field-hint">Un local de la empresa con dirección distinta de la fiscal. Si se completa, los teléfonos de la fila quedan asociados a esa sucursal.</p>
        ${Object.keys(st.sucursal).map(k => `<div class="map-fila"><span class="td-strong">${esc(CAMPOS[k])}</span><select class="fselect" data-suc="${k}">${opts(st.sucursal[k])}</select><span></span></div>`).join('')}</details>
      <div class="no-usadas">${noUsadas.length ? `<strong>Columnas que no se van a cargar:</strong> ${noUsadas.map(esc).join(', ')}` : 'Se usan todas las columnas del archivo.'}</div>`;
    $$('[data-nucleo]').forEach(s => s.onchange = () => { st.nucleo[s.dataset.nucleo] = s.value; dibujar(); });
    $$('[data-quitar-nucleo]').forEach(b => b.onclick = () => { delete st.nucleo[b.dataset.quitarNucleo]; dibujar(); });
    if ($('#c-add-nucleo')) $('#c-add-nucleo').onchange = (e) => { st.nucleo[e.target.value] = ''; dibujar(); };
    $$('[data-attr]').forEach(s => s.onchange = () => { st.atributos[s.dataset.attr] = s.value; dibujar(); });
    $$('[data-quitar-attr]').forEach(b => b.onclick = () => { delete st.atributos[b.dataset.quitarAttr]; dibujar(); });
    if ($('#c-add-attr')) $('#c-add-attr').onchange = (e) => { st.atributos[e.target.value] = ''; dibujar(); };
    $$('[data-tel]').forEach(s => s.onchange = () => { st.tels[+s.dataset.tel].col = s.value; dibujar(); });
    $$('[data-tel-origen]').forEach(s => s.onchange = () => { st.tels[+s.dataset.telOrigen].origen = s.value; dibujar(); });
    $$('[data-quitar-tel]').forEach(b => b.onclick = () => { st.tels.splice(+b.dataset.quitarTel, 1); dibujar(); });
    $('#c-add-tel').onclick = () => { st.tels.push({ col: '', origen: '' }); dibujar(); };
    $('#c-origen-defecto').onchange = (e) => { st.origen_defecto = e.target.value; };
    $$('[data-suc]').forEach(s => s.onchange = () => { st.sucursal[s.dataset.suc] = s.value; dibujar(); });
  };
  dibujar();

  const crear = async () => {
    const m = mapeoDe(st);
    $('#c-siguiente').disabled = true;
    try {
      const r = await api.post('/cargas', {
        archivo_id: a.archivo_id, fuente: $('#c-fuente').value.trim() || a.nombre, tipo_fuente: tipoFuente || 'sin tipo',
        licencia: $('#c-licencia').value.trim(), regla_fusion: $('#c-regla').value, confianza: +$('#c-conf').value,
        mapeo: m, guardar_plantilla: $('#c-plantilla').checked,
      });
      await seguirTarea(r.tarea_id, $('#c-prog'), { texto: 'Calculando el preview' });
      ctx.ir('cargas/' + r.carga_id);
    } catch (e) { toast(e.message, 'err'); $('#c-siguiente').disabled = false; }
  };

  $('#c-siguiente').onclick = async () => {
    const m = mapeoDe(st);
    if (!m.rut) return toast('Indicá la columna del RUT', 'err');
    if (m.telefonos.length && !m.origen_defecto) return toast('Elegí el origen por defecto de los teléfonos', 'err');
    if (!$('#c-licencia').value.trim()) return toast('Indicá la licencia de uso de la fuente', 'err');
    try {
      const v = await api.post('/cargas/valores', { archivo_id: a.archivo_id, mapeo: m });
      if (!v.origen.length && !v.atributos.length) { $('#c-traduccion').innerHTML = ''; return crear(); }
      traduccion(ctx, a, st, v, crear);
    } catch (e) { toast(e.message, 'err'); }
  };
}

// ── Traducción de valores (C5) ──
function traduccion(ctx, a, st, v, crear) {
  const admin = ctx.puede('admin');
  const origenes = [...a.origenes];
  const grupos = [];
  if (v.origen.length) grupos.push({ clave: 'origen', titulo: 'Origen del teléfono', valores: v.origen,
    opciones: () => origenes.map(o => [o.codigo, o.nombre]) });
  v.atributos.forEach(x => grupos.push({ clave: 'atributo.' + x.clave, titulo: x.nombre, valores: x.valores, atributo: x,
    opciones: () => x.opciones.map(o => [o, o]) }));
  const sel = (g, x, i) => {
    const actual = x.traducido ? (x.traduccion === null ? '__sin_dato' : x.traduccion) : '';
    return `<select class="fselect" data-tr="${esc(g.clave)}" data-i="${i}"><option value="">— elegí —</option>
      ${g.opciones().map(([val, t]) => `<option value="${esc(val)}" ${actual === val ? 'selected' : ''}>${esc(t)}</option>`).join('')}
      <option value="__sin_dato" ${actual === '__sin_dato' ? 'selected' : ''}>Sin dato</option>
      ${admin ? '<option value="__nuevo">+ Crear uno nuevo…</option>' : ''}</select>`;
  };
  const nombreDe = (g, val) => (g.opciones().find(o => o[0] === val) || [val, val])[1];
  const dibujar = () => {
    $('#c-traduccion').innerHTML = card('Traducción de valores', `<div class="alert alert-info"><span>El archivo trae valores que no coinciden exactamente con el catálogo.
      Elegí a qué corresponde cada uno: un valor del catálogo${admin ? ', uno nuevo' : ''} o «sin dato». Las sugerencias no se aplican solas: tocá «Usar sugerencias» o elegí una por una.
      La traducción queda en la plantilla del tipo de fuente.</span></div>
      ${grupos.map(g => `<div class="card-header-title mb mt">${esc(g.titulo)}</div>${tabla([
        { t: 'Valor en el archivo', f: x => `<span class="td-strong">${esc(x.valor)}</span>` }, { t: 'Filas', cls: 'num', f: x => num(x.filas) },
        { t: 'Sugerido', f: x => x.sugerido ? esc(nombreDe(g, x.sugerido)) : '<span class="muted">—</span>' },
        { t: 'Traducir a', f: (x, i) => sel(g, x, i) }], g.valores)}`).join('')}
      <div class="mt gap"><button class="btn btn-outline" id="c-sugerencias">Usar sugerencias</button>
      <button class="btn btn-orange" id="c-preview">Ver preview</button></div>`);
    $$('[data-tr]').forEach(s => s.onchange = async () => {
      const g = grupos.find(x => x.clave === s.dataset.tr);
      const x = g.valores[+s.dataset.i];
      if (s.value === '__nuevo') {
        const nombre = await pedirTexto(g.atributo ? `Nueva opción de ${g.titulo}` : 'Nuevo origen de teléfono', 'Nombre', { placeholder: x.valor });
        if (!nombre) { s.value = ''; return; }
        try {
          if (g.atributo) {
            await api.put('/atributos/' + a.atributos.find(t => t.clave === g.atributo.clave).id, { opciones: [...g.atributo.opciones, nombre] });
            g.atributo.opciones.push(nombre);
            Object.assign(x, { traducido: true, traduccion: nombre });
          } else {
            const o = await api.post('/origenes-telefono', { nombre });
            origenes.push(o); a.origenes.push(o);
            Object.assign(x, { traducido: true, traduccion: o.codigo });
          }
          toast(`«${nombre}» agregado al catálogo`, 'ok');
        } catch (e) { toast(e.message, 'err'); s.value = ''; return; }
        return dibujar();
      }
      Object.assign(x, { traducido: !!s.value, traduccion: s.value === '__sin_dato' ? null : s.value || null });
    });
    $('#c-sugerencias').onclick = () => {
      grupos.forEach(g => g.valores.forEach(x => { if (!x.traducido && x.sugerido) Object.assign(x, { traducido: true, traduccion: x.sugerido }); }));
      dibujar();
    };
    $('#c-preview').onclick = () => {
      const faltan = grupos.reduce((n, g) => n + g.valores.filter(x => !x.traducido).length, 0);
      if (faltan) return toast(`Faltan ${faltan} valores por traducir (elegí «Sin dato» si no corresponden a ninguno)`, 'err');
      grupos.forEach(g => {
        st.traducciones[g.clave] = { ...(st.traducciones[g.clave] || {}) };
        g.valores.forEach(x => { st.traducciones[g.clave][x.valor] = x.traduccion; });
      });
      $('#c-preview').disabled = true;
      crear().finally(() => { if ($('#c-preview')) $('#c-preview').disabled = false; });
    };
  };
  dibujar();
  $('#c-traduccion').scrollIntoView({ behavior: 'smooth' });
}

const PASO_DE = { analizando: 3, preview: 3, en_proceso: 4, confirmada: 5, deshecha: 5, descartada: 3, error: 3 };

export async function detalle(ctx, id) {
  const [c, origenes, atributos] = await Promise.all([api.get('/cargas/' + id), api.get('/origenes-telefono'), api.get('/atributos')]);
  const k = c.conteos || {};
  const nombreO = Object.fromEntries(origenes.map(o => [o.codigo, o.nombre]));
  const nombreA = Object.fromEntries(atributos.map(a => [a.clave, a.nombre]));
  const enCurso = ['analizando', 'en_proceso'].includes(c.estado);
  const [significa, sigue] = ESTADOS_CARGA[c.estado] || ['', ''];
  const acciones = [
    c.estado === 'preview' && ctx.puede('steward') ? `<button class="btn btn-green" id="c-confirmar">Confirmar carga</button>` : '',
    ['preview', 'error'].includes(c.estado) && ctx.puede('steward') ? `<button class="btn btn-outline" id="c-descartar">Descartar</button>` : '',
    c.estado === 'confirmada' && ctx.puede('steward') ? `<button class="btn btn-outline btn-del" id="c-deshacer">Deshacer carga</button>` : '',
    !enCurso && ctx.puede() ? `<button class="btn btn-danger" id="c-borrar">Borrar carga</button>` : '',
  ].join('');
  const fpt = k.filas_por_telefonos;
  const porOrigen = Object.entries(k.telefonos_por_origen || {});
  const porAtributo = Object.entries(k.atributos || {});
  main().innerHTML = pageHeader('Carga', '#' + c.id, `${esc(c.fuente)} · ${esc(c.archivo_nombre)} · ${estCarga(c.estado)}`, acciones) +
    pasos(PASO_DE[c.estado] || 3) +
    `<div class="card mb"><div class="card-body"><dl class="estado-explica"><dt>Estado</dt><dd>${est(c.estado)}</dd>
      <dt>Qué significa</dt><dd>${esc(significa)}</dd><dt>Qué sigue</dt><dd>${esc(sigue)}</dd></dl></div></div>` +
    (c.error ? `<div class="alert alert-error">${esc(c.error)}</div>` : '') +
    (enCurso ? card('Procesando', `<div id="c-prog"></div>`) : '') +
    (c.estado === 'preview' ? `<div class="alert alert-info"><span>Esto es un preview: la base todavía no cambió. Los conteos son exactamente los que se aplican al confirmar.</span></div>` : '') +
    stats([[k.filas || 0, 'Filas', 's-total'], [k.altas || 0, 'Altas', 's-ok'], [k.actualizaciones || 0, 'Actualizaciones', 's-free'],
      [k.sin_cambios || 0, 'Sin cambios', ''], [k.conflictos || 0, 'Conflictos', 's-warn'], [k.rechazos || 0, 'Rechazos', 's-bad'],
      [k.revision || 0, 'A revisión', 's-warn'], [k.nuevos_sospechosos || 0, 'Nuevos sospechosos', 's-bad'],
      [k.telefonos_nuevos || 0, 'Teléfonos nuevos', 's-free'],
      ...(k.contactos_nuevos ? [[k.contactos_nuevos, 'Contactos nuevos', 's-free']] : [])]) +
    (fpt || porOrigen.length || porAtributo.length ? `<div class="grid-2 mb">${card('Teléfonos', (fpt ? `<div class="card-body">${stats([[fpt['0'], 'Filas sin teléfono', fpt['0'] ? 's-warn' : ''],
        [fpt['1'], 'Con 1', ''], [fpt['2'], 'Con 2', ''], [fpt['3+'], 'Con 3 o más', '']]) +
        (fpt['0'] ? `<p class="small muted">Las filas sin teléfono se cargan igual: la empresa queda no disponible por «sin teléfono discable» si esa regla está activa.</p>` : '')}</div>` : '') +
        tabla([{ t: 'Origen', f: ([o]) => `<span class="td-strong">${esc(nombreO[o] || o)}</span>` },
          { t: 'Nuevos', cls: 'num', f: ([, n]) => num(n.nuevos) }, { t: 'Ya existentes', cls: 'num', f: ([, n]) => num(n.existentes) }],
        porOrigen, 'Sin teléfonos') + (k.origen_sin_traducir ? `<div class="card-body small"><span class="est est-sospechoso">${num(k.origen_sin_traducir)}</span> teléfonos con un origen sin traducir tomaron el origen por defecto.</div>` : ''), '', true)}
      ${card('Atributos', tabla([{ t: 'Atributo', f: ([a]) => `<span class="td-strong">${esc(nombreA[a] || a)}</span>` },
        { t: 'Cargados', cls: 'num', f: ([, n]) => num(n.cargados) },
        { t: 'Inválidos', cls: 'num', f: ([, n]) => n.invalidos ? `<span class="est est-sospechoso">${num(n.invalidos)}</span>` : '0' },
        { t: 'Sin dato', cls: 'num', f: ([, n]) => num(n.sin_dato || 0) }], porAtributo, 'La carga no trae atributos') +
        `<div class="card-body small muted">Un número o una fecha que no se puede interpretar no rechaza la fila: el valor queda como crudo y se cuenta como inválido.</div>`, '', true)}</div>` : '') +
    `<div class="grid-2">${card('Datos del lote', `<dl class="kv">
      <dt>Fuente</dt><dd>${esc(c.fuente)}</dd><dt>Tipo de fuente</dt><dd>${esc(c.tipo_fuente)}</dd><dt>Licencia</dt><dd>${esc(c.licencia)}</dd>
      <dt>Responsable</dt><dd>${esc(c.responsable)}</dd><dt>Regla de fusión</dt><dd>${esc(REGLAS[c.regla_fusion] || c.regla_fusion)}</dd>
      <dt>Confianza</dt><dd>${c.confianza}</dd><dt>Origen por defecto</dt><dd>${esc(nombreO[(c.mapeo || {}).origen_defecto] || '—')}</dd>
      <dt>Configuración</dt><dd>versión ${c.config_version}</dd><dt>Creada</dt><dd>${fechaHora(c.fecha)}</dd>
      <dt>Confirmada</dt><dd>${fechaHora(c.confirmada)}</dd>${c.descartada ? `<dt>Descartada</dt><dd>${fechaHora(c.descartada)}</dd>` : ''}
      ${c.deshecha ? `<dt>Deshecha</dt><dd>${fechaHora(c.deshecha)}</dd>` : ''}</dl>`)}
      ${card('Rechazos por motivo', tabla([{ t: 'Motivo', k: 0 }, { t: 'Filas', cls: 'num', f: r => num(r[1]) }],
        Object.entries(k.rechazos_por_motivo || {}), 'Sin rechazos') +
        (k.naturaleza_desconocida ? `<div class="card-body small"><span class="est est-sospechoso">${num(k.naturaleza_desconocida)}</span> filas con naturaleza jurídica que no está en el catálogo (el campo se ignoró).</div>` : '') +
        (k.rut_repetido_en_archivo ? `<div class="card-body small"><span class="est est-sospechoso">${num(k.rut_repetido_en_archivo)}</span> RUTs repetidos dentro del archivo.</div>` : '') +
        (c.revision_pendiente ? `<div class="card-body small"><a class="link" href="#/revision">${num(c.revision_pendiente)} coincidencias esperan revisión →</a></div>` : ''), '', true)}</div>` +
    (k.conflictos_ejemplos && k.conflictos_ejemplos.length ? card('Conflictos (ejemplos)', tabla([
      { t: 'RUT', f: x => `<a class="link mono" href="#/empresas/${x.rut}">${rutFmt(x.rut)}</a>` },
      { t: 'Campo · vigente → llegó', f: x => Object.entries(x.campos).map(([campo, v]) =>
        `<div><strong>${esc(campo.startsWith('atributo.') ? (nombreA[campo.slice(9)] || campo) : campo)}</strong>: ${esc(v.vigente)} <span class="muted">(${esc(v.fuente_vigente)})</span> → ${esc(v.llego)}</div>`).join('') },
    ], k.conflictos_ejemplos), '', true) : '') +
    card(`Filas rechazadas${c.rechazos.length >= 200 ? ' (primeras 200)' : ''}`, tabla([
      { t: 'Fila', cls: 'num', k: 'fila' }, { t: 'Motivo', k: 'motivo' },
      { t: 'Datos', f: r => `<span class="small muted">${esc(Object.entries(r.datos).filter(([, v]) => v !== null && v !== '').slice(0, 4).map(([kk, v]) => `${kk}: ${v}`).join(' · '))}</span>` },
    ], c.rechazos, 'Sin filas rechazadas'), '', true);

  const recargar = () => detalle(ctx, id);
  if (enCurso && c.tarea) {
    seguirTarea(c.tarea.id, $('#c-prog'), { texto: c.estado === 'analizando' ? 'Calculando el preview' : 'Aplicando la carga' })
      .then(recargar).catch(e => { toast(e.message, 'err'); recargar(); });
  }
  if ($('#c-confirmar')) $('#c-confirmar').onclick = async () => {
    if (!await confirmar('Confirmar carga', `Se aplican ${num(k.altas || 0)} altas y ${num(k.actualizaciones || 0)} actualizaciones. La carga se puede deshacer mientras ninguna de sus empresas entre a una muestra.`, 'Confirmar', 'btn-green')) return;
    await api.post(`/cargas/${id}/confirmar`);
    recargar();
  };
  if ($('#c-descartar')) $('#c-descartar').onclick = async () => {
    if (!await confirmar('Descartar carga', 'La carga queda «descartada»: no se aplica y la base no cambia. Queda como registro.', 'Descartar', 'btn-danger')) return;
    await api.del('/cargas/' + id); toast('Carga descartada', 'ok'); recargar();
  };
  if ($('#c-deshacer')) $('#c-deshacer').onclick = async () => {
    if (!await confirmar('Deshacer carga', 'Se anulan los valores y atributos que trajo, se borran sus vínculos de teléfono y sucursales (y el origen que sumó a teléfonos que ya existían), y las empresas que solo venían de esta carga quedan anuladas. La historia se conserva.', 'Deshacer', 'btn-danger')) return;
    const r = await api.del('/cargas/' + id);
    toast(`Carga deshecha: ${r.empresas_anuladas} empresas anuladas, ${r.empresas_recalculadas} recalculadas`, 'ok'); recargar();
  };
  if ($('#c-borrar')) $('#c-borrar').onclick = async () => {
    const txt = `Se elimina la carga y su archivo. Las empresas que solo venían de esta carga se borran del todo: historia, teléfonos,
      sucursales, atributos, su lugar en las muestras y su actividad de campo (intentos del CDR y respuestas del .sav).
      Las empresas que también tienen datos de otras fuentes se quedan, sin lo que aportó esta carga. <strong>No se puede deshacer.</strong>
      Solo queda el registro en Auditoría.<br><br>Escribí <strong>BORRAR</strong> para confirmar.`;
    const ok = await modal({ titulo: `Borrar carga #${c.id}`, cuerpo: `<p>${txt}</p><div class="form-group"><input type="text" id="m-borrar" autocomplete="off" /></div>`,
      acciones: [{ t: 'Cancelar' }, { t: 'Borrar definitivamente', cls: 'btn-danger', fn: (b) => {
        if (b.querySelector('#m-borrar').value.trim().toUpperCase() !== 'BORRAR') { toast('Escribí BORRAR para confirmar', 'err'); return false; }
        return true;
      } }] });
    if (!ok) return;
    const { tarea_id } = await api.del(`/cargas/${id}/definitivo`);
    main().innerHTML = pageHeader('Carga', '#' + c.id, 'Borrando…') + card('Borrando la carga', '<div id="c-prog"></div>');
    try {
      const t = await seguirTarea(tarea_id, $('#c-prog'), { texto: 'Borrando la carga' });
      const r = t.resultado || {};
      toast(`Carga borrada: ${num(r.empresas_borradas || 0)} empresas borradas, ${num(r.empresas_recalculadas || 0)} recalculadas`, 'ok');
      actualizarContadores && actualizarContadores();
      ctx.ir('cargas');
    } catch (e) { toast(e.message, 'err'); recargar(); }
  };
}

// ── Intermediarios ──
export async function intermediarios(ctx, params) {
  const estado = (params && params.get && params.get('estado')) || 'sospechoso';
  const r = await api.get('/telefonos/sospechosos', { estado });
  main().innerHTML = pageHeader('Teléfonos', 'intermediarios', `Un teléfono vinculado a ${r.umbral} RUTs o más queda sospechoso y sale de toda exportación hasta que lo confirmes o lo liberes.`) +
    tabs('inter', [['sospechoso', 'Sospechosos'], ['confirmado', 'Confirmados'], ['liberado', 'Liberados']], estado) +
    card(`${r.telefonos.length} teléfonos`, tabla([
      { t: 'Teléfono', f: t => `<span class="mono td-strong">${esc(t.e164 || t.crudo)}</span> ${est(t.tipo)}` },
      { t: 'RUTs', cls: 'num', f: t => `<strong>${t.n_empresas}</strong>` }, { t: 'Rubros distintos', cls: 'num', k: 'n_rubros' },
      { t: 'Empresas', f: t => `<details><summary class="link">${esc(t.empresas.slice(0, 2).map(e => e.razon_social || e.rut).join(', '))}${t.empresas.length > 2 ? '…' : ''}</summary>
        ${t.empresas.map(e => `<div class="small"><a class="link mono" href="#/empresas/${e.rut}">${rutFmt(e.rut)}</a> ${esc(e.razon_social || '')} <span class="muted">${esc(e.ciiu || '')}</span></div>`).join('')}</details>` },
      { t: 'Marcado', f: t => `${fechaHora(t.intermediario_fecha)}<div class="small muted">${esc(t.intermediario_por || '')}</div>` },
      { t: '', f: t => ctx.puede('steward') ? `<div class="td-actions">${estado !== 'confirmado' ? `<button class="btn btn-danger btn-sm" data-acc="confirmar" data-id="${t.id}">Confirmar</button>` : ''}
        ${estado !== 'liberado' ? `<button class="btn btn-outline btn-sm" data-acc="liberar" data-id="${t.id}">Liberar</button>` : ''}</div>` : '' },
    ], r.telefonos, estado === 'sospechoso' ? 'No hay sospechosos pendientes 🎉' : 'Sin teléfonos en este estado'), '', true) +
    `<p class="small muted mt">Confirmar marca todos los vínculos del número como "intermediario". Liberar lo vuelve discable; no se vuelve a marcar salvo que sume RUTs nuevos. La señal es más fuerte si las empresas tienen rubros distintos.</p>`;
  $$('[data-tabs="inter"] .tab').forEach(b => b.onclick = () => { location.hash = '#/intermediarios?estado=' + b.dataset.tab; });
  $$('[data-acc]').forEach(b => b.onclick = async () => {
    const motivo = await pedirTexto(b.dataset.acc === 'confirmar' ? 'Confirmar intermediario' : 'Liberar teléfono', 'Motivo', { obligatorio: false, placeholder: 'p. ej. estudio contable Pérez & Asoc.' });
    if (motivo === null) return;
    await api.post(`/telefonos/${b.dataset.id}/resolver`, { accion: b.dataset.acc, motivo });
    toast(b.dataset.acc === 'confirmar' ? 'Confirmado como intermediario' : 'Teléfono liberado', 'ok');
    actualizarContadores(); intermediarios(ctx, params);
  });
}

// ── Revisión de fusiones ──
export async function revision(ctx) {
  const items = await api.get('/revision');
  main().innerHTML = pageHeader('Revisión', 'de fusiones', 'Filas de cargas que coinciden con una empresa existente por teléfono, razón social o dominio, pero con otro RUT. No se fusionan solas.') +
    card(`${items.length} pendientes`, tabla([
      { t: 'Carga', f: r => `<a class="link" href="#/cargas/${r.carga_id}">#${r.carga_id}</a> <span class="small muted">fila ${r.fila}</span><div class="small muted">${esc(r.fuente)}</div>` },
      { t: 'Criterio', f: r => est('preview', etiqueta(r.criterio)) },
      { t: 'Fila que llegó', f: r => `<span class="mono">${rutFmt(r.datos.rut)}</span><div class="td-strong">${esc(r.datos.razon_social || '—')}</div>
        <div class="small muted">${esc((r.datos.telefonos || []).join(' · '))}${r.datos.web ? ' · ' + esc(r.datos.web) : ''}</div>` },
      { t: 'Empresa existente', f: r => `<a class="link mono" href="#/empresas/${r.candidata_rut}">${rutFmt(r.candidata_rut)}</a>
        <div class="td-strong">${esc(r.candidata_razon || '—')}</div><div class="small muted">${esc(r.candidata_web || '')}</div>` },
      { t: '', f: r => ctx.puede('steward') ? `<div class="td-actions">
        <button class="btn btn-orange btn-sm" data-r="${r.id}" data-a="alta" title="Crear como empresa nueva con su RUT">Alta nueva</button>
        <button class="btn btn-outline btn-sm" data-r="${r.id}" data-a="actualizar_candidata" title="Aplicar los datos a la empresa existente">Actualizar existente</button>
        <button class="btn btn-outline btn-sm btn-del" data-r="${r.id}" data-a="descartada">Descartar</button></div>` : '' },
    ], items, 'No hay coincidencias para revisar'), '', true);
  $$('[data-r]').forEach(b => b.onclick = async () => {
    await api.post('/revision/' + b.dataset.r, { accion: b.dataset.a });
    toast('Resuelto', 'ok'); actualizarContadores(); revision(ctx);
  });
}
