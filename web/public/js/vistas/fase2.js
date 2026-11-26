// ════════════════════════════════════════════════════════════════
//  Fase 2 (SPEC_fase2_enriquecimiento): calidad de la base, enriquecimiento bajo demanda,
//  posibles duplicados y grupos económicos, descubrimiento de empresas nuevas
// ════════════════════════════════════════════════════════════════
import * as api from '../api.js';
import { $, $$, esc, toast, main, num, fecha, fechaHora, rutFmt, est, pageHeader, stats, tabla, card, modal, confirmar,
  pedirTexto, seguirTarea, tabs } from '../ui.js';

const usd = (n) => n === null || n === undefined ? '—' : 'US$' + Number(n).toLocaleString('es-UY', { minimumFractionDigits: 2, maximumFractionDigits: 4 });
const ESTADO_CAL = { cumple: ['ok', 'cumple'], cerca: ['pendiente', 'cerca'], no_cumple: ['error', 'no cumple'],
  sin_historia: ['pendiente', 'sin historia'], sin_datos: ['pendiente', 'sin datos'], informativo: ['liberado', 'informativo'] };
const estCal = (s) => est(...(ESTADO_CAL[s] || [s, s]));
const ESTADO_CORRIDA = { estimada: 'estimada', en_curso: 'en curso', terminada: 'terminada', detenida_tope: 'detenida por tope',
  cancelada: 'cancelada', error: 'error', preview: 'para revisar', confirmada: 'confirmada', descartada: 'descartada', deshecha: 'deshecha' };
const CLS_CORRIDA = { en_curso: 'corriendo', terminada: 'ok', confirmada: 'ok', detenida_tope: 'sospechoso', error: 'error',
  cancelada: 'cancelada', deshecha: 'deshecha', preview: 'pendiente', estimada: 'pendiente' };
const estCorrida = (s) => est(CLS_CORRIDA[s] || s, ESTADO_CORRIDA[s] || s);
const ORIGEN = { muestra: 'Muestra', lista: 'Lista filtrada', ficha: 'Ficha', descubrimiento: 'Descubrimiento' };
const CRITERIO = { telefono: 'teléfono', dominio: 'sitio web', direccion: 'dirección', razon_social: 'razón social' };
const valorInd = (i) => i.valor === null || i.valor === undefined ? '—' : i.unidad === '%' ? `${Number(i.valor).toLocaleString('es-UY', { maximumFractionDigits: 1 })} %` : num(i.valor);

