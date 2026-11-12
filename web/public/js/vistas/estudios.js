// Estudios, partes, muestras, reemplazos y CSV para uContact (R1.5, R1.6, R1.7)
import * as api from '../api.js';
import { $, $$, esc, main, toast, num, pct, fecha, fechaHora, rutFmt, est, estDe, etiqueta, pageHeader, stats, tabla, card, modal,
  confirmar, confirmarEscrito, seguirTarea, chips, activarChips, chipsSel } from '../ui.js';

const pl = (n, uno, varios) => `${num(n)} ${n === 1 ? uno : varios}`;

// Borrado definitivo (solo administrador): corre como tarea y se sigue en pantalla
async function borrarConTarea(url, titulo, texto) {
  const { tarea_id } = await api.del(url);
  main().innerHTML = pageHeader(titulo, '', 'Borrando…') + card(titulo, '<div id="b-prog"></div>');
  return (await seguirTarea(tarea_id, $('#b-prog'), { texto })).resultado || {};
}

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
    (ctx.puede('jefe') ? `<button class="btn btn-orange" id="es-muestra">+ Nueva muestra</button>` : '') +
    (ctx.puede() ? `<button class="btn btn-danger" id="es-borrar">Borrar estudio</button>` : '')) +
    card('Partes', tabla([
      { t: 'Parte', f: p => `<span class="td-strong">${esc(p.nombre)}</span>` }, { t: 'Survey ID', k: 'survey_id' },
      { t: 'Respondente objetivo', k: 'respondente_objetivo' },
      { t: 'Link base', f: p => p.link_base ? `<span class="small mono">${esc(p.link_base)}</span>` : '<span class="muted">—</span>' },
      { t: 'Plantilla .sav', f: p => p.tiene_plantilla ? est('ok', 'sí') : est('pendiente', 'no') },
      { t: 'Completas (.sav)', cls: 'num', f: p => `${num(p.completas_sav)}${p.completas_sin_asociar ? `<div class="small muted">${num(p.completas_sin_asociar)} sin asociar</div>` : ''}` },
      { t: 'Estados de los ítems', f: p => Object.entries(p.estados || {}).map(([s, n]) => est(s, `${etiqueta(s)} ${n}`)).join(' ') || '—' },
      { t: '', f: p => ctx.puede('jefe') ? `<button class="btn btn-outline btn-sm" data-editar="${p.id}">Editar</button>` : '' },
    ], e.partes, 'Sin partes'), ctx.puede('jefe') ? `<button class="btn btn-outline btn-sm" id="es-parte">+ Parte</button>` : '', true) +
    card('Muestras', tabla([
      { t: 'Muestra', f: m => `<a class="link" href="#/muestras/${m.id}">${esc(m.nombre)}</a>` }, { t: 'Estado', f: m => estDe('muestra', m.estado) },
      { t: 'Ítems', cls: 'num', k: 'n_items' }, { t: 'Semilla', f: m => `<span class="mono small">${m.semilla ?? '—'}</span>` },
      { t: 'Config.', f: m => m.config_version ? 'v' + m.config_version : '—' }, { t: 'Sorteada', f: m => fechaHora(m.sorteada) },
    ], e.muestras, 'Sin muestras'), '', true);
  const recargar = () => detalle(ctx, id);
  if ($('#es-borrar')) $('#es-borrar').onclick = async () => {
    const n = await api.get(`/estudios/${id}/borrado`);
    const ok = await confirmarEscrito({ titulo: 'Borrar estudio', palabra: e.nombre, normalizar: (s) => s.trim(),
      ayuda: `Escribí el nombre del estudio, <strong>${esc(e.nombre)}</strong>, para confirmar.`,
      cuerpo: `<p>Se elimina el estudio <strong>${esc(e.nombre)}</strong> con:</p><ul class="modal-conteos">
        <li>${pl(n.partes, 'parte', 'partes')} y ${pl(n.muestras, 'muestra', 'muestras')} con ${pl(n.items, 'ítem', 'ítems')};</li>
        <li>${pl(n.ingestas_sav, 'ingesta .sav', 'ingestas .sav')} con ${pl(n.filas_sav, 'fila', 'filas')}, y sus archivos;</li>
        <li>${pl(n.intentos, 'intento', 'intentos')} del CDR asociados a sus ítems.</li></ul>
        <p>Lo que la base aprendió de las empresas <strong>se conserva</strong>: contactos y teléfonos nuevos, calidad de los números,
        historia de valores y último contacto efectivo (enfriamiento). <strong>No se puede deshacer.</strong> Queda el registro en Auditoría.</p>` });
    if (!ok) return;
    try {
      const r = await borrarConTarea(`/estudios/${id}`, 'Borrar estudio', 'Borrando el estudio');
      toast(`Estudio borrado: ${num(r.muestras.length)} muestras, ${num(r.items)} ítems, ${num(r.ingestas_sav)} ingestas .sav`, 'ok');
      ctx.ir('estudios');
    } catch (err) { toast(err.message, 'err'); recargar(); }
  };
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
function filtroAtributo(a) {
  const id = `ma-${a.clave}`;
  if (a.tipo === 'lista') return `<div class="form-group"><label>${esc(a.nombre)}</label>${chips('attr:' + a.clave, a.opciones)}</div>`;
  if (a.tipo === 'texto') return `<div class="form-group"><label>${esc(a.nombre)} (contiene)</label><input type="text" id="${id}-contiene" /></div>`;
  const tipo = a.tipo === 'fecha' ? 'date' : 'number';
  return `<div class="form-group"><label>${esc(a.nombre)}</label><div class="form-row">
    <input type="${tipo}" id="${id}-desde" placeholder="desde" /><input type="${tipo}" id="${id}-hasta" placeholder="hasta" /></div></div>`;
}

