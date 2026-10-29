// ════════════════════════════════════════════════════════════════
//  Base de Empresas — shell: login, navegación por rol y ruteo
// ════════════════════════════════════════════════════════════════
import * as api from './api.js';
import { $, $$, esc, initials, toast, main, cargando, errorEn } from './ui.js';
import * as base from './vistas/base.js';
import * as cargas from './vistas/cargas.js';
import * as estudios from './vistas/estudios.js';
import * as campo from './vistas/campo.js';
import * as admin from './vistas/admin.js';

const CFG = window.APP_CONFIG || {};
const S = { me: null, auth: null, fb: null };
const ROL_NOMBRE = { admin: 'Administrador/a', steward: 'Data steward', jefe: 'Jefe/a de proyecto', coordinador: 'Coordinador/a de campo', lectura: 'Lectura' };

// Secciones del menú: [ruta, ícono, título, roles que la ven (vacío = todos)]
const MENU = [
  ['General', [['inicio', '🏠', 'Inicio'], ['empresas', '🏢', 'Empresas']]],
  ['Base de datos', [['cargas', '📥', 'Cargas', ['steward']], ['intermediarios', '☎️', 'Intermediarios', ['steward']],
    ['revision', '🔀', 'Revisión de fusiones', ['steward']]]],
  ['Estudios', [['estudios', '📋', 'Estudios y muestras', ['jefe', 'coordinador']]]],
  ['Campo', [['sav', '📊', 'Ingesta .sav', ['coordinador']], ['conciliacion', '🧩', 'Conciliación', ['coordinador']],
    ['actividad', '📈', 'Actividad', ['coordinador', 'jefe']]]],
  ['Administración', [['config', '⚙️', 'Configuración', ['admin']], ['naturalezas', '⚖️', 'Naturalezas jurídicas', ['admin', 'steward']],
    ['no-llamar', '🚫', 'No llamar', ['admin', 'steward']], ['usuarios', '👥', 'Usuarios', ['admin']],
    ['auditoria', '🔎', 'Auditoría', ['admin', 'steward']]]],
];

const RUTAS = [
  [/^inicio$/, base.inicio], [/^empresas$/, base.empresas], [/^empresas\/(\d{12})$/, base.ficha],
  [/^cargas$/, cargas.lista], [/^cargas\/nueva$/, cargas.nueva], [/^cargas\/(\d+)$/, cargas.detalle],
  [/^intermediarios$/, cargas.intermediarios], [/^revision$/, cargas.revision],
  [/^estudios$/, estudios.lista], [/^estudios\/(\d+)$/, estudios.detalle], [/^estudios\/(\d+)\/nueva-muestra$/, estudios.nuevaMuestra],
  [/^muestras\/(\d+)$/, estudios.muestra],
  [/^sav$/, campo.sav], [/^sav\/(\d+)$/, campo.savDetalle], [/^conciliacion$/, campo.conciliacion], [/^actividad$/, campo.actividad],
  [/^config$/, admin.config], [/^naturalezas$/, admin.naturalezas], [/^no-llamar$/, admin.noLlamar],
  [/^usuarios$/, admin.usuarios], [/^auditoria$/, admin.auditoria],
];

export const ctx = {
  get me() { return S.me; },
  puede: (...roles) => S.me && (S.me.rol === 'admin' || roles.includes(S.me.rol)),
  ir: (ruta) => { location.hash = '#/' + ruta; },
};

// ── Arranque ──
async function iniciar() {
  if (CFG.authMode === 'dev') {
    if (!localStorage.getItem('devUser')) return renderLogin();
    return entrar();
  }
  const fc = CFG.firebaseConfig || {};
  if (!fc.apiKey || fc.apiKey === 'TU_API_KEY') {
    document.getElementById('app').innerHTML = `<div class="center-screen"><div class="info-card"><div class="ic-icon">⚙️</div>
      <h2>Falta configurar Firebase</h2><p>Completá <code>web/public/js/config.js</code> con la configuración web de tu proyecto Firebase.</p></div></div>`;
    return;
  }
  const { initializeApp } = await import('https://www.gstatic.com/firebasejs/10.7.0/firebase-app.js');
  S.fb = await import('https://www.gstatic.com/firebasejs/10.7.0/firebase-auth.js');
  S.auth = S.fb.getAuth(initializeApp(fc));
  api.setTokenProvider(async () => S.auth.currentUser ? S.auth.currentUser.getIdToken() : null);
  S.fb.onAuthStateChanged(S.auth, (u) => u ? entrar() : renderLogin());
}

async function entrar() {
  try {
    S.me = await api.get('/me');
  } catch (e) {
    renderLogin(e.status === 403 ? e.message : `No se pudo conectar con la API: ${e.message}`);
    if (CFG.authMode === 'dev') localStorage.removeItem('devUser');
    else if (S.auth) S.fb.signOut(S.auth);
    return;
  }
  renderShell();
  window.onhashchange = rutear;
  rutear();
}

