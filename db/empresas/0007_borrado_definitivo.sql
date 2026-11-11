-- 0007_borrado_definitivo.sql — Borrado definitivo de empresas y cargas (solo administrador).
-- La historia sigue siendo append-only para todo el resto del sistema: solo el borrado
-- definitivo (api/app/borrado.py) puede eliminar filas, y lo hace marcando su transacción con
-- SET LOCAL empresas.purga = 'on'. La auditoría no admite excepciones: el borrado queda registrado.
SET search_path TO empresas, public;

CREATE OR REPLACE FUNCTION append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' AND TG_TABLE_NAME <> 'auditoria'
     AND coalesce(current_setting('empresas.purga', true), '') = 'on' THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'La tabla % es append-only', TG_TABLE_NAME;
END $$;

-- Índices para que el borrado no recorra tablas enteras
CREATE INDEX IF NOT EXISTS telefono_vinculo_fuente_idx ON telefono_vinculo(fuente_tipo, fuente_id);
CREATE INDEX IF NOT EXISTS telefono_vinculo_historia_fuente_idx ON telefono_vinculo_historia(fuente_tipo, fuente_id);
CREATE INDEX IF NOT EXISTS sav_fila_item_idx ON sav_fila(item_id);
CREATE INDEX IF NOT EXISTS marco_snapshot_item_empresa_idx ON marco_snapshot_item(empresa_id);
CREATE INDEX IF NOT EXISTS empresa_carga_alta_idx ON empresa(carga_alta_id);
CREATE INDEX IF NOT EXISTS empresa_fusionada_en_idx ON empresa(fusionada_en);