// Evolución: línea chica con los puntos guardados por el job diario
function sparkline(serie) {
  const v = serie.map(p => p.valor).filter(x => x !== null);
  if (v.length < 2) return `<span class="small muted">${v.length ? '1 medición' : 'sin mediciones'}</span>`;
  const w = 140, h = 30, min = Math.min(...v), max = Math.max(...v), rango = max - min || 1;
  const pts = v.map((x, i) => `${(i * w / (v.length - 1)).toFixed(1)},${(h - 3 - (x - min) * (h - 6) / rango).toFixed(1)}`).join(' ');
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img"
    aria-label="Evolución: de ${esc(v[0])} a ${esc(v[v.length - 1])} en ${v.length} mediciones"><polyline points="${pts}" fill="none"
    stroke="currentColor" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" /></svg>
    <div class="small muted">${v.length} mediciones · desde ${esc(fecha(serie[0].fecha))}</div>`;
}

// ── A1 · Calidad de la base ──
export async function calidad(ctx) {
  const t = await api.get('/calidad');
  const g = t.enriquecimiento;
  const usoTope = g.tope_mensual ? Math.min(100, 100 * g.gasto_mes / g.tope_mensual) : 0;
  main().innerHTML = pageHeader('Calidad', 'de la base', `Una tarjeta por dimensión DMBOK, con su meta y la lista de lo que la incumple: es la lista de trabajo de la semana.
    ${t.ultima_medicion ? `Última foto del histórico: ${esc(fecha(t.ultima_medicion))}.` : 'Todavía no hay fotos del histórico: el job diario guarda la primera.'}`,
    ctx.puede('admin') ? `<button class="btn btn-outline btn-sm" id="cal-medir">Guardar la foto de hoy</button>` : '') +
    `<div class="grid-2">${t.dimensiones.map(d => card(d.nombre, `<p class="small muted mb">${esc(d.regla)}</p>
      ${d.indicadores.map(i => `<div class="cal-ind">
        <div class="cal-ind-main"><div class="td-strong">${esc(i.nombre)}</div>
          <div class="small muted">Meta: ${esc(i.meta_texto)}${i.trimestre_anterior !== null && i.trimestre_anterior !== undefined ? ` · hace un trimestre: ${esc(i.trimestre_anterior)} %` : ''}</div>
          <div class="small">${i.denominador ? `${num(i.numerador)} de ${num(i.denominador)}` : ''}
          ${i.estado !== 'informativo' || i.clave === 'provisorias' ? `<a class="link" href="#/calidad/${esc(i.clave)}">Ver la lista</a>` : ''}</div></div>
        <div class="cal-ind-valor"><div class="stat-num mono">${valorInd(i)}</div>${estCal(i.estado)}</div>
        <div class="cal-ind-spark">${sparkline(i.serie)}</div></div>`).join('')}`, estCal(d.estado))).join('')}
      ${card('Enriquecimiento', `<div class="small muted mb">Gasto del mes contra el tope mensual duro (Configuración → Enriquecimiento).</div>
        <div class="progress"><span style="width:${usoTope}%"></span></div>
        <div class="progress-label"><span>${usd(g.gasto_mes)} de ${usd(g.tope_mensual)}</span><span>quedan ${usd(g.restante_mes)}</span></div>
        ${stats([[usd(g.costo_por_verificado_mes), 'costo por teléfono verificado (mes)', g.costo_por_verificado_mes === null ? '' : g.costo_por_verificado_mes > 0.1 ? 's-bad' : 's-ok'],
                 [usd(g.costo_por_verificado_total), 'costo por verificado (acumulado)'],
                 [g.verificados_mes, 'enriquecidos verificados en el mes'], [g.places_gratis_restantes, 'llamadas gratis de Places que quedan']])}
        <div class="small muted">Meta: ≤ US$0,10 por teléfono verificado (stretch: US$0,05). Gasto acumulado: ${usd(g.gasto_total)}.</div>
        ${Object.keys(g.por_proveedor).length ? tabla([{ t: 'Proveedor', k: 'p' }, { t: 'Gasto del mes', cls: 'num', f: x => usd(x.g) }],
          Object.entries(g.por_proveedor).map(([p, x]) => ({ p, g: x }))) : '<div class="small muted mt">Sin gasto este mes.</div>'}
        <div class="mt"><a class="link" href="#/enriquecimiento">Ver las corridas</a></div>`)}</div>`;
  if ($('#cal-medir')) $('#cal-medir').onclick = async () => { await api.post('/calidad/medir'); toast('Foto guardada', 'ok'); calidad(ctx); };
}

export async function calidadLista(ctx, indicador, params) {
  const pagina = +(params.get('pagina') || 1);
  if (indicador === 'duplicados_pendientes') return ctx.ir('duplicados');
  const r = await api.get(`/calidad/${indicador}`, { pagina });
  const t = await api.get('/calidad');
  const ind = t.dimensiones.flatMap(d => d.indicadores.map(i => ({ ...i, dim: d.nombre }))).find(i => i.clave === indicador) || { nombre: indicador };
  const empresa = (f) => f.codigo ? `<a class="link mono" href="#/empresas/${esc(f.codigo)}">${esc(rutFmt(f.codigo))}</a>` : '—';
  const cols = r.tipo === 'telefonos'
    ? [{ t: 'Teléfono', f: f => `<span class="mono">${esc(f.e164 || f.crudo)}</span>` }, { t: 'Empresa', f: empresa },
       { t: 'Razón social', k: 'razon_social' }, { t: 'Problema', k: 'problema' }]
    : [{ t: 'Empresa', f: empresa }, { t: 'Razón social', f: f => `<span class="td-strong">${esc(f.razon_social || '—')}</span>` },
       ...(indicador === 'consistencia' ? [{ t: 'Naturaleza', f: f => `${esc(f.naturaleza)} → la razón social sugiere <strong>${esc(f.sugerida)}</strong>` }] : []),
       { t: 'Problema', f: f => esc(f.problema || '') },
       ...(indicador === 'consistencia' && ctx.puede('steward') ? [{ t: '', f: f => `<button class="btn btn-outline btn-sm" data-revisar="${f.id}">Revisada</button>` }] : [])];
  const paginas = Math.max(1, Math.ceil(r.total / r.por_pagina));
  main().innerHTML = pageHeader(ind.nombre, '', `${esc(ind.dim || '')} · meta: ${esc(ind.meta_texto || '')}. ${num(r.total)} para revisar.
    <a class="link" href="#/calidad">Volver al tablero</a>`) +
    card(`${num(r.total)} ${r.tipo === 'telefonos' ? 'teléfonos' : 'empresas'}`, tabla(cols, r.filas, 'Nada para revisar: se cumple la regla') +
      (paginas > 1 ? `<div class="toolbar mt"><button class="btn btn-outline btn-sm" id="cl-ant" ${pagina <= 1 ? 'disabled' : ''}>Anterior</button>
        <span class="small muted">Página ${pagina} de ${paginas}</span><button class="btn btn-outline btn-sm" id="cl-sig" ${pagina >= paginas ? 'disabled' : ''}>Siguiente</button></div>` : ''), '', true);
  if ($('#cl-ant')) $('#cl-ant').onclick = () => ctx.ir(`calidad/${indicador}?pagina=${pagina - 1}`);
  if ($('#cl-sig')) $('#cl-sig').onclick = () => ctx.ir(`calidad/${indicador}?pagina=${pagina + 1}`);
  $$('[data-revisar]').forEach(b => b.onclick = async () => {
    await api.post(`/calidad/alertas/${b.dataset.revisar}/revisar`);
    toast('Alerta revisada', 'ok'); calidadLista(ctx, indicador, params);
  });
}

// Nombre de cada paso de la cascada (D57: el paso 5, búsqueda web con Claude)
const PASO = { google_places: 'Google Places', brave: 'Brave Search', claude: 'Claude', sitio: 'Lectura del sitio',
  claude_web: 'Búsqueda web (Claude)', propias: 'Fuentes propias' };
const RESULTADO_EMP = { con_telefono: 'con teléfono', sin_resultado: 'sin resultado', tope: 'tope', ya_tenia: 'ya tenía',
  baja: 'dada de baja', error: 'error' };

// ── B2 · Lanzar una corrida: estimación, aprobación y seguimiento ──
export async function enriquecer(ctx, body) {
  let e;
  try { e = await api.post('/enriquecimiento/estimar', body); } catch (err) { return toast(err.message, 'err'); }
  const x = e.estimacion;
  const salteadas = Object.values(x.salteadas || {});
  const proveedores = Object.entries(x.proveedores).map(([p, s]) => `${PASO[p] || p}: ${s}`).join(' · ');
  if (!x.empresas) {
    await modal({ titulo: 'No hay empresas para enriquecer', cuerpo: e.opciones.candidatas
      ? `<p>De ${num(e.opciones.candidatas)} empresas, ninguna necesita enriquecerse:</p>
        <ul>${salteadas.map(s => `<li>${num(s.cantidad)} ${esc(s.motivo)}</li>`).join('')}</ul>`
      : `<p>${body.alcance === 'sin_telefono' ? 'Todas las empresas de la muestra tienen un teléfono discable.' : 'La selección no tiene empresas.'}</p>`,
      acciones: [{ t: 'Cerrar' }] });
    return api.post(`/enriquecimiento/${e.id}/descartar`).catch(() => {});
  }
  const cuerpo = `${stats([[x.empresas, 'empresas a enriquecer'], [usd(x.maximo), 'costo máximo', x.excede ? 's-bad' : ''],
      [usd(x.esperado), 'costo esperado'], [usd(x.permitido), 'permitido en esta corrida']])}
    ${salteadas.length ? `<div class="small mb"><strong>Se saltean</strong> (no se gasta en ellas):<ul>${salteadas.map(s => `<li>${num(s.cantidad)} ${esc(s.motivo)}</li>`).join('')}</ul></div>` : ''}
    <div class="small mb">Costo máximo por proveedor: ${Object.entries(x.por_proveedor_maximo).map(([p, v]) => `${esc(p)} ${usd(v)}`).join(' · ')}.
      ${x.places_gratis ? `${num(x.places_gratis)} llamadas a Places entran en las gratuitas del mes.` : ''}
      El esperado usa una tasa de éxito de Places de ${Math.round(100 * x.tasa_exito_places)} %.
      ${x.busqueda_web ? `<br><strong>Búsqueda web (Claude): hasta ${usd(x.busqueda_web.maximo)}</strong> (se esperan unos ${usd(x.busqueda_web.esperado)}: solo para las empresas que Places, Brave y el sitio no resuelven).` : ''}</div>
    <div class="small mb">Gasto del mes: ${usd(x.gasto_mes)} de ${usd(x.tope_mensual)} (quedan ${usd(x.restante_mes)}) · tope por corrida ${usd(x.tope_corrida)}.
      La cascada ${x.corte === 'telefono' ? 'se corta apenas consigue un teléfono' : 'sigue hasta tener teléfono y sitio web'}.</div>
    <div class="small muted mb">${esc(proveedores)}</div>
    ${x.excede ? `<div class="alert alert-warn">El costo máximo supera lo permitido${x.empresas > x.max_empresas_corrida ? ` o el máximo de ${num(x.max_empresas_corrida)} empresas por corrida` : ''}.
      Se pueden enriquecer como máximo <strong>${num(x.max_empresas_permitidas)}</strong> empresas.</div>
      <div class="form-row"><div class="form-group"><label>Enriquecer</label><input type="number" id="en-lim" min="1" max="${x.max_empresas_permitidas}" value="${x.max_empresas_permitidas}" /></div>
      <div class="form-group"><label>Cuáles</label><select class="fselect" id="en-red"><option value="orden">Las primeras (orden de la ${body.origen === 'muestra' ? 'muestra' : 'lista'})</option>
      <option value="azar">Al azar</option></select></div></div>` : ''}
    <p class="small muted">No se gasta nada hasta aprobar. Antes de cada llamada paga se verifica el tope: si se llega, la corrida se detiene y lo conseguido queda guardado.</p>`;
  const r = await modal({ titulo: `Enriquecer ${x.empresas === 1 ? 'esta empresa' : `${num(x.empresas)} empresas`}`, cuerpo, ancho: 680,
    acciones: [{ t: 'Cancelar' }, { t: 'Aprobar y enriquecer', cls: 'btn-orange', fn: async (b) => {
      const lim = b.querySelector('#en-lim');
      if (lim && (!+lim.value || +lim.value > x.max_empresas_permitidas)) { toast(`Como máximo ${x.max_empresas_permitidas} empresas`, 'err'); return false; }
      return api.post(`/enriquecimiento/${e.id}/aprobar`, lim ? { limite: +lim.value, reducir: b.querySelector('#en-red').value } : {});
    } }] });
  if (!r) return api.post(`/enriquecimiento/${e.id}/descartar`).catch(() => {});
  ctx.ir(`enriquecimiento/${e.id}`);
}

export async function corridas(ctx) {
  const filas = await api.get('/enriquecimiento');
  main().innerHTML = pageHeader('Enriquecimiento', 'corridas', 'Se lanzan desde una muestra, desde Empresas (con los filtros de la pantalla) o desde la ficha. Cada una muestra su estimación aprobada, el gasto real y lo que consiguió.') +
    card(`${num(filas.length)} corridas`, tabla([
      { t: '#', f: c => `<a class="link" href="#/enriquecimiento/${c.id}">#${c.id}</a>` },
      { t: 'Desde', f: c => c.origen === 'muestra' && c.muestra_id ? `Muestra <a class="link" href="#/muestras/${c.muestra_id}">${esc(c.muestra || '#' + c.muestra_id)}</a>` : esc(ORIGEN[c.origen] || c.origen) },
      { t: 'Estado', f: c => estCorrida(c.estado) + (c.estado === 'en_curso' && c.total ? ` <span class="small muted">${num(c.progreso)} / ${num(c.total)}</span>` : '') },
      { t: 'Empresas', cls: 'num', f: c => num(c.empresas) },
      { t: 'Con teléfono nuevo', cls: 'num', f: c => c.con_telefono_nuevo === null ? '—' : `${num(c.con_telefono_nuevo)}${c.tasa_telefono !== null ? ` <span class="small muted">(${c.tasa_telefono} %)</span>` : ''}` },
      { t: 'Gasto', cls: 'num', f: c => `${usd(c.gasto)}<div class="small muted">máx. ${usd(c.costo_maximo)}</div>` },
      { t: 'Lanzó', f: c => `${esc(c.creado_por)}<div class="small muted">${esc(fechaHora(c.creado))}</div>` },
    ], filas, 'Todavía no hay corridas'), '', true);
}

