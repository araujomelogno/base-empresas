// Configuración, naturalezas, no llamar, usuarios y auditoría (R1.4, R1.12, R1.13)
import * as api from '../api.js';
import { $, $$, esc, main, toast, num, fechaHora, est, pageHeader, tabla, card, modal, pedirTexto, confirmar, tabs,
  json } from '../ui.js';

const CAMPOS_CSV = ['id_item', 'tel_e164', 'tel_nacional', 'tel_sin_mas', 'rut', 'razon_social', 'fantasia', 'contacto', 'contacto_cargo',
  'departamento', 'localidad', 'estrato', 'link', 'parte', 'muestra', 'origen_telefono'];
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
    tarjetaCdr(p.cdr, c.cdr_password, editable) +
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
      cdr: leerCdr(),
    };
    const r = await api.put('/config', { parametros: nuevo, comentario: $('#c-coment').value || null });
    toast(`Guardada la versión ${r.version}`, 'ok');
    config(ctx);
  };
  if (editable) activarCdr(ctx);
}

// ── CDR: conexión a la base MySQL de uContact (SPEC_job_cdr_en_cloud) ──
const TLS = [['preferido', 'Preferido (cifra si el servidor lo acepta)'], ['requerido', 'Requerido'], ['desactivado', 'Desactivado']];

const textoClave = (clave) => !clave ? '' : clave.configurada
  ? `${est('ok', 'configurada')} <span class="small muted">el ${fechaHora(clave.fecha)}${clave.por ? ' por ' + esc(clave.por) : ''}</span>`
  : est('error', 'sin configurar');

function tarjetaCdr(d, clave, editable) {
  const dis = editable ? '' : 'disabled';
  const campo = (id, label, valor, tipo = 'text', extra = '') =>
    `<div class="form-group"><label>${label}</label><input type="${tipo}" id="cd-${id}" value="${esc(valor ?? '')}" ${dis} ${extra} /></div>`;
  const estadoClave = textoClave(clave);
  return card('CDR — conexión a la base de uContact', `
    <p class="small muted mb">El job del CDR corre en Google Cloud todos los días a las 4:00 (hora de Montevideo) y lee las llamadas
    nuevas de esta base MySQL. Los parámetros se guardan con «Guardar nueva versión»; la contraseña va aparte, a Secret Manager, y no se vuelve a mostrar.</p>
    <div class="grid-2"><div>
      <div class="form-row">${campo('host', 'Servidor (host)', d.host, 'text', 'placeholder="mysql.ejemplo.com"')}${campo('puerto', 'Puerto', d.puerto, 'number', 'min="1"')}</div>
      <div class="form-row">${campo('base', 'Base', d.base, 'text', 'placeholder="uc"')}${campo('usuario', 'Usuario (solo lectura)', d.usuario)}</div>
      <div class="form-row">${campo('tabla', 'Tabla', d.tabla)}
        <div class="form-group"><label>Cifrado (TLS)</label><select class="fselect" id="cd-tls" ${dis}>${TLS.map(([k, t]) => `<option value="${k}" ${k === d.tls ? 'selected' : ''}>${t}</option>`).join('')}</select></div></div>
      <div class="form-row">${campo('zona', 'Zona horaria de calldate', d.zona_horaria)}${campo('lote', 'Llamadas por lote', d.lote_tamano, 'number', 'min="1"')}</div>
      <div class="form-group"><label>Consulta propia (opcional)</label><textarea class="finput code" id="cd-consulta" rows="3" ${dis}
        placeholder="Vacío = SELECT uniqueid, calldate, src, dst, duration, billsec, disposition, userfield, peeraccount, accountcode FROM <tabla> WHERE calldate >= %s AND calldate < %s ORDER BY calldate, uniqueid">${esc(d.consulta || '')}</textarea>
        <div class="field-hint">Un solo SELECT con las columnas de arriba (usá AS si se llaman distinto), ordenado por calldate, con uno (desde) o dos (desde, hasta) %s.</div></div>
      <label class="check"><input type="checkbox" id="cd-activo" ${d.activo ? 'checked' : ''} ${dis} /> Job del CDR activo</label>
    </div><div>
      ${editable ? `<div class="form-group"><label>Contraseña de MySQL</label>
        <div class="gap"><input type="password" id="cd-clave" autocomplete="new-password" placeholder="••••••••" style="flex:1" />
        <button class="btn btn-outline btn-sm" id="cd-guardar-clave">Guardar contraseña</button></div>
        <div class="field-hint" id="cd-clave-estado">${estadoClave}</div></div>
      <div class="gap mb"><button class="btn btn-dark" id="cd-probar">Probar conexión</button>
        <span class="small muted">Usa los datos de este formulario y la contraseña escrita (o la guardada).</span></div>
      <div id="cd-prueba"></div>
      <div class="card-header-title mt mb">Correr el job</div>
      <div class="gap mb"><button class="btn btn-orange" id="cd-correr">Correr ahora</button></div>
      <div class="inline-form">
        <div class="form-group"><label>Reprocesar desde</label><input type="date" id="cd-desde" /></div>
        <div class="form-group"><label>Hasta (opcional)</label><input type="date" id="cd-hasta" /></div>
        <div class="form-group"><button class="btn btn-outline" id="cd-reprocesar">Reprocesar</button></div></div>
      <label class="check mt"><input type="checkbox" id="cd-dry" /> Prueba sin guardar intentos (dry-run)</label>
      <div id="cd-corrida" class="mt"></div>` : '<p class="small muted">Solo un administrador puede cambiar la conexión o correr el job.</p>'}
    </div></div>`);
}

