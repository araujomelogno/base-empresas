// Ingesta del .sav, conciliación y actividad (R1.8–R1.11)
import * as api from '../api.js';
import { $, $$, esc, main, toast, num, pct, fecha, fechaHora, rutFmt, est, etiqueta, pageHeader, stats, tabla, card,
  confirmar, seguirTarea, archivoDrop, activarDrop, tabs, barras, columnas, json } from '../ui.js';
import { actualizarContadores } from '../app.js';

const DESTINOS = {
  tel_usado: 'Teléfono usado (EC_TEL_USADO)', calidad_tel: 'Calidad del número (EC_CALIDAD_TEL)', tel_alt: 'Teléfono alternativo (EC_TEL_ALT)',
  resp_nombre: 'Respondente: nombre', resp_cargo: 'Respondente: cargo', resp_area: 'Respondente: área',
  resultado: 'Resultado (EC_RESULTADO)', estado_alchemer: 'Estado de Alchemer (status)', rut: 'RUT (EC_RUT, respaldo)',
  encuestador: 'Encuestador/a', fecha: 'Fecha de la respuesta',
};
const VALORES = {
  calidad_tel: ['corresponde', 'no_corresponde', 'intermediario', 'cerro', 'inexistente', 'ignorar'],
  resultado: ['completa', 'parcial', 'rechazo', 'no_corresponde', 'agendada', 'descalificada', 'ignorar'],
};
VALORES.estado_alchemer = VALORES.resultado;
const VALOR_TXT = { cerro: 'la empresa cerró', intermediario: 'estudio contable o jurídico (intermediario)', no_corresponde: 'no corresponde', ignorar: '— ignorar —' };

// Editor del mapeo: compartido entre la primera ingesta y la corrección (remapeo)
function editor(el, { columnas: cols, info, mapeo }) {
  const opt = (sel) => `<option value="">—</option>` + cols.map(c => `<option ${c === sel ? 'selected' : ''}>${esc(c)}</option>`).join('');
  const pintarValores = () => {
    const html = Object.keys(VALORES).map(d => {
      const v = $(`[data-dest="${d}"]`, el).value;
      if (!v) return '';
      const conocidos = new Map(Object.entries((info[v] && info[v].valores) || {}));
      ((info[v] && info[v].frecuentes) || []).forEach(([c]) => { if (!conocidos.has(String(c))) conocidos.set(String(c), null); });
      Object.keys((mapeo.valores || {})[d] || {}).forEach(c => { if (!conocidos.has(c)) conocidos.set(c, null); });
      const frec = Object.fromEntries(((info[v] && info[v].frecuentes) || []).map(([c, n]) => [String(c), n]));
      const actual = (mapeo.valores || {})[d] || {};
      return `<div class="mt"><div class="card-header-title mb">${esc(DESTINOS[d])} · variable ${esc(v)}</div>${tabla([
        { t: 'Código', f: x => `<span class="mono td-strong">${esc(x[0])}</span>` }, { t: 'Etiqueta en el archivo', f: x => esc(x[1] ?? '—') },
        { t: 'Filas', cls: 'num', f: x => num(frec[x[0]] || 0) },
        { t: 'Valor en el sistema', f: x => `<select class="fselect" data-val="${d}" data-cod="${esc(x[0])}" style="width:auto">
          <option value="">sin mapear</option>${VALORES[d].map(o => `<option value="${o}" ${actual[x[0]] === o ? 'selected' : ''}>${esc(VALOR_TXT[o] || o)}</option>`).join('')}</select>` },
      ], [...conocidos.entries()])}</div>`;
    }).join('');
    $('#ed-valores', el).innerHTML = html || '<p class="small muted">No hay variables codificadas mapeadas.</p>';
  };
  el.innerHTML = `<div class="grid-2"><div>
      <div class="form-group"><label>Response ID (identifica la respuesta)</label><select class="fselect" id="ed-rid">${opt(mapeo.response_id)}</select></div>
      <div class="form-row"><div class="form-group"><label>Variable identificador</label><select class="fselect" id="ed-idv">${opt((mapeo.identificador || {}).variable)}</select></div>
      <div class="form-group"><label>Tipo de identificador</label><select class="fselect" id="ed-idt">
        <option value="id_item" ${(mapeo.identificador || {}).tipo === 'id_item' ? 'selected' : ''}>id_item (EC_ID_ITEM)</option>
        <option value="rut" ${(mapeo.identificador || {}).tipo === 'rut' ? 'selected' : ''}>RUT</option></select></div></div>
      <p class="field-hint">Si una fila no trae id_item, se intenta asociar por RUT y teléfono usado.</p></div>
    <div><table class="map-grid"><thead><tr><th>Dato del sistema</th><th>Variable del .sav</th></tr></thead><tbody>
      ${Object.entries(DESTINOS).map(([d, t]) => `<tr><td class="td-strong">${esc(t)}</td><td><select class="fselect" data-dest="${d}">${opt((mapeo.variables || {})[d])}</select></td></tr>`).join('')}
    </tbody></table></div></div><div id="ed-valores"></div>`;
  $$('[data-dest]', el).forEach(s => s.onchange = () => { leer(); pintarValores(); });
  const leer = () => {
    const m = { response_id: $('#ed-rid', el).value, identificador: { variable: $('#ed-idv', el).value, tipo: $('#ed-idt', el).value }, variables: {}, valores: {} };
    $$('[data-dest]', el).forEach(s => { if (s.value) m.variables[s.dataset.dest] = s.value; });
    $$('[data-val]', el).forEach(s => { if (s.value) (m.valores[s.dataset.val] ||= {})[s.dataset.cod] = s.value; });
    Object.keys(VALORES).forEach(d => { if (!m.variables[d]) delete m.valores[d]; });
    mapeo = m;
    return m;
  };
  pintarValores();
  return { leer };
}

