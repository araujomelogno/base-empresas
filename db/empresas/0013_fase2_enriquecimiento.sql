-- 0013_fase2_enriquecimiento.sql — Fase 2 (SPEC_fase2_enriquecimiento): tablero de calidad, enriquecimiento
-- bajo demanda, duplicados difusos y grupo económico, y descubrimiento en Google Places (D45 a D48).
-- Compatible hacia atrás: agrega tablas, columnas, orígenes y atributos de sistema; amplía un CHECK.
SET search_path TO empresas, public;

-- ── A1 · Tablero de calidad ──
-- Foto diaria de cada indicador (Cloud Scheduler → POST /api/jobs/calidad)
CREATE TABLE IF NOT EXISTS calidad_medicion (
  id          bigserial PRIMARY KEY,
  fecha       date NOT NULL,
  dimension   text NOT NULL,
  indicador   text NOT NULL,
  valor       numeric,                 -- porcentaje (0–100) o cantidad, según el indicador
  numerador   bigint,
  denominador bigint,
  creado      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (fecha, indicador)
);
-- Alertas de consistencia revisadas por el data steward. Se guarda lo que se revisó: si la naturaleza
-- o la razón social cambian, la alerta vuelve a aparecer.
CREATE TABLE IF NOT EXISTS calidad_alerta_revisada (
  empresa_id   int NOT NULL REFERENCES empresa(id) ON DELETE CASCADE,
  regla        text NOT NULL,
  firma        text NOT NULL,
  revisada_por text NOT NULL,
  fecha        timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (empresa_id, regla)
);

-- ── B1 · Orígenes y atributos de sistema del enriquecimiento ──
INSERT INTO origen_telefono (codigo, nombre, prioridad, sistema) VALUES
  ('google_places', 'Google Places', 900, true),
  ('web', 'Sitio web', 910, true)
ON CONFLICT (codigo) DO UPDATE SET sistema = true;

INSERT INTO atributo (clave, nombre, tipo, opciones, sinonimos, filtrable, estratificable, activo, creado_por, ambito, sistema)
VALUES ('email_institucional', 'Email institucional', 'texto', '[]', '{}', false, false, true, 'sistema', 'empresa', true),
       ('google_place_id', 'Google Place ID', 'texto', '[]', '{}', false, false, true, 'sistema', 'empresa', true),
       ('rubro_descubrimiento', 'Rubro buscado (descubrimiento)', 'texto', '[]', '{}', false, false, true, 'sistema', 'empresa', true)
ON CONFLICT (clave) DO UPDATE SET sistema = true;

-- La historia acepta las dos fuentes nuevas
ALTER TABLE empresa_campo_historia DROP CONSTRAINT IF EXISTS empresa_campo_historia_fuente_tipo_check;
ALTER TABLE empresa_campo_historia ADD CONSTRAINT empresa_campo_historia_fuente_tipo_check
  CHECK (fuente_tipo IN ('carga','sav','sala','manual','fusion','sistema','enriquecimiento','descubrimiento'));

-- Motivo de un intermediario sospechoso marcado por el enriquecimiento (sitio de estudio contable/jurídico)
ALTER TABLE telefono ADD COLUMN IF NOT EXISTS intermediario_motivo text;

-- ── B2 · Corridas de enriquecimiento y lotes de descubrimiento ──
CREATE TABLE IF NOT EXISTS enriquecimiento_corrida (
  id          serial PRIMARY KEY,
  tipo        text NOT NULL DEFAULT 'enriquecimiento' CHECK (tipo IN ('enriquecimiento', 'descubrimiento')),
  origen      text NOT NULL CHECK (origen IN ('muestra', 'lista', 'ficha', 'descubrimiento')),
  muestra_id  int REFERENCES muestra(id) ON DELETE SET NULL,
  filtros     jsonb,                                  -- lista: filtros de Empresas; descubrimiento: consulta
  empresa_ids int[] NOT NULL DEFAULT '{}',            -- las que se enriquecen (sin las salteadas)
  salteadas   jsonb NOT NULL DEFAULT '{}',            -- {motivo: cantidad}
  estimacion  jsonb NOT NULL DEFAULT '{}',
  opciones    jsonb NOT NULL DEFAULT '{}',
  estado      text NOT NULL DEFAULT 'estimada'
              CHECK (estado IN ('estimada', 'en_curso', 'terminada', 'detenida_tope', 'cancelada', 'error',
                                'preview', 'confirmada', 'descartada', 'deshecha')),
  creado_por  text NOT NULL,
  creado      timestamptz NOT NULL DEFAULT now(),
  aprobada_por text,
  aprobada    timestamptz,
  gasto       numeric NOT NULL DEFAULT 0,
  resultado   jsonb,
  tarea_id    int REFERENCES tarea(id) ON DELETE SET NULL,
  terminada   timestamptz,
  deshecha    timestamptz,
  deshecha_por text,
  error       text
);
CREATE INDEX IF NOT EXISTS enriquecimiento_corrida_muestra_idx ON enriquecimiento_corrida(muestra_id);