function leerCdr() {
  return {
    host: $('#cd-host').value.trim(), puerto: +$('#cd-puerto').value || 3306, base: $('#cd-base').value.trim(),
    usuario: $('#cd-usuario').value.trim(), tabla: $('#cd-tabla').value.trim() || 'cdr', tls: $('#cd-tls').value,
    zona_horaria: $('#cd-zona').value.trim() || 'America/Montevideo', lote_tamano: +$('#cd-lote').value || 2000,
    consulta: $('#cd-consulta').value.trim() || null, activo: $('#cd-activo').checked,
  };
}

function resultadoPrueba(r) {
  const detalle = [r.version ? `MySQL ${esc(r.version)}` : '', r.tls === null || r.tls === undefined ? '' : r.tls ? 'conexión cifrada (TLS)' : 'conexión SIN cifrar',
    r.columnas && r.columnas.length ? `columnas: ${esc(r.columnas.join(', '))}` : ''].filter(Boolean).join(' · ');
  return `<div class="alert ${r.ok ? 'alert-success' : 'alert-error'}"><span><strong>${esc(r.mensaje)}</strong>${detalle ? `<br><span class="small">${detalle}</span>` : ''}</span></div>`;
}

async function seguirCorrida(id, el) {
  for (;;) {
    const c = await api.get(`/cdr/corridas/${id}`);
    const k = c.conteos || {};
    el.innerHTML = `<div class="alert ${c.estado === 'error' ? 'alert-error' : c.estado === 'ok' ? 'alert-success' : 'alert-info'}"><span>
      Corrida #${c.id} ${est(c.estado)} ${c.dry_run ? '(dry-run)' : ''}<br><span class="small">${k.llamadas_a_empresas !== undefined ? `${num(k.llamadas)} llamadas · ${num(k.llamadas_a_empresas)} a empresas (${num(k.nuevas || 0)} nuevas)`
        : `${k.filas_leidas !== undefined ? `${num(k.filas_leidas)} filas leídas · ` : ''}${num(k.intentos_nuevos || 0)} intentos nuevos`}${c.mensaje ? ' · ' + esc(c.mensaje) : ''}</span></span></div>`;
    if (c.estado !== 'en_curso') return c;
    await new Promise(r => setTimeout(r, 2000));
  }
}

