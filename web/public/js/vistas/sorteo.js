// Asistente de «Nueva muestra» y templates de sorteo (SPEC_templates_sorteo_sin_telefono_formatos_csv, R2–R4).
// Paso 1: filtros con cualquier dato de la empresa; paso 2: estratos (tramos, «Otros», año/semestre);
// paso 3: tamaño por estrato. Un template guarda los pasos 1 a 3 y se aplica con un clic.
import * as api from '../api.js';
import { $, $$, esc, main, toast, num, fechaHora, est, etiqueta, pageHeader, stats, tabla, card, modal, confirmar,
  chips, activarChips, chipsSel, conEspera, hayEspera } from '../ui.js';

// D56: métodos de sorteo
export const METODOS = { aleatorio: 'Aleatorio simple', sistematico_ciiu: 'Sistemático por CIIU' };
const MOTIVO = { sin_telefono_discable: 'sin teléfono discable', enfriamiento: 'enfriamiento', muestra_activa: 'en muestra activa',
  no_llamar: 'no llamar', naturaleza_excluida: 'naturaleza excluida', cerrada: 'empresa cerrada', baja: 'dada de baja',
  filtro_origen: 'sin teléfono del origen elegido' };
export const motivoTexto = (k) => MOTIVO[k] || etiqueta(k);

const MODOS_TEXTO = [['contiene', 'Contiene…'], ['valores', 'Es uno de…'], ['con', 'Tiene dato'], ['sin', 'No tiene dato']];
const SIN = '(sin dato)';

function nombreDato(datos, k) { return (datos[k] || {}).nombre || k; }

// Resumen legible de los criterios de una muestra o un template
export function criteriosTexto(c, datosLista, origenes) {
  const datos = Object.fromEntries((datosLista || []).map(d => [d.clave, d]));
  const nombreO = Object.fromEntries((origenes || []).map(o => [o.codigo, o.nombre]));
  const f = (s) => s.tiene_dato !== undefined ? (s.tiene_dato ? 'tiene dato' : 'sin dato')
    : [s.valores ? s.valores.join(', ') : '', s.contiene ? `contiene «${s.contiene}»` : '', s.desde ? 'desde ' + s.desde : '',
      s.hasta ? 'hasta ' + s.hasta : '', s.incluir_sin_dato ? '(o sin dato)' : ''].filter(Boolean).join(' ');
  const partes = Object.entries(c.filtros || {}).map(([k, v]) => `${k === 'ciiu' ? 'CIIU empieza con' : nombreDato(datos, k)}: ${[].concat(v).join(', ')}`);
  Object.entries(c.campos || {}).forEach(([k, s]) => partes.push(`${nombreDato(datos, k)}: ${f(s)}`));
  Object.entries(c.atributos || {}).forEach(([k, s]) => partes.push(`${nombreDato(datos, 'atributo.' + k)}: ${f(s)}`));
  if ((c.origenes || []).length) partes.push(`teléfonos de: ${c.origenes.map(o => nombreO[o] || o).join(', ')}`);
  if (c.incluir_provisoria) partes.push('incluye la base provisoria');
  if (c.incluir_sin_telefono) partes.push('incluía empresas sin teléfono (opción anterior a noviembre de 2026)');
  if (c.una_por_grupo) partes.push('una empresa por grupo económico');
  if (c.metodo && c.metodo !== 'aleatorio') partes.push(`sorteo ${(METODOS[c.metodo] || c.metodo).toLowerCase()}`);
  if ((c.estratificar_por || []).length) partes.push(`estratos: ${c.estratificar_por.map(k => {
    const d = (c.estratos_def || {})[k];
    const det = !d ? '' : d.cortes && !d.por ? ` (tramos ${d.cortes.join(', ')})` : d.por ? ` (${d.por === 'anio' ? 'por año' : d.por === 'semestre' ? 'por semestre' : 'tramos ' + d.cortes.join(', ')})`
      : d.agrupar === 'min' ? ` (Otros: menos de ${d.n})` : d.agrupar === 'top' ? ` (los ${d.n} más frecuentes)` : '';
    return nombreDato(datos, k) + det;
  }).join(' × ')}`);
  return partes.length ? partes.map(esc).join(' · ') : 'Sin filtros: toda la base disponible';
}

// Estado del asistente a partir de unos criterios (de un template o de una muestra)
function estadoDe(c = {}) {
  const st = { filtros: {}, legado: { ...(c.filtros || {}) }, origenes: [...(c.origenes || [])],
    incluir_provisoria: !!c.incluir_provisoria, metodo: c.metodo || 'aleatorio',
    // Fase 2 (Q3): una muestra nueva la trae marcada; un template o una muestra guardada, como estaba
    una_por_grupo: Object.keys(c).length ? !!c.una_por_grupo : true,
    por: [...(c.estratificar_por || [])], defs: JSON.parse(JSON.stringify(c.estratos_def || {})), tamanos: {},
    n_todos: c.n_por_estrato ?? '', r_todos: c.n_por_estrato != null ? (c.reemplazos_por_estrato || 0) : '',
    template_estratos: (c.estratos || []).map(e => e.estrato) };
  Object.entries(c.campos || {}).forEach(([k, s]) => { st.filtros[k] = { ...s }; });
  Object.entries(c.atributos || {}).forEach(([k, s]) => { st.filtros['atributo.' + k] = { ...s }; });
  (c.estratos || []).forEach(e => { st.tamanos[e.estrato] = { n: +e.n || 0, r: +e.reemplazos || 0 }; });
  (c.estratos_descartados || []).forEach(x => { if (!st.tamanos[x]) st.tamanos[x] = { n: 0, r: 0 }; });
  return st;
}