function renderLogin(error) {
  const dev = CFG.authMode === 'dev';
  document.getElementById('app').innerHTML = `
  <div class="login-wrap">
    <div class="login-brand">
      <div class="login-brand-inner">
        <div class="login-brand-logo"><img src="img/isotipo.png" alt="Equipos Consultores" /></div>
        <div class="tagline"><em>Base</em><em>de empresas</em></div>
        <div class="tagline-sub">Registro maestro por RUT · muestras auditables · resultados de campo</div>
      </div>
    </div>
    <div class="login-form-panel">
      <div class="login-form-inner">
        <div class="accent-bar"></div>
        <h1>Bienvenido/a</h1>
        <p class="login-sub">${dev ? 'Modo desarrollo: ingresá con el email de un usuario registrado' : 'Ingresá con tu cuenta de Equipos'}</p>
        <div id="login-alert" class="${error ? 'alert alert-error' : 'hidden'}">${esc(error || '')}</div>
        <div class="form-group"><label>Email</label><input type="email" id="login-user" placeholder="nombre@equipos.com.uy" autocomplete="username" /></div>
        ${dev ? '' : `<div class="form-group"><label>Clave</label><input type="password" id="login-pass" placeholder="••••••••" autocomplete="current-password" /></div>`}
        <button class="btn btn-orange btn-full" id="login-btn">Ingresar</button>
        ${dev ? '' : `<p class="login-forgot"><a id="login-forgot">¿Olvidaste tu contraseña?</a></p>`}
      </div>
    </div>
  </div>`;
  const alerta = (m, cls = 'alert-error') => { const a = $('#login-alert'); a.className = 'alert ' + cls; a.textContent = m; };
  const ingresar = async () => {
    const email = $('#login-user').value.trim().toLowerCase();
    if (!email) return alerta('Ingresá tu email');
    if (dev) { localStorage.setItem('devUser', email); return entrar(); }
    try {
      $('#login-btn').disabled = true;
      await S.fb.signInWithEmailAndPassword(S.auth, email, $('#login-pass').value);
    } catch (e) {
      alerta(/invalid|wrong|not-found|credential/.test(e.code || '') ? 'Email o clave incorrectos' : e.message);
    } finally { $('#login-btn').disabled = false; }
  };
  $('#login-btn').onclick = ingresar;
  $$('#login-user, #login-pass').forEach(i => i.addEventListener('keydown', e => { if (e.key === 'Enter') ingresar(); }));
  const olvido = $('#login-forgot');
  if (olvido) olvido.onclick = async (e) => {
    e.preventDefault();
    const email = $('#login-user').value.trim();
    if (!email) return alerta('Escribí tu email y volvé a tocar el enlace');
    try { await S.fb.sendPasswordResetEmail(S.auth, email); alerta('Te enviamos un correo para restablecer la clave', 'alert-success'); }
    catch (err) { alerta(err.message); }
  };
}

function renderShell() {
  const me = S.me;
  const secciones = MENU.map(([titulo, items]) => {
    // El rol lectura ve las pantallas de consulta, sin acciones
    const LECTURA = ['estudios', 'actividad', 'intermediarios', 'naturalezas', 'no-llamar'];
    const filtrados = items.filter(([ruta, , , roles]) => !roles || ctx.puede(...roles) || (me.rol === 'lectura' && LECTURA.includes(ruta)));
    if (!filtrados.length) return '';
    return `<div class="sidebar-section-label">${esc(titulo)}</div>` + filtrados.map(([ruta, icono, texto]) =>
      `<button class="nav-item" data-ruta="${ruta}"><span class="nav-icon">${icono}</span>${esc(texto)}<span class="nav-count hidden" data-count="${ruta}"></span></button>`).join('');
  }).join('');
  document.getElementById('app').innerHTML = `
  <div class="app">
    <aside class="sidebar">
      <div class="sidebar-top"><img class="logo-horizontal-white" src="img/logo-horizontal-blanco.png" alt="Equipos Consultores" />
        <div class="app-subtitle">Base de empresas</div></div>
      <nav id="nav">${secciones}</nav>
      <div class="sidebar-footer">
        <div class="user-pill">
          <div class="user-avatar">${esc(initials(me.nombre, me.email))}</div>
          <div class="user-info-wrap"><div class="user-email">${esc(me.nombre || me.email)}</div><div class="user-role">${esc(ROL_NOMBRE[me.rol] || me.rol)}</div></div>
        </div>
        <button class="btn btn-outline btn-full btn-sm" id="logout" style="border-color:rgba(255,255,255,0.2); color:rgba(255,255,255,0.85);">Cerrar sesión</button>
      </div>
    </aside>
    <main class="main" id="main"></main>
  </div>`;
  $('#logout').onclick = async () => {
    if (CFG.authMode === 'dev') { localStorage.removeItem('devUser'); location.hash = ''; return renderLogin(); }
    await S.fb.signOut(S.auth);
  };
  $$('#nav .nav-item').forEach(b => b.onclick = () => ctx.ir(b.dataset.ruta));
  actualizarContadores();
}

export async function actualizarContadores() {
  try {
    const r = await api.get('/inicio');
    const pon = (ruta, n) => { const el = document.querySelector(`[data-count="${ruta}"]`); if (el) { el.textContent = n; el.classList.toggle('hidden', !n); } };
    pon('intermediarios', r.sospechosos); pon('revision', r.revision); pon('conciliacion', r.conciliacion);
  } catch { /* el contador es accesorio */ }
}

async function rutear() {
  const ruta = (location.hash || '#/inicio').replace(/^#\/?/, '') || 'inicio';
  const [path, query] = ruta.split('?');
  const raiz = path.split('/')[0];
  $$('#nav .nav-item').forEach(b => b.classList.toggle('active', b.dataset.ruta === raiz || (raiz === 'muestras' && b.dataset.ruta === 'estudios')));
  for (const [re, vista] of RUTAS) {
    const m = path.match(re);
    if (m) {
      cargando();
      window.scrollTo(0, 0);
      try { await vista(ctx, ...m.slice(1), new URLSearchParams(query || '')); }
      catch (e) { console.error(e); errorEn(main(), e); }
      return;
    }
  }
  ctx.ir('inicio');
}

iniciar().catch(e => { console.error(e); toast(e.message, 'err'); });
