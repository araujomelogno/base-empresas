-- 0002_disponibilidad.sql — Teléfonos discables y reglas de disponibilidad (R1.2, R1.4, R1.6)
SET search_path TO empresas, public;

-- Vínculos teléfono–empresa que se pueden discar: teléfono válido, no intermediario
-- (sospechoso o confirmado), vínculo sin verificar o verificado y nada en no llamar.
CREATE VIEW v_vinculo_discable AS
SELECT v.id AS vinculo_id, v.empresa_id, v.telefono_id, v.contacto_id, t.e164, t.tipo, v.estado
FROM telefono_vinculo v
JOIN telefono t ON t.id = v.telefono_id
WHERE t.e164 IS NOT NULL
  AND t.estado = 'valido'
  AND t.tipo IN ('fijo','celular')
  AND (t.intermediario IS NULL OR t.intermediario = 'liberado')
  AND v.estado IN ('sin_verificar','verificado')
  AND NOT EXISTS (SELECT 1 FROM no_llamar n WHERE n.activo AND n.alcance = 'telefono' AND n.objeto_id = t.id)
  AND NOT EXISTS (SELECT 1 FROM no_llamar n WHERE n.activo AND n.alcance = 'contacto' AND n.objeto_id = v.contacto_id);

-- Reglas que bloquean a cada empresa según una configuración dada.
-- Devuelve una fila por (empresa, regla). Las reglas de exclusión por naturaleza,
-- no llamar, baja y cerrada son siempre activas; el resto se activa en la config.
CREATE FUNCTION bloqueos(cfg jsonb, excluir_muestra int DEFAULT NULL)
RETURNS TABLE (empresa_id int, regla text, hasta timestamptz)
LANGUAGE sql STABLE SET search_path = empresas, public AS $$
  SELECT e.id, 'baja', NULL::timestamptz FROM empresa e WHERE e.baja IS NOT NULL
  UNION ALL
  SELECT e.id, 'cerrada', NULL FROM empresa e WHERE e.estado = 'cerrada' AND e.baja IS NULL
  UNION ALL
  SELECT e.id, 'naturaleza_excluida', NULL
  FROM empresa e JOIN naturaleza_juridica n ON n.id = e.naturaleza_id
  WHERE n.codigo IN (SELECT jsonb_array_elements_text(coalesce(cfg->'naturalezas_excluidas','[]'::jsonb)))
  UNION ALL
  SELECT n.objeto_id, 'no_llamar', NULL FROM no_llamar n WHERE n.activo AND n.alcance = 'empresa'
  UNION ALL
  SELECT e.id, 'enfriamiento',
         e.ultimo_contacto_efectivo + make_interval(months => (cfg->>'meses_enfriamiento')::int)
  FROM empresa e
  WHERE coalesce((cfg->'reglas_disponibilidad'->>'enfriamiento')::boolean, true)
    AND e.ultimo_contacto_efectivo IS NOT NULL
    AND e.ultimo_contacto_efectivo + make_interval(months => (cfg->>'meses_enfriamiento')::int) > now()
  UNION ALL
  SELECT DISTINCT i.empresa_id, 'muestra_activa', NULL::timestamptz
  FROM muestra_item i JOIN muestra m ON m.id = i.muestra_id
  WHERE coalesce((cfg->'reglas_disponibilidad'->>'muestra_activa')::boolean, true)
    AND m.estado = 'activa'
    AND (excluir_muestra IS NULL OR m.id <> excluir_muestra)
  UNION ALL
  SELECT e.id, 'sin_telefono_discable', NULL::timestamptz
  FROM empresa e
  WHERE coalesce((cfg->'reglas_disponibilidad'->>'sin_telefono_discable')::boolean, true)
    AND NOT EXISTS (SELECT 1 FROM v_vinculo_discable d WHERE d.empresa_id = e.id)
$$;

CREATE FUNCTION config_vigente() RETURNS jsonb LANGUAGE sql STABLE SET search_path = empresas, public AS $$
  SELECT parametros FROM config_version ORDER BY version DESC LIMIT 1
$$;

-- Disponibilidad con la configuración vigente: para cada empresa, si está disponible
-- y, si no, qué reglas la bloquean y hasta cuándo.
CREATE VIEW v_empresa_disponible AS
SELECT e.id AS empresa_id, e.rut,
       b.reglas IS NULL AS disponible,
       coalesce(b.reglas, ARRAY[]::text[]) AS reglas,
       b.hasta
FROM empresa e
LEFT JOIN (
  SELECT empresa_id, array_agg(DISTINCT regla ORDER BY regla) AS reglas, max(hasta) AS hasta
  FROM bloqueos(config_vigente())
  GROUP BY empresa_id
) b ON b.empresa_id = e.id;
