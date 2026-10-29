// Configuración, naturalezas, no llamar, usuarios y auditoría (R1.4, R1.12, R1.13)
import * as api from '../api.js';
import { $, $$, esc, main, toast, num, fechaHora, est, pageHeader, tabla, card, modal, pedirTexto,
  json } from '../ui.js';

const CAMPOS_CSV = ['id_item', 'tel_e164', 'tel_nacional', 'tel_sin_mas', 'rut', 'razon_social', 'fantasia', 'contacto', 'contacto_cargo',
  'departamento', 'localidad', 'estrato', 'link', 'parte', 'muestra'];
const DIAS = ['', 'L', 'M', 'X', 'J', 'V', 'S', 'D'];

export async function config(ctx) {
  const c = await api.get('/config');
  const p = c.parametros;
  const editable = ctx.puede('admin');
  const dis = editable ? '' : 'disabled';
  main().innerHTML = pageHeader('Configuración', `v${c.version}`, 'Parámetros de negocio. Cada cambio crea una versión nueva con autor y fecha; las muestras guardan la versión con la que se sortearon.') +
    `<div class="grid-2">${card('Reglas de contacto', `
      <div class="form-row"><div class="form-group"><label>Umbral de intermediario (RUTs por teléfono)</label><input type="number" id="c-umbral" min="2" value="${p.umbral_intermediario}" ${dis} /></div>
      <div class="form-group"><label>Meses de enfriamiento</label><input type="number" id="c-enfr" min="0" value="${p.meses_enfriamiento}" ${dis} />
      <div class="field-hint">Se cuentan desde el último contacto efectivo.</div></div></div>
      <div class="form-group"><label>Reglas de disponibilidad activas</label>
        ${[['enfriamiento', 'Enfriamiento'], ['muestra_activa', 'Bloqueo por muestra activa'], ['sin_telefono_discable', 'Excluir empresas sin teléfono discable']].map(([k, t]) =>
          `<div><label class="check"><input type="checkbox" data-regla="${k}" ${p.reglas_disponibilidad[k] !== false ? 'checked' : ''} ${dis} /> ${t}</label></div>`).join('')}
        <div class="field-hint">La exclusión por naturaleza jurídica y la lista de no llamar están siempre activas.</div></div>
      <div class="form-group"><label>Cuenta como contacto efectivo</label>
        ${['completa', 'parcial', 'rechazo'].map(k => `<label class="check" style="margin-right:1rem"><input type="checkbox" data-efectivo="${k}" ${p.contacto_efectivo.includes(k) ? 'checked' : ''} ${dis} /> ${k}</label>`).join('')}</div>
      <div class="form-group"><label>Reglas de fusión disponibles en las cargas</label>
        ${[['rut', 'RUT'], ['telefono', 'Teléfono'], ['razon_social', 'Razón social normalizada'], ['dominio', 'Dominio web']].map(([k, t]) =>
          `<label class="check" style="margin-right:1rem"><input type="checkbox" data-fusion="${k}" ${p.reglas_fusion.includes(k) ? 'checked' : ''} ${k === 'rut' || !editable ? 'disabled' : ''} /> ${t}</label>`).join('')}</div>
      <div class="form-group"><label>Confianza por fuente (0–100)</label><div class="inline-form">
        ${Object.entries(p.confianza_fuentes).map(([k, v]) => `<div class="form-group"><label>${esc(k)}</label><input type="number" data-conf="${esc(k)}" value="${v}" ${dis} /></div>`).join('')}</div></div>`)}
    ${card('CDR', `
      <div class="form-group"><label>Destinos internos a ignorar</label><textarea class="finput code" id="c-internos" rows="5" ${dis}>${esc(p.destinos_internos.join('\n'))}</textarea>
      <div class="field-hint">Uno por línea. Si empieza con ^ es una expresión regular (p. ej. ^\\d{1,5}$ = extensiones); si no, un número exacto.</div></div>
      <div class="form-group"><label>Prefijos de salida de la central</label><input type="text" id="c-prefijos" value="${esc(p.prefijos_salida.join(', '))}" ${dis} />
      <div class="field-hint">Se quitan del número destino antes de normalizar (p. ej. 0 o 9 para tomar línea). Separados por coma.</div></div>
      <div class="form-group"><label>Franjas horarias</label><div id="c-franjas"></div>${editable ? `<button class="btn btn-outline btn-sm" id="c-franja-mas">+ Franja</button>` : ''}</div>`)}</div>` +
    card('Formato del CSV para uContact', `<div class="form-row"><div class="form-group"><label>Separador</label><input type="text" id="c-sep" value="${esc(p.csv_ucontact.separador)}" maxlength="1" ${dis} /></div><div></div></div>
      <div id="c-cols"></div>${editable ? `<button class="btn btn-outline btn-sm" id="c-col-mas">+ Columna</button>` : ''}`) +
    `<div class="grid-2">${editable ? card('Guardar', `<div class="form-group"><label>Comentario del cambio</label><input type="text" id="c-coment" placeholder="p. ej. enfriamiento a 12 meses (dirección, 30/10)" /></div>
      <button class="btn btn-orange" id="c-guardar">Guardar nueva versión</button>`) : ''}
      ${card('Historial de versiones', tabla([{ t: 'Versión', f: h => `<a class="link" data-ver="${h.version}">v${h.version}</a>` }, { t: 'Autor', k: 'autor' },
        { t: 'Comentario', k: 'comentario' }, { t: 'Fecha', f: h => fechaHora(h.fecha) }], c.historial), '', true)}</div>`;

  let franjas = p.franjas.map(f => ({ ...f }));
  let cols = p.csv_ucontact.columnas.map(x => ({ ...x }));
  const pintarFranjas = () => {
    $('#c-franjas').innerHTML = franjas.map((f, i) => `<div class="toolbar mb">
      <input type="text" data-f="${i}" data-k="nombre" value="${esc(f.nombre)}" style="width:130px" ${dis} />
      <span class="chips">${[1, 2, 3, 4, 5, 6, 7].map(d => `<span class="chip ${f.dias.includes(d) ? 'on' : ''}" data-fd="${i}" data-d="${d}">${DIAS[d]}</span>`).join('')}</span>
      <input type="time" data-f="${i}" data-k="desde" value="${f.desde}" style="width:110px" ${dis} /> a <input type="time" data-f="${i}" data-k="hasta" value="${f.hasta}" style="width:110px" ${dis} />
      ${editable ? `<button class="btn btn-outline btn-sm btn-del" data-fx="${i}">×</button>` : ''}</div>`).join('');
    $$('[data-f]').forEach(inp => inp.onchange = () => { franjas[+inp.dataset.f][inp.dataset.k] = inp.value; });
    if (editable) $$('[data-fd]').forEach(ch => ch.onclick = () => {
      const f = franjas[+ch.dataset.fd]; const d = +ch.dataset.d;
      f.dias = f.dias.includes(d) ? f.dias.filter(x => x !== d) : [...f.dias, d].sort(); pintarFranjas();
    });
    $$('[data-fx]').forEach(b => b.onclick = () => { franjas.splice(+b.dataset.fx, 1); pintarFranjas(); });
  };
  const pintarCols = () => {
    $('#c-cols').innerHTML = cols.map((x, i) => `<div class="toolbar mb"><span class="muted small mono">${i + 1}</span>
      <input type="text" data-cc="${i}" value="${esc(x.columna)}" placeholder="nombre de columna" style="width:200px" ${dis} />
      <select class="fselect" data-cv="${i}" style="width:auto" ${dis}>${CAMPOS_CSV.map(k => `<option ${k === x.campo ? 'selected' : ''}>${k}</option>`).join('')}</select>
      ${editable ? `<button class="btn btn-outline btn-sm btn-del" data-cx="${i}">×</button>` : ''}</div>`).join('');
    $$('[data-cc]').forEach(i => i.onchange = () => { cols[+i.dataset.cc].columna = i.value; });
    $$('[data-cv]').forEach(i => i.onchange = () => { cols[+i.dataset.cv].campo = i.value; });
    $$('[data-cx]').forEach(b => b.onclick = () => { cols.splice(+b.dataset.cx, 1); pintarCols(); });
  };
  pintarFranjas(); pintarCols();
  if ($('#c-franja-mas')) $('#c-franja-mas').onclick = () => { franjas.push({ nombre: 'nueva', dias: [1, 2, 3, 4, 5], desde: '09:00', hasta: '12:00' }); pintarFranjas(); };
  if ($('#c-col-mas')) $('#c-col-mas').onclick = () => { cols.push({ columna: 'columna', campo: 'rut' }); pintarCols(); };
  $$('[data-ver]').forEach(a => a.onclick = async () => {
    const v = await api.get('/config/' + a.dataset.ver);
    modal({ titulo: `Configuración v${v.version}`, cuerpo: json(v.parametros), acciones: [{ t: 'Cerrar' }], ancho: 720 });
  });
  if ($('#c-guardar')) $('#c-guardar').onclick = async () => {
    const nuevo = {
      ...p,
      umbral_intermediario: +$('#c-umbral').value, meses_enfriamiento: +$('#c-enfr').value,
      reglas_disponibilidad: Object.fromEntries($$('[data-regla]').map(i => [i.dataset.regla, i.checked])),
      contacto_efectivo: $$('[data-efectivo]').filter(i => i.checked).map(i => i.dataset.efectivo),
      reglas_fusion: $$('[data-fusion]').filter(i => i.checked).map(i => i.dataset.fusion),
      confianza_fuentes: Object.fromEntries($$('[data-conf]').map(i => [i.dataset.conf, +i.value])),
      destinos_internos: $('#c-internos').value.split('\n').map(s => s.trim()).filter(Boolean),
      prefijos_salida: $('#c-prefijos').value.split(',').map(s => s.trim()).filter(Boolean),
      franjas, csv_ucontact: { separador: $('#c-sep').value || ';', columnas: cols },
    };
    const r = await api.put('/config', { parametros: nuevo, comentario: $('#c-coment').value || null });
    toast(`Guardada la versión ${r.version}`, 'ok');
    config(ctx);
  };
}