function pintarConteos(el, k) {
  if (!k || k.filas === undefined) { el.innerHTML = ''; return; }
  el.innerHTML = stats([[k.filas, 'Filas', 's-total'], [k.asociadas || 0, 'Asociadas', 's-ok'], [k.sin_asociar || 0, 'Sin asociar', 's-bad'],
    [`${k.porcentaje_asociadas ?? 0}%`, 'Asociadas', k.porcentaje_asociadas >= 95 ? 's-ok' : 's-warn'], [k.ya_ingeridas || 0, 'Ya ingeridas', '']]) +
    (Object.keys(k.motivos_sin_asociar || {}).length ? `<div class="small mb"><strong>Sin asociar por motivo:</strong> ${Object.entries(k.motivos_sin_asociar).map(([m, n]) => `${esc(m)} <strong>${num(n)}</strong>`).join(' · ')}</div>` : '') +
    ((k.avisos || []).length ? `<div class="alert alert-warn"><div><strong>Valores sin mapear</strong> (el valor crudo se guarda igual y se puede corregir después):<ul class="aviso-lista">${k.avisos.map(a => `<li>${esc(a)}</li>`).join('')}</ul></div></div>`
      : `<div class="alert alert-success">Todos los valores codificados están mapeados.</div>`);
}

export async function sav(ctx) {
  const [partes, ingestas] = await Promise.all([api.get('/partes'), api.get('/sav')]);
  const opts = partes.map(p => `<option value="${p.id}">${esc(p.estudio_nombre)} — ${esc(p.nombre)}${p.tiene_plantilla ? ' (con plantilla)' : ''}</option>`).join('');
  main().innerHTML = pageHeader('Ingesta', 'del .sav', 'Subí el .sav que exporta Alchemer para una parte. El sistema propone el mapeo; nada se aplica hasta que confirmes.') +
    (ctx.puede('coordinador') ? card('Nueva ingesta', `<div class="form-row"><div>
        <div class="form-group"><label>Estudio y parte</label><select class="fselect" id="s-parte">${opts}</select></div>
        <div class="form-group"><label>Reusar el mapeo de otra parte (opcional)</label><select class="fselect" id="s-plantilla"><option value="">— la plantilla de esta parte, si existe —</option>
          ${partes.filter(p => p.tiene_plantilla).map(p => `<option value="${p.id}">${esc(p.estudio_nombre)} — ${esc(p.nombre)}</option>`).join('')}</select>
          <div class="field-hint">Útil para la segunda ola del mismo cuestionario en otro estudio.</div></div></div>
        <div>${archivoDrop('s-arch', 'Arrastrá el .sav o tocá para elegirlo', '.sav')}<button class="btn btn-orange mt" id="s-analizar" disabled>Analizar</button></div></div>`) : '') +
    `<div id="s-editor"></div>` +
    card('Ingestas anteriores', tabla([
      { t: '#', f: i => `<a class="link" href="#/sav/${i.id}">${i.id}</a>` }, { t: 'Estudio', k: 'estudio_nombre' }, { t: 'Parte', k: 'parte_nombre' },
      { t: 'Archivo', k: 'archivo_nombre' }, { t: 'Estado', f: i => est(i.estado) },
      { t: 'Asociadas', cls: 'num', f: i => i.conteos.porcentaje_asociadas !== undefined ? `${i.conteos.porcentaje_asociadas}%` : '—' },
      { t: 'Coordinador/a', k: 'actor' }, { t: 'Fecha', f: i => fechaHora(i.fecha) },
    ], ingestas, 'Todavía no hay ingestas'), '', true);
  if (!ctx.puede('coordinador') || !partes.length) return;
  let archivo = null;
  activarDrop('s-arch', f => { archivo = f; $('#s-analizar').disabled = false; });
  $('#s-analizar').onclick = async () => {
    $('#s-analizar').disabled = true;
    const parteId = $('#s-parte').value;
    try {
      const a = await api.upload(`/partes/${parteId}/sav/analizar`, archivo, { plantilla_de_parte: $('#s-plantilla').value });
      const info = Object.fromEntries(a.variables.map(v => [v.nombre, v]));
      $('#s-editor').innerHTML = card(`Mapeo propuesto — ${a.archivo} (${num(a.n_filas)} filas · ${esc(a.origen_mapeo)})`, `
        <div id="s-ed"></div><div class="card-header-title mt mb">Conteos con este mapeo</div><div id="s-conteos"></div>
        <div class="gap"><button class="btn btn-outline" id="s-recontar">Recontar</button><button class="btn btn-green" id="s-confirmar">Confirmar ingesta</button></div>
        <div id="s-prog" class="mt"></div>`) +
        card('Variables del archivo', tabla([{ t: 'Variable', f: v => `<span class="mono td-strong">${esc(v.nombre)}</span>` }, { t: 'Etiqueta', k: 'etiqueta' },
          { t: 'No vacíos', cls: 'num', f: v => num(v.n_no_vacios) }, { t: 'Distintos', cls: 'num', f: v => num(v.n_distintos) },
          { t: 'Valores frecuentes', f: v => `<span class="small muted">${esc(v.frecuentes.slice(0, 6).map(([c, n]) => `${c} (${n})`).join(' · '))}</span>` }], a.variables), '', true);
      const ed = editor($('#s-ed'), { columnas: a.variables.map(v => v.nombre), info, mapeo: a.mapeo });
      pintarConteos($('#s-conteos'), a.conteos);
      $('#s-recontar').onclick = async () => pintarConteos($('#s-conteos'), await api.post(`/sav/${a.ingesta_id}/contar`, { ingesta_id: a.ingesta_id, mapeo: ed.leer() }));
      $('#s-confirmar').onclick = async () => {
        const m = ed.leer();
        if (!await confirmar('Confirmar ingesta', 'Se guardan las filas crudas y se actualiza la base: estados por parte, calidad de los números, teléfonos alternativos, contactos y último contacto efectivo. El mapeo queda como plantilla de la parte.', 'Confirmar', 'btn-green')) return;
        $('#s-confirmar').disabled = true;
        try {
          const r = await api.post(`/partes/${parteId}/sav`, { ingesta_id: a.ingesta_id, mapeo: m });
          await seguirTarea(r.tarea_id, $('#s-prog'), { texto: 'Ingiriendo' });
          toast('Ingesta confirmada', 'ok'); actualizarContadores();
          ctx.ir('sav/' + a.ingesta_id);
        } catch (e) { toast(e.message, 'err'); $('#s-confirmar').disabled = false; }
      };
    } catch (e) { toast(e.message, 'err'); $('#s-analizar').disabled = false; }
  };
}

