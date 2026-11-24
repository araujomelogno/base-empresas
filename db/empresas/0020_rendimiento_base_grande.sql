-- 0020_rendimiento_base_grande.sql — SPEC_rendimiento_base_grande (D55)
-- P-2: disponibilidad guardada (empresa_disponibilidad) y marcas de «a recalcular» que dejan los triggers.
-- P-4: resumen precalculado (resumen_base) y un contador de cambios para saber si quedó viejo.
-- P-1: autovacuum más agresivo en las tablas grandes.
-- Los índices van en 0021, con CREATE INDEX CONCURRENTLY (fuera de una transacción).
SET search_path TO empresas, public;

-- ── P-2 · Disponibilidad guardada ──
-- El resultado de bloqueos(cfg) para cada empresa, con la configuración vigente. La vista v_empresa_disponible queda
-- para verificar; la leen solo los tests de equivalencia y el cálculo de respaldo mientras la tabla no está lista.
CREATE TABLE IF NOT EXISTS empresa_disponibilidad (
  empresa_id          int PRIMARY KEY REFERENCES empresa(id) ON DELETE CASCADE,
  disponible          boolean NOT NULL,
  reglas              text[] NOT NULL DEFAULT '{}',
  hasta               timestamptz,
  telefonos_discables int NOT NULL DEFAULT 0,       -- P-3: en lugar del subselect por fila del buscador
  actualizado         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS empresa_disponibilidad_disponible_idx ON empresa_disponibilidad (disponible);
CREATE INDEX IF NOT EXISTS empresa_disponibilidad_hasta_idx ON empresa_disponibilidad (hasta) WHERE hasta IS NOT NULL;

-- Empresas a recalcular. Sin clave única a propósito: una carga que marca una empresa nunca espera a otra
-- transacción que marcó la misma (se repite y el proceso la toma una vez).
CREATE TABLE IF NOT EXISTS disponibilidad_pendiente (
  id         bigserial PRIMARY KEY,
  empresa_id int NOT NULL,
  marcada    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS disponibilidad_pendiente_empresa_idx ON disponibilidad_pendiente (empresa_id);

-- Estado del cálculo completo: con qué reglas se calculó (meses de enfriamiento, reglas activas, naturalezas
-- excluidas). Si la configuración vigente no coincide, la tabla «no está lista» y se recalcula entera.
CREATE TABLE IF NOT EXISTS disponibilidad_control (
  id           int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  cfg          jsonb,                 -- reglas con las que está calculada la tabla entera (NULL: nunca)
  completo     boolean NOT NULL DEFAULT false,
  cfg_en_curso jsonb,                 -- recálculo completo en curso: con qué reglas
  ultimo_id    int,                   -- hasta qué empresa llegó
  hechas       int,
  total        int,
  iniciado     timestamptz,
  terminado    timestamptz
);
INSERT INTO disponibilidad_control (id) VALUES (1) ON CONFLICT DO NOTHING;

-- Las mismas reglas que bloqueos(cfg, excluir_muestra), solo para las empresas de «ids». La usan el recálculo
-- incremental, la ficha y el sorteo (que así calcula su marco al momento, sin depender de un recálculo pendiente).
CREATE OR REPLACE FUNCTION bloqueos_ids(cfg jsonb, ids int[], excluir_muestra int DEFAULT NULL)
RETURNS TABLE (empresa_id int, regla text, hasta timestamptz)
LANGUAGE sql STABLE AS $$
  SELECT e.id, 'baja'::text, NULL::timestamptz
  FROM empresas.empresa e JOIN (SELECT DISTINCT unnest(ids) AS id) x ON x.id = e.id
  WHERE e.baja IS NOT NULL
  UNION ALL
  SELECT e.id, 'cerrada', NULL
  FROM empresas.empresa e JOIN (SELECT DISTINCT unnest(ids) AS id) x ON x.id = e.id
  WHERE e.estado = 'cerrada' AND e.baja IS NULL
  UNION ALL
  SELECT e.id, 'naturaleza_excluida', NULL
  FROM empresas.empresa e JOIN (SELECT DISTINCT unnest(ids) AS id) x ON x.id = e.id
  JOIN empresas.naturaleza_juridica n ON n.id = e.naturaleza_id
  WHERE n.codigo IN (SELECT jsonb_array_elements_text(coalesce(cfg->'naturalezas_excluidas', '[]'::jsonb)))
  UNION ALL
  SELECT n.objeto_id, 'no_llamar', NULL
  FROM empresas.no_llamar n JOIN (SELECT DISTINCT unnest(ids) AS id) x ON x.id = n.objeto_id
  WHERE n.activo AND n.alcance = 'empresa'
  UNION ALL
  SELECT e.id, 'enfriamiento', e.ultimo_contacto_efectivo + make_interval(months => (cfg->>'meses_enfriamiento')::int)
  FROM empresas.empresa e JOIN (SELECT DISTINCT unnest(ids) AS id) x ON x.id = e.id
  WHERE coalesce((cfg->'reglas_disponibilidad'->>'enfriamiento')::boolean, true)
    AND e.ultimo_contacto_efectivo IS NOT NULL
    AND e.ultimo_contacto_efectivo + make_interval(months => (cfg->>'meses_enfriamiento')::int) > now()
  UNION ALL
  SELECT DISTINCT i.empresa_id, 'muestra_activa', NULL::timestamptz
  FROM empresas.muestra_item i JOIN (SELECT DISTINCT unnest(ids) AS id) x ON x.id = i.empresa_id
  JOIN empresas.muestra m ON m.id = i.muestra_id
  WHERE coalesce((cfg->'reglas_disponibilidad'->>'muestra_activa')::boolean, true)
    AND m.estado = 'activa'
    AND (excluir_muestra IS NULL OR m.id <> excluir_muestra)
  UNION ALL
  SELECT e.id, 'sin_telefono_discable', NULL::timestamptz
  FROM empresas.empresa e JOIN (SELECT DISTINCT unnest(ids) AS id) x ON x.id = e.id
  WHERE coalesce((cfg->'reglas_disponibilidad'->>'sin_telefono_discable')::boolean, true)
    AND NOT EXISTS (SELECT 1 FROM empresas.v_vinculo_discable d WHERE d.empresa_id = e.id)
$$;

-- Una fila por empresa de «ids», como v_empresa_disponible, más la cantidad de teléfonos discables.
CREATE OR REPLACE FUNCTION disponibilidad_calcular(cfg jsonb, ids int[])
RETURNS TABLE (empresa_id int, disponible boolean, reglas text[], hasta timestamptz, telefonos_discables int)
LANGUAGE sql STABLE AS $$
  SELECT e.id, b.reglas IS NULL, coalesce(b.reglas, ARRAY[]::text[]), b.hasta, coalesce(t.n, 0)::int
  FROM empresas.empresa e
  JOIN (SELECT DISTINCT unnest(ids) AS id) x ON x.id = e.id
  LEFT JOIN (SELECT b.empresa_id, array_agg(DISTINCT b.regla ORDER BY b.regla) AS reglas, max(b.hasta) AS hasta
             FROM empresas.bloqueos_ids(cfg, ids) b GROUP BY b.empresa_id) b ON b.empresa_id = e.id
  LEFT JOIN (SELECT d.empresa_id, count(*) AS n
             FROM empresas.v_vinculo_discable d JOIN (SELECT DISTINCT unnest(ids) AS id) y ON y.id = d.empresa_id
             GROUP BY d.empresa_id) t ON t.empresa_id = e.id
$$;

-- ── Marcas «a recalcular» (triggers por sentencia, con las filas que cambiaron) ──

CREATE OR REPLACE FUNCTION disp_empresa() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    INSERT INTO empresas.disponibilidad_pendiente (empresa_id) SELECT id FROM nuevas;
  ELSIF TG_OP = 'UPDATE' THEN
    INSERT INTO empresas.disponibilidad_pendiente (empresa_id)
    SELECT n.id FROM nuevas n JOIN viejas o ON o.id = n.id
    WHERE (n.baja, n.estado, n.naturaleza_id, n.ultimo_contacto_efectivo)
          IS DISTINCT FROM (o.baja, o.estado, o.naturaleza_id, o.ultimo_contacto_efectivo);
  END IF;
  RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS empresa_disp_ins ON empresa;
CREATE TRIGGER empresa_disp_ins AFTER INSERT ON empresa REFERENCING NEW TABLE AS nuevas
  FOR EACH STATEMENT EXECUTE FUNCTION disp_empresa();
DROP TRIGGER IF EXISTS empresa_disp_upd ON empresa;
CREATE TRIGGER empresa_disp_upd AFTER UPDATE ON empresa REFERENCING OLD TABLE AS viejas NEW TABLE AS nuevas
  FOR EACH STATEMENT EXECUTE FUNCTION disp_empresa();

CREATE OR REPLACE FUNCTION disp_vinculo() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    INSERT INTO empresas.disponibilidad_pendiente (empresa_id) SELECT empresa_id FROM nuevas;
  ELSIF TG_OP = 'DELETE' THEN
    INSERT INTO empresas.disponibilidad_pendiente (empresa_id) SELECT empresa_id FROM viejas;
  ELSE
    INSERT INTO empresas.disponibilidad_pendiente (empresa_id)
    SELECT x.empresa_id FROM nuevas n JOIN viejas o ON o.id = n.id
    CROSS JOIN LATERAL (VALUES (n.empresa_id), (o.empresa_id)) x(empresa_id)
    WHERE (n.empresa_id, n.telefono_id, n.contacto_id, n.estado) IS DISTINCT FROM (o.empresa_id, o.telefono_id, o.contacto_id, o.estado);
  END IF;
  RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS vinculo_disp_ins ON telefono_vinculo;
CREATE TRIGGER vinculo_disp_ins AFTER INSERT ON telefono_vinculo REFERENCING NEW TABLE AS nuevas
  FOR EACH STATEMENT EXECUTE FUNCTION disp_vinculo();
DROP TRIGGER IF EXISTS vinculo_disp_upd ON telefono_vinculo;
CREATE TRIGGER vinculo_disp_upd AFTER UPDATE ON telefono_vinculo REFERENCING OLD TABLE AS viejas NEW TABLE AS nuevas
  FOR EACH STATEMENT EXECUTE FUNCTION disp_vinculo();
DROP TRIGGER IF EXISTS vinculo_disp_del ON telefono_vinculo;
CREATE TRIGGER vinculo_disp_del AFTER DELETE ON telefono_vinculo REFERENCING OLD TABLE AS viejas
  FOR EACH STATEMENT EXECUTE FUNCTION disp_vinculo();

-- Un teléfono que cambia de estado, de tipo o de marca de intermediario cambia a todas sus empresas
CREATE OR REPLACE FUNCTION disp_telefono() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO empresas.disponibilidad_pendiente (empresa_id)
  SELECT v.empresa_id FROM nuevas n JOIN viejas o ON o.id = n.id
  JOIN empresas.telefono_vinculo v ON v.telefono_id = n.id
  WHERE (n.e164, n.estado, n.tipo, n.intermediario) IS DISTINCT FROM (o.e164, o.estado, o.tipo, o.intermediario);
  RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS telefono_disp_upd ON telefono;
CREATE TRIGGER telefono_disp_upd AFTER UPDATE ON telefono REFERENCING OLD TABLE AS viejas NEW TABLE AS nuevas
  FOR EACH STATEMENT EXECUTE FUNCTION disp_telefono();

-- No llamar: por empresa, por teléfono (sus empresas) o por contacto (las empresas de sus vínculos)
CREATE OR REPLACE FUNCTION disp_no_llamar() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP IN ('INSERT', 'UPDATE') THEN
    INSERT INTO empresas.disponibilidad_pendiente (empresa_id)
    SELECT t.objeto_id FROM nuevas t WHERE t.alcance = 'empresa'
    UNION ALL SELECT v.empresa_id FROM nuevas t JOIN empresas.telefono_vinculo v ON v.telefono_id = t.objeto_id WHERE t.alcance = 'telefono'
    UNION ALL SELECT v.empresa_id FROM nuevas t JOIN empresas.telefono_vinculo v ON v.contacto_id = t.objeto_id WHERE t.alcance = 'contacto';
  END IF;
  IF TG_OP IN ('DELETE', 'UPDATE') THEN
    INSERT INTO empresas.disponibilidad_pendiente (empresa_id)
    SELECT t.objeto_id FROM viejas t WHERE t.alcance = 'empresa'
    UNION ALL SELECT v.empresa_id FROM viejas t JOIN empresas.telefono_vinculo v ON v.telefono_id = t.objeto_id WHERE t.alcance = 'telefono'
    UNION ALL SELECT v.empresa_id FROM viejas t JOIN empresas.telefono_vinculo v ON v.contacto_id = t.objeto_id WHERE t.alcance = 'contacto';
  END IF;
  RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS no_llamar_disp_ins ON no_llamar;
CREATE TRIGGER no_llamar_disp_ins AFTER INSERT ON no_llamar REFERENCING NEW TABLE AS nuevas
  FOR EACH STATEMENT EXECUTE FUNCTION disp_no_llamar();
DROP TRIGGER IF EXISTS no_llamar_disp_upd ON no_llamar;
CREATE TRIGGER no_llamar_disp_upd AFTER UPDATE ON no_llamar REFERENCING OLD TABLE AS viejas NEW TABLE AS nuevas
  FOR EACH STATEMENT EXECUTE FUNCTION disp_no_llamar();
DROP TRIGGER IF EXISTS no_llamar_disp_del ON no_llamar;
CREATE TRIGGER no_llamar_disp_del AFTER DELETE ON no_llamar REFERENCING OLD TABLE AS viejas
  FOR EACH STATEMENT EXECUTE FUNCTION disp_no_llamar();

-- Muestra activa: los ítems que entran o salen, y las muestras que se activan, se cierran o vuelven a borrador
CREATE OR REPLACE FUNCTION disp_muestra_item() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP IN ('INSERT', 'UPDATE') THEN
    INSERT INTO empresas.disponibilidad_pendiente (empresa_id) SELECT empresa_id FROM nuevas;
  END IF;
  IF TG_OP IN ('DELETE', 'UPDATE') THEN
    INSERT INTO empresas.disponibilidad_pendiente (empresa_id) SELECT empresa_id FROM viejas;
  END IF;
  RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS muestra_item_disp_ins ON muestra_item;
CREATE TRIGGER muestra_item_disp_ins AFTER INSERT ON muestra_item REFERENCING NEW TABLE AS nuevas
  FOR EACH STATEMENT EXECUTE FUNCTION disp_muestra_item();
DROP TRIGGER IF EXISTS muestra_item_disp_upd ON muestra_item;
CREATE TRIGGER muestra_item_disp_upd AFTER UPDATE ON muestra_item REFERENCING OLD TABLE AS viejas NEW TABLE AS nuevas
  FOR EACH STATEMENT EXECUTE FUNCTION disp_muestra_item();
DROP TRIGGER IF EXISTS muestra_item_disp_del ON muestra_item;
CREATE TRIGGER muestra_item_disp_del AFTER DELETE ON muestra_item REFERENCING OLD TABLE AS viejas
  FOR EACH STATEMENT EXECUTE FUNCTION disp_muestra_item();

CREATE OR REPLACE FUNCTION disp_muestra() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO empresas.disponibilidad_pendiente (empresa_id)
  SELECT i.empresa_id FROM nuevas n JOIN viejas o ON o.id = n.id JOIN empresas.muestra_item i ON i.muestra_id = n.id
  WHERE n.estado IS DISTINCT FROM o.estado;
  RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS muestra_disp_upd ON muestra;
CREATE TRIGGER muestra_disp_upd AFTER UPDATE ON muestra REFERENCING OLD TABLE AS viejas NEW TABLE AS nuevas
  FOR EACH STATEMENT EXECUTE FUNCTION disp_muestra();

-- Una naturaleza que cambia de código cambia la regla «naturaleza excluida» de sus empresas
CREATE OR REPLACE FUNCTION disp_naturaleza() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO empresas.disponibilidad_pendiente (empresa_id)
  SELECT e.id FROM nuevas n JOIN viejas o ON o.id = n.id JOIN empresas.empresa e ON e.naturaleza_id = n.id
  WHERE n.codigo IS DISTINCT FROM o.codigo;
  RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS naturaleza_disp_upd ON naturaleza_juridica;
CREATE TRIGGER naturaleza_disp_upd AFTER UPDATE ON naturaleza_juridica REFERENCING OLD TABLE AS viejas NEW TABLE AS nuevas
  FOR EACH STATEMENT EXECUTE FUNCTION disp_naturaleza();

-- ── P-4 · Resumen precalculado ──
CREATE TABLE IF NOT EXISTS resumen_base (
  clave       text PRIMARY KEY,               -- valores, inicio, naturalezas
  valor       jsonb NOT NULL,
  version     bigint NOT NULL,                -- resumen_cambios_seq al calcularlo
  actualizado timestamptz NOT NULL DEFAULT now(),
  segundos    numeric
);
-- Cada sentencia que cambia algo que el resumen cuenta avanza este contador: si pasó al del resumen, quedó viejo.
CREATE SEQUENCE IF NOT EXISTS resumen_cambios_seq;
-- Aparte, los cambios de la disponibilidad guardada: solo dejan viejo el resumen de Inicio (disponibles)
CREATE SEQUENCE IF NOT EXISTS disponibilidad_cambios_seq;

CREATE OR REPLACE FUNCTION resumen_tocar() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  PERFORM nextval('empresas.resumen_cambios_seq');
  RETURN NULL;
END $$;
CREATE OR REPLACE FUNCTION resumen_tocar_disponibilidad() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  PERFORM nextval('empresas.disponibilidad_cambios_seq');
  RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS empresa_disponibilidad_resumen ON empresa_disponibilidad;
CREATE TRIGGER empresa_disponibilidad_resumen AFTER INSERT OR UPDATE OR DELETE ON empresa_disponibilidad
  FOR EACH STATEMENT EXECUTE FUNCTION resumen_tocar_disponibilidad();
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['empresa', 'telefono', 'telefono_vinculo', 'no_llamar', 'muestra', 'naturaleza_juridica',
                           'empresa_campo_historia', 'config_version', 'provisoria_descarte', 'provisoria_rut_propuesto']
  LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS %I ON empresas.%I', t || '_resumen', t);
    EXECUTE format('CREATE TRIGGER %I AFTER INSERT OR UPDATE OR DELETE ON empresas.%I'
                   ' FOR EACH STATEMENT EXECUTE FUNCTION empresas.resumen_tocar()', t || '_resumen', t);
  END LOOP;
END $$;

-- ── P-1 · Autovacuum más agresivo en las tablas grandes ──
ALTER TABLE empresa SET (autovacuum_analyze_scale_factor = 0.02, autovacuum_vacuum_scale_factor = 0.05);
ALTER TABLE empresa_campo_historia SET (autovacuum_analyze_scale_factor = 0.02, autovacuum_vacuum_scale_factor = 0.05);
ALTER TABLE empresa_atributo SET (autovacuum_analyze_scale_factor = 0.02, autovacuum_vacuum_scale_factor = 0.05);
