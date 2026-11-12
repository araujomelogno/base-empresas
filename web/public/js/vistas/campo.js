// Ingesta del .sav, conciliación y actividad (R1.8–R1.11)
import * as api from '../api.js';
import { $, $$, esc, main, toast, num, pct, fecha, fechaHora, rutFmt, est, etiqueta, pageHeader, stats, tabla, card, modal,
  confirmar, seguirTarea, archivoDrop, activarDrop, tabs, barras, columnas, json } from '../ui.js';
import { actualizarContadores } from '../app.js';

const DESTINOS = {
  tel_usado: 'Teléfono usado (EC_TEL_USADO)', calidad_tel: 'Calidad del número (EC_CALIDAD_TEL)', tel_alt: 'Teléfono alternativo (EC_TEL_ALT)',
  resp_nombre: 'Respondente: nombre', resp_cargo: 'Respondente: cargo', resp_area: 'Respondente: área',
  rut: 'RUT (EC_RUT, respaldo)',
  encuestador: 'Encuestador/a', fecha: 'Fecha de la respuesta',
};
const VALORES = {
  calidad_tel: ['corresponde', 'no_corresponde', 'intermediario', 'cerro', 'inexistente', 'ignorar'],
};
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
      <p class="field-hint">Si una fila no trae id_item, se intenta asociar por RUT y teléfono usado.</p>
      <div class="alert alert-info small"><span><strong>Toda fila del .sav es una encuesta completa</strong> (Alchemer exporta solo las completas):
      no hace falta mapear un resultado ni el estado de Alchemer. El número usado y el adicional quedan verificados.</span></div></div>
    <div><table class="map-grid"><thead><tr><th>Dato del sistema</th><th>Variable del .sav</th></tr></thead><tbody>
      ${Object.entries(DESTINOS).map(([d, t]) => `<tr><td class="td-strong">${esc(t)}</td><td><select class="fselect" data-dest="${d}">${opt((mapeo.variables || {})[d])}</select></td></tr>`).join('')}
    </tbody></table></div></div><div id="ed-valores"></div>`;
  $$('[data-dest]', el).forEach(s => s.onchange = () => { leer(); pintarValores(); });
  const leer = () => {
    const m = { ...mapeo, response_id: $('#ed-rid', el).value, identificador: { variable: $('#ed-idv', el).value, tipo: $('#ed-idt', el).value }, variables: {}, valores: {} };
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
  el.innerHTML = stats([[k.filas, 'Filas', 's-total'], [k.completas ?? ((k.filas || 0) - (k.sin_response_id || 0)), 'Encuestas completas', 's-ok'],
    [k.asociadas || 0, 'Asociadas', 's-ok'], [k.sin_asociar || 0, 'Sin asociar', 's-bad'],
    [`${k.porcentaje_asociadas ?? 0}%`, 'Asociadas', k.porcentaje_asociadas >= 95 ? 's-ok' : 's-warn'], [k.ya_ingeridas || 0, 'Ya ingeridas', '']]) +
    (Object.keys(k.motivos_sin_asociar || {}).length ? `<div class="small mb"><strong>Sin asociar por motivo:</strong> ${Object.entries(k.motivos_sin_asociar).map(([m, n]) => `${esc(m)} <strong>${num(n)}</strong>`).join(' · ')}</div>` : '') +
    (k.sin_response_id ? `<div class="small mb"><strong>${num(k.sin_response_id)} fila${k.sin_response_id > 1 ? 's' : ''} sin response_id:</strong> no cuentan como encuesta.</div>` : '') +
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
    (s.error ? `<div class="alert alert-error">${esc(s.error)}</div>` : '') +
    (s.tarea && s.tarea.trabada ? `<div class="alert alert-warn"><span>La tarea #${s.tarea.id} figura corriendo desde el ${fechaHora(s.tarea.creado)}:
      está <strong>trabada</strong> (la instancia que la corría probablemente se reinició). Volvé a subir el .sav; un administrador puede borrar el estudio de prueba si hace falta.</span></div>` : '') +
    `<div id="sd-prog"></div><div id="sd-conteos"></div>` +
    (s.completas ? `<div class="alert alert-info"><span><strong>${num(s.completas.total)} encuestas completas</strong> (filas con response_id):
      ${num(s.completas.asociadas)} asociadas a un ítem y ${num(s.completas.sin_asociar)} sin asociar${s.completas.sin_asociar ? ` · <a class="link" href="#/conciliacion?tipo=sav_fila">conciliarlas</a>` : ''}.</span></div>` : '') +
    card('Lo que no se aplicó, fila por fila', tabla([
      { t: 'Motivo', f: a => `<span class="td-strong">${esc(a.motivo)}</span>` }, { t: 'Filas', cls: 'num', f: a => num(a.n) },
      { t: 'Ejemplos (response_id)', f: a => `<span class="small">${(a.ejemplos || []).map(x => `<span class="mono">${esc(x.response_id)}</span>${x.valor ? ` «${esc(x.valor)}»` : ''}`).join(' · ')}</span>` },
    ], s.avisos_filas || [], 'Todas las filas se aplicaron completas'), '', true) +
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
  const [estudios, muestras, corridas] = await Promise.all([api.get('/estudios'), api.get('/muestras'), api.get('/cdr/corridas')]);
  main().innerHTML = pageHeader('Actividad', 'de campo', 'Llamadas del CDR (campañas y marcador manual) y resultados de las ingestas. Filtrá por estudio, muestra, encuestador y período.') +
    `<div class="card mb"><div class="card-body"><div class="inline-form">
      <div class="form-group"><label>Estudio</label><select class="fselect" id="a-estudio_id"><option value="">Todos</option>${estudios.map(e => `<option value="${e.id}">${esc(e.nombre)}</option>`).join('')}</select></div>
      <div class="form-group"><label>Muestra</label><select class="fselect" id="a-muestra_id"><option value="">Todas</option>${muestras.map(m => `<option value="${m.id}">${esc(m.estudio_nombre)} — ${esc(m.nombre)}</option>`).join('')}</select></div>
      <div class="form-group"><label>Encuestador/a</label><select class="fselect" id="a-encuestador"><option value="">Todos</option></select></div>
      <div class="form-group"><label>Desde</label><input type="date" id="a-desde" /></div>
      <div class="form-group"><label>Hasta</label><input type="date" id="a-hasta" /></div>
      ${ctx.puede('coordinador', 'jefe') ? `<div class="form-group"><label>&nbsp;</label><button class="btn btn-outline" id="a-empresas">Empresas llamadas</button></div>` : ''}
      </div></div></div><div id="a-res"></div>`;
  if ($('#a-empresas')) $('#a-empresas').onclick = () => irEmpresas(ctx, { ..._act });
  Object.entries(_act).forEach(([k, v]) => { const el = $('#a-' + k); if (el && k !== 'encuestador') el.value = v; });
  const cargar = async () => {
    Object.keys(_act).forEach(k => { _act[k] = $('#a-' + k).value; });
    const t = await api.get('/actividad', _act);
    const sel = $('#a-encuestador');
    if (sel.options.length === 1) sel.innerHTML += t.encuestadores_lista.map(e => `<option ${e === _act.encuestador ? 'selected' : ''}>${esc(e)}</option>`).join('');
    $('#a-res').innerHTML = stats([[t.intentos, 'Llamadas a empresas', 's-total'], [t.telefonos_marcados, 'Teléfonos marcados', 's-free'],
      [t.empresas_llamadas, 'Empresas llamadas', ''], [t.contactos_efectivos, 'Contactos efectivos', 's-warn'], [t.completas, 'Encuestas completas', 's-ok'],
      [pct(t.asociados_a_item, t.intentos), 'Asociadas a un ítem de muestra', '']]) +
      `<div class="card mb"><div class="card-body small">Encuestas completas (filas del .sav): <strong>${num(t.completas_asociadas)}</strong> asociadas a un ítem
        + <strong>${num(t.completas_sin_asociar)}</strong> sin asociar${t.completas_sin_asociar ? ` · <a class="link" href="#/conciliacion?tipo=sav_fila">conciliar las sin asociar</a>` : ''}.
        <span class="muted">Cuentan todas las filas del .sav, estén o no asociadas; el período usa la fecha de la respuesta.</span></div></div>` +
      `<div class="grid-2">${card('Intentos por franja', barras(t.por_franja, { label: 'franja', valor: 'intentos' }))}
      ${card('Intentos por día', columnas(t.por_dia, { label: 'dia', valor: 'intentos' }))}</div>` +
      card('Por encuestador/a', tabla([{ t: 'Encuestador/a', f: e => `<span class="td-strong">${esc(e.encuestador)}</span>` },
        { t: 'Intentos', cls: 'num', f: e => num(e.intentos) }, { t: 'Teléfonos', cls: 'num', f: e => num(e.telefonos) },
        { t: 'Contactos efectivos', cls: 'num', f: e => num(e.contactos_efectivos) }, { t: 'Completas', cls: 'num', f: e => num(e.completas) },
        { t: 'Intentos por completa', cls: 'num', f: e => e.completas ? (e.intentos / e.completas).toLocaleString('es-UY', { maximumFractionDigits: 1 }) : '—' }],
      t.por_encuestador, 'Sin actividad'), '', true) +
      card('Disposiciones de llamada', barras(t.por_disposicion, { label: 'disposicion', valor: 'intentos' })) +
      tablaCorridas(ctx, corridas.slice(0, 15)) +
      `<div id="a-origenes"></div>`;
    rendimientoOrigen();
    activarCorridas(ctx, corridas);
  };
  const rendimientoOrigen = async () => {
    const r = await api.get('/actividad/origenes', _act);
    const pc = (v) => v === null || v === undefined ? '—' : v.toLocaleString('es-UY', { maximumFractionDigits: 1 }) + '%';
    const dec = (v) => v === null || v === undefined ? '—' : v.toLocaleString('es-UY', { maximumFractionDigits: 1 });
    const cols = [
      ['Origen', o => o.nombre], ['Discables', o => o.discables], ['Teléfonos llamados', o => o.telefonos_llamados],
      ['Llamadas', o => enlace(o, o.llamadas)], ['Empresas llamadas', o => enlace(o, o.empresas_llamadas)],
      ['Contactab.', o => pc(o.contactabilidad)], ['Efectivos', o => o.contactos_efectivos],
      ['% no corr.', o => pc(o.pct_no_corresponde)], ['% inexist.', o => pc(o.pct_inexistente)],
      ['% interm.', o => pc(o.pct_intermediario)], ['Int. por efectivo', o => dec(o.intentos_por_efectivo)],
    ];
    const enlace = (o, n) => !n || !ctx.puede('coordinador', 'jefe') ? num(n)
      : `<a class="link" href="${hashEmpresas({ ..._act, origen: o.codigo || '' })}" title="Ver las empresas llamadas">${num(n)}</a>`;
    const filas = [...r.origenes, { ...r.total, __tr: 'class="fila-total"' }];
    $('#a-origenes').innerHTML = card('Rendimiento por origen', (r.origenes.length ? tabla(cols.map(([t, f], i) => ({
      t, cls: i ? 'num' : '', f: o => i ? (typeof f(o) === 'number' ? num(f(o)) : f(o)) : `<span class="td-strong">${esc(f(o))}</span>` })), filas)
      : `<div class="empty-state"><span class="ei">☎️</span>Sin teléfonos con origen para estos filtros</div>`) +
      `<div class="card-body small muted">Cuenta <strong>todas las llamadas a empresas de la base</strong> del período, estén o no en una muestra; con un estudio o una muestra elegidos, las llamadas a empresas de sus muestras (aunque no hayan quedado asociadas al ítem).
       Discables y teléfonos llamados son teléfonos; llamadas son llamadas del CDR a esos teléfonos (una por llamada); empresas llamadas son empresas distintas; efectivos son ítems con contacto efectivo cuyo teléfono usado tiene ese origen.
       Tocá un número de llamadas o de empresas para ver la lista. Un teléfono con varios orígenes cuenta en cada uno; la fila Total cuenta cada teléfono una sola vez.
       Contactabilidad: teléfonos con al menos una llamada atendida (${esc(r.definicion_atendida)}) sobre teléfonos llamados.
       Los porcentajes de no corresponde, inexistente e intermediario son vínculos marcados por la sala sobre teléfonos llamados.</div>`,
      r.origenes.length ? `<button class="btn btn-outline btn-sm" id="a-origenes-csv">Descargar CSV</button>` : '', true);
    if ($('#a-origenes-csv')) $('#a-origenes-csv').onclick = () => {
      const celda = (v) => { const s = v === null || v === undefined ? '' : String(v); return /[;"\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
      const crudo = [['Origen', o => o.nombre], ['Teléfonos discables', o => o.discables], ['Teléfonos llamados', o => o.telefonos_llamados],
        ['Llamadas', o => o.llamadas], ['Empresas llamadas', o => o.empresas_llamadas], ['Teléfonos atendidos', o => o.atendidos],
        ['Contactabilidad %', o => o.contactabilidad],
        ['Contactos efectivos', o => o.contactos_efectivos], ['% no corresponde', o => o.pct_no_corresponde],
        ['% inexistente', o => o.pct_inexistente], ['% intermediario', o => o.pct_intermediario],
        ['Intentos por contacto efectivo', o => o.intentos_por_efectivo]];
      const lineas = [crudo.map(c => c[0]), ...[...r.origenes, r.total].map(o => crudo.map(c => c[1](o)))].map(l => l.map(celda).join(';'));
      const url = URL.createObjectURL(new Blob(['\ufeff' + lineas.join('\r\n')], { type: 'text/csv;charset=utf-8' }));
      const a = document.createElement('a'); a.href = url; a.download = 'rendimiento_por_origen.csv'; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    };
  };
  $$('.inline-form select, .inline-form input').forEach(i => i.onchange = cargar);
  await cargar();
}

// ── Corridas del job del CDR (R2) ──
const v2 = (c) => (c.conteos || {}).conteo_version >= 2;
const NOTA_ANTERIOR = 'Corrida anterior al nuevo conteo: no tiene este dato. Un reproceso con «Correr ahora» y fechas lo recalcula.';

function tablaCorridas(ctx, corridas) {
  const n = (c, k) => v2(c) ? num(c.conteos[k] || 0) : `<span class="muted" title="${NOTA_ANTERIOR}">—</span>`;
  return card('Corridas del job del CDR', tabla([
    { t: 'Inicio', f: c => `<span class="small">${fechaHora(c.inicio)}</span><div class="small muted">${esc(c.origen)}${c.dry_run ? ' · dry-run' : ''}</div>` },
    { t: 'Estado', f: c => est(c.estado) },
    { t: 'Llamadas', cls: 'num', f: c => n(c, 'llamadas') }, { t: 'A empresas', cls: 'num', f: c => n(c, 'llamadas_a_empresas') },
    { t: 'Teléfonos', cls: 'num', f: c => n(c, 'telefonos_marcados') }, { t: 'Empresas', cls: 'num', f: c => n(c, 'empresas_llamadas') },
    { t: 'Detalle', f: c => `<span class="small">${esc(c.mensaje || (c.pedido_desde ? `reproceso desde ${c.pedido_desde}` : ''))}</span>
      ${!v2(c) && c.conteos && Object.keys(c.conteos).length ? `<div class="small muted">corrida anterior al nuevo conteo</div>` : ''}
      ${c.conteos && Object.keys(c.conteos).length ? `<div class="small"><a class="link" href="javascript:void 0" data-corrida-detalle="${c.id}">Ver detalle</a></div>` : ''}
      ${ctx.puede('coordinador', 'jefe') && c.estado !== 'en_curso' && !c.dry_run ? `<div class="small"><a class="link" href="${hashEmpresas({ corrida_id: c.id })}">Exportar empresas</a></div>` : ''}` },
  ], corridas, 'Todavía no corrió el job del CDR'), '', true) +
    `<p class="small muted mt">Llamadas: una por llamada del CDR (los tramos de una misma llamada cuentan una vez), con destino externo y sin filtro de campaña, igual que el dashboard de productividad.
     A empresas: las llamadas a un teléfono de la base, nuevas o ya registradas. Teléfonos y empresas: distintos, entre esas llamadas.</p>`;
}

function embudo(c) {
  const k = c.conteos || {};
  const fila = (t, v, sub = '') => `<tr><td>${t}</td><td class="num td-strong">${v === undefined ? (v2(c) ? '0' : '—') : num(v)}</td><td class="small muted">${sub}</td></tr>`;
  const porTipo = Object.entries(k.no_cruzan_por_tipo || {}).map(([t, v]) => `${esc(etiqueta(t))} ${num(v)}`).join(' · ');
  if (!v2(c)) {
    return `<p class="small muted mb">${NOTA_ANTERIOR}</p><table class="tabla-simple">${fila('Filas leídas', k.filas_leidas)}
      ${fila('Recibidas (después de quitar tramos repetidos)', k.recibidas)}${fila('Internas', k.internas)}${fila('No normalizables', k.no_normalizables)}
      ${fila('No están en la base', k.no_cruzan, porTipo)}${fila('Intentos nuevos', k.intentos_nuevos)}${fila('Ya registrados', k.duplicados)}</table>`;
  }
  const repetidas = (k.filas_leidas || 0) - (k.recibidas || 0);
  return `<table class="tabla-simple">
    ${fila('Filas leídas', k.filas_leidas)}
    ${fila('− tramos repetidos y filas ya procesadas', repetidas, 'una llamada con varios tramos (mismo uniqueid) cuenta una vez')}
    ${fila('− internas', k.internas, 'anexos, colas y demás destinos internos de la configuración')}
    ${fila('= Llamadas', k.llamadas)}
    ${fila('− no normalizables', k.no_normalizables)}
    ${fila('− números que no están en la base', k.no_cruzan, porTipo)}
    ${fila('= Llamadas a empresas', k.llamadas_a_empresas, `${num(k.nuevas || 0)} nuevas · ${num(k.ya_registradas || 0)} ya registradas`)}
    ${fila('&nbsp;&nbsp;asociadas a una muestra', k.asociadas_a_muestra)}
    ${fila('&nbsp;&nbsp;en Conciliación', k.en_conciliacion)}
    ${fila('&nbsp;&nbsp;sin muestra', k.sin_muestra, 'la empresa no está en una muestra activa o la llamada fue fuera de las fechas de campo')}
    ${fila('Teléfonos marcados', k.telefonos_marcados)}${fila('Empresas llamadas', k.empresas_llamadas)}</table>`;
}

function activarCorridas(ctx, corridas) {
  $$('[data-corrida-detalle]').forEach(b => b.onclick = () => {
    const c = corridas.find(x => x.id === +b.dataset.corridaDetalle);
    modal({ titulo: `Corrida #${c.id} — ${fechaHora(c.inicio)}`, ancho: 680, cuerpo: embudo(c),
      acciones: [...(ctx.puede('coordinador', 'jefe') && !c.dry_run ? [{ t: 'Exportar empresas', fn: () => { ctx.ir(hashEmpresas({ corrida_id: c.id }).slice(2)); return true; } }] : []),
        { t: 'Cerrar', cls: 'btn-orange' }] });
  });
}

