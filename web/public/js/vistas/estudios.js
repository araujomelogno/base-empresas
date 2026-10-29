// Estudios, partes, muestras, reemplazos y CSV para uContact (R1.5, R1.6, R1.7)
import * as api from '../api.js';
import { $, $$, esc, main, toast, num, pct, fecha, fechaHora, est, etiqueta, pageHeader, stats, tabla, card, modal,
  confirmar, chips, activarChips, chipsSel } from '../ui.js';

const ESTRATIF = [['tamano', 'Tamaño'], ['departamento', 'Departamento'], ['naturaleza', 'Naturaleza'], ['ciiu2', 'CIIU 2 dígitos'], ['ciiu1', 'CIIU 1 dígito']];

function formParte(p = {}) {
  return `<div class="form-group"><label>Nombre de la parte</label><input type="text" data-p="nombre" value="${esc(p.nombre || '')}" placeholder="p. ej. Parte A — RRHH" /></div>
    <div class="form-row"><div class="form-group"><label>Survey ID de Alchemer</label><input type="text" data-p="survey_id" value="${esc(p.survey_id || '')}" /></div>
    <div class="form-group"><label>Respondente objetivo (área o cargo)</label><input type="text" data-p="respondente_objetivo" value="${esc(p.respondente_objetivo || '')}" /></div></div>
    <div class="form-group"><label>Link base de Alchemer</label><input type="text" data-p="link_base" value="${esc(p.link_base || '')}" placeholder="https://s.alchemer.com/s3/…" />
    <div class="field-hint">Al exportar se agregan las URL variables EC_ID_ITEM, EC_RUT y EC_TEL_USADO.</div></div>`;
}
const leerParte = (el) => Object.fromEntries($$('[data-p]', el).map(i => [i.dataset.p, i.value.trim() || null]));

export async function lista(ctx) {
  const estudios = await api.get('/estudios');
  main().innerHTML = pageHeader('Estudios', 'y muestras', 'Cada estudio tiene sus partes (una encuesta de Alchemer cada una) y sus muestras.',
    ctx.puede('jefe') ? `<button class="btn btn-orange" id="es-nuevo">+ Nuevo estudio</button>` : '') +
    card('Estudios', tabla([
      { t: 'Estudio', f: e => `<a class="link" href="#/estudios/${e.id}">${esc(e.nombre)}</a>` }, { t: 'Cliente', k: 'cliente' },
      { t: 'Campo', f: e => `${fecha(e.campo_desde)} → ${fecha(e.campo_hasta)}` }, { t: 'Partes', cls: 'num', k: 'n_partes' },
      { t: 'Muestras', cls: 'num', f: e => `${e.n_muestras}${e.muestras_activas ? ` <span class="est est-activa">${e.muestras_activas} activa${e.muestras_activas > 1 ? 's' : ''}</span>` : ''}` },
      { t: 'Creó', k: 'creado_por' },
    ], estudios, 'Todavía no hay estudios'), '', true);
  if ($('#es-nuevo')) $('#es-nuevo').onclick = async () => {
    const r = await modal({
      titulo: 'Nuevo estudio', ancho: 620, cuerpo: `
        <div class="form-group"><label>Nombre</label><input type="text" id="es-nombre" /></div>
        <div class="form-row"><div class="form-group"><label>Cliente</label><input type="text" id="es-cliente" /></div><div></div></div>
        <div class="form-row"><div class="form-group"><label>Campo desde</label><input type="date" id="es-desde" /></div>
        <div class="form-group"><label>Campo hasta</label><input type="date" id="es-hasta" /></div></div>
        <div class="card-header-title mb">Primera parte</div><div id="es-parte">${formParte()}</div>`,
      acciones: [{ t: 'Cancelar' }, { t: 'Crear', cls: 'btn-orange', fn: (b) => {
        const parte = leerParte($('#es-parte', b));
        return api.post('/estudios', { nombre: $('#es-nombre', b).value, cliente: $('#es-cliente', b).value || null,
          campo_desde: $('#es-desde', b).value, campo_hasta: $('#es-hasta', b).value, partes: parte.nombre ? [parte] : [] });
      } }],
    });
    if (r) ctx.ir('estudios/' + r.id);
  };
}

