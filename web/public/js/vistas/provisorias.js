// Base provisoria: empresas sin RUT (SPEC_mejoras_sav_contactos, F6.1). Pantalla, «Agregar RUT»,
// «Fusionar con…», «Es otra empresa» y completar el RUT con un archivo codigo_provisorio;rut.
import * as api from '../api.js';
import { $, $$, esc, main, toast, num, rutFmt, est, pageHeader, tabla, card, modal, pedirTexto, confirmar,
  archivoDrop, activarDrop } from '../ui.js';

const pct = (s) => `${Math.round((s || 0) * 100)} %`;
const CRITERIO = { telefono: 'mismo teléfono', razon_social: 'razón social parecida', direccion: 'dirección parecida',
  dominio_web: 'mismo dominio web', 'rut del .sav': 'RUT que trajo el .sav' };

// «Agregar RUT»: si el RUT es nuevo pasa a la definitiva; si ya existe, ofrece fusionar (reversible)
export async function agregarRut(emp, alTerminar) {
  const rut = await pedirTexto(`Agregar RUT — ${emp.razon_social || emp.codigo}`, 'RUT', { placeholder: '21 000000 001 X' });
  if (!rut) return;
  try {
    await api.post(`/empresas/${emp.codigo}/rut`, { rut });
    toast('La empresa pasó a la base definitiva', 'ok');
    alTerminar(rut.replace(/\D/g, ''));
  } catch (e) {
    if (e.status !== 409 || !e.datos || !e.datos.existente) return toast(e.message, 'err');
    if (!await confirmar('Ese RUT ya existe', `${e.message} ¿Fusionar ${emp.codigo} dentro de ${rutFmt(e.datos.existente)}? Sus teléfonos, contactos, atributos e historia pasan a esa empresa; sus ítems de muestra y llamadas se ven desde ella. La fusión se puede deshacer.`, 'Fusionar', 'btn-orange')) return;
    await fusionar(emp, e.datos.existente, alTerminar);
  }
}

export async function fusionar(emp, destino, alTerminar) {
  await api.post(`/empresas/${destino}/fusionar`, { rut_absorbida: emp.codigo, motivo: `${emp.codigo} es la misma empresa` });
  toast(`${emp.codigo} se fusionó en ${rutFmt(destino)}`, 'ok');
  alTerminar(destino);
}

// «Fusionar con…»: elegir entre las candidatas o buscar la empresa de la definitiva
export async function fusionarCon(emp, candidatas, alTerminar) {
  const r = await modal({ titulo: `Fusionar ${emp.codigo} con…`, ancho: 640, cuerpo: `
    ${candidatas.length ? `<div class="form-group"><label>Candidatas en la base definitiva</label>${candidatas.map((c, i) => `<label class="check">
      <input type="radio" name="fu-c" value="${esc(c.codigo)}" ${i === 0 ? 'checked' : ''} /> <span class="mono">${rutFmt(c.codigo)}</span>
      ${esc(c.razon_social || '—')} <span class="small muted">(${esc(CRITERIO[c.criterio] || c.criterio)}, ${pct(c.similitud)})</span></label>`).join('')}</div>` : ''}
    <div class="form-group"><label>${candidatas.length ? 'U otra empresa (RUT o razón social)' : 'Empresa de la definitiva (RUT o razón social)'}</label>
      <input type="search" id="fu-q" placeholder="Buscar…" /><div id="fu-res" class="mt"></div></div>`,
    acciones: [{ t: 'Cancelar' }, { t: 'Fusionar', cls: 'btn-orange', fn: (b) => {
      const sel = $('input[name="fu-c"]:checked', b);
      if (!sel) { toast('Elegí la empresa', 'err'); return false; }
      return sel.value;
    } }] });
  // la búsqueda agrega opciones al grupo de radios
  if (r) await fusionar(emp, r, alTerminar);
}

