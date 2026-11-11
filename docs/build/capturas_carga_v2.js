// Capturas de la carga v2 (atributos y origen del teléfono) para el manual: mapeo, traducción de
// valores, preview, atributos, orígenes, filtros de la muestra, exportación y rendimiento por origen.
// Requiere la API en modo dev con la demo cargada (api/demo/sembrar_demo.py) y un CSV de prueba con
// columnas Tel 1 / Origen 1 / Tel 2 / Origen 2 / Exporta / Cámara (ver docs/build/README.md):
//   BASE=http://localhost:8080 node docs/build/capturas_carga_v2.js docs/manual/img base_prueba.csv
// Cada captura lleva los números de las referencias del manual (círculos naranjas).
const { chromium } = require('playwright');
const OUT = process.argv[2], CSV = process.argv[3], BASE = process.env.BASE || 'http://localhost:8080';

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

async function foto(p, selector, nombre) {
  await p.locator(selector).first().screenshot({ path: `${OUT}/${nombre}.png` });
}

(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1360, height: 1000 }, deviceScaleFactor: 1.5, locale: 'es-UY' });
  const w = (ms = 900) => p.waitForTimeout(ms);
  await p.route('**/js/config.js', r => r.fulfill({ contentType: 'application/javascript',
    body: 'window.APP_CONFIG = { firebaseConfig: {}, authMode: "dev", apiBase: "/api", tz: "America/Montevideo" };' }));
  await p.goto(BASE); await w(600);
  await p.fill('#login-user', 'admin@equipos.com.uy'); await p.click('#login-btn'); await w(1200);
  // La tarjeta se recorta junto con las marcas: se agranda un poco el área
  const tarjeta = (sel) => `.card:has(${sel})`;

  // Guía 15: catálogos
  await p.goto(`${BASE}/#/atributos`); await w();
  await marcar(p, [['#at-nuevo', 1, -30, -6], ['[data-at-editar]', 2, -30, -6]]);
  await p.screenshot({ path: `${OUT}/33-atributos.png`, clip: { x: 240, y: 0, width: 1120, height: 760 } });
  await p.goto(`${BASE}/#/origenes`); await w();
  await marcar(p, [['#or-nuevo', 1, -30, -6], ['[data-or-subir]', 2, -30, -6]]);
  await p.screenshot({ path: `${OUT}/34-origenes.png`, clip: { x: 240, y: 0, width: 1120, height: 900 } });

  // Guía 3: mapeo, traducción y preview
  await p.goto(`${BASE}/#/cargas/nueva`); await w();
  await p.setInputFiles('#c-arch', CSV); await p.fill('#c-tipo', 'directorio de prueba'); await p.click('#c-analizar'); await w(1500);
  await p.selectOption('#c-origen-defecto', 'directorio_de_camara'); await p.fill('#c-licencia', 'uso interno');
  await p.locator('#c-paso2 .card').first().scrollIntoViewIfNeeded();
  await marcar(p, [['#c-bloques > .map-bloque:nth-child(1) h4', 1, -44, -6], ['#c-bloques > .map-bloque:nth-child(2) h4', 2, -44, -6],
    ['#c-bloques > .map-bloque:nth-child(3) h4', 3, -44, -6], ['#c-origen-defecto', 4, -44, 6], ['details.map-bloque summary', 5, -44, -4],
    ['.no-usadas', 6, -32, -4], ['#c-licencia', 7, -32, 6], ['#c-siguiente', 8, -32, 2]]);
  await foto(p, '#c-paso2 .card', '35-carga-mapeo');
  await p.click('#c-siguiente'); await w(1200);
  await marcar(p, [['[data-tr]', 1, -32, 6], ['#c-sugerencias', 2, -30, 2], ['#c-preview', 3, -30, 2]]);
  await foto(p, '#c-traduccion .card', '36-carga-traduccion');
  await p.click('#c-sugerencias'); await w(300);
  for (const s of await p.$$('[data-tr]')) { if (!(await s.inputValue())) await s.selectOption('__sin_dato'); }
  await p.click('#c-preview');
  await p.waitForURL(/#\/cargas\/\d+$/, { timeout: 30000 }); await w(1500);
  await marcar(p, [['.estado-explica', 1, -32, 0], ['.grid-2.mb .card', 2, -14, -14], ['.grid-2.mb .card:nth-child(2)', 3, -14, -14],
    ['#c-confirmar', 4, 0, -30], ['#c-descartar', 5, 0, -30]]);
  await p.screenshot({ path: `${OUT}/37-carga-preview.png`, clip: { x: 240, y: 0, width: 1120, height: 1000 } });

  // Guía 7: filtros de la muestra
  await p.goto(`${BASE}/#/estudios/1/nueva-muestra`); await w(1200);
  await p.fill('#ma-empleados-desde', '30');
  await p.click('[data-chips="origenes"] .chip >> text=Estudio anterior');
  await p.click('[data-chips="por"] .chip >> text=Exporta'); await p.click('#m-marco'); await w(1200);
  await p.locator('#ma-empleados-desde').scrollIntoViewIfNeeded();
  await marcar(p, [['#ma-empleados-desde', 1, -32, 8], ['[data-chips="origenes"]', 2, -32, 0], ['[data-chips="por"]', 3, -32, 0]]);
  await foto(p, '.grid-2', '38-muestra-filtros');

  // Guía 10: exportación por origen
  await p.goto(`${BASE}/#/muestras/1`); await w(1500);
  await marcar(p, [['[data-chips="exp-origenes"]', 1, -32, 0], ['#mu-orden', 2, -32, 8], ['#mu-csv-res', 3, -32, 0]]);
  await foto(p, tarjeta('#mu-csv'), '39-muestra-exportar');

  // Guía 11: rendimiento por origen
  await p.goto(`${BASE}/#/actividad`); await w(2000);
  await p.locator('#a-origenes .card').scrollIntoViewIfNeeded();
  await foto(p, '#a-origenes .card', '40-rendimiento-origen');
  await b.close();
})();
