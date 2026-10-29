// Cargas de bases, intermediarios y revisión de fusiones (R1.2, R1.3)
import * as api from '../api.js';
import { $, $$, esc, main, toast, num, fecha, fechaHora, rutFmt, est, etiqueta, pageHeader, stats, tabla, card, modal,
  pedirTexto, confirmar, seguirTarea, archivoDrop, activarDrop, tabs } from '../ui.js';
import { actualizarContadores } from '../app.js';

const CAMPOS = {
  rut: 'RUT *', razon_social: 'Razón social', fantasia: 'Nombre de fantasía', naturaleza: 'Naturaleza jurídica (código o nombre)',
  ciiu: 'CIIU / rubro', tamano: 'Tamaño', departamento: 'Departamento', localidad: 'Localidad', direccion: 'Dirección', web: 'Web',
  email: 'Email (para dominio)', estado: 'Estado (activa / cerrada)', contacto_nombre: 'Contacto: nombre', contacto_cargo: 'Contacto: cargo',
  contacto_area: 'Contacto: área', contacto_email: 'Contacto: email', contacto_telefono: 'Contacto: teléfono',
  sucursal_direccion: 'Sucursal: dirección', sucursal_departamento: 'Sucursal: departamento', sucursal_localidad: 'Sucursal: localidad',
};
const REGLAS = { rut: 'RUT (por defecto)', telefono: 'Teléfono', razon_social: 'Razón social normalizada', dominio: 'Dominio web' };

