-- 0022_muestras_sistematico.sql — SPEC_muestras_marco_excel_sistematico (D56)
-- Sorteo sistemático por CIIU: el CIIU congelado en el snapshot (para «Verificar reproducibilidad») y el titular
-- al que reemplaza cada reemplazo (el vecino en la lista). Columnas nuevas, nulas: no se reescribe ningún dato.
SET search_path TO empresas, public;

ALTER TABLE marco_snapshot_item ADD COLUMN IF NOT EXISTS ciiu text;
-- true en los snapshots que congelaron el CIIU (todos los sorteos desde D56, con los dos métodos)
ALTER TABLE marco_snapshot ADD COLUMN IF NOT EXISTS ciiu_congelado boolean NOT NULL DEFAULT false;
-- empresa_id del titular al que reemplaza (sorteo sistemático); nula en titulares y en el sorteo aleatorio
ALTER TABLE muestra_item ADD COLUMN IF NOT EXISTS reemplaza_a int;
