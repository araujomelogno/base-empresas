-- 0012_templates_sorteo.sql — Templates de sorteo, empresas sin teléfono por muestra y filtros y estratos con
-- todos los datos de la empresa (SPEC_templates_sorteo_sin_telefono_formatos_csv, R2–R4; D44).
-- Compatible hacia atrás: las muestras existentes no cambian (sin «incluir_sin_telefono» = false).
SET search_path TO empresas, public;

-- ── R2 Templates de sorteo: copias de criterios (pasos 1 a 3), no referencias vivas ──
CREATE TABLE IF NOT EXISTS muestra_template (
  id              serial PRIMARY KEY,
  nombre          text NOT NULL,
  descripcion     text,
  criterios       jsonb NOT NULL,
  creado_por      text NOT NULL,
  creado          timestamptz NOT NULL DEFAULT now(),
  actualizado_por text,
  actualizado     timestamptz,
  veces_usado     int NOT NULL DEFAULT 0,
  activo          boolean NOT NULL DEFAULT true
);
CREATE UNIQUE INDEX IF NOT EXISTS muestra_template_nombre_idx ON muestra_template (lower(nombre));
ALTER TABLE muestra ADD COLUMN IF NOT EXISTS template_id int REFERENCES muestra_template(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS muestra_template_id_idx ON muestra(template_id);

-- ── R4 Todo dato de la empresa sirve como filtro y estrato: «estratificable» deja de restringir ──
DO $$
DECLARE c record;
BEGIN
  FOR c IN SELECT conname FROM pg_constraint
           WHERE conrelid = 'empresas.atributo'::regclass AND contype = 'c'
             AND pg_get_constraintdef(oid) ILIKE '%estratificable%'
  LOOP
    EXECUTE format('ALTER TABLE empresas.atributo DROP CONSTRAINT %I', c.conname);
  END LOOP;
END $$;

-- Filtros sobre atributos por valor (lista, «es uno de», rangos)
CREATE INDEX IF NOT EXISTS empresa_atributo_texto_idx ON empresa_atributo (atributo_id, valor_texto);
CREATE INDEX IF NOT EXISTS empresa_atributo_numero_idx ON empresa_atributo (atributo_id, valor_numero);
CREATE INDEX IF NOT EXISTS empresa_atributo_fecha_idx ON empresa_atributo (atributo_id, valor_fecha);

-- Texto comparable: sin mayúsculas, tildes ni espacios de más (igual que criterios.norm_txt en la API)
CREATE OR REPLACE FUNCTION norm_txt(t text) RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT nullif(regexp_replace(translate(lower(btrim(t)), 'áéíóúüñàèìòùâêîôûäëïö', 'aeiouunaeiouaeiouaeio'),
                               '\s+', ' ', 'g'), '')
$$;
