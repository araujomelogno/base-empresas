// Inicio, buscador de empresas y ficha (R1.1, R1.2, R1.11)
import * as api from '../api.js';
import { agregarRut, fusionarCon } from './provisorias.js';
import { $, $$, esc, main, toast, num, fecha, fechaHora, rutFmt, est, estDe, etiqueta, pageHeader, stats, tabla, card, modal,
  pedirTexto, confirmar, tabs } from '../ui.js';

// ── Inicio ──
export async function inicio(ctx) {
  const r = await api.get('/inicio');
  const nombre = (ctx.me.nombre || ctx.me.email).split(/[ @]/)[0];
  const bandejas = [
    ['intermediarios', '☎️', 'Teléfonos sospechosos de intermediario', r.sospechosos, ['steward']],
    ['revision', '🔀', 'Coincidencias de cargas para revisar', r.revision, ['steward']],
    ['conciliacion', '🧩', 'Filas del .sav y llamadas sin asociar', r.conciliacion, ['coordinador']],
  ].filter(b => ctx.puede(...b[4]));
  main().innerHTML = pageHeader('Hola,', nombre, 'Estado de la base y bandejas pendientes.') +
    (r.cdr.aviso && ctx.puede('coordinador') ? `<div class="alert alert-error"><span><strong>CDR:</strong> ${esc(r.cdr.aviso)}.
      ${ctx.puede('admin') ? '<a class="link" href="#/config">Revisar la conexión</a>' : 'Avisale a un administrador.'}</span></div>` : '') +
    stats([[r.empresas, 'Empresas activas', 's-total'], [r.disponibles, 'Disponibles para muestra', 's-ok'],
      [r.con_telefono_discable, 'Con teléfono discable', 's-free'], [r.muestras_activas, 'Muestras activas', 's-warn', '#/muestras?estado=activa'],
      [r.intermediarios, 'Intermediarios confirmados', 's-bad'], [r.intentos_7d, 'Llamadas últimos 7 días', ''],
      ...(r.provisorias ? [[`${num(r.provisorias)}${r.provisorias_con_candidatas ? ` · ${num(r.provisorias_con_candidatas)}` : ''}`,
        `Base provisoria${r.provisorias_con_candidatas ? ' · con candidatas' : ''}`, 's-free', '#/provisorias']] : [])]) +
    `<div class="grid-2">
      ${card('Bandejas pendientes', bandejas.length ? tabla([
        { t: '', f: b => `<span style="font-size:1.1rem">${b[1]}</span>` },
        { t: 'Bandeja', f: b => `<a class="link" href="#/${b[0]}">${esc(b[2])}</a>` },
        { t: 'Pendientes', cls: 'num', f: b => b[3] ? `<span class="est est-sospechoso">${num(b[3])}</span>` : est('ok', '0') },
      ], bandejas) : '<div class="empty-state">No tenés bandejas a cargo.</div>', '', true)}
      ${card('Últimas cargas', tabla([
        { t: '#', f: c => `<a class="link" href="#/cargas/${c.id}">${c.id}</a>` }, { t: 'Fuente', k: 'fuente' },
        { t: 'Estado', f: c => est(c.estado) }, { t: 'Altas', cls: 'num', f: c => num(c.altas) }, { t: 'Fecha', f: c => fecha(c.fecha) },
      ], r.ultimas_cargas, 'Todavía no hay cargas'), '', true)}
    </div>
    <div class="card mt"><div class="card-body small muted">
      Configuración vigente: <strong>versión ${r.config_version}</strong> ·
      Última corrida del CDR: <strong>${r.cdr.ultima ? `${fechaHora(r.cdr.ultima.inicio)}</strong> ${est(r.cdr.ultima.estado)}` : 'ninguna</strong>'}${r.cdr.activo ? '' : ' <span class="muted">(job inactivo)</span>'} ·
      Registros activos en no llamar: <strong>${num(r.no_llamar)}</strong></div></div>`;
}

// ── Buscador ──
let _filtros = { q: '', departamento: '', tamano: '', naturaleza: '', disponible: '', base: 'definitiva', pagina: 1 };