export async function savDetalle(ctx, id) {
  const s = await api.get('/sav/' + id);
  const k = s.conteos || {};
  const aplicado = Object.entries(k).filter(([c]) => c.startsWith('aplicado_')).map(([c, n]) => [c.replace('aplicado_', ''), n]);
  main().innerHTML = pageHeader('Ingesta', '#' + s.id, `${esc(s.parte_nombre)} · ${esc(s.archivo_nombre)} · ${est(s.estado)} · ${esc(s.actor)} · ${fechaHora(s.fecha)}`,
    s.estado === 'confirmada' && ctx.puede('coordinador') ? `<button class="btn btn-outline" id="sd-remap">Corregir mapeo</button>` : '') +
    (s.error ? `<div class="alert alert-error">${esc(s.error)}</div>` : '') + `<div id="sd-prog"></div><div id="sd-conteos"></div>` +
    `<div class="grid-2">${card('Cambios aplicados a la base', tabla([{ t: 'Cambio', f: x => esc(etiqueta(x[0])) }, { t: 'Filas', cls: 'num', f: x => num(x[1]) }], aplicado, 'Sin cambios'), '', true)}
    ${card('Mapeo confirmado', json(s.mapeo))}</div><div id="sd-editor"></div>`;
  pintarConteos($('#sd-conteos'), k);
  if (['en_proceso'].includes(s.estado) && s.tarea) seguirTarea(s.tarea.id, $('#sd-prog')).then(() => savDetalle(ctx, id)).catch(e => toast(e.message, 'err'));
  if ($('#sd-remap')) $('#sd-remap').onclick = () => {
    const info = Object.fromEntries(Object.entries(s.frecuencias).map(([v, f]) => [v, { frecuentes: f, valores: {} }]));
    $('#sd-editor').innerHTML = card('Corregir mapeo (se reaplica sobre los valores crudos guardados)', `<div id="sd-ed"></div>
      <button class="btn btn-orange mt" id="sd-aplicar">Reaplicar con este mapeo</button><div id="sd-prog2" class="mt"></div>`);
    const ed = editor($('#sd-ed'), { columnas: s.columnas, info, mapeo: s.mapeo });
    $('#sd-aplicar').onclick = async () => {
      $('#sd-aplicar').disabled = true;
      try {
        const r = await api.post(`/sav/${id}/remapear`, { ingesta_id: +id, mapeo: ed.leer() });
        await seguirTarea(r.tarea_id, $('#sd-prog2'), { texto: 'Reaplicando' });
        toast('Mapeo corregido y reaplicado', 'ok'); savDetalle(ctx, id);
      } catch (e) { toast(e.message, 'err'); $('#sd-aplicar').disabled = false; }
    };
  };
}