export async function naturalezas(ctx) {
  const lista = await api.get('/naturalezas');
  const editable = ctx.puede('admin');
  main().innerHTML = pageHeader('Naturalezas', 'jurídicas', 'Catálogo editable. Las empresas de una naturaleza excluida se guardan y se actualizan, pero nunca entran a un marco muestral ni a un CSV.',
    editable ? `<button class="btn btn-orange" id="n-nueva">+ Naturaleza</button>` : '') +
    card('Catálogo', tabla([
      { t: 'Código', f: n => `<span class="mono td-strong">${esc(n.codigo)}</span>` }, { t: 'Nombre', k: 'nombre' },
      { t: 'Empresas', cls: 'num', f: n => num(n.empresas) },
      { t: 'Contacto', f: n => editable ? `<label class="check"><input type="checkbox" data-excl="${esc(n.codigo)}" data-nombre="${esc(n.nombre)}" ${n.excluida ? 'checked' : ''} /> excluida</label>`
        : (n.excluida ? est('error', 'excluida') : est('ok', 'habilitada')) },
    ], lista), '', true) +
    `<p class="small muted mt">Cambiar una exclusión crea una versión nueva de la configuración. La carga inicial sale de la hoja "excluidos" del Excel de referencia (ver fase0/cargar_excluidos.py).</p>`;
  $$('[data-excl]').forEach(i => i.onchange = async () => {
    try {
      await api.post('/naturalezas', { codigo: i.dataset.excl, nombre: i.dataset.nombre, excluida: i.checked });
      toast(`${i.dataset.excl}: ${i.checked ? 'excluida' : 'habilitada'}`, 'ok');
    } catch (e) { toast(e.message, 'err'); i.checked = !i.checked; }
  });
  if ($('#n-nueva')) $('#n-nueva').onclick = async () => {
    const r = await modal({ titulo: 'Nueva naturaleza jurídica', cuerpo: `
      <div class="form-row"><div class="form-group"><label>Código</label><input type="text" id="nn-c" /></div><div class="form-group"><label>Nombre</label><input type="text" id="nn-n" /></div></div>
      <label class="check"><input type="checkbox" id="nn-e" /> Excluida de contacto</label>`,
    acciones: [{ t: 'Cancelar' }, { t: 'Guardar', cls: 'btn-orange', fn: (b) => api.post('/naturalezas', { codigo: $('#nn-c', b).value, nombre: $('#nn-n', b).value, excluida: $('#nn-e', b).checked }) }] });
    if (r) naturalezas(ctx);
  };
}