-- Cada paso de la cascada (pago o no), con su costo: es el registro del gasto
CREATE TABLE IF NOT EXISTS enriquecimiento_paso (
  id          bigserial PRIMARY KEY,
  corrida_id  int NOT NULL REFERENCES enriquecimiento_corrida(id) ON DELETE CASCADE,
  empresa_id  int REFERENCES empresa(id) ON DELETE SET NULL,
  proveedor   text NOT NULL CHECK (proveedor IN ('propias', 'google_places', 'brave', 'claude', 'sitio')),
  consulta    text,
  costo       numeric NOT NULL DEFAULT 0,
  resultado   text NOT NULL,                          -- ok · sin_resultado · error · tope
  detalle     jsonb,
  place_id    text,
  url         text,
  fecha       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS enriquecimiento_paso_fecha_idx ON enriquecimiento_paso(fecha);
CREATE INDEX IF NOT EXISTS enriquecimiento_paso_corrida_idx ON enriquecimiento_paso(corrida_id);
CREATE INDEX IF NOT EXISTS enriquecimiento_paso_empresa_idx ON enriquecimiento_paso(empresa_id);

-- Empresas que dio de alta un lote de descubrimiento (para deshacerlo)
ALTER TABLE empresa ADD COLUMN IF NOT EXISTS alta_corrida_id int REFERENCES enriquecimiento_corrida(id) ON DELETE SET NULL;

-- ── B4 · Grupo económico y duplicados difusos ──
CREATE TABLE IF NOT EXISTS grupo_economico (
  id         serial PRIMARY KEY,
  nombre     text NOT NULL,
  creado_por text NOT NULL,
  creado     timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE empresa ADD COLUMN IF NOT EXISTS grupo_economico_id int REFERENCES grupo_economico(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS empresa_grupo_idx ON empresa(grupo_economico_id) WHERE grupo_economico_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS duplicado_par (
  id           serial PRIMARY KEY,
  empresa_a    int NOT NULL REFERENCES empresa(id) ON DELETE CASCADE,
  empresa_b    int NOT NULL REFERENCES empresa(id) ON DELETE CASCADE,
  criterios    jsonb NOT NULL,                        -- [{"criterio": "telefono", "evidencia": "+59829001234"}]
  estado       text NOT NULL DEFAULT 'pendiente'
               CHECK (estado IN ('pendiente', 'fusionado', 'grupo', 'sin_relacion', 'obsoleto')),
  detectado    timestamptz NOT NULL DEFAULT now(),
  actualizado  timestamptz NOT NULL DEFAULT now(),
  resuelto_por text,
  resuelto     timestamptz,
  CHECK (empresa_a < empresa_b),
  UNIQUE (empresa_a, empresa_b)
);
CREATE INDEX IF NOT EXISTS duplicado_par_estado_idx ON duplicado_par(estado);

-- El sorteo congela la pertenencia a grupos (Verificar reproducibilidad con «una empresa por grupo»)
ALTER TABLE marco_snapshot_item ADD COLUMN IF NOT EXISTS grupo_id int;

-- Razón social sin forma societaria (mismo criterio que util.razon_normalizada) para la similitud ≥ 0,9
CREATE OR REPLACE FUNCTION razon_sin_sufijo(t text) RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT nullif(btrim(regexp_replace(regexp_replace(regexp_replace(
           translate(lower(coalesce(t, '')), 'áéíóúüñàèìòù', 'aeiouunaeiou'),
           '\m(s\.?\s?a\.?\s?s\.?|s\.?\s?r\.?\s?l\.?|s\.?\s?a\.?|ltda\.?|sociedad anonima|limitada|cia\.?|y cia)(\s|$|[^a-z0-9])',
           ' ', 'g'), '[^a-z0-9 ]', ' ', 'g'), '\s+', ' ', 'g')), '')
$$;
CREATE INDEX IF NOT EXISTS empresa_razon_sin_sufijo_trgm_idx ON empresa USING gin (razon_sin_sufijo(razon_social) gin_trgm_ops)
  WHERE baja IS NULL AND base = 'definitiva';

-- Dominio del sitio web (sin protocolo ni www)
CREATE OR REPLACE FUNCTION dominio_web(t text) RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT nullif(split_part(split_part(regexp_replace(lower(btrim(coalesce(t, ''))), '^([a-z]+://)?(www[0-9]?\.)?', ''), '/', 1), '?', 1), '')
$$;
CREATE INDEX IF NOT EXISTS empresa_dominio_idx ON empresa (dominio_web(web)) WHERE web IS NOT NULL AND baja IS NULL;
