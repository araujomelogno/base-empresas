-- 0023_busqueda_web_claude.sql — SPEC_brave_pais_y_errores_visibles (D57), B4
-- Paso 5 del enriquecimiento: búsqueda web con Claude. Los teléfonos que trae tienen su propio origen (para medir su
-- tasa de contacto aparte de «Sitio web» y «Google Places») y el paso queda registrado con proveedor «claude_web».
SET search_path TO empresas, public;

INSERT INTO origen_telefono (codigo, nombre, prioridad, sistema) VALUES ('claude_web', 'Búsqueda web (Claude)', 920, true)
ON CONFLICT (codigo) DO UPDATE SET sistema = true;

ALTER TABLE enriquecimiento_paso DROP CONSTRAINT IF EXISTS enriquecimiento_paso_proveedor_check;
ALTER TABLE enriquecimiento_paso ADD CONSTRAINT enriquecimiento_paso_proveedor_check
  CHECK (proveedor IN ('propias', 'google_places', 'brave', 'claude', 'sitio', 'claude_web'));