// ── Conciliación ──
export async function conciliacion(ctx, params) {
  const tipo = (params && params.get && params.get('tipo')) || 'sav_fila';
  const items = await api.get('/conciliacion', { tipo });
  main().innerHTML = pageHeader('Conciliación', '', 'Filas del .sav y llamadas que no se pudieron asociar solas a un ítem de muestra.') +
    tabs('conc', [['sav_fila', 'Filas del .sav'], ['intento', 'Llamadas del CDR']], tipo) +
    card(`${items.length} pendientes`, tabla([
      { t: '#', k: 'id' },
      { t: tipo === 'intento' ? 'Llamada' : 'Respuesta', f: c => tipo === 'intento'
        ? `<span class="mono td-strong">${esc(c.objeto.e164)}</span><div class="small muted">${fechaHora(c.objeto.inicio)} · ${esc(c.objeto.encuestador || '')} · CDR ${esc(c.objeto.cdr_id)}</div>`
        : `<span class="td-strong">response ${esc(c.objeto.response_id)}</span><div class="small muted">${esc(c.objeto.parte)} · ingesta #${c.objeto.ingesta_id}</div>
          <details><summary class="link small">valores crudos</summary>${json(c.objeto.valores)}</details>` },
      { t: 'Motivo', k: 'motivo' },
      { t: 'Asociar a', f: c => ctx.puede('coordinador') ? `<div class="gap">${c.candidatos_detalle.length
        ? `<select class="fselect" data-sel="${c.id}" style="width:auto">${c.candidatos_detalle.map(i => `<option value="${i.id}">ítem ${i.id} · ${esc(i.razon_social || rutFmt(i.rut))} · ${esc(i.muestra)}</option>`).join('')}</select>`
        : `<input type="number" data-sel="${c.id}" placeholder="id de ítem" style="width:130px" />`}
        <button class="btn btn-orange btn-sm" data-asociar="${c.id}">Asociar</button><button class="btn btn-outline btn-sm btn-del" data-descartar="${c.id}">Descartar</button></div>` : '' },
    ], items, 'Nada para conciliar 🎉'), '', true) +
    `<p class="small muted mt">Para encontrar el id de ítem, abrí la muestra y buscá la empresa. Al asociar una fila del .sav se aplican sus resultados a la base.</p>`;
  $$('[data-tabs="conc"] .tab').forEach(b => b.onclick = () => { location.hash = '#/conciliacion?tipo=' + b.dataset.tab; });
  $$('[data-asociar]').forEach(b => b.onclick = async () => {
    const item = +$(`[data-sel="${b.dataset.asociar}"]`).value;
    if (!item) return toast('Elegí o escribí el ítem', 'err');
    await api.post('/conciliacion/' + b.dataset.asociar, { accion: 'asociar', item_id: item });
    toast('Asociado', 'ok'); actualizarContadores(); conciliacion(ctx, params);
  });
  $$('[data-descartar]').forEach(b => b.onclick = async () => {
    await api.post('/conciliacion/' + b.dataset.descartar, { accion: 'descartar' });
    actualizarContadores(); conciliacion(ctx, params);
  });
}