export async function corrida(ctx, id) {
  let c = await api.get(`/enriquecimiento/${id}`);
  // D57 (B3): debajo de una fila con error, el motivo más frecuente («422: country: …» × 3) y los demás al pasar el mouse
  const motivoPaso = (p) => {
    const m = p.resultado === 'error' ? (c.errores || {})[p.proveedor] || [] : [];
    if (!m.length) return '';
    const todos = m.map(x => `${x.motivo} × ${x.n}`).join('\n');
    return `<div class="small motivo-error" title="${esc(todos)}">${esc(m[0].motivo)} × ${num(m[0].n)}${m.length > 1 ? ` <span class="muted">y ${m.length - 1} motivo${m.length > 2 ? 's' : ''} más</span>` : ''}</div>`;
  };
  const r = c.resultado || {};
  const x = c.estimacion || {};
  const puedeDeshacer = ctx.puede('steward') && ['terminada', 'detenida_tope', 'cancelada', 'error'].includes(c.estado);
  main().innerHTML = pageHeader(`Enriquecimiento #${c.id}`, ESTADO_CORRIDA[c.estado] || c.estado,
    `${esc(ORIGEN[c.origen] || c.origen)}${c.muestra_id ? ` · <a class="link" href="#/muestras/${c.muestra_id}">${esc(c.muestra || 'muestra')}</a>` : ''}
     · lanzó ${esc(c.creado_por)} el ${esc(fechaHora(c.creado))}${c.aprobada_por ? ` · aprobó ${esc(c.aprobada_por)}` : ''}`,
    (c.estado === 'en_curso' ? `<button class="btn btn-outline btn-sm btn-del" id="co-cancelar">Cancelar</button>` : '') +
    (puedeDeshacer ? `<button class="btn btn-outline btn-sm btn-del" id="co-deshacer">Deshacer</button>` : '') +
    `<a class="btn btn-outline btn-sm" href="#/enriquecimiento">Todas las corridas</a>`) +
    `<div id="co-progreso"></div>` +
    stats([[r.procesadas ?? 0, `procesadas de ${num(c.n_empresas)}`], [r.con_telefono_nuevo ?? 0, `con teléfono nuevo${r.tasa_telefono !== null && r.tasa_telefono !== undefined ? ` (${r.tasa_telefono} %)` : ''}`, 's-ok'],
      [r.sin_resultado ?? 0, 'sin resultado', 's-bad'], [usd(c.gasto), `gasto real (máx. aprobado ${usd(x.maximo)})`]]) +
    (c.estado === 'detenida_tope' ? `<div class="alert alert-warn mb">La corrida se detuvo al llegar al tope de gasto. Lo conseguido quedó guardado.</div>` : '') +
    (c.error ? `<div class="alert alert-error mb">${esc(c.error)}</div>` : '') +
    ((r.avisos || []).length ? `<div class="alert alert-warn mb">${r.avisos.map(esc).join('<br>')}</div>` : '') +
    `<div class="grid-2">${card('Gasto por proveedor', tabla([{ t: 'Proveedor', k: 'p' }, { t: 'Gasto', cls: 'num', f: f => usd(f.g) }],
        Object.entries(r.gasto_por_proveedor || {}).map(([p, g]) => ({ p, g })), 'Sin gasto'), '', true)}
      ${card('Pasos', tabla([{ t: 'Paso', f: p => `${esc(PASO[p.proveedor] || p.proveedor)}${motivoPaso(p)}${p.proveedor === 'claude_web' && p.propuestos !== null
          ? `<div class="small muted">${num(p.propuestos)} teléfonos propuestos · ${num(p.verificados)} verificados · ${num(p.busquedas)} búsquedas</div>` : ''}` },
        { t: 'Resultado', f: p => est(p.resultado === 'ok' ? 'ok' : p.resultado === 'tope' ? 'sospechoso' : p.resultado === 'error' ? 'error' : 'pendiente', p.resultado.replace('_', ' ')) },
        { t: 'Cantidad', cls: 'num', f: p => num(p.n) }, { t: 'Costo', cls: 'num', f: p => usd(p.costo) }], c.pasos, 'Todavía no hay pasos'), '', true)}</div>` +
    (r.procesadas ? card('Empresas', `<div class="toolbar mb">${tabs('co-res', [['', 'Todas'], ['con_telefono', 'Con teléfono nuevo'], ['sin_resultado', 'Sin resultado'],
      ...(r.con_error ? [['error', 'Con error']] : []), ['tope', 'Por el tope']], '')}</div>
      <div id="co-emp"></div>`) : '');
  const empresas = async (resultado = '', pagina = 1) => {
    const e = await api.get(`/enriquecimiento/${id}/empresas`, { resultado, pagina });
    $('#co-emp').innerHTML = tabla([
      { t: 'Empresa', f: f => f.codigo ? `<a class="link mono" href="#/empresas/${esc(f.codigo)}">${esc(rutFmt(f.codigo))}</a>` : '—' },
      { t: 'Razón social', f: f => `<span class="td-strong">${esc(f.razon_social || '—')}</span>` },
      { t: 'Teléfonos nuevos', cls: 'num', f: f => num(f.telefonos_nuevos) },
      { t: 'Además', f: f => [f.web && 'sitio web', f.direccion && 'dirección', f.email && 'email', f.estudio && 'sitio de estudio contable'].filter(Boolean).join(', ') || '—' },
      { t: 'Resultado', f: f => {
        const motivos = (f.errores || []).map(x => `${x.proveedor}: ${x.motivo}`).join('\n');
        const chip = est(f.resultado === 'con_telefono' ? 'ok' : f.resultado === 'tope' ? 'sospechoso' : f.resultado === 'error' ? 'error' : 'pendiente',
          RESULTADO_EMP[f.resultado] || f.resultado);
        return motivos ? `<span title="${esc(motivos)}" class="con-motivo">${chip}</span>` : chip;
      } },
    ], e.filas, 'Ninguna') + (e.total > 50 ? `<div class="small muted mt">${num(e.total)} en total · página ${pagina}
      ${pagina > 1 ? `<a class="link" data-pag="${pagina - 1}">anterior</a>` : ''} ${pagina * 50 < e.total ? `<a class="link" data-pag="${pagina + 1}">siguiente</a>` : ''}</div>` : '');
    $$('#co-emp [data-pag]').forEach(a => a.onclick = () => empresas(resultado, +a.dataset.pag));
  };
  if ($('#co-emp')) {
    empresas();
    $$('[data-tabs="co-res"] [data-tab]').forEach(b => b.onclick = () => {
      $$('[data-tabs="co-res"] [data-tab]').forEach(t => t.classList.toggle('active', t === b)); empresas(b.dataset.tab);
    });
  }
  if ($('#co-cancelar')) $('#co-cancelar').onclick = async () => {
    if (!await confirmar('Cancelar la corrida', 'Se detiene al terminar la empresa en curso. Lo conseguido hasta ahora queda guardado.', 'Cancelar la corrida', 'btn-danger')) return;
    await api.post(`/enriquecimiento/${id}/cancelar`); toast('Corrida cancelada', 'ok'); corrida(ctx, id);
  };
  if ($('#co-deshacer')) $('#co-deshacer').onclick = async () => {
    if (!await confirmar('Deshacer la corrida', 'Se quitan los teléfonos, sitios, direcciones y emails que trajo. Los teléfonos que la sala ya verificó quedan.', 'Deshacer', 'btn-danger')) return;
    const d = await api.post(`/enriquecimiento/${id}/deshacer`);
    toast(`Deshecha: ${d.vinculos_quitados} teléfonos quitados, ${d.verificados_conservados} verificados conservados`, 'ok'); corrida(ctx, id);
  };
  if (c.estado === 'en_curso' && c.tarea_id) {
    try { await seguirTarea(c.tarea_id, $('#co-progreso'), { texto: 'Enriqueciendo' }); } catch (e) { /* cancelada o con error: se muestra al recargar */ }
    if (location.hash === `#/enriquecimiento/${id}`) corrida(ctx, id);
  }
}