export async function noLlamar(ctx, params) {
  const activos = !(params && params.get && params.get('todos'));
  const lista = await api.get('/no-llamar', { activos });
  const puede = ctx.puede('admin', 'steward');
  main().innerHTML = pageHeader('No llamar', '', 'Pedidos de no llamar por empresa, teléfono o contacto (Ley 18.331). Se respetan en todas las muestras y exportaciones desde que se registran.',
    puede ? `<button class="btn btn-danger" id="nl-nuevo">+ Registrar pedido</button>` : '') +
    card(activos ? 'Activos' : 'Todos', tabla([
      { t: 'Alcance', f: n => est('preview', n.alcance) }, { t: 'Objeto', f: n => n.alcance === 'empresa' ? `<a class="link" href="#/empresas/${(n.objeto || '').slice(0, 12)}">${esc(n.objeto)}</a>` : esc(n.objeto) },
      { t: 'Motivo', k: 'motivo' }, { t: 'Solicitante', k: 'solicitante' }, { t: 'Registró', k: 'registrado_por' }, { t: 'Fecha', f: n => fechaHora(n.fecha) },
      { t: 'Estado', f: n => n.activo ? est('error', 'activo') : est('ok', 'levantado') },
      { t: '', f: n => n.activo && ctx.puede('admin') ? `<button class="btn btn-outline btn-sm" data-levantar="${n.id}">Levantar</button>` : '' },
    ], lista, 'Sin registros'), `<a class="link small" href="#/no-llamar${activos ? '?todos=1' : ''}">${activos ? 'Ver también los levantados' : 'Ver solo activos'}</a>`, true);
  if ($('#nl-nuevo')) $('#nl-nuevo').onclick = async () => {
    const r = await modal({ titulo: 'Registrar pedido de no llamar', cuerpo: `
      <div class="form-group"><label>Alcance</label><select class="fselect" id="nl-a"><option value="empresa">Empresa (RUT)</option><option value="telefono">Teléfono</option><option value="contacto">Contacto (id)</option></select></div>
      <div class="form-group"><label>RUT, teléfono o id de contacto</label><input type="text" id="nl-o" /></div>
      <div class="form-group"><label>Motivo</label><input type="text" id="nl-m" /></div>
      <div class="form-group"><label>Quién lo pidió</label><input type="text" id="nl-s" /></div>`,
    acciones: [{ t: 'Cancelar' }, { t: 'Registrar', cls: 'btn-danger', fn: (b) => {
      const a = $('#nl-a', b).value; const o = $('#nl-o', b).value.trim();
      return api.post('/no-llamar', { alcance: a, rut: a === 'empresa' ? o : null, telefono: a === 'telefono' ? o : null,
        contacto_id: a === 'contacto' ? +o : null, motivo: $('#nl-m', b).value, solicitante: $('#nl-s', b).value });
    } }] });
    if (r) { toast('Registrado', 'ok'); noLlamar(ctx, params); }
  };
  $$('[data-levantar]').forEach(b => b.onclick = async () => {
    const motivo = await pedirTexto('Levantar pedido de no llamar', 'Motivo');
    if (!motivo) return;
    await api.del(`/no-llamar/${b.dataset.levantar}?motivo=${encodeURIComponent(motivo)}`);
    noLlamar(ctx, params);
  });
}

