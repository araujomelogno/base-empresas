-- 0015_cargas_por_lotes.sql — Cargas grandes por lotes (SPEC_cargas_grandes_por_lotes; D50).
-- Preview, confirmación, deshacer y borrado dejan de ser una sola transacción: cada lote (o tanda) es una
-- transacción y una ejecución de la tarea. Compatible hacia atrás: las cargas existentes no cambian.
SET search_path TO empresas, public;

-- ── L1 · El archivo se lee una sola vez: sus filas quedan acá mientras la carga se procesa ──
CREATE TABLE IF NOT EXISTS carga_fila (
  carga_id int NOT NULL REFERENCES carga(id) ON DELETE CASCADE,
  fila     int NOT NULL,              -- número de fila del archivo (la primera de datos es la 2)
  lote     int NOT NULL,              -- las filas con el mismo RUT caen en el mismo lote
  datos    jsonb NOT NULL,
  PRIMARY KEY (carga_id, fila)
);
CREATE INDEX IF NOT EXISTS carga_fila_lote_idx ON carga_fila(carga_id, lote);

-- ── L2 / L3 · Estado de cada lote, para el preview y para la confirmación ──
CREATE TABLE IF NOT EXISTS carga_lote (
  carga_id        int NOT NULL REFERENCES carga(id) ON DELETE CASCADE,
  numero          int NOT NULL,
  filas           int NOT NULL,
  fila_desde      int,
  fila_hasta      int,
  preview_hecho   boolean NOT NULL DEFAULT false,
  preview_conteos jsonb,
  preview_segundos numeric,           -- cuánto tardó su preview (para estimar la confirmación)
  estado          text NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'en_proceso', 'aplicado', 'error')),
  conteos         jsonb,
  intentos        int NOT NULL DEFAULT 0,
  inicio          timestamptz,
  fin             timestamptz,
  segundos        numeric,
  error           text,
  PRIMARY KEY (carga_id, numero)
);

-- ── L5 · Trabajo pendiente de deshacer y borrar (empresas a recalcular, teléfonos a reevaluar…) ──
CREATE TABLE IF NOT EXISTS carga_trabajo (
  carga_id  int NOT NULL,             -- sin FK: el borrado termina borrando la carga
  tipo      text NOT NULL,
  objeto_id int NOT NULL,
  PRIMARY KEY (carga_id, tipo, objeto_id)
);

-- ── Estados nuevos de la carga y de qué operación se trata ──
ALTER TABLE carga DROP CONSTRAINT IF EXISTS carga_estado_check;
ALTER TABLE carga ADD CONSTRAINT carga_estado_check
  CHECK (estado IN ('analizando','preview','en_proceso','confirmada','descartada','deshecha','error',
                    'interrumpida','deshaciendo','borrando'));
ALTER TABLE carga ADD COLUMN IF NOT EXISTS operacion text;          -- preview · confirmar · deshacer · borrar
ALTER TABLE carga ADD COLUMN IF NOT EXISTS paso text;               -- fase de deshacer o borrar
ALTER TABLE carga ADD COLUMN IF NOT EXISTS tarea_id int;            -- la tarea de la operación en curso
ALTER TABLE carga ADD COLUMN IF NOT EXISTS cola timestamptz;        -- esperando a que termine otra carga pesada
ALTER TABLE carga ADD COLUMN IF NOT EXISTS lotes int;
ALTER TABLE carga ADD COLUMN IF NOT EXISTS n_filas int;
ALTER TABLE carga ADD COLUMN IF NOT EXISTS error text;
ALTER TABLE carga ADD COLUMN IF NOT EXISTS resumen_op jsonb NOT NULL DEFAULT '{}';

-- ── Tareas por pasos: un mensaje para la pantalla y la última vez que avanzaron (para detectar las trabadas) ──
ALTER TABLE tarea ADD COLUMN IF NOT EXISTS mensaje text;
ALTER TABLE tarea ADD COLUMN IF NOT EXISTS actualizado timestamptz NOT NULL DEFAULT now();
CREATE INDEX IF NOT EXISTS tarea_activas_idx ON tarea(tipo, estado) WHERE estado IN ('pendiente', 'corriendo');

-- Deshacer y borrar recorren lo que aportó una carga: índices por fuente que faltaban
CREATE INDEX IF NOT EXISTS telefono_vinculo_origen_fuente_idx ON telefono_vinculo_origen(fuente_tipo, fuente_id);
CREATE INDEX IF NOT EXISTS contacto_fuente_idx ON contacto(fuente_tipo, fuente_id);
CREATE INDEX IF NOT EXISTS sucursal_fuente_idx ON sucursal(fuente_tipo, fuente_id);
CREATE INDEX IF NOT EXISTS empresa_carga_alta_idx ON empresa(carga_alta_id) WHERE carga_alta_id IS NOT NULL;
