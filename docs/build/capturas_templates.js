// Capturas de SPEC_templates_sorteo_sin_telefono_formatos_csv para el manual (guías 7, 10 y 25).
// Requiere la API en modo dev con la demo recién cargada, sin templates (ver docs/build/README.md):
//   BASE=http://localhost:8080 node docs/build/capturas_templates.js docs/manual/img
// Genera 16-nueva-muestra, 33-atributos, 53-templates, 54-asistente-filtros y 55-formatos-csv.
const { chromium } = require('playwright');
const OUT = process.argv[2], BASE = process.env.BASE || 'http://localhost:8080';

// Círculos numerados sobre la pantalla, para los pasos del manual
async function marcar(p, marcas) {
  await p.evaluate((marcas) => {
    document.querySelectorAll('.marca-manual').forEach(m => m.remove());
    for (const [sel, n, dx = -14, dy = -14] of marcas) {
      const el = document.querySelector(sel);
      if (!el) continue;
      const r = el.getBoundingClientRect();
      const m = document.createElement('div');
      m.className = 'marca-manual';
      m.textContent = n;
      Object.assign(m.style, { position: 'absolute', left: `${r.left + window.scrollX + dx}px`, top: `${r.top + window.scrollY + dy}px`,
        width: '26px', height: '26px', borderRadius: '50%', background: '#E96436', color: '#fff', font: '700 14px Montserrat, sans-serif',
        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999, boxShadow: '0 1px 4px rgba(0,0,0,.35)' });
      document.body.appendChild(m);
    }
  }, marcas);
}

(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1360, height: 1100 }, deviceScaleFactor: 1.5, locale: 'es-UY' });
  const w = (ms = 900) => p.waitForTimeout(ms);
  const ir = async (ruta, ms = 1500) => {
    await p.evaluate(() => { document.querySelectorAll('.modal-backdrop').forEach(m => m.remove());
      document.getElementById('toast-wrap')?.replaceChildren(); });
    await p.goto(`${BASE}/#/inicio`); await w(500);
    await p.goto(`${BASE}/#/${ruta}`); await w(ms);
  };
  await p.route('**/js/config.js', r => r.fulfill({ contentType: 'application/javascript',
    body: 'window.APP_CONFIG = { firebaseConfig: {}, authMode: "dev", apiBase: "/api", tz: "America/Montevideo" };' }));
  await p.goto(BASE); await w(600);
  await p.fill('#login-user', 'jefe@equipos.com.uy'); await p.click('#login-btn'); await w(1200);

  // 54 · Asistente: filtros con cualquier dato y estratos por tramos
  await ir('estudios/1/nueva-muestra');
  await p.selectOption('#m-add-filtro', 'departamento'); await w(300);
  await p.click('[data-chips="f:departamento"] .chip >> text=Montevideo');
  await p.click('[data-chips="f:departamento"] .chip >> text=Canelones');
  await p.selectOption('#m-add-filtro', 'atributo.exporta'); await w(300);
  await p.click('[data-chips="f:atributo.exporta"] .chip >> text=Sí');
  await p.check('#m-sintel');
  await p.selectOption('#m-add-estrato', 'tamano'); await w(300);
  await p.selectOption('#m-add-estrato', 'atributo.empleados'); await w(300);
  await p.fill('[data-cortes="atributo.empleados"]', '1, 20, 100');
  await p.click('#m-marco'); await w(1800);
  await p.fill('#m-n-todos', '2'); await p.fill('#m-r-todos', '1'); await p.click('#m-aplicar'); await w(300);
  await marcar(p, [['#m-add-filtro', 1, -32, 8], ['[data-chips="origenes"]', 2, -32, 0], ['#m-sintel', 3, -34, -4],
                   ['[data-cortes="atributo.empleados"]', 4, -32, 12], ['#m-marco', 5, -32, 8]]);
  // Las marcas quedan a la izquierda de las tarjetas: se agranda el recorte
  const caja = await p.locator('.grid-2').first().boundingBox();
  await p.screenshot({ path: `${OUT}/54-asistente-filtros.png`, fullPage: true,
    clip: { x: caja.x - 30, y: caja.y - 6, width: caja.width + 36, height: caja.height + 12 } });
  await marcar(p, []);

  // Guardar como template
  await p.click('#m-guardar-t'); await w(400);
  await p.fill('#t-nombre', 'Exportadoras de Montevideo y Canelones');
  await p.fill('#t-desc', 'Tamaño × tramos de empleados; incluye sin teléfono');
  await p.click('.modal-foot .btn-orange'); await w(900);

  // 53 · Templates de sorteo
  await ir('templates');
  await p.screenshot({ path: `${OUT}/53-templates.png`, clip: { x: 240, y: 0, width: 1120, height: 520 } });

  // 16 · Nueva muestra partiendo del template
  await ir('estudios/1/nueva-muestra');
  const opt = await p.$$eval('#m-template option', os => os.map(o => o.value).filter(Boolean));
  await p.selectOption('#m-template', opt[0]); await w(2500);
  await p.fill('#m-nombre', 'Ola 2 · exportadoras');
  const alto = await p.evaluate(() => document.documentElement.scrollHeight);
  await p.screenshot({ path: `${OUT}/16-nueva-muestra.png`, fullPage: true, clip: { x: 240, y: 0, width: 1120, height: alto } });

  // 55 · Formatos del CSV
  await ir('muestras/1', 1800);
  await p.locator('.card', { hasText: 'Exportar a uContact' }).screenshot({ path: `${OUT}/55-formatos-csv.png` });

  // 33 · Atributos, ya sin las columnas «filtro» y «estrato» (como administrador)
  const a = await b.newPage({ viewport: { width: 1360, height: 1100 }, deviceScaleFactor: 1.5, locale: 'es-UY' });
  await a.route('**/js/config.js', r => r.fulfill({ contentType: 'application/javascript',
    body: 'window.APP_CONFIG = { firebaseConfig: {}, authMode: "dev", apiBase: "/api", tz: "America/Montevideo" };' }));
  await a.goto(BASE); await a.waitForTimeout(600);
  await a.evaluate(() => localStorage.clear());
  await a.goto(BASE); await a.waitForTimeout(600);
  await a.fill('#login-user', 'admin@equipos.com.uy'); await a.click('#login-btn'); await a.waitForTimeout(1200);
  await a.goto(`${BASE}/#/atributos`); await a.waitForTimeout(1200);
  await marcar(a, [['#at-nuevo', 1, -30, -6], ['[data-at-editar]', 2, -30, -6]]);
  await a.screenshot({ path: `${OUT}/33-atributos.png`, clip: { x: 240, y: 0, width: 1120, height: 760 } });
  await b.close();
})();
