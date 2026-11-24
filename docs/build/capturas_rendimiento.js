// Capturas de SPEC_rendimiento_base_grande (D55): Empresas con el total y la paginación por clave, Inicio con la fecha
// de los contadores, Configuración → Rendimiento de la base y la franja de carga en curso.
//   BASE=http://localhost:8080 node docs/build/capturas_rendimiento.js docs/manual/img
// Para la franja, la captura 72 simula /api/estado con una carga en el lote 12 de 39.
const { chromium } = require('playwright');
const OUT = process.argv[2], BASE = process.env.BASE || 'http://localhost:8080';

(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1360, height: 1000 }, deviceScaleFactor: 1.5, locale: 'es-UY' });
  const errores = [];
  p.on('pageerror', e => errores.push(e.message));
  p.on('console', m => { if (m.type() === 'error') errores.push(m.text()); });
  const w = (ms = 900) => p.waitForTimeout(ms);
  const ir = async (ruta, ms = 1500) => { await p.goto(`${BASE}/#/inicio`); await w(400); await p.goto(`${BASE}/#/${ruta}`); await w(ms); };
  await p.route('**/js/config.js', r => r.fulfill({ contentType: 'application/javascript',
    body: 'window.APP_CONFIG = { firebaseConfig: {}, authMode: "dev", apiBase: "/api", tz: "America/Montevideo" };' }));
  await p.goto(BASE); await w(600);
  await p.fill('#login-user', 'admin@equipos.com.uy'); await p.click('#login-btn'); await w(1200);

  // 69 · Empresas: total, «Contar exacto» y página siguiente
  await ir('empresas', 2000);
  console.log('total:', await p.textContent('#e-total'));
  await p.click('#p-sig'); await w(1200);
  console.log('página 2:', (await p.textContent('#e-total')).replace(/\s+/g, ' '));
  await p.locator('#e-total').locator('xpath=..').screenshot({ path: `${OUT}/69-empresas-paginas.png` });
  await p.click('#p-ant'); await w(1200);
  console.log('volvió a:', (await p.textContent('#e-total')).replace(/\s+/g, ' '));

  // 70 · Inicio con «Contadores actualizados hace …»
  await ir('inicio', 2000);
  console.log('inicio:', (await p.textContent('.card-body.small.muted')).replace(/\s+/g, ' ').slice(-90));
  await p.screenshot({ path: `${OUT}/70-inicio-contadores.png`, clip: { x: 240, y: 0, width: 1120, height: 680 } });

  // 71 · Configuración → Rendimiento de la base
  await ir('config', 2500);
  const tarjeta = p.locator('#c-rendimiento .card');
  console.log('rendimiento:', (await tarjeta.textContent()).replace(/\s+/g, ' ').slice(0, 200));
  await p.click('#c-recalcular'); await w(2500);
  await tarjeta.screenshot({ path: `${OUT}/71-config-rendimiento.png` });
  console.log('después de recalcular:', (await tarjeta.textContent()).replace(/\s+/g, ' ').slice(0, 120));

  // 72 · Franja de carga en curso (simulada)
  await p.route('**/api/estado', r => r.fulfill({ contentType: 'application/json', body: JSON.stringify({
    carga: { id: 12, operacion: 'confirmar', lote: 12, lotes: 39 }, disponibilidad_preparando: null, resumen: {} }) }));
  await ir('empresas', 2000);
  console.log('franja:', await p.textContent('#franja-estado'));
  await p.screenshot({ path: `${OUT}/72-franja-carga.png`, clip: { x: 0, y: 0, width: 1360, height: 260 } });
  console.log('errores:', errores);
  await b.close();
})();