function activarCdr(ctx) {
  $('#cd-guardar-clave').onclick = async () => {
    const v = $('#cd-clave').value;
    if (!v) return toast('Escribí la contraseña', 'err');
    const estado = await api.put('/config/cdr/password', { password: v });
    $('#cd-clave').value = '';
    $('#cd-clave-estado').innerHTML = textoClave(estado);  // sin redibujar: no se pierden los datos sin guardar
    toast('Contraseña guardada en Secret Manager', 'ok');
  };
  $('#cd-probar').onclick = async () => {
    const b = $('#cd-probar'); b.disabled = true;
    $('#cd-prueba').innerHTML = '<div class="small muted">Probando la conexión (hasta 10 segundos)…</div>';
    try { $('#cd-prueba').innerHTML = resultadoPrueba(await api.post('/config/cdr/probar', { parametros: leerCdr(), password: $('#cd-clave').value || null })); }
    catch (e) { $('#cd-prueba').innerHTML = `<div class="alert alert-error"><span>${esc(e.message)}</span></div>`; }
    finally { b.disabled = false; }
  };
  const correr = async (cuerpo) => {
    try {
      const r = await api.post('/config/cdr/correr', { ...cuerpo, dry_run: $('#cd-dry').checked });
      toast(`Corrida #${r.corrida_id} lanzada`, 'ok');
      await seguirCorrida(r.corrida_id, $('#cd-corrida'));
    } catch (e) { toast(e.message, 'err'); }
  };
  $('#cd-correr').onclick = () => correr({});
  $('#cd-reprocesar').onclick = () => {
    if (!$('#cd-desde').value) return toast('Indicá la fecha desde', 'err');
    correr({ desde: $('#cd-desde').value, hasta: $('#cd-hasta').value || null });
  };
}

// ── Atributos (C1) ──
const TIPOS_ATRIBUTO = { texto: 'Texto', numero: 'Número', fecha: 'Fecha', lista: 'Lista de opciones' };
const NUCLEO = [['rut', 'RUT (obligatorio)'], ['razon_social', 'Razón social'], ['fantasia', 'Nombre de fantasía'],
  ['naturaleza', 'Naturaleza jurídica'], ['ciiu', 'CIIU / rubro'], ['tamano', 'Tamaño'], ['departamento', 'Departamento'],
  ['localidad', 'Localidad'], ['direccion', 'Dirección'], ['web', 'Web'], ['estado', 'Estado (activa / cerrada)']];

function formAtributo(a = {}) {
  const nuevo = !a.id;
  // F1.5: la clave se genera sola a partir del nombre; acá solo se muestra (de solo lectura) al editar
  return `<div class="form-row"><div class="form-group"><label>Nombre visible <span class="req">*</span></label><input type="text" id="at-nombre" value="${esc(a.nombre || '')}" placeholder="p. ej. Cantidad de empleados" /></div>
    ${nuevo ? `<div class="form-group"><label>Clave</label><div class="field-hint">Se genera sola a partir del nombre (minúsculas, sin tildes, con guiones bajos). Si ya existe, se agrega _2, _3…</div></div>`
      : `<div class="form-group"><label>Clave</label><div class="mono" style="padding:.45rem 0">${esc(a.clave)}</div><div class="field-hint">No cambia aunque cambies el nombre.</div></div>`}</div>
    <div class="form-row"><div class="form-group"><label>Tipo <span class="req">*</span></label><select class="fselect" id="at-tipo" ${nuevo || !a.n_valores ? '' : 'disabled'}>${
      Object.entries(TIPOS_ATRIBUTO).map(([k, t]) => `<option value="${k}" ${k === (a.tipo || 'texto') ? 'selected' : ''}>${t}</option>`).join('')}</select></div>
    <div class="form-group" id="at-norm-g"><label>Normalizar el texto al cargar</label><select class="fselect" id="at-norm">${
      [['ninguna', 'Sin cambios (solo se recortan los espacios)'], ['capital', 'Mayúscula inicial'], ['mayusculas', 'MAYÚSCULAS']].map(([k, t]) =>
        `<option value="${k}" ${k === (a.normalizar_texto || 'ninguna') ? 'selected' : ''}>${t}</option>`).join('')}</select></div>
    <div class="form-group" id="at-opciones-g"><label>Opciones (una por línea, opcional)</label><textarea id="at-opciones" rows="3">${esc((a.opciones || []).join('\n'))}</textarea>
    <div class="field-hint">Pueden quedar vacías: se completan en la carga, con la traducción de valores.</div></div></div>
    <div class="form-group"><label>Sinónimos para el mapeo automático (separados por coma)</label><input type="text" id="at-sinonimos" value="${esc((a.sinonimos || []).join(', '))}" placeholder="p. ej. empleados, personal, cant. empleados" />
    <div class="field-hint">Opcional. Si una columna del archivo se llama así, la carga la reconoce sola. También se reconocen el nombre y la clave.</div></div>
    ${(a.ambito || 'empresa') === 'contacto' ? '<input type="hidden" id="at-filtro" /><span id="at-estrato-g"><input type="hidden" id="at-estrato" /></span>' : `
    <label class="check"><input type="checkbox" id="at-filtro" ${a.filtrable ? 'checked' : ''} /> Sirve como filtro del sorteo</label>
    <label class="check" id="at-estrato-g"><input type="checkbox" id="at-estrato" ${a.estratificable ? 'checked' : ''} /> Sirve como estrato (solo listas)</label>`}
    ${nuevo ? '' : `<label class="check"><input type="checkbox" id="at-activo" ${a.activo ? 'checked' : ''} /> Activo</label>`}`;
}