// ── B4 · Posibles duplicados ──
const ladoDup = (e) => `<div class="dup-lado"><a class="link mono" href="#/empresas/${esc(e.codigo)}">${esc(rutFmt(e.codigo))}</a>
  <div class="td-strong">${esc(e.razon_social || '—')}</div>${e.fantasia ? `<div class="small muted">${esc(e.fantasia)}</div>` : ''}
  <div class="small">${esc([e.direccion, e.localidad, e.departamento].filter(Boolean).join(', ') || 'sin dirección')}</div>
  <div class="small muted">${esc(e.web || 'sin web')} · ${num(e.telefonos)} teléfonos · CIIU ${esc(e.ciiu || '—')} · ${esc(e.tamano || '—')}</div>
  ${e.grupo ? `<div class="small">${est('liberado', 'grupo: ' + e.grupo)}</div>` : ''}</div>`;

export async function duplicados(ctx, params) {
  const estado = params.get('estado') || 'pendiente';
  const pagina = +(params.get('pagina') || 1);
  const r = await api.get('/duplicados', { estado, pagina });
  const paginas = Math.max(1, Math.ceil(r.total / r.por_pagina));
  main().innerHTML = pageHeader('Posibles', 'duplicados', `Pares de empresas con RUT distinto que comparten teléfono, sitio web, dirección o una razón social muy parecida.
    Se detectan todos los días. ${r.vencidos ? `<strong>${num(r.vencidos)} llevan más de 14 días sin resolver.</strong>` : ''}`,
    `<button class="btn btn-outline btn-sm" id="dup-detectar">Detectar ahora</button>`) +
    `<div class="toolbar mb">${tabs('dup-estado', [['pendiente', 'Pendientes'], ['grupo', 'Grupo económico'], ['fusionado', 'Fusionados'], ['sin_relacion', 'Sin relación']], estado)}</div>` +
    (r.filas.length ? r.filas.map(p => `<div class="card mb"><div class="card-header"><div class="card-header-title">
        ${p.criterios.map(c => est('sospechoso', CRITERIO[c.criterio] || c.criterio)).join(' ')} ${p.vencido && estado === 'pendiente' ? est('error', 'más de 14 días') : ''}</div>
        <div class="small muted">detectado ${esc(fecha(p.detectado))}${p.resuelto_por ? ` · resolvió ${esc(p.resuelto_por)} el ${esc(fecha(p.resuelto))}` : ''}</div></div>
      <div class="card-body"><div class="small muted mb">Coinciden en: ${p.criterios.map(c => `${esc(CRITERIO[c.criterio] || c.criterio)} <span class="mono">${esc(c.evidencia)}</span>`).join(' · ')}</div>
        <div class="grid-2">${ladoDup(p.a)}${ladoDup(p.b)}</div>
        ${estado === 'pendiente' ? `<div class="toolbar mt"><button class="btn btn-outline btn-sm" data-dup="${p.id}" data-acc="fusionar" data-queda="${p.a.id}">Fusionar: queda ${esc(rutFmt(p.a.codigo))}</button>
          <button class="btn btn-outline btn-sm" data-dup="${p.id}" data-acc="fusionar" data-queda="${p.b.id}">Fusionar: queda ${esc(rutFmt(p.b.codigo))}</button>
          <button class="btn btn-orange btn-sm" data-dup="${p.id}" data-acc="grupo">Son grupo económico</button>
          <button class="btn btn-outline btn-sm btn-del" data-dup="${p.id}" data-acc="sin_relacion">Sin relación</button></div>` : ''}</div></div>`).join('')
      : `<div class="empty-state"><span class="ei">✅</span>${estado === 'pendiente' ? 'No hay posibles duplicados pendientes' : 'Ninguno'}</div>`) +
    (paginas > 1 ? `<div class="toolbar"><button class="btn btn-outline btn-sm" id="dup-ant" ${pagina <= 1 ? 'disabled' : ''}>‹ Anterior</button>
      <span class="small muted">${num(r.total)} pares · página ${pagina} de ${paginas}</span>
      <button class="btn btn-outline btn-sm" id="dup-sig" ${pagina >= paginas ? 'disabled' : ''}>Siguiente ›</button></div>` : '');
  if ($('#dup-ant')) $('#dup-ant').onclick = () => ctx.ir(`duplicados?estado=${estado}&pagina=${pagina - 1}`);
  if ($('#dup-sig')) $('#dup-sig').onclick = () => ctx.ir(`duplicados?estado=${estado}&pagina=${pagina + 1}`);
  $$('[data-tabs="dup-estado"] [data-tab]').forEach(b => b.onclick = () => ctx.ir(`duplicados?estado=${b.dataset.tab}`));
  $('#dup-detectar').onclick = async () => {
    const d = await api.post('/duplicados/detectar');
    toast(`${d.nuevos} pares nuevos · ${d.pendientes} pendientes`, 'ok'); duplicados(ctx, params);
  };
  $$('[data-dup]').forEach(b => b.onclick = async () => {
    const accion = b.dataset.acc;
    const body = { accion };
    if (accion === 'fusionar') {
      if (!await confirmar('Fusionar', 'La otra empresa se fusiona en la que queda (teléfonos, contactos e historia). Se puede deshacer desde la ficha.', 'Fusionar')) return;
      body.absorbente_id = +b.dataset.queda;
    } else if (accion === 'grupo') {
      const nombre = await pedirTexto('Grupo económico', 'Nombre del grupo (opcional: si alguna ya está en un grupo, la otra se suma a ese)', { obligatorio: false });
      if (nombre === null) return;
      body.nombre_grupo = nombre || null;
    }
    await api.post(`/duplicados/${b.dataset.dup}/resolver`, body);
    toast('Listo', 'ok'); duplicados(ctx, params);
  });
}