// ── Actividad ──
let _act = { estudio_id: '', muestra_id: '', encuestador: '', desde: '', hasta: '' };

export async function actividad(ctx) {
  const [estudios, muestras, lotes] = await Promise.all([api.get('/estudios'), api.get('/muestras'), api.get('/cdr/lotes')]);
  main().innerHTML = pageHeader('Actividad', 'de campo', 'Llamadas del CDR (campañas y marcador manual) y resultados de las ingestas. Filtrá por estudio, muestra, encuestador y período.') +
    `<div class="card mb"><div class="card-body"><div class="inline-form">
      <div class="form-group"><label>Estudio</label><select class="fselect" id="a-estudio_id"><option value="">Todos</option>${estudios.map(e => `<option value="${e.id}">${esc(e.nombre)}</option>`).join('')}</select></div>
      <div class="form-group"><label>Muestra</label><select class="fselect" id="a-muestra_id"><option value="">Todas</option>${muestras.map(m => `<option value="${m.id}">${esc(m.estudio_nombre)} — ${esc(m.nombre)}</option>`).join('')}</select></div>
      <div class="form-group"><label>Encuestador/a</label><select class="fselect" id="a-encuestador"><option value="">Todos</option></select></div>
      <div class="form-group"><label>Desde</label><input type="date" id="a-desde" /></div>
      <div class="form-group"><label>Hasta</label><input type="date" id="a-hasta" /></div></div></div></div><div id="a-res"></div>`;
  Object.entries(_act).forEach(([k, v]) => { const el = $('#a-' + k); if (el && k !== 'encuestador') el.value = v; });
  const cargar = async () => {
    Object.keys(_act).forEach(k => { _act[k] = $('#a-' + k).value; });
    const t = await api.get('/actividad', _act);
    const sel = $('#a-encuestador');
    if (sel.options.length === 1) sel.innerHTML += t.encuestadores_lista.map(e => `<option ${e === _act.encuestador ? 'selected' : ''}>${esc(e)}</option>`).join('');
    $('#a-res').innerHTML = stats([[t.intentos, 'Intentos', 's-total'], [t.telefonos_marcados, 'Teléfonos marcados', 's-free'],
      [t.empresas_llamadas, 'Empresas llamadas', ''], [t.contactos_efectivos, 'Contactos efectivos', 's-warn'], [t.completas, 'Completas', 's-ok'],
      [pct(t.asociados_a_item, t.intentos), 'Intentos asociados a ítem', '']]) +
      `<div class="grid-2">${card('Intentos por franja', barras(t.por_franja, { label: 'franja', valor: 'intentos' }))}
      ${card('Intentos por día', columnas(t.por_dia, { label: 'dia', valor: 'intentos' }))}</div>` +
      card('Por encuestador/a', tabla([{ t: 'Encuestador/a', f: e => `<span class="td-strong">${esc(e.encuestador)}</span>` },
        { t: 'Intentos', cls: 'num', f: e => num(e.intentos) }, { t: 'Teléfonos', cls: 'num', f: e => num(e.telefonos) },
        { t: 'Contactos efectivos', cls: 'num', f: e => num(e.contactos_efectivos) }, { t: 'Completas', cls: 'num', f: e => num(e.completas) },
        { t: 'Intentos por completa', cls: 'num', f: e => e.completas ? (e.intentos / e.completas).toLocaleString('es-UY', { maximumFractionDigits: 1 }) : '—' }],
      t.por_encuestador, 'Sin actividad'), '', true) +
      `<div class="grid-2">${card('Disposiciones de llamada', barras(t.por_disposicion, { label: 'disposicion', valor: 'intentos' }))}
      ${card('Lotes del CDR recibidos', tabla([{ t: 'Recibido', f: l => fechaHora(l.recibido) }, { t: 'Llamadas', cls: 'num', f: l => num(l.conteos.recibidas) },
        { t: 'Internas', cls: 'num', f: l => num(l.conteos.internas) }, { t: 'No cruzan', cls: 'num', f: l => num(l.conteos.no_cruzan) },
        { t: 'Nuevos', cls: 'num', f: l => num(l.conteos.intentos_nuevos) }], lotes.slice(0, 10), 'Todavía no llegó ningún lote'), '', true)}</div>`;
  };
  $$('.inline-form select, .inline-form input').forEach(i => i.onchange = cargar);
  await cargar();
}