export async function asistente(ctx, { estudioId = null, templateId = null, params = new URLSearchParams() } = {}) {
  const editarTemplate = estudioId === null;
  const [e, ds, origenes, plantillas] = await Promise.all([
    editarTemplate ? null : api.get('/estudios/' + estudioId), api.get('/muestras/datos-sorteo'),
    api.get('/origenes-telefono', { activos: true }), ctx.puede('jefe') ? api.get('/muestra-templates', { activos: true }) : []]);
  const datos = Object.fromEntries(ds.datos.map(d => [d.clave, d]));
  const natNombre = Object.fromEntries(ds.naturalezas.map(n => [n.codigo, n.nombre]));
  const valoresCache = {};
  let st = estadoDe({}), template = null, avisosTemplate = [], marcoActual = null, marcoViejo = false;

  const titulo = editarTemplate ? 'Editar template' : 'Nueva muestra';
  main().innerHTML = pageHeader(titulo, editarTemplate ? '' : '— ' + e.nombre, editarTemplate
    ? 'Los pasos 1 a 3 del sorteo. Guardar el template no cambia las muestras que ya lo usaron.'
    : 'Definí filtros y estratos, mirá el marco disponible y después sorteá. El sorteo congela el marco y guarda la semilla y la versión de configuración.') +
    (!editarTemplate && plantillas.length ? `<div class="card mb"><div class="card-body"><div class="toolbar">
      <label class="td-strong" for="m-template">Partir de un template</label>
      <select class="fselect" id="m-template" style="max-width:420px"><option value="">— ninguno: empezar de cero —</option>${plantillas.map(t =>
        `<option value="${t.id}">${esc(t.nombre)}${t.descripcion ? ' — ' + esc(t.descripcion) : ''}</option>`).join('')}</select>
      <span class="small muted">Completa los pasos 1 a 3; todo se puede ajustar antes de sortear.</span></div></div></div>` : '') +
    `<div id="m-template-avisos"></div>` +
    `<div class="grid-2">${card('1 · Filtros', '<div id="m-paso1"></div>')}${card('2 · Estratos', '<div id="m-paso2"></div>')}</div><div id="m-estratos"></div>`;

  // ── Opciones agrupadas para «+ Agregar» (campos de la empresa y atributos) con buscador ──
  const selectorDatos = (id, usados, texto) => {
    const grupo = (g, t) => {
      const ops = ds.datos.filter(d => d.grupo === g && !usados.includes(d.clave));
      return ops.length ? `<optgroup label="${t}">${ops.map(d => `<option value="${esc(d.clave)}">${esc(d.nombre)}</option>`).join('')}</optgroup>` : '';
    };
    return `<div class="map-agregar gap"><input type="search" class="buscador-datos" data-para="${id}" placeholder="Buscar dato…" style="max-width:160px" />
      <select class="fselect" id="${id}"><option value="">${texto}</option>${grupo('campo', 'Campos de la empresa')}${grupo('atributo', 'Atributos')}</select></div>`;
  };
  const activarBuscadores = (el) => $$('.buscador-datos', el).forEach(b => b.oninput = () => {
    const q = b.value.trim().toLowerCase();
    $$(`#${b.dataset.para} option`, el).forEach(o => { if (o.value) o.hidden = q && !o.textContent.toLowerCase().includes(q); });
  });

  // ── Paso 1 ──
  const leerPaso1 = () => {
    Object.keys(st.filtros).forEach(k => {
      const d = datos[k]; const s = {}; const id = CSS.escape(k);
      if (!d) return;
      if (d.tipo === 'lista') { const v = chipsSel(main(), 'f:' + k); if (v.length) s.valores = v; }
      else if (d.tipo === 'texto') {
        const modo = $(`[data-modo="${id}"]`).value;
        if (modo === 'contiene') { const t = $(`[data-contiene="${id}"]`).value.trim(); if (t) s.contiene = t; }
        if (modo === 'valores') {
          // Mientras se cargan los valores no hay chips: se conserva lo elegido (por ejemplo, al aplicar un template)
          const v = $(`[data-chips="fv:${id}"]`) ? chipsSel(main(), 'fv:' + k) : (st.filtros[k].valores || []);
          if (v.length) s.valores = v; else s._modo = 'valores';
        }
        if (modo === 'con') s.tiene_dato = true;
        if (modo === 'sin') s.tiene_dato = false;
      } else {
        const a = $(`[data-desde="${id}"]`).value, b = $(`[data-hasta="${id}"]`).value;
        if (a) s.desde = a; if (b) s.hasta = b;
      }
      const sd = $(`[data-sindato="${id}"]`);
      if (sd && sd.checked && s.tiene_dato === undefined) s.incluir_sin_dato = true;
      st.filtros[k] = s;
    });
    st.origenes = chipsSel(main(), 'origenes');
    st.incluir_provisoria = $('#m-provisoria').checked;
    st.una_por_grupo = $('#m-grupo').checked;
  };
  const controlFiltro = (k, s) => {
    const d = datos[k]; const id = esc(k);
    if (!d) return `<span class="small muted">Dato que ya no existe</span>`;
    let ctrl = '';
    if (d.tipo === 'lista') ctrl = chips('f:' + k, (d.opciones || []).map(o => [o, k === 'naturaleza' ? (natNombre[o] || o) : o]), s.valores || []);
    else if (d.tipo === 'texto') {
      const modo = s.tiene_dato === true ? 'con' : s.tiene_dato === false ? 'sin' : s.valores || s._modo === 'valores' ? 'valores' : 'contiene';
      const vals = valoresCache[k];
      ctrl = `<select class="fselect" data-modo="${id}" style="width:auto">${MODOS_TEXTO.map(([v, t]) => `<option value="${v}" ${v === modo ? 'selected' : ''}>${t}</option>`).join('')}</select>
        ${modo === 'contiene' ? `<input type="text" data-contiene="${id}" value="${esc(s.contiene || '')}" placeholder="texto" />` : ''}
        ${modo === 'valores' ? (vals ? (vals.length ? chips('fv:' + k, vals.map(v => [v.valor, `${v.valor} (${num(v.empresas)})`]), s.valores || []) : '<span class="small muted">Ninguna empresa tiene este dato cargado.</span>')
          + (vals.length >= 200 ? '<div class="field-hint">Se muestran los 200 valores más frecuentes.</div>' : '') : '<span class="small muted">Cargando valores…</span>') : ''}`;
    } else {
      const t = d.tipo === 'fecha' ? 'date' : 'number';
      ctrl = `<div class="form-row"><input type="${t}" data-desde="${id}" value="${esc(s.desde || '')}" placeholder="desde" />
        <input type="${t}" data-hasta="${id}" value="${esc(s.hasta || '')}" placeholder="hasta" /></div>`;
    }
    const sinDato = s.tiene_dato === undefined ? `<label class="check small"><input type="checkbox" data-sindato="${id}" ${s.incluir_sin_dato ? 'checked' : ''} /> Incluir empresas sin dato</label>` : '';
    return `<div class="filtro-dato"><div class="filtro-cab"><span class="td-strong">${esc(d.nombre)}</span> <span class="small muted">${d.grupo === 'atributo' ? 'atributo · ' : ''}${esc(d.tipo)}</span>
      <button class="btn btn-outline btn-sm btn-del" data-quitar-f="${id}" title="Quitar">×</button></div>${ctrl}${sinDato}</div>`;
  };
  const pintarPaso1 = () => {
    const el = $('#m-paso1');
    const legado = Object.entries(st.legado).filter(([, v]) => v && [].concat(v).length);
    el.innerHTML = (legado.length ? `<div class="small mb">${legado.map(([k, v]) => `<span class="chip on">${esc(k === 'ciiu' ? 'CIIU empieza con' : nombreDato(datos, k))}: ${esc([].concat(v).join(', '))}
        <span data-quitar-legado="${esc(k)}" style="cursor:pointer">×</span></span>`).join(' ')}</div>` : '') +
      (Object.keys(st.filtros).map(k => controlFiltro(k, st.filtros[k])).join('') || '<p class="small muted">Sin filtros: entra toda la base disponible.</p>') +
      selectorDatos('m-add-filtro', Object.keys(st.filtros), '+ Agregar filtro…') +
      `<div class="field-hint">Los filtros se combinan con «y»: todos tienen que cumplirse. Sirve cualquier dato de la empresa; los atributos de contacto no.</div>
      <div class="form-group mt"><label>Origen de los teléfonos</label>${chips('origenes', origenes.map(o => [o.codigo, o.nombre]), st.origenes)}
        <div class="field-hint">Solo empresas con al menos un teléfono discable de estos orígenes. Sin selección, no filtra.</div></div>
      <label class="check mt"><input type="checkbox" id="m-provisoria" ${st.incluir_provisoria ? 'checked' : ''} /> Incluir la base provisoria (empresas sin RUT)</label>
      <div class="field-hint">${ds.regla_sin_telefono ? 'Las empresas sin teléfono discable aparecen en el marco como no sorteables y nunca se sortean.'
        : 'La regla «Excluir empresas sin teléfono discable» está apagada en Configuración: las empresas sin teléfono se pueden sortear.'}</div>
      <label class="check mt"><input type="checkbox" id="m-grupo" ${st.una_por_grupo ? 'checked' : ''} /> Como máximo una empresa por grupo económico</label>
      <div class="field-hint">Si sale sorteada una empresa de un grupo que ya tiene otra en la muestra, se saltea y sigue la siguiente del orden.</div>`;
    activarChips(el, () => {});
    activarBuscadores(el);
    $$('[data-quitar-f]', el).forEach(b => b.onclick = () => { leerPaso1(); delete st.filtros[b.dataset.quitarF]; pintarPaso1(); });
    $$('[data-quitar-legado]', el).forEach(b => b.onclick = () => { leerPaso1(); delete st.legado[b.dataset.quitarLegado]; pintarPaso1(); });
    $$('[data-modo]', el).forEach(sel => sel.onchange = async () => {
      leerPaso1();
      const k = Object.keys(st.filtros).find(x => x === sel.dataset.modo);
      st.filtros[k] = sel.value === 'valores' ? { _modo: 'valores' } : sel.value === 'con' ? { tiene_dato: true } : sel.value === 'sin' ? { tiene_dato: false } : {};
      pintarPaso1();
      if (sel.value === 'valores') cargarValores(k);
    });
    $('#m-add-filtro').onchange = (ev) => {
      leerPaso1(); const k = ev.target.value; st.filtros[k] = {}; pintarPaso1();
    };
    Object.entries(st.filtros).forEach(([k, s]) => { if ((s.valores || s._modo === 'valores') && datos[k] && datos[k].tipo === 'texto' && !valoresCache[k]) cargarValores(k); });
  };
  const cargarValores = async (k) => {
    valoresCache[k] = await api.get('/muestras/valores-dato', { dato: k });
    leerPaso1(); pintarPaso1();
  };

  // ── Paso 2 ──
  const leerPaso2 = () => {
    st.por.forEach(k => {
      const d = datos[k]; const id = CSS.escape(k);
      if (!d) return;
      if (d.tipo === 'numero') st.defs[k] = { cortes: $(`[data-cortes="${id}"]`).value.split(/[;,\s]+/).filter(Boolean) };
      else if (d.tipo === 'fecha') {
        const por = $(`[data-porfecha="${id}"]`).value;
        st.defs[k] = por === 'tramos' ? { por, cortes: ($(`[data-cortes="${id}"]`) || { value: '' }).value.split(/[;,\s]+/).filter(Boolean) } : { por };
      } else if (d.tipo === 'texto') {
        const ag = $(`[data-agrupar="${id}"]`).value;
        if (ag) st.defs[k] = { agrupar: ag, n: +$(`[data-agrupar-n="${id}"]`).value || 5 }; else delete st.defs[k];
      }
    });
  };
  const controlEstrato = (k) => {
    const d = datos[k]; const id = esc(k); const r = st.defs[k] || {};
    if (!d) return `<div class="filtro-dato"><span class="small muted">${esc(k)}: dato que ya no existe</span></div>`;
    let ctrl = '<div class="small muted">Un estrato por opción.</div>';
    if (d.tipo === 'numero') ctrl = `<div class="gap"><input type="text" data-cortes="${id}" value="${esc((r.cortes || []).join(', '))}" placeholder="tramos, p. ej. 1, 5, 20, 100" />
      <button class="btn btn-outline btn-sm" data-sugerir="${id}" data-forma="cuartiles">Cuartiles</button><button class="btn btn-outline btn-sm" data-sugerir="${id}" data-forma="iguales">Tramos iguales</button></div>
      <div class="field-hint">Cada número es el comienzo de un tramo: 1, 5, 20, 100 da 1–4, 5–19, 20–99 y 100 o más.</div>`;
    if (d.tipo === 'fecha') ctrl = `<select class="fselect" data-porfecha="${id}" style="width:auto">${[['anio', 'Por año'], ['semestre', 'Por semestre'], ['tramos', 'Por tramos']].map(([v, t]) =>
      `<option value="${v}" ${(r.por || 'anio') === v ? 'selected' : ''}>${t}</option>`).join('')}</select>
      ${r.por === 'tramos' ? `<input type="text" data-cortes="${id}" value="${esc((r.cortes || []).join(', '))}" placeholder="2010-01-01, 2020-01-01" />` : ''}`;
    if (d.tipo === 'texto') ctrl = `<div class="gap"><select class="fselect" data-agrupar="${id}" style="width:auto">
      <option value="" ${!r.agrupar ? 'selected' : ''}>Un estrato por valor (sin mayúsculas ni tildes)</option>
      <option value="min" ${r.agrupar === 'min' ? 'selected' : ''}>Agrupar en «Otros» los de menos de N empresas</option>
      <option value="top" ${r.agrupar === 'top' ? 'selected' : ''}>Los N más frecuentes y el resto en «Otros»</option></select>
      <input type="number" min="1" data-agrupar-n="${id}" value="${r.n || 5}" style="width:80px" ${r.agrupar ? '' : 'hidden'} /></div>`;
    return `<div class="filtro-dato"><div class="filtro-cab"><span class="td-strong">${esc(d.nombre)}</span> <span class="small muted">${d.grupo === 'atributo' ? 'atributo · ' : ''}${esc(d.tipo)}</span>
      <button class="btn btn-outline btn-sm btn-del" data-quitar-e="${id}" title="Quitar">×</button></div>${ctrl}</div>`;
  };
  const pintarPaso2 = () => {
    const el = $('#m-paso2');
    el.innerHTML = (st.por.map(controlEstrato).join(' <div class="small muted" style="text-align:center">×</div> ') || '<p class="small muted">Sin estratos: un único estrato «Total».</p>') +
      selectorDatos('m-add-estrato', st.por, '+ Agregar estrato…') +
      `<div class="field-hint">Las empresas sin dato van al estrato «(sin dato)». Se pueden combinar varios datos.</div>
      <button class="btn btn-dark mt" id="m-marco">Ver marco disponible</button><div id="m-marco-res" class="mt"></div>`;
    activarBuscadores(el);
    $$('[data-quitar-e]', el).forEach(b => b.onclick = () => { leerPaso2(); st.por = st.por.filter(x => x !== b.dataset.quitarE); delete st.defs[b.dataset.quitarE]; pintarPaso2(); });
    $$('[data-agrupar], [data-porfecha]', el).forEach(s => s.onchange = () => { leerPaso2(); pintarPaso2(); });
    $$('[data-sugerir]', el).forEach(b => b.onclick = async () => {
      leerPaso1(); leerPaso2();
      const t = await api.post('/muestras/tramos', { dato: b.dataset.sugerir, criterios: criterios(false) });
      if (!t.n) return toast('No hay empresas con ese dato en el marco', 'err');
      st.defs[b.dataset.sugerir] = { cortes: t[b.dataset.forma] };
      pintarPaso2(); toast(`De ${num(t.n)} empresas: mínimo ${t.min}, máximo ${t.max}`, 'ok');
    });
    $('#m-add-estrato').onchange = (ev) => { leerPaso2(); st.por.push(ev.target.value); pintarPaso2(); };
    $('#m-marco').onclick = verMarco;
  };

  // ── Criterios y paso 3 ──
  const criterios = (conTamanos) => {
    const c = { filtros: st.legado, campos: {}, atributos: {}, origenes: st.origenes, estratificar_por: st.por, estratos_def: {} };
    Object.entries(st.filtros).forEach(([k, s]) => {
      const limpio = Object.fromEntries(Object.entries(s).filter(([x]) => !x.startsWith('_')));
      if (!Object.keys(limpio).filter(x => x !== 'incluir_sin_dato').length) return;
      if (k.startsWith('atributo.')) c.atributos[k.slice(9)] = limpio; else c.campos[k] = limpio;
    });
    st.por.forEach(k => { if (st.defs[k]) c.estratos_def[k] = st.defs[k]; });
    if (st.incluir_provisoria) c.incluir_provisoria = true;
    if (st.una_por_grupo) c.una_por_grupo = true;
    if ($('#m-metodo')) st.metodo = $('#m-metodo').value;
    if (st.metodo && st.metodo !== 'aleatorio') c.metodo = st.metodo;
    if (conTamanos) {
      const filas = $$('[data-n]').map(i => ({ estrato: i.dataset.n, n: +i.value || 0, reemplazos: +($(`[data-r="${CSS.escape(i.dataset.n)}"]`).value) || 0 }));
      c.estratos = filas.filter(x => x.n || x.reemplazos);
      c.estratos_descartados = filas.filter(x => !x.n && !x.reemplazos).map(x => x.estrato);
    }
    return c;
  };
  async function verMarco() {
    if (hayEspera()) return;
    leerPaso1(); leerPaso2();
    const r = await conEspera($('#m-marco'), 'Recuperando el marco disponible…', () => api.post('/muestras/marco', criterios(false)));
    if (r) mostrarMarco(r);
  }
  // R1: si cambia un filtro o un estrato, el marco que se ve queda marcado como desactualizado (no se recalcula solo)
  const marcarViejo = () => {
    if (!marcoActual || marcoViejo) return;
    marcoViejo = true;
    const res = $('#m-marco-res');
    if (res) res.insertAdjacentHTML('afterbegin', '<div class="alert alert-warn mb" id="m-marco-viejo"><span><strong>Cambiaste filtros o estratos.</strong> Volvé a consultar el marco: los números de abajo son los de antes.</span></div>');
    $$('#m-marco-res .stats, #m-estratos .card').forEach(x => x.classList.add('desactualizado'));
  };
  ['m-paso1', 'm-paso2'].forEach(id => {
    const el = $('#' + id);
    el.addEventListener('change', (ev) => { if (!ev.target.closest('#m-marco-res')) marcarViejo(); });
    el.addEventListener('input', (ev) => { if (ev.target.matches('input[type=text], input[type=number], input[type=date]')) marcarViejo(); });
    el.addEventListener('click', (ev) => { if (ev.target.closest('.chip, [data-quitar-f], [data-quitar-e], [data-quitar-legado]')) marcarViejo(); });
  });
  function mostrarMarco(r) {
    marcoActual = r; marcoViejo = false;
    const ex = Object.entries(r.exclusiones).filter(([k]) => k !== 'total_excluidas');
    $('#m-marco-res').innerHTML = stats([[r.universo, 'Cumplen filtros', 's-total'], [r.marco, 'Sorteables', 's-ok'],
      [r.universo - r.marco, 'No sorteables', 's-bad']]) +
      (ex.length ? `<div class="small"><strong>No sorteables por motivo</strong> (una empresa puede tener varios): ${ex.map(([k, n]) => `${esc(motivoTexto(k))} <strong>${num(n)}</strong>`).join(' · ')}
        · <a class="link" href="javascript:void 0" id="m-no-sorteables">Descargar no sorteables</a></div>` : '') +
      (r.avisos || []).map(a => `<div class="alert alert-warn mt"><span>${esc(a)}</span></div>`).join('');
    if ($('#m-no-sorteables')) $('#m-no-sorteables').onclick = (ev) => {
      leerPaso1(); leerPaso2();
      return conEspera(ev.target, 'Preparando la lista de no sorteables…',
        () => api.descargar('/muestras/marco/no-sorteables.csv', null, criterios(false)));
    };
    pintarPaso3(r);
  }
  const pintarPaso3 = (r) => {
    const enMarco = new Set(r.estratos.map(x => x.estrato));
    const delTemplate = new Set(st.template_estratos);
    const filas = [...r.estratos.map(x => ({ ...x, nuevo: template && delTemplate.size && !delTemplate.has(x.estrato) && !(x.estrato in st.tamanos) })),
      ...[...delTemplate].filter(x => !enMarco.has(x)).map(x => ({ estrato: x, total: 0, sorteables: 0, no_sorteables: 0, disponibles: 0, sin_empresas: true }))];
    const motivos = (x) => Object.entries(x.motivos || {}).map(([k, n]) => `${motivoTexto(k)}: ${num(n)}`).join(' · ');
    const val = (x, k) => (st.tamanos[x.estrato] || {})[k] ?? (k === 'n' ? (st.n_todos === '' ? 0 : st.n_todos) : (st.r_todos === '' ? 0 : st.r_todos));
    $('#m-estratos').innerHTML = card('3 · Tamaño por estrato y reemplazos', `
      <div class="form-row mb"><div class="form-group"><label for="m-metodo">Método de sorteo</label>
        <select class="fselect" id="m-metodo">${Object.entries(METODOS).map(([k, t]) => `<option value="${k}" ${st.metodo === k ? 'selected' : ''}>${t}</option>`).join('')}</select>
        <div class="field-hint" id="m-metodo-ayuda"></div></div>
        <div class="form-group"><label>Tamaños desde una planilla</label><div class="gap">
          <button class="btn btn-outline btn-sm" id="m-excel-bajar">Descargar Excel</button>
          <button class="btn btn-outline btn-sm" id="m-excel-subir">Importar Excel</button><input type="file" id="m-excel-archivo" accept=".xlsx" hidden /></div>
          <div class="field-hint">Completá Titulares y Reemplazos en el Excel y volvé a subirlo: los valores se cargan en la tabla y se guardan con el botón de abajo.</div></div></div>
      <div id="m-excel-res"></div>
      <div class="toolbar mb"><span class="small muted">Aplicar a todos:</span><input type="number" id="m-n-todos" placeholder="n" style="width:90px" value="${esc(st.n_todos)}" />
        <input type="number" id="m-r-todos" placeholder="reemplazos" style="width:120px" value="${esc(st.r_todos)}" /><button class="btn btn-outline btn-sm" id="m-aplicar">Aplicar</button></div>
      ${tabla([{ t: 'Estrato', f: x => `<span class="td-strong">${esc(x.estrato)}</span>${x.sin_empresas ? ` ${est('sospechoso', 'estrato del template sin empresas en el marco')}` : ''}${x.nuevo ? ` ${est('preview', 'nuevo')}` : ''}` },
        { t: 'Total', cls: 'num', f: x => num(x.total ?? x.disponibles) },
        { t: 'Sorteables', cls: 'num', f: x => `<strong>${num(x.sorteables ?? x.disponibles)}</strong>` },
        { t: 'No sorteables', cls: 'num', f: x => x.no_sorteables ? `<details class="motivos"><summary title="${esc(motivos(x))}">${num(x.no_sorteables)}</summary><div class="small muted">${esc(motivos(x))}</div></details>` : '0' },
        { t: 'Titulares', f: x => `<input type="number" min="0" data-n="${esc(x.estrato)}" value="${x.nuevo ? 0 : val(x, 'n')}" style="width:100px" />` },
        { t: 'Reemplazos', f: x => `<input type="number" min="0" data-r="${esc(x.estrato)}" value="${x.nuevo ? 0 : val(x, 'r')}" style="width:100px" />` },
        { t: '', f: x => `<span class="small" data-alcanza="${esc(x.estrato)}" data-sorteables="${x.sorteables ?? x.disponibles ?? 0}"></span>` }],
      filas, 'No hay empresas con esos filtros')}
      ${editarTemplate ? `<div class="mt gap"><button class="btn btn-orange" id="m-guardar-t">Guardar template</button></div>` : `
      <div class="form-row mt"><div class="form-group"><label>Nombre de la muestra</label><input type="text" id="m-nombre" value="Muestra ${e.muestras.length + 1}" /></div>
      <div class="form-group"><label>Semilla (opcional)</label><input type="number" id="m-semilla" placeholder="se genera al azar" />
      <div class="field-hint">Con la misma semilla y el mismo marco, el sorteo da la misma lista.</div></div></div>
      <div class="gap"><button class="btn btn-orange" id="m-sortear">Crear y sortear</button>
      ${ctx.puede('jefe') ? `<button class="btn btn-outline" id="m-guardar-t">Guardar como template…</button>` : ''}</div>`}`);
    // «Faltan N» al lado de cada estrato: los tamaños pedidos se comparan contra las sorteables
    const alcanza = () => $$('[data-alcanza]').forEach(s => {
      const e = s.dataset.alcanza;
      const pedido = (+$(`[data-n="${CSS.escape(e)}"]`).value || 0) + (+$(`[data-r="${CSS.escape(e)}"]`).value || 0);
      const falta = pedido - (+s.dataset.sorteables);
      s.innerHTML = falta > 0 ? est('sospechoso', `faltan ${num(falta)}`) : '';
    });
    $$('[data-n], [data-r]').forEach(i => { i.oninput = alcanza; });
    alcanza();
    const ayuda = { aleatorio: 'Cada empresa sorteable del estrato tiene la misma chance; el orden lo da la semilla.',
      sistematico_ciiu: 'Ordena el estrato por CIIU y toma una cada N/n empresas: la muestra recorre todas las actividades. El reemplazo de cada titular es su vecino en la lista.' };
    const pintarAyuda = () => { $('#m-metodo-ayuda').textContent = ayuda[$('#m-metodo').value] || ''; };
    $('#m-metodo').onchange = () => { st.metodo = $('#m-metodo').value; pintarAyuda(); };
    pintarAyuda();
    $('#m-aplicar').onclick = () => {
      st.n_todos = $('#m-n-todos').value; st.r_todos = $('#m-r-todos').value;
      $$('[data-n]').forEach(i => { if (st.n_todos !== '') i.value = st.n_todos; });
      $$('[data-r]').forEach(i => { if (st.r_todos !== '') i.value = st.r_todos; });
      alcanza();
    };
    // R2: Excel de tamaños
    $('#m-excel-bajar').onclick = (ev) => {
      if (marcoViejo) return toast('Volvé a consultar el marco antes de descargar el Excel', 'err');
      leerPaso1(); leerPaso2();
      return conEspera(ev.target, 'Armando el Excel…', () => api.descargar('/muestras/marco/tamanos.xlsx', null, {
        criterios: criterios(true), estudio_id: editarTemplate ? null : +estudioId,
        nombre: editarTemplate ? (template ? template.nombre : null) : ($('#m-nombre') ? $('#m-nombre').value : null) }));
    };
    $('#m-excel-subir').onclick = () => $('#m-excel-archivo').click();
    $('#m-excel-archivo').onchange = async (ev) => {
      const archivo = ev.target.files[0];
      ev.target.value = '';
      if (!archivo) return;
      leerPaso1(); leerPaso2();
      const res = await conEspera($('#m-excel-subir'), 'Leyendo el Excel…',
        () => api.upload('/muestras/tamanos/importar', archivo, { criterios: JSON.stringify(criterios(false)) }));
      if (!res) return;
      res.tamanos.forEach(x => {
        const n = $(`[data-n="${CSS.escape(x.estrato)}"]`), r = $(`[data-r="${CSS.escape(x.estrato)}"]`);
        if (n) n.value = x.n;
        if (r) r.value = x.reemplazos;
        st.tamanos[x.estrato] = { n: x.n, r: x.reemplazos };
      });
      alcanza();
      const lista = (t, xs, cls) => xs.length ? `<details class="mt"><summary>${t} (${xs.length})</summary><ul class="aviso-lista">${xs.map(a => `<li>${esc(a)}</li>`).join('')}</ul></details>` : '';
      $('#m-excel-res').innerHTML = `<div class="alert ${res.errores.length ? 'alert-warn' : 'alert-success'} mb"><div>
        <strong>Se importaron ${num(res.importados)} estratos · ${num(res.avisos.length)} avisos · ${num(res.errores.length)} errores.</strong>
        Revisá la tabla y guardá: todavía no se guardó nada.${lista('Errores (esas filas no se importaron)', res.errores)}${lista('Avisos', res.avisos)}</div></div>`;
    };
    if ($('#m-sortear')) $('#m-sortear').onclick = sortear;
    if ($('#m-guardar-t')) $('#m-guardar-t').onclick = guardarTemplate;
  };
  async function sortear() {
    if (hayEspera()) return;
    if (marcoViejo) return toast('Cambiaste filtros o estratos: volvé a consultar el marco antes de sortear', 'err');
    leerPaso1(); leerPaso2();
    const c = criterios(true);
    if (!c.estratos.length) return toast('Indicá el tamaño de al menos un estrato', 'err');
    const total = c.estratos.reduce((a, x) => a + x.n, 0);
    if (!await confirmar('Sortear muestra', `Se sortean ${num(total)} titulares y ${num(c.estratos.reduce((a, x) => a + x.reemplazos, 0))} reemplazos en ${c.estratos.length} estratos, con el método ${(METODOS[st.metodo] || '').toLowerCase()}. Las empresas sorteadas quedan bloqueadas para otras muestras mientras esta esté activa.`, 'Sortear')) return;
    const semilla = $('#m-semilla').value;
    let creada = null;
    const ok = await conEspera($('#m-sortear'), 'Sorteando…', async () => {
      creada = creada || await api.post('/muestras', { estudio_id: +estudioId, nombre: $('#m-nombre').value, criterios: c, template_id: template ? template.id : null });
      await api.post(`/muestras/${creada.id}/sortear`, { semilla: semilla ? +semilla : null });
      return true;
    });
    if (!ok) { if (creada) ctx.ir('muestras/' + creada.id); return; }   // quedó en borrador: se ve en su detalle
    toast('Muestra sorteada', 'ok');
    ctx.ir('muestras/' + creada.id);
  }
  async function guardarTemplate() {
    leerPaso1(); leerPaso2();
    const c = criterios(true);
    if (editarTemplate) {
      await api.put('/muestra-templates/' + template.id, { criterios: c });
      toast(`Template «${template.nombre}» guardado`, 'ok'); return ctx.ir('templates');
    }
    const r = await modal({ titulo: 'Guardar como template', ancho: 560, cuerpo: `
      <div class="form-group"><label>Nombre</label><input type="text" id="t-nombre" value="${template ? esc(template.nombre) : ''}" /></div>
      <div class="form-group"><label>Descripción</label><input type="text" id="t-desc" value="${template ? esc(template.descripcion || '') : ''}" placeholder="p. ej. clima laboral, olas trimestrales" /></div>
      <p class="small muted">Guarda los pasos 1 a 3 (filtros, estratos y tamaños). No guarda la semilla, el nombre de la muestra ni las opciones de exportación.</p>`,
      acciones: [{ t: 'Cancelar' }, ...(template ? [{ t: `Actualizar template «${template.nombre}»`, fn: () => api.put('/muestra-templates/' + template.id, { criterios: c }) }] : []),
        { t: 'Guardar como nuevo', cls: 'btn-orange', fn: (b) => api.post('/muestra-templates', { nombre: $('#t-nombre', b).value, descripcion: $('#t-desc', b).value, criterios: c }) }] });
    if (r) toast('Template guardado', 'ok');
  }

  const aplicarTemplate = async (id) => {
    const ap = await conEspera($('#m-template'), 'Aplicando el template…', () => api.post(`/muestra-templates/${id}/aplicar`));
    if (!ap) return;
    template = ap.template;
    st = estadoDe(ap.criterios);
    avisosTemplate = ap.avisos;
    $('#m-template-avisos').innerHTML = avisosTemplate.length
      ? `<div class="alert alert-warn mb"><div><strong>El template usa cosas que ya no existen:</strong><ul class="aviso-lista">${avisosTemplate.map(a => `<li>${esc(a)}</li>`).join('')}</ul></div></div>` : '';
    pintarPaso1(); pintarPaso2(); mostrarMarco(ap.marco);
  };
  pintarPaso1(); pintarPaso2();
  if ($('#m-template')) $('#m-template').onchange = async (ev) => {
    if (ev.target.value) await aplicarTemplate(ev.target.value);
    else { template = null; st = estadoDe({}); $('#m-template-avisos').innerHTML = ''; $('#m-estratos').innerHTML = ''; pintarPaso1(); pintarPaso2(); }
  };
  const inicial = templateId || params.get('template');
  if (inicial) {
    if ($('#m-template')) $('#m-template').value = inicial;
    await aplicarTemplate(inicial);
    if (editarTemplate && $('.page-header p')) $('.page-header p').textContent = `«${template.nombre}»: los pasos 1 a 3 del sorteo. Guardar el template no cambia las muestras que ya lo usaron.`;
  }
}