// ── B5 · Buscar empresas nuevas (Google Places) ──
const CASO = { nueva: ['ok', 'nueva'], coincide: ['sospechoso', 'coincide'], ya_guardado: ['liberado', 'ya guardada'] };

export async function descubrimiento(ctx) {
  const [lotes, valores] = await Promise.all([api.get('/descubrimiento'), api.valores()]);
  main().innerHTML = pageHeader('Buscar empresas', 'nuevas', 'Busca por rubro y zona en Google Places. Cada resultado se compara con la base: los nuevos entran a la base provisoria (con origen Google Places) y los que coinciden con una empresa se pueden completar. Nada se guarda hasta confirmar.') +
    card('Búsqueda', `<div class="form-group"><label>Qué buscar</label><input type="text" id="de-q" placeholder="imprentas en Salto" /></div>
      <div class="small muted mb">O armala por partes:</div>
      <div class="form-row"><div class="form-group"><label>Rubro</label><input type="text" id="de-rubro" placeholder="estudios de arquitectura" /></div>
      <div class="form-group"><label>Departamento</label><select class="fselect" id="de-dep"><option value="">—</option>${(valores.departamento || []).map(d => `<option>${esc(d)}</option>`).join('')}</select></div>
      <div class="form-group"><label>Localidad</label><input type="text" id="de-loc" /></div>
      <div class="form-group"><label>Páginas (20 resultados c/u)</label><select class="fselect" id="de-pag"><option>1</option><option>2</option><option>3</option></select></div></div>
      <button class="btn btn-orange" id="de-estimar">Ver el costo</button>`) +
    card(`${num(lotes.length)} búsquedas`, tabla([
      { t: '#', f: l => `<a class="link" href="#/descubrimiento/${l.id}">Descubrimiento #${l.id}</a>` },
      { t: 'Búsqueda', f: l => esc((l.filtros || {}).consulta || '') },
      { t: 'Estado', f: l => estCorrida(l.estado) }, { t: 'Gasto', cls: 'num', f: l => usd(l.gasto) },
      { t: 'Lanzó', f: l => `${esc(l.creado_por)}<div class="small muted">${esc(fechaHora(l.creado))}</div>` },
    ], lotes, 'Todavía no hay búsquedas'), '', true);
  $('#de-estimar').onclick = async () => {
    const e = await api.post('/descubrimiento/estimar', { consulta: $('#de-q').value.trim() || null, rubro: $('#de-rubro').value.trim() || null,
      departamento: $('#de-dep').value || null, localidad: $('#de-loc').value.trim() || null, paginas: +$('#de-pag').value });
    const x = e.estimacion;
    const ok = await modal({ titulo: 'Buscar en Google Places', ancho: 600, cuerpo: `<p><strong>${esc(x.consulta)}</strong></p>
      ${stats([[x.paginas, 'páginas (llamadas)'], [usd(x.maximo), 'costo máximo', x.excede ? 's-bad' : ''], [x.places_gratis, 'dentro de las gratis del mes']])}
      <div class="small">Gasto del mes: ${usd(x.gasto_mes)} de ${usd(x.tope_mensual)} · tope por búsqueda ${usd(x.tope_corrida)}.</div>
      ${x.excede ? `<div class="alert alert-warn mt">Supera lo permitido: pedí menos páginas.</div>` : ''}`,
      acciones: [{ t: 'Cancelar' }, ...(x.excede ? [] : [{ t: 'Buscar', cls: 'btn-orange', valor: true }])] });
    if (!ok) return api.post(`/descubrimiento/${e.id}/descartar`).catch(() => {});
    await api.post(`/descubrimiento/${e.id}/buscar`);
    ctx.ir(`descubrimiento/${e.id}`);
  };
}