// ── Empresas llamadas (R4) ──
const FILTROS_EMPRESAS = ['estudio_id', 'muestra_id', 'encuestador', 'desde', 'hasta', 'corrida_id', 'origen', 'solo_sin_muestra'];
function hashEmpresas(f) {
  const q = new URLSearchParams(Object.entries(f).filter(([k, v]) => FILTROS_EMPRESAS.includes(k) && v !== '' && v !== null && v !== undefined));
  return '#/actividad/empresas' + (q.toString() ? '?' + q : '');
}
function irEmpresas(ctx, f) { location.hash = hashEmpresas(f); }

export async function empresasLlamadas(ctx, params) {
  const f = Object.fromEntries(FILTROS_EMPRESAS.map(k => [k, params.get(k) || '']));
  const [r, estudios, muestras, origenes] = await Promise.all([api.get('/actividad/empresas-llamadas', f), api.get('/estudios'),
    api.get('/muestras'), api.get('/origenes-telefono')]);
  const nombreO = Object.fromEntries(origenes.map(o => [o.codigo, o.nombre]));
  const filtros = [
    f.corrida_id && `corrida #${esc(f.corrida_id)}`,
    f.estudio_id && `estudio ${esc((estudios.find(e => e.id === +f.estudio_id) || {}).nombre || '#' + f.estudio_id)}`,
    f.muestra_id && `muestra ${esc((muestras.find(m => m.id === +f.muestra_id) || {}).nombre || '#' + f.muestra_id)}`,
    f.origen && `origen ${esc(f.origen === '_sin_vinculo' ? 'sin vínculo vigente' : (nombreO[f.origen] || f.origen))}`,
    f.encuestador && `encuestador/a ${esc(f.encuestador)}`, f.desde && `desde ${fecha(f.desde)}`, f.hasta && `hasta ${fecha(f.hasta)}`,
  ].filter(Boolean);
  main().innerHTML = pageHeader('Empresas', 'llamadas', `${filtros.length ? 'Filtros: ' + filtros.join(' · ') : 'Todas las llamadas a empresas de la base'} ·
    <a class="link" href="#/actividad">volver a Actividad</a>`,
    `<button class="btn btn-orange" id="el-csv">Descargar CSV</button>`) +
    stats([[r.total, 'Empresas', 's-total'], [r.llamadas, 'Llamadas', 's-free'],
      [r.empresas.filter(e => !e.muestras).length, 'Sin muestra', '']]) +
    `<div class="toolbar mb"><label class="check"><input type="checkbox" id="el-sin" ${f.solo_sin_muestra ? 'checked' : ''} /> Solo empresas que no están en ninguna muestra</label></div>` +
    card(`${num(r.total)} empresas`, tabla([
      { t: 'RUT', f: e => `<a class="link mono" href="#/empresas/${e.rut}">${rutFmt(e.rut)}</a>` },
      { t: 'Razón social', f: e => `<span class="td-strong">${esc(e.razon_social || '—')}</span>` }, { t: 'Departamento', k: 'departamento' },
      { t: 'Teléfonos llamados', f: e => (e.telefonos || []).map(t => `<div class="small"><span class="mono">${esc(t.numero)}</span> <span class="muted">${esc(t.origenes.join(', ') || 'sin origen')}</span></div>`).join('') },
      { t: 'Llamadas', cls: 'num', f: e => num(e.llamadas) }, { t: 'Atendidas', cls: 'num', f: e => num(e.atendidas) },
      { t: 'Primera y última', f: e => `<div class="small">${fechaHora(e.primera)}</div><div class="small">${fechaHora(e.ultima)}</div>` },
      { t: 'Encuestadores', f: e => `<span class="small">${(e.encuestadores || []).map(esc).join(', ') || '—'}</span>` },
      { t: 'Estudio / muestra', f: e => (e.muestras || []).map(m => `<div class="small"><a class="link" href="#/muestras/${m.muestra_id}">${esc(m.estudio)} / ${esc(m.muestra)}</a></div>`).join('') || '<span class="muted small">sin muestra</span>' },
      { t: 'Estado del ítem', f: e => (e.muestras || []).map(m => `<div class="small">${Object.entries(m.estados || {}).map(([p, s]) => `${esc(p)}: ${est(s)}`).join(' ') || (m.liberado ? 'liberado' : 'no liberado')}</div>`).join('') || '—' },
    ], r.empresas, 'No hay llamadas a empresas con estos filtros'), '', true) +
    `<p class="small muted mt">Una fila por empresa de la base a la que se llamó. «Llamadas» arriba cuenta cada llamada una vez; una llamada a un número
     compartido por varias empresas aparece en la fila de cada una, así que la suma de las filas puede ser mayor. Atendidas: disposición ANSWERED en el CDR o, si la disposición no lo dice, duración facturada mayor a 0.
     No incluye contactos (nombres de personas). La descarga queda registrada en Auditoría.</p>`;
  $('#el-sin').onchange = (e) => irEmpresas(ctx, { ...f, solo_sin_muestra: e.target.checked ? 'true' : '' });
  $('#el-csv').onclick = async () => {
    const d = await api.descargar('/actividad/empresas-llamadas', { ...Object.fromEntries(Object.entries(f).filter(([, v]) => v)), formato: 'csv' });
    toast(`Descargado ${d.nombre} (${d.headers.get('X-Renglones')} empresas)`, 'ok');
  };
}