const ROLES = [['admin', 'Administrador/a'], ['steward', 'Data steward'], ['jefe', 'Jefe/a de proyecto'], ['coordinador', 'Coordinador/a de campo'], ['lectura', 'Lectura']];

export async function usuarios(ctx) {
  const lista = await api.get('/usuarios');
  main().innerHTML = pageHeader('Usuarios', '', 'Quién entra y con qué rol. El acceso se valida en la API con el token de Firebase Auth.',
    `<button class="btn btn-orange" id="u-nuevo">+ Usuario</button>`) +
    card(`${lista.length} usuarios`, tabla([
      { t: 'Email', f: u => `<span class="td-strong">${esc(u.email)}</span>` }, { t: 'Nombre', k: 'nombre' },
      { t: 'Rol', f: u => `<span class="badge ${u.rol === 'admin' ? 'badge-admin' : 'badge-user'}">${esc((ROLES.find(r => r[0] === u.rol) || [])[1] || u.rol)}</span>` },
      { t: 'Exporta contactos', f: u => u.exportar_contactos ? est('ok', 'sí') : '—' }, { t: 'Estado', f: u => u.activo ? '<span class="badge badge-on">activo</span>' : '<span class="badge badge-off">inactivo</span>' },
      { t: '', f: u => `<button class="btn btn-outline btn-sm" data-u="${esc(u.email)}">Editar</button>` },
    ], lista), '', true) +
    `<p class="small muted mt">El usuario tiene que existir también en Firebase Authentication (consola de Firebase → Authentication → Agregar usuario), con el mismo email.</p>`;
  const editar = async (u = { activo: true, rol: 'lectura' }) => {
    const r = await modal({ titulo: u.email ? 'Editar usuario' : 'Nuevo usuario', cuerpo: `
      <div class="form-group"><label>Email</label><input type="email" id="u-e" value="${esc(u.email || '')}" ${u.email ? 'disabled' : ''} /></div>
      <div class="form-group"><label>Nombre</label><input type="text" id="u-n" value="${esc(u.nombre || '')}" /></div>
      <div class="form-group"><label>Rol</label><select class="fselect" id="u-r">${ROLES.map(([k, t]) => `<option value="${k}" ${k === u.rol ? 'selected' : ''}>${t}</option>`).join('')}</select></div>
      <div><label class="check"><input type="checkbox" id="u-x" ${u.exportar_contactos ? 'checked' : ''} /> Puede exportar contactos personales (queda auditado)</label></div>
      <div class="mt"><label class="check"><input type="checkbox" id="u-a" ${u.activo ? 'checked' : ''} /> Activo</label></div>`,
    acciones: [{ t: 'Cancelar' }, { t: 'Guardar', cls: 'btn-orange', fn: (b) => api.post('/usuarios', { email: $('#u-e', b).value, nombre: $('#u-n', b).value || null,
      rol: $('#u-r', b).value, exportar_contactos: $('#u-x', b).checked, activo: $('#u-a', b).checked }) }] });
    if (r) usuarios(ctx);
  };
  $('#u-nuevo').onclick = () => editar();
  $$('[data-u]').forEach(b => b.onclick = () => editar(lista.find(u => u.email === b.dataset.u)));
}

