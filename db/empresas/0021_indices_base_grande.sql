-- migrate: sin-transaccion
-- 0021_indices_base_grande.sql — SPEC_rendimiento_base_grande (D55), P-3 y P-4.
-- CREATE INDEX CONCURRENTLY no bloquea la aplicación mientras se arma (sobre 2 millones de filas tarda unos minutos),
-- pero no puede correr dentro de una transacción: db/migrate.py ejecuta cada sentencia de este archivo por separado,
-- y si un índice quedó a medio armar (inválido) de un intento anterior, lo borra y lo vuelve a crear.

-- Filtros del buscador: base y baja van siempre; departamento, tamaño o naturaleza según el filtro
CREATE INDEX CONCURRENTLY IF NOT EXISTS empresa_base_baja_depto_idx ON empresas.empresa (base, baja, departamento);
CREATE INDEX CONCURRENTLY IF NOT EXISTS empresa_base_baja_tamano_idx ON empresas.empresa (base, baja, tamano);
CREATE INDEX CONCURRENTLY IF NOT EXISTS empresa_base_baja_naturaleza_idx ON empresas.empresa (base, baja, naturaleza_id);

-- Orden y paginación por clave del buscador: (razón social, sin razón social al final, código)
CREATE INDEX CONCURRENTLY IF NOT EXISTS empresa_orden_buscador_idx
  ON empresas.empresa (base, (razon_social IS NULL), (coalesce(razon_social, '')), codigo) WHERE baja IS NULL;

-- Búsqueda por razón social o fantasía con ILIKE '%…%' (pg_trgm)
CREATE INDEX CONCURRENTLY IF NOT EXISTS empresa_razon_social_trgm_idx ON empresas.empresa USING gin (razon_social public.gin_trgm_ops);
CREATE INDEX CONCURRENTLY IF NOT EXISTS empresa_fantasia_trgm_idx ON empresas.empresa USING gin (fantasia public.gin_trgm_ops);

-- CIIU a 2 dígitos (filtros del sorteo y valores precalculados)
CREATE INDEX CONCURRENTLY IF NOT EXISTS empresa_ciiu2_idx ON empresas.empresa ((left(ciiu, 2)));

-- Uso de cada naturaleza en la historia y «¿se puede borrar esta naturaleza?»
CREATE INDEX CONCURRENTLY IF NOT EXISTS empresa_campo_historia_campo_valor_idx ON empresas.empresa_campo_historia (campo, valor);

-- «No llamar» por contacto: las empresas de los vínculos de ese contacto
CREATE INDEX CONCURRENTLY IF NOT EXISTS telefono_vinculo_contacto_idx ON empresas.telefono_vinculo (contacto_id) WHERE contacto_id IS NOT NULL;
