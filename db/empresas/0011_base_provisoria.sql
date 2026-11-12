-- 0011_base_provisoria.sql — Base provisoria (empresas sin RUT) y reglas de fusión en cascada
-- (SPEC_mejoras_sav_contactos_atributos_identidad, F6.1 y F6.2; D42 y D43). Compatible hacia atrás:
-- todo lo que existe queda en la base definitiva y cada carga con su regla como una lista de reglas.
SET search_path TO empresas, public;

-- ── F6.1 Dos bases en la misma tabla ──
ALTER TABLE empresa ADD COLUMN IF NOT EXISTS base text NOT NULL DEFAULT 'definitiva';
ALTER TABLE empresa DROP CONSTRAINT IF EXISTS empresa_base_check;
ALTER TABLE empresa ADD CONSTRAINT empresa_base_check CHECK (base IN ('definitiva', 'provisoria'));
ALTER TABLE empresa ALTER COLUMN rut DROP NOT NULL;
ALTER TABLE empresa DROP CONSTRAINT IF EXISTS empresa_rut_solo_provisoria;
ALTER TABLE empresa ADD CONSTRAINT empresa_rut_solo_provisoria CHECK (base = 'provisoria' OR rut IS NOT NULL);
-- Código visible: el RUT en la definitiva, «P-» + id en la provisoria (URL, buscador, exportación, .sav)
ALTER TABLE empresa ADD COLUMN IF NOT EXISTS codigo text
  GENERATED ALWAYS AS (coalesce(rut::text, 'P-' || lpad(id::text, 6, '0'))) STORED;
CREATE UNIQUE INDEX IF NOT EXISTS empresa_codigo_idx ON empresa(codigo);
CREATE INDEX IF NOT EXISTS empresa_base_idx ON empresa(base);
-- Similitud (F6.2): razón social y dirección
CREATE INDEX IF NOT EXISTS empresa_razon_trgm_idx ON empresa USING gin (lower(razon_social) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS empresa_direccion_trgm_idx ON empresa USING gin (lower(direccion) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS contacto_email_idx ON contacto (lower(email));

-- Atributo de sistema: el identificador que trajo la fila cuando no es un RUT válido (cédula, BPS, «RUT» de 7 dígitos)
ALTER TABLE atributo ADD COLUMN IF NOT EXISTS sistema boolean NOT NULL DEFAULT false;
INSERT INTO atributo (clave, nombre, tipo, opciones, sinonimos, filtrable, estratificable, activo, creado_por, ambito, sistema)
VALUES ('id_informado', 'Identificador informado', 'texto', '[]', '{}', false, false, true, 'sistema', 'empresa', true)
ON CONFLICT (clave) DO UPDATE SET sistema = true;

-- ── Carga: destino, reglas en cascada, opciones y decisiones del preview ──
ALTER TABLE carga ADD COLUMN IF NOT EXISTS destino text NOT NULL DEFAULT 'definitiva';
ALTER TABLE carga DROP CONSTRAINT IF EXISTS carga_destino_check;
ALTER TABLE carga ADD CONSTRAINT carga_destino_check CHECK (destino IN ('definitiva', 'provisoria'));
ALTER TABLE carga ADD COLUMN IF NOT EXISTS reglas jsonb;
ALTER TABLE carga ADD COLUMN IF NOT EXISTS opciones jsonb NOT NULL DEFAULT '{}';
ALTER TABLE carga ADD COLUMN IF NOT EXISTS decisiones jsonb NOT NULL DEFAULT '{}';
-- Las cargas existentes: su regla única pasa a ser una lista (RUT exacta y, si había otra, esa)
UPDATE carga SET reglas = CASE WHEN regla_fusion = 'rut' THEN '[{"criterio": "rut", "tipo": "exacta"}]'::jsonb
  ELSE jsonb_build_array(jsonb_build_object('criterio', 'rut', 'tipo', 'exacta'),
                         jsonb_build_object('criterio', CASE regla_fusion WHEN 'dominio' THEN 'dominio_web' ELSE regla_fusion END,
                                            'tipo', 'exacta')) END
WHERE reglas IS NULL;
ALTER TABLE carga ALTER COLUMN reglas SET DEFAULT '[{"criterio": "rut", "tipo": "exacta"}]';
ALTER TABLE carga_plantilla ADD COLUMN IF NOT EXISTS destino text;
ALTER TABLE carga_plantilla ADD COLUMN IF NOT EXISTS reglas jsonb;

ALTER TABLE revision_fusion ADD COLUMN IF NOT EXISTS similitud numeric;

-- Lo que una carga cambió de la identidad de una empresa existente (pasar a la definitiva), para deshacerlo
CREATE TABLE IF NOT EXISTS carga_promocion (
  id          serial PRIMARY KEY,
  carga_id    int NOT NULL REFERENCES carga(id) ON DELETE CASCADE,
  empresa_id  int NOT NULL REFERENCES empresa(id),
  rut_anterior char(12),
  base_anterior text NOT NULL,
  fecha       timestamptz NOT NULL DEFAULT now()
);

-- ── Pantalla «Base provisoria» ──
-- «Es otra empresa»: la candidata descartada no se vuelve a proponer
CREATE TABLE IF NOT EXISTS provisoria_descarte (
  empresa_id   int NOT NULL REFERENCES empresa(id),
  candidata_id int NOT NULL REFERENCES empresa(id),
  actor        text NOT NULL,
  fecha        timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (empresa_id, candidata_id)
);
-- RUT propuesto por el .sav (EC_RUT de una fila de una provisoria): no se aplica solo
CREATE TABLE IF NOT EXISTS provisoria_rut_propuesto (
  id          serial PRIMARY KEY,
  empresa_id  int NOT NULL REFERENCES empresa(id),
  rut         char(12) NOT NULL,
  fuente_tipo text NOT NULL,
  fuente_id   int,
  estado      text NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'aplicado', 'descartado')),
  fecha       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (empresa_id, rut)
);