export async function empresas(ctx) {
  const v = await api.get('/empresas/valores');
  const opt = (arr, sel, todos) => `<option value="">${todos}</option>` + arr.map(x => {
    const [val, t] = Array.isArray(x) ? x : [x, x];
    return `<option value="${esc(val)}" ${val === sel ? 'selected' : ''}>${esc(t)}</option>`;
  }).join('');
  main().innerHTML = pageHeader('Empresas', '', 'Registro maestro por RUT. Buscá por RUT, razón social o nombre de fantasía; con #1234 o item:1234, por EC_ID_ITEM.',
    ctx.puede('steward') ? `<button class="btn btn-orange" id="e-nueva">+ Nueva empresa</button>` : '') +
    `<div class="card"><div class="card-header"><div class="toolbar" style="width:100%">
      <input type="search" class="grow" id="f-q" placeholder="RUT, nombre o #ítem…" value="${esc(_filtros.q)}" />
      <select class="fselect" id="f-departamento">${opt(v.departamento, _filtros.departamento, 'Todos los departamentos')}</select>
      <select class="fselect" id="f-tamano">${opt(v.tamano, _filtros.tamano, 'Todos los tamaños')}</select>
      <select class="fselect" id="f-naturaleza">${opt(v.naturaleza.map(n => [n.codigo, n.nombre]), _filtros.naturaleza, 'Toda naturaleza')}</select>
      <select class="fselect" id="f-disponible">${opt([['true', 'Disponibles'], ['false', 'No disponibles']], _filtros.disponible, 'Disponibilidad')}</select>
      <select class="fselect" id="f-base" title="Base">${[['definitiva', 'Base definitiva'], ['provisoria', 'Base provisoria'], ['ambas', 'Ambas bases']].map(([k, t]) =>
        `<option value="${k}" ${k === _filtros.base ? 'selected' : ''}>${t}</option>`).join('')}</select>
      <button class="btn btn-dark btn-sm" id="f-buscar">Buscar</button></div></div>
      <div class="card-body tight" id="e-res"></div></div>`;
  const buscar = async (pagina = 1) => {
    ['q', 'departamento', 'tamano', 'naturaleza', 'disponible', 'base'].forEach(k => { _filtros[k] = $('#f-' + k).value; });
    _filtros.pagina = pagina;
    const r = await api.get('/empresas', _filtros);
    if (r.item && r.empresas.length === 1) {  // F1.4: #1234 lleva directo a la ficha, pestaña Muestras, con la fila resaltada
      ctx.ir(`empresas/${r.empresas[0].rut}?tab=muestras&item=${r.item}`);
      return;
    }
    if (r.item && !r.empresas.length) {
      $('#e-res').innerHTML = `<div class="empty-state"><span class="ei">🔎</span>No hay ningún ítem de muestra con EC_ID_ITEM ${num(r.item)}</div>`;
      return;
    }
    const paginas = Math.max(1, Math.ceil(r.total / 50));
    $('#e-res').innerHTML = tabla([
      { t: 'RUT / código', f: e => `<a class="link mono" href="#/empresas/${e.rut}">${rutFmt(e.rut)}</a>${e.base === 'provisoria' ? ` ${est('sospechoso', 'provisoria')}` : ''}` },
      { t: 'Razón social', f: e => `<span class="td-strong">${esc(e.razon_social || '—')}</span>${e.fantasia ? `<div class="small muted">${esc(e.fantasia)}</div>` : ''}` },
      { t: 'Departamento', k: 'departamento' }, { t: 'Tamaño', k: 'tamano' }, { t: 'Nat.', k: 'naturaleza' },
      { t: 'Tel. discables', cls: 'num', f: e => num(e.telefonos_discables) },
      { t: 'Disponibilidad', f: e => e.disponible ? est('disponible') : e.reglas.map(r => est('no_disponible', etiqueta(r))).join(' ') },
    ], r.empresas, 'No hay empresas con esos filtros') +
      `<div class="card-body gap" style="justify-content:space-between"><span class="small muted">${num(r.total)} empresas · página ${r.pagina} de ${paginas}</span>
       <span class="gap"><button class="btn btn-outline btn-sm" id="p-ant" ${r.pagina <= 1 ? 'disabled' : ''}>‹ Anterior</button>
       <button class="btn btn-outline btn-sm" id="p-sig" ${r.pagina >= paginas ? 'disabled' : ''}>Siguiente ›</button></span></div>`;
    $('#p-ant').onclick = () => buscar(r.pagina - 1);
    $('#p-sig').onclick = () => buscar(r.pagina + 1);
  };
  $('#f-buscar').onclick = () => buscar(1);
  $('#f-q').addEventListener('keydown', e => { if (e.key === 'Enter') buscar(1); });
  $$('.toolbar select').forEach(s => s.onchange = () => buscar(1));
  if ($('#e-nueva')) $('#e-nueva').onclick = () => modal({
    titulo: 'Nueva empresa', cuerpo: `
      <div class="form-group"><label>RUT</label><input type="text" id="n-rut" placeholder="21 000000 001 X" /></div>
      <div class="form-group"><label>Razón social</label><input type="text" id="n-razon" /></div>
      <div class="form-group"><label>Teléfonos</label><input type="text" id="n-tel" placeholder="2900 1234 / 099 123 456" />
      <div class="field-hint">Separados por / o ;</div></div>`,
    acciones: [{ t: 'Cancelar' }, { t: 'Crear', cls: 'btn-orange', fn: async (b) => {
      const r = await api.post('/empresas', { rut: $('#n-rut', b).value, razon_social: $('#n-razon', b).value || null,
        telefonos: $('#n-tel', b).value.split(/[\/;]/).map(s => s.trim()).filter(Boolean) });
      ctx.ir('empresas/' + r.rut);
    } }],
  });
  await buscar(_filtros.pagina);
}