export async function descubrimientoLote(ctx, id) {
  const c = await api.get(`/descubrimiento/${id}`);
  const r = c.resultado || { resultados: [], resumen: {} };
  const preview = c.estado === 'preview';
  main().innerHTML = pageHeader(`Descubrimiento #${c.id}`, ESTADO_CORRIDA[c.estado] || c.estado,
    `${esc((c.filtros || {}).consulta || '')} · ${esc(c.creado_por)}, ${esc(fechaHora(c.creado))} · gasto ${usd(c.gasto)}`,
    (c.estado === 'confirmada' ? `<button class="btn btn-outline btn-sm btn-del" id="de-deshacer">Deshacer</button>` : '') +
    `<a class="btn btn-outline btn-sm" href="#/descubrimiento">Volver</a>`) +
    ((r.avisos || []).length ? `<div class="alert alert-warn mb">${r.avisos.map(esc).join('<br>')}</div>` : '') +
    stats([[r.resumen.nueva || 0, 'nuevas', 's-ok'], [r.resumen.coincide || 0, 'coinciden con una empresa'], [r.resumen.ya_guardado || 0, 'ya guardadas']]) +
    (r.confirmado ? `<div class="alert alert-success mb">Confirmado: ${num(r.confirmado.altas)} altas en la base provisoria, ${num(r.confirmado.completadas)} empresas completadas,
      ${num(r.confirmado.telefonos)} teléfonos nuevos. <a class="link" href="#/provisorias">Ver la base provisoria</a></div>` : '') +
    card(`${num(r.resultados.length)} resultados`, tabla([
      { t: 'Caso', f: f => est(...CASO[f.caso]) },
      { t: 'En Google Places', f: f => `<span class="td-strong">${esc(f.nombre)}</span><div class="small muted">${esc(f.direccion || '')}</div>
        <div class="small">${esc(f.telefono || 'sin teléfono')}${f.web ? ` · ${esc(f.web)}` : ''}${f.cerrado ? ' · ' + est('error', 'cerrada') : ''}</div>` },
      { t: 'En la base', f: f => f.empresa ? `<a class="link mono" href="#/empresas/${esc(f.empresa.codigo)}">${esc(rutFmt(f.empresa.codigo))}</a> ${esc(f.empresa.razon_social || '')}
        ${f.regla ? `<div class="small muted">por ${esc(CRITERIO[f.regla] || f.regla.replace('_web', ' web'))}${f.tipo === 'flexible' ? ` (similitud ${Math.round(100 * f.similitud)} %: revisá)` : ''}</div>` : ''}` : '<span class="muted">—</span>' },
      { t: 'Qué hacer', f: f => !preview || f.caso === 'ya_guardado' ? '<span class="muted">—</span>' : `<select class="fselect" data-sel="${f.i}">
        ${f.caso === 'coincide' ? `<option value="completar" ${f.marcada ? 'selected' : ''}>Completar la empresa</option><option value="alta">Alta en la provisoria</option>`
          : `<option value="alta" ${f.marcada ? 'selected' : ''}>Alta en la provisoria</option>`}
        <option value="omitir" ${f.marcada ? '' : 'selected'}>No guardar</option></select>` },
    ], r.resultados, 'Sin resultados'), '', true) +
    (preview ? `<div class="toolbar"><button class="btn btn-orange" id="de-confirmar">Confirmar</button>
      <button class="btn btn-outline" id="de-descartar">Descartar</button></div>` : '');
  if (preview) {
    $('#de-confirmar').onclick = async () => {
      const seleccion = Object.fromEntries($$('[data-sel]').map(s => [s.dataset.sel, s.value]));
      await api.post(`/descubrimiento/${id}/confirmar`, { seleccion });
      toast('Lote confirmado', 'ok'); descubrimientoLote(ctx, id);
    };
    $('#de-descartar').onclick = async () => { await api.post(`/descubrimiento/${id}/descartar`); ctx.ir('descubrimiento'); };
  }
  if ($('#de-deshacer')) $('#de-deshacer').onclick = async () => {
    if (!await confirmar('Deshacer el lote', 'Se quitan las empresas provisorias que creó y los datos que agregó.', 'Deshacer', 'btn-danger')) return;
    const d = await api.post(`/descubrimiento/${id}/deshacer`);
    toast(`Deshecho: ${d.provisorias_anuladas} provisorias anuladas`, 'ok'); descubrimientoLote(ctx, id);
  };
}