export async function detalle(ctx, id) {
  const e = await api.get('/estudios/' + id);
  main().innerHTML = pageHeader(e.nombre, '', `${esc(e.cliente || 'Sin cliente')} · campo del ${fecha(e.campo_desde)} al ${fecha(e.campo_hasta)}`,
    (ctx.puede('jefe') ? `<button class="btn btn-outline" id="es-editar">Editar</button>` : '') +
    (ctx.puede('jefe') ? `<button class="btn btn-orange" id="es-muestra">+ Nueva muestra</button>` : '')) +
    card('Partes', tabla([
      { t: 'Parte', f: p => `<span class="td-strong">${esc(p.nombre)}</span>` }, { t: 'Survey ID', k: 'survey_id' },
      { t: 'Respondente objetivo', k: 'respondente_objetivo' },
      { t: 'Link base', f: p => p.link_base ? `<span class="small mono">${esc(p.link_base)}</span>` : '<span class="muted">—</span>' },
      { t: 'Plantilla .sav', f: p => p.tiene_plantilla ? est('ok', 'sí') : est('pendiente', 'no') },
      { t: 'Estados', f: p => Object.entries(p.estados || {}).map(([s, n]) => est(s, `${etiqueta(s)} ${n}`)).join(' ') || '—' },
      { t: '', f: p => ctx.puede('jefe') ? `<button class="btn btn-outline btn-sm" data-editar="${p.id}">Editar</button>` : '' },
    ], e.partes, 'Sin partes'), ctx.puede('jefe') ? `<button class="btn btn-outline btn-sm" id="es-parte">+ Parte</button>` : '', true) +
    card('Muestras', tabla([
      { t: 'Muestra', f: m => `<a class="link" href="#/muestras/${m.id}">${esc(m.nombre)}</a>` }, { t: 'Estado', f: m => est(m.estado) },
      { t: 'Ítems', cls: 'num', k: 'n_items' }, { t: 'Semilla', f: m => `<span class="mono small">${m.semilla ?? '—'}</span>` },
      { t: 'Config.', f: m => m.config_version ? 'v' + m.config_version : '—' }, { t: 'Sorteada', f: m => fechaHora(m.sorteada) },
    ], e.muestras, 'Sin muestras'), '', true);
  const recargar = () => detalle(ctx, id);
  if ($('#es-muestra')) $('#es-muestra').onclick = () => ctx.ir(`estudios/${id}/nueva-muestra`);
  if ($('#es-parte')) $('#es-parte').onclick = async () => {
    const r = await modal({ titulo: 'Nueva parte', ancho: 620, cuerpo: `<div id="pp">${formParte()}</div>`,
      acciones: [{ t: 'Cancelar' }, { t: 'Crear', cls: 'btn-orange', fn: (b) => api.post(`/estudios/${id}/partes`, leerParte(b)) }] });
    if (r) recargar();
  };
  $$('[data-editar]').forEach(btn => btn.onclick = async () => {
    const p = e.partes.find(x => x.id === +btn.dataset.editar);
    const r = await modal({ titulo: 'Editar parte', ancho: 620, cuerpo: formParte(p),
      acciones: [{ t: 'Cancelar' }, { t: 'Guardar', cls: 'btn-orange', fn: (b) => api.patch(`/partes/${p.id}`, leerParte(b)) }] });
    if (r) recargar();
  });
  if ($('#es-editar')) $('#es-editar').onclick = async () => {
    const r = await modal({ titulo: 'Editar estudio', cuerpo: `
      <div class="form-group"><label>Nombre</label><input type="text" id="ee-n" value="${esc(e.nombre)}" /></div>
      <div class="form-group"><label>Cliente</label><input type="text" id="ee-c" value="${esc(e.cliente || '')}" /></div>
      <div class="form-row"><div class="form-group"><label>Campo desde</label><input type="date" id="ee-d" value="${e.campo_desde}" /></div>
      <div class="form-group"><label>Campo hasta</label><input type="date" id="ee-h" value="${e.campo_hasta}" /></div></div>
      <p class="field-hint">Las fechas de campo definen qué llamadas del CDR se asocian a los ítems de la muestra.</p>`,
    acciones: [{ t: 'Cancelar' }, { t: 'Guardar', cls: 'btn-orange', fn: (b) => api.patch('/estudios/' + id, {
      nombre: $('#ee-n', b).value, cliente: $('#ee-c', b).value, campo_desde: $('#ee-d', b).value, campo_hasta: $('#ee-h', b).value }) }] });
    if (r) recargar();
  };
}