// F2.2: los números del contacto, con «se habló el …» cuando vienen del .sav
const telNac = (e164) => {
  if (!e164 || !e164.startsWith('+598')) return e164 || '';
  const n = e164.slice(4);
  return n.startsWith('9') ? `0${n.slice(0, 2)} ${n.slice(2, 5)} ${n.slice(5)}` : `${n.slice(0, 4)} ${n.slice(4)}`;
};
export function telefonosContacto(tels) {
  if (!tels || !tels.length) return '<span class="muted">—</span>';
  return tels.map(t => `<div class="small"><span class="mono">${esc(telNac(t.e164) || t.crudo)}</span> <span class="muted">${
    t.relacion === 'se_hablo'
      ? `se habló el ${fecha(t.ultima_vez)}${t.estudio ? ` (${esc(t.estudio)}, ${esc(t.parte)})` : ''}${t.veces > 1 ? ` · ${t.veces} veces` : ''}`
      : 'número del contacto'}</span></div>`).join('');
}

// F3.1: alta, edición y borrado de contactos (admin y data steward)
async function activarContactos(ctx, e, recargar) {
  const defs = await api.get('/atributos', { ambito: 'contacto', activos: true });
  const form = (c = {}) => {
    const mios = new Set((c.telefonos || []).filter(t => t.relacion === 'del_contacto').map(t => t.telefono_id));
    const attr = Object.fromEntries((c.atributos || []).map(a => [a.clave, a.valor_texto ?? a.crudo]));
    return `<div class="form-row"><div class="form-group"><label>Nombre <span class="req">*</span></label><input type="text" id="ct-nombre" value="${esc(c.nombre || '')}" /></div>
      <div class="form-group"><label>Email</label><input type="email" id="ct-email" value="${esc(c.email || '')}" placeholder="nombre@empresa.com.uy" /></div></div>
      <div class="form-row"><div class="form-group"><label>Cargo</label><input type="text" id="ct-cargo" value="${esc(c.cargo || '')}" /></div>
      <div class="form-group"><label>Área</label><input type="text" id="ct-area" value="${esc(c.area || '')}" /></div></div>
      ${e.sucursales.length ? `<div class="form-group"><label>Sucursal</label><select class="fselect" id="ct-sucursal"><option value="">— ninguna —</option>${
        e.sucursales.map(x => `<option value="${x.id}" ${x.id === c.sucursal_id ? 'selected' : ''}>${esc([x.direccion, x.localidad, x.departamento].filter(Boolean).join(', '))}</option>`).join('')}</select></div>` : ''}
      <div class="form-group"><label>Teléfonos del contacto</label>${e.telefonos.filter(t => t.e164).map(t => `<label class="check"><input type="checkbox" data-ct-tel="${t.telefono_id}" ${mios.has(t.telefono_id) ? 'checked' : ''} />
        <span class="mono">${esc(t.e164)}</span> <span class="small muted">${esc(etiqueta(t.estado))}</span></label>`).join('') || '<div class="small muted">La empresa no tiene teléfonos.</div>'}
        <input type="text" id="ct-nuevo" class="mt" placeholder="Agregar otro número (se vincula a la empresa como manual)" /></div>
      ${defs.length ? `<div class="card-header-title mb">Atributos de contacto</div><div class="form-row">${defs.map(a => `<div class="form-group"><label>${esc(a.nombre)}</label>${
        a.tipo === 'lista' ? `<select class="fselect" data-ct-attr="${esc(a.clave)}"><option value="">—</option>${a.opciones.map(o => `<option ${o === attr[a.clave] ? 'selected' : ''}>${esc(o)}</option>`).join('')}</select>`
          : `<input type="${a.tipo === 'numero' ? 'number' : a.tipo === 'fecha' ? 'date' : 'text'}" data-ct-attr="${esc(a.clave)}" value="${esc(attr[a.clave] ?? '')}" />`}</div>`).join('')}</div>` : ''}`;
  };
  const leer = (b, c) => {
    const d = { nombre: $('#ct-nombre', b).value.trim(), email: $('#ct-email', b).value.trim() || null, cargo: $('#ct-cargo', b).value.trim() || null,
      area: $('#ct-area', b).value.trim() || null, telefonos: $$('[data-ct-tel]', b).filter(x => x.checked).map(x => +x.dataset.ctTel),
      telefonos_nuevos: $('#ct-nuevo', b).value.trim() ? [$('#ct-nuevo', b).value.trim()] : [] };
    if ($('#ct-sucursal', b)) d.sucursal_id = $('#ct-sucursal', b).value ? +$('#ct-sucursal', b).value : null;
    const attrs = {};
    $$('[data-ct-attr]', b).forEach(x => {
      const antes = ((c && c.atributos) || []).find(a => a.clave === x.dataset.ctAttr);
      if (x.value || antes) attrs[x.dataset.ctAttr] = x.value || null;
    });
    if (Object.keys(attrs).length) d.atributos = attrs;
    return d;
  };
  const editar = async (c) => {
    const r = await modal({ titulo: `Editar contacto — ${c.nombre}`, ancho: 680, cuerpo: form(c),
      acciones: [{ t: 'Cancelar' }, { t: 'Guardar', cls: 'btn-orange', fn: (b) => api.patch('/contactos/' + c.id, leer(b, c)) }] });
    if (r) { toast('Contacto actualizado', 'ok'); recargar(); }
  };
  if ($('#c-agregar')) $('#c-agregar').onclick = async () => {
    let forzar = false;
    const r = await modal({ titulo: 'Agregar contacto', ancho: 680, cuerpo: form(), acciones: [{ t: 'Cancelar' }, { t: 'Agregar', cls: 'btn-orange', fn: async (b) => {
      try { return await api.post(`/empresas/${e.codigo}/contactos`, { ...leer(b), forzar }); }
      catch (err) {
        if (err.status !== 409 || !err.datos) throw err;
        // Duplicado: mismo nombre normalizado en la empresa → editar el existente o crear igual
        const existente = e.contactos.find(x => x.id === err.datos.duplicado);
        const eleccion = await modal({ titulo: 'Ya existe un contacto con ese nombre', cuerpo: `<p>${esc(err.message)}.</p>
          <p class="small muted">Podés editar el que ya existe o agregar otro contacto igual (por ejemplo, dos personas con el mismo nombre).</p>`,
          acciones: [{ t: 'Cancelar' }, { t: 'Agregar igual', fn: () => 'forzar' }, { t: 'Editar el existente', cls: 'btn-orange', fn: () => 'editar' }] });
        if (eleccion === 'forzar') { forzar = true; return api.post(`/empresas/${e.codigo}/contactos`, { ...leer(b), forzar: true }); }
        if (eleccion === 'editar' && existente) setTimeout(() => editar(existente), 50);
        return { cancelado: true };
      }
    } }] });
    if (r && !r.cancelado) { toast('Contacto agregado', 'ok'); recargar(); }
  };
  $$('[data-c-editar]').forEach(b => b.onclick = () => editar(e.contactos.find(c => c.id === +b.dataset.cEditar)));
  $$('[data-c-borrar]').forEach(b => b.onclick = async () => {
    const c = e.contactos.find(x => x.id === +b.dataset.cBorrar);
    if (!await confirmar('Borrar contacto', `Se borra definitivamente a ${c.nombre}: sus datos, su historia, sus teléfonos de contacto, sus atributos y su «no llamar». Es un dato personal (Ley 18.331): no se puede deshacer. En Auditoría queda el borrado sin el nombre.`, 'Borrar', 'btn-danger')) return;
    await api.del('/contactos/' + c.id);
    toast('Contacto borrado', 'ok'); recargar();
  });
}

