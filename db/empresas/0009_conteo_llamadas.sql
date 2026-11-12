-- 0009_conteo_llamadas.sql — Conteo de llamadas del CDR y lista de empresas llamadas
-- (SPEC_conteo_llamadas_cdr_y_rendimiento_por_origen, R2 y R4). Compatible hacia atrás.
SET search_path TO empresas, public;

-- Las llamadas a empresas de cada corrida del job: los intentos nuevos y los que ya estaban
-- registrados (un reproceso los vuelve a encontrar). Con esto la corrida informa teléfonos y
-- empresas distintas, el embudo, y «Exportar empresas» da exactamente sus empresas aunque los
-- intentos se hayan guardado en una corrida anterior (su lote_id es el de la primera vez).
CREATE TABLE IF NOT EXISTS cdr_corrida_intento (
  corrida_id int    NOT NULL REFERENCES cdr_corrida(id) ON DELETE CASCADE,
  intento_id bigint NOT NULL REFERENCES intento(id) ON DELETE CASCADE,
  PRIMARY KEY (corrida_id, intento_id)
);
CREATE INDEX IF NOT EXISTS cdr_corrida_intento_intento_idx ON cdr_corrida_intento(intento_id);

-- Corridas anteriores a este cambio: sus intentos se encuentran por el lote
CREATE INDEX IF NOT EXISTS intento_lote_idx ON intento(lote_id);
CREATE INDEX IF NOT EXISTS cdr_lote_corrida_idx ON cdr_lote(corrida_id);