// ── Templates de sorteo (jefe y administrador) ──
export async function lista(ctx) {
  const [ts, ds, origenes] = await Promise.all([api.get('/muestra-templates'), api.get('/muestras/datos-sorteo'), api.get('/origenes-telefono')]);
  main().innerHTML = pageHeader('Templates', 'de sorteo', 'Filtros, estratos y tamaños guardados para reusar en la próxima ola o en otro estudio. Las muestras guardan su propia copia: editar un template no cambia las muestras que ya lo usaron.') +
    card(`${num(ts.length)} templates`, tabla([
      { t: 'Template', f: t => `<span class="td-strong">${esc(t.nombre)}</span>${t.activo ? '' : ` ${est('pendiente', 'inactivo')}`}<div class="small muted">${esc(t.descripcion || '')}</div>` },
      { t: 'Filtros y estratos', f: t => `<div class="small">${criteriosTexto(t.criterios, ds.datos, origenes)}</div>` },
      { t: 'Tamaño', f: t => esc(t.resumen.tamano) },
      { t: 'Usado', cls: 'num', f: t => num(t.veces_usado) },
      { t: 'Última muestra', f: t => t.ultima_muestra_id ? `<a class="link" href="#/muestras/${t.ultima_muestra_id}">${esc(t.ultima_muestra)}</a><div class="small muted">${esc(t.ultima_muestra_estudio)}</div>` : '—' },
      { t: 'Actualizado', f: t => `<span class="small">${fechaHora(t.actualizado || t.creado)}<div class="muted">${esc(t.actualizado_por || t.creado_por)}</div></span>` },
      { t: '', f: t => `<div class="td-actions"><a class="btn btn-outline btn-sm" href="#/templates/${t.id}">Editar</a>
        <button class="btn btn-outline btn-sm" data-dup="${t.id}">Duplicar</button>
        <button class="btn btn-outline btn-sm" data-act="${t.id}" data-v="${t.activo ? '0' : '1'}">${t.activo ? 'Desactivar' : 'Activar'}</button>
        ${t.veces_usado ? '' : `<button class="btn btn-outline btn-sm btn-del" data-del="${t.id}">Borrar</button>`}</div>` },
    ], ts, 'Todavía no hay templates. Se crean desde el paso 3 de «Nueva muestra» o desde el detalle de una muestra.'), '', true);
  $$('[data-dup]').forEach(b => b.onclick = async () => { await api.post(`/muestra-templates/${b.dataset.dup}/duplicar`); toast('Template duplicado', 'ok'); lista(ctx); });
  $$('[data-act]').forEach(b => b.onclick = async () => { await api.put(`/muestra-templates/${b.dataset.act}`, { activo: b.dataset.v === '1' }); lista(ctx); });
  $$('[data-del]').forEach(b => b.onclick = async () => {
    if (!await confirmar('Borrar template', 'El template nunca se usó: se borra.', 'Borrar', 'btn-danger')) return;
    try { await api.del('/muestra-templates/' + b.dataset.del); toast('Template borrado', 'ok'); } catch (e) { toast(e.message, 'err'); }
    lista(ctx);
  });
}

export const editar = (ctx, id) => asistente(ctx, { templateId: id });