// ── Ficha ──
const CAMPOS = [['razon_social', 'Razón social'], ['fantasia', 'Nombre de fantasía'], ['naturaleza', 'Naturaleza jurídica'],
  ['ciiu', 'CIIU'], ['tamano', 'Tamaño'], ['departamento', 'Departamento'], ['localidad', 'Localidad'], ['direccion', 'Dirección'],
  ['web', 'Web'], ['estado', 'Estado']];

export async function ficha(ctx, rut, params) {
  const e = await api.get('/empresas/' + rut);
  const tab = params.get('tab') || 'datos';
  const vig = Object.fromEntries(e.historia.filter(h => h.vigente).map(h => [h.campo, h]));
  const d = e.disponibilidad || {};
  let acciones = [
    ctx.puede('steward') && !e.baja ? `<button class="btn btn-outline btn-sm" id="a-editar">Editar datos</button>` : '',
    ctx.puede('steward') && !e.baja ? `<button class="btn btn-outline btn-sm" id="a-fusionar">Fusionar otra empresa</button>` : '',
    ctx.puede('admin', 'steward') && !e.baja ? `<button class="btn btn-outline btn-sm btn-del" id="a-nollamar">No llamar</button>` : '',
    ctx.puede() ? `<button class="btn btn-danger btn-sm" id="a-borrar">Borrar empresa</button>` : '',
  ];
  const prov = e.base === 'provisoria';
  if (prov) acciones.unshift(...(ctx.puede('steward') && !e.baja ? [`<button class="btn btn-orange btn-sm" id="a-rut">Agregar RUT</button>`,
    `<button class="btn btn-outline btn-sm" id="a-fus-def">Fusionar con…</button>`] : []));
  main().innerHTML = pageHeader(e.razon_social || 'Empresa sin razón social', '', `${prov ? `${est('sospechoso', 'Provisoria')} Código <strong class="mono">${esc(e.codigo)}</strong>` : `RUT <strong class="mono">${rutFmt(e.rut)}</strong>`}
    ${e.fantasia ? ' · ' + esc(e.fantasia) : ''} · ${estDe('empresa', e.estado)} ${e.baja ? est('error', e.baja) : ''}`, acciones.join('')) +
    (prov && !e.baja ? `<div class="alert alert-info"><span><strong>Empresa de la base provisoria</strong> (no trae RUT). Se puede sortear y llamar.
      Pasa a la base definitiva al agregarle el RUT o al fusionarla con una empresa que lo tiene.<span id="f-cands"></span></span></div>` : '') +
    (e.baja === 'fusionada' ? `<div class="alert alert-warn">Esta empresa fue absorbida por <a class="link" href="#/empresas/${e.fusionada_en_rut}">${rutFmt(e.fusionada_en_rut)}</a>.</div>` : '') +
    (d.disponible ? `<div class="alert alert-success">Disponible para muestras.</div>`
      : `<div class="alert alert-warn"><span>No disponible: ${(d.reglas || []).map(r => `<strong>${esc(etiqueta(r))}</strong>`).join(', ')}${d.hasta ? ` · hasta ${fecha(d.hasta)}` : ''}</span></div>`) +
    stats([[e.telefonos.filter(t => t.discable).length, 'Teléfonos discables', 's-ok'], [e.contactos.length, 'Contactos', 's-free'],
      [e.muestras.length, 'Muestras', 's-warn'], [e.ultimo_contacto_efectivo ? fecha(e.ultimo_contacto_efectivo) : '—', 'Último contacto efectivo', 's-total']]) +
    tabs('ficha', [['datos', 'Datos'], ['historia', 'Historia'], ['telefonos', 'Teléfonos'], ['contactos', 'Contactos'],
      ['muestras', 'Muestras'], ['tiempo', 'Línea de tiempo'], ['fusiones', 'Fusiones y no llamar']], tab) +
    `<div id="f-tab"></div>`;
  $$('[data-tabs="ficha"] .tab').forEach(b => b.onclick = () => { location.hash = `#/empresas/${rut}?tab=${b.dataset.tab}`; });
  const el = $('#f-tab');
  const recargar = () => ficha(ctx, rut, params);

  if (tab === 'datos') {
    el.innerHTML = card('Valores vigentes', `<dl class="kv">${CAMPOS.map(([c, t]) => {
      const h = vig[c];
      let val = c === 'naturaleza' && e.naturaleza ? `${e.naturaleza.nombre} (${e.naturaleza.codigo})${e.naturaleza.excluida ? ' ' + est('error', 'excluida') : ''}` : esc(e[c] ?? '—');
      if (c === 'estado') val = estDe('empresa', e.estado);
      return `<dt>${t}</dt><dd>${val}${h ? `<span class="fuente">· ${esc(h.fuente_tipo)}${h.fuente_id ? ' #' + h.fuente_id : ''} · conf. ${h.confianza} · ${fecha(h.fecha)}</span>` : ''}</dd>`;
    }).join('')}</dl>`) + (e.sucursales.length ? card('Sucursales', tabla([{ t: 'Dirección', k: 'direccion' },
      { t: 'Departamento', k: 'departamento' }, { t: 'Localidad', k: 'localidad' }, { t: 'Fuente', k: 'fuente_tipo' }], e.sucursales), '', true) : '') +
      card('Atributos', e.atributos.length ? `<dl class="kv">${e.atributos.map(a => {
        const val = a.invalido ? `${esc(a.valor_crudo)} ${est('preview', 'valor inválido')}`
          : a.tipo === 'fecha' ? fecha(a.valor_fecha) : a.tipo === 'numero' ? num(a.valor_numero) : esc(a.valor_texto);
        return `<dt>${esc(a.nombre)}${a.activo ? '' : ' <span class="small muted">(inactivo)</span>'}</dt><dd>${val}<span class="fuente">· ${esc(a.fuente_tipo)}${a.fuente_id ? ' #' + a.fuente_id : ''} · conf. ${a.confianza} · ${fecha(a.fecha)}</span></dd>`;
      }).join('')}</dl>` : `<div class="small muted">Sin atributos cargados. Los atributos (cantidad de empleados, exporta, cámara…) se definen en Administración → Atributos y llegan con las cargas.</div>`);
  } else if (tab === 'historia') {
    el.innerHTML = card('Historia por campo', tabla([
      { t: 'Campo', f: h => `<span class="td-strong">${esc(h.campo)}</span>` }, { t: 'Valor', f: h => esc(h.valor ?? '∅') + (h.vigente ? ' ' + est('ok', 'vigente') : '') },
      { t: 'Fuente', f: h => `${esc(h.fuente_tipo)}${h.fuente_id ? ' #' + h.fuente_id : ''}${h.ingesta_borrada ? ' <span class="small muted">(ingesta borrada)</span>' : ''}`
        + (h.detalle && h.detalle.estudio_id && h.ingesta_borrada ? `<div class="small muted">estudio #${esc(h.detalle.estudio_id)} · parte #${esc(h.detalle.parte_id)}</div>` : '') },
      { t: 'Confianza', cls: 'num', k: 'confianza' },
      { t: 'Actor', k: 'actor' }, { t: 'Fecha', f: h => fechaHora(h.fecha) },
    ], e.historia.map(h => ({ ...h, __tr: h.anulada ? 'class="anulada" title="Anulada: la carga o fusión fue deshecha"' : h.vigente ? 'class="vigente"' : '' })),
    'Sin historia'), '', true) +
      `<p class="small muted mt">Regla de supervivencia: gana la fuente de mayor confianza y, a igual confianza, la más reciente. Un dato confirmado por la sala nunca lo pisa una carga. Las filas tachadas son de cargas o fusiones deshechas.</p>`;
  } else if (tab === 'telefonos') {
    el.innerHTML = card('Teléfonos', tabla([
      { t: 'Número', f: t => `<span class="mono td-strong">${esc(t.e164 || t.crudo)}</span> ${est(t.tipo)}` },
      { t: 'Vínculo', f: t => ctx.puede('steward') ? `<select class="fselect" data-vinc="${t.vinculo_id}" style="width:auto">${
        ['sin_verificar', 'verificado', 'no_corresponde', 'intermediario', 'inexistente'].map(s => `<option value="${s}" ${s === t.estado ? 'selected' : ''}>${etiqueta(s)}</option>`).join('')}</select>` : est(t.estado) },
      { t: 'Discable', f: t => t.discable ? est('ok', 'sí') : est('error', 'no') },
      { t: 'Alertas', f: t => [t.intermediario ? est(t.intermediario, 'intermediario ' + t.intermediario) : '', t.no_llamar ? est('error', 'no llamar') : '',
        t.estado_telefono !== 'valido' ? est('error', t.estado_telefono) : ''].join(' ') },
      { t: 'RUTs', cls: 'num', k: 'n_empresas' }, { t: 'Intentos', cls: 'num', f: t => num(t.intentos) },
      { t: 'Último intento', f: t => fechaHora(t.ultimo_intento) },
      { t: 'Origen', f: t => (t.origenes || []).map(o => `<div class="small" title="${esc(o.fuente_tipo)}${o.fuente_id ? ' #' + o.fuente_id : ''} · ${esc(fecha(o.fecha))}">${esc(o.nombre)}</div>`).join('') || '—' },
      { t: 'Contacto', k: 'contacto' },
    ], e.telefonos, 'Sin teléfonos'), ctx.puede('steward') ? `<button class="btn btn-orange btn-sm" id="t-agregar">+ Teléfono</button>` : '', true);
    $$('[data-vinc]').forEach(s => s.onchange = async () => {
      const motivo = await pedirTexto('Cambiar estado del vínculo', 'Motivo', { obligatorio: false });
      if (motivo === null) return recargar();
      await api.post(`/vinculos/${s.dataset.vinc}/estado`, { estado: s.value, motivo });
      toast('Estado actualizado', 'ok'); recargar();
    });
    if ($('#t-agregar')) $('#t-agregar').onclick = async () => {
      const n = await pedirTexto('Agregar teléfono', 'Número', { placeholder: '2900 1234 o 099 123 456' });
      if (!n) return;
      const r = await api.post(`/empresas/${rut}/telefonos`, { numero: n });
      toast(r.e164 ? `Agregado ${r.e164}${r.sospechoso ? ' — quedó como sospechoso de intermediario' : ''}` : `Guardado como inválido: ${r.motivo}`, r.e164 ? 'ok' : 'err');
      recargar();
    };
  } else if (tab === 'contactos') {
    const edita = ctx.puede('steward') && !e.baja;
    el.innerHTML = card('Contactos (dato personal, Ley 18.331)', tabla([
      { t: 'Nombre', f: c => `<span class="td-strong">${esc(c.nombre)}</span>${c.no_llamar ? ' ' + est('error', 'no llamar') : ''}${c.sucursal ? `<div class="small muted">${esc(c.sucursal)}</div>` : ''}` },
      { t: 'Cargo', k: 'cargo' }, { t: 'Área', k: 'area' }, { t: 'Email', k: 'email' },
      { t: 'Teléfonos', f: c => telefonosContacto(c.telefonos) },
      { t: 'Atributos', f: c => (c.atributos || []).map(a => `<div class="small"><span class="muted">${esc(a.nombre)}:</span> ${esc(a.valor_texto ?? a.crudo ?? '—')}</div>`).join('') || '<span class="muted">—</span>' },
      { t: 'Fuente', k: 'fuente_tipo' }, { t: 'Actualizado', f: c => fecha(c.actualizado) },
      { t: '', f: c => edita && c.id ? `<div class="td-actions"><button class="btn btn-outline btn-sm" data-c-editar="${c.id}">Editar</button>
        <button class="btn btn-outline btn-sm btn-del" data-c-borrar="${c.id}">Borrar</button></div>` : '' },
    ], e.contactos, 'Sin contactos'), edita ? `<button class="btn btn-orange btn-sm" id="c-agregar">+ Agregar contacto</button>` : '', true);
    if (edita) activarContactos(ctx, e, recargar);
  } else if (tab === 'muestras') {
    el.innerHTML = card('Muestras', tabla([
      { t: 'Muestra', f: m => `<a class="link" href="#/muestras/${m.muestra_id}">${esc(m.nombre)}</a>` }, { t: 'Estudio', k: 'estudio' },
      { t: 'Estado', f: m => estDe('muestra', m.estado) }, { t: 'Estrato', k: 'estrato' }, { t: 'Rol', f: m => est(m.rol) },
      { t: 'Liberado', f: m => m.liberado ? 'sí' : 'no' }, { t: 'Ítem (EC_ID_ITEM)', cls: 'num', k: 'item_id' },
    ], e.muestras.map(m => ({ ...m, __tr: String(m.item_id) === params.get('item') ? 'class="fila-resaltada" id="f-item"' : '' })),
    'Nunca entró a una muestra'), '', true);
    if ($('#f-item')) $('#f-item').scrollIntoView({ block: 'center' });
  } else if (tab === 'tiempo') {
    const clase = { llamada: 't-llamada', resultado: 't-resultado', dato: 't-dato', 'no llamar': 't-no' };
    const evento = (x) => `<li class="${clase[x.tipo] || ''}"><div class="tl-fecha">${fechaHora(x.fecha)} · ${esc(x.tipo)}</div>
      <div class="tl-desc">${esc(x.descripcion)}</div><div class="tl-meta">${esc(x.fuente || '')}${x.actor ? ' · ' + esc(x.actor) : ''}</div></li>`;
    // F2.4: lo que trajo una ingesta del .sav se agrupa en una línea desplegable
    const grupo = (g) => `<li class="t-ingesta"><div class="tl-fecha">${fechaHora(g.fecha)} · ingesta .sav</div>
      <details class="tl-grupo"><summary class="tl-desc"><a class="link" href="#/sav/${g.ingesta_id}">${esc(g.titulo)}</a>: ${esc(g.descripcion.slice(g.titulo.length + 2))}</summary>
      <ul class="timeline tl-sub">${g.eventos.map(evento).join('')}</ul></details>
      <div class="tl-meta">${esc(g.fuente)}${g.actor ? ' · ' + esc(g.actor) : ''}</div></li>`;
    el.innerHTML = card('Línea de tiempo', e.linea_de_tiempo.length ? `<ul class="timeline">${e.linea_de_tiempo.map(x => x.tipo === 'ingesta' ? grupo(x) : evento(x)).join('')}</ul>`
      : '<div class="empty-state">Sin eventos</div>');
  } else if (tab === 'fusiones') {
    el.innerHTML = card('Fusiones', tabla([
      { t: '#', k: 'id' }, { t: 'Absorbente', f: f => `<a class="link mono" href="#/empresas/${f.absorbente_rut}">${rutFmt(f.absorbente_rut)}</a>` },
      { t: 'Absorbida', f: f => `<a class="link mono" href="#/empresas/${f.absorbida_rut}">${rutFmt(f.absorbida_rut)}</a>` },
      { t: 'Motivo', k: 'motivo' }, { t: 'Actor', k: 'actor' }, { t: 'Fecha', f: f => fechaHora(f.fecha) },
      { t: 'Estado', f: f => f.deshecha ? est('deshecha') : est('activa', 'vigente') },
      { t: '', f: f => !f.deshecha && ctx.puede('steward') ? `<button class="btn btn-outline btn-sm" data-deshacer="${f.id}">Deshacer</button>` : '' },
    ], e.fusiones, 'Sin fusiones'), '', true) + card('No llamar (empresa)', tabla([
      { t: 'Motivo', k: 'motivo' }, { t: 'Solicitante', k: 'solicitante' }, { t: 'Registró', k: 'registrado_por' },
      { t: 'Fecha', f: n => fechaHora(n.fecha) }, { t: 'Estado', f: n => n.activo ? est('error', 'activo') : est('ok', 'levantado') },
    ], e.no_llamar, 'Sin pedidos de no llamar'), '', true);
    $$('[data-deshacer]').forEach(b => b.onclick = async () => {
      if (!await confirmar('Deshacer fusión', 'Se devuelven a la empresa absorbida sus teléfonos, contactos y sucursales.')) return;
      await api.post(`/fusiones/${b.dataset.deshacer}/deshacer`);
      toast('Fusión deshecha', 'ok'); recargar();
    });
  }

  if ($('#a-editar')) $('#a-editar').onclick = async () => {
    const v = await api.get('/empresas/valores');
    await modal({
      titulo: 'Editar datos (fuente manual)', ancho: 640, cuerpo: `<div class="form-row">${CAMPOS.map(([c, t]) => {
        if (c === 'naturaleza') return `<div class="form-group"><label>${t}</label><select class="fselect" data-campo="naturaleza"><option value="">—</option>${
          v.naturaleza.map(n => `<option value="${n.codigo}" ${e.naturaleza && e.naturaleza.codigo === n.codigo ? 'selected' : ''}>${esc(n.nombre)}</option>`).join('')}</select></div>`;
        if (c === 'estado') return `<div class="form-group"><label>${t}</label><select class="fselect" data-campo="estado">${
          ['activa', 'cerrada', 'desconocida'].map(s => `<option ${s === e.estado ? 'selected' : ''}>${s}</option>`).join('')}</select></div>`;
        return `<div class="form-group"><label>${t}</label><input type="text" data-campo="${c}" value="${esc(e[c] ?? '')}" /></div>`;
      }).join('')}</div><div class="form-group"><label>Motivo</label><input type="text" id="ed-motivo" placeholder="p. ej. verificado en la web de la empresa" /></div>
      <p class="field-hint">Solo se registran los campos que cambies. Un valor manual tiene la confianza de la fuente "manual" de la configuración.</p>`,
      acciones: [{ t: 'Cancelar' }, { t: 'Guardar', cls: 'btn-orange', fn: async (b) => {
        const valores = {};
        $$('[data-campo]', b).forEach(i => {
          const actual = i.dataset.campo === 'naturaleza' ? (e.naturaleza ? e.naturaleza.codigo : '') : (e[i.dataset.campo] ?? '');
          if (i.value !== actual) valores[i.dataset.campo] = i.value || null;
        });
        if (!Object.keys(valores).length) { toast('No cambiaste nada'); return; }
        await api.patch('/empresas/' + rut, { valores, motivo: $('#ed-motivo', b).value || null });
        toast('Datos actualizados', 'ok');
      } }],
    });
    recargar();
  };
  if ($('#a-fusionar')) $('#a-fusionar').onclick = async () => {
    const r = await modal({
      titulo: 'Fusionar otra empresa en esta', cuerpo: `<p class="small muted mb">La empresa absorbida queda guardada como "fusionada" y la fusión se puede deshacer.</p>
        <div class="form-group"><label>RUT de la empresa absorbida</label><input type="text" id="fu-rut" /></div>
        <div class="form-group"><label>Motivo</label><input type="text" id="fu-motivo" /></div>`,
      acciones: [{ t: 'Cancelar' }, { t: 'Fusionar', cls: 'btn-orange', fn: (b) => api.post(`/empresas/${rut}/fusionar`, {
        rut_absorbida: $('#fu-rut', b).value, motivo: $('#fu-motivo', b).value || null }) }],
    });
    if (r) { toast('Empresas fusionadas', 'ok'); recargar(); }
  };
  if ($('#a-rut')) $('#a-rut').onclick = () => agregarRut(e, (cod) => ctx.ir('empresas/' + cod));
  if (prov && !e.baja) {
    const cands = await api.get(`/empresas/${e.codigo}/candidatas`);
    if (cands.length && $('#f-cands')) $('#f-cands').innerHTML = ` Candidatas en la definitiva: ${cands.map(c =>
      `<a class="link mono" href="#/empresas/${c.codigo}">${rutFmt(c.codigo)}</a> ${esc(c.razon_social || '')} (${Math.round(c.similitud * 100)} %)`).join(' · ')}.`;
    if ($('#a-fus-def')) $('#a-fus-def').onclick = () => {
      fusionarCon(e, cands, (cod) => ctx.ir('empresas/' + cod));
      setTimeout(() => {
        const q = $('#fu-q');
        if (q) q.addEventListener('keydown', async (ev) => {
          if (ev.key !== 'Enter') return;
          const r = await api.get('/empresas', { q: q.value, base: 'definitiva' });
          $('#fu-res').innerHTML = r.empresas.slice(0, 8).map(x => `<label class="check"><input type="radio" name="fu-c" value="${esc(x.rut)}" />
            <span class="mono">${rutFmt(x.rut)}</span> ${esc(x.razon_social || '—')}</label>`).join('') || '<div class="small muted">Sin resultados</div>';
        });
      }, 50);
    };
  }
  if ($('#a-borrar')) $('#a-borrar').onclick = async () => {
    const txt = `Se elimina <strong>${esc(e.razon_social || rutFmt(e.rut))}</strong> con toda su historia, teléfonos, contactos, sucursales
      y atributos, su lugar en las muestras (${e.muestras.length}) y su actividad de campo (intentos del CDR y respuestas del .sav).
      Si otras empresas se fusionaron dentro de esta, se borran también. <strong>No se puede deshacer.</strong> Solo queda el registro
      en Auditoría.<br><br>Escribí ${e.rut ? 'el RUT' : 'el código'} <strong class="mono">${esc(e.codigo)}</strong> para confirmar.`;
    const ok = await modal({ titulo: 'Borrar empresa', cuerpo: `<p>${txt}</p><div class="form-group"><input type="text" id="m-borrar" autocomplete="off" /></div>`,
      acciones: [{ t: 'Cancelar' }, { t: 'Borrar definitivamente', cls: 'btn-danger', fn: (b) => {
        const v = b.querySelector('#m-borrar').value;
        if ((e.rut ? v.replace(/\D/g, '') : v.trim().toUpperCase()) !== e.codigo) { toast(e.rut ? 'El RUT no coincide' : 'El código no coincide', 'err'); return false; }
        return true;
      } }] });
    if (!ok) return;
    const r = await api.del('/empresas/' + e.codigo);
    toast(`Empresa borrada${r.empresas > 1 ? ` (con ${r.empresas - 1} fusionadas)` : ''}`, 'ok');
    ctx.ir('empresas');
  };
  if ($('#a-nollamar')) $('#a-nollamar').onclick = async () => {
    const r = await modal({
      titulo: 'Registrar pedido de no llamar', cuerpo: `<p class="small muted mb">Se respeta en todas las muestras y exportaciones desde ahora.</p>
        <div class="form-group"><label>Motivo</label><input type="text" id="nl-motivo" /></div>
        <div class="form-group"><label>Quién lo pidió</label><input type="text" id="nl-sol" /></div>`,
      acciones: [{ t: 'Cancelar' }, { t: 'Registrar', cls: 'btn-danger', fn: (b) => api.post('/no-llamar', {
        alcance: 'empresa', rut, motivo: $('#nl-motivo', b).value, solicitante: $('#nl-sol', b).value }) }],
    });
    if (r) { toast('Registrado en no llamar', 'ok'); recargar(); }
  };
}