// ── B1 · Configuración → Enriquecimiento (dentro de la pantalla Configuración) ──
const PROV = [['google_places', 'Google Places'], ['brave', 'Brave Search'], ['claude', 'Claude']];

export function tarjetaEnriquecimiento(p, dominios, estado, editable) {
  const dis = editable ? '' : 'disabled';
  const n = (id, label, v, extra = '', hint = '') => `<div class="form-group"><label>${label}</label><input type="number" id="en-${id}" value="${esc(v)}" ${extra} ${dis} />${hint ? `<div class="field-hint">${hint}</div>` : ''}</div>`;
  return card('Enriquecimiento', `<p class="small muted mb">Proveedores, precios y topes del enriquecimiento bajo demanda. Las claves van a Secret Manager y no se vuelven a mostrar;
      el resto se guarda con «Guardar nueva versión». Un proveedor sin clave aparece como «no configurado» y la cascada lo saltea.</p>
    ${tabla([{ t: 'Proveedor', k: 'n' }, { t: 'Estado', f: x => est(x.e.estado === 'activo' ? 'ok' : x.e.estado === 'desactivado' ? 'pendiente' : 'error', x.e.estado)
        + (x.e.fecha ? `<div class="small muted">clave del ${esc(fechaHora(x.e.fecha))} · ${esc(x.e.por || '')}</div>` : '') },
      { t: 'Activo', f: x => `<label class="check"><input type="checkbox" id="en-act-${x.k}" ${p[`${x.k}_activo`] ? 'checked' : ''} ${dis} /> usar</label>` },
      { t: 'Clave', f: x => editable ? `<div class="toolbar"><input type="password" id="en-clave-${x.k}" placeholder="pegá la clave" autocomplete="off" style="width:200px" />
        <button class="btn btn-outline btn-sm" data-clave="${x.k}">Guardar clave</button></div>` : '' }],
      PROV.map(([k, n]) => ({ k, n, e: estado[k] })))}
    <div class="form-row mt">${n('places', 'Places Text Search (US$ por llamada)', p.precio_places, 'step="0.001" min="0"')}
      ${n('gratis', 'Llamadas gratis de Places por mes', p.places_gratis_mes, 'min="0"')}
      ${n('brave', 'Brave Search (US$ por búsqueda)', p.precio_brave, 'step="0.001" min="0"')}</div>
    <div class="form-row"><div class="form-group"><label>Modelo de Claude</label><input type="text" id="en-modelo" value="${esc(p.modelo_claude)}" ${dis} /></div>
      ${n('cin', 'Claude: US$ por millón de tokens de entrada', p.precio_claude_entrada, 'step="0.01" min="0"')}
      ${n('cout', 'Claude: US$ por millón de tokens de salida', p.precio_claude_salida, 'step="0.01" min="0"')}</div>
    <div class="form-row"><div class="form-group"><label class="check"><input type="checkbox" id="en-act-claude_web" ${p.claude_web_activo ? 'checked' : ''} ${dis} /> <strong>Búsqueda web con Claude</strong></label>
        <div class="field-hint">Último paso, solo para las empresas que siguen sin teléfono. Usa la clave de Claude. Solo entran los teléfonos que aparecen en la página que Claude cita.</div></div>
      ${n('web-busq', 'Búsquedas máximas por empresa', p.claude_web_busquedas, 'min="1" max="10"')}
      ${n('web-precio', 'Precio por búsqueda (US$)', p.precio_busqueda_web, 'step="0.001" min="0"', 'US$10 cada 1.000 búsquedas. Los tokens se cobran con los precios de Claude.')}</div>
    <div class="form-row">${n('mes', 'Tope mensual duro (US$)', p.tope_mensual, 'step="1" min="0"')}
      ${n('corrida', 'Tope por corrida (US$)', p.tope_corrida, 'step="1" min="0"')}
      ${n('max', 'Máximo de empresas por corrida', p.max_empresas_corrida, 'min="1"')}</div>
    <div class="form-row">${n('conf', 'Confianza de los datos enriquecidos', p.confianza, 'min="1" max="100"', 'Cargas 50, sala 80: con 30 nunca pisan datos de mejor fuente.')}
      ${n('dias', 'No volver a enriquecer antes de (días)', p.dias_sin_reenriquecer, 'min="0"')}
      <div class="form-group"><label>La cascada se corta</label><select class="fselect" id="en-corte" ${dis}>
        <option value="telefono" ${p.corte === 'telefono' ? 'selected' : ''}>Apenas consigue un teléfono (más barato)</option>
        <option value="telefono_y_web" ${p.corte === 'telefono_y_web' ? 'selected' : ''}>Cuando tiene teléfono y sitio web</option></select></div></div>
    <div class="form-group"><label>Dominios que no cuentan como «mismo sitio» en los posibles duplicados</label>
      <textarea class="finput code" id="en-genericos" rows="3" ${dis}>${esc(dominios.join(', '))}</textarea><div class="field-hint">Separados por coma (gmail.com, facebook.com…).</div></div>`);
}

