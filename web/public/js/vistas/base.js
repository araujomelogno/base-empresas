// Inicio, buscador de empresas y ficha (R1.1, R1.2, R1.11)
import * as api from '../api.js';
import { $, $$, esc, main, toast, num, fecha, fechaHora, rutFmt, est, etiqueta, pageHeader, stats, tabla, card, modal,
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
    stats([[r.empresas, 'Empresas activas', 's-total'], [r.disponibles, 'Disponibles para muestra', 's-ok'],
      [r.con_telefono_discable, 'Con teléfono discable', 's-free'], [r.muestras_activas, 'Muestras activas', 's-warn'],
      [r.intermediarios, 'Intermediarios confirmados', 's-bad'], [r.intentos_7d, 'Llamadas últimos 7 días', '']]) +
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
      Último lote del CDR: <strong>${r.ultimo_cdr ? fechaHora(r.ultimo_cdr) : 'nunca'}</strong> ·
      Registros activos en no llamar: <strong>${num(r.no_llamar)}</strong></div></div>`;
}

// ── Buscador ──
let _filtros = { q: '', departamento: '', tamano: '', naturaleza: '', disponible: '', pagina: 1 };

export async function empresas(ctx) {
  const v = await api.get('/empresas/valores');
  const opt = (arr, sel, todos) => `<option value="">${todos}</option>` + arr.map(x => {
    const [val, t] = Array.isArray(x) ? x : [x, x];
    return `<option value="${esc(val)}" ${val === sel ? 'selected' : ''}>${esc(t)}</option>`;
  }).join('');
  main().innerHTML = pageHeader('Empresas', '', 'Registro maestro por RUT. Buscá por RUT, razón social o nombre de fantasía.',
    ctx.puede('steward') ? `<button class="btn btn-orange" id="e-nueva">+ Nueva empresa</button>` : '') +
    `<div class="card"><div class="card-header"><div class="toolbar" style="width:100%">
      <input type="search" class="grow" id="f-q" placeholder="RUT o nombre…" value="${esc(_filtros.q)}" />
      <select class="fselect" id="f-departamento">${opt(v.departamento, _filtros.departamento, 'Todos los departamentos')}</select>
      <select class="fselect" id="f-tamano">${opt(v.tamano, _filtros.tamano, 'Todos los tamaños')}</select>
      <select class="fselect" id="f-naturaleza">${opt(v.naturaleza.map(n => [n.codigo, n.nombre]), _filtros.naturaleza, 'Toda naturaleza')}</select>
      <select class="fselect" id="f-disponible">${opt([['true', 'Disponibles'], ['false', 'No disponibles']], _filtros.disponible, 'Disponibilidad')}</select>
      <button class="btn btn-dark btn-sm" id="f-buscar">Buscar</button></div></div>
      <div class="card-body tight" id="e-res"></div></div>`;
  const buscar = async (pagina = 1) => {
    ['q', 'departamento', 'tamano', 'naturaleza', 'disponible'].forEach(k => { _filtros[k] = $('#f-' + k).value; });
    _filtros.pagina = pagina;
    const r = await api.get('/empresas', _filtros);
    const paginas = Math.max(1, Math.ceil(r.total / 50));
    $('#e-res').innerHTML = tabla([
      { t: 'RUT', f: e => `<a class="link mono" href="#/empresas/${e.rut}">${rutFmt(e.rut)}</a>` },
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

// ── Ficha ──
const CAMPOS = [['razon_social', 'Razón social'], ['fantasia', 'Nombre de fantasía'], ['naturaleza', 'Naturaleza jurídica'],
  ['ciiu', 'CIIU'], ['tamano', 'Tamaño'], ['departamento', 'Departamento'], ['localidad', 'Localidad'], ['direccion', 'Dirección'],
  ['web', 'Web'], ['estado', 'Estado']];

export async function ficha(ctx, rut, params) {
  const e = await api.get('/empresas/' + rut);
  const tab = params.get('tab') || 'datos';
  const vig = Object.fromEntries(e.historia.filter(h => h.vigente).map(h => [h.campo, h]));
  const d = e.disponibilidad || {};
  const acciones = [
    ctx.puede('steward') && !e.baja ? `<button class="btn btn-outline btn-sm" id="a-editar">Editar datos</button>` : '',
    ctx.puede('steward') && !e.baja ? `<button class="btn btn-outline btn-sm" id="a-fusionar">Fusionar otra empresa</button>` : '',
    ctx.puede('admin', 'steward') && !e.baja ? `<button class="btn btn-outline btn-sm btn-del" id="a-nollamar">No llamar</button>` : '',
  ].join('');
  main().innerHTML = pageHeader(e.razon_social || 'Empresa sin razón social', '', `RUT <strong class="mono">${rutFmt(e.rut)}</strong>
    ${e.fantasia ? ' · ' + esc(e.fantasia) : ''} · ${est(e.estado)} ${e.baja ? est('error', e.baja) : ''}`, acciones) +
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
      if (c === 'estado') val = est(e.estado);
      return `<dt>${t}</dt><dd>${val}${h ? `<span class="fuente">· ${esc(h.fuente_tipo)}${h.fuente_id ? ' #' + h.fuente_id : ''} · conf. ${h.confianza} · ${fecha(h.fecha)}</span>` : ''}</dd>`;
    }).join('')}</dl>`) + (e.sucursales.length ? card('Sucursales', tabla([{ t: 'Dirección', k: 'direccion' },
      { t: 'Departamento', k: 'departamento' }, { t: 'Localidad', k: 'localidad' }, { t: 'Fuente', k: 'fuente_tipo' }], e.sucursales), '', true) : '');
  } else if (tab === 'historia') {
    el.innerHTML = card('Historia por campo', tabla([
      { t: 'Campo', f: h => `<span class="td-strong">${esc(h.campo)}</span>` }, { t: 'Valor', f: h => esc(h.valor ?? '∅') + (h.vigente ? ' ' + est('ok', 'vigente') : '') },
      { t: 'Fuente', f: h => `${esc(h.fuente_tipo)}${h.fuente_id ? ' #' + h.fuente_id : ''}` }, { t: 'Confianza', cls: 'num', k: 'confianza' },
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
      { t: 'Último intento', f: t => fechaHora(t.ultimo_intento) }, { t: 'Fuente', k: 'fuente_tipo' }, { t: 'Contacto', k: 'contacto' },
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
    el.innerHTML = card('Contactos (dato personal, Ley 18.331)', tabla([
      { t: 'Nombre', f: c => `<span class="td-strong">${esc(c.nombre)}</span>${c.no_llamar ? ' ' + est('error', 'no llamar') : ''}` },
      { t: 'Cargo', k: 'cargo' }, { t: 'Área', k: 'area' }, { t: 'Email', k: 'email' }, { t: 'Fuente', k: 'fuente_tipo' },
      { t: 'Actualizado', f: c => fecha(c.actualizado) },
    ], e.contactos, 'Sin contactos'), '', true);
  } else if (tab === 'muestras') {
    el.innerHTML = card('Muestras', tabla([
      { t: 'Muestra', f: m => `<a class="link" href="#/muestras/${m.muestra_id}">${esc(m.nombre)}</a>` }, { t: 'Estudio', k: 'estudio' },
      { t: 'Estado', f: m => est(m.estado) }, { t: 'Estrato', k: 'estrato' }, { t: 'Rol', f: m => est(m.rol) },
      { t: 'Liberado', f: m => m.liberado ? 'sí' : 'no' }, { t: 'Ítem', cls: 'num', k: 'item_id' },
    ], e.muestras, 'Nunca entró a una muestra'), '', true);
  } else if (tab === 'tiempo') {
    const clase = { llamada: 't-llamada', resultado: 't-resultado', dato: 't-dato', 'no llamar': 't-no' };
    el.innerHTML = card('Línea de tiempo', e.linea_de_tiempo.length ? `<ul class="timeline">${e.linea_de_tiempo.map(x => `
      <li class="${clase[x.tipo] || ''}"><div class="tl-fecha">${fechaHora(x.fecha)} · ${esc(x.tipo)}</div>
      <div class="tl-desc">${esc(x.descripcion)}</div><div class="tl-meta">${esc(x.fuente || '')}${x.actor ? ' · ' + esc(x.actor) : ''}</div></li>`).join('')}</ul>`
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