// ── Armado de la muestra ──
export async function nuevaMuestra(ctx, estudioId) {
  const [e, v] = await Promise.all([api.get('/estudios/' + estudioId), api.get('/empresas/valores')]);
  main().innerHTML = pageHeader('Nueva muestra', '— ' + e.nombre, 'Definí filtros y estratos, mirá el marco disponible y después sorteá. El sorteo congela el marco y guarda la semilla y la versión de configuración.') +
    `<div class="grid-2">${card('1 · Filtros', `
      <div class="form-group"><label>Tamaño</label>${chips('tamano', v.tamano)}</div>
      <div class="form-group"><label>Departamento</label>${chips('departamento', v.departamento)}</div>
      <div class="form-group"><label>Naturaleza jurídica</label>${chips('naturaleza', v.naturaleza.filter(n => !n.excluida).map(n => [n.codigo, n.nombre]))}</div>
      <div class="form-group"><label>CIIU (prefijos)</label><input type="text" id="m-ciiu" placeholder="p. ej. 47, 56, 1071" />
        <div class="field-hint">Vacío = todos. Sin filtros, entra toda la base disponible.</div></div>`)}
    ${card('2 · Estratos', `<div class="form-group"><label>Estratificar por</label>${chips('por', ESTRATIF)}</div>
      <button class="btn btn-dark" id="m-marco">Ver marco disponible</button><div id="m-marco-res" class="mt"></div>`)}</div>
    <div id="m-estratos"></div>`;
  activarChips(main());
  const criteriosBase = () => {
    const f = {};
    ['tamano', 'departamento', 'naturaleza'].forEach(k => { const s = chipsSel(main(), k); if (s.length) f[k] = s; });
    const ciiu = $('#m-ciiu').value.split(/[,\s]+/).filter(Boolean);
    if (ciiu.length) f.ciiu = ciiu;
    return { filtros: f, estratificar_por: chipsSel(main(), 'por') };
  };
  $('#m-marco').onclick = async () => {
    const c = criteriosBase();
    const r = await api.post('/muestras/marco', c);
    const ex = Object.entries(r.exclusiones).filter(([k]) => k !== 'total_excluidas');
    $('#m-marco-res').innerHTML = stats([[r.universo, 'Cumplen filtros', 's-total'], [r.marco, 'Disponibles', 's-ok'],
      [r.exclusiones.total_excluidas || 0, 'Excluidas', 's-bad']]) +
      (ex.length ? `<div class="small"><strong>Excluidas por regla</strong> (una empresa puede caer en varias): ${ex.map(([k, n]) => `${esc(etiqueta(k))} <strong>${num(n)}</strong>`).join(' · ')}</div>` : '');
    $('#m-estratos').innerHTML = card('3 · Tamaño por estrato y reemplazos', `
      <div class="toolbar mb"><span class="small muted">Aplicar a todos:</span><input type="number" id="m-n-todos" placeholder="n" style="width:90px" />
        <input type="number" id="m-r-todos" placeholder="reemplazos" style="width:120px" /><button class="btn btn-outline btn-sm" id="m-aplicar">Aplicar</button></div>
      ${tabla([{ t: 'Estrato', f: x => `<span class="td-strong">${esc(x.estrato)}</span>` }, { t: 'Disponibles', cls: 'num', f: x => num(x.disponibles) },
        { t: 'Titulares', f: x => `<input type="number" min="0" data-n="${esc(x.estrato)}" value="0" style="width:100px" />` },
        { t: 'Reemplazos', f: x => `<input type="number" min="0" data-r="${esc(x.estrato)}" value="0" style="width:100px" />` }], r.estratos, 'No hay empresas disponibles con esos filtros')}
      <div class="form-row mt"><div class="form-group"><label>Nombre de la muestra</label><input type="text" id="m-nombre" value="Muestra ${e.muestras.length + 1}" /></div>
      <div class="form-group"><label>Semilla (opcional)</label><input type="number" id="m-semilla" placeholder="se genera al azar" />
      <div class="field-hint">Con la misma semilla y el mismo marco, el sorteo da la misma lista.</div></div></div>
      <button class="btn btn-orange" id="m-sortear">Crear y sortear</button>`);
    $('#m-aplicar').onclick = () => {
      $$('[data-n]').forEach(i => { if ($('#m-n-todos').value !== '') i.value = $('#m-n-todos').value; });
      $$('[data-r]').forEach(i => { if ($('#m-r-todos').value !== '') i.value = $('#m-r-todos').value; });
    };
    if ($('#m-sortear')) $('#m-sortear').onclick = async () => {
      const estratos = $$('[data-n]').map(i => ({ estrato: i.dataset.n, n: +i.value || 0, reemplazos: +($(`[data-r="${CSS.escape(i.dataset.n)}"]`).value) || 0 }))
        .filter(x => x.n || x.reemplazos);
      if (!estratos.length) return toast('Indicá el tamaño de al menos un estrato', 'err');
      const total = estratos.reduce((a, x) => a + x.n, 0);
      if (!await confirmar('Sortear muestra', `Se sortean ${num(total)} titulares y ${num(estratos.reduce((a, x) => a + x.reemplazos, 0))} reemplazos en ${estratos.length} estratos. Las empresas sorteadas quedan bloqueadas para otras muestras mientras esta esté activa.`, 'Sortear')) return;
      const m = await api.post('/muestras', { estudio_id: +estudioId, nombre: $('#m-nombre').value, criterios: { ...c, estratos } });
      const semilla = $('#m-semilla').value;
      await api.post(`/muestras/${m.id}/sortear`, { semilla: semilla ? +semilla : null });
      toast('Muestra sorteada', 'ok');
      ctx.ir('muestras/' + m.id);
    };
  };
}