function leerAtributo(b) {
  return {
    nombre: $('#at-nombre', b).value.trim(), tipo: $('#at-tipo', b).value, normalizar_texto: $('#at-norm', b).value,
    opciones: $('#at-opciones', b).value.split('\n').map(s => s.trim()).filter(Boolean),
    sinonimos: $('#at-sinonimos', b).value.split(',').map(s => s.trim()).filter(Boolean),
    filtrable: $('#at-filtro', b).checked, estratificable: $('#at-estrato', b).checked,
    ...($('#at-activo', b) ? { activo: $('#at-activo', b).checked } : {}),
  };
}

function activarFormAtributo() {
  const ver = () => {
    const lista = $('#at-tipo').value === 'lista';
    $('#at-opciones-g').style.display = lista ? '' : 'none';
    $('#at-norm-g').style.display = $('#at-tipo').value === 'texto' ? '' : 'none';
    $('#at-estrato-g').style.display = lista ? '' : 'none';
    if (!lista) $('#at-estrato').checked = false;
  };
  $('#at-tipo').onchange = ver;
  ver();
}

export async function atributos(ctx, params) {
  const ambito = (params && params.get('ambito')) === 'contacto' ? 'contacto' : 'empresa';
  const lista = await api.get('/atributos', { ambito });
  const editable = ctx.puede('admin');
  const deContacto = ambito === 'contacto';
  main().innerHTML = pageHeader('Atributos', deContacto ? 'de contacto' : 'de empresa', deContacto
    ? 'Datos de las personas de contacto: decisor sí/no, antigüedad en el cargo… Se cargan desde la carga (bloque Contacto), el .sav o la ficha, y se pueden exportar. No se usan para filtrar ni estratificar el sorteo.'
    : 'Datos que traen las bases y que no son campos del sistema: cantidad de empleados, exporta sí/no, cámara a la que pertenece… Un atributo nuevo se puede mapear en la próxima carga y usar para filtrar y estratificar.',
    editable ? `<button class="btn btn-orange" id="at-nuevo">+ Nuevo atributo</button>` : '') +
    tabs('atributos', [['empresa', 'De empresa'], ['contacto', 'De contacto']], ambito) +
    card(deContacto ? 'Atributos de contacto' : 'Atributos de empresa', tabla([
      { t: 'Nombre', f: a => `<span class="td-strong">${esc(a.nombre)}</span><div class="small muted mono">${esc(a.clave)}</div>` },
      { t: 'Tipo', f: a => esc(TIPOS_ATRIBUTO[a.tipo]) + (a.opciones.length ? `<div class="small muted">${a.opciones.map(esc).join(' · ')}</div>` : '') },
      { t: 'Sinónimos', f: a => `<span class="small">${a.sinonimos.map(esc).join(', ') || '—'}</span>` },
      ...(deContacto ? [] : [{ t: 'Filtro', f: a => a.filtrable ? est('ok', 'sí') : '—' }, { t: 'Estrato', f: a => a.estratificable ? est('ok', 'sí') : '—' }]),
      { t: deContacto ? 'Contactos con valor' : 'Empresas con valor', cls: 'num', f: a => num(a.n_valores) }, { t: 'Estado', f: a => a.activo ? est('activa', 'activo') : est('pendiente', 'inactivo') },
      { t: '', f: a => editable && a.fusionado_en ? `<span class="small muted">${esc(a.nota || 'fusionado')}</span>` : editable ? `<div class="td-actions"><button class="btn btn-outline btn-sm" data-at-editar="${a.id}">Editar</button>
        <button class="btn btn-outline btn-sm" data-at-fusionar="${a.id}">Fusionar con…</button>
        ${a.n_valores ? '' : `<button class="btn btn-outline btn-sm btn-del" data-at-borrar="${a.id}">Borrar</button>`}</div>` : '' },
    ], lista, 'Todavía no hay atributos'), '', true) +
    (deContacto ? '' : card('Campos del sistema (no editables)', `<p class="small muted mb">Las reglas de disponibilidad, los estratos, la fusión y las exclusiones dependen de estos campos, por eso no se pueden borrar ni renombrar. Las cargas también aceptan teléfonos (con su origen) y los datos de una sucursal.</p>
      <div class="chips">${NUCLEO.map(([k, t]) => `<span class="chip" title="${esc(k)}">${esc(t)}</span>`).join('')}</div>`)) +
    `<p class="small muted mt">Desactivar un atributo lo saca del mapeo y de los filtros pero conserva sus valores. Solo se borra un atributo sin valores y que no se use en una muestra activa.</p>`;
  $$('[data-tabs="atributos"] .tab').forEach(b => b.onclick = () => { location.hash = `#/atributos?ambito=${b.dataset.tab}`; });
  const guardar = async (a) => {
    const r = await modal({ titulo: a ? 'Editar atributo' : `Nuevo atributo ${deContacto ? 'de contacto' : 'de empresa'}`, ancho: 640,
      cuerpo: formAtributo(a || { ambito }),
      acciones: [{ t: 'Cancelar' }, { t: 'Guardar', cls: 'btn-orange', fn: async (b) => {
        if (a) return api.put('/atributos/' + a.id, leerAtributo(b));
        // F4.1: si ya hay uno parecido, se avisa y se ofrece usarlo en lugar de crear otro
        const d = leerAtributo(b);
        const par = d.nombre ? await api.get('/atributos/parecidos', { texto: d.nombre, ambito }) : [];
        if (par.length) {
          const ok = await modal({ titulo: 'Ya hay un atributo parecido', cuerpo: `<p>«${esc(d.nombre)}» se parece a:</p><ul class="aviso-lista">${
            par.map(x => `<li><strong>${esc(x.nombre)}</strong> (${Math.round(x.similitud * 100)} %${x.por !== x.nombre ? `, por «${esc(x.por)}»` : ''})</li>`).join('')}</ul>
            <p class="small muted">Si es el mismo dato, usá el existente (podés agregarle un sinónimo). Crear otro duplica los valores.</p>`,
            acciones: [{ t: 'Usar el existente' }, { t: 'Crear igual', cls: 'btn-orange', fn: () => true }] });
          if (!ok) return false;
        }
        return api.post('/atributos', { ...d, ambito });
      } }] });
    if (r) { toast('Atributo guardado', 'ok'); atributos(ctx, params); }
  };
  if ($('#at-nuevo')) $('#at-nuevo').onclick = () => { guardar(null); activarFormAtributo(); };
  $$('[data-at-editar]').forEach(b => b.onclick = () => { guardar(lista.find(a => a.id === +b.dataset.atEditar)); activarFormAtributo(); });
  $$('[data-at-fusionar]').forEach(b => b.onclick = async () => {
    const a = lista.find(x => x.id === +b.dataset.atFusionar);
    const destinos = lista.filter(x => x.id !== a.id && x.activo && !x.fusionado_en && (x.tipo === a.tipo || x.tipo === 'texto'));
    if (!destinos.length) return toast('No hay otro atributo activo del mismo ámbito y de un tipo compatible', 'err');
    const r = await modal({ titulo: `Fusionar «${a.nombre}» con…`, ancho: 600, cuerpo: `
      <div class="form-group"><label>Atributo que queda</label><select class="fselect" id="fu-destino">${destinos.map(x => `<option value="${x.id}">${esc(x.nombre)} (${esc(TIPOS_ATRIBUTO[x.tipo])})</option>`).join('')}</select></div>
      <ul class="aviso-lista small"><li>Los valores de «${esc(a.nombre)}» pasan al elegido como historia nueva (fuente fusión) y se recalcula el valor vigente.</li>
      <li>Su nombre y sus sinónimos pasan a los sinónimos del elegido; las opciones de lista se unifican.</li>
      <li>«${esc(a.nombre)}» queda inactivo, con la nota «fusionado en …». No se puede si se usa como filtro o estrato de una muestra activa.</li></ul>`,
      acciones: [{ t: 'Cancelar' }, { t: 'Fusionar', cls: 'btn-danger', fn: (x) => api.post(`/atributos/${a.id}/fusionar`, { destino_id: +$('#fu-destino', x).value }) }] });
    if (r) { toast(`Fusionado: ${num(r.empresas + r.contactos)} con valores pasados`, 'ok'); atributos(ctx, params); }
  });
  $$('[data-at-borrar]').forEach(b => b.onclick = async () => {
    const a = lista.find(x => x.id === +b.dataset.atBorrar);
    if (!await confirmar('Borrar atributo', `Se borra «${a.nombre}». No tiene valores cargados.`, 'Borrar', 'btn-danger')) return;
    try { await api.del('/atributos/' + a.id); atributos(ctx, params); } catch (e) { toast(e.message, 'err'); }
  });
}

