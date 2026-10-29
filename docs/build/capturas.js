// Capturas de pantalla para el manual de usuario.
// Requiere la API corriendo en modo dev con la demo cargada (ver docs/build/README.md):
//   node docs/build/capturas.js http://localhost:8080 docs/manual/img <rut_ficha> <archivo.sav> <base.csv>
const { chromium } = require('playwright');

const [BASE, OUT, RUT, SAV, CSV] = process.argv.slice(2);
const W = 1280, H = 820;

(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 1.5, locale: 'es-UY', timezoneId: 'America/Montevideo' });
  const errores = [];
  p.on('pageerror', e => errores.push(e.message));
  const espera = (ms = 1200) => p.waitForTimeout(ms);
  const foto = async (nombre, { full = false, alto } = {}) => {
    const opts = { path: `${OUT}/${nombre}.png` };
    if (full) opts.fullPage = true;
    if (alto) opts.clip = { x: 0, y: 0, width: W, height: alto };
    if (alto) opts.fullPage = true;
    // En capturas altas el sidebar fijo quedaría flotando: se lo estira a todo el alto
    const estilo = (full || alto) ? await p.addStyleTag({ content: '.app{position:relative}.sidebar{position:absolute!important;top:0;bottom:0;height:auto!important}' }) : null;
    await p.screenshot(opts);
    if (estilo) await estilo.evaluate(e => e.remove());
    console.log('📸', nombre);
  };
  const ir = async (ruta, ms) => {
    await p.evaluate(() => document.querySelectorAll('.modal-backdrop').forEach(m => m.remove()));
    await p.goto(`${BASE}/#/${ruta}`); await espera(ms);
  };

  await p.goto(BASE);
  await espera(800);
  await foto('01-login');
  await p.fill('#login-user', 'admin@equipos.com.uy');
  await p.click('#login-btn');
  await espera(1500);
  await foto('02-inicio');

  await ir('empresas'); await foto('03-empresas');
  await ir(`empresas/${RUT}`); await foto('04-ficha-datos');
  await ir(`empresas/${RUT}?tab=historia`); await foto('05-ficha-historia', { alto: 1100 });
  await ir(`empresas/${RUT}?tab=telefonos`); await foto('06-ficha-telefonos');
  await ir(`empresas/${RUT}?tab=tiempo`); await foto('07-ficha-tiempo', { alto: 1100 });

  await ir('cargas'); await foto('08-cargas');
  await ir('cargas/nueva');
  await p.setInputFiles('#c-arch', CSV);
  await p.fill('#c-tipo', 'directorio de cámaras');
  await foto('09-carga-archivo');
  await p.click('#c-analizar');
  await espera(2000);
  await p.fill('#c-licencia', 'Convenio 2026, uso para investigación');
  await p.evaluate(() => document.querySelector('#c-paso2').scrollIntoView());
  await espera(300);
  await foto('10-carga-mapeo');
  await ir('cargas/3'); await foto('11-carga-preview', { alto: 1250 });
  await ir('intermediarios'); await foto('12-intermediarios');
  await ir('revision'); await foto('13-revision');

  await ir('estudios'); await foto('14-estudios');
  await ir('estudios/1'); await foto('15-estudio');
  await ir('estudios/1/nueva-muestra');
  await p.click('[data-chips="por"] .chip[data-v="tamano"]');
  await p.click('#m-marco');
  await espera(1500);
  await p.fill('#m-n-todos', '10'); await p.fill('#m-r-todos', '4'); await p.click('#m-aplicar');
  await foto('16-nueva-muestra', { alto: 1500 });
  await ir('muestras/1', 1800); await foto('17-muestra', { alto: 1350 });
  await p.click('[data-liberar]');
  await espera(500);
  await p.fill('#lb-m', 'Dos rechazos y una empresa cerrada');
  await foto('18-liberar');

  await ir('sav');
  const opciones = await p.$$eval('#s-parte option', os => os.map(o => o.value));
  await p.selectOption('#s-parte', opciones[opciones.length - 1]);
  await p.setInputFiles('#s-arch', SAV);
  await p.click('#s-analizar');
  await espera(2500);
  await p.evaluate(() => document.querySelector('#s-editor').scrollIntoView());
  await espera(300);
  await foto('19-sav-mapeo');
  await p.evaluate(() => document.querySelector('#s-conteos').scrollIntoView({ block: 'center' }));
  await espera(300);
  await foto('20-sav-conteos');
  await ir('sav/1'); await foto('21-sav-detalle');
  await ir('conciliacion?tipo=intento'); await foto('22-conciliacion');
  await ir('actividad', 1800); await foto('23-actividad', { alto: 1300 });

  await ir('config'); await foto('24-config', { alto: 1500 });
  await ir('naturalezas'); await foto('25-naturalezas');
  await ir('no-llamar'); await foto('26-no-llamar');
  await ir('usuarios'); await foto('27-usuarios');
  await ir('auditoria'); await foto('28-auditoria');

  if (errores.length) console.error('Errores en la página:\n' + errores.join('\n'));
  await b.close();
})();