function leerFiltrosAtributo(atributos) {
  const salida = {};
  for (const a of atributos) {
    let f = null;
    if (a.tipo === 'lista') { const s = chipsSel(main(), 'attr:' + a.clave); if (s.length) f = { valores: s }; }
    else if (a.tipo === 'texto') { const t = $(`#ma-${a.clave}-contiene`).value.trim(); if (t) f = { contiene: t }; }
    else {
      const d = $(`#ma-${a.clave}-desde`).value, h = $(`#ma-${a.clave}-hasta`).value;
      if (d || h) { f = {}; if (d) f.desde = d; if (h) f.hasta = h; }
    }
    if (f) salida[a.clave] = f;
  }
  return salida;
}

export async function nuevaMuestra(ctx, estudioId) {
  const [e, v, atributos, origenes] = await Promise.all([api.get('/estudios/' + estudioId), api.get('/empresas/valores'),
    api.get('/atributos', { activos: true }), api.get('/origenes-telefono', { activos: true })]);
  const filtrables = atributos.filter(a => a.filtrable);
  const estratif = [...ESTRATIF, ...atributos.filter(a => a.estratificable).map(a => ['atributo.' + a.clave, a.nombre])];
  main().innerHTML = pageHeader('Nueva muestra', '— ' + e.nombre, 'Definí filtros y estratos, mirá el marco disponible y después sorteá. El sorteo congela el marco y guarda la semilla y la versión de configuración.') +
    `<div class="grid-2">${card('1 · Filtros', `
      <div class="form-group"><label>Tamaño</label>${chips('tamano', v.tamano)}</div>
      <div class="form-group"><label>Departamento</label>${chips('departamento', v.departamento)}</div>
      <div class="form-group"><label>Naturaleza jurídica</label>${chips('naturaleza', v.naturaleza.filter(n => !n.excluida).map(n => [n.codigo, n.nombre]))}</div>
      <div class="form-group"><label>CIIU (prefijos)</label><input type="text" id="m-ciiu" placeholder="p. ej. 47, 56, 1071" />
        <div class="field-hint">Vacío = todos. Sin filtros, entra toda la base disponible.</div></div>
      ${filtrables.length ? `<div class="card-header-title mb mt">Atributos</div>${filtrables.map(filtroAtributo).join('')}` : ''}
      <div class="form-group mt"><label>Origen de los teléfonos</label>${chips('origenes', origenes.map(o => [o.codigo, o.nombre]))}
        <div class="field-hint">Solo empresas con al menos un teléfono discable de estos orígenes. Sin selección, no filtra.</div></div>`)}
    ${card('2 · Estratos', `<div class="form-group"><label>Estratificar por</label>${chips('por', estratif)}</div>
      <button class="btn btn-dark" id="m-marco">Ver marco disponible</button><div id="m-marco-res" class="mt"></div>`)}</div>
    <div id="m-estratos"></div>`;
  activarChips(main());
  const criteriosBase = () => {
    const f = {};
    ['tamano', 'departamento', 'naturaleza'].forEach(k => { const s = chipsSel(main(), k); if (s.length) f[k] = s; });
    const ciiu = $('#m-ciiu').value.split(/[,\s]+/).filter(Boolean);
    if (ciiu.length) f.ciiu = ciiu;
    return { filtros: f, atributos: leerFiltrosAtributo(filtrables), origenes: chipsSel(main(), 'origenes'),
      estratificar_por: chipsSel(main(), 'por') };
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
// F1.1: la lista a la que lleva el contador «Muestras activas» de Inicio
export async function muestras(ctx, params) {
  const estado = params.get('estado') || 'activa';
  const lista = await api.get('/muestras', { estado });
  const titulo = { activa: 'Muestras activas', cerrada: 'Muestras cerradas', borrador: 'Muestras en borrador' }[estado] || 'Muestras';
  const sinEmpresas = lista.filter(m => m.estado === 'activa' && !m.n_items).length;
  main().innerHTML = pageHeader(titulo, '', 'Las muestras activas bloquean a sus empresas para otras muestras.') +
    (sinEmpresas ? `<div class="alert alert-warn"><span><strong>${sinEmpresas === 1 ? 'Una muestra activa no tiene' : `${num(sinEmpresas)} muestras activas no tienen`} empresas:</strong>
      se borraron todas sus empresas (borrar empresa o borrar carga). Cerrala o borrala desde acá.</span></div>` : '') +
    card(titulo, tabla([
      { t: 'Estudio', f: m => `<a class="link" href="#/estudios/${m.estudio_id}">${esc(m.estudio_nombre)}</a>` },
      { t: 'Muestra', f: m => `<a class="link td-strong" href="#/muestras/${m.id}">${esc(m.nombre)}</a>` },
      { t: 'Estado', f: m => (m.estado === 'activa' && !m.n_items ? est('sospechoso', 'activa, sin empresas') : estDe('muestra', m.estado)) +
        (['error', 'cancelada'].includes(m.tarea_borrado) ? ` ${est('error', 'borrado sin terminar')}` : '') },
      { t: 'Ítems', cls: 'num', f: m => num(m.n_items) }, { t: 'Liberados', cls: 'num', f: m => num(m.n_liberados) },
      { t: 'Sorteada', f: m => m.sorteada ? fechaHora(m.sorteada) : '—' },
      { t: '', f: m => m.estado === 'activa' && !m.n_items ? `<span class="gap">
        ${ctx.puede('jefe') ? `<button class="btn btn-outline btn-sm" data-cerrar="${m.id}">Cerrar</button>` : ''}
        ${ctx.puede() ? `<button class="btn btn-danger btn-sm" data-borrar="${m.id}" data-nombre="${esc(m.nombre)}">Borrar</button>` : ''}</span>` : '' },
    ], lista, estado === 'activa' ? 'No hay muestras activas' : 'No hay muestras'), '', true);
  $$('[data-cerrar]').forEach(b => b.onclick = async () => {
    if (!await confirmar('Cerrar muestra', 'La muestra no tiene empresas. Al cerrarla deja de contar como activa.', 'Cerrar', 'btn-danger')) return;
    await api.post(`/muestras/${b.dataset.cerrar}/cerrar`);
    toast('Muestra cerrada', 'ok'); muestras(ctx, params);
  });
  $$('[data-borrar]').forEach(b => b.onclick = async () => {
    const ok = await confirmarEscrito({ titulo: `Borrar muestra «${b.dataset.nombre}»`, palabra: 'BORRAR',
      cuerpo: '<p>La muestra no tiene empresas. Se elimina junto con su marco congelado. <strong>No se puede deshacer.</strong> Queda el registro en Auditoría.</p>' });
    if (!ok) return;
    try {
      await borrarConTarea(`/muestras/${b.dataset.borrar}`, 'Borrar muestra', 'Borrando la muestra');
      toast('Muestra borrada', 'ok');
    } catch (err) { toast(err.message, 'err'); }
    muestras(ctx, params);
  });
}

function criteriosTexto(c, atributos, origenes) {
  const nombreA = Object.fromEntries(atributos.map(a => [a.clave, a.nombre]));
  const nombreO = Object.fromEntries(origenes.map(o => [o.codigo, o.nombre]));
  const partes = Object.entries(c.filtros || {}).map(([k, v]) => `${etiqueta(k)}: ${[].concat(v).join(', ')}`);
  Object.entries(c.atributos || {}).forEach(([k, f]) => partes.push(`${nombreA[k] || k}: ${f.valores ? f.valores.join(', ')
    : f.contiene ? 'contiene «' + f.contiene + '»' : [f.desde ? 'desde ' + f.desde : '', f.hasta ? 'hasta ' + f.hasta : ''].filter(Boolean).join(' ')}`));
  if ((c.origenes || []).length) partes.push(`teléfonos de: ${c.origenes.map(o => nombreO[o] || o).join(', ')}`);
  if ((c.estratificar_por || []).length) partes.push(`estratos: ${c.estratificar_por.map(k => k.startsWith('atributo.') ? (nombreA[k.slice(9)] || k) : (Object.fromEntries(ESTRATIF)[k] || etiqueta(k))).join(' × ')}`);
  return partes.length ? partes.map(esc).join(' · ') : 'Sin filtros: toda la base disponible';
}

export async function muestra(ctx, id) {
  const [m, atributos, origenes] = await Promise.all([api.get('/muestras/' + id), api.get('/atributos'), api.get('/origenes-telefono')]);
  const exp = m.exportacion || { origenes: [], orden: 'prioridad' };
  const r = m.resultado || {};
  const tot = (k) => m.avance.reduce((a, x) => a + (x[k] || 0), 0);
  main().innerHTML = pageHeader(m.nombre, '', `<a class="link" href="#/estudios/${m.estudio_id}">${esc(m.estudio_nombre)}</a> · ${estDe('muestra', m.estado)} · semilla <span class="mono">${m.semilla ?? '—'}</span> · configuración v${m.config_version ?? '—'} · snapshot #${m.snapshot_id ?? '—'}`,
    `<button class="btn btn-outline" id="mu-verificar">Verificar reproducibilidad</button>` +
    (m.estado === 'activa' && ctx.puede('jefe') ? `<button class="btn btn-outline btn-del" id="mu-cerrar">Cerrar muestra</button>` : '') +
    (ctx.puede() ? `<button class="btn btn-danger" id="mu-borrar">Borrar muestra</button>` : '')) +
    (m.borrado_fallido ? `<div class="alert alert-error"><span><strong>El borrado de esta muestra no terminó</strong>
      (tarea #${m.borrado_fallido.id}, ${esc(etiqueta(m.borrado_fallido.estado))}${m.borrado_fallido.terminado ? ` el ${fechaHora(m.borrado_fallido.terminado)}` : ''}${m.borrado_fallido.error ? `: ${esc(m.borrado_fallido.error)}` : ''}).
      La muestra sigue existiendo${m.estado === 'activa' ? ' y cuenta como activa' : ''}. Volvé a usar «Borrar muestra».</span></div>` : '') +
    (m.estado === 'activa' && !m.avance.length ? `<div class="alert alert-warn"><span><strong>Activa, sin empresas:</strong> se borraron todas sus empresas. Cerrala o borrala para que deje de contar como activa.</span></div>` : '') +
    (m.n_items_borrados ? `<div class="alert alert-warn"><span><strong>${num(m.n_items_borrados)} empresa${m.n_items_borrados > 1 ? 's' : ''}
      borrada${m.n_items_borrados > 1 ? 's' : ''} después del sorteo.</strong> El marco congelado no cambia: «Verificar reproducibilidad» las tiene en cuenta.</span></div>` : '') +
    (r.avisos && r.avisos.length ? `<div class="alert alert-warn"><div><strong>Avisos del sorteo</strong><ul class="aviso-lista">${r.avisos.map(a => `<li>${esc(a)}</li>`).join('')}</ul></div></div>` : '') +
    stats([[tot('titulares'), 'Titulares', 's-total'], [tot('liberados'), 'Liberados', 's-free'], [tot('llamados'), 'Con llamadas', ''],
      [tot('completas'), 'Con alguna completa', 's-ok'], [tot('rechazos'), 'Rechazos', 's-bad'], [r.marco, 'Marco congelado', '']]) +
    `<div class="grid-2">${card('Exclusiones al sortear', tabla([{ t: 'Regla', f: x => esc(etiqueta(x[0])) }, { t: 'Empresas', cls: 'num', f: x => num(x[1]) }],
      Object.entries(r.exclusiones || {}).sort((a, b) => b[1] - a[1]), 'Ninguna') + `<div class="card-body small muted">Universo que cumplía los filtros: <strong>${num(r.universo)}</strong> · marco disponible: <strong>${num(r.marco)}</strong><br>Criterios: ${criteriosTexto(m.criterios || {}, atributos, origenes)}</div>`, '', true)}
    ${card('Exportar a uContact', m.estado === 'activa' && ctx.puede('coordinador', 'jefe') ? `
      <div class="form-group"><label>Parte</label><select class="fselect" id="mu-parte">${m.partes.map(p => `<option value="${p.id}">${esc(p.nombre)}</option>`).join('')}</select></div>
      <div class="form-group"><label>Orígenes a exportar</label>${chips('exp-origenes', origenes.filter(o => o.activo || exp.origenes.includes(o.codigo)).map(o => [o.codigo, o.nombre]), exp.origenes)}
        <div class="field-hint">Sin selección se exportan todos. Un teléfono con varios orígenes pasa si alguno está elegido.</div></div>
      <div class="form-group"><label>Orden de los teléfonos</label><select class="fselect" id="mu-orden">
        <option value="prioridad" ${exp.orden === 'prioridad' ? 'selected' : ''}>Prioridad de origen y, dentro de cada origen, verificados primero</option>
        <option value="verificados" ${exp.orden === 'verificados' ? 'selected' : ''}>Verificados primero, sin mirar el origen</option></select></div>
      <details class="map-bloque" id="mu-incluir"><summary>Qué incluir</summary>
        <div class="form-group"><label>Atributos de empresa <span class="small muted">(<a class="link" href="javascript:void 0" data-todos="atr">todos</a> · <a class="link" href="javascript:void 0" data-ninguno="atr">ninguno</a>)</span></label>
          ${atributos.filter(a => (a.ambito || 'empresa') === 'empresa' && a.activo).map(a => `<label class="check"><input type="checkbox" data-inc-atr="${esc(a.clave)}" ${exp.atributos_excluidos.includes(a.clave) ? '' : 'checked'} /> ${esc(a.nombre)}</label>`).join('') || '<div class="small muted">No hay atributos de empresa activos.</div>'}</div>
        <div class="form-group"><label>Números</label><select class="fselect" id="mu-numeros">
          <option value="discables" ${exp.numeros === 'discables' ? 'selected' : ''}>Todos los discables (verificados y sin verificar)</option>
          <option value="verificados" ${exp.numeros === 'verificados' ? 'selected' : ''}>Solo los verificados</option></select></div>
        ${ctx.me.exportar_contactos ? `<div class="form-group"><label class="check"><input type="checkbox" id="mu-contactos" ${exp.contactos ? 'checked' : ''} /> <strong>Contactos</strong> (dato personal: tu usuario tiene el permiso)</label>
          <div class="chips-inline">${[['nombre', 'Nombre'], ['cargo', 'Cargo'], ['area', 'Área'], ['email', 'Email'], ['telefonos', 'Teléfonos del contacto']].map(([k, t]) =>
            `<label class="check"><input type="checkbox" data-inc-ccampo="${k}" ${exp.contacto_campos.includes(k) ? 'checked' : ''} /> ${t}</label>`).join('')}
          ${atributos.filter(a => a.ambito === 'contacto' && a.activo).map(a => `<label class="check"><input type="checkbox" data-inc-catr="${esc(a.clave)}" ${exp.atributos_contacto_excluidos.includes(a.clave) ? '' : 'checked'} /> ${esc(a.nombre)}</label>`).join('')}</div>
          <div class="field-hint">Van en columnas contacto_1_*, contacto_2_*… (hasta ${num(m.contactos_por_empresa_csv || 3)} por empresa; primero el que coincide con el respondente objetivo de la parte).</div></div>` : ''}
        <div class="field-hint">La elección queda guardada en la muestra para la próxima exportación.</div></details>
      <div class="form-group"><label>Formato</label><select class="fselect" id="mu-formato">
        <option value="ucontact">uContact: un renglón por teléfono</option><option value="planilla">Planilla de la muestra: un renglón por empresa</option></select></div>
      <div id="mu-csv-res" class="small muted mb"></div>
      <button class="btn btn-orange" id="mu-csv">Descargar CSV</button>
      <p class="field-hint mt">Un renglón por teléfono discable de cada ítem liberado y pendiente en la parte. Nunca incluye intermediarios, inexistentes, "no corresponde" ni no llamar.${ctx.me.exportar_contactos ? '' : ' Tu usuario no tiene permiso para exportar contactos personales: no salen en el archivo.'}</p>`
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
    `<div class="card mt"><div class="card-header"><div class="card-header-title">Empresas de la muestra <span class="muted small" id="mu-total"></span></div></div>
      <div class="card-body"><div class="toolbar">
      <input type="search" class="grow" id="mu-q" style="min-width:260px" placeholder="RUT, razón social o EC_ID_ITEM…" />
      <select class="fselect" id="mu-estrato" style="width:auto"><option value="">Todos los estratos</option>${m.avance.map(x => `<option>${esc(x.estrato)}</option>`).join('')}</select>
      <select class="fselect" id="mu-rol" style="width:auto"><option value="">Titulares y reemplazos</option><option value="titular">Titulares</option><option value="reemplazo">Reemplazos</option></select>
      <select class="fselect" id="mu-liberado" style="width:auto"><option value="">Liberados o no</option><option value="true">Liberados</option><option value="false">No liberados</option></select>
      <select class="fselect" id="mu-eparte" style="width:auto"><option value="">En cualquier parte</option>${m.partes.map(p => `<option value="${p.id}">${esc(p.nombre)}</option>`).join('')}</select>
      <select class="fselect" id="mu-estado" style="width:auto"><option value="">Cualquier estado</option>${['pendiente', 'en_curso', 'completa', 'rechazo', 'no_contactable', 'fuera_de_marco'].map(x => `<option value="${x}">${esc(etiqueta(x))}</option>`).join('')}</select>
      </div></div>
      <div class="card-body tight" id="mu-items"></div><div class="card-body gap" style="justify-content:space-between" id="mu-pag"></div></div>`;

  let pagina = 1;
  const items = async () => {
    const r = await api.get(`/muestras/${id}/items`, { estrato: $('#mu-estrato').value, rol: $('#mu-rol').value,
      liberado: $('#mu-liberado').value, parte_id: $('#mu-eparte').value, estado: $('#mu-estado').value,
      q: $('#mu-q').value.trim(), pagina });
    const lista = r.items;
    $('#mu-total').textContent = `· ${num(r.total)} empresa${r.total === 1 ? '' : 's'}`;
    $('#mu-pag').innerHTML = `<span class="small muted">${num(r.total)} empresas · página ${r.pagina} de ${r.paginas} · ${r.por_pagina} por página</span>
      <span class="gap"><button class="btn btn-outline btn-sm" id="mu-ant" ${r.pagina <= 1 ? 'disabled' : ''}>‹ Anterior</button>
      <button class="btn btn-outline btn-sm" id="mu-sig" ${r.pagina >= r.paginas ? 'disabled' : ''}>Siguiente ›</button></span>`;
    $('#mu-ant').onclick = () => { pagina--; items(); };
    $('#mu-sig').onclick = () => { pagina++; items(); };
    $('#mu-items').innerHTML = tabla([
      { t: 'EC_ID_ITEM', cls: 'num', k: 'id' }, { t: 'Estrato', k: 'estrato' }, { t: 'Orden', cls: 'num', k: 'orden' }, { t: 'Rol', f: i => est(i.rol) },
      { t: 'Empresa', f: i => `<a class="link" href="#/empresas/${i.rut}">${esc(i.razon_social || i.rut)}</a>` },
      { t: 'Liberado', f: i => i.liberado ? `sí <span class="small muted">${esc(i.liberado_motivo || '')}</span>` : 'no' },
      { t: 'Intentos', cls: 'num', k: 'intentos' },
      { t: 'Estado por parte', f: i => Object.entries(i.estados || {}).map(([p, s]) => `<span class="small muted">${esc(p)}:</span> ${est(s)}`).join(' ') || '—' },
    ], lista, 'Ninguna empresa con esos filtros');
  };
  const filtrar = () => { pagina = 1; items(); };  // los filtros se mantienen al cambiar de página
  ['#mu-estrato', '#mu-rol', '#mu-liberado', '#mu-eparte', '#mu-estado'].forEach(sel => { $(sel).onchange = filtrar; });
  $('#mu-q').addEventListener('keydown', e => { if (e.key === 'Enter') filtrar(); });
  $('#mu-q').addEventListener('search', filtrar);
  items();
  const recargar = () => muestra(ctx, id);
  $('#mu-verificar').onclick = async () => {
    const v = await api.post(`/muestras/${id}/verificar`);
    if (v.resultado === 'reproducible') {
      toast(`Reproducible ✓: el re-sorteo con la semilla ${v.semilla} y el snapshot #${v.snapshot_id} da los mismos ${v.items} ítems en el mismo orden`, 'ok');
    } else if (v.resultado === 'reproducible_con_borrados') {
      const n = v.items_borrados.length;
      await modal({ titulo: 'Reproducible ✓', ancho: 720, cuerpo: `<p>El re-sorteo con la semilla <span class="mono">${v.semilla}</span> y el snapshot
        #${v.snapshot_id} coincide con la muestra. <strong>${num(n)} empresa${n > 1 ? 's se borraron' : ' se borró'} después del sorteo</strong>
        (ver Auditoría):</p>` + tabla([
          { t: 'Estrato', k: 'estrato' }, { t: 'Orden', cls: 'num', k: 'orden' }, { t: 'Rol', f: b => est(b.rol) },
          { t: 'Empresa', f: b => b.rut ? `<span class="mono">${rutFmt(b.rut)}</span> <span class="small muted">(ya no existe)</span>` : '<span class="muted">RUT no disponible</span>' },
          { t: 'Borrado', f: b => `${b.accion === 'empresa.borrar' ? 'empresa borrada' : `carga #${esc(b.carga_id || '—')} borrada`}<div class="small muted">${fechaHora(b.fecha)} · ${esc(b.borrado_por)}</div>` },
        ], v.items_borrados), acciones: [{ t: 'Cerrar', cls: 'btn-orange' }] });
    } else if (v.resultado === 'no_verificable') {
      toast('No verificable: se borraron empresas de esta muestra antes de que el sistema guardara los borrados (versión anterior). Ver Auditoría.', 'err');
    } else {
      toast('¡El re-sorteo no coincide! Revisar auditoría', 'err');
    }
  };
  if ($('#mu-borrar')) $('#mu-borrar').onclick = async () => {
    const n = await api.get(`/muestras/${id}/borrado`);
    const ok = await confirmarEscrito({ titulo: `Borrar muestra «${m.nombre}»`, palabra: 'BORRAR',
      cuerpo: `<p>Se elimina la muestra (${etiqueta(m.estado, 'muestra')}) con:</p><ul class="modal-conteos">
        <li>${pl(n.items, 'ítem', 'ítems')}${m.estado === 'activa' ? ', que dejan de bloquear a sus empresas para otras muestras' : ''};</li>
        <li>${pl(n.intentos, 'intento', 'intentos')} del CDR y ${pl(n.filas_sav, 'fila', 'filas')} del .sav asociados a esos ítems;</li>
        <li>su marco congelado.</li></ul>
        <p>Lo que la base aprendió de las empresas <strong>se conserva</strong>: contactos y teléfonos nuevos, calidad de los números,
        historia de valores y último contacto efectivo (enfriamiento). <strong>No se puede deshacer.</strong> Queda el registro en Auditoría.</p>` });
    if (!ok) return;
    try {
      const r = await borrarConTarea(`/muestras/${id}`, 'Borrar muestra', 'Borrando la muestra');
      toast(`Muestra borrada: ${num(r.items)} ítems, ${num(r.intentos)} intentos del CDR y ${num(r.filas_sav)} filas del .sav`, 'ok');
      ctx.ir('estudios/' + m.estudio_id);
    } catch (err) { toast(err.message, 'err'); recargar(); }
  };
  if ($('#mu-cerrar')) $('#mu-cerrar').onclick = async () => {
    if (!await confirmar('Cerrar muestra', 'Las empresas dejan de estar bloqueadas por esta muestra y ya no se puede exportar ni liberar reemplazos.', 'Cerrar', 'btn-danger')) return;
    await api.post(`/muestras/${id}/cerrar`); recargar();
  };
  if ($('#mu-csv')) {
    const resumen = async () => {
      const s = await api.get(`/muestras/${id}/csv/resumen`, { parte_id: $('#mu-parte').value });
      $('#mu-csv-res').innerHTML = `${num(s.renglones)} renglones para ${num(s.items)} de ${num(s.items_pendientes)} ítems pendientes en la parte · ${s.items_sin_telefono ? `<strong>${num(s.items_sin_telefono)} sin teléfono discable</strong>` : "todos tienen teléfono"}` +
        (s.items_sin_telefono_por_origen ? ` · <strong>${num(s.items_sin_telefono_por_origen)} sin teléfono exportable por el filtro de origen</strong>` : '') +
        (s.columnas_extra && s.columnas_extra.length ? `<div>Columnas agregadas: ${esc(s.columnas_extra.filter(c => !/^contacto_[2-9]/.test(c)).join(', '))}${s.columnas_extra.some(c => c.startsWith('contacto_2')) ? ', …' : ''}</div>` : '');
    };
    const guardarExportacion = async () => {
      const d = { origenes: chipsSel(main(), 'exp-origenes'), orden: $('#mu-orden').value, numeros: $('#mu-numeros').value,
        atributos_excluidos: $$('[data-inc-atr]').filter(x => !x.checked).map(x => x.dataset.incAtr) };
      if ($('#mu-contactos')) Object.assign(d, { contactos: $('#mu-contactos').checked,
        contacto_campos: $$('[data-inc-ccampo]').filter(x => x.checked).map(x => x.dataset.incCcampo),
        atributos_contacto_excluidos: $$('[data-inc-catr]').filter(x => !x.checked).map(x => x.dataset.incCatr) });
      try { await api.put(`/muestras/${id}/exportacion`, d); } catch (e) { toast(e.message, 'err'); }
      resumen();
    };
    $$('#mu-incluir input, #mu-numeros').forEach(x => { x.onchange = guardarExportacion; });
    $$('[data-todos], [data-ninguno]').forEach(a => a.onclick = () => {
      $$('[data-inc-atr]').forEach(x => { x.checked = !!a.dataset.todos; });
      guardarExportacion();
    });
    activarChips($('#mu-csv').closest('.card'), guardarExportacion);
    $('#mu-orden').onchange = guardarExportacion;
    $('#mu-parte').onchange = resumen;
    resumen();
    $('#mu-csv').onclick = async () => {
      const r = await api.descargar(`/muestras/${id}/csv`, { parte_id: $('#mu-parte').value, formato: $('#mu-formato').value });
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