// ── Muestra ──
export async function muestra(ctx, id) {
  const m = await api.get('/muestras/' + id);
  const r = m.resultado || {};
  const tot = (k) => m.avance.reduce((a, x) => a + (x[k] || 0), 0);
  main().innerHTML = pageHeader(m.nombre, '', `<a class="link" href="#/estudios/${m.estudio_id}">${esc(m.estudio_nombre)}</a> · ${est(m.estado)} · semilla <span class="mono">${m.semilla ?? '—'}</span> · configuración v${m.config_version ?? '—'} · snapshot #${m.snapshot_id ?? '—'}`,
    `<button class="btn btn-outline" id="mu-verificar">Verificar reproducibilidad</button>` +
    (m.estado === 'activa' && ctx.puede('jefe') ? `<button class="btn btn-outline btn-del" id="mu-cerrar">Cerrar muestra</button>` : '')) +
    (r.avisos && r.avisos.length ? `<div class="alert alert-warn"><div><strong>Avisos del sorteo</strong><ul class="aviso-lista">${r.avisos.map(a => `<li>${esc(a)}</li>`).join('')}</ul></div></div>` : '') +
    stats([[tot('titulares'), 'Titulares', 's-total'], [tot('liberados'), 'Liberados', 's-free'], [tot('llamados'), 'Con llamadas', ''],
      [tot('completas'), 'Con alguna completa', 's-ok'], [tot('rechazos'), 'Rechazos', 's-bad'], [r.marco, 'Marco congelado', '']]) +
    `<div class="grid-2">${card('Exclusiones al sortear', tabla([{ t: 'Regla', f: x => esc(etiqueta(x[0])) }, { t: 'Empresas', cls: 'num', f: x => num(x[1]) }],
      Object.entries(r.exclusiones || {}).sort((a, b) => b[1] - a[1]), 'Ninguna') + `<div class="card-body small muted">Universo que cumplía los filtros: <strong>${num(r.universo)}</strong> · marco disponible: <strong>${num(r.marco)}</strong></div>`, '', true)}
    ${card('Exportar a uContact', m.estado === 'activa' && ctx.puede('coordinador', 'jefe') ? `
      <div class="form-group"><label>Parte</label><select class="fselect" id="mu-parte">${m.partes.map(p => `<option value="${p.id}">${esc(p.nombre)}</option>`).join('')}</select></div>
      <div id="mu-csv-res" class="small muted mb"></div>
      <button class="btn btn-orange" id="mu-csv">Descargar CSV</button>
      <p class="field-hint mt">Un renglón por teléfono discable de cada ítem liberado y pendiente en la parte. Nunca incluye intermediarios, inexistentes, "no corresponde" ni no llamar.${ctx.me.exportar_contactos ? '' : ' Tu usuario no tiene permiso para exportar contactos personales: la columna de contacto sale vacía.'}</p>`
      : '<div class="muted small">Solo se exporta una muestra activa, con rol coordinador o jefe de proyecto.</div>')}</div>` +
    card('Avance por estrato', tabla([
      { t: 'Estrato', f: x => `<span class="td-strong">${esc(x.estrato)}</span>` }, { t: 'Titulares', cls: 'num', k: 'titulares' },
      { t: 'Reemplazos (lib./total)', cls: 'num', f: x => `${x.reemplazos_liberados} / ${x.reemplazos}` }, { t: 'Llamados', cls: 'num', k: 'llamados' },
      { t: 'Contactabilidad', cls: 'num', f: x => pct(x.contactados, x.liberados) }, { t: 'Completas', cls: 'num', k: 'completas' },
      { t: 'Tasa de respuesta', cls: 'num', f: x => pct(x.completas, x.liberados) }, { t: 'Rechazos', cls: 'num', k: 'rechazos' },
      { t: 'Fuera de marco', cls: 'num', k: 'fuera_de_marco' },
      { t: '', f: x => m.estado === 'activa' && ctx.puede('jefe') && x.reemplazos > x.reemplazos_liberados
        ? `<button class="btn btn-outline btn-sm" data-liberar="${esc(x.estrato)}" data-max="${x.reemplazos - x.reemplazos_liberados}">Liberar reemplazos</button>` : '' },
    ], m.avance), '', true) +
    `<div class="card mt"><div class="card-header"><div class="card-header-title">Ítems</div><div class="gap">
      <select class="fselect" id="mu-estrato" style="width:auto"><option value="">Todos los estratos</option>${m.avance.map(x => `<option>${esc(x.estrato)}</option>`).join('')}</select></div></div>
      <div class="card-body tight" id="mu-items"></div></div>`;

  const items = async () => {
    const lista = await api.get(`/muestras/${id}/items`, { estrato: $('#mu-estrato').value });
    $('#mu-items').innerHTML = tabla([
      { t: 'Ítem', cls: 'num', k: 'id' }, { t: 'Estrato', k: 'estrato' }, { t: 'Orden', cls: 'num', k: 'orden' }, { t: 'Rol', f: i => est(i.rol) },
      { t: 'Empresa', f: i => `<a class="link" href="#/empresas/${i.rut}">${esc(i.razon_social || i.rut)}</a>` },
      { t: 'Liberado', f: i => i.liberado ? `sí <span class="small muted">${esc(i.liberado_motivo || '')}</span>` : 'no' },
      { t: 'Intentos', cls: 'num', k: 'intentos' },
      { t: 'Estado por parte', f: i => Object.entries(i.estados || {}).map(([p, s]) => `<span class="small muted">${esc(p)}:</span> ${est(s)}`).join(' ') || '—' },
    ], lista, 'Sin ítems');
  };
  $('#mu-estrato').onchange = items;
  items();
  const recargar = () => muestra(ctx, id);
  $('#mu-verificar').onclick = async () => {
    const v = await api.post(`/muestras/${id}/verificar`);
    v.reproducible ? toast(`Reproducible: el re-sorteo con la semilla ${v.semilla} y el snapshot #${v.snapshot_id} da los mismos ${v.items} ítems en el mismo orden`, 'ok')
      : toast('¡El re-sorteo no coincide! Revisar auditoría', 'err');
  };
  if ($('#mu-cerrar')) $('#mu-cerrar').onclick = async () => {
    if (!await confirmar('Cerrar muestra', 'Las empresas dejan de estar bloqueadas por esta muestra y ya no se puede exportar ni liberar reemplazos.', 'Cerrar', 'btn-danger')) return;
    await api.post(`/muestras/${id}/cerrar`); recargar();
  };
  if ($('#mu-csv')) {
    const resumen = async () => {
      const s = await api.get(`/muestras/${id}/csv/resumen`, { parte_id: $('#mu-parte').value });
      $('#mu-csv-res').innerHTML = `${num(s.renglones)} renglones para ${num(s.items)} de ${num(s.items_pendientes)} ítems pendientes en la parte · ${s.items_sin_telefono ? `<strong>${num(s.items_sin_telefono)} sin teléfono discable</strong>` : "todos tienen teléfono"}`;
    };
    $('#mu-parte').onchange = resumen;
    resumen();
    $('#mu-csv').onclick = async () => {
      const r = await api.descargar(`/muestras/${id}/csv`, { parte_id: $('#mu-parte').value });
      toast(`Descargado ${r.nombre} (${r.headers.get('X-Renglones')} renglones)`, 'ok');
    };
  }
  $$('[data-liberar]').forEach(b => b.onclick = async () => {
    const res = await modal({ titulo: `Liberar reemplazos — ${b.dataset.liberar}`, cuerpo: `
      <p class="small muted mb">Se liberan en el orden sorteado. Queda registrado quién los liberó y por qué.</p>
      <div class="form-group"><label>Cantidad (quedan ${b.dataset.max})</label><input type="number" id="lb-n" min="1" max="${b.dataset.max}" value="1" /></div>
      <div class="form-group"><label>Motivo</label><input type="text" id="lb-m" placeholder="p. ej. 3 rechazos y 2 fuera de marco" /></div>`,
    acciones: [{ t: 'Cancelar' }, { t: 'Liberar', cls: 'btn-orange', fn: (x) => api.post(`/muestras/${id}/liberar`, {
      estrato: b.dataset.liberar, cantidad: +$('#lb-n', x).value, motivo: $('#lb-m', x).value }) }] });
    if (res) { toast(`Liberados ${res.liberados} reemplazos`, 'ok'); recargar(); }
  });
}