export async function lista(ctx) {
  const cargas = await api.get('/cargas');
  main().innerHTML = pageHeader('Cargas', 'de bases', 'Cada carga es un lote con fuente, responsable y licencia. Se puede deshacer mientras ninguna de sus empresas haya entrado a una muestra.',
    ctx.puede('steward') ? `<button class="btn btn-orange" id="c-nueva">+ Nueva carga</button>` : '') +
    card('Historial de cargas', tabla([
      { t: '#', f: c => `<a class="link" href="#/cargas/${c.id}">${c.id}</a>` },
      { t: 'Fuente', f: c => `<span class="td-strong">${esc(c.fuente)}</span><div class="small muted">${esc(c.archivo_nombre)}</div>` },
      { t: 'Tipo', k: 'tipo_fuente' }, { t: 'Fusión', f: c => esc(REGLAS[c.regla_fusion] || c.regla_fusion) }, { t: 'Estado', f: c => est(c.estado) },
      { t: 'Altas', cls: 'num', f: c => num(c.conteos.altas || 0) }, { t: 'Act.', cls: 'num', f: c => num(c.conteos.actualizaciones || 0) },
      { t: 'Rechazos', cls: 'num', f: c => num(c.conteos.rechazos || 0) }, { t: 'Responsable', k: 'responsable' }, { t: 'Fecha', f: c => fechaHora(c.fecha) },
    ], cargas, 'Todavía no hay cargas'), '', true);
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
        <div class="field-hint">El mapeo de columnas se guarda como plantilla por tipo de fuente y se reusa en la próxima carga.</div></div>
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

function mapeo(ctx, a, tipoFuente, params) {
  const opts = (sel) => `<option value="">— no usar —</option>` + a.columnas.map(c => `<option ${c === sel ? 'selected' : ''}>${esc(c)}</option>`).join('');
  $('.steps').outerHTML = pasos(2);
  $('#c-paso2').innerHTML = card(`2 · Mapeo de columnas — ${a.nombre} (${num(a.n_filas)} filas)`, `
    <div class="alert alert-info">Mapeo ${a.origen_mapeo === 'plantilla' ? `cargado de la plantilla <strong>${esc(tipoFuente)}</strong>` : 'sugerido por los nombres de columna'}. Revisalo antes de seguir.</div>
    <div class="grid-2"><div><table class="map-grid"><thead><tr><th>Campo de la base</th><th>Columna del archivo</th></tr></thead><tbody>
      ${Object.entries(CAMPOS).map(([k, t]) => `<tr><td class="td-strong">${t}</td><td><select class="fselect" data-map="${k}">${opts(a.mapeo[k])}</select></td></tr>`).join('')}
    </tbody></table></div>
    <div><div class="form-group"><label>Columnas de teléfono</label><div class="chips" id="c-tels">${a.columnas.map(c =>
      `<span class="chip ${(a.mapeo.telefonos || []).includes(c) ? 'on' : ''}" data-v="${esc(c)}">${esc(c)}</span>`).join('')}</div>
      <div class="field-hint">Una celda puede traer varios números separados por / ; o ,</div></div>
      <div class="form-group"><label>Nombre de la fuente</label><input type="text" id="c-fuente" value="${esc(a.nombre.replace(/\.[^.]+$/, ''))}" /></div>
      <div class="form-group"><label>Licencia de uso</label><input type="text" id="c-licencia" placeholder="p. ej. base propia, uso interno" /></div>
      <div class="form-row"><div class="form-group"><label>Regla de fusión</label><select class="fselect" id="c-regla">${
        params.reglas_fusion.map(r => `<option value="${r}">${esc(REGLAS[r] || r)}</option>`).join('')}</select>
        <div class="field-hint">Las coincidencias que no son por RUT van a la bandeja de revisión.</div></div>
        <div class="form-group"><label>Confianza (0–100)</label><input type="number" id="c-conf" min="0" max="100" value="${params.confianza_fuentes.carga ?? 50}" /></div></div>
      <label class="check"><input type="checkbox" id="c-plantilla" checked /> Guardar el mapeo como plantilla de "${esc(tipoFuente || 'sin tipo')}"</label>
      <div class="mt"><button class="btn btn-orange" id="c-preview">Ver preview</button></div><div id="c-prog" class="mt"></div></div></div>`) +
    card('Primeras filas del archivo', `<div class="table-wrap"><table><thead><tr>${a.columnas.map(c => `<th>${esc(c)}</th>`).join('')}</tr></thead>
      <tbody>${a.ejemplos.map(f => `<tr>${a.columnas.map(c => `<td>${esc(f[c] ?? '')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`, '', true);
  $$('#c-tels .chip').forEach(c => c.onclick = () => c.classList.toggle('on'));
  $('#c-preview').onclick = async () => {
    const m = { telefonos: $$('#c-tels .chip.on').map(c => c.dataset.v) };
    $$('[data-map]').forEach(s => { if (s.value) m[s.dataset.map] = s.value; });
    if (!m.rut) return toast('Indicá la columna del RUT', 'err');
    if (!$('#c-licencia').value.trim()) return toast('Indicá la licencia de uso de la fuente', 'err');
    $('#c-preview').disabled = true;
    try {
      const r = await api.post('/cargas', {
        archivo_id: a.archivo_id, fuente: $('#c-fuente').value.trim() || a.nombre, tipo_fuente: tipoFuente || 'sin tipo',
        licencia: $('#c-licencia').value.trim(), regla_fusion: $('#c-regla').value, confianza: +$('#c-conf').value,
        mapeo: m, guardar_plantilla: $('#c-plantilla').checked,
      });
      await seguirTarea(r.tarea_id, $('#c-prog'), { texto: 'Calculando el preview' });
      ctx.ir('cargas/' + r.carga_id);
    } catch (e) { toast(e.message, 'err'); $('#c-preview').disabled = false; }
  };
}

export async function detalle(ctx, id) {
  const c = await api.get('/cargas/' + id);
  const k = c.conteos || {};
  const enCurso = ['analizando', 'en_proceso'].includes(c.estado);
  const acciones = [
    c.estado === 'preview' && ctx.puede('steward') ? `<button class="btn btn-green" id="c-confirmar">Confirmar carga</button>` : '',
    ['preview', 'error'].includes(c.estado) && ctx.puede('steward') ? `<button class="btn btn-outline" id="c-descartar">Descartar</button>` : '',
    c.estado === 'confirmada' && ctx.puede('steward') ? `<button class="btn btn-outline btn-del" id="c-deshacer">Deshacer carga</button>` : '',
  ].join('');
  main().innerHTML = pageHeader('Carga', '#' + c.id, `${esc(c.fuente)} · ${esc(c.archivo_nombre)} · ${est(c.estado)}`, acciones) +
    pasos(c.estado === 'preview' ? 3 : c.estado === 'confirmada' ? 5 : 3) +
    (c.error ? `<div class="alert alert-error">${esc(c.error)}</div>` : '') +
    (enCurso ? card('Procesando', `<div id="c-prog"></div>`) : '') +
    (c.estado === 'preview' ? `<div class="alert alert-info">Esto es un preview: la base todavía no cambió. Los conteos son exactamente los que se aplican al confirmar.</div>` : '') +
    stats([[k.filas || 0, 'Filas', 's-total'], [k.altas || 0, 'Altas', 's-ok'], [k.actualizaciones || 0, 'Actualizaciones', 's-free'],
      [k.sin_cambios || 0, 'Sin cambios', ''], [k.conflictos || 0, 'Conflictos', 's-warn'], [k.rechazos || 0, 'Rechazos', 's-bad'],
      [k.revision || 0, 'A revisión', 's-warn'], [k.nuevos_sospechosos || 0, 'Nuevos sospechosos', 's-bad'],
      [k.telefonos_nuevos || 0, 'Teléfonos nuevos', 's-free'], [k.contactos_nuevos || 0, 'Contactos nuevos', 's-free']]) +
    `<div class="grid-2">${card('Datos del lote', `<dl class="kv">
      <dt>Fuente</dt><dd>${esc(c.fuente)}</dd><dt>Tipo de fuente</dt><dd>${esc(c.tipo_fuente)}</dd><dt>Licencia</dt><dd>${esc(c.licencia)}</dd>
      <dt>Responsable</dt><dd>${esc(c.responsable)}</dd><dt>Regla de fusión</dt><dd>${esc(REGLAS[c.regla_fusion] || c.regla_fusion)}</dd>
      <dt>Confianza</dt><dd>${c.confianza}</dd><dt>Configuración</dt><dd>versión ${c.config_version}</dd><dt>Creada</dt><dd>${fechaHora(c.fecha)}</dd>
      <dt>Confirmada</dt><dd>${fechaHora(c.confirmada)}</dd><dt>Deshecha</dt><dd>${fechaHora(c.deshecha)}</dd></dl>`)}
      ${card('Rechazos por motivo', tabla([{ t: 'Motivo', k: 0 }, { t: 'Filas', cls: 'num', f: r => num(r[1]) }],
        Object.entries(k.rechazos_por_motivo || {}), 'Sin rechazos') +
        (k.naturaleza_desconocida ? `<div class="card-body small"><span class="est est-sospechoso">${num(k.naturaleza_desconocida)}</span> filas con naturaleza jurídica que no está en el catálogo (el campo se ignoró).</div>` : '') +
        (k.rut_repetido_en_archivo ? `<div class="card-body small"><span class="est est-sospechoso">${num(k.rut_repetido_en_archivo)}</span> RUTs repetidos dentro del archivo.</div>` : '') +
        (c.revision_pendiente ? `<div class="card-body small"><a class="link" href="#/revision">${num(c.revision_pendiente)} coincidencias esperan revisión →</a></div>` : ''), '', true)}</div>` +
    (k.conflictos_ejemplos && k.conflictos_ejemplos.length ? card('Conflictos (ejemplos)', tabla([
      { t: 'RUT', f: x => `<a class="link mono" href="#/empresas/${x.rut}">${rutFmt(x.rut)}</a>` },
      { t: 'Campo · vigente → llegó', f: x => Object.entries(x.campos).map(([campo, v]) =>
        `<div><strong>${esc(campo)}</strong>: ${esc(v.vigente)} <span class="muted">(${esc(v.fuente_vigente)})</span> → ${esc(v.llego)}</div>`).join('') },
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
    if (!await confirmar('Descartar carga', 'El preview se descarta y la base no cambia.', 'Descartar', 'btn-danger')) return;
    await api.del('/cargas/' + id); recargar();
  };
  if ($('#c-deshacer')) $('#c-deshacer').onclick = async () => {
    if (!await confirmar('Deshacer carga', 'Se anulan los valores que trajo, se borran sus vínculos de teléfono, contactos y sucursales, y las empresas que solo venían de esta carga quedan anuladas. La historia se conserva.', 'Deshacer', 'btn-danger')) return;
    const r = await api.del('/cargas/' + id);
    toast(`Carga deshecha: ${r.empresas_anuladas} empresas anuladas, ${r.empresas_recalculadas} recalculadas`, 'ok'); recargar();
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