// ── Orígenes de teléfono (C4) ──
export async function origenes(ctx) {
  const lista = await api.get('/origenes-telefono');
  const editable = ctx.puede('admin');
  main().innerHTML = pageHeader('Orígenes', 'de teléfono', 'De dónde salió cada teléfono (guía, DGI, web, estudio anterior…). El orden es la prioridad: el CSV para uContact pone primero los teléfonos de los orígenes de arriba.',
    editable ? `<button class="btn btn-orange" id="or-nuevo">+ Nuevo origen</button>` : '') +
    card('Orígenes en orden de prioridad', tabla([
      { t: '#', cls: 'num', f: (o, i) => i + 1 },
      { t: 'Origen', f: o => `<span class="td-strong">${esc(o.nombre)}</span><div class="small muted mono">${esc(o.codigo)}</div>` },
      { t: 'Tipo', f: o => o.sistema ? est('pendiente', 'de sistema') : '—' },
      { t: 'Teléfonos', cls: 'num', f: o => num(o.n_vinculos) }, { t: 'Estado', f: o => o.activo ? est('activa', 'activo') : est('pendiente', 'inactivo') },
      { t: '', f: (o, i) => editable ? `<div class="td-actions">
        ${o.codigo !== 'sin_dato' && i > 0 ? `<button class="btn btn-outline btn-sm" data-or-subir="${i}" title="Subir prioridad">↑</button>` : ''}
        ${o.codigo !== 'sin_dato' && i < lista.length - 2 ? `<button class="btn btn-outline btn-sm" data-or-bajar="${i}" title="Bajar prioridad">↓</button>` : ''}
        <button class="btn btn-outline btn-sm" data-or-editar="${o.id}">Editar</button>
        ${!o.sistema && !o.n_vinculos ? `<button class="btn btn-outline btn-sm btn-del" data-or-borrar="${o.id}">Borrar</button>` : ''}</div>` : '' },
    ], lista), '', true) +
    `<p class="small muted mt"><strong>Sala</strong> (teléfonos alternativos que llegan en el .sav), <strong>Manual</strong> (agregados en la ficha) y <strong>Sin dato</strong> (teléfonos cargados antes de que existiera el origen) son de sistema: no se borran. Un origen con teléfonos no se borra: se desactiva.</p>`;
  const mover = async (i, d) => {
    const cods = lista.map(o => o.codigo);
    [cods[i], cods[i + d]] = [cods[i + d], cods[i]];
    await api.put('/origenes-telefono/orden', { codigos: cods }); origenes(ctx);
  };
  $$('[data-or-subir]').forEach(b => b.onclick = () => mover(+b.dataset.orSubir, -1));
  $$('[data-or-bajar]').forEach(b => b.onclick = () => mover(+b.dataset.orBajar, 1));
  const form = (o = {}) => `<div class="form-row"><div class="form-group"><label>Nombre</label><input type="text" id="or-nombre" value="${esc(o.nombre || '')}" placeholder="p. ej. Guía telefónica" /></div>
    <div class="form-group"><label>Código</label><input type="text" id="or-codigo" value="${esc(o.codigo || '')}" ${o.id ? 'disabled' : ''} placeholder="se genera del nombre" /></div></div>
    ${o.id && !o.sistema ? `<label class="check"><input type="checkbox" id="or-activo" ${o.activo ? 'checked' : ''} /> Activo</label>` : ''}`;
  if ($('#or-nuevo')) $('#or-nuevo').onclick = async () => {
    const r = await modal({ titulo: 'Nuevo origen de teléfono', cuerpo: form() + `<p class="field-hint">Se agrega al final de la lista (antes de «Sin dato»); después se puede subir.</p>`,
      acciones: [{ t: 'Cancelar' }, { t: 'Guardar', cls: 'btn-orange', fn: (b) => api.post('/origenes-telefono', { nombre: $('#or-nombre', b).value, codigo: $('#or-codigo', b).value.trim() || null }) }] });
    if (r) origenes(ctx);
  };
  $$('[data-or-editar]').forEach(b => b.onclick = async () => {
    const o = lista.find(x => x.id === +b.dataset.orEditar);
    const r = await modal({ titulo: 'Editar origen', cuerpo: form(o),
      acciones: [{ t: 'Cancelar' }, { t: 'Guardar', cls: 'btn-orange', fn: (x) => api.put('/origenes-telefono/' + o.id, {
        nombre: $('#or-nombre', x).value, ...($('#or-activo', x) ? { activo: $('#or-activo', x).checked } : {}) }) }] });
    if (r) origenes(ctx);
  });
  $$('[data-or-borrar]').forEach(b => b.onclick = async () => {
    const o = lista.find(x => x.id === +b.dataset.orBorrar);
    if (!await confirmar('Borrar origen', `Se borra «${o.nombre}». No tiene teléfonos.`, 'Borrar', 'btn-danger')) return;
    try { await api.del('/origenes-telefono/' + o.id); origenes(ctx); } catch (e) { toast(e.message, 'err'); }
  });
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

const CORREO_TIPO = { bienvenida: 'bienvenida', restablecer: 'restablecer' };

// El enlace de acceso se muestra una sola vez, solo cuando el correo no salió (R3)
async function mostrarEnlace(email, r) {
  await modal({
    titulo: 'Enlace de acceso — se muestra una sola vez', ancho: 620, cuerpo: `
      <div class="alert alert-warn"><span>El correo a <strong>${esc(email)}</strong> no salió: ${esc(r.correo.detalle)}</span></div>
      <p class="small mb">La cuenta quedó creada. Pasale este enlace a la persona por otro canal (por ejemplo, WhatsApp o Teams)
      para que cree su contraseña. <strong>Vence en una hora</strong> y no se guarda en ningún lado: si se pierde, usá «Reenviar acceso».</p>
      <div class="form-group"><label>Enlace</label><input type="text" id="enl" value="${esc(r.enlace)}" readonly /></div>`,
    acciones: [{ t: 'Copiar enlace', cls: 'btn-orange', fn: async (b) => {
      const i = $('#enl', b); i.select();
      try { await navigator.clipboard.writeText(i.value); } catch { document.execCommand('copy'); }
      toast('Enlace copiado', 'ok'); return false;
    } }, { t: 'Listo', cls: 'btn-dark' }],
  });
}

function avisoResultado(email, r) {
  if (r.enlace) return mostrarEnlace(email, r);
  if (r.estado === 'ya_existia') return toast(r.mensaje || 'La cuenta ya existía', 'ok');
  if (r.correo && r.correo.enviado) return toast(`Le enviamos a ${email} el correo de ${CORREO_TIPO[r.correo.tipo] || 'acceso'}`, 'ok');
  if (r.estado === 'actualizado') return toast('Usuario actualizado', 'ok');
  return toast('Guardado', 'ok');
}

export async function usuarios(ctx) {
  const lista = await api.get('/usuarios');
  const errorCuentas = lista.find(u => u.error_cuentas);
  main().innerHTML = pageHeader('Usuarios', '', 'Quién entra y con qué rol. Al dar de alta a alguien le llega un correo para crear su contraseña.',
    `<button class="btn btn-orange" id="u-nuevo">+ Usuario</button>`) +
    (errorCuentas ? `<div class="alert alert-warn"><span>${esc(errorCuentas.error_cuentas)}: el último ingreso no está disponible.</span></div>` : '') +
    card(`${lista.length} usuarios`, '<div class="compacta">' + tabla([
      { t: 'Usuario', f: u => `<span class="td-strong">${esc(u.nombre || u.email)}</span>${u.nombre ? `<div class="small muted">${esc(u.email)}</div>` : ''}` },
      { t: 'Rol', f: u => `<span class="badge ${u.rol === 'admin' ? 'badge-admin' : 'badge-user'}">${esc((ROLES.find(r => r[0] === u.rol) || [])[1] || u.rol)}</span>
        ${u.exportar_contactos ? '<div class="small muted mt" style="margin-top:.35rem">exporta contactos</div>' : ''}` },
      { t: 'Estado · último ingreso', f: u => `${u.activo ? '<span class="badge badge-on">activo</span>' : '<span class="badge badge-off">inactivo</span>'}
        <div class="small muted" style="margin-top:.35rem">${!u.cuenta ? 'sin cuenta' : u.cuenta.ultimo_ingreso ? fechaHora(u.cuenta.ultimo_ingreso) : 'nunca ingresó'}</div>` },
      { t: 'Correo de acceso', f: u => !u.correo_estado ? '<span class="small muted">—</span>'
        : `${u.correo_estado === 'enviado' ? est('ok', 'enviado') : est('error', 'fallido')} <span class="small muted">${esc(CORREO_TIPO[u.correo_tipo] || '')} · ${fechaHora(u.correo_fecha)}</span>
          ${u.correo_motivo ? `<div class="small" style="color:var(--red)">${esc(u.correo_motivo)}</div>` : ''}` },
      { t: '', f: u => `<div class="td-actions"><button class="btn btn-outline btn-sm" data-u="${esc(u.email)}">Editar</button>
        ${u.activo ? `<button class="btn btn-outline btn-sm" data-reenviar="${esc(u.email)}">Reenviar acceso</button>` : ''}</div>` },
    ], lista) + '</div>', '', true) +
    `<p class="small muted mt">«Reenviar acceso» manda un enlace nuevo: de bienvenida si la persona nunca entró, o para restablecer la contraseña si ya entró.
     Desactivar a alguien también bloquea su ingreso.</p>`;
  const editar = async (u = { activo: true, rol: 'lectura' }) => {
    const nuevo = !u.email;
    const r = await modal({ titulo: nuevo ? 'Nuevo usuario' : 'Editar usuario', cuerpo: `
      <div class="form-group"><label>Email</label><input type="email" id="u-e" value="${esc(u.email || '')}" ${nuevo ? '' : 'disabled'} placeholder="nombre@equipos.com.uy" /></div>
      <div class="form-group"><label>Nombre</label><input type="text" id="u-n" value="${esc(u.nombre || '')}" /></div>
      <div class="form-group"><label>Rol</label><select class="fselect" id="u-r">${ROLES.map(([k, t]) => `<option value="${k}" ${k === u.rol ? 'selected' : ''}>${t}</option>`).join('')}</select></div>
      <div><label class="check"><input type="checkbox" id="u-x" ${u.exportar_contactos ? 'checked' : ''} /> Puede exportar contactos personales (queda auditado)</label></div>
      <div class="mt"><label class="check"><input type="checkbox" id="u-a" ${u.activo ? 'checked' : ''} /> Activo (desactivarlo también bloquea su ingreso)</label></div>
      ${nuevo ? '<p class="field-hint mt">La persona recibe un correo para crear su contraseña. No hace falta crear nada en Firebase.</p>' : ''}`,
    acciones: [{ t: 'Cancelar' }, { t: nuevo ? 'Dar de alta' : 'Guardar', cls: 'btn-orange', fn: (b) => api.post('/usuarios', {
      email: $('#u-e', b).value.trim(), nombre: $('#u-n', b).value.trim() || null, rol: $('#u-r', b).value,
      exportar_contactos: $('#u-x', b).checked, activo: $('#u-a', b).checked }) }] });
    if (r) { await avisoResultado(r.email, r); usuarios(ctx); }
  };
  $('#u-nuevo').onclick = () => editar();
  $$('[data-u]').forEach(b => b.onclick = () => editar(lista.find(u => u.email === b.dataset.u)));
  $$('[data-reenviar]').forEach(b => b.onclick = async () => {
    if (!await confirmar('Reenviar acceso', `Se genera un enlace nuevo para <strong>${esc(b.dataset.reenviar)}</strong> y se le manda por correo. Vence en una hora.`, 'Reenviar')) return;
    b.disabled = true;
    try {
      const r = await api.post(`/usuarios/${encodeURIComponent(b.dataset.reenviar)}/reenviar-acceso`);
      await avisoResultado(b.dataset.reenviar, r);
      usuarios(ctx);
    } catch (e) { toast(e.message, 'err'); b.disabled = false; }
  });
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
