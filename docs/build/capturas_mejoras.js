// Capturas de SPEC_mejoras_sav_contactos_atributos_identidad para el manual (guías 19 a 24).
// Requiere la API en modo dev con la demo recién cargada (ver docs/build/README.md):
//   BASE=http://localhost:8080 node docs/build/capturas_mejoras.js docs/manual/img
const { chromium } = require('playwright');
const fs = require('fs');
const os = require('os');
const path = require('path');
const OUT = process.argv[2], BASE = process.env.BASE || 'http://localhost:8080';

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'capturas-'));
const SIN_RUT = path.join(tmp, 'directorio_sin_rut.csv');
fs.writeFileSync(SIN_RUT, 'Razón social;Teléfono;Departamento;Dirección\nCLINICA COLONIA;2477 0001;Colonia;Gral. Flores 120\n' +
  'Hotel Norte S.A.;2477 0002;Montevideo;Rambla 4500\nAlmacén Don Pepe;2477 0003;Canelones;Ruta 8 km 30\n' +
  'Taller Mecánico Sur;2477 0004;Montevideo;Garibaldi 2200\nPanadería La Espiga;2477 0005;Salto;Uruguay 800\n');
const PARECIDA = path.join(tmp, 'camara_comercio.csv');
fs.writeFileSync(PARECIDA, 'RUT;Razón social;Cant. Empleados;Exportadora\n212003150018;Clínica Colonia SA;40;SI\n');

(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1360, height: 1000 }, deviceScaleFactor: 1.5, locale: 'es-UY' });
  const w = (ms = 900) => p.waitForTimeout(ms);
  p.on('dialog', d => d.accept());
  await p.route('**/js/config.js', r => r.fulfill({ contentType: 'application/javascript',
    body: 'window.APP_CONFIG = { firebaseConfig: {}, authMode: "dev", apiBase: "/api", tz: "America/Montevideo" };' }));
  const entrar = async (email) => {
    await p.goto(BASE); await w(600);
    await p.evaluate(() => localStorage.clear());
    await p.goto(BASE); await w(600);
    if (await p.$('#login-user')) { await p.fill('#login-user', email); await p.click('#login-btn'); await w(1200); }
  };
  await entrar('admin@equipos.com.uy');
  const H = { 'X-Dev-User': 'admin@equipos.com.uy' };
  // Atributo de contacto para las capturas
  await p.evaluate(async (H) => {
    await fetch('/api/atributos', { method: 'POST', headers: { ...H, 'Content-Type': 'application/json' },
      body: JSON.stringify({ nombre: 'Decisor', tipo: 'lista', opciones: ['Sí', 'No'], ambito: 'contacto' }) });
  }, H);
  const rut = await p.evaluate(async (H) => {
    const m = await (await fetch('/api/muestras/1/items?por_pagina=200&estado=completa', { headers: H })).json();
    for (const it of m.items) {
      const f = await (await fetch('/api/empresas/' + it.rut, { headers: H })).json();
      if (f.contactos.some(c => c.telefonos.length)) return it.rut;
    }
    return m.items[0].rut;
  }, H);

  // 44 · Línea de tiempo con la ingesta agrupada
  await p.goto(`${BASE}/#/empresas/${rut}?tab=tiempo`); await w(1500);
  await p.click('details.tl-grupo summary'); await w(300);
  await p.locator('#f-tab .card').screenshot({ path: `${OUT}/44-linea-tiempo-ingesta.png` });
  // 45 · Empresas de la muestra
  await p.goto(`${BASE}/#/muestras/1`); await w(1800);
  await p.selectOption('#mu-rol', 'titular'); await w(800);
  await p.locator('.card', { hasText: 'Empresas de la muestra' }).screenshot({ path: `${OUT}/45-empresas-muestra.png` });
  // 51 · Qué incluir
  await p.click('#mu-incluir summary'); await w(400);
  await p.locator('.card', { hasText: 'Exportar a uContact' }).screenshot({ path: `${OUT}/51-que-incluir.png` });
  // 46 · Agregar un contacto
  await p.goto(`${BASE}/#/empresas/${rut}?tab=contactos`); await w(1500);
  await p.click('#c-agregar'); await w(600);
  await p.fill('#ct-nombre', 'Lucía Fernández'); await p.fill('#ct-cargo', 'Jefa de RRHH'); await p.fill('#ct-email', 'lucia@empresa.com.uy');
  await p.check('[data-ct-tel] >> nth=0'); await p.selectOption('[data-ct-attr="decisor"]', 'Sí');
  await p.locator('.modal-box').screenshot({ path: `${OUT}/46-contacto-form.png` });
  await p.click('.modal-foot .btn-outline'); await w(300);
  // 52 · Detalle de la ingesta: motivos por fila
  await p.goto(`${BASE}/#/sav/1`); await w(1500);
  await p.locator('.card', { hasText: 'Lo que no se aplicó' }).screenshot({ path: `${OUT}/52-ingesta-motivos.png` });
  // 50 · Sugerencia de atributo parecido
  await p.goto(`${BASE}/#/cargas/nueva`); await w();
  await p.setInputFiles('#c-arch', PARECIDA); await p.fill('#c-tipo', 'cámara de comercio'); await p.click('#c-analizar'); await w(1600);
  await p.locator('#c-parecidos .alert').screenshot({ path: `${OUT}/50-sugerencia-atributo.png` });
  // 48 · Destino y reglas · 49 · Coincidencias a decidir · 47 · Base provisoria
  await p.goto(`${BASE}/#/cargas/nueva`); await w();
  await p.setInputFiles('#c-arch', SIN_RUT); await p.fill('#c-tipo', 'directorio sin RUT'); await p.click('#c-analizar'); await w(1600);
  await p.selectOption('#c-destino', 'provisoria'); await p.click('#c-rg-add'); await w(400);
  await p.locator('.grid-2 > div', { has: p.locator('#c-destino') }).screenshot({ path: `${OUT}/48-destino-reglas.png` });
  await p.selectOption('#c-origen-defecto', { index: 1 }); await p.fill('#c-licencia', 'uso interno');
  await p.click('#c-siguiente'); await w(3000);
  if (await p.$('#c-preview')) { await p.click('#c-preview'); await w(3000); }
  await p.locator('#c-coinc .card').screenshot({ path: `${OUT}/49-coincidencias.png` });
  await p.click('#cc-95'); await w(900);
  await p.click('#c-confirmar'); await w(600);
  const ok = await p.$('.modal-foot .btn-green, .modal-foot .btn-orange'); if (ok) await ok.click();
  await w(3000);
  await p.goto(`${BASE}/#/provisorias`); await w(2000);
  await p.screenshot({ path: `${OUT}/47-base-provisoria.png`, clip: { x: 240, y: 0, width: 1120, height: 760 } });
  await b.close();
  fs.rmSync(tmp, { recursive: true, force: true });
})();
