// Capturas de la pantalla Usuarios y del login para el manual (alta con enlace de acceso).
// Requiere la API en modo dev con la demo cargada y el SMTP apuntando a un puerto cerrado,
// para mostrar el caso "el correo no salió" (ver docs/build/README.md):
//   BASE=http://localhost:8080 node docs/build/capturas_usuarios.js docs/manual/img
const { chromium } = require('playwright');
const OUT = process.argv[2], BASE = process.env.BASE || 'http://localhost:8080';
const EMAIL = process.argv[3] || 'sofia.perez@equipos.com.uy';
// Login de producción con los módulos de Firebase simulados: todo intento da "cuenta deshabilitada"
const AUTH = `
export function getAuth() { return { currentUser: null }; }
export function onAuthStateChanged(a, cb) { cb(null); }
export async function signInWithEmailAndPassword() { const e = new Error('disabled'); e.code = 'auth/user-disabled'; throw e; }
export async function signOut() {}
export async function sendPasswordResetEmail() {}`;

async function usuarios(b) {
  const p = await b.newPage({ viewport: { width: 1280, height: 820 }, deviceScaleFactor: 1.5, locale: 'es-UY' });
  const espera = (ms = 1000) => p.waitForTimeout(ms);
  await p.route('**/js/config.js', r => r.fulfill({ contentType: 'application/javascript',
    body: 'window.APP_CONFIG = { firebaseConfig: {}, authMode: "dev", apiBase: "/api", tz: "America/Montevideo" };' }));
  await p.goto(BASE); await espera(800);
  await p.fill('#login-user', 'admin@equipos.com.uy'); await p.click('#login-btn'); await espera(1500);
  await p.goto(`${BASE}/#/usuarios`); await espera(1200);
  await p.click('#u-nuevo'); await espera(400);
  await p.fill('#u-e', EMAIL); await p.fill('#u-n', 'Sofía Pérez');
  await p.selectOption('#u-r', 'coordinador');
  await p.screenshot({ path: `${OUT}/30-usuario-alta.png` });
  await p.click('.modal-foot .btn-orange');
  await p.waitForSelector('#enl', { timeout: 30000 }); await espera(300);
  await p.screenshot({ path: `${OUT}/31-usuario-enlace.png` });
  await p.click('.modal-foot .btn-dark'); await espera(1200);
  await p.screenshot({ path: `${OUT}/27-usuarios.png` });
  await p.close();
}

async function login(b) {
  const p = await b.newPage({ viewport: { width: 1280, height: 820 }, deviceScaleFactor: 1.5, locale: 'es-UY' });
  await p.route('**/js/config.js', r => r.fulfill({ contentType: 'application/javascript',
    body: 'window.APP_CONFIG = { firebaseConfig: { apiKey: "x", projectId: "x" }, authMode: "firebase", apiBase: "/api", tz: "America/Montevideo" };' }));
  await p.route('https://www.gstatic.com/firebasejs/**/firebase-app.js', r => r.fulfill({ contentType: 'application/javascript', body: 'export function initializeApp() { return {}; }' }));
  await p.route('https://www.gstatic.com/firebasejs/**/firebase-auth.js', r => r.fulfill({ contentType: 'application/javascript', body: AUTH }));
  await p.goto(BASE); await p.waitForTimeout(1200);
  await p.screenshot({ path: `${OUT}/01-login.png` });
  await p.fill('#login-user', 'valentina.rodriguez@equipos.com.uy'); await p.fill('#login-pass', 'una-clave');
  await p.click('#login-btn'); await p.waitForTimeout(800);
  await p.screenshot({ path: `${OUT}/29-login-error.png` });
  await p.close();
}

(async () => {
  const b = await chromium.launch();
  await usuarios(b);
  await login(b);
  await b.close();
  console.log('📸 01-login, 27-usuarios, 29-login-error, 30-usuario-alta, 31-usuario-enlace');
})();
