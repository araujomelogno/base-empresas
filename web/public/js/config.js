// ══════════════════════════════════════════════════════════════════
//  CONFIGURACIÓN DE LA WEB
//  Reemplazá firebaseConfig por la de TU proyecto Firebase
//  (Consola Firebase → Configuración del proyecto → Tus apps → Web).
//  Estas claves son públicas por diseño; el acceso lo controla la API.
// ══════════════════════════════════════════════════════════════════
window.APP_CONFIG = {
  firebaseConfig: {
    apiKey: "TU_API_KEY",
    authDomain: "TU_PROYECTO.firebaseapp.com",
    projectId: "TU_PROYECTO",
    appId: "TU_APP_ID",
  },
  // "firebase" en producción. "dev" solo para desarrollo local: se entra eligiendo un email
  // y la API tiene que correr con AUTH_MODE=dev.
  authMode: "firebase",
  // Base de la API. Con Firebase Hosting, /api/** se reescribe al servicio de Cloud Run.
  apiBase: "/api",
  // Zona horaria de referencia para fechas y horas (Uruguay).
  tz: "America/Montevideo",
};
// En desarrollo local (localhost) se usa el modo dev si no hay Firebase configurado.
if (["localhost", "127.0.0.1"].includes(location.hostname) && window.APP_CONFIG.firebaseConfig.apiKey === "TU_API_KEY") {
  window.APP_CONFIG.authMode = "dev";
}
