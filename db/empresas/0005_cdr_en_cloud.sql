-- 0005_cdr_en_cloud.sql — Job del CDR en Google Cloud (SPEC_job_cdr_en_cloud, R5).
-- Compatible hacia atrás: solo agrega tablas y una columna opcional.
SET search_path TO empresas, public;

-- Estado incremental de la lectura del CDR (antes estado.json en la máquina del job).
-- Una sola fila. ultima_calldate es la hora local de MySQL (sin zona), como viene del CDR.
CREATE TABLE IF NOT EXISTS cdr_estado (
  id               int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  ultima_calldate  timestamp,
  uniqueids        text[] NOT NULL DEFAULT '{}',   -- uniqueid ya enviados del último segundo
  actualizado      timestamptz NOT NULL DEFAULT now()
);

-- Una fila por ejecución del job (programada o manual).
CREATE TABLE IF NOT EXISTS cdr_corrida (
  id             serial PRIMARY KEY,
  origen         text NOT NULL CHECK (origen IN ('programada','manual')),
  estado         text NOT NULL DEFAULT 'en_curso' CHECK (estado IN ('en_curso','ok','error','omitida')),
  solicitada_por text,
  dry_run        boolean NOT NULL DEFAULT false,
  pedido_desde   date,                 -- argumentos del reproceso
  pedido_hasta   date,
  leido_desde    timestamp,            -- rango de calldate efectivamente leído
  leido_hasta    timestamp,
  conteos        jsonb NOT NULL DEFAULT '{}'::jsonb,
  mensaje        text,
  inicio         timestamptz NOT NULL DEFAULT now(),
  fin            timestamptz
);
CREATE INDEX IF NOT EXISTS cdr_corrida_inicio ON cdr_corrida (inicio DESC);

ALTER TABLE cdr_lote ADD COLUMN IF NOT EXISTS corrida_id int REFERENCES cdr_corrida(id);
