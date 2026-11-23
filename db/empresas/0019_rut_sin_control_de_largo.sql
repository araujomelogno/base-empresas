-- 0019_rut_sin_control_de_largo.sql — Aceptar identificadores de 6 a 11 dígitos (SPEC_rut_sin_control_de_largo; D54).
-- empresa.rut deja de ser char(12) (que rellenaba con espacios un valor más corto) y pasa a varchar(12) con solo
-- dígitos; rut_verificado distingue el RUT de 12 dígitos validado de un identificador aceptado sin validar.
-- Los valores que ya existen (todos de 12 dígitos) no cambian.
SET search_path TO empresas, public;

DO $$
DECLARE
  vista text;
BEGIN
  -- La vista de disponibilidad y la columna generada «codigo» usan empresa.rut: se rearman alrededor del cambio de tipo
  vista := pg_get_viewdef('empresas.v_empresa_disponible'::regclass, true);
  DROP VIEW empresas.v_empresa_disponible;
  ALTER TABLE empresas.empresa DROP COLUMN codigo;
  ALTER TABLE empresas.empresa ALTER COLUMN rut TYPE varchar(12) USING rtrim(rut);
  ALTER TABLE empresas.empresa ADD COLUMN codigo text
    GENERATED ALWAYS AS (coalesce(rut::text, 'P-' || lpad(id::text, 6, '0'))) STORED;
  EXECUTE 'CREATE VIEW empresas.v_empresa_disponible AS ' || vista;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS empresa_codigo_idx ON empresa(codigo);
ALTER TABLE empresa DROP CONSTRAINT IF EXISTS empresa_rut_digitos;
ALTER TABLE empresa ADD CONSTRAINT empresa_rut_digitos CHECK (rut IS NULL OR rut ~ '^[0-9]{6,12}$');

-- true: RUT de 12 dígitos validado (registro, «001» y dígito verificador); false: identificador de 6 a 11 dígitos
-- aceptado sin validar. Se deriva del largo: un valor de 12 dígitos solo entra validado.
ALTER TABLE empresa ADD COLUMN IF NOT EXISTS rut_verificado boolean
  GENERATED ALWAYS AS (CASE WHEN rut IS NULL THEN NULL ELSE length(rut) = 12 END) STORED;
CREATE INDEX IF NOT EXISTS empresa_rut_no_verificado_idx ON empresa(id) WHERE rut_verificado = false;

-- Las otras columnas de RUT, igual
ALTER TABLE carga_promocion ALTER COLUMN rut_anterior TYPE varchar(12) USING rtrim(rut_anterior);
ALTER TABLE provisoria_rut_propuesto ALTER COLUMN rut TYPE varchar(12) USING rtrim(rut);