export async function auditoria(ctx, params) {
  const f = { objeto: params.get('objeto') || '', actor: params.get('actor') || '', accion: params.get('accion') || '' };
  const lista = await api.get('/auditoria', { ...f, limite: 300 });
  main().innerHTML = pageHeader('Auditoría', '', 'Log append-only de cargas, fusiones, exclusiones, sorteos, exportaciones, ingestas y cambios de configuración. Se exporta a BigQuery cada día.') +
    `<div class="card mb"><div class="card-body"><div class="inline-form">
      <div class="form-group"><label>Acción (prefijo)</label><input type="text" id="au-accion" value="${esc(f.accion)}" placeholder="carga, muestra, config…" /></div>
      <div class="form-group"><label>Objeto</label><input type="text" id="au-objeto" value="${esc(f.objeto)}" placeholder="carga, muestra, empresa…" /></div>
      <div class="form-group"><label>Actor</label><input type="text" id="au-actor" value="${esc(f.actor)}" /></div>
      <div class="form-group"><button class="btn btn-dark" id="au-filtrar">Filtrar</button></div></div></div></div>` +
    card(`Últimos ${lista.length} eventos`, tabla([
      { t: 'Fecha', f: a => fechaHora(a.fecha) }, { t: 'Actor', k: 'actor' }, { t: 'Acción', f: a => `<span class="td-strong">${esc(a.accion)}</span>` },
      { t: 'Objeto', f: a => `${esc(a.objeto)} ${a.objeto_id ? `<span class="mono">${esc(a.objeto_id)}</span>` : ''}` },
      { t: 'Detalle', f: a => a.detalle ? `<details><summary class="link small">ver</summary>${json(a.detalle)}</details>` : '' },
    ], lista, 'Sin eventos'), '', true);
  $('#au-filtrar').onclick = () => {
    const q = new URLSearchParams(Object.entries({ accion: $('#au-accion').value, objeto: $('#au-objeto').value, actor: $('#au-actor').value }).filter(([, v]) => v));
    location.hash = '#/auditoria?' + q;
  };
}