export function leerEnriquecimiento(p) {
  if (!$('#en-places')) return {};
  const f = (id) => +$('#en-' + id).value;
  return {
    enriquecimiento: { ...p.enriquecimiento, google_places_activo: $('#en-act-google_places').checked, brave_activo: $('#en-act-brave').checked,
      claude_activo: $('#en-act-claude').checked, precio_places: f('places'), places_gratis_mes: f('gratis'), precio_brave: f('brave'),
      modelo_claude: $('#en-modelo').value.trim(), precio_claude_entrada: f('cin'), precio_claude_salida: f('cout'), tope_mensual: f('mes'),
      tope_corrida: f('corrida'), max_empresas_corrida: f('max'), confianza: f('conf'), dias_sin_reenriquecer: f('dias'), corte: $('#en-corte').value,
      claude_web_activo: $('#en-act-claude_web').checked, claude_web_busquedas: f('web-busq'), precio_busqueda_web: f('web-precio') },
    dominios_genericos: $('#en-genericos').value.split(',').map(s => s.trim().toLowerCase()).filter(Boolean),
  };
}

export function activarEnriquecimiento(recargar) {
  $$('[data-clave]').forEach(b => b.onclick = async () => {
    const inp = $('#en-clave-' + b.dataset.clave);
    if (!inp.value.trim()) return toast('Pegá la clave', 'err');
    await api.put('/config/enriquecimiento/clave', { proveedor: b.dataset.clave, clave: inp.value });
    inp.value = '';
    toast('Clave guardada en Secret Manager', 'ok'); recargar();
  });
}
