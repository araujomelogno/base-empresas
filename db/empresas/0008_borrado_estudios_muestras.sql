-- 0008_borrado_estudios_muestras.sql — Borrar estudios y muestras, cancelar tareas y verificar la
-- reproducibilidad después de borrados (SPEC_borrado_estudios_muestras_y_cargas_en_curso, E4).
-- Compatible hacia atrás: amplía un CHECK, agrega una tabla e índices y quita una FK.
SET search_path TO empresas, public;

-- E3 · Una tarea se puede cancelar (al borrar su carga, muestra o estudio)
ALTER TABLE tarea DROP CONSTRAINT IF EXISTS tarea_estado_check;
ALTER TABLE tarea ADD CONSTRAINT tarea_estado_check
  CHECK (estado IN ('pendiente','corriendo','ok','error','cancelada'));

-- V1 · El marco congelado es un registro histórico, como la auditoría: no se toca nunca.
-- empresa_id queda como número sin referencia cuando la empresa se borra.
ALTER TABLE marco_snapshot_item DROP CONSTRAINT IF EXISTS marco_snapshot_item_empresa_id_fkey;

-- V1 · Ítems de muestra que se fueron con un borrado de empresa o de carga, para que
-- «Verificar reproducibilidad» compare contra la muestra completa.
CREATE TABLE IF NOT EXISTS muestra_item_borrado (
  id           serial PRIMARY KEY,
  muestra_id   int NOT NULL REFERENCES muestra(id),
  item_id      int NOT NULL,          -- id que tenía en muestra_item
  empresa_id   int NOT NULL,          -- sin FK: la empresa ya no existe
  estrato      text NOT NULL,
  rol          text NOT NULL,
  orden        int NOT NULL,
  liberado     boolean NOT NULL,
  accion       text NOT NULL CHECK (accion IN ('empresa.borrar','carga.borrar')),
  borrado_por  text NOT NULL,
  auditoria_id bigint,
  fecha        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS muestra_item_borrado_muestra_idx ON muestra_item_borrado(muestra_id);

-- Índices para que los borrados no recorran tablas enteras
CREATE INDEX IF NOT EXISTS sav_ingesta_parte_idx ON sav_ingesta(parte_id);
CREATE INDEX IF NOT EXISTS sav_fila_ingesta_idx ON sav_fila(ingesta_id);
CREATE INDEX IF NOT EXISTS muestra_estudio_idx ON muestra(estudio_id);
CREATE INDEX IF NOT EXISTS parte_estudio_idx ON parte(estudio_id);
-- intento(item_id) ya tiene índice desde 0001 (intento_item_id_idx)
CREATE INDEX IF NOT EXISTS tarea_estado_idx ON tarea(estado);
CREATE INDEX IF NOT EXISTS tarea_carga_idx ON tarea(((payload->>'carga_id')::int));
CREATE INDEX IF NOT EXISTS tarea_ingesta_idx ON tarea(((payload->>'ingesta_id')::int));
