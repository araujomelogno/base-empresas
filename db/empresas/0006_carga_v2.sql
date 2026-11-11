-- 0006_carga_v2.sql — Carga de bases v2: atributos administrables y origen del teléfono
-- (SPEC_carga_v2_atributos_y_origen_telefono). Compatible hacia atrás: agrega tablas y
-- columnas, amplía un CHECK y deja con origen "Sin dato" a los vínculos que ya existían.
SET search_path TO empresas, public;

-- ─── C1 · Catálogo de atributos ───
CREATE TABLE IF NOT EXISTS atributo (
  id             serial PRIMARY KEY,
  clave          text NOT NULL UNIQUE CHECK (clave ~ '^[a-z][a-z0-9_]{0,39}$'),
  nombre         text NOT NULL,
  tipo           text NOT NULL CHECK (tipo IN ('texto','numero','fecha','lista')),
  opciones       jsonb NOT NULL DEFAULT '[]'::jsonb,   -- solo para 'lista': ["Sí","No"]
  sinonimos      text[] NOT NULL DEFAULT '{}',          -- nombres de columna que se reconocen
  filtrable      boolean NOT NULL DEFAULT false,
  estratificable boolean NOT NULL DEFAULT false,
  activo         boolean NOT NULL DEFAULT true,
  creado_por     text NOT NULL,
  creado         timestamptz NOT NULL DEFAULT now(),
  actualizado    timestamptz NOT NULL DEFAULT now(),
  CHECK (NOT estratificable OR tipo = 'lista')
);

-- ─── C2 · Valor vigente por empresa y atributo ───
-- La historia está en empresa_campo_historia con campo = 'atributo.<clave>'; esta tabla
-- guarda el ganador de la regla de supervivencia, tipado, para filtrar y estratificar.
CREATE TABLE IF NOT EXISTS empresa_atributo (
  empresa_id   int NOT NULL REFERENCES empresa(id),
  atributo_id  int NOT NULL REFERENCES atributo(id),
  valor_texto  text,
  valor_numero numeric,
  valor_fecha  date,
  valor_crudo  text NOT NULL,          -- lo que llegó; si no se pudo interpretar, solo esto
  fuente_tipo  text NOT NULL,
  fuente_id    int,
  confianza    int NOT NULL,
  fecha        timestamptz NOT NULL,
  PRIMARY KEY (empresa_id, atributo_id)
);
CREATE INDEX IF NOT EXISTS empresa_atributo_atributo ON empresa_atributo(atributo_id);

-- ─── C4 · Catálogo de orígenes de teléfono ───
CREATE TABLE IF NOT EXISTS origen_telefono (
  id        serial PRIMARY KEY,
  codigo    text NOT NULL UNIQUE CHECK (codigo ~ '^[a-z][a-z0-9_]{0,39}$'),
  nombre    text NOT NULL,
  prioridad int NOT NULL DEFAULT 100,   -- menor = más confiable; ordena los teléfonos del CSV
  activo    boolean NOT NULL DEFAULT true,
  sistema   boolean NOT NULL DEFAULT false
);
INSERT INTO origen_telefono (codigo, nombre, prioridad, sistema) VALUES
  ('sala', 'Sala (teléfono alternativo del .sav)', 10, true),
  ('manual', 'Manual (agregado en la ficha)', 20, true),
  ('sin_dato', 'Sin dato', 1000, true)
ON CONFLICT (codigo) DO NOTHING;

-- Evidencia del origen de cada vínculo teléfono–empresa: un registro por vínculo y origen.
CREATE TABLE IF NOT EXISTS telefono_vinculo_origen (
  vinculo_id  int NOT NULL REFERENCES telefono_vinculo(id) ON DELETE CASCADE,
  origen_id   int NOT NULL REFERENCES origen_telefono(id),
  fuente_tipo text NOT NULL,
  fuente_id   int,
  fecha       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (vinculo_id, origen_id)
);
CREATE INDEX IF NOT EXISTS telefono_vinculo_origen_origen ON telefono_vinculo_origen(origen_id);

-- Los vínculos anteriores a este cambio quedan con origen "Sin dato" (salvo los de la sala
-- y los manuales, cuyo origen se conoce por su fuente).
INSERT INTO telefono_vinculo_origen (vinculo_id, origen_id, fuente_tipo, fuente_id, fecha)
SELECT v.id, o.id, v.fuente_tipo, v.fuente_id, v.fecha
FROM telefono_vinculo v
JOIN origen_telefono o ON o.codigo = CASE v.fuente_tipo WHEN 'sala' THEN 'sala' WHEN 'manual' THEN 'manual' ELSE 'sin_dato' END
ON CONFLICT DO NOTHING;

-- ─── C10 · Estado "descartada" ───
ALTER TABLE carga DROP CONSTRAINT IF EXISTS carga_estado_check;
ALTER TABLE carga ADD CONSTRAINT carga_estado_check
  CHECK (estado IN ('analizando','preview','en_proceso','confirmada','descartada','deshecha','error'));
ALTER TABLE carga ADD COLUMN IF NOT EXISTS descartada timestamptz;
-- Las cargas "deshechas" que nunca se confirmaron se descartaron en el preview
UPDATE carga SET estado = 'descartada', descartada = deshecha, deshecha = NULL
WHERE estado = 'deshecha' AND confirmada IS NULL;

-- ─── C8 · Opciones de exportación de la muestra ───
ALTER TABLE muestra ADD COLUMN IF NOT EXISTS exportacion jsonb;
