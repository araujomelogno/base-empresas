// Captura de la tarjeta "CDR — conexión a la base de uContact" (Configuración) para el manual.
// Requiere la API en modo dev con la demo cargada (ver docs/build/README.md). Como en local no hay
// un MySQL de uContact, la respuesta de "Probar conexión" se simula con un resultado exitoso:
//   BASE=http://localhost:8080 node docs/build/capturas_cdr.js docs/manual/img
const { chromium } = require('playwright');
const OUT = process.argv[2], BASE = process.env.BASE || 'http://localhost:8080';
const PRUEBA = {
  ok: true, version: '8.0.36', tls: true, filas: 5, faltan: [],
  columnas: ['uniqueid', 'calldate', 'src', 'dst', 'duration', 'billsec', 'disposition', 'userfield', 'peeraccount', 'accountcode'],
  mensaje: 'Conectó. 5 llamadas de las últimas 24 horas en la muestra.',
};

(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 1.5, locale: 'es-UY' });
  await p.route('**/js/config.js', r => r.fulfill({ contentType: 'application/javascript',
    body: 'window.APP_CONFIG = { firebaseConfig: {}, authMode: "dev", apiBase: "/api", tz: "America/Montevideo" };' }));
  await p.route('**/api/config/cdr/probar', r => r.fulfill({ contentType: 'application/json', body: JSON.stringify(PRUEBA) }));
  await p.goto(BASE); await p.waitForTimeout(800);
  await p.fill('#login-user', 'admin@equipos.com.uy'); await p.click('#login-btn'); await p.waitForTimeout(1500);
  await p.goto(`${BASE}/#/config`); await p.waitForSelector('#cd-host'); await p.waitForTimeout(800);
  await p.fill('#cd-host', 'cdr.ucontact.equipos.com.uy'); await p.fill('#cd-base', 'uc'); await p.fill('#cd-usuario', 'lector_cdr');
  await p.click('#cd-probar'); await p.waitForSelector('#cd-prueba .alert'); await p.waitForTimeout(300);
  const tarjeta = p.locator('.card', { has: p.locator('#cd-host') });
  await tarjeta.scrollIntoViewIfNeeded();
  await tarjeta.screenshot({ path: `${OUT}/32-config-cdr.png` });
  await b.close();
})();