function activarBusquedaFusion() {
  const q = $('#fu-q');
  if (!q) return;
  q.addEventListener('keydown', async (e) => {
    if (e.key !== 'Enter') return;
    const r = await api.get('/empresas', { q: q.value, base: 'definitiva' });
    $('#fu-res').innerHTML = r.empresas.slice(0, 8).map(x => `<label class="check"><input type="radio" name="fu-c" value="${esc(x.rut)}" />
      <span class="mono">${rutFmt(x.rut)}</span> ${esc(x.razon_social || '—')} <span class="small muted">${esc(x.departamento || '')}</span></label>`).join('')
      || '<div class="small muted">Sin resultados</div>';
  });
}

export async function lista(ctx, params) {
  const q = params.get('q') || '';
  const soloCand = params.get('candidatas') === '1';
  const r = await api.get('/provisorias', { q, con_candidatas: soloCand || '' });
  const edita = ctx.puede('steward');
  main().innerHTML = pageHeader('Base', 'provisoria', 'Empresas que no traen RUT. Se cargan, se consultan y se depuran por separado; se pueden sortear y llamar. Pasan a la base definitiva al agregarles el RUT o al fusionarlas con una empresa que lo tiene.') +
    `<div class="card mb"><div class="card-body"><div class="toolbar">
      <input type="search" class="grow" id="pv-q" placeholder="Razón social o código P-…" value="${esc(q)}" />
      <label class="check"><input type="checkbox" id="pv-cand" ${soloCand ? 'checked' : ''} /> Solo con candidatas en la definitiva</label>
      <button class="btn btn-dark btn-sm" id="pv-buscar">Buscar</button></div></div></div>` +
    card(`${num(r.total)} empresas provisorias`, tabla([
      { t: 'Código', f: e => `<a class="link mono" href="#/empresas/${e.codigo}">${esc(e.codigo)}</a>${e.id_informado ? `<div class="small muted" title="Identificador que traía la fila">id informado: ${esc(e.id_informado)}</div>` : ''}` },
      { t: 'Razón social', f: e => `<span class="td-strong">${esc(e.razon_social || '—')}</span><div class="small muted">${esc(e.departamento || '')}</div>` },
      { t: 'Teléfonos', cls: 'num', f: e => `${num(e.n_discables)}<span class="small muted"> / ${num(e.n_telefonos)}</span>` },
      { t: 'Carga', f: e => e.carga_alta_id ? `<a class="link" href="#/cargas/${e.carga_alta_id}">#${e.carga_alta_id}</a> <span class="small muted">${esc(e.carga_fuente || '')}</span>` : '—' },
      { t: 'Muestras', cls: 'num', f: e => num(e.n_muestras) },
      { t: 'Candidatas en la definitiva', f: e => (e.candidatas || []).map(c => `<div class="small"><a class="link mono" href="#/empresas/${c.codigo}">${rutFmt(c.codigo)}</a>
        ${esc(c.razon_social || '')} <span class="muted">· ${esc(CRITERIO[c.criterio] || c.criterio)} · ${pct(c.similitud)}</span></div>`).join('')
        + ((e.ruts_propuestos || []).length ? `<div class="small">${est('sospechoso', 'el .sav propone')} ${e.ruts_propuestos.map(p => `<span class="mono">${rutFmt(p.rut)}</span>`).join(', ')}</div>` : '')
        || '<span class="muted">—</span>' },
      { t: '', f: e => edita ? `<div class="td-actions"><button class="btn btn-orange btn-sm" data-pv-rut="${e.id}">Agregar RUT</button>
        <button class="btn btn-outline btn-sm" data-pv-fus="${e.id}">Fusionar con…</button>
        ${(e.candidatas || []).length ? `<button class="btn btn-outline btn-sm btn-del" data-pv-otra="${e.id}">Es otra empresa</button>` : ''}</div>` : '' },
    ], r.empresas, 'No hay empresas en la base provisoria'), '', true) +
    (edita ? card('Completar RUT con un archivo', `<p class="small muted mb">Un CSV o Excel con las columnas <span class="mono">codigo_provisorio</span> y <span class="mono">rut</span>.
      Primero se muestra qué pasaría: las de RUT nuevo pasan a la definitiva; las de un RUT que ya existe se fusionan solo si lo confirmás.</p>
      <div class="form-row"><div>${archivoDrop('pv-arch', 'Arrastrá el archivo o tocá para elegirlo', '.csv,.xlsx,.xls')}</div>
      <div><button class="btn btn-orange" id="pv-analizar" disabled>Ver qué pasaría</button></div></div><div id="pv-prev" class="mt"></div>`) : '');
  const ir = () => ctx.ir(`provisorias?q=${encodeURIComponent($('#pv-q').value.trim())}${$('#pv-cand').checked ? '&candidatas=1' : ''}`);
  $('#pv-buscar').onclick = ir;
  $('#pv-q').addEventListener('keydown', e => { if (e.key === 'Enter') ir(); });
  $('#pv-cand').onchange = ir;
  const recargar = () => lista(ctx, params);
  const de = (id) => r.empresas.find(e => e.id === +id);
  $$('[data-pv-rut]').forEach(b => b.onclick = () => agregarRut(de(b.dataset.pvRut), recargar));
  $$('[data-pv-fus]').forEach(b => b.onclick = () => { const e = de(b.dataset.pvFus); fusionarCon(e, e.candidatas || [], recargar); setTimeout(activarBusquedaFusion, 50); });
  $$('[data-pv-otra]').forEach(b => b.onclick = async () => {
    const e = de(b.dataset.pvOtra);
    if (!await confirmar('Es otra empresa', `Las ${e.candidatas.length} candidatas de ${e.codigo} no se vuelven a proponer.`, 'Descartar candidatas')) return;
    await api.post(`/empresas/${e.codigo}/descartar`, { candidatas: e.candidatas.map(c => c.id) });
    toast('Candidatas descartadas', 'ok'); recargar();
  });
  if (!edita) return;
  let archivo = null;
  activarDrop('pv-arch', f => { archivo = f; $('#pv-analizar').disabled = false; });
  $('#pv-analizar').onclick = async () => {
    try {
      const p = await api.upload('/provisorias/ruts/analizar', archivo, {});
      const ACC = { promover: est('ok', 'pasa a la definitiva'), fusionar: est('sospechoso', 'el RUT ya existe: fusionar'), error: est('error', 'error') };
      $('#pv-prev').innerHTML = `<div class="small mb">${num(p.conteos.promover)} pasan a la definitiva · ${num(p.conteos.fusionar)} con un RUT que ya existe · ${num(p.conteos.error)} con error</div>` +
        tabla([{ t: 'Fila', cls: 'num', k: 'fila' }, { t: 'Código', f: x => `<span class="mono">${esc(x.codigo || '—')}</span>` },
          { t: 'RUT', f: x => `<span class="mono">${rutFmt(x.rut || x.rut_crudo || '')}</span>` }, { t: 'Razón social', f: x => esc(x.razon_social || '') },
          { t: 'Qué pasa', f: x => ACC[x.accion] + (x.motivo ? ` <span class="small muted">${esc(x.motivo)}</span>` : '') + (x.existente ? ` <span class="small muted">con ${rutFmt(x.existente)} ${esc(x.existente_razon_social || '')}</span>` : '') },
        ], p.filas) +
        `<div class="mt gap"><label class="check"><input type="checkbox" id="pv-fusionar" /> Fusionar también las que tienen un RUT que ya existe</label>
        <button class="btn btn-green" id="pv-aplicar">Aplicar</button></div>`;
      $('#pv-aplicar').onclick = async () => {
        const n = await api.post('/provisorias/ruts/aplicar', { archivo_id: p.archivo_id, fusionar: $('#pv-fusionar').checked });
        toast(`${num(n.promovidas)} pasaron a la definitiva, ${num(n.fusionadas)} fusionadas${n.pendientes ? `, ${num(n.pendientes)} sin fusionar` : ''}`, 'ok');
        recargar();
      };
    } catch (e) { toast(e.message, 'err'); }
  };
}
